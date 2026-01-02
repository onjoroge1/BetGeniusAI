"""
Player V2 LightGBM Training Script

Trains player-level models for predicting:
- Goal involvement (binary: will player score or assist?)
- Goals scored (regression)
- Assists (regression)

Usage:
    python training/train_player_v2.py

Expected Results:
    - Goal involvement AUC: 0.65-0.70
    - Goals RMSE: < 0.8
"""

import os
import sys
import json
import pickle
import logging
import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Tuple

import psycopg2
from psycopg2.extras import RealDictCursor
import lightgbm as lgb
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import (
    log_loss, accuracy_score, roc_auc_score, 
    mean_squared_error, mean_absolute_error
)

sys.path.append('.')
from features.player_v2_feature_builder import PlayerV2FeatureBuilder

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

OUTPUT_DIR = Path("artifacts/models/player_v2")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def get_training_samples(min_games: int = 5, limit: int = 10000) -> List[Dict]:
    """
    Get player-match samples for training.
    
    Requirements:
    - Player has at least min_games previous games (for form features)
    - Player played at least 45 minutes in the match
    - Non-goalkeeper (positions F, M, D)
    """
    conn = psycopg2.connect(os.getenv('DATABASE_URL'))
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        cur.execute("""
            WITH player_game_counts AS (
                SELECT player_id, COUNT(*) as game_count
                FROM player_game_stats
                WHERE sport_key = 'soccer'
                GROUP BY player_id
                HAVING COUNT(*) >= %s
            )
            SELECT 
                pgs.player_id,
                pgs.game_id,
                pgs.game_date,
                pgs.team_id,
                pgs.minutes_played,
                (pgs.stats->>'goals')::int as goals,
                (pgs.stats->>'assists')::int as assists,
                p.position,
                p.player_name
            FROM player_game_stats pgs
            JOIN players_unified p ON pgs.player_id = p.player_id
            JOIN player_game_counts pgc ON pgs.player_id = pgc.player_id
            WHERE pgs.sport_key = 'soccer'
              AND pgs.minutes_played >= 45
              AND p.position IS NOT NULL
              AND p.position NOT ILIKE '%%G%%'
            ORDER BY pgs.game_date
            LIMIT %s
        """, (min_games, limit))
        
        samples = cur.fetchall()
        logger.info(f"Found {len(samples)} training samples")
        return [dict(s) for s in samples]
        
    finally:
        conn.close()


def build_training_dataset(samples: List[Dict], max_samples: int = None) -> pd.DataFrame:
    """Build training dataset with player V2 features."""
    
    builder = PlayerV2FeatureBuilder()
    records = []
    skipped = 0
    
    if max_samples:
        samples = samples[:max_samples]
    
    logger.info(f"Building features for {len(samples)} samples...")
    
    for i, sample in enumerate(samples):
        try:
            cutoff = datetime.combine(
                sample['game_date'], 
                datetime.min.time()
            ).replace(tzinfo=timezone.utc)
            
            features = builder.build_features(
                player_id=sample['player_id'],
                match_id=sample['game_id'],
                cutoff_time=cutoff
            )
            
            features['player_id'] = sample['player_id']
            features['game_id'] = sample['game_id']
            features['game_date'] = sample['game_date']
            features['goals'] = sample['goals'] or 0
            features['assists'] = sample['assists'] or 0
            features['goal_involvement'] = 1 if (sample['goals'] or 0) + (sample['assists'] or 0) > 0 else 0
            features['position'] = sample['position']
            
            records.append(features)
            
            if (i + 1) % 100 == 0:
                logger.info(f"  Progress: {i+1}/{len(samples)} ({len(records)} built, {skipped} skipped)")
                
        except Exception as e:
            skipped += 1
            if skipped <= 5:
                logger.warning(f"  Skip sample {sample['player_id']}: {e}")
            continue
    
    if not records:
        raise ValueError("No training data could be built")
    
    df = pd.DataFrame(records)
    logger.info(f"Built {len(df)} training samples with {len(df.columns)} columns")
    
    return df


def train_goal_involvement_model(df: pd.DataFrame, n_splits: int = 5) -> Dict:
    """Train binary classification model for goal involvement."""
    
    feature_cols = [c for c in df.columns if c not in [
        'player_id', 'game_id', 'game_date', 'goals', 'assists', 
        'goal_involvement', 'position'
    ]]
    
    X = df[feature_cols].fillna(0).values
    y = df['goal_involvement'].values
    
    logger.info(f"\nTraining goal involvement model with {len(feature_cols)} features")
    logger.info(f"Class distribution: Involved={sum(y==1)} ({sum(y==1)/len(y)*100:.1f}%), Not={sum(y==0)}")
    
    params = {
        'objective': 'binary',
        'metric': 'binary_logloss',
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
        'seed': 42,
        'is_unbalance': True
    }
    
    n_splits = min(n_splits, len(y) // 100)
    if n_splits < 2:
        n_splits = 2
    
    tscv = TimeSeriesSplit(n_splits=n_splits, gap=20)
    
    models = []
    oof_preds = np.zeros(len(y))
    oof_mask = np.zeros(len(y), dtype=bool)
    fold_metrics = []
    
    for fold, (train_idx, val_idx) in enumerate(tscv.split(X)):
        logger.info(f"\n--- Fold {fold + 1}/{n_splits} ---")
        
        X_train, X_val = X[train_idx], X[val_idx]
        y_train, y_val = y[train_idx], y[val_idx]
        
        train_data = lgb.Dataset(X_train, label=y_train)
        val_data = lgb.Dataset(X_val, label=y_val, reference=train_data)
        
        model = lgb.train(
            params,
            train_data,
            num_boost_round=1000,
            valid_sets=[train_data, val_data],
            valid_names=['train', 'valid'],
            callbacks=[
                lgb.early_stopping(stopping_rounds=50),
                lgb.log_evaluation(period=100)
            ]
        )
        
        val_preds = model.predict(X_val, num_iteration=model.best_iteration)
        oof_preds[val_idx] = val_preds
        oof_mask[val_idx] = True
        
        fold_auc = roc_auc_score(y_val, val_preds)
        fold_logloss = log_loss(y_val, val_preds)
        fold_acc = accuracy_score(y_val, (val_preds > 0.5).astype(int))
        
        fold_metrics.append({
            'fold': fold + 1,
            'auc': fold_auc,
            'logloss': fold_logloss,
            'accuracy': fold_acc
        })
        
        logger.info(f"Fold {fold + 1}: AUC={fold_auc:.3f}, LogLoss={fold_logloss:.4f}, Acc={fold_acc:.3f}")
        models.append(model)
    
    y_valid = y[oof_mask]
    preds_valid = oof_preds[oof_mask]
    
    oof_auc = roc_auc_score(y_valid, preds_valid)
    oof_logloss = log_loss(y_valid, preds_valid)
    oof_accuracy = accuracy_score(y_valid, (preds_valid > 0.5).astype(int))
    
    logger.info(f"\n{'='*50}")
    logger.info(f"GOAL INVOLVEMENT MODEL OOF METRICS:")
    logger.info(f"  AUC: {oof_auc:.3f}")
    logger.info(f"  LogLoss: {oof_logloss:.4f}")
    logger.info(f"  Accuracy: {oof_accuracy:.3f} ({oof_accuracy*100:.1f}%)")
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
            'auc': oof_auc,
            'logloss': oof_logloss,
            'accuracy': oof_accuracy,
            'n_samples': len(y_valid)
        },
        'fold_metrics': fold_metrics,
        'feature_importance': feature_importance,
        'params': params,
        'target': 'goal_involvement'
    }


def train_goals_regression_model(df: pd.DataFrame, n_splits: int = 5) -> Dict:
    """Train regression model for goals scored."""
    
    feature_cols = [c for c in df.columns if c not in [
        'player_id', 'game_id', 'game_date', 'goals', 'assists', 
        'goal_involvement', 'position'
    ]]
    
    X = df[feature_cols].fillna(0).values
    y = df['goals'].values
    
    logger.info(f"\nTraining goals regression model")
    logger.info(f"Target distribution: Mean={y.mean():.3f}, Std={y.std():.3f}")
    
    params = {
        'objective': 'regression',
        'metric': 'rmse',
        'boosting_type': 'gbdt',
        'learning_rate': 0.03,
        'num_leaves': 31,
        'max_depth': 6,
        'min_data_in_leaf': 20,
        'feature_fraction': 0.8,
        'bagging_fraction': 0.8,
        'bagging_freq': 5,
        'verbose': -1,
        'seed': 42
    }
    
    n_splits = min(n_splits, len(y) // 100)
    if n_splits < 2:
        n_splits = 2
    
    tscv = TimeSeriesSplit(n_splits=n_splits, gap=20)
    
    models = []
    oof_preds = np.zeros(len(y))
    oof_mask = np.zeros(len(y), dtype=bool)
    
    for fold, (train_idx, val_idx) in enumerate(tscv.split(X)):
        X_train, X_val = X[train_idx], X[val_idx]
        y_train, y_val = y[train_idx], y[val_idx]
        
        train_data = lgb.Dataset(X_train, label=y_train)
        val_data = lgb.Dataset(X_val, label=y_val, reference=train_data)
        
        model = lgb.train(
            params,
            train_data,
            num_boost_round=1000,
            valid_sets=[train_data, val_data],
            valid_names=['train', 'valid'],
            callbacks=[
                lgb.early_stopping(stopping_rounds=50),
                lgb.log_evaluation(period=100)
            ]
        )
        
        val_preds = model.predict(X_val, num_iteration=model.best_iteration)
        val_preds = np.maximum(val_preds, 0)
        
        oof_preds[val_idx] = val_preds
        oof_mask[val_idx] = True
        models.append(model)
    
    y_valid = y[oof_mask]
    preds_valid = oof_preds[oof_mask]
    
    oof_rmse = np.sqrt(mean_squared_error(y_valid, preds_valid))
    oof_mae = mean_absolute_error(y_valid, preds_valid)
    
    logger.info(f"\n{'='*50}")
    logger.info(f"GOALS REGRESSION MODEL OOF METRICS:")
    logger.info(f"  RMSE: {oof_rmse:.4f}")
    logger.info(f"  MAE: {oof_mae:.4f}")
    logger.info(f"  Mean baseline RMSE: {np.sqrt(mean_squared_error(y_valid, np.full_like(y_valid, y.mean()))):.4f}")
    logger.info(f"{'='*50}")
    
    return {
        'models': models,
        'feature_cols': feature_cols,
        'oof_metrics': {
            'rmse': oof_rmse,
            'mae': oof_mae,
            'n_samples': len(y_valid)
        },
        'params': params,
        'target': 'goals'
    }


def save_models(classification_result: Dict, regression_result: Dict):
    """Save trained models and metadata."""
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    with open(OUTPUT_DIR / f"goal_involvement_{timestamp}.pkl", 'wb') as f:
        pickle.dump({
            'models': classification_result['models'],
            'feature_cols': classification_result['feature_cols'],
            'params': classification_result['params']
        }, f)
    
    with open(OUTPUT_DIR / f"goals_regression_{timestamp}.pkl", 'wb') as f:
        pickle.dump({
            'models': regression_result['models'],
            'feature_cols': regression_result['feature_cols'],
            'params': regression_result['params']
        }, f)
    
    metadata = {
        'timestamp': timestamp,
        'goal_involvement': {
            'metrics': classification_result['oof_metrics'],
            'feature_importance': classification_result['feature_importance'][:20]
        },
        'goals_regression': {
            'metrics': regression_result['oof_metrics']
        }
    }
    
    with open(OUTPUT_DIR / f"player_v2_metadata_{timestamp}.json", 'w') as f:
        json.dump(metadata, f, indent=2, default=str)
    
    with open(OUTPUT_DIR / "latest.json", 'w') as f:
        json.dump({'version': timestamp}, f)
    
    logger.info(f"\nModels saved to {OUTPUT_DIR}")
    return timestamp


def main():
    """Main training pipeline."""
    logger.info("="*60)
    logger.info("PLAYER V2 MODEL TRAINING")
    logger.info("="*60)
    
    samples = get_training_samples(min_games=5, limit=10000)
    
    if len(samples) < 100:
        logger.error(f"Insufficient training data: {len(samples)} samples")
        logger.info("Run player game stats collection first:")
        logger.info("  POST /api/v1/players/collect-game-stats?batch=True&limit=200")
        return
    
    df = build_training_dataset(samples, max_samples=5000)
    
    logger.info(f"\nDataset built: {len(df)} samples")
    logger.info(f"Goal involvement rate: {df['goal_involvement'].mean()*100:.1f}%")
    logger.info(f"Goals mean: {df['goals'].mean():.3f}")
    
    classification_result = train_goal_involvement_model(df)
    regression_result = train_goals_regression_model(df)
    
    version = save_models(classification_result, regression_result)
    
    logger.info("\n" + "="*60)
    logger.info("TRAINING COMPLETE")
    logger.info("="*60)
    logger.info(f"Version: {version}")
    logger.info(f"Goal Involvement AUC: {classification_result['oof_metrics']['auc']:.3f}")
    logger.info(f"Goals RMSE: {regression_result['oof_metrics']['rmse']:.4f}")


if __name__ == "__main__":
    main()
