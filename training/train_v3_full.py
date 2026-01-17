"""
V3 Full Model Training - Complete Ensemble
Combines: Binary Experts + Stacked Meta-Model + Regime Features
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
from features.regime_feature_builder import RegimeFeatureBuilder

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

OUTPUT_DIR = Path("artifacts/models/v3_full")
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

REGIME_FEATURES = [
    'league_draw_regime', 'league_goals_regime',
    'regime_home_stability', 'regime_draw_volatility',
    'odds_skewness', 'favorite_dominance',
    'draw_compression', 'home_favorite_fragility',
    'sharp_draw_signal', 'sharp_away_signal',
    'early_season', 'late_season', 'winter_period', 'draw_season_bias'
]

EXPERT_FEATURES = [
    'expert_home_prob', 'expert_away_prob', 'expert_draw_prob',
    'expert_home_away_diff', 'expert_draw_confidence', 'expert_favorite_spread',
    'expert_norm_home', 'expert_norm_away', 'expert_norm_draw'
]


def load_binary_experts():
    """Load trained binary expert models and calibrators"""
    experts = {}
    
    for expert_type in ['home', 'away', 'draw']:
        model_path = BINARY_EXPERTS_DIR / f"{expert_type}_expert.pkl"
        calibrator_path = BINARY_EXPERTS_DIR / f"{expert_type}_calibrator.pkl"
        
        with open(model_path, 'rb') as f:
            model = pickle.load(f)
        with open(calibrator_path, 'rb') as f:
            calibrator = pickle.load(f)
        
        experts[expert_type] = {'model': model, 'calibrator': calibrator}
    
    return experts


def generate_expert_predictions(df: pd.DataFrame, experts: dict) -> pd.DataFrame:
    """Generate calibrated predictions from binary experts"""
    
    result_df = df.copy()
    X = result_df[BASE_FEATURES]
    
    for expert_type, expert in experts.items():
        raw_proba = expert['model'].predict(X)
        calibrated_proba = expert['calibrator'].predict(raw_proba)
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


def add_regime_features(df: pd.DataFrame, regime_builder: RegimeFeatureBuilder) -> pd.DataFrame:
    """Add regime features to dataframe (vectorized)"""
    
    result_df = df.copy()
    
    for col in REGIME_FEATURES:
        result_df[col] = 0.0
    
    for league in result_df['league'].unique():
        mask = result_df['league'] == league
        
        if league in regime_builder._league_regime_cache:
            regime_data = regime_builder._league_regime_cache[league]
            if len(regime_data) >= 2:
                home_rates = [float(r['home_rate']) for r in regime_data]
                draw_rates = [float(r['draw_rate']) for r in regime_data]
                goals_avgs = [float(r['goals_avg']) for r in regime_data]
                
                avg_draw = np.mean(draw_rates)
                std_draw = np.std(draw_rates)
                
                result_df.loc[mask, 'league_draw_regime'] = float(avg_draw - 0.26)
                result_df.loc[mask, 'league_goals_regime'] = float(np.mean(goals_avgs) - 2.5)
                result_df.loc[mask, 'regime_home_stability'] = float(max(0, 1 - np.std(home_rates) * 5))
                result_df.loc[mask, 'regime_draw_volatility'] = float(std_draw * 5)
    
    p_home = result_df['p_b365_h']
    p_draw = result_df['p_b365_d']
    p_away = result_df['p_b365_a']
    
    probs_sorted = np.sort(np.column_stack([p_home, p_draw, p_away]), axis=1)[:, ::-1]
    result_df['odds_skewness'] = probs_sorted[:, 0] - probs_sorted[:, 2]
    result_df['favorite_dominance'] = probs_sorted[:, 0] / (probs_sorted[:, 1] + 0.001)
    
    draw_compression = np.abs(p_draw - 0.30) * -1 + 0.1
    draw_compression = np.where((p_draw > 0.2) & (p_draw < 0.4), draw_compression, np.abs(p_draw - 0.30) * -3)
    result_df['draw_compression'] = np.clip(draw_compression + 0.5, 0, 1)
    
    result_df['home_favorite_fragility'] = np.where(
        p_home > 0.5,
        (p_home - 0.5) * (1 - result_df['book_agreement_score']),
        0.0
    )
    
    ps_home = result_df['p_ps_h']
    ps_draw = result_df['p_ps_d']
    ps_away = result_df['p_ps_a']
    avg_home = result_df['p_avg_h']
    avg_draw = result_df['p_avg_d']
    avg_away = result_df['p_avg_a']
    
    result_df['sharp_draw_signal'] = (ps_draw - avg_draw) * 3
    result_df['sharp_away_signal'] = (ps_away - avg_away) * 3
    
    month = result_df['season_month']
    result_df['early_season'] = month.isin([8, 9]).astype(float)
    result_df['late_season'] = month.isin([4, 5]).astype(float)
    result_df['winter_period'] = month.isin([12, 1, 2]).astype(float)
    
    result_df['draw_season_bias'] = 0.0
    result_df.loc[month.isin([10, 11, 3]), 'draw_season_bias'] = 0.05
    result_df.loc[month.isin([12, 1, 2]), 'draw_season_bias'] = 0.03
    
    return result_df


def train_binary_expert_fold(X_train, y_train, expert_type, config):
    """Train a binary expert on a fold and return calibrated model"""
    train_data = lgb.Dataset(X_train, label=y_train)
    
    params = {
        'objective': 'binary',
        'metric': 'binary_logloss',
        'boosting_type': 'gbdt',
        'num_leaves': 31 if expert_type != 'draw' else 25,
        'max_depth': 5 if expert_type != 'draw' else 4,
        'learning_rate': 0.05 if expert_type != 'draw' else 0.03,
        'min_data_in_leaf': 200 if expert_type != 'draw' else 300,
        'feature_fraction': 0.8 if expert_type != 'draw' else 0.7,
        'bagging_fraction': 0.8 if expert_type != 'draw' else 0.7,
        'bagging_freq': 5,
        'lambda_l1': 0.5 if expert_type != 'draw' else 1.0,
        'lambda_l2': 0.5 if expert_type != 'draw' else 1.0,
        'verbosity': -1,
        'seed': 42,
        'n_jobs': -1
    }
    
    if expert_type == 'draw':
        params['scale_pos_weight'] = 2.5
    
    model = lgb.train(params, train_data, num_boost_round=100)
    return model


def main():
    logger.info("=" * 60)
    logger.info("V3 FULL MODEL TRAINING (LEAK-FREE)")
    logger.info("Binary Experts + Stacked Meta-Model + Regime Features")
    logger.info("Out-of-fold predictions to prevent stacking leakage")
    logger.info("=" * 60)
    
    regime_builder = RegimeFeatureBuilder()
    
    builder = HistoricalFeatureBuilder()
    raw_data = builder.get_all_features_for_training(min_date='2020-01-01')
    
    df = pd.DataFrame(raw_data)
    logger.info(f"Loaded {len(df)} matches")
    
    df = df.sort_values('match_date').reset_index(drop=True)
    
    for col in BASE_FEATURES:
        if col not in df.columns:
            df[col] = 0.0
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    
    logger.info("Generating out-of-fold expert predictions...")
    
    split1 = int(len(df) * 0.5)
    split2 = int(len(df) * 0.8)
    
    fold1 = df.iloc[:split1]
    fold2 = df.iloc[split1:split2]
    val_df = df.iloc[split2:]
    
    logger.info(f"Fold 1 (train experts): {len(fold1)}")
    logger.info(f"Fold 2 (train meta): {len(fold2)}")
    logger.info(f"Validation: {len(val_df)}")
    
    for col in EXPERT_FEATURES:
        df[col] = 0.0
    
    X_fold1 = fold1[BASE_FEATURES]
    
    experts = {}
    for expert_type in ['home', 'away', 'draw']:
        target_map = {'home': 'H', 'away': 'A', 'draw': 'D'}
        y_fold1 = (fold1['outcome'] == target_map[expert_type]).astype(int)
        model = train_binary_expert_fold(X_fold1, y_fold1, expert_type, {})
        experts[expert_type] = model
        logger.info(f"Trained {expert_type} expert on fold 1")
    
    X_fold2 = fold2[BASE_FEATURES]
    X_val = val_df[BASE_FEATURES]
    
    from sklearn.isotonic import IsotonicRegression
    calibrators = {}
    
    for expert_type, model in experts.items():
        raw_proba = model.predict(X_fold2)
        target_map = {'home': 'H', 'away': 'A', 'draw': 'D'}
        y_fold2 = (fold2['outcome'] == target_map[expert_type]).astype(int)
        
        calibrator = IsotonicRegression(out_of_bounds='clip')
        calibrator.fit(raw_proba, y_fold2)
        calibrators[expert_type] = calibrator
        
        cal_proba = calibrator.predict(raw_proba)
        df.loc[fold2.index, f'expert_{expert_type}_prob'] = np.clip(cal_proba, 0.01, 0.99)
        
        val_raw = model.predict(X_val)
        val_cal = calibrator.predict(val_raw)
        df.loc[val_df.index, f'expert_{expert_type}_prob'] = np.clip(val_cal, 0.01, 0.99)
    
    for idx_set in [fold2.index, val_df.index]:
        subset = df.loc[idx_set]
        df.loc[idx_set, 'expert_home_away_diff'] = subset['expert_home_prob'] - subset['expert_away_prob']
        df.loc[idx_set, 'expert_draw_confidence'] = subset['expert_draw_prob'] * subset['implied_competitiveness']
        df.loc[idx_set, 'expert_favorite_spread'] = abs(subset['expert_home_prob'] - subset['expert_away_prob'])
        
        total = subset['expert_home_prob'] + subset['expert_away_prob'] + subset['expert_draw_prob'] * 1.1
        df.loc[idx_set, 'expert_norm_home'] = subset['expert_home_prob'] / total
        df.loc[idx_set, 'expert_norm_away'] = subset['expert_away_prob'] / total
        df.loc[idx_set, 'expert_norm_draw'] = (subset['expert_draw_prob'] * 1.1) / total
    
    logger.info("Generated out-of-fold expert predictions")
    
    logger.info("Adding regime features...")
    df = add_regime_features(df, regime_builder)
    logger.info("Added regime features")
    
    all_features = BASE_FEATURES + EXPERT_FEATURES + REGIME_FEATURES
    logger.info(f"Total features: {len(all_features)}")
    
    outcome_map = {'H': 0, 'D': 1, 'A': 2}
    df['target'] = df['outcome'].map(outcome_map)
    
    train_df_final = df.loc[fold2.index]
    val_df_final = df.iloc[split2:]
    
    X_train = train_df_final[all_features]
    y_train = train_df_final['target']
    X_val = val_df_final[all_features]
    y_val = val_df_final['target']
    
    logger.info(f"Train: {len(train_df_final)}, Val: {len(val_df_final)}")
    
    params = {
        'objective': 'multiclass',
        'num_class': 3,
        'metric': 'multi_logloss',
        'boosting_type': 'gbdt',
        'num_leaves': 31,
        'max_depth': 5,
        'learning_rate': 0.025,
        'min_data_in_leaf': 200,
        'feature_fraction': 0.75,
        'bagging_fraction': 0.75,
        'bagging_freq': 5,
        'lambda_l1': 0.7,
        'lambda_l2': 0.7,
        'verbosity': -1,
        'seed': 42,
        'n_jobs': -1
    }
    
    train_data = lgb.Dataset(X_train, label=y_train)
    val_data = lgb.Dataset(X_val, label=y_val, reference=train_data)
    
    logger.info("\nTraining V3 full model...")
    
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
    logger.info("V3 FULL MODEL RESULTS")
    logger.info("=" * 60)
    logger.info(f"  Accuracy: {accuracy:.4f} ({accuracy*100:.2f}%)")
    logger.info(f"  LogLoss: {logloss:.4f}")
    logger.info(f"  Best Iteration: {model.best_iteration}")
    
    importance = pd.DataFrame({
        'feature': all_features,
        'importance': model.feature_importance()
    }).sort_values('importance', ascending=False)
    
    logger.info("\nTop 20 Feature Importance:")
    for _, row in importance.head(20).iterrows():
        logger.info(f"  {row['feature']}: {row['importance']:.0f}")
    
    with open(OUTPUT_DIR / 'model.pkl', 'wb') as f:
        pickle.dump(model, f)
    
    for expert_type in experts.keys():
        with open(OUTPUT_DIR / f'{expert_type}_expert.pkl', 'wb') as f:
            pickle.dump(experts[expert_type], f)
        with open(OUTPUT_DIR / f'{expert_type}_calibrator.pkl', 'wb') as f:
            pickle.dump(calibrators[expert_type], f)
    
    metadata = {
        'version': 'v3_full_leakfree',
        'trained_at': datetime.now().isoformat(),
        'total_samples': len(df),
        'train_samples': len(train_df_final),
        'val_samples': len(val_df_final),
        'training_method': 'out-of-fold stacking with time-based splits',
        'features': {
            'base': BASE_FEATURES,
            'expert': EXPERT_FEATURES,
            'regime': REGIME_FEATURES,
            'all': all_features
        },
        'feature_counts': {
            'base': len(BASE_FEATURES),
            'expert': len(EXPERT_FEATURES),
            'regime': len(REGIME_FEATURES),
            'total': len(all_features)
        },
        'params': params,
        'metrics': {
            'accuracy': float(accuracy),
            'logloss': float(logloss),
            'best_iteration': model.best_iteration
        },
        'feature_importance': importance.head(25).to_dict('records')
    }
    
    with open(OUTPUT_DIR / 'metadata.json', 'w') as f:
        json.dump(metadata, f, indent=2)
    
    logger.info("\n" + "=" * 60)
    logger.info("COMPARISON VS ALL MODELS")
    logger.info("=" * 60)
    
    comparisons = [
        ("V2 Improved", "artifacts/models/v2_improved/metadata.json"),
        ("V3 Stacked", "artifacts/models/v3_stacked/metadata.json"),
    ]
    
    for name, path in comparisons:
        if Path(path).exists():
            with open(path) as f:
                meta = json.load(f)
            acc = meta['metrics']['accuracy']
            ll = meta['metrics']['logloss']
            logger.info(f"  {name}: {acc*100:.2f}% acc, {ll:.4f} logloss")
    
    logger.info(f"  V3 Full:    {accuracy*100:.2f}% acc, {logloss:.4f} logloss")
    
    logger.info(f"\nModel saved to: {OUTPUT_DIR}")
    
    return accuracy, logloss


if __name__ == '__main__':
    main()
