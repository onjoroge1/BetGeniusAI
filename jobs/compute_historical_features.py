"""
Historical Feature Extraction Pipeline

Extracts team form, head-to-head, venue, and temporal features from historical_odds table
to enrich training data for ML models.

Features extracted:
- Team Form: Last 5/10 matches (W/D/L, goals, points, streaks)
- Head-to-Head: Historical matchup statistics
- Venue: Home/away performance metrics
- Temporal: Days since last match, fixture congestion
- Advanced: Shooting efficiency, defensive pressure (when available)

Designed to be reusable across all leagues.
"""

import psycopg2
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import os
import sys
from typing import Dict, List, Tuple, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from models.database import DatabaseManager


class HistoricalFeatureExtractor:
    """Extract features from historical match data"""
    
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager
        self.historical_cache = None
        
    def load_historical_data(self, as_of_date: Optional[str] = None):
        """Load all historical odds data into memory for fast lookups"""
        print("Loading historical data into memory...")
        
        query = """
            SELECT 
                match_date,
                league_name,
                home_team,
                away_team,
                home_goals,
                away_goals,
                result,
                avg_h, avg_d, avg_a,
                home_shots, away_shots,
                home_shots_target, away_shots_target,
                home_corners, away_corners,
                home_fouls, away_fouls,
                home_yellows, away_yellows,
                home_reds, away_reds
            FROM historical_odds
            WHERE league_name IS NOT NULL
        """
        
        if as_of_date:
            query += f" AND match_date < '{as_of_date}'"
        
        query += " ORDER BY match_date"
        
        self.historical_cache = pd.read_sql(query, self.db.engine)
        self.historical_cache['match_date'] = pd.to_datetime(self.historical_cache['match_date'])
        
        print(f"Loaded {len(self.historical_cache)} historical matches")
        print(f"Date range: {self.historical_cache['match_date'].min()} to {self.historical_cache['match_date'].max()}")
        print(f"Leagues: {self.historical_cache['league_name'].nunique()}")
        
        return self.historical_cache
    
    def get_team_last_n_matches(self, team: str, as_of_date: pd.Timestamp, 
                                n: int = 5, league: Optional[str] = None) -> pd.DataFrame:
        """Get last N matches for a team before a given date"""
        if self.historical_cache is None:
            raise ValueError("Historical data not loaded. Call load_historical_data() first.")
        
        team_matches = self.historical_cache[
            ((self.historical_cache['home_team'] == team) | 
             (self.historical_cache['away_team'] == team)) &
            (self.historical_cache['match_date'] < as_of_date)
        ]
        
        if league:
            team_matches = team_matches[team_matches['league_name'] == league]
        
        return team_matches.sort_values('match_date', ascending=False).head(n)
    
    def compute_team_form_features(self, team: str, as_of_date: pd.Timestamp, 
                                   n: int = 5, league: Optional[str] = None) -> Dict:
        """Compute team form features from last N matches"""
        matches = self.get_team_last_n_matches(team, as_of_date, n, league)
        
        if len(matches) == 0:
            return self._empty_form_features(n)
        
        features = {}
        wins = draws = losses = 0
        goals_for = goals_against = 0
        points = 0
        
        for _, match in matches.iterrows():
            is_home = match['home_team'] == team
            
            if is_home:
                gf, ga = match['home_goals'], match['away_goals']
                result = match['result']
                if result == 'H':
                    wins += 1
                    points += 3
                elif result == 'D':
                    draws += 1
                    points += 1
                else:
                    losses += 1
            else:
                gf, ga = match['away_goals'], match['home_goals']
                result = match['result']
                if result == 'A':
                    wins += 1
                    points += 3
                elif result == 'D':
                    draws += 1
                    points += 1
                else:
                    losses += 1
            
            goals_for += gf
            goals_against += ga
        
        num_matches = len(matches)
        
        features[f'form_last{n}_wins'] = wins
        features[f'form_last{n}_draws'] = draws
        features[f'form_last{n}_losses'] = losses
        features[f'form_last{n}_points'] = points
        features[f'form_last{n}_win_rate'] = wins / num_matches if num_matches > 0 else 0
        features[f'form_last{n}_ppg'] = points / num_matches if num_matches > 0 else 0
        features[f'form_last{n}_goals_for'] = goals_for
        features[f'form_last{n}_goals_against'] = goals_against
        features[f'form_last{n}_goal_diff'] = goals_for - goals_against
        features[f'form_last{n}_avg_goals_for'] = goals_for / num_matches if num_matches > 0 else 0
        features[f'form_last{n}_avg_goals_against'] = goals_against / num_matches if num_matches > 0 else 0
        features[f'form_last{n}_matches'] = num_matches
        
        return features
    
    def compute_venue_form_features(self, team: str, as_of_date: pd.Timestamp,
                                    is_home: bool, n: int = 10, league: Optional[str] = None) -> Dict:
        """Compute venue-specific form (home or away only)"""
        all_matches = self.get_team_last_n_matches(team, as_of_date, n * 2, league)
        
        if is_home:
            venue_matches = all_matches[all_matches['home_team'] == team].head(n)
            prefix = 'home'
        else:
            venue_matches = all_matches[all_matches['away_team'] == team].head(n)
            prefix = 'away'
        
        if len(venue_matches) == 0:
            return self._empty_venue_features(prefix, n)
        
        features = {}
        wins = draws = losses = 0
        goals_for = goals_against = 0
        
        for _, match in venue_matches.iterrows():
            if is_home:
                gf, ga = match['home_goals'], match['away_goals']
                result = match['result']
                if result == 'H':
                    wins += 1
                elif result == 'D':
                    draws += 1
                else:
                    losses += 1
            else:
                gf, ga = match['away_goals'], match['home_goals']
                result = match['result']
                if result == 'A':
                    wins += 1
                elif result == 'D':
                    draws += 1
                else:
                    losses += 1
            
            goals_for += gf
            goals_against += ga
        
        num_matches = len(venue_matches)
        
        features[f'{prefix}_last{n}_win_rate'] = wins / num_matches if num_matches > 0 else 0
        features[f'{prefix}_last{n}_ppg'] = (wins * 3 + draws) / num_matches if num_matches > 0 else 0
        features[f'{prefix}_last{n}_avg_goals_for'] = goals_for / num_matches if num_matches > 0 else 0
        features[f'{prefix}_last{n}_avg_goals_against'] = goals_against / num_matches if num_matches > 0 else 0
        features[f'{prefix}_last{n}_matches'] = num_matches
        
        return features
    
    def compute_h2h_features(self, home_team: str, away_team: str, 
                            as_of_date: pd.Timestamp, n: int = 5) -> Dict:
        """Compute head-to-head features between two teams"""
        if self.historical_cache is None:
            raise ValueError("Historical data not loaded. Call load_historical_data() first.")
        
        h2h_matches = self.historical_cache[
            ((self.historical_cache['home_team'] == home_team) & 
             (self.historical_cache['away_team'] == away_team)) |
            ((self.historical_cache['home_team'] == away_team) & 
             (self.historical_cache['away_team'] == home_team))
        ]
        h2h_matches = h2h_matches[h2h_matches['match_date'] < as_of_date]
        h2h_matches = h2h_matches.sort_values('match_date', ascending=False).head(n)
        
        if len(h2h_matches) == 0:
            return self._empty_h2h_features(n)
        
        features = {}
        home_wins = draws = away_wins = 0
        total_goals = 0
        home_goals_advantage = 0
        
        for _, match in h2h_matches.iterrows():
            if match['home_team'] == home_team:
                if match['result'] == 'H':
                    home_wins += 1
                elif match['result'] == 'D':
                    draws += 1
                else:
                    away_wins += 1
                home_goals_advantage += (match['home_goals'] - match['away_goals'])
            else:
                if match['result'] == 'A':
                    home_wins += 1
                elif match['result'] == 'D':
                    draws += 1
                else:
                    away_wins += 1
                home_goals_advantage += (match['away_goals'] - match['home_goals'])
            
            total_goals += match['home_goals'] + match['away_goals']
        
        num_matches = len(h2h_matches)
        
        features[f'h2h_last{n}_home_wins'] = home_wins
        features[f'h2h_last{n}_draws'] = draws
        features[f'h2h_last{n}_away_wins'] = away_wins
        features[f'h2h_last{n}_home_win_rate'] = home_wins / num_matches if num_matches > 0 else 0
        features[f'h2h_last{n}_avg_total_goals'] = total_goals / num_matches if num_matches > 0 else 0
        features[f'h2h_last{n}_home_goal_advantage'] = home_goals_advantage / num_matches if num_matches > 0 else 0
        features[f'h2h_last{n}_matches'] = num_matches
        
        return features
    
    def compute_temporal_features(self, team: str, as_of_date: pd.Timestamp, 
                                  league: Optional[str] = None) -> Dict:
        """Compute temporal features (days since last match, fixture congestion)"""
        last_match = self.get_team_last_n_matches(team, as_of_date, 1, league)
        
        if len(last_match) == 0:
            return {
                'days_since_last_match': 999,
                'matches_last_7days': 0,
                'matches_last_14days': 0,
                'matches_last_30days': 0
            }
        
        last_match_date = last_match.iloc[0]['match_date']
        days_since = (as_of_date - last_match_date).days
        
        recent_matches = self.get_team_last_n_matches(team, as_of_date, 20, league)
        
        matches_7d = len(recent_matches[recent_matches['match_date'] >= as_of_date - timedelta(days=7)])
        matches_14d = len(recent_matches[recent_matches['match_date'] >= as_of_date - timedelta(days=14)])
        matches_30d = len(recent_matches[recent_matches['match_date'] >= as_of_date - timedelta(days=30)])
        
        return {
            'days_since_last_match': min(days_since, 999),
            'matches_last_7days': matches_7d,
            'matches_last_14days': matches_14d,
            'matches_last_30days': matches_30d
        }
    
    def compute_advanced_stats_features(self, team: str, as_of_date: pd.Timestamp,
                                       is_home: bool, n: int = 5, league: Optional[str] = None) -> Dict:
        """Compute advanced stats (shooting, corners, discipline) when available"""
        matches = self.get_team_last_n_matches(team, as_of_date, n, league)
        
        if len(matches) == 0:
            return self._empty_advanced_features(n)
        
        features = {}
        shots = shots_on_target = corners = fouls = yellows = reds = 0
        goals = 0
        valid_matches = 0
        
        for _, match in matches.iterrows():
            team_is_home = match['home_team'] == team
            
            if pd.notna(match['home_shots']) and pd.notna(match['away_shots']):
                if team_is_home:
                    shots += match['home_shots']
                    shots_on_target += match['home_shots_target'] if pd.notna(match['home_shots_target']) else 0
                    corners += match['home_corners'] if pd.notna(match['home_corners']) else 0
                    fouls += match['home_fouls'] if pd.notna(match['home_fouls']) else 0
                    yellows += match['home_yellows'] if pd.notna(match['home_yellows']) else 0
                    reds += match['home_reds'] if pd.notna(match['home_reds']) else 0
                    goals += match['home_goals']
                else:
                    shots += match['away_shots']
                    shots_on_target += match['away_shots_target'] if pd.notna(match['away_shots_target']) else 0
                    corners += match['away_corners'] if pd.notna(match['away_corners']) else 0
                    fouls += match['away_fouls'] if pd.notna(match['away_fouls']) else 0
                    yellows += match['away_yellows'] if pd.notna(match['away_yellows']) else 0
                    reds += match['away_reds'] if pd.notna(match['away_reds']) else 0
                    goals += match['away_goals']
                
                valid_matches += 1
        
        if valid_matches == 0:
            return self._empty_advanced_features(n)
        
        features[f'adv_last{n}_avg_shots'] = shots / valid_matches
        features[f'adv_last{n}_avg_shots_on_target'] = shots_on_target / valid_matches
        features[f'adv_last{n}_shot_accuracy'] = shots_on_target / shots if shots > 0 else 0
        features[f'adv_last{n}_conversion_rate'] = goals / shots_on_target if shots_on_target > 0 else 0
        features[f'adv_last{n}_avg_corners'] = corners / valid_matches
        features[f'adv_last{n}_avg_fouls'] = fouls / valid_matches
        features[f'adv_last{n}_avg_yellows'] = yellows / valid_matches
        features[f'adv_last{n}_avg_reds'] = reds / valid_matches
        
        return features
    
    def extract_all_features(self, home_team: str, away_team: str, 
                            match_date: pd.Timestamp, league: Optional[str] = None) -> Dict:
        """Extract all features for a single match"""
        features = {}
        
        # Team form (last 5 and last 10)
        home_form_5 = self.compute_team_form_features(home_team, match_date, 5, league)
        away_form_5 = self.compute_team_form_features(away_team, match_date, 5, league)
        
        for key, val in home_form_5.items():
            features[f'home_{key}'] = val
        for key, val in away_form_5.items():
            features[f'away_{key}'] = val
        
        # Venue-specific form
        home_venue = self.compute_venue_form_features(home_team, match_date, True, 10, league)
        away_venue = self.compute_venue_form_features(away_team, match_date, False, 10, league)
        
        features.update(home_venue)
        features.update(away_venue)
        
        # Head-to-head
        h2h = self.compute_h2h_features(home_team, away_team, match_date, 5)
        features.update(h2h)
        
        # Temporal features
        home_temporal = self.compute_temporal_features(home_team, match_date, league)
        away_temporal = self.compute_temporal_features(away_team, match_date, league)
        
        for key, val in home_temporal.items():
            features[f'home_{key}'] = val
        for key, val in away_temporal.items():
            features[f'away_{key}'] = val
        
        # Advanced stats (last 5)
        home_advanced = self.compute_advanced_stats_features(home_team, match_date, True, 5, league)
        away_advanced = self.compute_advanced_stats_features(away_team, match_date, False, 5, league)
        
        for key, val in home_advanced.items():
            features[f'home_{key}'] = val
        for key, val in away_advanced.items():
            features[f'away_{key}'] = val
        
        return features
    
    def _empty_form_features(self, n: int) -> Dict:
        """Return empty form features when no data available"""
        return {
            f'form_last{n}_wins': 0,
            f'form_last{n}_draws': 0,
            f'form_last{n}_losses': 0,
            f'form_last{n}_points': 0,
            f'form_last{n}_win_rate': 0.33,
            f'form_last{n}_ppg': 1.0,
            f'form_last{n}_goals_for': 0,
            f'form_last{n}_goals_against': 0,
            f'form_last{n}_goal_diff': 0,
            f'form_last{n}_avg_goals_for': 1.0,
            f'form_last{n}_avg_goals_against': 1.0,
            f'form_last{n}_matches': 0
        }
    
    def _empty_venue_features(self, prefix: str, n: int) -> Dict:
        """Return empty venue features when no data available"""
        return {
            f'{prefix}_last{n}_win_rate': 0.33 if prefix == 'home' else 0.25,
            f'{prefix}_last{n}_ppg': 1.0 if prefix == 'home' else 0.8,
            f'{prefix}_last{n}_avg_goals_for': 1.0,
            f'{prefix}_last{n}_avg_goals_against': 1.0,
            f'{prefix}_last{n}_matches': 0
        }
    
    def _empty_h2h_features(self, n: int) -> Dict:
        """Return empty H2H features when no data available"""
        return {
            f'h2h_last{n}_home_wins': 0,
            f'h2h_last{n}_draws': 0,
            f'h2h_last{n}_away_wins': 0,
            f'h2h_last{n}_home_win_rate': 0.40,
            f'h2h_last{n}_avg_total_goals': 2.5,
            f'h2h_last{n}_home_goal_advantage': 0,
            f'h2h_last{n}_matches': 0
        }
    
    def _empty_advanced_features(self, n: int) -> Dict:
        """Return empty advanced features when no data available"""
        return {
            f'adv_last{n}_avg_shots': 12.0,
            f'adv_last{n}_avg_shots_on_target': 4.0,
            f'adv_last{n}_shot_accuracy': 0.33,
            f'adv_last{n}_conversion_rate': 0.25,
            f'adv_last{n}_avg_corners': 5.0,
            f'adv_last{n}_avg_fouls': 12.0,
            f'adv_last{n}_avg_yellows': 2.0,
            f'adv_last{n}_avg_reds': 0.1
        }


def enrich_training_matches(force: bool = False):
    """Enrich training_matches with historical features"""
    print("="*70)
    print("HISTORICAL FEATURE ENRICHMENT PIPELINE")
    print("="*70)
    
    db = DatabaseManager()
    extractor = HistoricalFeatureExtractor(db)
    
    extractor.load_historical_data()
    
    print("\nFetching training matches...")
    query = """
        SELECT 
            match_id,
            match_date,
            home_team,
            away_team,
            league_id
        FROM training_matches
        ORDER BY match_date
    """
    
    training_matches = pd.read_sql(query, db.engine)
    training_matches['match_date'] = pd.to_datetime(training_matches['match_date'])
    
    print(f"Found {len(training_matches)} training matches to enrich")
    
    all_features = []
    
    for idx, row in training_matches.iterrows():
        if idx % 50 == 0:
            print(f"Processing {idx}/{len(training_matches)}...")
        
        features = extractor.extract_all_features(
            home_team=row['home_team'],
            away_team=row['away_team'],
            match_date=row['match_date'],
            league=None  # League filtering not needed for now
        )
        
        features['match_id'] = row['match_id']
        all_features.append(features)
    
    features_df = pd.DataFrame(all_features)
    
    print(f"\n{'='*70}")
    print(f"FEATURE EXTRACTION COMPLETE")
    print(f"{'='*70}")
    print(f"Total matches enriched: {len(features_df)}")
    print(f"Total features extracted: {len(features_df.columns) - 1}")
    print(f"\nFeature categories:")
    print(f"  - Team form (last 5): 24 features (12 per team)")
    print(f"  - Venue form (last 10): 10 features (5 per team)")
    print(f"  - Head-to-head (last 5): 7 features")
    print(f"  - Temporal: 8 features (4 per team)")
    print(f"  - Advanced stats (last 5): 16 features (8 per team)")
    print(f"  Total: ~65 features")
    
    output_path = 'artifacts/datasets/historical_features.parquet'
    features_df.to_parquet(output_path, index=False)
    print(f"\nSaved to: {output_path}")
    
    print(f"\nSample features for first match:")
    print(features_df.head(1).T)
    
    db.close()
    
    return features_df


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Extract historical features')
    parser.add_argument('--force', action='store_true', help='Force recomputation')
    args = parser.parse_args()
    
    enrich_training_matches(force=args.force)
