#!/usr/bin/env python3
"""
V3 Model Sanity and Leakage Validation
A. Hard time-block test (one-shot train/test split)
B. Book-only baseline comparison
C. Per-league and per-odds-band breakdown
"""

import os
import sys
import pickle
import json
import numpy as np
import pandas as pd
import lightgbm as lgb
from pathlib import Path
from datetime import datetime, timedelta
from sklearn.metrics import accuracy_score, log_loss
from sklearn.isotonic import IsotonicRegression

sys.path.insert(0, str(Path(__file__).parent.parent))
from features.historical_feature_builder import HistoricalFeatureBuilder
from features.regime_feature_builder import RegimeFeatureBuilder

import logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')
logger = logging.getLogger(__name__)

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
    'upset_potential', 'book_agreement_score', 'implied_competitiveness',
    'sharp_home_signal', 'sharp_away_signal', 'sharp_draw_signal'
]

EXPERT_FEATURES = [
    'expert_home_prob', 'expert_away_prob', 'expert_draw_prob',
    'expert_home_away_diff', 'expert_draw_confidence', 'expert_favorite_spread',
    'expert_norm_home', 'expert_norm_away', 'expert_norm_draw'
]

REGIME_FEATURES = [
    'league_draw_regime', 'league_goals_regime', 'league_home_stability',
    'league_draw_volatility', 'odds_skewness', 'favorite_dominance',
    'draw_compression', 'sharp_agreement', 'day_of_week', 'is_weekend',
    'is_early_season', 'is_late_season', 'days_since_season_start',
    'season_progress'
]


def brier_score(y_true, y_pred_proba):
    """Calculate multiclass Brier score"""
    n_classes = y_pred_proba.shape[1]
    y_true_onehot = np.zeros((len(y_true), n_classes))
    for i, label in enumerate(y_true):
        y_true_onehot[i, label] = 1
    return np.mean(np.sum((y_pred_proba - y_true_onehot) ** 2, axis=1))


def train_binary_expert(X_train, y_train, expert_type):
    """Train a binary expert"""
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


def add_regime_features_fast(df):
    """Add regime features to dataframe (fast vectorized version)"""
    df = df.copy()
    
    df['match_date'] = pd.to_datetime(df['match_date'])
    df['day_of_week'] = df['match_date'].dt.dayofweek
    df['is_weekend'] = (df['day_of_week'] >= 5).astype(int)
    df['season_month'] = df['match_date'].dt.month
    df['is_early_season'] = (df['season_month'].isin([8, 9])).astype(int)
    df['is_late_season'] = (df['season_month'].isin([4, 5])).astype(int)
    df['days_since_season_start'] = (df['match_date'].dt.month - 8) * 30
    df['season_progress'] = np.clip(df['days_since_season_start'] / 300, 0, 1)
    
    df['odds_skewness'] = df['p_avg_h'] - df['p_avg_a']
    df['favorite_dominance'] = df[['p_avg_h', 'p_avg_a']].max(axis=1) - 0.5
    df['draw_compression'] = 0.27 - df['p_avg_d']
    df['sharp_agreement'] = 1 - abs(df['p_ps_h'] - df['p_avg_h']).fillna(0)
    
    for col in REGIME_FEATURES:
        if col not in df.columns:
            df[col] = 0.0
    
    df['league_draw_regime'] = df.get('league_draw_rate', 0.26)
    df['league_goals_regime'] = df.get('league_goals_avg', 2.5) / 3.0
    df['league_home_stability'] = df.get('league_home_win_rate', 0.45)
    df['league_draw_volatility'] = 0.05
    
    return df


def run_hard_time_block_test(df, test_months=3):
    """
    A. Hard time-block test
    Train on all matches up to date T, test on matches after T
    No folds, no mixing, no tuning on test
    """
    logger.info("\n" + "=" * 70)
    logger.info("A. HARD TIME-BLOCK TEST (One-Shot)")
    logger.info("=" * 70)
    
    df = df.sort_values('match_date').reset_index(drop=True)
    
    max_date = pd.to_datetime(df['match_date'].max())
    cutoff_date = max_date - timedelta(days=test_months * 30)
    
    df['match_date'] = pd.to_datetime(df['match_date'])
    train_df = df[df['match_date'] < cutoff_date].copy()
    test_df = df[df['match_date'] >= cutoff_date].copy()
    
    logger.info(f"Train: {len(train_df)} matches (up to {cutoff_date.strftime('%Y-%m-%d')})")
    logger.info(f"Test:  {len(test_df)} matches ({cutoff_date.strftime('%Y-%m-%d')} to {max_date.strftime('%Y-%m-%d')})")
    logger.info(f"Test period: ~{test_months} months")
    
    split1 = int(len(train_df) * 0.6)
    fold1 = train_df.iloc[:split1].copy()
    fold2 = train_df.iloc[split1:].copy()
    
    X_fold1 = fold1[BASE_FEATURES]
    
    experts = {}
    calibrators = {}
    
    for expert_type in ['home', 'away', 'draw']:
        target_map = {'home': 'H', 'away': 'A', 'draw': 'D'}
        y_fold1 = (fold1['outcome'] == target_map[expert_type]).astype(int)
        model = train_binary_expert(X_fold1, y_fold1, expert_type)
        experts[expert_type] = model
    
    X_fold2 = fold2[BASE_FEATURES]
    
    for expert_type, model in experts.items():
        raw_proba = model.predict(X_fold2)
        target_map = {'home': 'H', 'away': 'A', 'draw': 'D'}
        y_fold2 = (fold2['outcome'] == target_map[expert_type]).astype(int)
        
        calibrator = IsotonicRegression(out_of_bounds='clip')
        calibrator.fit(raw_proba, y_fold2)
        calibrators[expert_type] = calibrator
    
    for col in EXPERT_FEATURES:
        fold2[col] = 0.0
        test_df[col] = 0.0
    
    for expert_type, model in experts.items():
        raw_fold2 = model.predict(fold2[BASE_FEATURES])
        cal_fold2 = calibrators[expert_type].predict(raw_fold2)
        fold2[f'expert_{expert_type}_prob'] = np.clip(cal_fold2, 0.01, 0.99)
        
        raw_test = model.predict(test_df[BASE_FEATURES])
        cal_test = calibrators[expert_type].predict(raw_test)
        test_df[f'expert_{expert_type}_prob'] = np.clip(cal_test, 0.01, 0.99)
    
    for target_df in [fold2, test_df]:
        target_df['expert_home_away_diff'] = target_df['expert_home_prob'] - target_df['expert_away_prob']
        target_df['expert_draw_confidence'] = target_df['expert_draw_prob'] * target_df['implied_competitiveness']
        target_df['expert_favorite_spread'] = abs(target_df['expert_home_prob'] - target_df['expert_away_prob'])
        
        total = target_df['expert_home_prob'] + target_df['expert_away_prob'] + target_df['expert_draw_prob'] * 1.1
        target_df['expert_norm_home'] = target_df['expert_home_prob'] / total
        target_df['expert_norm_away'] = target_df['expert_away_prob'] / total
        target_df['expert_norm_draw'] = (target_df['expert_draw_prob'] * 1.1) / total
    
    fold2 = add_regime_features_fast(fold2)
    test_df = add_regime_features_fast(test_df)
    
    all_features = BASE_FEATURES + EXPERT_FEATURES + REGIME_FEATURES
    outcome_map = {'H': 0, 'D': 1, 'A': 2}
    
    X_train = fold2[all_features]
    y_train = fold2['outcome'].map(outcome_map)
    X_test = test_df[all_features]
    y_test = test_df['outcome'].map(outcome_map)
    
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
    model = lgb.train(params, train_data, num_boost_round=100)
    
    y_pred_proba = model.predict(X_test)
    y_pred = np.argmax(y_pred_proba, axis=1)
    
    accuracy = accuracy_score(y_test, y_pred)
    logloss = log_loss(y_test, y_pred_proba)
    brier = brier_score(y_test.values, y_pred_proba)
    
    logger.info("\n--- V3 HARD TIME-BLOCK RESULTS ---")
    logger.info(f"  Accuracy: {accuracy:.4f} ({accuracy*100:.2f}%)")
    logger.info(f"  LogLoss:  {logloss:.4f}")
    logger.info(f"  Brier:    {brier:.4f}")
    
    return {
        'accuracy': accuracy,
        'logloss': logloss,
        'brier': brier,
        'test_samples': len(test_df),
        'train_samples': len(train_df)
    }, test_df


def run_book_only_baseline(df):
    """
    B. Book-only baseline
    Use only sharp book implied probabilities (margin removed)
    """
    logger.info("\n" + "=" * 70)
    logger.info("B. BOOK-ONLY BASELINE (Sharp Book Implied Probs)")
    logger.info("=" * 70)
    
    df = df.copy()
    
    has_pinnacle = (df['p_ps_h'] > 0) & (df['p_ps_d'] > 0) & (df['p_ps_a'] > 0)
    df_pin = df[has_pinnacle].copy()
    
    if len(df_pin) < 100:
        logger.warning(f"Only {len(df_pin)} matches with Pinnacle odds, using average odds")
        df_pin = df.copy()
        df_pin['sharp_h'] = df_pin['p_avg_h']
        df_pin['sharp_d'] = df_pin['p_avg_d']
        df_pin['sharp_a'] = df_pin['p_avg_a']
    else:
        df_pin['sharp_h'] = df_pin['p_ps_h']
        df_pin['sharp_d'] = df_pin['p_ps_d']
        df_pin['sharp_a'] = df_pin['p_ps_a']
    
    total = df_pin['sharp_h'] + df_pin['sharp_d'] + df_pin['sharp_a']
    df_pin['norm_h'] = df_pin['sharp_h'] / total
    df_pin['norm_d'] = df_pin['sharp_d'] / total
    df_pin['norm_a'] = df_pin['sharp_a'] / total
    
    outcome_map = {'H': 0, 'D': 1, 'A': 2}
    y_true = df_pin['outcome'].map(outcome_map)
    
    y_pred_proba = df_pin[['norm_h', 'norm_d', 'norm_a']].values
    y_pred = np.argmax(y_pred_proba, axis=1)
    
    accuracy = accuracy_score(y_true, y_pred)
    logloss = log_loss(y_true, y_pred_proba)
    brier = brier_score(y_true.values, y_pred_proba)
    
    logger.info(f"\nBook-only baseline ({len(df_pin)} matches):")
    logger.info(f"  Accuracy: {accuracy:.4f} ({accuracy*100:.2f}%)")
    logger.info(f"  LogLoss:  {logloss:.4f}")
    logger.info(f"  Brier:    {brier:.4f}")
    
    return {
        'accuracy': accuracy,
        'logloss': logloss,
        'brier': brier,
        'samples': len(df_pin)
    }


def run_per_league_breakdown(test_df, v3_results):
    """
    C. Per-league and per-odds-band breakdown
    """
    logger.info("\n" + "=" * 70)
    logger.info("C. PER-LEAGUE AND PER-ODDS-BAND BREAKDOWN")
    logger.info("=" * 70)
    
    if 'league_id' not in test_df.columns:
        logger.warning("No league_id column found, skipping per-league breakdown")
        return {}
    
    logger.info("\n--- PER-LEAGUE BREAKDOWN ---")
    logger.info(f"{'League ID':<12} {'Matches':<10} {'Accuracy':<12} {'LogLoss':<12}")
    logger.info("-" * 50)
    
    league_results = {}
    outcome_map = {'H': 0, 'D': 1, 'A': 2}
    
    for league_id in sorted(test_df['league_id'].unique()):
        league_df = test_df[test_df['league_id'] == league_id]
        if len(league_df) < 10:
            continue
        
        y_true = league_df['outcome'].map(outcome_map)
        
        y_pred_proba = league_df[['norm_h', 'norm_d', 'norm_a']].values if 'norm_h' in league_df.columns else None
        
        if y_pred_proba is None:
            total = league_df['p_avg_h'] + league_df['p_avg_d'] + league_df['p_avg_a']
            y_pred_proba = np.column_stack([
                league_df['p_avg_h'] / total,
                league_df['p_avg_d'] / total,
                league_df['p_avg_a'] / total
            ])
        
        y_pred = np.argmax(y_pred_proba, axis=1)
        
        try:
            acc = accuracy_score(y_true, y_pred)
            ll = log_loss(y_true, y_pred_proba, labels=[0, 1, 2])
            
            league_results[league_id] = {
                'matches': len(league_df),
                'accuracy': acc,
                'logloss': ll
            }
            
            logger.info(f"{league_id:<12} {len(league_df):<10} {acc:.4f}       {ll:.4f}")
        except Exception as e:
            logger.warning(f"League {league_id}: {e}")
    
    logger.info("\n--- PER HOME-ODDS-BAND BREAKDOWN ---")
    logger.info(f"{'Home Implied':<15} {'Matches':<10} {'Accuracy':<12} {'Book Acc':<12}")
    logger.info("-" * 55)
    
    bins = [(0.30, 0.40), (0.40, 0.50), (0.50, 0.60), (0.60, 0.75)]
    
    for low, high in bins:
        band_df = test_df[(test_df['p_avg_h'] >= low) & (test_df['p_avg_h'] < high)]
        if len(band_df) < 10:
            continue
        
        y_true = band_df['outcome'].map(outcome_map)
        
        total = band_df['p_avg_h'] + band_df['p_avg_d'] + band_df['p_avg_a']
        book_proba = np.column_stack([
            band_df['p_avg_h'] / total,
            band_df['p_avg_d'] / total,
            band_df['p_avg_a'] / total
        ])
        book_pred = np.argmax(book_proba, axis=1)
        book_acc = accuracy_score(y_true, book_pred)
        
        actual_home_rate = (band_df['outcome'] == 'H').mean()
        
        logger.info(f"{low:.2f}-{high:.2f}        {len(band_df):<10} {actual_home_rate:.4f}       {book_acc:.4f}")
    
    logger.info("\n--- PER DRAW-ODDS-BAND BREAKDOWN ---")
    logger.info(f"{'Draw Implied':<15} {'Matches':<10} {'Draw Rate':<12} {'Book Acc':<12}")
    logger.info("-" * 55)
    
    draw_bins = [(0.20, 0.25), (0.25, 0.30), (0.30, 0.35), (0.35, 0.45)]
    
    for low, high in draw_bins:
        band_df = test_df[(test_df['p_avg_d'] >= low) & (test_df['p_avg_d'] < high)]
        if len(band_df) < 10:
            continue
        
        y_true = band_df['outcome'].map(outcome_map)
        actual_draw_rate = (band_df['outcome'] == 'D').mean()
        
        total = band_df['p_avg_h'] + band_df['p_avg_d'] + band_df['p_avg_a']
        book_proba = np.column_stack([
            band_df['p_avg_h'] / total,
            band_df['p_avg_d'] / total,
            band_df['p_avg_a'] / total
        ])
        book_pred = np.argmax(book_proba, axis=1)
        book_acc = accuracy_score(y_true, book_pred)
        
        logger.info(f"{low:.2f}-{high:.2f}        {len(band_df):<10} {actual_draw_rate:.4f}       {book_acc:.4f}")
    
    return league_results


def main():
    logger.info("=" * 70)
    logger.info("V3 MODEL SANITY AND LEAKAGE VALIDATION")
    logger.info("=" * 70)
    
    builder = HistoricalFeatureBuilder()
    raw_data = builder.get_all_features_for_training(min_date='2020-01-01')
    
    df = pd.DataFrame(raw_data)
    logger.info(f"Loaded {len(df)} matches")
    
    df = df.sort_values('match_date').reset_index(drop=True)
    
    for col in BASE_FEATURES:
        if col not in df.columns:
            df[col] = 0.0
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    
    v3_results, test_df = run_hard_time_block_test(df, test_months=3)
    
    book_results = run_book_only_baseline(df)
    
    league_results = run_per_league_breakdown(test_df, v3_results)
    
    logger.info("\n" + "=" * 70)
    logger.info("FINAL COMPARISON SUMMARY")
    logger.info("=" * 70)
    
    logger.info("\n                    Accuracy    LogLoss     Brier")
    logger.info("-" * 55)
    logger.info(f"Book-Only Baseline:  {book_results['accuracy']:.4f}      {book_results['logloss']:.4f}      {book_results['brier']:.4f}")
    logger.info(f"V3 Hard Time-Block:  {v3_results['accuracy']:.4f}      {v3_results['logloss']:.4f}      {v3_results['brier']:.4f}")
    
    ll_diff = book_results['logloss'] - v3_results['logloss']
    acc_diff = v3_results['accuracy'] - book_results['accuracy']
    
    logger.info("\n--- V3 vs Book-Only ---")
    logger.info(f"  LogLoss improvement: {ll_diff:.4f} ({'BETTER' if ll_diff > 0 else 'WORSE'})")
    logger.info(f"  Accuracy difference: {acc_diff*100:.2f}% ({'BETTER' if acc_diff > 0 else 'WORSE'})")
    
    if ll_diff > 0 and acc_diff > 0:
        logger.info("\n✅ V3 PASSES: Beats book-only baseline on both LogLoss and Accuracy")
        logger.info("   This suggests V3 is adding real signal beyond book implied probabilities")
    elif ll_diff > 0:
        logger.info("\n⚠️  V3 PARTIAL: Beats book on LogLoss but not Accuracy")
        logger.info("   V3 has better calibration but may not improve top-1 picks")
    else:
        logger.info("\n❌ V3 FAILS: Does not beat book-only baseline on LogLoss")
        logger.info("   V3 may be learning book quirks rather than adding signal")
    
    results = {
        'v3_hard_timeblock': v3_results,
        'book_only_baseline': book_results,
        'per_league': league_results,
        'validation_date': datetime.now().isoformat()
    }
    
    output_path = Path('artifacts/models/v3_full/validation_results.json')
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    
    logger.info(f"\nResults saved to: {output_path}")
    
    return results


if __name__ == "__main__":
    main()
