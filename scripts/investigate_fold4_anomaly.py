#!/usr/bin/env python3
"""
Investigate Fold 4 Anomaly (56.8% accuracy vs 49.5% average)

This script analyzes why Fold 4 performed significantly better than other folds
to rule out data leakage or data distribution issues.

Checks:
1. League distribution per fold
2. Outcome distribution per fold
3. Bookmaker coverage (n_books) per fold
4. Opening odds availability per fold
5. Date range and temporal patterns per fold
6. Bookmaker margin distribution per fold
"""

import os
import sys
import numpy as np
import pandas as pd
from datetime import datetime
from sqlalchemy import create_engine, text
import matplotlib.pyplot as plt

sys.path.append('.')


def investigate_fold_anomaly():
    """Main investigation function"""
    
    print("="*70)
    print("  FOLD 4 ANOMALY INVESTIGATION")
    print("="*70)
    print("Current results:")
    print("  Fold 1: 46.12%")
    print("  Fold 2: 47.57%")
    print("  Fold 3: 45.63%")
    print("  Fold 4: 56.80%  ← ANOMALY (+11.3pp above average)")
    print("  Fold 5: 51.46%")
    print("  Average: 49.51%")
    print("")
    
    database_url = os.getenv('DATABASE_URL')
    engine = create_engine(database_url)
    
    # Load training matches with odds
    query = text("""
        SELECT 
            tm.match_id,
            tm.match_date,
            tm.outcome,
            tm.league_id,
            tm.home_team,
            tm.away_team,
            orc.ph_cons,
            orc.pd_cons,
            orc.pa_cons,
            orc.n_books,
            CASE 
                WHEN oro.match_id IS NOT NULL THEN 1 
                ELSE 0 
            END as has_opening
        FROM training_matches tm
        INNER JOIN match_context mc ON tm.match_id = mc.match_id
        INNER JOIN odds_real_consensus orc ON tm.match_id = orc.match_id
        LEFT JOIN odds_real_opening oro ON tm.match_id = oro.match_id
        WHERE tm.match_date >= '2025-08-18'
          AND tm.match_date < '2025-12-31'
          AND tm.match_date IS NOT NULL
          AND tm.outcome IS NOT NULL
        ORDER BY RANDOM()
    """)
    
    with engine.connect() as conn:
        df = pd.read_sql(query, conn)
    
    print(f"📊 Loaded {len(df)} matches for analysis\n")
    
    # Simulate TimeSeriesSplit folds
    df = df.sort_values('match_date').reset_index(drop=True)
    n_splits = 5
    fold_size = len(df) // (n_splits + 1)
    
    fold_assignments = []
    for i in range(len(df)):
        fold = min(i // fold_size, n_splits - 1)
        fold_assignments.append(fold)
    
    df['fold'] = fold_assignments
    
    # === ANALYSIS 1: League Distribution ===
    print("\n" + "="*70)
    print("  ANALYSIS 1: League Distribution per Fold")
    print("="*70)
    
    league_dist = df.groupby(['fold', 'league_id']).size().unstack(fill_value=0)
    league_pct = league_dist.div(league_dist.sum(axis=1), axis=0) * 100
    
    print("\nMatches per league per fold:")
    print(league_dist)
    print("\nPercentage per league per fold:")
    print(league_pct.round(1))
    
    # Highlight if Fold 4 has unusual league concentration
    fold4_leagues = league_pct.loc[4]
    avg_leagues = league_pct.drop(4).mean()
    league_diff = fold4_leagues - avg_leagues
    
    print("\n📈 Fold 4 league concentration vs average:")
    for league_id in league_diff.index:
        if abs(league_diff[league_id]) > 10:
            print(f"   League {league_id}: {league_diff[league_id]:+.1f}pp "
                  f"({'⚠️ HIGHER' if league_diff[league_id] > 0 else 'lower'})")
    
    # === ANALYSIS 2: Outcome Distribution ===
    print("\n" + "="*70)
    print("  ANALYSIS 2: Outcome Distribution per Fold")
    print("="*70)
    
    outcome_dist = df.groupby(['fold', 'outcome']).size().unstack(fill_value=0)
    outcome_pct = outcome_dist.div(outcome_dist.sum(axis=1), axis=0) * 100
    
    print("\nOutcome percentages per fold:")
    print(outcome_pct.round(1))
    
    # Check if Fold 4 has unusual outcome balance
    fold4_outcomes = outcome_pct.loc[4]
    avg_outcomes = outcome_pct.drop(4).mean()
    outcome_diff = fold4_outcomes - avg_outcomes
    
    print("\n📈 Fold 4 outcome distribution vs average:")
    for outcome in outcome_diff.index:
        if abs(outcome_diff[outcome]) > 5:
            print(f"   {outcome}: {outcome_diff[outcome]:+.1f}pp "
                  f"({'⚠️ HIGHER' if outcome_diff[outcome] > 0 else 'lower'})")
    
    # === ANALYSIS 3: Bookmaker Coverage ===
    print("\n" + "="*70)
    print("  ANALYSIS 3: Bookmaker Coverage per Fold")
    print("="*70)
    
    n_books_stats = df.groupby('fold')['n_books'].describe()
    print("\nBookmaker count statistics per fold:")
    print(n_books_stats)
    
    fold4_avg_books = df[df['fold'] == 4]['n_books'].mean()
    other_avg_books = df[df['fold'] != 4]['n_books'].mean()
    
    print(f"\n📈 Fold 4 avg books: {fold4_avg_books:.1f}")
    print(f"   Other folds avg books: {other_avg_books:.1f}")
    print(f"   Difference: {fold4_avg_books - other_avg_books:+.1f} "
          f"({'⚠️ HIGHER' if fold4_avg_books > other_avg_books else 'lower'})")
    
    # === ANALYSIS 4: Opening Odds Availability ===
    print("\n" + "="*70)
    print("  ANALYSIS 4: Opening Odds Availability per Fold")
    print("="*70)
    
    opening_avail = df.groupby('fold')['has_opening'].mean() * 100
    print("\nPercentage with opening odds per fold:")
    for fold, pct in opening_avail.items():
        marker = " ⚠️ " if fold == 4 and abs(pct - opening_avail.drop(4).mean()) > 10 else ""
        print(f"   Fold {fold}: {pct:.1f}%{marker}")
    
    # === ANALYSIS 5: Date Range Analysis ===
    print("\n" + "="*70)
    print("  ANALYSIS 5: Date Range per Fold")
    print("="*70)
    
    date_ranges = df.groupby('fold')['match_date'].agg(['min', 'max', 'count'])
    date_ranges['days'] = (pd.to_datetime(date_ranges['max']) - 
                           pd.to_datetime(date_ranges['min'])).dt.days
    
    print("\nDate ranges per fold:")
    print(date_ranges)
    
    # === ANALYSIS 6: Bookmaker Margin ===
    print("\n" + "="*70)
    print("  ANALYSIS 6: Bookmaker Margin per Fold")
    print("="*70)
    
    df['margin'] = df['ph_cons'] + df['pd_cons'] + df['pa_cons'] - 1.0
    margin_stats = df.groupby('fold')['margin'].describe()
    
    print("\nBookmaker margin statistics per fold:")
    print(margin_stats)
    
    fold4_avg_margin = df[df['fold'] == 4]['margin'].mean()
    other_avg_margin = df[df['fold'] != 4]['margin'].mean()
    
    print(f"\n📈 Fold 4 avg margin: {fold4_avg_margin:.4f}")
    print(f"   Other folds avg margin: {other_avg_margin:.4f}")
    print(f"   Difference: {fold4_avg_margin - other_avg_margin:+.4f}")
    
    # === ANALYSIS 7: Market Predictability ===
    print("\n" + "="*70)
    print("  ANALYSIS 7: Market Predictability (Favorite Strength)")
    print("="*70)
    
    df['max_prob'] = df[['ph_cons', 'pd_cons', 'pa_cons']].max(axis=1)
    df['favorite_strength'] = df['max_prob'] - (1.0 / 3.0)  # Distance from uniform
    
    fav_strength_stats = df.groupby('fold')['favorite_strength'].describe()
    print("\nFavorite strength statistics per fold:")
    print(fav_strength_stats)
    
    fold4_fav_strength = df[df['fold'] == 4]['favorite_strength'].mean()
    other_fav_strength = df[df['fold'] != 4]['favorite_strength'].mean()
    
    print(f"\n📈 Fold 4 avg favorite strength: {fold4_fav_strength:.4f}")
    print(f"   Other folds avg: {other_fav_strength:.4f}")
    print(f"   Difference: {fold4_fav_strength - other_fav_strength:+.4f} "
          f"({'⚠️ MORE PREDICTABLE' if fold4_fav_strength > other_fav_strength else 'less predictable'})")
    
    # === SUMMARY ===
    print("\n" + "="*70)
    print("  SUMMARY & DIAGNOSIS")
    print("="*70)
    
    print("\n🔍 Key Findings:")
    
    # Check for anomalies
    anomalies = []
    
    if abs(fold4_avg_books - other_avg_books) > 5:
        anomalies.append(f"Bookmaker coverage differs by {fold4_avg_books - other_avg_books:+.1f} books")
    
    if abs(fold4_avg_margin - other_avg_margin) > 0.01:
        anomalies.append(f"Bookmaker margin differs by {(fold4_avg_margin - other_avg_margin)*100:+.2f}%")
    
    if abs(fold4_fav_strength - other_fav_strength) > 0.02:
        anomalies.append(f"Favorite strength differs by {fold4_fav_strength - other_fav_strength:+.3f}")
    
    opening_diff = opening_avail[4] - opening_avail.drop(4).mean()
    if abs(opening_diff) > 10:
        anomalies.append(f"Opening odds availability differs by {opening_diff:+.1f}pp")
    
    if len(anomalies) > 0:
        print("\n⚠️  Potential explanations for Fold 4 anomaly:")
        for i, anomaly in enumerate(anomalies, 1):
            print(f"   {i}. {anomaly}")
    else:
        print("\n✅ No obvious data distribution issues found")
        print("   Fold 4 performance may be:")
        print("   - Random variance (small sample size)")
        print("   - Temporal patterns (specific leagues/teams in that period)")
        print("   - Need to investigate feature leakage")
    
    print("\n💡 Recommendations:")
    print("   1. Run sanity checks on Fold 4 data specifically")
    print("   2. Check if any features have unusually high importance on Fold 4")
    print("   3. Validate that no future information leaked into Fold 4 features")
    print("   4. Consider stratified sampling by league to balance folds")
    print("   5. Increase dataset size to reduce fold variance")


if __name__ == '__main__':
    investigate_fold_anomaly()
