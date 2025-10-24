"""
Training Matrix Builder for Historical Data

Extracts training data from historical_odds table using bookmaker odds
as market features, enabling training on 10,000+ historical matches.

Market Consensus Strategy:
- Uses Pinnacle (PS) as primary (sharp bookmaker)
- Falls back to Bet365 (B365) if Pinnacle unavailable
- Falls back to market average if both unavailable

Output: artifacts/datasets/v2_tabular_historical.parquet

Author: BetGenius AI Team
Date: Oct 2025
"""

import os
import sys
import psycopg2
import pandas as pd
import numpy as np
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from models.database import DatabaseManager


def odds_to_prob(home_odds, draw_odds, away_odds):
    """Convert decimal odds to normalized probabilities"""
    if pd.isna(home_odds) or pd.isna(draw_odds) or pd.isna(away_odds):
        return None, None, None
    
    # Implied probabilities (with bookmaker margin)
    p_h = 1.0 / home_odds
    p_d = 1.0 / draw_odds
    p_a = 1.0 / away_odds
    
    # Normalize to remove margin
    total = p_h + p_d + p_a
    if total == 0:
        return None, None, None
    
    return p_h / total, p_d / total, p_a / total


def build_historical_training_matrix(output_path: str = 'artifacts/datasets/v2_tabular_historical.parquet',
                                     min_date: str = '2000-01-01'):
    """
    Build training matrix from historical_odds table.
    
    Args:
        output_path: Where to save parquet file
        min_date: Minimum date to include (filter out very old matches)
    
    Returns:
        pd.DataFrame with training samples
    """
    print("=" * 70)
    print("HISTORICAL TRAINING MATRIX BUILDER")
    print("=" * 70)
    
    db_manager = DatabaseManager()
    conn = psycopg2.connect(db_manager.database_url)
    
    # Query historical odds with bookmaker consensus
    sql = f"""
        SELECT 
            id as match_id,
            league_name as league,
            match_date as kickoff_date,
            home_team,
            away_team,
            
            -- Pinnacle odds (preferred - sharpest bookmaker)
            ps_h, ps_d, ps_a,
            
            -- Bet365 odds (fallback)
            b365_h, b365_d, b365_a,
            
            -- Market average (second fallback)
            avg_h, avg_d, avg_a,
            
            -- Market maximum (for dispersion calculation)
            max_h, max_d, max_a,
            
            -- Outcome label
            result as y
            
        FROM historical_odds
        WHERE match_date >= '{min_date}'
          AND result IS NOT NULL
          AND result IN ('H', 'D', 'A')
          AND home_goals IS NOT NULL
          AND away_goals IS NOT NULL
          AND (
              (ps_h IS NOT NULL AND ps_d IS NOT NULL AND ps_a IS NOT NULL) OR
              (b365_h IS NOT NULL AND b365_d IS NOT NULL AND b365_a IS NOT NULL) OR
              (avg_h IS NOT NULL AND avg_d IS NOT NULL AND avg_a IS NOT NULL)
          )
        ORDER BY match_date, id
    """
    
    print(f"📊 Loading historical matches (from {min_date})...")
    df = pd.read_sql(sql, conn)
    conn.close()
    
    print(f"   Loaded {len(df)} historical matches")
    
    if len(df) == 0:
        print("❌ No historical data found!")
        return None
    
    # Extract market features from odds
    print("🔢 Converting bookmaker odds to market probabilities...")
    
    market_probs = []
    for idx, row in df.iterrows():
        # Try Pinnacle first (sharpest)
        p_h, p_d, p_a = odds_to_prob(row['ps_h'], row['ps_d'], row['ps_a'])
        
        # Fallback to Bet365
        if p_h is None:
            p_h, p_d, p_a = odds_to_prob(row['b365_h'], row['b365_d'], row['b365_a'])
        
        # Fallback to market average
        if p_h is None:
            p_h, p_d, p_a = odds_to_prob(row['avg_h'], row['avg_d'], row['avg_a'])
        
        market_probs.append({
            'p_last_home': p_h,
            'p_last_draw': p_d,
            'p_last_away': p_a
        })
    
    # Add market probabilities to dataframe
    market_df = pd.DataFrame(market_probs)
    df = pd.concat([df, market_df], axis=1)
    
    # Remove rows where we couldn't extract probabilities
    valid_market = df['p_last_home'].notna()
    df = df[valid_market].copy()
    print(f"   Extracted market probabilities for {len(df)} matches")
    
    # Calculate market-derived features
    df['p_open_home'] = df['p_last_home']  # No drift data, assume stable
    df['p_open_draw'] = df['p_last_draw']
    df['p_open_away'] = df['p_last_away']
    
    df['prob_drift_home'] = 0.0  # No historical drift data
    df['prob_drift_draw'] = 0.0
    df['prob_drift_away'] = 0.0
    df['drift_magnitude'] = 0.0
    
    # Calculate dispersion from max vs consensus
    for outcome, odds_col_max in [('home', 'max_h'), ('draw', 'max_d'), ('away', 'max_a')]:
        max_odds = df[odds_col_max]
        consensus_prob = df[f'p_last_{outcome}']
        
        # Dispersion = difference between max implied prob and consensus
        max_implied = 1.0 / max_odds.where(max_odds.notna() & (max_odds > 0), np.nan)
        df[f'dispersion_{outcome}'] = (max_implied - consensus_prob).fillna(0.0).abs()
    
    df['book_dispersion'] = df[['dispersion_home', 'dispersion_draw', 'dispersion_away']].mean(axis=1)
    
    # No volatility data for historical
    df['volatility_home'] = 0.0
    df['volatility_draw'] = 0.0
    df['volatility_away'] = 0.0
    
    # Coverage metrics (historical = 1 snapshot, varies by bookmaker)
    df['num_books_last'] = (~df[['ps_h', 'b365_h', 'avg_h']].isna()).sum(axis=1)
    df['num_snapshots'] = 1
    df['coverage_hours'] = 0.0
    
    # ELO features (default to 1500 - no historical ELO data)
    df['home_elo'] = 1500.0
    df['away_elo'] = 1500.0
    df['elo_diff'] = 0.0
    
    # Market entropy and favorite margin
    df['market_entropy'] = -(
        df['p_last_home'] * np.log(df['p_last_home'] + 1e-9) +
        df['p_last_draw'] * np.log(df['p_last_draw'] + 1e-9) +
        df['p_last_away'] * np.log(df['p_last_away'] + 1e-9)
    )
    
    df['favorite_margin'] = df[['p_last_home', 'p_last_draw', 'p_last_away']].max(axis=1) - \
                           df[['p_last_home', 'p_last_draw', 'p_last_away']].apply(
                               lambda row: sorted(row)[-2], axis=1
                           )
    
    # Load and merge historical features if available
    hist_features_path = 'artifacts/datasets/historical_features.parquet'
    if os.path.exists(hist_features_path):
        print(f"📚 Loading historical features from {hist_features_path}...")
        hist_df = pd.read_parquet(hist_features_path)
        print(f"   Loaded {len(hist_df)} matches with {len(hist_df.columns)-1} historical features")
        
        # Merge on match_id
        df_before = len(df)
        df = df.merge(hist_df, on='match_id', how='left')
        print(f"   Merged: {df_before} → {len(df)} matches")
        
        # Fill missing historical features with defaults
        hist_cols = [c for c in hist_df.columns if c != 'match_id']
        for col in hist_cols:
            if col in df.columns and df[col].isna().any():
                if 'win_rate' in col or 'ppg' in col or 'accuracy' in col or 'conversion' in col:
                    df[col].fillna(0.33 if 'home' in col else 0.25, inplace=True)
                elif 'matches' in col or 'wins' in col or 'draws' in col or 'losses' in col:
                    df[col].fillna(0, inplace=True)
                else:
                    median_val = df[col].median()
                    df[col].fillna(median_val if pd.notna(median_val) else 0.0, inplace=True)
        
        print(f"   Total features: {len(df.columns) - 4}")
    else:
        print(f"   ℹ️  Historical features not found (will use market features only)")
    
    # Drop intermediate columns
    drop_cols = ['ps_h', 'ps_d', 'ps_a', 'b365_h', 'b365_d', 'b365_a',
                 'avg_h', 'avg_d', 'avg_a', 'max_h', 'max_d', 'max_a',
                 'home_team', 'away_team']
    df = df.drop(columns=[c for c in drop_cols if c in df.columns])
    
    # Summary statistics
    print(f"\n📊 Training Matrix Summary:")
    print(f"   Total samples: {len(df)}")
    print(f"   Date range: {df['kickoff_date'].min()} → {df['kickoff_date'].max()}")
    print(f"   Leagues: {df['league'].nunique()}")
    
    outcome_dist = df['y'].value_counts()
    print(f"   Outcome distribution:")
    print(f"      Home wins: {outcome_dist.get('H', 0)} ({outcome_dist.get('H', 0)/len(df)*100:.1f}%)")
    print(f"      Draws:     {outcome_dist.get('D', 0)} ({outcome_dist.get('D', 0)/len(df)*100:.1f}%)")
    print(f"      Away wins: {outcome_dist.get('A', 0)} ({outcome_dist.get('A', 0)/len(df)*100:.1f}%)")
    
    print(f"   Features: {len(df.columns) - 4} (excluding match_id, league, kickoff_date, y)")
    
    # Market statistics
    print(f"\n   Market Statistics:")
    print(f"      Avg home prob: {df['p_last_home'].mean():.3f} ± {df['p_last_home'].std():.3f}")
    print(f"      Avg draw prob: {df['p_last_draw'].mean():.3f} ± {df['p_last_draw'].std():.3f}")
    print(f"      Avg away prob: {df['p_last_away'].mean():.3f} ± {df['p_last_away'].std():.3f}")
    print(f"      Avg entropy: {df['market_entropy'].mean():.3f}")
    
    # Save to parquet
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    df.to_parquet(output_path, index=False)
    
    print(f"\n💾 Saved training matrix to: {output_path}")
    print(f"   File size: {os.path.getsize(output_path) / 1024:.1f} KB")
    print("=" * 70)
    
    return df


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Build historical training matrix')
    parser.add_argument('--output', type=str, default='artifacts/datasets/v2_tabular_historical.parquet',
                       help='Output path for parquet file')
    parser.add_argument('--min-date', type=str, default='2000-01-01',
                       help='Minimum match date to include (YYYY-MM-DD)')
    
    args = parser.parse_args()
    
    df = build_historical_training_matrix(output_path=args.output, min_date=args.min_date)
    
    if df is not None:
        print("\n✅ Historical training matrix ready for LightGBM!")
        print(f"   Shape: {df.shape}")
        print(f"   Sample size suitable for training: {len(df) >= 1000}")
