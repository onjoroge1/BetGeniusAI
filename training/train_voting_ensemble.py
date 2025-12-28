"""
Train Voting Ensemble - Combines Lite and Premium Models

The voting ensemble:
1. Lite Model: Trained on ALL matches using historical features (form, H2H, stats)
2. Premium Model: Trained on odds-rich matches using full features (including market data)

For predictions:
- If match has odds: Average both models' predictions (weighted by confidence)
- If match has no odds: Use lite model only

Usage:
    export LD_LIBRARY_PATH="$(gcc -print-file-name=libgomp.so | xargs dirname):$LD_LIBRARY_PATH"
    python training/train_voting_ensemble.py
"""

import os
import sys
import json
import pickle
import logging
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

import psycopg2
import lightgbm as lgb
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import log_loss, accuracy_score

sys.path.append('.')
from features.unified_v2_feature_builder import UnifiedV2FeatureBuilder

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

OUTPUT_DIR = Path("artifacts/models/voting_ensemble")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

LITE_FEATURES = (
    UnifiedV2FeatureBuilder.FORM_FEATURES +
    UnifiedV2FeatureBuilder.H2H_FEATURES +
    UnifiedV2FeatureBuilder.ADVANCED_STATS_FEATURES +
    UnifiedV2FeatureBuilder.CONTEXT_FEATURES +
    UnifiedV2FeatureBuilder.ECE_FEATURES +
    UnifiedV2FeatureBuilder.HISTORICAL_FLAGS
)


def get_all_matches() -> List[Tuple]:
    """Get all trainable matches"""
    conn = psycopg2.connect(os.getenv('DATABASE_URL'))
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT DISTINCT ON (tm.id)
            tm.id as training_match_id,
            tm.match_id as api_match_id,
            CASE 
                WHEN tm.outcome IN ('H', 'Home') THEN 'H'
                WHEN tm.outcome IN ('A', 'Away') THEN 'A'
                WHEN tm.outcome IN ('D', 'Draw') THEN 'D'
                ELSE tm.outcome
            END as outcome,
            tm.match_date as kickoff_at,
            EXISTS (
                SELECT 1 FROM odds_snapshots os 
                WHERE os.match_id = tm.match_id
                LIMIT 1
            ) as has_odds
        FROM training_matches tm
        WHERE tm.outcome IS NOT NULL
          AND tm.match_date >= '2020-01-01'
          AND (
              EXISTS (SELECT 1 FROM odds_snapshots os WHERE os.match_id = tm.match_id)
              OR
              EXISTS (SELECT 1 FROM historical_features hf WHERE hf.match_id = tm.id)
          )
        ORDER BY tm.id, tm.match_date
    """)
    
    matches = cursor.fetchall()
    cursor.close()
    conn.close()
    
    with_odds = sum(1 for m in matches if m[4])
    logger.info(f"Found {len(matches)} total matches ({with_odds} with odds)")
    return matches


def build_datasets(matches: List[Tuple]) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Build both lite and premium datasets"""
    
    builder = UnifiedV2FeatureBuilder()
    all_records = []
    skipped = 0
    
    logger.info(f"Building features for {len(matches)} matches...")
    
    for i, row in enumerate(matches):
        training_match_id, api_match_id, outcome, kickoff, has_odds = row
        
        try:
            features = builder.build_features(training_match_id, cutoff_time=kickoff)
            features['match_id'] = training_match_id
            features['outcome'] = outcome
            features['kickoff'] = kickoff
            features['has_odds_data'] = 1 if has_odds else 0
            all_records.append(features)
            
            if (i + 1) % 200 == 0:
                logger.info(f"  Progress: {i+1}/{len(matches)} ({len(all_records)} built)")
                
        except Exception as e:
            skipped += 1
            continue
    
    df_all = pd.DataFrame(all_records)
    logger.info(f"Built {len(df_all)} samples (skipped {skipped})")
    
    df_premium = df_all[df_all['has_odds_data'] == 1].copy()
    logger.info(f"Premium dataset: {len(df_premium)} samples with odds")
    
    return df_all, df_premium


def train_model(df: pd.DataFrame, feature_cols: List[str], model_name: str, n_splits: int = 5) -> Dict:
    """Train a single LightGBM model"""
    
    existing_cols = [c for c in feature_cols if c in df.columns]
    
    X = df[existing_cols].fillna(0).values
    outcome_map = {'H': 0, 'D': 1, 'A': 2}
    y = df['outcome'].map(outcome_map).values
    
    logger.info(f"\nTraining {model_name} with {len(existing_cols)} features, {len(y)} samples")
    
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
    
    n_splits = min(n_splits, len(y) // 50)
    if n_splits < 2:
        n_splits = 2
    
    gap_size = max(20, len(y) // 50)
    tscv = TimeSeriesSplit(n_splits=n_splits, gap=gap_size)
    
    models = []
    oof_preds = np.zeros((len(y), 3))
    oof_mask = np.zeros(len(y), dtype=bool)
    fold_metrics = []
    
    for fold, (train_idx, val_idx) in enumerate(tscv.split(X)):
        logger.info(f"Fold {fold + 1}/{n_splits}: Train={len(train_idx)}, Val={len(val_idx)}")
        
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
                lgb.log_evaluation(period=500)
            ]
        )
        
        val_preds = model.predict(X_val, num_iteration=model.best_iteration)
        oof_preds[val_idx] = val_preds
        oof_mask[val_idx] = True
        
        fold_acc = accuracy_score(y_val, np.argmax(val_preds, axis=1))
        fold_logloss = log_loss(y_val, val_preds)
        fold_metrics.append({'fold': fold+1, 'accuracy': fold_acc, 'logloss': fold_logloss})
        
        logger.info(f"  Fold {fold+1}: Acc={fold_acc:.3f}, LogLoss={fold_logloss:.4f}")
        models.append(model)
    
    y_valid = y[oof_mask]
    preds_valid = oof_preds[oof_mask]
    
    oof_accuracy = accuracy_score(y_valid, np.argmax(preds_valid, axis=1))
    oof_logloss = log_loss(y_valid, preds_valid)
    
    logger.info(f"\n{model_name} OOF: Accuracy={oof_accuracy:.3f}, LogLoss={oof_logloss:.4f}")
    
    feature_importance = []
    for i, col in enumerate(existing_cols):
        avg_importance = np.mean([m.feature_importance()[i] for m in models])
        feature_importance.append({'feature': col, 'importance': avg_importance})
    feature_importance.sort(key=lambda x: x['importance'], reverse=True)
    
    return {
        'models': models,
        'feature_cols': existing_cols,
        'oof_metrics': {'accuracy_3way': oof_accuracy, 'logloss': oof_logloss, 'n_samples': len(y_valid)},
        'fold_metrics': fold_metrics,
        'feature_importance': feature_importance,
        'params': params
    }


def save_voting_ensemble(lite_result: Dict, premium_result: Dict):
    """Save both models and voting config"""
    
    with open(OUTPUT_DIR / "lite_ensemble.pkl", "wb") as f:
        pickle.dump(lite_result['models'], f)
    
    with open(OUTPUT_DIR / "lite_features.json", "w") as f:
        json.dump(lite_result['feature_cols'], f, indent=2)
    
    with open(OUTPUT_DIR / "premium_ensemble.pkl", "wb") as f:
        pickle.dump(premium_result['models'], f)
    
    with open(OUTPUT_DIR / "premium_features.json", "w") as f:
        json.dump(premium_result['feature_cols'], f, indent=2)
    
    metadata = {
        'model_type': 'Voting_Ensemble',
        'trained_at': datetime.now(timezone.utc).isoformat(),
        'lite_model': {
            'n_features': len(lite_result['feature_cols']),
            'accuracy': lite_result['oof_metrics']['accuracy_3way'],
            'logloss': lite_result['oof_metrics']['logloss'],
            'n_samples': lite_result['oof_metrics']['n_samples']
        },
        'premium_model': {
            'n_features': len(premium_result['feature_cols']),
            'accuracy': premium_result['oof_metrics']['accuracy_3way'],
            'logloss': premium_result['oof_metrics']['logloss'],
            'n_samples': premium_result['oof_metrics']['n_samples']
        },
        'voting_strategy': 'weighted_average',
        'weights': {
            'lite': 0.4,
            'premium': 0.6
        }
    }
    
    with open(OUTPUT_DIR / "metadata.json", "w") as f:
        json.dump(metadata, f, indent=2)
    
    logger.info(f"\nVoting ensemble saved to {OUTPUT_DIR}/")


if __name__ == "__main__":
    logger.info("="*60)
    logger.info("VOTING ENSEMBLE TRAINING")
    logger.info("="*60)
    
    matches = get_all_matches()
    df_all, df_premium = build_datasets(matches)
    
    sparse = UnifiedV2FeatureBuilder.SPARSE_FEATURES
    lite_feature_cols = [f for f in LITE_FEATURES if f not in sparse]
    
    all_features = [c for c in df_all.columns if c not in ['match_id', 'outcome', 'kickoff', 'has_odds_data']]
    premium_feature_cols = [f for f in all_features if f not in sparse]
    
    logger.info("\n" + "="*60)
    logger.info("TRAINING LITE MODEL (All Matches, Historical Features)")
    logger.info("="*60)
    lite_result = train_model(df_all, lite_feature_cols, "LITE MODEL")
    
    logger.info("\n" + "="*60)
    logger.info("TRAINING PREMIUM MODEL (Odds Matches, Full Features)")
    logger.info("="*60)
    
    if len(df_premium) >= 500:
        premium_result = train_model(df_premium, premium_feature_cols, "PREMIUM MODEL")
    else:
        logger.warning(f"Not enough odds matches ({len(df_premium)}), using lite model for premium")
        premium_result = lite_result
    
    save_voting_ensemble(lite_result, premium_result)
    
    logger.info("\n" + "="*60)
    logger.info("VOTING ENSEMBLE TRAINING COMPLETE")
    logger.info("="*60)
    logger.info(f"Lite Model:    Accuracy={lite_result['oof_metrics']['accuracy_3way']*100:.1f}%")
    logger.info(f"Premium Model: Accuracy={premium_result['oof_metrics']['accuracy_3way']*100:.1f}%")
    logger.info("="*60)
