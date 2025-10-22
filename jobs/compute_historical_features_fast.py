"""
Fast Historical Feature Extraction - Only for matches with market features

This processes only the ~462 matches that already have market features,
making it much faster than processing all 10,599 training_matches.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from compute_historical_features import HistoricalFeatureExtractor
from models.database import DatabaseManager
import pandas as pd


def enrich_market_feature_matches():
    """Enrich only matches that have market features (for immediate training)"""
    print("="*70)
    print("FAST HISTORICAL FEATURE ENRICHMENT")
    print("Processing only matches with market features")
    print("="*70)
    
    db = DatabaseManager()
    extractor = HistoricalFeatureExtractor(db)
    
    # Load historical data
    extractor.load_historical_data()
    
    # Get matches that have market features
    print("\nFetching matches with market features...")
    query = """
        SELECT DISTINCT
            tm.match_id,
            tm.match_date,
            tm.home_team,
            tm.away_team
        FROM training_matches tm
        INNER JOIN market_features mf ON tm.match_id = mf.match_id
        ORDER BY tm.match_date
    """
    
    training_matches = pd.read_sql(query, db.engine)
    training_matches['match_date'] = pd.to_datetime(training_matches['match_date'])
    
    print(f"Found {len(training_matches)} matches with market features to enrich")
    
    all_features = []
    
    for idx, row in training_matches.iterrows():
        if idx % 50 == 0:
            print(f"Processing {idx}/{len(training_matches)}...")
        
        features = extractor.extract_all_features(
            home_team=row['home_team'],
            away_team=row['away_team'],
            match_date=row['match_date'],
            league=None
        )
        
        features['match_id'] = row['match_id']
        all_features.append(features)
    
    features_df = pd.DataFrame(all_features)
    
    print(f"\n{'='*70}")
    print(f"FEATURE EXTRACTION COMPLETE")
    print(f"{'='*70}")
    print(f"Total matches enriched: {len(features_df)}")
    print(f"Total features extracted: {len(features_df.columns) - 1}")
    
    output_path = 'artifacts/datasets/historical_features.parquet'
    features_df.to_parquet(output_path, index=False)
    print(f"\nSaved to: {output_path}")
    
    # Show sample
    print(f"\nFeature summary (first match):")
    sample = features_df.iloc[0]
    print(f"  Match ID: {sample['match_id']}")
    print(f"  Form features: {len([c for c in features_df.columns if 'form' in c])}")
    print(f"  Venue features: {len([c for c in features_df.columns if 'home_last' in c or 'away_last' in c])}")
    print(f"  H2H features: {len([c for c in features_df.columns if 'h2h' in c])}")
    print(f"  Temporal features: {len([c for c in features_df.columns if 'days_since' in c or 'matches_last' in c])}")
    print(f"  Advanced features: {len([c for c in features_df.columns if 'adv_' in c])}")
    
    # db.close() is not needed for DatabaseManager
    
    return features_df


if __name__ == "__main__":
    enrich_market_feature_matches()
