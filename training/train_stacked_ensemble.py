"""
Stacked Meta-Model Training - Phase 2
Uses binary expert outputs as additional features for improved H/D/A prediction
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
from sklearn.metrics import accuracy_score, log_loss

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from features.historical_feature_builder import HistoricalFeatureBuilder

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

OUTPUT_DIR = Path("artifacts/models/v3_stacked")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

BINARY_EXPERTS_DIR = Path("artifacts/models/binary_experts")

BASE_FEATURES = [
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


def load_binary_experts():
    """Load trained binary expert models and calibrators"""
    experts = {}
    
    for expert_type in ['home', 'away', 'draw']:
        model_path = BINARY_EXPERTS_DIR / f"{expert_type}_expert.pkl"
        calibrator_path = BINARY_EXPERTS_DIR / f"{expert_type}_calibrator.pkl"
        
        if model_path.exists() and calibrator_path.exists():
            with open(model_path, 'rb') as f:
                model = pickle.load(f)
            with open(calibrator_path, 'rb') as f:
                calibrator = pickle.load(f)
            
            experts[expert_type] = {
                'model': model,
                'calibrator': calibrator
            }
            logger.info(f"Loaded {expert_type} expert")
        else:
            raise FileNotFoundError(f"Binary expert {expert_type} not found. Run train_binary_experts.py first.")
    
    return experts


def generate_expert_predictions(df: pd.DataFrame, experts: dict) -> pd.DataFrame:
    """Generate calibrated predictions from binary experts"""
    
    result_df = df.copy()
    
    for col in BASE_FEATURES:
        if col not in result_df.columns:
            result_df[col] = 0.0
        result_df[col] = pd.to_numeric(result_df[col], errors='coerce').fillna(0)
    
    X = result_df[BASE_FEATURES]
    
    for expert_type, expert in experts.items():
        model = expert['model']
        calibrator = expert['calibrator']
        
        raw_proba = model.predict(X)
        calibrated_proba = calibrator.predict(raw_proba)
        calibrated_proba = np.clip(calibrated_proba, 0.01, 0.99)
        
        result_df[f'expert_{expert_type}_prob'] = calibrated_proba
    
    result_df['expert_home_away_diff'] = result_df['expert_home_prob'] - result_df['expert_away_prob']
    result_df['expert_draw_confidence'] = result_df['expert_draw_prob'] * result_df['implied_competitiveness']
    result_df['expert_favorite_spread'] = abs(result_df['expert_home_prob'] - result_df['expert_away_prob'])
    
    total = result_df['expert_home_prob'] + result_df['expert_away_prob'] + result_df['expert_draw_prob'] * 1.1
    result_df['expert_norm_home'] = result_df['expert_home_prob'] / total
    result_df['expert_norm_away'] = result_df['expert_away_prob'] / total
    result_df['expert_norm_draw'] = (result_df['expert_draw_prob'] * 1.1) / total
    
    return result_df


def main():
    logger.info("=" * 60)
    logger.info("STACKED META-MODEL TRAINING - PHASE 2")
    logger.info("=" * 60)
    
    experts = load_binary_experts()
    
    builder = HistoricalFeatureBuilder()
    raw_data = builder.get_all_features_for_training(min_date='2020-01-01')
    
    df = pd.DataFrame(raw_data)
    logger.info(f"Loaded {len(df)} matches")
    
    df = df.sort_values('match_date').reset_index(drop=True)
    
    df = generate_expert_predictions(df, experts)
    
    stacked_features = BASE_FEATURES + [
        'expert_home_prob', 'expert_away_prob', 'expert_draw_prob',
        'expert_home_away_diff', 'expert_draw_confidence', 'expert_favorite_spread',
        'expert_norm_home', 'expert_norm_away', 'expert_norm_draw'
    ]
    
    logger.info(f"Total features for stacked model: {len(stacked_features)}")
    
    outcome_map = {'H': 0, 'D': 1, 'A': 2}
    df['target'] = df['outcome'].map(outcome_map)
    
    split_idx = int(len(df) * 0.8)
    train_df = df.iloc[:split_idx]
    val_df = df.iloc[split_idx:]
    
    X_train = train_df[stacked_features]
    y_train = train_df['target']
    X_val = val_df[stacked_features]
    y_val = val_df['target']
    
    logger.info(f"Train: {len(train_df)}, Val: {len(val_df)}")
    
    params = {
        'objective': 'multiclass',
        'num_class': 3,
        'metric': 'multi_logloss',
        'boosting_type': 'gbdt',
        'num_leaves': 31,
        'max_depth': 5,
        'learning_rate': 0.03,
        'min_data_in_leaf': 200,
        'feature_fraction': 0.8,
        'bagging_fraction': 0.8,
        'bagging_freq': 5,
        'lambda_l1': 0.5,
        'lambda_l2': 0.5,
        'verbosity': -1,
        'seed': 42,
        'n_jobs': -1
    }
    
    train_data = lgb.Dataset(X_train, label=y_train)
    val_data = lgb.Dataset(X_val, label=y_val, reference=train_data)
    
    logger.info("\nTraining stacked meta-model...")
    
    model = lgb.train(
        params,
        train_data,
        num_boost_round=500,
        valid_sets=[train_data, val_data],
        valid_names=['train', 'valid'],
        callbacks=[
            lgb.early_stopping(stopping_rounds=30),
            lgb.log_evaluation(period=20)
        ]
    )
    
    y_pred_proba = model.predict(X_val)
    y_pred = np.argmax(y_pred_proba, axis=1)
    
    accuracy = accuracy_score(y_val, y_pred)
    logloss = log_loss(y_val, y_pred_proba)
    
    logger.info("\n" + "=" * 60)
    logger.info("V3 STACKED MODEL RESULTS")
    logger.info("=" * 60)
    logger.info(f"  Accuracy: {accuracy:.4f} ({accuracy*100:.2f}%)")
    logger.info(f"  LogLoss: {logloss:.4f}")
    logger.info(f"  Best Iteration: {model.best_iteration}")
    
    importance = pd.DataFrame({
        'feature': stacked_features,
        'importance': model.feature_importance()
    }).sort_values('importance', ascending=False)
    
    logger.info("\nTop 15 Feature Importance:")
    for _, row in importance.head(15).iterrows():
        logger.info(f"  {row['feature']}: {row['importance']:.0f}")
    
    with open(OUTPUT_DIR / 'model.pkl', 'wb') as f:
        pickle.dump(model, f)
    
    metadata = {
        'version': 'v3_stacked',
        'trained_at': datetime.now().isoformat(),
        'total_samples': len(df),
        'train_samples': len(train_df),
        'val_samples': len(val_df),
        'features': stacked_features,
        'base_features_count': len(BASE_FEATURES),
        'expert_features_count': 9,
        'params': params,
        'metrics': {
            'accuracy': float(accuracy),
            'logloss': float(logloss),
            'best_iteration': model.best_iteration
        },
        'feature_importance': importance.head(20).to_dict('records')
    }
    
    with open(OUTPUT_DIR / 'metadata.json', 'w') as f:
        json.dump(metadata, f, indent=2)
    
    logger.info("\n" + "=" * 60)
    logger.info("COMPARISON VS PREVIOUS MODELS")
    logger.info("=" * 60)
    
    v2_metadata_path = Path("artifacts/models/v2_improved/metadata.json")
    if v2_metadata_path.exists():
        with open(v2_metadata_path) as f:
            v2_meta = json.load(f)
        v2_acc = v2_meta['metrics']['accuracy']
        v2_logloss = v2_meta['metrics']['logloss']
        
        logger.info(f"  V2 Model:     {v2_acc*100:.2f}% acc, {v2_logloss:.4f} logloss")
        logger.info(f"  V3 Stacked:   {accuracy*100:.2f}% acc, {logloss:.4f} logloss")
        
        acc_improvement = (accuracy - v2_acc) * 100
        logloss_improvement = (v2_logloss - logloss) / v2_logloss * 100
        
        logger.info(f"\n  Accuracy Improvement: {acc_improvement:+.2f}%")
        logger.info(f"  LogLoss Improvement: {logloss_improvement:+.2f}%")
    
    logger.info(f"\nModel saved to: {OUTPUT_DIR}")
    
    return accuracy, logloss


if __name__ == '__main__':
    main()
