#!/usr/bin/env python3
"""
V3 Model Sanity Check - Uses pre-trained model for validation
A. Hard time-block test (last 3 months)
B. Book-only baseline
C. Per-league breakdown
"""

import os
import sys
import pickle
import json
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
from sklearn.metrics import accuracy_score, log_loss

sys.path.insert(0, str(Path(__file__).parent.parent))
from features.historical_feature_builder import HistoricalFeatureBuilder
from models.v3_ensemble_predictor import get_v3_ensemble_predictor

import logging
logging.basicConfig(level=logging.WARNING)

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


def main():
    print("=" * 70)
    print("V3 MODEL SANITY CHECK")
    print("Using pre-trained V3 model")
    print("=" * 70)
    
    predictor = get_v3_ensemble_predictor()
    print(f"\nV3 Model loaded: {predictor.is_loaded()}")
    model_info = predictor.get_model_info()
    print(f"Training accuracy: {model_info['accuracy']:.4f}")
    print(f"Training logloss: {model_info['logloss']:.4f}")
    
    print("\nLoading match data...")
    builder = HistoricalFeatureBuilder()
    raw_data = builder.get_all_features_for_training(min_date='2020-01-01')
    
    df = pd.DataFrame(raw_data)
    print(f"Total matches: {len(df)}")
    
    df['match_date'] = pd.to_datetime(df['match_date'])
    df = df.sort_values('match_date').reset_index(drop=True)
    
    for col in BASE_FEATURES:
        if col not in df.columns:
            df[col] = 0.0
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    
    max_date = df['match_date'].max()
    cutoff_date = max_date - timedelta(days=90)
    
    test_df = df[df['match_date'] >= cutoff_date].copy()
    
    print(f"\nTest period: {cutoff_date.strftime('%Y-%m-%d')} to {max_date.strftime('%Y-%m-%d')}")
    print(f"Test matches: {len(test_df)}")
    
    print("\n" + "=" * 70)
    print("A. V3 MODEL ON RECENT MATCHES")
    print("=" * 70)
    
    outcome_map = {'H': 0, 'D': 1, 'A': 2}
    v3_preds = []
    v3_probs = []
    
    for idx, row in test_df.iterrows():
        features = row[BASE_FEATURES].to_dict()
        result = predictor.predict(features)
        
        probs = result['probabilities']
        v3_probs.append([probs['home'], probs['draw'], probs['away']])
        v3_preds.append(outcome_map.get(result['prediction'], 0))
    
    v3_probs = np.array(v3_probs)
    v3_preds = np.array(v3_preds)
    y_true = test_df['outcome'].map(outcome_map).values
    
    v3_accuracy = accuracy_score(y_true, v3_preds)
    v3_logloss = log_loss(y_true, v3_probs)
    v3_brier = brier_score(y_true, v3_probs)
    
    print(f"\nV3 Results on {len(test_df)} recent matches:")
    print(f"  Accuracy: {v3_accuracy:.4f} ({v3_accuracy*100:.2f}%)")
    print(f"  LogLoss:  {v3_logloss:.4f}")
    print(f"  Brier:    {v3_brier:.4f}")
    
    print("\n" + "=" * 70)
    print("B. BOOK-ONLY BASELINE")
    print("=" * 70)
    
    has_ps = (test_df['p_ps_h'] > 0) & (test_df['p_ps_d'] > 0) & (test_df['p_ps_a'] > 0)
    
    if has_ps.sum() >= 50:
        test_book = test_df[has_ps].copy()
        total = test_book['p_ps_h'] + test_book['p_ps_d'] + test_book['p_ps_a']
        book_proba = np.column_stack([
            test_book['p_ps_h'] / total,
            test_book['p_ps_d'] / total,
            test_book['p_ps_a'] / total
        ])
        book_name = "Pinnacle"
        y_book = test_book['outcome'].map(outcome_map).values
    else:
        total = test_df['p_avg_h'] + test_df['p_avg_d'] + test_df['p_avg_a']
        book_proba = np.column_stack([
            test_df['p_avg_h'] / total,
            test_df['p_avg_d'] / total,
            test_df['p_avg_a'] / total
        ])
        book_name = "Average"
        y_book = y_true
    
    book_pred = np.argmax(book_proba, axis=1)
    book_accuracy = accuracy_score(y_book, book_pred)
    book_logloss = log_loss(y_book, book_proba)
    book_brier = brier_score(y_book, book_proba)
    
    print(f"\n{book_name} Book-Only ({len(y_book)} matches):")
    print(f"  Accuracy: {book_accuracy:.4f} ({book_accuracy*100:.2f}%)")
    print(f"  LogLoss:  {book_logloss:.4f}")
    print(f"  Brier:    {book_brier:.4f}")
    
    print("\n" + "=" * 70)
    print("C. PER-LEAGUE BREAKDOWN")
    print("=" * 70)
    
    if 'league_id' in test_df.columns:
        print(f"\n{'League':<12} {'Matches':<8} {'H/D/A Rate':<18} {'Book Acc':<10}")
        print("-" * 55)
        
        for league_id in sorted(test_df['league_id'].dropna().unique()):
            league_df = test_df[test_df['league_id'] == league_id]
            if len(league_df) < 3:
                continue
            
            h_rate = (league_df['outcome'] == 'H').mean()
            d_rate = (league_df['outcome'] == 'D').mean()
            a_rate = (league_df['outcome'] == 'A').mean()
            
            y_l = league_df['outcome'].map(outcome_map)
            total = league_df['p_avg_h'] + league_df['p_avg_d'] + league_df['p_avg_a']
            proba = np.column_stack([
                league_df['p_avg_h'] / total,
                league_df['p_avg_d'] / total,
                league_df['p_avg_a'] / total
            ])
            pred = np.argmax(proba, axis=1)
            acc = accuracy_score(y_l, pred)
            
            print(f"{int(league_id):<12} {len(league_df):<8} {h_rate:.2f}/{d_rate:.2f}/{a_rate:.2f}    {acc:.4f}")
    
    print("\n" + "=" * 70)
    print("D. HOME IMPLIED ODDS BANDS")
    print("=" * 70)
    
    print(f"\n{'Band':<15} {'Matches':<8} {'Actual H%':<12} {'Implied H%':<12}")
    print("-" * 50)
    
    bins = [(0.30, 0.40), (0.40, 0.50), (0.50, 0.60), (0.60, 0.75)]
    
    for low, high in bins:
        band_df = test_df[(test_df['p_avg_h'] >= low) & (test_df['p_avg_h'] < high)]
        if len(band_df) < 3:
            continue
        
        actual_h = (band_df['outcome'] == 'H').mean()
        implied_h = band_df['p_avg_h'].mean()
        
        print(f"{low:.2f}-{high:.2f}        {len(band_df):<8} {actual_h:.4f}       {implied_h:.4f}")
    
    print("\n" + "=" * 70)
    print("FINAL SUMMARY")
    print("=" * 70)
    
    print(f"\n                    Accuracy    LogLoss     Brier")
    print("-" * 55)
    print(f"Book-Only Baseline:  {book_accuracy:.4f}      {book_logloss:.4f}      {book_brier:.4f}")
    print(f"V3 Model:            {v3_accuracy:.4f}      {v3_logloss:.4f}      {v3_brier:.4f}")
    
    ll_diff = book_logloss - v3_logloss
    acc_diff = v3_accuracy - book_accuracy
    
    print(f"\n--- V3 vs Book-Only ---")
    print(f"  LogLoss improvement: {ll_diff:.4f} ({'BETTER' if ll_diff > 0 else 'WORSE'})")
    print(f"  Accuracy difference: {acc_diff*100:.2f}% ({'BETTER' if acc_diff > 0 else 'WORSE'})")
    
    if ll_diff > 0:
        print(f"\n✅ V3 PASSES LOGLOSS TEST")
    else:
        print(f"\n❌ V3 FAILS LOGLOSS TEST")
    
    if acc_diff >= 0:
        print(f"✅ V3 PASSES/TIES ACCURACY TEST")
    else:
        print(f"⚠️  V3 has lower accuracy (may be due to small sample)")
    
    results = {
        'test_period': f"{cutoff_date.strftime('%Y-%m-%d')} to {max_date.strftime('%Y-%m-%d')}",
        'test_matches': len(test_df),
        'v3': {'accuracy': v3_accuracy, 'logloss': v3_logloss, 'brier': v3_brier},
        'book': {'accuracy': book_accuracy, 'logloss': book_logloss, 'brier': book_brier},
        'logloss_improvement': ll_diff,
        'accuracy_improvement': acc_diff
    }
    
    output_path = Path('artifacts/models/v3_full/sanity_check.json')
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"\nResults saved to: {output_path}")


if __name__ == "__main__":
    main()
