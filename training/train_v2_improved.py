"""
Improved V2 Model Training with Historical Data + Hyperparameter Tuning

Uses:
- historical_odds table (37,000+ matches vs 2,957)
- 35 high-quality features with 90%+ coverage
- Hyperparameter tuning via Optuna-style grid search
- Class-weighted training for imbalanced outcomes
- Better regularization to prevent overfitting

Usage:
    export LD_LIBRARY_PATH="$(gcc -print-file-name=libgomp.so | xargs dirname):$LD_LIBRARY_PATH"
    python training/train_v2_improved.py
"""

import os
import sys
import json
import pickle
import logging
import numpy as np
import pandas as pd
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Optional

import lightgbm as lgb
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import log_loss, accuracy_score, f1_score
from sklearn.preprocessing import LabelEncoder

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
    'ah_line', 'ah_home_prob', 'ah_away_prob',
    'league_home_win_rate', 'league_draw_rate', 'league_goals_avg',
    'season_month',
    'expected_total_goals', 'home_goals_expected', 'away_goals_expected', 
    'goal_diff_expected',
    'home_value_score', 'draw_value_score', 'away_value_score'
]

BASE_PARAMS = {
    'objective': 'multiclass',
    'num_class': 3,
    'metric': 'multi_logloss',
    'boosting_type': 'gbdt',
    'verbosity': -1,
    'seed': 42,
    'n_jobs': -1,
    'force_col_wise': True,
}

HYPERPARAMS_GRID = [
    {
        'name': 'regularized',
        'num_leaves': 31,
        'max_depth': 5,
        'learning_rate': 0.05,
        'min_data_in_leaf': 200,
        'feature_fraction': 0.8,
        'bagging_fraction': 0.8,
        'bagging_freq': 5,
        'lambda_l1': 0.5,
        'lambda_l2': 0.5,
    },
    {
        'name': 'high_reg',
        'num_leaves': 23,
        'max_depth': 4,
        'learning_rate': 0.03,
        'min_data_in_leaf': 300,
        'feature_fraction': 0.7,
        'bagging_fraction': 0.7,
        'bagging_freq': 5,
        'lambda_l1': 1.0,
        'lambda_l2': 1.0,
    },
]


def load_training_data(min_date: str = '2018-01-01', 
                       max_date: str = '2026-01-01') -> pd.DataFrame:
    """Load and prepare training data from historical_odds"""
    
    builder = HistoricalFeatureBuilder()
    raw_data = builder.get_all_features_for_training(
        min_date=min_date,
        max_date=max_date
    )
    
    df = pd.DataFrame(raw_data)
    logger.info(f"Loaded {len(df)} matches from historical_odds")
    
    outcome_map = {'H': 0, 'D': 1, 'A': 2}
    df = df[df['outcome'].isin(['H', 'D', 'A'])]
    df['target'] = df['outcome'].map(outcome_map)
    
    df = df.sort_values('match_date').reset_index(drop=True)
    
    for col in FEATURE_COLS:
        if col not in df.columns:
            df[col] = 0.0
            logger.warning(f"Missing feature column: {col}")
    
    logger.info(f"\nClass distribution:")
    logger.info(f"  Home wins (H=0): {(df['target'] == 0).sum()}")
    logger.info(f"  Draws (D=1): {(df['target'] == 1).sum()}")
    logger.info(f"  Away wins (A=2): {(df['target'] == 2).sum()}")
    
    return df


def compute_feature_coverage(df: pd.DataFrame) -> Dict[str, float]:
    """Compute coverage percentage for each feature"""
    coverage = {}
    for col in FEATURE_COLS:
        if col in df.columns:
            non_zero = (df[col] != 0).sum()
            non_null = df[col].notna().sum()
            coverage[col] = min(non_zero, non_null) / len(df) * 100
        else:
            coverage[col] = 0.0
    return coverage


def train_with_params(df: pd.DataFrame, 
                      params: Dict, 
                      n_splits: int = 3) -> Dict:
    """Train model with given hyperparameters and return metrics"""
    
    X = df[FEATURE_COLS].values.astype(np.float32)
    y = df['target'].values.astype(np.int32)
    
    X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
    
    class_counts = np.bincount(y)
    total = len(y)
    class_weights = {i: total / (3 * count) for i, count in enumerate(class_counts)}
    sample_weights = np.array([class_weights[yi] for yi in y])
    
    gap = len(df) // (n_splits + 1)
    tscv = TimeSeriesSplit(n_splits=n_splits, gap=gap)
    
    train_params = {**BASE_PARAMS}
    for k, v in params.items():
        if k != 'name':
            train_params[k] = v
    
    oof_preds = np.zeros((len(y), 3))
    fold_metrics = []
    models = []
    
    for fold, (train_idx, val_idx) in enumerate(tscv.split(X), 1):
        X_train, X_val = X[train_idx], X[val_idx]
        y_train, y_val = y[train_idx], y[val_idx]
        w_train = sample_weights[train_idx]
        
        train_data = lgb.Dataset(X_train, label=y_train, weight=w_train)
        val_data = lgb.Dataset(X_val, label=y_val, reference=train_data)
        
        model = lgb.train(
            train_params,
            train_data,
            num_boost_round=500,
            valid_sets=[train_data, val_data],
            valid_names=['train', 'valid'],
            callbacks=[
                lgb.early_stopping(stopping_rounds=50, verbose=False),
                lgb.log_evaluation(period=0)
            ]
        )
        
        val_probs = model.predict(X_val, num_iteration=model.best_iteration)
        val_preds = np.argmax(val_probs, axis=1)
        
        acc = accuracy_score(y_val, val_preds)
        ll = log_loss(y_val, val_probs)
        
        fold_metrics.append({
            'fold': fold,
            'accuracy': acc,
            'logloss': ll,
            'best_iteration': model.best_iteration
        })
        
        oof_preds[val_idx] = val_probs
        models.append(model)
    
    valid_mask = oof_preds.sum(axis=1) > 0
    oof_valid = oof_preds[valid_mask]
    y_valid = y[valid_mask]
    
    final_preds = np.argmax(oof_valid, axis=1)
    
    metrics = {
        'name': params.get('name', 'unknown'),
        'accuracy': accuracy_score(y_valid, final_preds),
        'logloss': log_loss(y_valid, oof_valid),
        'f1_macro': f1_score(y_valid, final_preds, average='macro'),
        'samples_validated': valid_mask.sum(),
        'avg_iterations': np.mean([m['best_iteration'] for m in fold_metrics]),
        'fold_metrics': fold_metrics
    }
    
    return metrics, models, oof_preds


def train_final_model(df: pd.DataFrame, best_params: Dict) -> lgb.Booster:
    """Train final model on all data with best hyperparameters"""
    
    X = df[FEATURE_COLS].values.astype(np.float32)
    y = df['target'].values.astype(np.int32)
    X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
    
    class_counts = np.bincount(y)
    total = len(y)
    class_weights = {i: total / (3 * count) for i, count in enumerate(class_counts)}
    sample_weights = np.array([class_weights[yi] for yi in y])
    
    train_params = {**BASE_PARAMS}
    for k, v in best_params.items():
        if k != 'name':
            train_params[k] = v
    
    split_point = int(len(X) * 0.9)
    X_train, X_val = X[:split_point], X[split_point:]
    y_train, y_val = y[:split_point], y[split_point:]
    w_train = sample_weights[:split_point]
    
    train_data = lgb.Dataset(X_train, label=y_train, weight=w_train)
    val_data = lgb.Dataset(X_val, label=y_val, reference=train_data)
    
    model = lgb.train(
        train_params,
        train_data,
        num_boost_round=1000,
        valid_sets=[train_data, val_data],
        valid_names=['train', 'valid'],
        callbacks=[
            lgb.early_stopping(stopping_rounds=100, verbose=True),
            lgb.log_evaluation(period=50)
        ]
    )
    
    return model


def main():
    logger.info("=" * 60)
    logger.info("IMPROVED V2 MODEL TRAINING")
    logger.info("Using historical_odds (37K+ matches) + Hyperparameter Tuning")
    logger.info("=" * 60)
    
    df = load_training_data(min_date='2018-01-01')
    
    logger.info(f"\nFeature coverage:")
    coverage = compute_feature_coverage(df)
    for feat, pct in sorted(coverage.items(), key=lambda x: -x[1]):
        status = "✓" if pct > 80 else "⚠️" if pct > 50 else "❌"
        logger.info(f"  {status} {feat}: {pct:.1f}%")
    
    logger.info("\n" + "=" * 60)
    logger.info("HYPERPARAMETER SEARCH")
    logger.info("=" * 60)
    
    all_results = []
    
    for params in HYPERPARAMS_GRID:
        logger.info(f"\nTesting: {params['name']}")
        logger.info(f"  Params: leaves={params['num_leaves']}, depth={params['max_depth']}, lr={params['learning_rate']}")
        
        metrics, models, oof = train_with_params(df, params, n_splits=5)
        
        logger.info(f"  → Accuracy: {metrics['accuracy']:.4f}")
        logger.info(f"  → LogLoss: {metrics['logloss']:.4f}")
        logger.info(f"  → F1-Macro: {metrics['f1_macro']:.4f}")
        logger.info(f"  → Avg Iterations: {metrics['avg_iterations']:.0f}")
        
        all_results.append(metrics)
    
    best_result = min(all_results, key=lambda x: x['logloss'])
    best_params = next(p for p in HYPERPARAMS_GRID if p['name'] == best_result['name'])
    
    logger.info("\n" + "=" * 60)
    logger.info("HYPERPARAMETER SEARCH RESULTS")
    logger.info("=" * 60)
    
    for result in sorted(all_results, key=lambda x: x['logloss']):
        logger.info(f"  {result['name']}: Acc={result['accuracy']:.4f}, LL={result['logloss']:.4f}")
    
    logger.info(f"\n🏆 Best configuration: {best_result['name']}")
    
    logger.info("\n" + "=" * 60)
    logger.info("TRAINING FINAL MODEL")
    logger.info("=" * 60)
    
    final_model = train_final_model(df, best_params)
    
    importance = pd.DataFrame({
        'feature': FEATURE_COLS,
        'importance': final_model.feature_importance(importance_type='gain')
    }).sort_values('importance', ascending=False)
    
    logger.info("\nTop 15 Feature Importance:")
    for _, row in importance.head(15).iterrows():
        logger.info(f"  {row['feature']}: {row['importance']:.2f}")
    
    model_path = OUTPUT_DIR / "model.txt"
    final_model.save_model(str(model_path))
    
    metadata = {
        'version': 'v2_improved',
        'trained_at': datetime.now().isoformat(),
        'samples': len(df),
        'features': FEATURE_COLS,
        'best_params': best_params,
        'metrics': {
            'accuracy': best_result['accuracy'],
            'logloss': best_result['logloss'],
            'f1_macro': best_result['f1_macro']
        },
        'feature_importance': importance.to_dict('records'),
        'all_search_results': all_results
    }
    
    with open(OUTPUT_DIR / "metadata.json", 'w') as f:
        json.dump(metadata, f, indent=2, default=str)
    
    logger.info("\n" + "=" * 60)
    logger.info("TRAINING COMPLETE")
    logger.info("=" * 60)
    logger.info(f"  Samples trained: {len(df)}")
    logger.info(f"  Best configuration: {best_result['name']}")
    logger.info(f"  Accuracy: {best_result['accuracy']:.4f} ({best_result['accuracy']*100:.1f}%)")
    logger.info(f"  LogLoss: {best_result['logloss']:.4f}")
    logger.info(f"  Model saved to: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
