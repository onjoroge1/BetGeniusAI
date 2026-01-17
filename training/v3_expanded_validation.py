#!/usr/bin/env python3
"""
V3 Expanded Validation - Robust statistical testing
- Larger holdout (6-12 months)
- Proper de-vig methodology shown
- Per-outcome reliability tables
- Statistical confidence bounds
"""

import os
import sys
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
    """Multiclass Brier score"""
    n_classes = y_pred_proba.shape[1]
    y_true_onehot = np.zeros((len(y_true), n_classes))
    for i, label in enumerate(y_true):
        y_true_onehot[i, int(label)] = 1
    return np.mean(np.sum((y_pred_proba - y_true_onehot) ** 2, axis=1))


def de_vig_pinnacle(p_h, p_d, p_a, method='normalize'):
    """
    De-vig Pinnacle implied probabilities.
    
    Method: 'normalize' - Simple normalization (divide by total)
    This is the standard approach for 3-way markets.
    
    Raw Pinnacle implied probs sum to ~1.03-1.04 (the margin).
    After de-vig, they sum to exactly 1.0.
    """
    total = p_h + p_d + p_a
    
    if method == 'normalize':
        return p_h / total, p_d / total, p_a / total
    else:
        return p_h / total, p_d / total, p_a / total


def multiclass_logloss(y_true, y_pred_proba, eps=1e-15):
    """
    Multiclass log loss (cross-entropy).
    
    y_true: array of class labels (0, 1, 2 for H, D, A)
    y_pred_proba: array of shape (n_samples, 3) with probabilities
    
    LogLoss = -1/N * sum(log(p_true_class))
    
    Lower is better. Perfect = 0.0, Random = log(3) ≈ 1.099
    """
    y_pred_proba = np.clip(y_pred_proba, eps, 1 - eps)
    y_pred_proba = y_pred_proba / y_pred_proba.sum(axis=1, keepdims=True)
    
    n = len(y_true)
    ll = 0.0
    for i in range(n):
        ll += np.log(y_pred_proba[i, int(y_true[i])])
    
    return -ll / n


def reliability_table(y_true, y_pred_proba, outcome_idx, bins=10):
    """
    Build reliability table for a specific outcome.
    Shows calibration: predicted probability vs actual frequency.
    """
    probs = y_pred_proba[:, outcome_idx]
    actual = (y_true == outcome_idx).astype(int)
    
    bin_edges = np.linspace(0, 1, bins + 1)
    results = []
    
    for i in range(bins):
        mask = (probs >= bin_edges[i]) & (probs < bin_edges[i + 1])
        if mask.sum() > 0:
            results.append({
                'bin': f'{bin_edges[i]:.2f}-{bin_edges[i+1]:.2f}',
                'count': mask.sum(),
                'mean_pred': probs[mask].mean(),
                'actual_freq': actual[mask].mean(),
                'calibration_error': abs(probs[mask].mean() - actual[mask].mean())
            })
    
    return results


def bootstrap_confidence(y_true, y_pred_proba_v3, y_pred_proba_book, n_bootstrap=1000):
    """
    Bootstrap confidence interval for LogLoss difference.
    """
    n = len(y_true)
    ll_diffs = []
    
    for _ in range(n_bootstrap):
        idx = np.random.choice(n, n, replace=True)
        ll_v3 = multiclass_logloss(y_true[idx], y_pred_proba_v3[idx])
        ll_book = multiclass_logloss(y_true[idx], y_pred_proba_book[idx])
        ll_diffs.append(ll_book - ll_v3)
    
    ll_diffs = np.array(ll_diffs)
    return {
        'mean': ll_diffs.mean(),
        'std': ll_diffs.std(),
        'ci_lower': np.percentile(ll_diffs, 2.5),
        'ci_upper': np.percentile(ll_diffs, 97.5),
        'prob_v3_better': (ll_diffs > 0).mean()
    }


def main():
    print("=" * 70)
    print("V3 EXPANDED VALIDATION")
    print("Robust statistical testing with proper methodology")
    print("=" * 70)
    
    print("\n--- METHODOLOGY ---")
    print("""
De-vig Method for Pinnacle:
  - Raw Pinnacle implied probs sum to ~1.03-1.04 (margin)
  - De-vig by simple normalization: p_devig = p_raw / sum(p_raw)
  - This is standard for 3-way markets

Multiclass LogLoss Formula:
  - LogLoss = -1/N * sum(log(p_true_class))
  - Measures probability quality (lower is better)
  - Perfect = 0.0, Random uniform = log(3) ≈ 1.099

Outcome Mapping:
  - H = 0 (Home win)
  - D = 1 (Draw)
  - A = 2 (Away win)
  - Aligned with how odds are recorded in matches table
""")
    
    predictor = get_v3_ensemble_predictor()
    print(f"\nV3 Model loaded: {predictor.is_loaded()}")
    
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
    
    holdout_months = 12
    cutoff_date = max_date - timedelta(days=holdout_months * 30)
    
    train_end = max_date - timedelta(days=holdout_months * 30 + 90)
    
    train_df = df[df['match_date'] <= train_end].copy()
    test_df = df[df['match_date'] > train_end].copy()
    
    print(f"\n--- DATA SPLIT ---")
    print(f"Training data: up to {train_end.strftime('%Y-%m-%d')} ({len(train_df)} matches)")
    print(f"Holdout data: {train_end.strftime('%Y-%m-%d')} to {max_date.strftime('%Y-%m-%d')} ({len(test_df)} matches)")
    print(f"Holdout period: ~{(max_date - train_end).days} days")
    
    has_ps = (test_df['p_ps_h'] > 0) & (test_df['p_ps_d'] > 0) & (test_df['p_ps_a'] > 0)
    test_df = test_df[has_ps].copy()
    print(f"Matches with Pinnacle odds: {len(test_df)}")
    
    print(f"\n--- PINNACLE MARGIN CHECK ---")
    raw_total = test_df['p_ps_h'] + test_df['p_ps_d'] + test_df['p_ps_a']
    print(f"Raw Pinnacle total (before de-vig):")
    print(f"  Mean: {raw_total.mean():.4f} (margin = {(raw_total.mean()-1)*100:.2f}%)")
    print(f"  Min:  {raw_total.min():.4f}")
    print(f"  Max:  {raw_total.max():.4f}")
    
    outcome_map = {'H': 0, 'D': 1, 'A': 2}
    y_true = test_df['outcome'].map(outcome_map).values
    
    print(f"\n--- OUTCOME DISTRIBUTION ---")
    print(f"Home wins: {(y_true == 0).sum()} ({(y_true == 0).mean()*100:.1f}%)")
    print(f"Draws:     {(y_true == 1).sum()} ({(y_true == 1).mean()*100:.1f}%)")
    print(f"Away wins: {(y_true == 2).sum()} ({(y_true == 2).mean()*100:.1f}%)")
    
    print("\n" + "=" * 70)
    print("COMPUTING PREDICTIONS")
    print("=" * 70)
    
    book_probs = []
    for idx, row in test_df.iterrows():
        p_h, p_d, p_a = de_vig_pinnacle(row['p_ps_h'], row['p_ps_d'], row['p_ps_a'])
        book_probs.append([p_h, p_d, p_a])
    book_probs = np.array(book_probs)
    
    print("Pinnacle de-vigged: ✓")
    print(f"  De-vigged total check: {book_probs.sum(axis=1).mean():.6f} (should be 1.0)")
    
    v3_probs = []
    for idx, row in test_df.iterrows():
        features = row[BASE_FEATURES].to_dict()
        result = predictor.predict(features)
        probs = result['probabilities']
        v3_probs.append([probs['home'], probs['draw'], probs['away']])
    v3_probs = np.array(v3_probs)
    
    v3_probs = v3_probs / v3_probs.sum(axis=1, keepdims=True)
    
    print("V3 predictions: ✓")
    print(f"  V3 total check: {v3_probs.sum(axis=1).mean():.6f} (should be 1.0)")
    
    print("\n" + "=" * 70)
    print("RESULTS")
    print("=" * 70)
    
    book_pred = np.argmax(book_probs, axis=1)
    v3_pred = np.argmax(v3_probs, axis=1)
    
    book_acc = accuracy_score(y_true, book_pred)
    v3_acc = accuracy_score(y_true, v3_pred)
    
    book_ll = multiclass_logloss(y_true, book_probs)
    v3_ll = multiclass_logloss(y_true, v3_probs)
    
    book_brier = brier_score(y_true, book_probs)
    v3_brier = brier_score(y_true, v3_probs)
    
    print(f"\n                    Accuracy    LogLoss     Brier       N")
    print("-" * 65)
    print(f"Pinnacle De-vigged:  {book_acc:.4f}      {book_ll:.4f}      {book_brier:.4f}      {len(test_df)}")
    print(f"V3 Model:            {v3_acc:.4f}      {v3_ll:.4f}      {v3_brier:.4f}      {len(test_df)}")
    print("-" * 65)
    print(f"Difference:          {v3_acc - book_acc:+.4f}      {book_ll - v3_ll:+.4f}      {book_brier - v3_brier:+.4f}")
    
    print("\n" + "=" * 70)
    print("STATISTICAL CONFIDENCE (Bootstrap)")
    print("=" * 70)
    
    print("\nRunning 1000 bootstrap samples...")
    ci = bootstrap_confidence(y_true, v3_probs, book_probs)
    
    print(f"\nLogLoss improvement (V3 vs Pinnacle):")
    print(f"  Mean: {ci['mean']:.4f}")
    print(f"  Std:  {ci['std']:.4f}")
    print(f"  95% CI: [{ci['ci_lower']:.4f}, {ci['ci_upper']:.4f}]")
    print(f"  P(V3 better): {ci['prob_v3_better']*100:.1f}%")
    
    if ci['ci_lower'] > 0:
        print("\n✅ STATISTICALLY SIGNIFICANT: 95% CI excludes zero")
    elif ci['prob_v3_better'] > 0.9:
        print("\n⚠️  LIKELY BETTER: 90%+ probability V3 beats Pinnacle, but CI includes zero")
    else:
        print("\n❓ INCONCLUSIVE: Need more data to establish significance")
    
    print("\n" + "=" * 70)
    print("RELIABILITY TABLES (Calibration)")
    print("=" * 70)
    
    outcome_names = ['Home', 'Draw', 'Away']
    
    for oidx, oname in enumerate(outcome_names):
        print(f"\n--- {oname} Win Reliability ---")
        print(f"{'Pred Bin':<12} {'Count':<8} {'Mean Pred':<12} {'Actual':<12} {'Cal Error':<10}")
        print("-" * 55)
        
        rel = reliability_table(y_true, v3_probs, oidx, bins=5)
        for r in rel:
            print(f"{r['bin']:<12} {r['count']:<8} {r['mean_pred']:.4f}       {r['actual_freq']:.4f}       {r['calibration_error']:.4f}")
    
    print("\n" + "=" * 70)
    print("PER-LEAGUE ANALYSIS")
    print("=" * 70)
    
    if 'league_id' in test_df.columns:
        print(f"\n{'League':<10} {'N':<6} {'Book Acc':<10} {'V3 Acc':<10} {'Book LL':<10} {'V3 LL':<10} {'LL Diff':<10}")
        print("-" * 70)
        
        league_results = []
        for league_id in sorted(test_df['league_id'].dropna().unique()):
            mask = test_df['league_id'] == league_id
            if mask.sum() < 20:
                continue
            
            y_l = y_true[mask.values]
            book_l = book_probs[mask.values]
            v3_l = v3_probs[mask.values]
            
            book_acc_l = accuracy_score(y_l, np.argmax(book_l, axis=1))
            v3_acc_l = accuracy_score(y_l, np.argmax(v3_l, axis=1))
            book_ll_l = multiclass_logloss(y_l, book_l)
            v3_ll_l = multiclass_logloss(y_l, v3_l)
            
            ll_diff = book_ll_l - v3_ll_l
            
            print(f"{int(league_id):<10} {mask.sum():<6} {book_acc_l:.4f}     {v3_acc_l:.4f}     {book_ll_l:.4f}     {v3_ll_l:.4f}     {ll_diff:+.4f}")
            
            league_results.append({
                'league_id': int(league_id),
                'n': int(mask.sum()),
                'book_acc': book_acc_l,
                'v3_acc': v3_acc_l,
                'book_ll': book_ll_l,
                'v3_ll': v3_ll_l,
                'll_diff': ll_diff
            })
    
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    
    ll_improvement = book_ll - v3_ll
    
    if ll_improvement > 0 and ci['prob_v3_better'] > 0.9:
        verdict = "✅ V3 shows evidence of incremental probability-quality improvement vs Pinnacle"
    elif ll_improvement > 0:
        verdict = "⚠️  V3 shows slight improvement, but need larger sample for confidence"
    else:
        verdict = "❌ V3 does not beat Pinnacle on this holdout"
    
    print(f"\n{verdict}")
    print(f"\nKey metrics:")
    print(f"  - LogLoss improvement: {ll_improvement:.4f}")
    print(f"  - Bootstrap P(V3 better): {ci['prob_v3_better']*100:.1f}%")
    print(f"  - Sample size: {len(test_df)} matches")
    
    results = {
        'holdout_period': f"{train_end.strftime('%Y-%m-%d')} to {max_date.strftime('%Y-%m-%d')}",
        'n_matches': len(test_df),
        'pinnacle': {
            'accuracy': float(book_acc),
            'logloss': float(book_ll),
            'brier': float(book_brier)
        },
        'v3': {
            'accuracy': float(v3_acc),
            'logloss': float(v3_ll),
            'brier': float(v3_brier)
        },
        'improvement': {
            'logloss': float(ll_improvement),
            'accuracy': float(v3_acc - book_acc),
            'brier': float(book_brier - v3_brier)
        },
        'bootstrap_ci': ci,
        'methodology': {
            'devig': 'Simple normalization (divide by total)',
            'logloss': 'Standard multiclass cross-entropy',
            'outcome_mapping': 'H=0, D=1, A=2'
        }
    }
    
    output_path = Path('artifacts/models/v3_full/expanded_validation.json')
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    
    print(f"\nResults saved to: {output_path}")


if __name__ == "__main__":
    main()
