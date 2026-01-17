"""
Binary Expert Models Training - Phase 1
Trains 3 calibrated binary classifiers:
- Home Expert: H vs (D + A)
- Away Expert: A vs (H + D)  
- Draw Expert: D vs (H + A)
"""

import os
import json
import pickle
import logging
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import (
    accuracy_score, log_loss, roc_auc_score, 
    precision_score, recall_score, f1_score,
    brier_score_loss
)

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from features.historical_feature_builder import HistoricalFeatureBuilder

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

OUTPUT_DIR = Path("artifacts/models/binary_experts")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

FEATURE_COLS = [
    'p_b365_h', 'p_b365_d', 'p_b365_a',
    'p_ps_h', 'p_ps_d', 'p_ps_a',
    'p_avg_h', 'p_avg_d', 'p_avg_a',
    'favorite_strength', 'underdog_value', 'draw_tendency',
    'market_overround', 'sharp_soft_divergence',
    'max_vs_avg_edge_h', 'max_vs_avg_edge_d', 'max_vs_avg_edge_a',
    'league_home_win_rate', 'league_draw_rate', 'league_goals_avg',
    'season_month',
    'expected_total_goals', 'home_goals_expected', 'away_goals_expected', 
    'goal_diff_expected',
    'home_value_score', 'draw_value_score', 'away_value_score',
    'home_advantage_signal', 'draw_vs_away_ratio', 'favorite_confidence',
    'upset_potential', 'book_agreement_score', 'implied_competitiveness'
]

EXPERT_CONFIGS = {
    'home': {
        'name': 'Home Expert',
        'target_class': 'H',
        'description': 'Home Win vs (Draw + Away)',
        'key_features': ['p_ps_h', 'p_b365_h', 'favorite_confidence', 'home_advantage_signal'],
        'params': {
            'objective': 'binary',
            'metric': 'binary_logloss',
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
            'is_unbalance': False,
            'verbosity': -1,
            'seed': 42,
            'n_jobs': -1
        }
    },
    'away': {
        'name': 'Away Expert',
        'target_class': 'A',
        'description': 'Away Win vs (Home + Draw)',
        'key_features': ['p_ps_a', 'p_b365_a', 'p_avg_a', 'upset_potential'],
        'params': {
            'objective': 'binary',
            'metric': 'binary_logloss',
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
            'is_unbalance': False,
            'verbosity': -1,
            'seed': 42,
            'n_jobs': -1
        }
    },
    'draw': {
        'name': 'Draw Expert',
        'target_class': 'D',
        'description': 'Draw vs (Home + Away)',
        'key_features': ['draw_vs_away_ratio', 'book_agreement_score', 'implied_competitiveness', 'draw_tendency'],
        'params': {
            'objective': 'binary',
            'metric': 'binary_logloss',
            'boosting_type': 'gbdt',
            'num_leaves': 25,
            'max_depth': 4,
            'learning_rate': 0.03,
            'min_data_in_leaf': 300,
            'feature_fraction': 0.7,
            'bagging_fraction': 0.7,
            'bagging_freq': 5,
            'lambda_l1': 1.0,
            'lambda_l2': 1.0,
            'scale_pos_weight': 2.5,
            'verbosity': -1,
            'seed': 42,
            'n_jobs': -1
        }
    }
}


def create_binary_target(results: pd.Series, target_class: str) -> pd.Series:
    """Create binary target: 1 if matches target_class, 0 otherwise"""
    return (results == target_class).astype(int)


def train_binary_expert(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_val: pd.DataFrame,
    y_val: pd.Series,
    config: dict,
    expert_type: str
) -> dict:
    """Train a single binary expert with calibration"""
    
    logger.info(f"\n{'='*60}")
    logger.info(f"Training {config['name']}: {config['description']}")
    logger.info(f"{'='*60}")
    
    pos_count = y_train.sum()
    neg_count = len(y_train) - pos_count
    logger.info(f"Train: {len(y_train)} samples ({pos_count} positive, {neg_count} negative)")
    logger.info(f"Positive rate: {pos_count/len(y_train)*100:.1f}%")
    
    train_data = lgb.Dataset(X_train, label=y_train)
    val_data = lgb.Dataset(X_val, label=y_val, reference=train_data)
    
    model = lgb.train(
        config['params'],
        train_data,
        num_boost_round=500,
        valid_sets=[train_data, val_data],
        valid_names=['train', 'valid'],
        callbacks=[
            lgb.early_stopping(stopping_rounds=30),
            lgb.log_evaluation(period=50)
        ]
    )
    
    y_pred_proba = model.predict(X_val)
    y_pred = (y_pred_proba >= 0.5).astype(int)
    
    raw_metrics = {
        'accuracy': accuracy_score(y_val, y_pred),
        'logloss': log_loss(y_val, y_pred_proba),
        'auc': roc_auc_score(y_val, y_pred_proba),
        'precision': precision_score(y_val, y_pred, zero_division=0),
        'recall': recall_score(y_val, y_pred, zero_division=0),
        'f1': f1_score(y_val, y_pred, zero_division=0),
        'brier': brier_score_loss(y_val, y_pred_proba)
    }
    
    logger.info(f"\nRaw Model Metrics:")
    logger.info(f"  AUC: {raw_metrics['auc']:.4f}")
    logger.info(f"  LogLoss: {raw_metrics['logloss']:.4f}")
    logger.info(f"  Brier Score: {raw_metrics['brier']:.4f}")
    logger.info(f"  Accuracy: {raw_metrics['accuracy']*100:.1f}%")
    
    logger.info("\nCalibrating with isotonic regression...")
    
    from sklearn.isotonic import IsotonicRegression
    
    calibrator = IsotonicRegression(out_of_bounds='clip')
    calibrator.fit(y_pred_proba, y_val)
    
    y_pred_calibrated = calibrator.predict(y_pred_proba)
    y_pred_cal_class = (y_pred_calibrated >= 0.5).astype(int)
    
    calibrated_metrics = {
        'accuracy': accuracy_score(y_val, y_pred_cal_class),
        'logloss': log_loss(y_val, y_pred_calibrated),
        'auc': roc_auc_score(y_val, y_pred_calibrated),
        'precision': precision_score(y_val, y_pred_cal_class, zero_division=0),
        'recall': recall_score(y_val, y_pred_cal_class, zero_division=0),
        'f1': f1_score(y_val, y_pred_cal_class, zero_division=0),
        'brier': brier_score_loss(y_val, y_pred_calibrated)
    }
    
    logger.info(f"\nCalibrated Model Metrics:")
    logger.info(f"  AUC: {calibrated_metrics['auc']:.4f}")
    logger.info(f"  LogLoss: {calibrated_metrics['logloss']:.4f}")
    logger.info(f"  Brier Score: {calibrated_metrics['brier']:.4f}")
    logger.info(f"  Accuracy: {calibrated_metrics['accuracy']*100:.1f}%")
    
    importance = pd.DataFrame({
        'feature': X_train.columns,
        'importance': model.feature_importance()
    }).sort_values('importance', ascending=False)
    
    logger.info(f"\nTop 10 Features:")
    for _, row in importance.head(10).iterrows():
        logger.info(f"  {row['feature']}: {row['importance']:.0f}")
    
    model_path = OUTPUT_DIR / f"{expert_type}_expert.pkl"
    calibrator_path = OUTPUT_DIR / f"{expert_type}_calibrator.pkl"
    
    with open(model_path, 'wb') as f:
        pickle.dump(model, f)
    with open(calibrator_path, 'wb') as f:
        pickle.dump(calibrator, f)
    
    return {
        'expert_type': expert_type,
        'name': config['name'],
        'description': config['description'],
        'target_class': config['target_class'],
        'train_samples': len(y_train),
        'val_samples': len(y_val),
        'positive_rate': float(y_train.mean()),
        'best_iteration': model.best_iteration,
        'raw_metrics': raw_metrics,
        'calibrated_metrics': calibrated_metrics,
        'feature_importance': importance.head(15).to_dict('records'),
        'model_path': str(model_path),
        'calibrator_path': str(calibrator_path)
    }


def main():
    logger.info("=" * 60)
    logger.info("BINARY EXPERTS TRAINING - PHASE 1")
    logger.info("=" * 60)
    
    builder = HistoricalFeatureBuilder()
    raw_data = builder.get_all_features_for_training(min_date='2020-01-01')
    
    df = pd.DataFrame(raw_data)
    logger.info(f"Loaded {len(df)} matches")
    
    df = df.sort_values('match_date').reset_index(drop=True)
    
    for col in FEATURE_COLS:
        if col not in df.columns:
            df[col] = 0.0
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    
    split_idx = int(len(df) * 0.8)
    train_df = df.iloc[:split_idx]
    val_df = df.iloc[split_idx:]
    
    X_train = train_df[FEATURE_COLS]
    X_val = val_df[FEATURE_COLS]
    results_train = train_df['outcome']
    results_val = val_df['outcome']
    
    logger.info(f"Train: {len(train_df)}, Val: {len(val_df)}")
    logger.info(f"Training date range: {train_df['match_date'].min()} to {train_df['match_date'].max()}")
    logger.info(f"Validation date range: {val_df['match_date'].min()} to {val_df['match_date'].max()}")
    
    all_results = {}
    
    for expert_type, config in EXPERT_CONFIGS.items():
        y_train = create_binary_target(results_train, config['target_class'])
        y_val = create_binary_target(results_val, config['target_class'])
        
        result = train_binary_expert(
            X_train, y_train,
            X_val, y_val,
            config, expert_type
        )
        all_results[expert_type] = result
    
    logger.info("\n" + "=" * 60)
    logger.info("PHASE 1 SUMMARY - BINARY EXPERTS")
    logger.info("=" * 60)
    
    for expert_type, result in all_results.items():
        cal_metrics = result['calibrated_metrics']
        logger.info(f"\n{result['name']} ({result['target_class']} vs rest):")
        logger.info(f"  AUC: {cal_metrics['auc']:.4f}")
        logger.info(f"  LogLoss: {cal_metrics['logloss']:.4f}")
        logger.info(f"  Brier: {cal_metrics['brier']:.4f}")
        logger.info(f"  Positive Rate: {result['positive_rate']*100:.1f}%")
    
    metadata = {
        'version': 'binary_experts_v1',
        'trained_at': datetime.now().isoformat(),
        'total_samples': len(df),
        'features': FEATURE_COLS,
        'experts': all_results
    }
    
    with open(OUTPUT_DIR / 'metadata.json', 'w') as f:
        json.dump(metadata, f, indent=2, default=str)
    
    logger.info(f"\nModels saved to: {OUTPUT_DIR}")
    
    return all_results


if __name__ == '__main__':
    main()
