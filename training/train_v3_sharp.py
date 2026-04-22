"""
V3 LightGBM Training Script - Enhanced Draw Prediction

Trains a V3 model using 24 features (pruned from 36, enhanced for draws):
- V2 Core Features (11): Market probabilities, dispersion, volatility
- League ECE Features (3): Expected Calibration Error, tier weights
- H2H Draw Features (2): Historical draw rate between teams
- Match Closeness (4): Prob gap, favourite strength, competitiveness
- League Draw Context (2): League draw rate, deviation from average
- Draw Market Structure (2): Bookmaker disagreement on draws

Improvements over v1:
- Class-weighted training (inverse frequency) to address draw imbalance
- Expanded training window (2024-07-01 vs 2025-10-01) for more samples
- Tuned hyperparameters for small-data regime
- Draw-specific evaluation metrics (precision, recall, per-class accuracy)
- np.nan for missing features (LightGBM handles natively)
- Pruned 20 dead features (sharp, injury, timing, drift)

Usage:
    python training/train_v3_sharp.py
"""

import os
import sys
import json
import pickle
import logging
import numpy as np
import pandas as pd
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Tuple

import psycopg2
import lightgbm as lgb
from sklearn.model_selection import TimeSeriesSplit

sys.path.append('.')
from features.v3_feature_builder import V3FeatureBuilder

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

OUTPUT_DIR = Path("artifacts/models/v3_sharp")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Training window — expanded from 2025-10-01 to get more samples
TRAINING_START_DATE = '2024-07-01'


def get_trainable_matches(min_sharp_odds: int = 0) -> List[Tuple[int, str]]:
    """
    Get matches suitable for V3 training from BOTH data sources:
    1. fixtures + matches + odds_consensus (original pipeline)
    2. training_matches + odds_consensus (8x more data)

    Requirements:
    - Known outcome (H/D/A)
    - Has odds_consensus data (for base features)
    """
    conn = psycopg2.connect(os.getenv('DATABASE_URL'))
    cursor = conn.cursor()

    # Source 1: fixtures + matches (original)
    cursor.execute("""
        SELECT
            f.match_id,
            CASE
                WHEN m.home_goals > m.away_goals THEN 'H'
                WHEN m.home_goals < m.away_goals THEN 'A'
                ELSE 'D'
            END as outcome,
            f.kickoff_at as sort_date
        FROM fixtures f
        JOIN matches m ON f.match_id = m.match_id
        JOIN odds_consensus oc ON f.match_id = oc.match_id
        WHERE f.status = 'finished'
          AND m.home_goals IS NOT NULL
          AND m.away_goals IS NOT NULL
          AND oc.ph_cons IS NOT NULL
    """)
    source1 = {row[0]: (row[0], row[1], row[2]) for row in cursor.fetchall()}
    logger.info(f"Source 1 (fixtures+matches): {len(source1):,} matches")

    # Source 2: training_matches (much larger, includes historical)
    cursor.execute("""
        SELECT DISTINCT ON (tm.match_id)
            tm.match_id,
            CASE
                WHEN tm.outcome IN ('H', 'Home') THEN 'H'
                WHEN tm.outcome IN ('A', 'Away') THEN 'A'
                WHEN tm.outcome IN ('D', 'Draw') THEN 'D'
                ELSE NULL
            END as outcome,
            tm.match_date as sort_date
        FROM training_matches tm
        JOIN odds_consensus oc ON tm.match_id = oc.match_id
        WHERE tm.outcome IS NOT NULL
          AND oc.ph_cons IS NOT NULL
        ORDER BY tm.match_id, tm.match_date
    """)
    source2_new = 0
    for row in cursor.fetchall():
        mid, outcome, sort_date = row
        if outcome and mid not in source1:
            source1[mid] = (mid, outcome, sort_date)
            source2_new += 1
    logger.info(f"Source 2 (training_matches): +{source2_new:,} new matches")

    cursor.close()
    conn.close()

    # Sort by date and return (normalize dates to strings for safe comparison)
    from datetime import datetime as _dt
    def _sort_key(x):
        d = x[2]
        if d is None:
            return '2000-01-01'
        if isinstance(d, str):
            return d
        return d.isoformat() if hasattr(d, 'isoformat') else str(d)

    all_matches = sorted(source1.values(), key=_sort_key)
    logger.info(f"Combined: {len(all_matches):,} total trainable matches")

    return [(row[0], row[1]) for row in all_matches]


def build_training_dataset(matches: List[Tuple[int, str]], cutoff_hours: float = 1.0) -> pd.DataFrame:
    """Build training dataset with V3 features — reuses a single DB connection per match for speed"""
    import psycopg2

    builder = V3FeatureBuilder()
    records = []
    errors = 0

    logger.info(f"Building features for {len(matches)} matches...")

    for i, (match_id, outcome) in enumerate(matches):
        try:
            conn = psycopg2.connect(os.getenv('DATABASE_URL'))
            cursor = conn.cursor()

            match_info = builder._get_match_info(cursor, match_id)
            if not match_info:
                cursor.close()
                conn.close()
                continue

            cutoff_time = match_info['kickoff_time']
            if cutoff_time is None:
                cursor.close()
                conn.close()
                continue

            v2_f = builder._build_v2_core_features(cursor, match_id, cutoff_time)
            ece_f = builder._build_ece_features(cursor, match_info['league_id'])
            h2h_f = builder._build_h2h_features(cursor, match_id, match_info)
            closeness_f = builder._build_closeness_features(v2_f)
            league_draw_f = builder._build_league_draw_features(cursor, match_info['league_id'], v2_f)
            draw_market_f = builder._build_draw_market_features(v2_f)
            form_f = builder._build_form_features(cursor, match_info, cutoff_time) if builder.FORM_FEATURE_NAMES else {}

            cursor.close()
            conn.close()

            features = {**v2_f, **ece_f, **h2h_f, **closeness_f,
                        **league_draw_f, **draw_market_f, **form_f}
            features['match_id'] = match_id
            features['outcome'] = outcome
            records.append(features)

            if (i + 1) % 100 == 0:
                logger.info(f"  Progress: {i+1}/{len(matches)} matches (errors: {errors})")

        except Exception as e:
            errors += 1
            try:
                cursor.close()
                conn.close()
            except Exception:
                pass
            if errors <= 10:
                logger.warning(f"  Skip match {match_id}: {e}")
            continue

    if not records:
        raise ValueError("No training data could be built")

    df = pd.DataFrame(records)
    logger.info(f"Built {len(df)} training samples with {len(df.columns)} columns ({errors} skipped)")

    return df


def compute_sample_weights(y: np.ndarray) -> np.ndarray:
    """
    Compute inverse-frequency class weights to address draw imbalance.
    Draws (~27%) get ~1.2x weight, Home (~45%) gets ~0.74x weight.
    """
    class_counts = np.bincount(y, minlength=3)
    total = len(y)
    # Inverse frequency weighting: total / (n_classes * count_per_class)
    class_weights = total / (3.0 * class_counts.clip(min=1))

    logger.info(f"Class weights: H={class_weights[0]:.3f}, D={class_weights[1]:.3f}, A={class_weights[2]:.3f}")

    sample_weights = np.array([class_weights[label] for label in y])
    return sample_weights


def train_v3_model(df: pd.DataFrame, n_splits: int = 5) -> Dict:
    """
    Train V3 LightGBM with time-series cross-validation and class weighting
    """

    feature_cols = [c for c in df.columns if c not in ['match_id', 'outcome']]
    X = df[feature_cols].values

    outcome_map = {'H': 0, 'D': 1, 'A': 2}
    y = df['outcome'].map(outcome_map).values

    logger.info(f"Training with {len(feature_cols)} features, {len(y)} samples")
    logger.info(f"Class distribution: H={sum(y==0)} ({sum(y==0)/len(y)*100:.1f}%), "
                f"D={sum(y==1)} ({sum(y==1)/len(y)*100:.1f}%), "
                f"A={sum(y==2)} ({sum(y==2)/len(y)*100:.1f}%)")

    # Compute class-weighted sample weights
    sample_weights = compute_sample_weights(y)

    # Tuned hyperparameters for better generalization on moderate data
    params = {
        'objective': 'multiclass',
        'num_class': 3,
        'metric': 'multi_logloss',
        'boosting_type': 'gbdt',
        'learning_rate': 0.02,          # Slower learning for better generalization
        'num_leaves': 20,               # Reduced from 31 — prevent overfit
        'max_depth': 5,                 # Reduced from 6
        'min_data_in_leaf': 30,         # Increased from 20 — more stable leaf predictions
        'feature_fraction': 0.7,        # Reduced from 0.8
        'bagging_fraction': 0.7,        # Reduced from 0.8
        'bagging_freq': 3,              # More frequent bagging
        'lambda_l1': 0.5,              # Stronger L1 regularization
        'lambda_l2': 1.0,              # Stronger L2 regularization
        'verbose': -1,
        'force_row_wise': True,
        'seed': 42
    }

    tscv = TimeSeriesSplit(n_splits=n_splits)
    models = []
    oof_preds = np.zeros((len(y), 3))
    oof_mask = np.zeros(len(y), dtype=bool)

    for fold, (train_idx, val_idx) in enumerate(tscv.split(X)):
        logger.info(f"Fold {fold+1}/{n_splits}: train={len(train_idx)}, val={len(val_idx)}")

        X_train, X_val = X[train_idx], X[val_idx]
        y_train, y_val = y[train_idx], y[val_idx]
        w_train = sample_weights[train_idx]

        # Pass sample weights to LightGBM
        train_data = lgb.Dataset(X_train, label=y_train, weight=w_train)
        val_data = lgb.Dataset(X_val, label=y_val, reference=train_data)

        model = lgb.train(
            params,
            train_data,
            num_boost_round=2000,
            valid_sets=[train_data, val_data],
            valid_names=['train', 'valid'],
            callbacks=[
                lgb.early_stopping(stopping_rounds=100),
                lgb.log_evaluation(period=200)
            ]
        )

        models.append(model)

        val_preds = model.predict(X_val, num_iteration=model.best_iteration)
        oof_preds[val_idx] = val_preds
        oof_mask[val_idx] = True

    valid_preds = oof_preds[oof_mask]
    valid_y = y[oof_mask]

    predicted_classes = np.argmax(valid_preds, axis=1)
    accuracy = np.mean(predicted_classes == valid_y)

    logloss = -np.mean([
        np.log(max(valid_preds[i, valid_y[i]], 1e-15))
        for i in range(len(valid_y))
    ])

    brier = np.mean([
        sum((valid_preds[i, c] - (1 if c == valid_y[i] else 0))**2 for c in range(3))
        for i in range(len(valid_y))
    ])

    logger.info("=" * 60)
    logger.info("V3 MODEL RESULTS")
    logger.info("=" * 60)
    logger.info(f"3-way Accuracy: {accuracy*100:.2f}%")
    logger.info(f"LogLoss: {logloss:.4f}")
    logger.info(f"Brier Score: {brier:.4f}")

    # === DRAW-SPECIFIC EVALUATION ===
    logger.info("\n--- Per-Class Accuracy ---")
    class_labels = {0: 'Home', 1: 'Draw', 2: 'Away'}
    per_class_acc = {}
    for cls, label in class_labels.items():
        cls_mask = valid_y == cls
        cls_n = cls_mask.sum()
        if cls_n > 0:
            cls_acc = np.mean(predicted_classes[cls_mask] == valid_y[cls_mask])
            per_class_acc[label] = {'accuracy': cls_acc, 'n': int(cls_n)}
            logger.info(f"  {label}: {cls_acc*100:.1f}% ({cls_n} samples)")
        else:
            per_class_acc[label] = {'accuracy': 0.0, 'n': 0}
            logger.info(f"  {label}: N/A (0 samples)")

    # Draw precision and recall
    draw_predicted = predicted_classes == 1
    draw_actual = valid_y == 1
    draw_pred_count = draw_predicted.sum()
    draw_actual_count = draw_actual.sum()
    draw_correct = (draw_predicted & draw_actual).sum()

    draw_precision = draw_correct / max(draw_pred_count, 1)
    draw_recall = draw_correct / max(draw_actual_count, 1)
    draw_f1 = 2 * draw_precision * draw_recall / max(draw_precision + draw_recall, 1e-10)

    logger.info(f"\n--- Draw Metrics ---")
    logger.info(f"  Draw Predictions Made: {draw_pred_count} / {len(valid_y)} ({draw_pred_count/len(valid_y)*100:.1f}%)")
    logger.info(f"  Draw Precision: {draw_precision*100:.1f}%")
    logger.info(f"  Draw Recall: {draw_recall*100:.1f}%")
    logger.info(f"  Draw F1: {draw_f1*100:.1f}%")

    # Feature importance
    feature_importance = pd.DataFrame({
        'feature': feature_cols,
        'importance': np.mean([m.feature_importance(importance_type='gain') for m in models], axis=0)
    }).sort_values('importance', ascending=False)

    logger.info(f"\nTop 15 Features:")
    for _, row in feature_importance.head(15).iterrows():
        logger.info(f"  {row['feature']}: {row['importance']:.2f}")

    # Check for zero-importance features
    zero_imp = feature_importance[feature_importance['importance'] == 0.0]
    if len(zero_imp) > 0:
        logger.warning(f"\n⚠️  {len(zero_imp)} features with ZERO importance:")
        for _, row in zero_imp.iterrows():
            logger.warning(f"  {row['feature']}")

    return {
        'models': models,
        'feature_cols': feature_cols,
        'metrics': {
            'accuracy_3way': accuracy,
            'logloss': logloss,
            'brier_score': brier,
            'n_samples': len(valid_y),
            'n_folds': n_splits,
            'per_class_accuracy': per_class_acc,
            'draw_precision': draw_precision,
            'draw_recall': draw_recall,
            'draw_f1': draw_f1,
            'draw_predictions_made': int(draw_pred_count),
        },
        'feature_importance': feature_importance.to_dict('records')
    }


def save_model(result: Dict):
    """Save trained V3 model artifacts"""

    with open(OUTPUT_DIR / "lgbm_ensemble.pkl", "wb") as f:
        pickle.dump(result['models'], f)

    with open(OUTPUT_DIR / "features.json", "w") as f:
        json.dump(result['feature_cols'], f, indent=2)

    metadata = {
        'model_type': 'V3_Sharp_LightGBM_DrawEnhanced',
        'trained_at': datetime.now(timezone.utc).isoformat(),
        'training_window_start': TRAINING_START_DATE,
        'n_features': len(result['feature_cols']),
        'improvements': [
            'Pruned 20 dead features (sharp, injury, timing, drift)',
            'Added 13 draw-specific features (closeness, league draw, market structure, form)',
            'Class-weighted training (inverse frequency)',
            'np.nan for missing features (LightGBM native handling)',
            'Tuned hyperparams for small-data regime',
            'Expanded training window from 2025-10-01 to 2024-07-01',
        ],
        'oof_metrics': result['metrics'],
        'feature_importance': result['feature_importance']
    }

    with open(OUTPUT_DIR / "metadata.json", "w") as f:
        json.dump(metadata, f, indent=2)

    logger.info(f"\n✅ V3 model saved to {OUTPUT_DIR}")


def main():
    logger.info("=" * 60)
    logger.info("V3 SHARP BOOK INTELLIGENCE MODEL TRAINING")
    logger.info("Draw-Enhanced Edition (24 features)")
    logger.info("=" * 60)

    matches = get_trainable_matches()
    logger.info(f"Found {len(matches)} trainable matches (from {TRAINING_START_DATE})")

    if len(matches) < 100:
        logger.warning("⚠️  Low sample count - results may be unreliable")

    # Show outcome distribution
    outcomes = [m[1] for m in matches]
    logger.info(f"Outcome distribution: H={outcomes.count('H')}, D={outcomes.count('D')}, A={outcomes.count('A')}")

    df = build_training_dataset(matches)

    # Feature population report (NaN-aware)
    logger.info("\nFeature Population:")
    feature_cols = [c for c in df.columns if c not in ['match_id', 'outcome']]
    for col in feature_cols:
        non_null = df[col].notna().sum()
        pct = non_null / len(df) * 100
        status = "✅" if pct > 80 else "⚠️" if pct > 50 else "❌"
        logger.info(f"  {status} {col}: {pct:.1f}% populated ({non_null}/{len(df)})")

    result = train_v3_model(df)

    save_model(result)

    logger.info("\n" + "=" * 60)
    logger.info("TRAINING COMPLETE")
    logger.info("=" * 60)

    return result


if __name__ == "__main__":
    main()
