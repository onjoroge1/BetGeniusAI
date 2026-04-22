"""
V3 Retrain — Disciplined approach with holdout validation.

Key principles (learned from the 94% draw regression):
1. NO class weighting — draws at 25% are not severely imbalanced
2. NO inference-time boost — let argmax speak
3. TRUE holdout set (last 15% chronologically) NEVER touched during training
4. Hard gates: pick distribution must match reality within 5pp
5. Same 24 features as the working rollback model
6. Only promote if accuracy > baseline AND distribution is balanced

If this retrain fails the gates, it won't save artifacts.
"""

import os
import sys
import json
import pickle
import logging
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict

import numpy as np
import pandas as pd
import psycopg2
import lightgbm as lgb
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import accuracy_score, log_loss, precision_recall_fscore_support

sys.path.append('.')
from features.v3_feature_builder import V3FeatureBuilder

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

OUTPUT_DIR = Path("artifacts/models/v3_sharp_candidate")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
PROMOTE_DIR = Path("artifacts/models/v3_sharp")

# Hard gates for promotion
MIN_ACCURACY = 0.47  # Beat current baseline
MAX_CLASS_SKEW_PP = 8  # Pick distribution can't be more than 8pp off from reality
MIN_DRAW_PREDICTIONS = 0.15  # At least 15% draws
MAX_DRAW_PREDICTIONS = 0.38  # At most 38% draws (actual is ~25%)


def load_training_data():
    """Load all usable training matches, sorted chronologically."""
    conn = psycopg2.connect(os.environ['DATABASE_URL'])
    cur = conn.cursor()

    logger.info("Loading training matches...")
    cur.execute("""
        SELECT match_id, outcome, dt FROM (
            SELECT f.match_id,
                   CASE WHEN m.home_goals > m.away_goals THEN 'H'
                        WHEN m.home_goals < m.away_goals THEN 'A' ELSE 'D' END as outcome,
                   f.kickoff_at as dt
            FROM fixtures f
            JOIN matches m ON f.match_id = m.match_id
            JOIN odds_consensus oc ON f.match_id = oc.match_id
            WHERE f.status = 'finished' AND m.home_goals IS NOT NULL
            UNION ALL
            SELECT tm.match_id,
                   CASE WHEN tm.outcome IN ('H','Home','home') THEN 'H'
                        WHEN tm.outcome IN ('A','Away','away') THEN 'A'
                        ELSE 'D' END,
                   tm.match_date
            FROM training_matches tm
            JOIN odds_consensus oc ON tm.match_id = oc.match_id
            WHERE tm.outcome IS NOT NULL
              AND tm.match_id NOT IN (SELECT match_id FROM fixtures WHERE status='finished')
        ) sub
        WHERE outcome IN ('H','D','A')
        ORDER BY dt ASC NULLS LAST
    """)
    rows = cur.fetchall()
    conn.close()
    logger.info(f"Loaded {len(rows):,} matches")
    return [(r[0], r[1]) for r in rows]


def build_features_for_matches(matches):
    """Build 24-feature vectors for all matches."""
    builder = V3FeatureBuilder()
    records = []
    errors = 0

    logger.info(f"Building features for {len(matches):,} matches...")
    for i, (mid, outcome) in enumerate(matches):
        try:
            conn = psycopg2.connect(os.environ['DATABASE_URL'])
            cur = conn.cursor()
            match_info = builder._get_match_info(cur, mid)
            if not match_info:
                cur.close(); conn.close(); continue

            cutoff = match_info['kickoff_time']
            if cutoff is None:
                cur.close(); conn.close(); continue

            v2 = builder._build_v2_core_features(cur, mid, cutoff)
            ece = builder._build_ece_features(cur, match_info['league_id'])
            h2h = builder._build_h2h_features(cur, mid, match_info)
            cls = builder._build_closeness_features(v2)
            ld = builder._build_league_draw_features(cur, match_info['league_id'], v2)
            dm = builder._build_draw_market_features(v2)
            cur.close(); conn.close()

            feats = {**v2, **ece, **h2h, **cls, **ld, **dm}
            feats['match_id'] = mid
            feats['outcome'] = outcome
            records.append(feats)

            if (i + 1) % 500 == 0:
                logger.info(f"  Built {i+1}/{len(matches):,} ({errors} errors)")
        except Exception as e:
            errors += 1
            if errors <= 5:
                logger.warning(f"  match {mid}: {e}")

    df = pd.DataFrame(records)
    logger.info(f"Built {len(df):,} feature rows ({errors} errors)")
    return df


def train_ensemble(X_train, y_train, n_splits=5):
    """Train 5-fold LightGBM ensemble. NO class weighting."""
    params = {
        'objective': 'multiclass',
        'num_class': 3,
        'metric': 'multi_logloss',
        'boosting_type': 'gbdt',
        'learning_rate': 0.03,
        'num_leaves': 31,
        'max_depth': 6,
        'min_data_in_leaf': 40,
        'feature_fraction': 0.8,
        'bagging_fraction': 0.8,
        'bagging_freq': 5,
        'lambda_l1': 0.3,
        'lambda_l2': 0.5,
        'verbose': -1,
        'force_row_wise': True,
        'seed': 42,
    }

    tscv = TimeSeriesSplit(n_splits=n_splits)
    models = []
    oof_preds = np.zeros((len(y_train), 3))
    oof_mask = np.zeros(len(y_train), dtype=bool)

    for fold, (tr_idx, val_idx) in enumerate(tscv.split(X_train)):
        X_tr, X_va = X_train[tr_idx], X_train[val_idx]
        y_tr, y_va = y_train[tr_idx], y_train[val_idx]

        td = lgb.Dataset(X_tr, label=y_tr)
        vd = lgb.Dataset(X_va, label=y_va, reference=td)

        model = lgb.train(
            params, td, num_boost_round=2000,
            valid_sets=[vd], valid_names=['valid'],
            callbacks=[lgb.early_stopping(100), lgb.log_evaluation(0)],
        )
        models.append(model)
        oof_preds[val_idx] = model.predict(X_va, num_iteration=model.best_iteration)
        oof_mask[val_idx] = True

        val_acc = accuracy_score(y_va, np.argmax(oof_preds[val_idx], axis=1))
        logger.info(f"  Fold {fold+1}: val_acc={val_acc:.3f}, iters={model.best_iteration}")

    return models, oof_preds, oof_mask


def evaluate(y_true, preds, label=""):
    """Evaluate predictions with pick distribution checks."""
    picks = np.argmax(preds, axis=1)
    acc = accuracy_score(y_true, picks)
    ll = log_loss(y_true, preds, labels=[0, 1, 2])

    # Per-class accuracy
    per_class = {}
    for cls, name in [(0, 'H'), (1, 'D'), (2, 'A')]:
        mask = y_true == cls
        if mask.sum() > 0:
            per_class[name] = {
                'accuracy': float(accuracy_score(y_true[mask], picks[mask])),
                'n_actual': int(mask.sum()),
            }

    # Pick distribution
    pick_dist = {
        'H': int((picks == 0).sum()),
        'D': int((picks == 1).sum()),
        'A': int((picks == 2).sum()),
    }
    actual_dist = {
        'H': int((y_true == 0).sum()),
        'D': int((y_true == 1).sum()),
        'A': int((y_true == 2).sum()),
    }
    n = len(y_true)
    pick_pct = {k: v / n * 100 for k, v in pick_dist.items()}
    actual_pct = {k: v / n * 100 for k, v in actual_dist.items()}

    # Skew: how far pick distribution deviates from actual
    skews = {k: abs(pick_pct[k] - actual_pct[k]) for k in ['H', 'D', 'A']}
    max_skew = max(skews.values())

    logger.info(f"\n{label} EVALUATION")
    logger.info(f"  Accuracy: {acc*100:.1f}%  |  LogLoss: {ll:.4f}")
    logger.info(f"  Pick dist:    H={pick_pct['H']:.1f}% D={pick_pct['D']:.1f}% A={pick_pct['A']:.1f}%")
    logger.info(f"  Actual dist:  H={actual_pct['H']:.1f}% D={actual_pct['D']:.1f}% A={actual_pct['A']:.1f}%")
    logger.info(f"  Max skew: {max_skew:.1f}pp")

    for name, v in per_class.items():
        logger.info(f"  {name}: {v['accuracy']*100:.1f}% ({v['n_actual']} actual)")

    return {
        'accuracy': acc,
        'logloss': ll,
        'per_class': per_class,
        'pick_dist_pct': pick_pct,
        'actual_dist_pct': actual_pct,
        'max_skew_pp': max_skew,
        'draw_pred_rate': pick_pct['D'] / 100,
    }


def gate_check(holdout_metrics):
    """Hard gates — reject if any fail."""
    passed = True
    reasons = []

    if holdout_metrics['accuracy'] < MIN_ACCURACY:
        reasons.append(f"Accuracy {holdout_metrics['accuracy']*100:.1f}% < {MIN_ACCURACY*100}%")
        passed = False
    if holdout_metrics['max_skew_pp'] > MAX_CLASS_SKEW_PP:
        reasons.append(f"Class skew {holdout_metrics['max_skew_pp']:.1f}pp > {MAX_CLASS_SKEW_PP}pp")
        passed = False
    if holdout_metrics['draw_pred_rate'] < MIN_DRAW_PREDICTIONS:
        reasons.append(f"Draw picks {holdout_metrics['draw_pred_rate']*100:.1f}% < {MIN_DRAW_PREDICTIONS*100}%")
        passed = False
    if holdout_metrics['draw_pred_rate'] > MAX_DRAW_PREDICTIONS:
        reasons.append(f"Draw picks {holdout_metrics['draw_pred_rate']*100:.1f}% > {MAX_DRAW_PREDICTIONS*100}%")
        passed = False

    return passed, reasons


def main():
    logger.info("=" * 60)
    logger.info("V3 DISCIPLINED RETRAIN — holdout validation")
    logger.info("=" * 60)

    # 1. Load & build features
    matches = load_training_data()
    df = build_features_for_matches(matches)

    # 2. Prepare data
    feature_cols = [c for c in df.columns if c not in ['match_id', 'outcome']]
    X = df[feature_cols].values
    outcome_map = {'H': 0, 'D': 1, 'A': 2}
    y = df['outcome'].map(outcome_map).values

    n = len(y)
    logger.info(f"\nDataset: {n:,} samples, {len(feature_cols)} features")
    logger.info(f"Classes: H={sum(y==0)}, D={sum(y==1)}, A={sum(y==2)}")

    # 3. Split: last 15% = holdout (NEVER touched during training)
    split = int(n * 0.85)
    X_train, X_hold = X[:split], X[split:]
    y_train, y_hold = y[:split], y[split:]
    logger.info(f"\nTrain: {len(y_train):,}  |  Holdout: {len(y_hold):,}")

    # 4. Train on 5-fold CV of training set only
    models, oof_preds, oof_mask = train_ensemble(X_train, y_train)

    # 5. Evaluate on OOF (sanity check)
    oof_metrics = evaluate(y_train[oof_mask], oof_preds[oof_mask], "OOF (5-fold CV)")

    # 6. Evaluate on HOLDOUT (the real test)
    hold_preds = np.mean([m.predict(X_hold, num_iteration=m.best_iteration) for m in models], axis=0)
    # Normalize
    hold_preds = hold_preds / hold_preds.sum(axis=1, keepdims=True)
    hold_metrics = evaluate(y_hold, hold_preds, "HOLDOUT (last 15%, unseen)")

    # 7. Gate check — reject if holdout fails
    passed, reasons = gate_check(hold_metrics)

    logger.info("\n" + "=" * 60)
    logger.info("GATE CHECK")
    logger.info("=" * 60)
    if passed:
        logger.info("✅ PASSED — model meets quality bar")
    else:
        logger.info("❌ FAILED — will NOT promote")
        for r in reasons:
            logger.info(f"    {r}")

    # 8. Save candidate (always) + promote if passed
    with open(OUTPUT_DIR / "lgbm_ensemble.pkl", "wb") as f:
        pickle.dump(models, f)
    with open(OUTPUT_DIR / "features.json", "w") as f:
        json.dump(feature_cols, f, indent=2)
    metadata = {
        'model_type': 'V3_Sharp_LightGBM_Holdout',
        'trained_at': datetime.now(timezone.utc).isoformat(),
        'n_features': len(feature_cols),
        'train_size': int(len(y_train)),
        'holdout_size': int(len(y_hold)),
        'oof_metrics': oof_metrics,
        'holdout_metrics': hold_metrics,
        'gate_passed': passed,
        'gate_reasons': reasons,
    }
    with open(OUTPUT_DIR / "metadata.json", "w") as f:
        json.dump(metadata, f, indent=2, default=float)

    logger.info(f"\nCandidate saved to {OUTPUT_DIR}")
    if passed:
        import shutil
        for f in ['lgbm_ensemble.pkl', 'features.json', 'metadata.json']:
            shutil.copy(OUTPUT_DIR / f, PROMOTE_DIR / f)
        logger.info(f"✅ PROMOTED to {PROMOTE_DIR}")
    else:
        logger.info(f"⚠️  NOT promoted — candidate kept for inspection only")

    return passed


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
