"""
V3 LightGBM Training Script - Sharp Book Intelligence Model

Trains a V3 model using 34 features including:
- V2 Odds Features (17): Market probabilities, dispersion, volatility, drift
- Sharp Book Features (4): Pinnacle/Betfair odds, soft vs sharp divergence
- League ECE Features (3): Expected Calibration Error, tier weights
- Injury Features (6): Player availability impact (when available)
- Timing Features (4): Market movement velocity, steam moves

Usage:
    python training/train_v3_sharp.py

Expected Results:
    - 3-way accuracy: 52-56% (target: beat V2's 49.5%)
    - LogLoss: < 1.02
    - Brier Score: < 0.21
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


def get_trainable_matches(min_sharp_odds: int = 0) -> List[Tuple[int, str]]:
    """
    Get matches suitable for V3 training
    
    Requirements:
    - Finished matches with known outcomes
    - Has odds_consensus data (for base features)
    - Optionally: has sharp book odds (min_sharp_odds threshold)
    """
    conn = psycopg2.connect(os.getenv('DATABASE_URL'))
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT 
            f.match_id,
            CASE 
                WHEN m.home_goals > m.away_goals THEN 'H'
                WHEN m.home_goals < m.away_goals THEN 'A'
                ELSE 'D'
            END as outcome,
            f.kickoff_at,
            f.league_id
        FROM fixtures f
        JOIN matches m ON f.match_id = m.match_id
        JOIN odds_consensus oc ON f.match_id = oc.match_id
        WHERE f.status = 'finished'
          AND m.home_goals IS NOT NULL
          AND m.away_goals IS NOT NULL
          AND f.kickoff_at >= '2025-10-01'
        ORDER BY f.kickoff_at
    """)
    
    matches = cursor.fetchall()
    cursor.close()
    conn.close()
    
    return [(row[0], row[1]) for row in matches]


def build_training_dataset(matches: List[Tuple[int, str]], cutoff_hours: float = 1.0) -> pd.DataFrame:
    """Build training dataset with V3 features"""
    
    builder = V3FeatureBuilder()
    records = []
    
    logger.info(f"Building features for {len(matches)} matches...")
    
    for i, (match_id, outcome) in enumerate(matches):
        try:
            features = builder.build_features(match_id)
            features['match_id'] = match_id
            features['outcome'] = outcome
            records.append(features)
            
            if (i + 1) % 50 == 0:
                logger.info(f"  Progress: {i+1}/{len(matches)} matches")
                
        except Exception as e:
            logger.warning(f"  Skip match {match_id}: {e}")
            continue
    
    if not records:
        raise ValueError("No training data could be built")
    
    df = pd.DataFrame(records)
    logger.info(f"Built {len(df)} training samples with {len(df.columns)} columns")
    
    return df


def train_v3_model(df: pd.DataFrame, n_splits: int = 5) -> Dict:
    """
    Train V3 LightGBM with time-series cross-validation
    """
    
    feature_cols = [c for c in df.columns if c not in ['match_id', 'outcome']]
    X = df[feature_cols].values
    
    outcome_map = {'H': 0, 'D': 1, 'A': 2}
    y = df['outcome'].map(outcome_map).values
    
    logger.info(f"Training with {len(feature_cols)} features, {len(y)} samples")
    logger.info(f"Class distribution: H={sum(y==0)}, D={sum(y==1)}, A={sum(y==2)}")
    
    params = {
        'objective': 'multiclass',
        'num_class': 3,
        'metric': 'multi_logloss',
        'boosting_type': 'gbdt',
        'learning_rate': 0.03,
        'num_leaves': 31,
        'max_depth': 6,
        'min_data_in_leaf': 20,
        'feature_fraction': 0.8,
        'bagging_fraction': 0.8,
        'bagging_freq': 5,
        'lambda_l1': 0.1,
        'lambda_l2': 0.1,
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
        
        train_data = lgb.Dataset(X_train, label=y_train)
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
    
    feature_importance = pd.DataFrame({
        'feature': feature_cols,
        'importance': np.mean([m.feature_importance(importance_type='gain') for m in models], axis=0)
    }).sort_values('importance', ascending=False)
    
    logger.info("\nTop 10 Features:")
    for _, row in feature_importance.head(10).iterrows():
        logger.info(f"  {row['feature']}: {row['importance']:.2f}")
    
    return {
        'models': models,
        'feature_cols': feature_cols,
        'metrics': {
            'accuracy_3way': accuracy,
            'logloss': logloss,
            'brier_score': brier,
            'n_samples': len(valid_y),
            'n_folds': n_splits
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
        'model_type': 'V3_Sharp_LightGBM',
        'trained_at': datetime.now(timezone.utc).isoformat(),
        'n_features': len(result['feature_cols']),
        'oof_metrics': result['metrics'],
        'feature_importance': result['feature_importance']
    }
    
    with open(OUTPUT_DIR / "metadata.json", "w") as f:
        json.dump(metadata, f, indent=2)
    
    logger.info(f"\n✅ V3 model saved to {OUTPUT_DIR}")


def main():
    logger.info("=" * 60)
    logger.info("V3 SHARP BOOK INTELLIGENCE MODEL TRAINING")
    logger.info("=" * 60)
    
    matches = get_trainable_matches()
    logger.info(f"Found {len(matches)} trainable matches")
    
    if len(matches) < 100:
        logger.warning("⚠️  Low sample count - results may be unreliable")
    
    df = build_training_dataset(matches)
    
    n_populated = (df.drop(['match_id', 'outcome'], axis=1) != 0).sum()
    logger.info("\nFeature Population:")
    for col, count in n_populated.items():
        pct = count / len(df) * 100
        logger.info(f"  {col}: {pct:.1f}%")
    
    result = train_v3_model(df)
    
    save_model(result)
    
    logger.info("\n" + "=" * 60)
    logger.info("TRAINING COMPLETE")
    logger.info("=" * 60)
    
    return result


if __name__ == "__main__":
    main()
