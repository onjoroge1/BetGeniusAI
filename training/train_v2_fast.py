"""
Fast V2 Model Training - Single Train/Val Split

Faster training for testing, uses 80/20 split instead of CV.

Usage:
    export LD_LIBRARY_PATH="$(gcc -print-file-name=libgomp.so | xargs dirname):$LD_LIBRARY_PATH"
    python training/train_v2_fast.py
"""

import os
import sys
import json
import logging
import numpy as np
import pandas as pd
from datetime import datetime
from pathlib import Path

import lightgbm as lgb
from sklearn.metrics import log_loss, accuracy_score

sys.path.append('.')
from features.historical_feature_builder import HistoricalFeatureBuilder

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

OUTPUT_DIR = Path("artifacts/models/v2_improved")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

FEATURE_COLS = [
    'p_b365_h', 'p_b365_d', 'p_b365_a',
    'p_ps_h', 'p_ps_d', 'p_ps_a',
    'p_avg_h', 'p_avg_d', 'p_avg_a',
    'favorite_strength', 'underdog_value', 'draw_tendency',
    'market_overround', 'sharp_soft_divergence',
    'max_vs_avg_edge_h', 'max_vs_avg_edge_d', 'max_vs_avg_edge_a',
    'ou_line', 'over_implied_prob', 'under_implied_prob',
    'ah_home_prob', 'ah_away_prob',
    'league_home_win_rate', 'league_draw_rate', 'league_goals_avg',
    'season_month',
    'expected_total_goals', 'home_goals_expected', 'away_goals_expected', 
    'goal_diff_expected',
    'home_value_score', 'draw_value_score', 'away_value_score',
    'home_advantage_signal', 'draw_vs_away_ratio', 'favorite_confidence',
    'upset_potential', 'book_agreement_score', 'implied_competitiveness'
]


def main():
    logger.info("=" * 60)
    logger.info("FAST V2 MODEL TRAINING")
    logger.info("=" * 60)
    
    builder = HistoricalFeatureBuilder()
    raw_data = builder.get_all_features_for_training(min_date='2020-01-01')
    
    df = pd.DataFrame(raw_data)
    logger.info(f"Loaded {len(df)} matches")
    
    outcome_map = {'H': 0, 'D': 1, 'A': 2}
    df = df[df['outcome'].isin(['H', 'D', 'A'])]
    df['target'] = df['outcome'].map(outcome_map)
    df = df.sort_values('match_date').reset_index(drop=True)
    
    for col in FEATURE_COLS:
        if col not in df.columns:
            df[col] = 0.0
    
    logger.info(f"Class distribution: H={sum(df['target']==0)}, D={sum(df['target']==1)}, A={sum(df['target']==2)}")
    
    X = df[FEATURE_COLS].values.astype(np.float32)
    y = df['target'].values.astype(np.int32)
    X = np.nan_to_num(X, nan=0.0)
    
    split = int(len(X) * 0.8)
    X_train, X_val = X[:split], X[split:]
    y_train, y_val = y[:split], y[split:]
    
    logger.info(f"Train: {len(X_train)}, Val: {len(X_val)}")
    
    class_counts = np.bincount(y_train)
    total = len(y_train)
    class_weights = {i: total / (3 * count) for i, count in enumerate(class_counts)}
    sample_weights = np.array([class_weights[yi] for yi in y_train])
    
    params = {
        'objective': 'multiclass',
        'num_class': 3,
        'metric': 'multi_logloss',
        'boosting_type': 'gbdt',
        'num_leaves': 31,
        'max_depth': 5,
        'learning_rate': 0.05,
        'min_data_in_leaf': 200,
        'feature_fraction': 0.8,
        'bagging_fraction': 0.8,
        'bagging_freq': 5,
        'lambda_l1': 0.5,
        'lambda_l2': 0.5,
        'verbosity': -1,
        'seed': 42,
        'n_jobs': -1,
    }
    
    train_data = lgb.Dataset(X_train, label=y_train, weight=sample_weights)
    val_data = lgb.Dataset(X_val, label=y_val, reference=train_data)
    
    logger.info("\nTraining LightGBM model...")
    
    model = lgb.train(
        params,
        train_data,
        num_boost_round=150,
        valid_sets=[train_data, val_data],
        valid_names=['train', 'valid'],
        callbacks=[
            lgb.early_stopping(stopping_rounds=20, verbose=True),
            lgb.log_evaluation(period=20)
        ]
    )
    
    val_probs = model.predict(X_val, num_iteration=model.best_iteration)
    val_preds = np.argmax(val_probs, axis=1)
    
    acc = accuracy_score(y_val, val_preds)
    ll = log_loss(y_val, val_probs)
    
    logger.info("\n" + "=" * 60)
    logger.info("RESULTS")
    logger.info("=" * 60)
    logger.info(f"  Accuracy: {acc:.4f} ({acc*100:.1f}%)")
    logger.info(f"  LogLoss: {ll:.4f}")
    logger.info(f"  Best Iteration: {model.best_iteration}")
    
    importance = pd.DataFrame({
        'feature': FEATURE_COLS,
        'importance': model.feature_importance(importance_type='gain')
    }).sort_values('importance', ascending=False)
    
    logger.info("\nTop 10 Feature Importance:")
    for _, row in importance.head(10).iterrows():
        logger.info(f"  {row['feature']}: {row['importance']:.2f}")
    
    model.save_model(str(OUTPUT_DIR / "model.txt"))
    
    metadata = {
        'version': 'v2_improved_fast',
        'trained_at': datetime.now().isoformat(),
        'samples': len(df),
        'train_samples': len(X_train),
        'val_samples': len(X_val),
        'features': FEATURE_COLS,
        'params': params,
        'metrics': {
            'accuracy': float(acc),
            'logloss': float(ll),
            'best_iteration': model.best_iteration
        },
        'feature_importance': importance.to_dict('records')
    }
    
    with open(OUTPUT_DIR / "metadata.json", 'w') as f:
        json.dump(metadata, f, indent=2, default=str)
    
    logger.info(f"\nModel saved to: {OUTPUT_DIR}")
    
    logger.info("\n" + "=" * 60)
    logger.info("COMPARISON VS PREVIOUS")
    logger.info("=" * 60)
    logger.info(f"  Previous (odds-rich):  50.1% acc, 1.0133 logloss, 2957 samples")
    logger.info(f"  New (historical):      {acc*100:.1f}% acc, {ll:.4f} logloss, {len(df)} samples")
    improvement = ((acc - 0.501) / 0.501) * 100 if acc > 0.501 else 0
    logger.info(f"  Improvement: {improvement:+.1f}% relative accuracy")


if __name__ == "__main__":
    main()
