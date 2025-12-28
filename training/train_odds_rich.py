"""
Train Premium Model on Odds-Rich Matches Only

This trains the V2 model exclusively on matches that have odds data,
which should dramatically improve accuracy since market data is the strongest signal.

Usage:
    export LD_LIBRARY_PATH="$(gcc -print-file-name=libgomp.so | xargs dirname):$LD_LIBRARY_PATH"
    python training/train_odds_rich.py
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

OUTPUT_DIR = Path("artifacts/models/unified_v2_premium")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def get_odds_rich_matches() -> List[Tuple[int, int, str, datetime]]:
    """
    Get matches that have odds data from odds_snapshots
    
    Returns matches where we have collected actual betting odds.
    """
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
            tm.match_date as kickoff_at
        FROM training_matches tm
        WHERE tm.outcome IS NOT NULL
          AND tm.match_date >= '2024-01-01'
          AND EXISTS (
              SELECT 1 FROM odds_snapshots os 
              WHERE os.match_id = tm.match_id
              LIMIT 1
          )
        ORDER BY tm.id, tm.match_date
    """)
    
    matches = cursor.fetchall()
    cursor.close()
    conn.close()
    
    logger.info(f"Found {len(matches)} odds-rich matches for training")
    return matches


def build_training_dataset(matches: List[Tuple]) -> pd.DataFrame:
    """Build training dataset with unified V2 features for odds-rich matches"""
    
    builder = UnifiedV2FeatureBuilder()
    records = []
    skipped = 0
    
    logger.info(f"Building features for {len(matches)} odds-rich matches...")
    
    for i, row in enumerate(matches):
        training_match_id, api_match_id, outcome, kickoff = row
        
        try:
            features = builder.build_features(training_match_id, cutoff_time=kickoff)
            features['match_id'] = training_match_id
            features['outcome'] = outcome
            features['kickoff'] = kickoff
            records.append(features)
            
            if (i + 1) % 100 == 0:
                logger.info(f"  Progress: {i+1}/{len(matches)} ({len(records)} built, {skipped} skipped)")
                
        except Exception as e:
            skipped += 1
            if skipped <= 5:
                logger.warning(f"  Skip match {training_match_id}: {e}")
            continue
    
    if not records:
        raise ValueError("No training data could be built")
    
    df = pd.DataFrame(records)
    logger.info(f"Built {len(df)} training samples with {len(df.columns)} columns")
    
    feature_cols = [c for c in df.columns if c not in ['match_id', 'outcome', 'kickoff']]
    
    logger.info("\nFeature coverage (odds-rich matches):")
    for col in sorted(feature_cols):
        pct = (df[col] != 0).sum() / len(df) * 100
        status = "✓" if pct > 50 else "⚠️" if pct > 10 else "❌"
        if pct < 100:
            logger.info(f"  {status} {col}: {pct:.1f}%")
    
    return df


def train_premium_model(df: pd.DataFrame, n_splits: int = 5) -> Dict:
    """Train premium model on odds-rich matches with all features"""
    
    all_feature_cols = [c for c in df.columns if c not in ['match_id', 'outcome', 'kickoff']]
    
    sparse_features = UnifiedV2FeatureBuilder.SPARSE_FEATURES
    feature_cols = [c for c in all_feature_cols if c not in sparse_features]
    
    X = df[feature_cols].fillna(0).values
    
    outcome_map = {'H': 0, 'D': 1, 'A': 2}
    y = df['outcome'].map(outcome_map).values
    
    logger.info(f"\nTraining PREMIUM model with {len(feature_cols)} features, {len(y)} samples")
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
    
    n_splits = min(n_splits, len(y) // 50)
    if n_splits < 2:
        n_splits = 2
    
    gap_size = max(20, len(y) // 50)
    tscv = TimeSeriesSplit(n_splits=n_splits, gap=gap_size)
    logger.info(f"Using TimeSeriesSplit with gap={gap_size}")
    
    models = []
    oof_preds = np.zeros((len(y), 3))
    oof_mask = np.zeros(len(y), dtype=bool)
    fold_metrics = []
    
    for fold, (train_idx, val_idx) in enumerate(tscv.split(X)):
        logger.info(f"\n--- Fold {fold + 1}/{n_splits} ---")
        logger.info(f"Train: {len(train_idx)} samples, Val: {len(val_idx)} samples")
        
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
        
        val_preds = model.predict(X_val, num_iteration=model.best_iteration)
        oof_preds[val_idx] = val_preds
        oof_mask[val_idx] = True
        
        val_pred_labels = np.argmax(val_preds, axis=1)
        fold_acc = accuracy_score(y_val, val_pred_labels)
        fold_logloss = log_loss(y_val, val_preds)
        
        fold_metrics.append({
            'fold': fold + 1,
            'accuracy': fold_acc,
            'logloss': fold_logloss,
            'best_iteration': model.best_iteration
        })
        
        logger.info(f"Fold {fold + 1}: Accuracy={fold_acc:.3f}, LogLoss={fold_logloss:.4f}")
        models.append(model)
    
    y_valid = y[oof_mask]
    preds_valid = oof_preds[oof_mask]
    
    oof_accuracy = accuracy_score(y_valid, np.argmax(preds_valid, axis=1))
    oof_logloss = log_loss(y_valid, preds_valid)
    
    brier_components = []
    for i, cls in enumerate([0, 1, 2]):
        y_binary = (y_valid == cls).astype(float)
        pred_probs = preds_valid[:, i]
        brier_components.append(np.mean((y_binary - pred_probs) ** 2))
    oof_brier = np.mean(brier_components)
    
    logger.info(f"\n{'='*50}")
    logger.info(f"PREMIUM MODEL OOF METRICS:")
    logger.info(f"  3-Way Accuracy: {oof_accuracy:.3f} ({oof_accuracy*100:.1f}%)")
    logger.info(f"  LogLoss: {oof_logloss:.4f}")
    logger.info(f"  Brier Score: {oof_brier:.4f}")
    logger.info(f"  Validated Samples: {len(y_valid)}/{len(y)}")
    logger.info(f"{'='*50}")
    
    feature_importance = []
    for i, col in enumerate(feature_cols):
        avg_importance = np.mean([m.feature_importance()[i] for m in models])
        feature_importance.append({'feature': col, 'importance': avg_importance})
    
    feature_importance.sort(key=lambda x: x['importance'], reverse=True)
    
    logger.info("\nTop 15 Feature Importance:")
    for fi in feature_importance[:15]:
        logger.info(f"  {fi['feature']}: {fi['importance']:.2f}")
    
    return {
        'models': models,
        'feature_cols': feature_cols,
        'oof_metrics': {
            'accuracy_3way': oof_accuracy,
            'logloss': oof_logloss,
            'brier_score': oof_brier,
            'n_samples': len(y_valid),
            'n_folds': n_splits
        },
        'fold_metrics': fold_metrics,
        'feature_importance': feature_importance,
        'params': params
    }


def save_model(results: Dict, feature_cols: List[str]):
    """Save trained premium model"""
    
    model_path = OUTPUT_DIR / "lgbm_ensemble.pkl"
    with open(model_path, "wb") as f:
        pickle.dump(results['models'], f)
    
    features_path = OUTPUT_DIR / "features.json"
    with open(features_path, "w") as f:
        json.dump(feature_cols, f, indent=2)
    
    metadata = {
        'model_type': 'Premium_V2_LightGBM',
        'trained_at': datetime.now(timezone.utc).isoformat(),
        'n_features': len(feature_cols),
        'training_data': 'odds_rich_matches_only',
        'oof_metrics': results['oof_metrics'],
        'fold_metrics': results['fold_metrics'],
        'feature_importance': results['feature_importance'][:20],
        'params': results['params']
    }
    
    metadata_path = OUTPUT_DIR / "metadata.json"
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2)
    
    logger.info(f"\nPremium model saved to {OUTPUT_DIR}/")


if __name__ == "__main__":
    logger.info("="*60)
    logger.info("PREMIUM MODEL TRAINING - ODDS-RICH MATCHES ONLY")
    logger.info("="*60)
    
    matches = get_odds_rich_matches()
    
    if len(matches) < 500:
        logger.error(f"Not enough odds-rich matches ({len(matches)} < 500)")
        sys.exit(1)
    
    df = build_training_dataset(matches)
    
    has_odds = df.get('has_odds', df['p_last_home'] > 0)
    odds_pct = has_odds.sum() / len(df) * 100
    logger.info(f"\nOdds coverage in training set: {odds_pct:.1f}%")
    
    results = train_premium_model(df)
    
    save_model(results, results['feature_cols'])
    
    logger.info("\n" + "="*60)
    logger.info("PREMIUM MODEL TRAINING COMPLETE")
    logger.info(f"Accuracy: {results['oof_metrics']['accuracy_3way']*100:.1f}%")
    logger.info(f"LogLoss: {results['oof_metrics']['logloss']:.4f}")
    logger.info("="*60)
