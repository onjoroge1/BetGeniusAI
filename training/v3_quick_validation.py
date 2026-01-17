#!/usr/bin/env python3
"""
V3 Model Quick Validation - Sanity and Leakage Checks
A. Hard time-block test
B. Book-only baseline
C. Per-league breakdown
"""

import os
import sys
import numpy as np
import pandas as pd
import lightgbm as lgb
from pathlib import Path
from datetime import datetime, timedelta
from sklearn.metrics import accuracy_score, log_loss
from sklearn.isotonic import IsotonicRegression

sys.path.insert(0, str(Path(__file__).parent.parent))
from features.historical_feature_builder import HistoricalFeatureBuilder

import logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(message)s')
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


def brier_score(y_true, y_pred_proba):
    """Calculate multiclass Brier score"""
    n_classes = y_pred_proba.shape[1]
    y_true_onehot = np.zeros((len(y_true), n_classes))
    for i, label in enumerate(y_true):
        y_true_onehot[i, int(label)] = 1
    return np.mean(np.sum((y_pred_proba - y_true_onehot) ** 2, axis=1))


def train_v3_model(train_df, val_df):
    """Train V3 model with binary experts and stacked meta"""
    
    split1 = int(len(train_df) * 0.6)
    fold1 = train_df.iloc[:split1].copy()
    fold2 = train_df.iloc[split1:].copy()
    
    experts = {}
    calibrators = {}
    
    for expert_type in ['home', 'away', 'draw']:
        target_map = {'home': 'H', 'away': 'A', 'draw': 'D'}
        y_fold1 = (fold1['outcome'] == target_map[expert_type]).astype(int)
        
        params = {
            'objective': 'binary',
            'metric': 'binary_logloss',
            'boosting_type': 'gbdt',
            'num_leaves': 31 if expert_type != 'draw' else 25,
            'max_depth': 5 if expert_type != 'draw' else 4,
            'learning_rate': 0.05 if expert_type != 'draw' else 0.03,
            'min_data_in_leaf': 200,
            'verbosity': -1,
            'seed': 42
        }
        if expert_type == 'draw':
            params['scale_pos_weight'] = 2.5
        
        train_data = lgb.Dataset(fold1[BASE_FEATURES], label=y_fold1)
        model = lgb.train(params, train_data, num_boost_round=100)
        experts[expert_type] = model
        
        raw_proba = model.predict(fold2[BASE_FEATURES])
        y_fold2 = (fold2['outcome'] == target_map[expert_type]).astype(int)
        calibrator = IsotonicRegression(out_of_bounds='clip')
        calibrator.fit(raw_proba, y_fold2)
        calibrators[expert_type] = calibrator
    
    for target_df in [fold2, val_df]:
        for expert_type, model in experts.items():
            raw = model.predict(target_df[BASE_FEATURES])
            cal = calibrators[expert_type].predict(raw)
            target_df[f'expert_{expert_type}_prob'] = np.clip(cal, 0.01, 0.99)
        
        target_df['expert_home_away_diff'] = target_df['expert_home_prob'] - target_df['expert_away_prob']
        target_df['expert_draw_confidence'] = target_df['expert_draw_prob'] * target_df.get('implied_competitiveness', 0.5)
        target_df['expert_favorite_spread'] = abs(target_df['expert_home_prob'] - target_df['expert_away_prob'])
        
        total = target_df['expert_home_prob'] + target_df['expert_away_prob'] + target_df['expert_draw_prob'] * 1.1
        target_df['expert_norm_home'] = target_df['expert_home_prob'] / total
        target_df['expert_norm_away'] = target_df['expert_away_prob'] / total
        target_df['expert_norm_draw'] = (target_df['expert_draw_prob'] * 1.1) / total
    
    expert_features = [
        'expert_home_prob', 'expert_away_prob', 'expert_draw_prob',
        'expert_home_away_diff', 'expert_draw_confidence', 'expert_favorite_spread',
        'expert_norm_home', 'expert_norm_away', 'expert_norm_draw'
    ]
    
    all_features = BASE_FEATURES + expert_features
    outcome_map = {'H': 0, 'D': 1, 'A': 2}
    
    X_train = fold2[all_features]
    y_train = fold2['outcome'].map(outcome_map)
    
    params = {
        'objective': 'multiclass',
        'num_class': 3,
        'metric': 'multi_logloss',
        'num_leaves': 31,
        'max_depth': 5,
        'learning_rate': 0.025,
        'min_data_in_leaf': 200,
        'verbosity': -1,
        'seed': 42
    }
    
    train_data = lgb.Dataset(X_train, label=y_train)
    meta_model = lgb.train(params, train_data, num_boost_round=100)
    
    X_val = val_df[all_features]
    y_val = val_df['outcome'].map(outcome_map)
    
    y_pred_proba = meta_model.predict(X_val)
    y_pred = np.argmax(y_pred_proba, axis=1)
    
    return {
        'accuracy': accuracy_score(y_val, y_pred),
        'logloss': log_loss(y_val, y_pred_proba),
        'brier': brier_score(y_val.values, y_pred_proba)
    }


def main():
    print("=" * 70)
    print("V3 MODEL SANITY AND LEAKAGE VALIDATION")
    print("=" * 70)
    
    builder = HistoricalFeatureBuilder()
    raw_data = builder.get_all_features_for_training(min_date='2020-01-01')
    
    df = pd.DataFrame(raw_data)
    print(f"\nLoaded {len(df)} matches")
    
    df['match_date'] = pd.to_datetime(df['match_date'])
    df = df.sort_values('match_date').reset_index(drop=True)
    
    for col in BASE_FEATURES:
        if col not in df.columns:
            df[col] = 0.0
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    
    print("\n" + "=" * 70)
    print("A. HARD TIME-BLOCK TEST (One-Shot)")
    print("=" * 70)
    
    max_date = df['match_date'].max()
    cutoff_date = max_date - timedelta(days=90)
    
    train_df = df[df['match_date'] < cutoff_date].copy()
    test_df = df[df['match_date'] >= cutoff_date].copy()
    
    print(f"Train: {len(train_df)} matches (up to {cutoff_date.strftime('%Y-%m-%d')})")
    print(f"Test:  {len(test_df)} matches ({cutoff_date.strftime('%Y-%m-%d')} to {max_date.strftime('%Y-%m-%d')})")
    
    v3_results = train_v3_model(train_df, test_df)
    
    print(f"\n--- V3 HARD TIME-BLOCK RESULTS ---")
    print(f"  Accuracy: {v3_results['accuracy']:.4f} ({v3_results['accuracy']*100:.2f}%)")
    print(f"  LogLoss:  {v3_results['logloss']:.4f}")
    print(f"  Brier:    {v3_results['brier']:.4f}")
    
    print("\n" + "=" * 70)
    print("B. BOOK-ONLY BASELINE (Sharp Book Implied Probs)")
    print("=" * 70)
    
    outcome_map = {'H': 0, 'D': 1, 'A': 2}
    
    has_ps = (test_df['p_ps_h'] > 0) & (test_df['p_ps_d'] > 0) & (test_df['p_ps_a'] > 0)
    test_ps = test_df[has_ps].copy()
    
    if len(test_ps) >= 50:
        total = test_ps['p_ps_h'] + test_ps['p_ps_d'] + test_ps['p_ps_a']
        book_proba = np.column_stack([
            test_ps['p_ps_h'] / total,
            test_ps['p_ps_d'] / total,
            test_ps['p_ps_a'] / total
        ])
        book_name = "Pinnacle"
    else:
        total = test_df['p_avg_h'] + test_df['p_avg_d'] + test_df['p_avg_a']
        book_proba = np.column_stack([
            test_df['p_avg_h'] / total,
            test_df['p_avg_d'] / total,
            test_df['p_avg_a'] / total
        ])
        test_ps = test_df
        book_name = "Average"
    
    y_true = test_ps['outcome'].map(outcome_map)
    book_pred = np.argmax(book_proba, axis=1)
    
    book_accuracy = accuracy_score(y_true, book_pred)
    book_logloss = log_loss(y_true, book_proba)
    book_brier = brier_score(y_true.values, book_proba)
    
    print(f"\n{book_name} book-only baseline ({len(test_ps)} matches):")
    print(f"  Accuracy: {book_accuracy:.4f} ({book_accuracy*100:.2f}%)")
    print(f"  LogLoss:  {book_logloss:.4f}")
    print(f"  Brier:    {book_brier:.4f}")
    
    print("\n" + "=" * 70)
    print("C. PER-LEAGUE BREAKDOWN")
    print("=" * 70)
    
    if 'league_id' in test_df.columns:
        print(f"\n{'League ID':<12} {'Matches':<10} {'Actual H/D/A':<20} {'Book Acc':<10}")
        print("-" * 60)
        
        for league_id in sorted(test_df['league_id'].dropna().unique()):
            league_df = test_df[test_df['league_id'] == league_id]
            if len(league_df) < 5:
                continue
            
            h_rate = (league_df['outcome'] == 'H').mean()
            d_rate = (league_df['outcome'] == 'D').mean()
            a_rate = (league_df['outcome'] == 'A').mean()
            
            y_true = league_df['outcome'].map(outcome_map)
            total = league_df['p_avg_h'] + league_df['p_avg_d'] + league_df['p_avg_a']
            proba = np.column_stack([
                league_df['p_avg_h'] / total,
                league_df['p_avg_d'] / total,
                league_df['p_avg_a'] / total
            ])
            pred = np.argmax(proba, axis=1)
            acc = accuracy_score(y_true, pred)
            
            print(f"{int(league_id):<12} {len(league_df):<10} {h_rate:.2f}/{d_rate:.2f}/{a_rate:.2f}        {acc:.4f}")
    
    print("\n" + "=" * 70)
    print("D. PER HOME-ODDS-BAND BREAKDOWN")
    print("=" * 70)
    
    print(f"\n{'Home Implied':<15} {'Matches':<10} {'Actual H%':<12} {'Book Acc':<10}")
    print("-" * 55)
    
    bins = [(0.30, 0.40), (0.40, 0.50), (0.50, 0.60), (0.60, 0.75)]
    
    for low, high in bins:
        band_df = test_df[(test_df['p_avg_h'] >= low) & (test_df['p_avg_h'] < high)]
        if len(band_df) < 5:
            continue
        
        actual_h = (band_df['outcome'] == 'H').mean()
        
        y_true = band_df['outcome'].map(outcome_map)
        total = band_df['p_avg_h'] + band_df['p_avg_d'] + band_df['p_avg_a']
        proba = np.column_stack([
            band_df['p_avg_h'] / total,
            band_df['p_avg_d'] / total,
            band_df['p_avg_a'] / total
        ])
        pred = np.argmax(proba, axis=1)
        acc = accuracy_score(y_true, pred)
        
        print(f"{low:.2f}-{high:.2f}        {len(band_df):<10} {actual_h:.4f}       {acc:.4f}")
    
    print("\n" + "=" * 70)
    print("FINAL COMPARISON SUMMARY")
    print("=" * 70)
    
    print(f"\n                    Accuracy    LogLoss     Brier")
    print("-" * 55)
    print(f"Book-Only Baseline:  {book_accuracy:.4f}      {book_logloss:.4f}      {book_brier:.4f}")
    print(f"V3 Hard Time-Block:  {v3_results['accuracy']:.4f}      {v3_results['logloss']:.4f}      {v3_results['brier']:.4f}")
    
    ll_diff = book_logloss - v3_results['logloss']
    acc_diff = v3_results['accuracy'] - book_accuracy
    
    print(f"\n--- V3 vs Book-Only ---")
    print(f"  LogLoss improvement: {ll_diff:.4f} ({'BETTER' if ll_diff > 0 else 'WORSE'})")
    print(f"  Accuracy difference: {acc_diff*100:.2f}% ({'BETTER' if acc_diff > 0 else 'WORSE'})")
    
    if ll_diff > 0:
        print(f"\n✅ V3 PASSES LOGLOSS: Beats book-only baseline")
        print("   V3 is adding real signal beyond book implied probabilities")
    else:
        print(f"\n⚠️  V3 FAILS LOGLOSS: Does not beat book-only baseline")
        print("   V3 may be learning book quirks rather than adding signal")
    
    if acc_diff > 0:
        print(f"✅ V3 PASSES ACCURACY: Higher top-1 pick accuracy")
    else:
        print(f"⚠️  V3 FAILS ACCURACY: Lower top-1 pick accuracy than book")


if __name__ == "__main__":
    main()
