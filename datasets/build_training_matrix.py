"""
Training Matrix Builder for V2 LightGBM Model

Combines all pre-kick features into a single training dataset:
- Market features (drift, dispersion, volatility)
- ELO ratings (home/away team strength)
- Team form (from training_matches features JSONB)
- Match outcomes (labels)

All features guaranteed < kickoff_at (no data leakage).

Output: artifacts/datasets/v2_tabular.parquet

Author: BetGenius AI Team
Date: Oct 2025
"""

import os
import sys
import psycopg2
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from models.database import DatabaseManager


def build_training_matrix(output_path: str = 'artifacts/datasets/v2_tabular.parquet'):
    """
    Build complete training matrix with all features and labels.
    
    Returns:
        pd.DataFrame with columns:
        - match_id, league, kickoff_date
        - Market features: p_open_*, p_last_*, drift_*, dispersion_*, volatility_*
        - ELO features: home_elo, away_elo, elo_diff
        - Outcome: y (H/D/A)
    """
    print("=" * 70)
    print("TRAINING MATRIX BUILDER - V2 LIGHTGBM")
    print("=" * 70)
    
    db_manager = DatabaseManager()
    conn = psycopg2.connect(db_manager.database_url)
    
    # Build unified query joining all feature sources
    sql = """
        SELECT 
            f.match_id,
            COALESCE(f.league_name, 'Unknown') as league,
            f.kickoff_at::date as kickoff_date,
            
            -- Market features (opening)
            mf.p_open_home,
            mf.p_open_draw,
            mf.p_open_away,
            
            -- Market features (last/closing)
            mf.p_last_home,
            mf.p_last_draw,
            mf.p_last_away,
            
            -- Market drift
            mf.prob_drift_home,
            mf.prob_drift_draw,
            mf.prob_drift_away,
            mf.drift_magnitude,
            
            -- Cross-book dispersion
            mf.book_dispersion,
            mf.dispersion_home,
            mf.dispersion_draw,
            mf.dispersion_away,
            
            -- Temporal volatility
            mf.volatility_home,
            mf.volatility_draw,
            mf.volatility_away,
            
            -- Coverage metrics
            mf.num_books_last,
            mf.num_snapshots,
            mf.coverage_hours,
            
            -- ELO ratings (lookup nearest past snapshot)
            elo_h.elo_neutral as home_elo,
            elo_a.elo_neutral as away_elo,
            (elo_h.elo_neutral - elo_a.elo_neutral) as elo_diff,
            
            -- Outcome (label)
            mr.outcome as y
            
        FROM fixtures f
        INNER JOIN match_results mr ON f.match_id = mr.match_id
        INNER JOIN market_features mf ON f.match_id = mf.match_id
        INNER JOIN training_matches tm ON f.match_id = tm.match_id
        LEFT JOIN LATERAL (
            SELECT elo_neutral 
            FROM elo_ratings 
            WHERE team_id = tm.home_team_id 
              AND as_of_date <= f.kickoff_at::date
            ORDER BY as_of_date DESC 
            LIMIT 1
        ) elo_h ON true
        LEFT JOIN LATERAL (
            SELECT elo_neutral 
            FROM elo_ratings 
            WHERE team_id = tm.away_team_id 
              AND as_of_date <= f.kickoff_at::date
            ORDER BY as_of_date DESC 
            LIMIT 1
        ) elo_a ON true
        
        WHERE f.kickoff_at IS NOT NULL
          AND mr.outcome IS NOT NULL
          AND mf.p_last_home IS NOT NULL
          AND tm.home_team_id IS NOT NULL
          AND tm.away_team_id IS NOT NULL
        
        ORDER BY f.kickoff_at, f.match_id
    """
    
    print("📊 Querying database for training data...")
    df = pd.read_sql(sql, conn)
    conn.close()
    
    print(f"   Loaded {len(df)} matches with market/ELO features")
    
    # Load historical features if available
    hist_features_path = 'artifacts/datasets/historical_features.parquet'
    if os.path.exists(hist_features_path):
        print(f"📚 Loading historical features from {hist_features_path}...")
        hist_df = pd.read_parquet(hist_features_path)
        print(f"   Loaded {len(hist_df)} matches with {len(hist_df.columns)-1} historical features")
        
        # Merge on match_id
        df_before = len(df)
        df = df.merge(hist_df, on='match_id', how='left')
        print(f"   Merged: {df_before} → {len(df)} matches ({len(df.columns)-4} total features)")
        
        # Fill any missing historical features with defaults
        hist_cols = [c for c in hist_df.columns if c != 'match_id']
        missing_hist = df[hist_cols].isna().sum().sum()
        if missing_hist > 0:
            print(f"   ⚠️  Filling {missing_hist} missing historical feature values with defaults")
            for col in hist_cols:
                if df[col].isna().any():
                    if 'win_rate' in col or 'ppg' in col or 'accuracy' in col or 'conversion' in col:
                        df[col].fillna(0.33 if 'home' in col else 0.25, inplace=True)
                    elif 'matches' in col or 'wins' in col or 'draws' in col or 'losses' in col:
                        df[col].fillna(0, inplace=True)
                    else:
                        df[col].fillna(df[col].median(), inplace=True)
    else:
        print(f"   ⚠️  Historical features not found at {hist_features_path}")
        print(f"   💡 Run: python jobs/compute_historical_features_fast.py")
    
    print(f"   Total features loaded: {len(df.columns) - 4}")
    
    if len(df) == 0:
        print("❌ No training data found!")
        return None
    
    # Data quality checks
    print("\n🔍 Data Quality Checks:")
    
    # Check for NaN values
    nan_counts = df.isna().sum()
    critical_features = ['p_last_home', 'p_last_draw', 'p_last_away', 'home_elo', 'away_elo', 'y']
    
    for feat in critical_features:
        if nan_counts[feat] > 0:
            print(f"   ⚠️  {feat}: {nan_counts[feat]} NaN values")
    
    # Impute missing ELO with default (1500)
    if df['home_elo'].isna().any() or df['away_elo'].isna().any():
        print(f"   📝 Imputing {df['home_elo'].isna().sum()} missing home ELO with 1500")
        print(f"   📝 Imputing {df['away_elo'].isna().sum()} missing away ELO with 1500")
        df['home_elo'].fillna(1500.0, inplace=True)
        df['away_elo'].fillna(1500.0, inplace=True)
        df['elo_diff'] = df['home_elo'] - df['away_elo']
    
    # Impute missing market features with neutral/zero values
    market_cols = [
        'p_open_home', 'p_open_draw', 'p_open_away',
        'prob_drift_home', 'prob_drift_draw', 'prob_drift_away',
        'dispersion_home', 'dispersion_draw', 'dispersion_away',
        'volatility_home', 'volatility_draw', 'volatility_away'
    ]
    
    for col in market_cols:
        if col in df.columns and df[col].isna().any():
            # Use last probs for missing open probs
            if 'open' in col:
                df[col].fillna(df[col.replace('open', 'last')], inplace=True)
            else:
                df[col].fillna(0.0, inplace=True)
    
    # Validate outcome labels
    valid_outcomes = df['y'].isin(['H', 'D', 'A'])
    if not valid_outcomes.all():
        print(f"   ⚠️  {(~valid_outcomes).sum()} invalid outcomes (not H/D/A)")
        df = df[valid_outcomes]
    
    # Feature engineering: Market entropy, favorite margin
    df['market_entropy'] = -(
        df['p_last_home'] * np.log(df['p_last_home'] + 1e-9) +
        df['p_last_draw'] * np.log(df['p_last_draw'] + 1e-9) +
        df['p_last_away'] * np.log(df['p_last_away'] + 1e-9)
    )
    
    df['favorite_margin'] = df[['p_last_home', 'p_last_draw', 'p_last_away']].max(axis=1) - \
                           df[['p_last_home', 'p_last_draw', 'p_last_away']].apply(
                               lambda row: sorted(row)[-2], axis=1
                           )
    
    # Summary statistics
    print(f"\n📊 Training Matrix Summary:")
    print(f"   Total samples: {len(df)}")
    print(f"   Date range: {df['kickoff_date'].min()} → {df['kickoff_date'].max()}")
    print(f"   Leagues: {df['league'].nunique()}")
    print(f"   Outcome distribution:")
    print(f"      Home wins: {(df['y'] == 'H').sum()} ({(df['y'] == 'H').mean()*100:.1f}%)")
    print(f"      Draws:     {(df['y'] == 'D').sum()} ({(df['y'] == 'D').mean()*100:.1f}%)")
    print(f"      Away wins: {(df['y'] == 'A').sum()} ({(df['y'] == 'A').mean()*100:.1f}%)")
    print(f"   Features: {len(df.columns) - 4} (excluding match_id, league, kickoff_date, y)")
    
    # ELO distribution
    print(f"\n   ELO Statistics:")
    print(f"      Home ELO: {df['home_elo'].mean():.1f} ± {df['home_elo'].std():.1f}")
    print(f"      Away ELO: {df['away_elo'].mean():.1f} ± {df['away_elo'].std():.1f}")
    print(f"      ELO diff: {df['elo_diff'].mean():.1f} ± {df['elo_diff'].std():.1f}")
    
    # Save to parquet
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    df.to_parquet(output_path, index=False)
    
    print(f"\n💾 Saved training matrix to: {output_path}")
    print(f"   File size: {os.path.getsize(output_path) / 1024:.1f} KB")
    print("=" * 70)
    
    return df


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Build training matrix for V2 LightGBM')
    parser.add_argument('--output', type=str, default='artifacts/datasets/v2_tabular.parquet',
                       help='Output path for parquet file')
    
    args = parser.parse_args()
    
    df = build_training_matrix(output_path=args.output)
    
    if df is not None:
        print("\n✅ Training matrix ready for LightGBM!")
        print(f"   Shape: {df.shape}")
        print(f"   Columns: {list(df.columns[:10])}...")
