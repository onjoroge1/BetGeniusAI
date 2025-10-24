"""
Extract historical features for ALL matches in historical_odds table

This processes all 10,895+ matches to provide complete feature coverage.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from jobs.compute_historical_features import HistoricalFeatureExtractor
from models.database import DatabaseManager
import pandas as pd


def extract_all_historical_features(min_date='2000-01-01'):
    """Extract features for all matches in historical_odds table"""
    print("="*70)
    print("HISTORICAL FEATURE EXTRACTION - ALL MATCHES")
    print(f"Processing historical_odds from {min_date}")
    print("="*70)
    
    db = DatabaseManager()
    extractor = HistoricalFeatureExtractor(db)
    
    # Load historical data (this loads the full history for lookback)
    print("\nLoading historical match data for feature extraction...")
    extractor.load_historical_data()
    
    # Get ALL matches from historical_odds
    print(f"\nFetching all matches from historical_odds (from {min_date})...")
    query = f"""
        SELECT 
            id as match_id,
            match_date,
            home_team,
            away_team,
            league_name as league
        FROM historical_odds
        WHERE match_date >= '{min_date}'
          AND result IS NOT NULL
          AND result IN ('H', 'D', 'A')
        ORDER BY match_date
    """
    
    matches = pd.read_sql(query, db.engine)
    matches['match_date'] = pd.to_datetime(matches['match_date'])
    
    print(f"✅ Found {len(matches)} matches to process")
    print(f"   Date range: {matches['match_date'].min()} → {matches['match_date'].max()}")
    print(f"   Leagues: {matches['league'].nunique()}")
    
    all_features = []
    
    print("\n🔄 Extracting historical features...")
    for idx, row in matches.iterrows():
        if idx % 500 == 0:
            print(f"   Progress: {idx}/{len(matches)} ({idx/len(matches)*100:.1f}%)")
        
        features = extractor.extract_all_features(
            home_team=row['home_team'],
            away_team=row['away_team'],
            match_date=row['match_date'],
            league=row['league']
        )
        
        features['match_id'] = row['match_id']
        all_features.append(features)
    
    features_df = pd.DataFrame(all_features)
    
    print(f"\n{'='*70}")
    print(f"FEATURE EXTRACTION COMPLETE")
    print(f"{'='*70}")
    print(f"✅ Total matches enriched: {len(features_df):,}")
    print(f"📊 Total features extracted: {len(features_df.columns) - 1}")
    
    # Feature breakdown
    form_cols = [c for c in features_df.columns if 'form' in c]
    venue_cols = [c for c in features_df.columns if 'home_last' in c or 'away_last' in c]
    h2h_cols = [c for c in features_df.columns if 'h2h' in c]
    temporal_cols = [c for c in features_df.columns if 'days_since' in c or 'matches_last' in c]
    adv_cols = [c for c in features_df.columns if 'adv_' in c]
    
    print(f"\n📈 Feature breakdown:")
    print(f"   Form features: {len(form_cols)}")
    print(f"   Venue features: {len(venue_cols)}")
    print(f"   H2H features: {len(h2h_cols)}")
    print(f"   Temporal features: {len(temporal_cols)}")
    print(f"   Advanced stats: {len(adv_cols)}")
    
    output_path = 'artifacts/datasets/historical_features.parquet'
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    features_df.to_parquet(output_path, index=False)
    print(f"\n💾 Saved to: {output_path}")
    print(f"   File size: {os.path.getsize(output_path) / 1024 / 1024:.2f} MB")
    
    return features_df


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Extract historical features for all matches')
    parser.add_argument('--min-date', type=str, default='2000-01-01',
                       help='Minimum match date to process (YYYY-MM-DD)')
    
    args = parser.parse_args()
    
    extract_all_historical_features(min_date=args.min_date)
