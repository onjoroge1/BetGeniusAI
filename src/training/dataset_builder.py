"""
Enhanced Dataset Builder - Combines all feature types for comprehensive model training
Implements the full feature engineering pipeline from the ML build specification
"""

import os
import sys
import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

# Add src to path for imports
sys.path.append('/home/runner/workspace/src')
from features.form_features import TeamFormFeatures
from features.elo import EloRatingSystem
from features.h2h_features import HeadToHeadFeatures

class EnhancedDatasetBuilder:
    def __init__(self):
        self.database_url = os.environ.get('DATABASE_URL')
        self.engine = create_engine(self.database_url)
        
        # Initialize feature extractors
        self.form_extractor = TeamFormFeatures()
        self.elo_system = EloRatingSystem()
        self.h2h_extractor = HeadToHeadFeatures()
        
    def build_complete_dataset(self, limit_matches: int = None) -> pd.DataFrame:
        """
        Build comprehensive dataset with all feature types
        
        Args:
            limit_matches: Limit number of matches for testing (None for all)
            
        Returns:
            DataFrame with complete feature set
        """
        print("🏗️ Building Enhanced Dataset with Complete Features")
        print("=" * 55)
        
        # Get base matches data
        matches_df = self._get_base_matches(limit_matches)
        print(f"📊 Processing {len(matches_df)} matches...")
        
        feature_rows = []
        processed = 0
        skipped = 0
        
        for _, match in matches_df.iterrows():
            try:
                # Extract all feature types
                features = self._extract_complete_features(match)
                
                if features:
                    features['match_id'] = match['match_id']
                    features['outcome'] = match['outcome']
                    feature_rows.append(features)
                    processed += 1
                else:
                    skipped += 1
                
                if processed % 50 == 0:
                    print(f"  ✅ Processed: {processed}, ⚠️ Skipped: {skipped}")
                    
            except Exception as e:
                print(f"  ❌ Error processing match {match['match_id']}: {e}")
                skipped += 1
                continue
        
        if not feature_rows:
            print("❌ No valid features extracted")
            return pd.DataFrame()
        
        dataset_df = pd.DataFrame(feature_rows)
        
        print(f"\n🎯 Dataset Building Complete:")
        print(f"  ✅ Successfully processed: {processed} matches")
        print(f"  ⚠️ Skipped: {skipped} matches")
        print(f"  📊 Features per match: {len(dataset_df.columns)-2}")
        print(f"  🎯 Feature categories: Original (8) + Form (15) + Elo (11) + H2H (20) = 54 total")
        
        return dataset_df
    
    def _get_base_matches(self, limit_matches: int = None) -> pd.DataFrame:
        """Get base match data with team IDs"""
        
        with self.engine.connect() as conn:
            limit_clause = f"LIMIT {limit_matches}" if limit_matches else ""
            
            query = text(f"""
                SELECT 
                    match_id,
                    home_team_id,
                    away_team_id,
                    home_team,
                    away_team,
                    league_id,
                    region,
                    match_date,
                    outcome
                FROM training_matches
                WHERE outcome IN ('Home', 'Draw', 'Away')
                AND home_team_id IS NOT NULL
                AND away_team_id IS NOT NULL
                AND home_team != away_team
                AND league_id IS NOT NULL
                ORDER BY match_date ASC
                {limit_clause}
            """)
            
            matches_df = pd.read_sql(query, conn)
        
        return matches_df
    
    def _extract_complete_features(self, match) -> dict:
        """Extract all feature types for a single match"""
        
        # Original clean features
        original_features = self._extract_original_features(match['league_id'], match['region'])
        
        # Team form features (last 5 matches)
        form_features = self.form_extractor.extract_team_form_features(
            match_id=match['match_id'],
            home_team_id=match['home_team_id'],
            away_team_id=match['away_team_id'],
            match_date=match['match_date']
        )
        
        # Elo rating features
        elo_features = self.elo_system.extract_elo_features(
            match_id=match['match_id'],
            home_team_id=match['home_team_id'],
            away_team_id=match['away_team_id'],
            match_date=match['match_date']
        )
        
        # Head-to-head features
        h2h_features = self.h2h_extractor.extract_h2h_features(
            home_team_id=match['home_team_id'],
            away_team_id=match['away_team_id'],
            match_date=match['match_date']
        )
        
        # Simple team strength (for compatibility)
        team_strength_features = self._extract_team_strength_features(
            match['home_team'], match['away_team']
        )
        
        # Combine all features
        complete_features = {
            **original_features,
            **form_features,
            **elo_features,
            **h2h_features,
            **team_strength_features
        }
        
        return complete_features
    
    def _extract_original_features(self, league_id: int, region: str) -> dict:
        """Extract original clean features for consistency"""
        tier1_leagues = [39, 140, 135, 78, 61]
        tier2_leagues = [88, 203, 179]
        
        if league_id in tier1_leagues:
            league_tier = 1.0
            league_competitiveness = 0.85
            expected_goals = 2.7
        elif league_id in tier2_leagues:
            league_tier = 0.7
            league_competitiveness = 0.75
            expected_goals = 2.4
        else:
            league_tier = 0.5
            league_competitiveness = 0.65
            expected_goals = 2.2
        
        if region == 'Europe':
            regional_strength = 1.0
        elif region == 'South America':
            regional_strength = 0.9
        elif region == 'Africa':
            regional_strength = 0.7
        else:
            regional_strength = 0.6
        
        home_advantage_factor = 0.55
        
        if league_id == 39:
            match_importance = 0.9
        elif league_id in tier1_leagues:
            match_importance = 0.8
        else:
            match_importance = 0.7
        
        premier_league_indicator = 1.0 if league_id == 39 else 0.0
        top5_league_indicator = 1.0 if league_id in tier1_leagues else 0.0
        
        return {
            'league_tier': league_tier,
            'league_competitiveness': league_competitiveness,
            'regional_strength': regional_strength,
            'home_advantage_factor': home_advantage_factor,
            'expected_goals_avg': expected_goals,
            'match_importance': match_importance,
            'premier_league_indicator': premier_league_indicator,
            'top5_league_indicator': top5_league_indicator
        }
    
    def _extract_team_strength_features(self, home_team: str, away_team: str) -> dict:
        """Extract simple team strength features for compatibility"""
        
        # Get team strengths from database
        team_strength = self._get_cached_team_strengths()
        
        home_strength = team_strength.get(home_team, 0.5)
        away_strength = team_strength.get(away_team, 0.5)
        
        return {
            'home_team_strength': home_strength,
            'away_team_strength': away_strength,
            'strength_diff': home_strength - away_strength,
            'strength_sum': home_strength + away_strength,
            'match_competitiveness': abs(home_strength - away_strength),
            'total_quality': (home_strength + away_strength) / 2,
            'home_favored': int(home_strength > away_strength + 0.1),
            'away_favored': int(away_strength > home_strength + 0.1),
            'even_match': int(abs(home_strength - away_strength) < 0.1)
        }
    
    def _get_cached_team_strengths(self) -> dict:
        """Get cached team strengths (simple win rate based)"""
        if hasattr(self, '_team_strength_cache'):
            return self._team_strength_cache
        
        team_strength = {}
        
        with self.engine.connect() as conn:
            # Combined home and away performance
            query = text("""
                WITH team_stats AS (
                    SELECT 
                        home_team as team,
                        COUNT(*) as matches,
                        SUM(CASE WHEN outcome = 'Home' THEN 3 
                                 WHEN outcome = 'Draw' THEN 1 
                                 ELSE 0 END) as points
                    FROM training_matches
                    WHERE outcome IN ('Home', 'Draw', 'Away')
                    GROUP BY home_team
                    
                    UNION ALL
                    
                    SELECT 
                        away_team as team,
                        COUNT(*) as matches,
                        SUM(CASE WHEN outcome = 'Away' THEN 3 
                                 WHEN outcome = 'Draw' THEN 1 
                                 ELSE 0 END) as points
                    FROM training_matches
                    WHERE outcome IN ('Home', 'Draw', 'Away')
                    GROUP BY away_team
                )
                SELECT 
                    team,
                    SUM(matches) as total_matches,
                    SUM(points) as total_points
                FROM team_stats
                GROUP BY team
                HAVING SUM(matches) >= 5
            """)
            
            results = conn.execute(query).fetchall()
            
            for team, matches, points in results:
                max_points = matches * 3
                strength = points / max_points if max_points > 0 else 0.5
                team_strength[team] = strength
        
        self._team_strength_cache = team_strength
        return team_strength
    
    def get_feature_importance_analysis(self, dataset_df: pd.DataFrame) -> pd.DataFrame:
        """Analyze feature importance categories"""
        
        feature_cols = [col for col in dataset_df.columns if col not in ['match_id', 'outcome']]
        
        categories = {
            'Original': [col for col in feature_cols if col in [
                'league_tier', 'league_competitiveness', 'regional_strength',
                'home_advantage_factor', 'expected_goals_avg', 'match_importance',
                'premier_league_indicator', 'top5_league_indicator'
            ]],
            'Form': [col for col in feature_cols if 'form' in col or 'win_rate' in col or 'streak' in col],
            'Elo': [col for col in feature_cols if 'elo' in col],
            'H2H': [col for col in feature_cols if 'h2h' in col],
            'Team_Strength': [col for col in feature_cols if 'strength' in col or 'favored' in col]
        }
        
        analysis = []
        for category, features in categories.items():
            analysis.append({
                'Category': category,
                'Feature_Count': len(features),
                'Features': ', '.join(features[:3]) + '...' if len(features) > 3 else ', '.join(features)
            })
        
        return pd.DataFrame(analysis)

def main():
    """Build and test the enhanced dataset"""
    print("🚀 Enhanced Dataset Builder - Complete Feature Pipeline")
    print("=" * 60)
    
    builder = EnhancedDatasetBuilder()
    
    try:
        # Build dataset with first 500 matches for testing
        dataset = builder.build_complete_dataset(limit_matches=500)
        
        if len(dataset) == 0:
            print("❌ No dataset built")
            return
        
        # Feature analysis
        feature_analysis = builder.get_feature_importance_analysis(dataset)
        print(f"\n📊 Feature Category Analysis:")
        print(feature_analysis.to_string(index=False))
        
        # Basic statistics
        print(f"\n🎯 Dataset Statistics:")
        print(f"  Total matches: {len(dataset)}")
        print(f"  Total features: {len(dataset.columns)-2}")
        print(f"  Outcome distribution:")
        
        outcome_dist = dataset['outcome'].value_counts()
        for outcome, count in outcome_dist.items():
            print(f"    {outcome}: {count} ({count/len(dataset)*100:.1f}%)")
        
        # Save sample for inspection
        dataset.to_csv('enhanced_dataset_sample.csv', index=False)
        print(f"\n💾 Sample dataset saved: enhanced_dataset_sample.csv")
        
        print(f"\n✅ Enhanced dataset ready for training!")
        print(f"🎯 Next step: Train two-stage model with complete features")
        
    except Exception as e:
        print(f"❌ Error building enhanced dataset: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()