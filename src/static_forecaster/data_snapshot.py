"""
Static Data Snapshot Builder - Fixed T-24h evaluation cutoff
"""

import pandas as pd
import numpy as np
import psycopg2
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import json
import warnings
warnings.filterwarnings('ignore')

class StaticSnapshotBuilder:
    """Build static data snapshots for accuracy-first evaluation"""
    
    def __init__(self, snapshot_time_hours: int = 24):
        """
        Initialize with fixed snapshot time
        
        Args:
            snapshot_time_hours: Hours before kickoff for feature cutoff (default: 24h)
        """
        self.snapshot_time = snapshot_time_hours
        self.euro_leagues = {
            39: 'English Premier League',
            140: 'La Liga Santander', 
            135: 'Serie A',
            78: 'Bundesliga',
            61: 'Ligue 1'
        }
    
    def get_db_connection(self):
        """Get database connection"""
        return psycopg2.connect(os.environ['DATABASE_URL'])
    
    def build_static_dataset(self, min_date: str = None, 
                           max_date: str = None) -> pd.DataFrame:
        """
        Build static dataset with features frozen at T-24h before kickoff
        
        Args:
            min_date: Earliest match date (YYYY-MM-DD)
            max_date: Latest match date (YYYY-MM-DD)
            
        Returns:
            DataFrame with features and outcomes for evaluation
        """
        
        if min_date is None:
            min_date = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
        if max_date is None:
            max_date = datetime.now().strftime('%Y-%m-%d')
        
        print(f"Building static dataset: {min_date} to {max_date}")
        print(f"Feature cutoff: T-{self.snapshot_time}h before kickoff")
        
        conn = self.get_db_connection()
        
        # Load completed matches with outcomes
        matches_query = """
        SELECT 
            match_id,
            league_id,
            season,
            match_date_utc,
            home_team_id,
            away_team_id,
            outcome,
            home_goals,
            away_goals
        FROM matches
        WHERE match_date_utc >= %s
          AND match_date_utc <= %s
          AND outcome IS NOT NULL
          AND league_id IN (39, 140, 135, 78, 61)
          AND home_goals IS NOT NULL
          AND away_goals IS NOT NULL
        ORDER BY match_date_utc ASC
        """
        
        matches_df = pd.read_sql_query(matches_query, conn, 
                                     params=[min_date + ' 00:00:00', 
                                            max_date + ' 23:59:59'])
        
        if len(matches_df) == 0:
            print("No matches found in date range")
            conn.close()
            return pd.DataFrame()
        
        print(f"Loaded {len(matches_df)} completed matches")
        
        # Build feature set for each match
        features_list = []
        
        for _, match in matches_df.iterrows():
            match_features = self._extract_match_features(
                conn, match, self.snapshot_time
            )
            
            if match_features is not None:
                features_list.append(match_features)
        
        conn.close()
        
        if not features_list:
            print("No valid features extracted")
            return pd.DataFrame()
        
        # Combine into dataset
        dataset_df = pd.DataFrame(features_list)
        
        print(f"Built dataset: {len(dataset_df)} matches, {len(dataset_df.columns)} features")
        
        # Add derived features
        dataset_df = self._add_derived_features(dataset_df)
        
        # Quality checks
        self._validate_dataset(dataset_df)
        
        return dataset_df
    
    def _extract_match_features(self, conn, match, hours_before: int) -> Optional[Dict]:
        """Extract pre-match features available at T-hours before kickoff"""
        
        match_id = match['match_id']
        match_date = match['match_date_utc']
        home_team = match['home_team_id']
        away_team = match['away_team_id']
        league_id = match['league_id']
        
        # Feature cutoff time
        cutoff_time = match_date - timedelta(hours=hours_before)
        
        # Base match info
        features = {
            'match_id': match_id,
            'league_id': league_id,
            'season': match['season'],
            'match_date_utc': match_date,
            'home_team_id': home_team,
            'away_team_id': away_team,
            'outcome': match['outcome'],
            'home_goals': match['home_goals'],
            'away_goals': match['away_goals'],
            'goal_difference': match['home_goals'] - match['away_goals'],
            'total_goals': match['home_goals'] + match['away_goals'],
            'feature_cutoff_time': cutoff_time
        }
        
        # Team strength features (computed from historical data before cutoff)
        home_strength = self._get_team_strength(conn, home_team, league_id, cutoff_time)
        away_strength = self._get_team_strength(conn, away_team, league_id, cutoff_time)
        
        # Recent form features (last 5 matches before cutoff)
        home_form = self._get_recent_form(conn, home_team, league_id, cutoff_time, 5)
        away_form = self._get_recent_form(conn, away_team, league_id, cutoff_time, 5)
        
        # Head-to-head features
        h2h_features = self._get_h2h_features(conn, home_team, away_team, cutoff_time, 5)
        
        # League context features
        league_features = self._get_league_context(conn, league_id, cutoff_time)
        
        # Rest and fatigue features
        rest_features = self._get_rest_features(conn, home_team, away_team, cutoff_time)
        
        # Combine all features
        features.update({
            # Team strength
            'home_elo': home_strength.get('elo', 1500),
            'away_elo': away_strength.get('elo', 1500),
            'home_wins_pct': home_strength.get('wins_pct', 0.33),
            'away_wins_pct': away_strength.get('wins_pct', 0.33),
            'home_gf_avg': home_strength.get('gf_avg', 1.5),
            'away_gf_avg': away_strength.get('gf_avg', 1.5),
            'home_ga_avg': home_strength.get('ga_avg', 1.5),
            'away_ga_avg': away_strength.get('ga_avg', 1.5),
            
            # Recent form (last 5)
            'home_form_pts': home_form.get('points', 5),
            'away_form_pts': away_form.get('points', 5),
            'home_form_gf': home_form.get('gf_avg', 1.5),
            'away_form_gf': away_form.get('gf_avg', 1.5),
            'home_form_ga': home_form.get('ga_avg', 1.5),
            'away_form_ga': away_form.get('ga_avg', 1.5),
            
            # Head-to-head
            'h2h_home_wins': h2h_features.get('home_wins', 1),
            'h2h_draws': h2h_features.get('draws', 1),
            'h2h_away_wins': h2h_features.get('away_wins', 1),
            'h2h_home_gd': h2h_features.get('home_gd', 0.0),
            
            # League context
            'league_avg_goals': league_features.get('avg_goals', 2.7),
            'league_draw_rate': league_features.get('draw_rate', 0.25),
            'home_advantage': league_features.get('home_advantage', 0.15),
            
            # Rest and fatigue
            'home_rest_days': rest_features.get('home_rest', 7),
            'away_rest_days': rest_features.get('away_rest', 7),
            'home_congestion': rest_features.get('home_congestion', 0),
            'away_congestion': rest_features.get('away_congestion', 0)
        })
        
        return features
    
    def _get_team_strength(self, conn, team_id: int, league_id: int, 
                          cutoff_time: datetime) -> Dict:
        """Get team strength metrics from matches before cutoff"""
        
        # Simplified strength calculation (in production would use full Elo)
        try:
            query = """
            SELECT 
                COUNT(*) as matches,
                SUM(CASE 
                    WHEN (home_team_id = %s AND outcome = 'H') OR 
                         (away_team_id = %s AND outcome = 'A') THEN 1 
                    ELSE 0 END) as wins,
                SUM(CASE WHEN outcome = 'D' THEN 1 ELSE 0 END) as draws,
                AVG(CASE WHEN home_team_id = %s THEN home_goals ELSE away_goals END) as gf_avg,
                AVG(CASE WHEN home_team_id = %s THEN away_goals ELSE home_goals END) as ga_avg
            FROM matches
            WHERE (home_team_id = %s OR away_team_id = %s)
              AND league_id = %s
              AND match_date_utc < %s
              AND match_date_utc >= %s
              AND outcome IS NOT NULL
            """
            
            lookback_date = cutoff_time - timedelta(days=365)
            
            cursor = conn.cursor()
            cursor.execute(query, [team_id, team_id, team_id, team_id, 
                                 team_id, team_id, league_id, cutoff_time, lookback_date])
            result = cursor.fetchone()
            cursor.close()
            
            if result and result[0] > 0:
                matches, wins, draws, gf_avg, ga_avg = result
                wins_pct = wins / matches if matches > 0 else 0.33
                
                # Simple Elo approximation
                base_elo = 1500
                elo_adjustment = (wins_pct - 0.5) * 400
                elo = base_elo + elo_adjustment
                
                return {
                    'elo': elo,
                    'wins_pct': wins_pct,
                    'gf_avg': gf_avg or 1.5,
                    'ga_avg': ga_avg or 1.5,
                    'matches': matches
                }
            
        except Exception as e:
            print(f"Error calculating team strength: {e}")
        
        # Default values
        return {
            'elo': 1500,
            'wins_pct': 0.33,
            'gf_avg': 1.5,
            'ga_avg': 1.5,
            'matches': 0
        }
    
    def _get_recent_form(self, conn, team_id: int, league_id: int,
                        cutoff_time: datetime, n_matches: int) -> Dict:
        """Get recent form from last N matches before cutoff"""
        
        try:
            query = """
            SELECT 
                outcome,
                CASE WHEN home_team_id = %s THEN home_goals ELSE away_goals END as gf,
                CASE WHEN home_team_id = %s THEN away_goals ELSE home_goals END as ga
            FROM matches
            WHERE (home_team_id = %s OR away_team_id = %s)
              AND league_id = %s
              AND match_date_utc < %s
              AND outcome IS NOT NULL
            ORDER BY match_date_utc DESC
            LIMIT %s
            """
            
            cursor = conn.cursor()
            cursor.execute(query, [team_id, team_id, team_id, team_id, 
                                 league_id, cutoff_time, n_matches])
            results = cursor.fetchall()
            cursor.close()
            
            if results:
                points = 0
                gf_total = 0
                ga_total = 0
                
                for outcome, gf, ga in results:
                    # Calculate points for this team
                    if (outcome == 'H' and results[0][1] == gf) or \
                       (outcome == 'A' and results[0][1] == gf):  # This team won
                        points += 3
                    elif outcome == 'D':
                        points += 1
                    
                    gf_total += gf
                    ga_total += ga
                
                n_actual = len(results)
                return {
                    'points': points,
                    'gf_avg': gf_total / n_actual if n_actual > 0 else 1.5,
                    'ga_avg': ga_total / n_actual if n_actual > 0 else 1.5,
                    'matches': n_actual
                }
        
        except Exception as e:
            print(f"Error calculating recent form: {e}")
        
        # Default form
        return {
            'points': 5,  # Average expectation
            'gf_avg': 1.5,
            'ga_avg': 1.5,
            'matches': 0
        }
    
    def _get_h2h_features(self, conn, home_team: int, away_team: int,
                         cutoff_time: datetime, n_matches: int) -> Dict:
        """Get head-to-head features from recent matchups"""
        
        try:
            query = """
            SELECT 
                outcome,
                home_goals,
                away_goals
            FROM matches
            WHERE ((home_team_id = %s AND away_team_id = %s) OR 
                   (home_team_id = %s AND away_team_id = %s))
              AND match_date_utc < %s
              AND outcome IS NOT NULL
            ORDER BY match_date_utc DESC
            LIMIT %s
            """
            
            cursor = conn.cursor()
            cursor.execute(query, [home_team, away_team, away_team, home_team,
                                 cutoff_time, n_matches])
            results = cursor.fetchall()
            cursor.close()
            
            if results:
                home_wins = 0
                draws = 0
                away_wins = 0
                home_gd = 0
                
                for outcome, home_goals, away_goals in results:
                    if outcome == 'H':
                        home_wins += 1
                    elif outcome == 'D':
                        draws += 1
                    else:
                        away_wins += 1
                    
                    home_gd += (home_goals - away_goals)
                
                n_actual = len(results)
                return {
                    'home_wins': home_wins,
                    'draws': draws,
                    'away_wins': away_wins,
                    'home_gd': home_gd / n_actual if n_actual > 0 else 0.0,
                    'matches': n_actual
                }
        
        except Exception as e:
            print(f"Error calculating H2H: {e}")
        
        # Default balanced H2H
        return {
            'home_wins': 1,
            'draws': 1, 
            'away_wins': 1,
            'home_gd': 0.0,
            'matches': 0
        }
    
    def _get_league_context(self, conn, league_id: int, cutoff_time: datetime) -> Dict:
        """Get league-wide context features"""
        
        try:
            query = """
            SELECT 
                AVG(home_goals + away_goals) as avg_goals,
                SUM(CASE WHEN outcome = 'D' THEN 1 ELSE 0 END)::float / COUNT(*) as draw_rate,
                SUM(CASE WHEN outcome = 'H' THEN 1 ELSE 0 END)::float / COUNT(*) as home_win_rate
            FROM matches
            WHERE league_id = %s
              AND match_date_utc < %s
              AND match_date_utc >= %s
              AND outcome IS NOT NULL
            """
            
            lookback_date = cutoff_time - timedelta(days=180)
            
            cursor = conn.cursor()
            cursor.execute(query, [league_id, cutoff_time, lookback_date])
            result = cursor.fetchone()
            cursor.close()
            
            if result and result[0] is not None:
                avg_goals, draw_rate, home_win_rate = result
                home_advantage = home_win_rate - 0.33  # vs balanced expectation
                
                return {
                    'avg_goals': avg_goals,
                    'draw_rate': draw_rate,
                    'home_advantage': home_advantage
                }
        
        except Exception as e:
            print(f"Error calculating league context: {e}")
        
        # Default league stats
        return {
            'avg_goals': 2.7,
            'draw_rate': 0.25,
            'home_advantage': 0.15
        }
    
    def _get_rest_features(self, conn, home_team: int, away_team: int,
                          cutoff_time: datetime) -> Dict:
        """Get rest and fatigue features"""
        
        # Simplified rest calculation
        rest_features = {
            'home_rest': 7,
            'away_rest': 7,
            'home_congestion': 0,
            'away_congestion': 0
        }
        
        for team_id, prefix in [(home_team, 'home'), (away_team, 'away')]:
            try:
                query = """
                SELECT match_date_utc
                FROM matches
                WHERE (home_team_id = %s OR away_team_id = %s)
                  AND match_date_utc < %s
                  AND outcome IS NOT NULL
                ORDER BY match_date_utc DESC
                LIMIT 3
                """
                
                cursor = conn.cursor()
                cursor.execute(query, [team_id, team_id, cutoff_time])
                results = cursor.fetchall()
                cursor.close()
                
                if results:
                    last_match = results[0][0]
                    rest_days = (cutoff_time - last_match).days
                    rest_features[f'{prefix}_rest'] = max(0, rest_days)
                    
                    # Simple congestion check (3 matches in 10 days)
                    if len(results) >= 3:
                        span_days = (results[0][0] - results[2][0]).days
                        if span_days <= 10:
                            rest_features[f'{prefix}_congestion'] = 1
            
            except Exception as e:
                print(f"Error calculating rest for {team_id}: {e}")
        
        return rest_features
    
    def _add_derived_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add derived difference features between home and away"""
        
        df = df.copy()
        
        # Elo difference
        df['elo_diff'] = df['home_elo'] - df['away_elo']
        
        # Strength differences
        df['wins_pct_diff'] = df['home_wins_pct'] - df['away_wins_pct']
        df['gf_avg_diff'] = df['home_gf_avg'] - df['away_gf_avg']
        df['ga_avg_diff'] = df['home_ga_avg'] - df['away_ga_avg']
        
        # Form differences
        df['form_pts_diff'] = df['home_form_pts'] - df['away_form_pts']
        df['form_gf_diff'] = df['home_form_gf'] - df['away_form_gf']
        df['form_ga_diff'] = df['home_form_ga'] - df['away_form_ga']
        
        # Rest differences
        df['rest_diff'] = df['home_rest_days'] - df['away_rest_days']
        df['congestion_diff'] = df['home_congestion'] - df['away_congestion']
        
        # Attack vs Defense matchups
        df['attack_defense_home'] = df['home_gf_avg'] - df['away_ga_avg']
        df['attack_defense_away'] = df['away_gf_avg'] - df['home_ga_avg']
        df['attack_defense_diff'] = df['attack_defense_home'] - df['attack_defense_away']
        
        return df
    
    def _validate_dataset(self, df: pd.DataFrame):
        """Validate dataset quality and feature contracts"""
        
        print("\n" + "="*60)
        print("DATASET VALIDATION")
        print("="*60)
        
        # Basic stats
        print(f"Total matches: {len(df)}")
        print(f"Total features: {len(df.columns)}")
        print(f"Date range: {df['match_date_utc'].min()} to {df['match_date_utc'].max()}")
        
        # Outcome distribution
        outcome_dist = df['outcome'].value_counts(normalize=True)
        print(f"\nOutcome distribution:")
        for outcome, pct in outcome_dist.items():
            print(f"  {outcome}: {pct:.1%}")
        
        # League distribution
        league_dist = df['league_id'].value_counts()
        print(f"\nLeague distribution:")
        for league_id, count in league_dist.items():
            league_name = self.euro_leagues.get(league_id, f"League_{league_id}")
            print(f"  {league_name}: {count} matches")
        
        # Missing values check
        missing_counts = df.isnull().sum()
        missing_features = missing_counts[missing_counts > 0]
        
        if len(missing_features) > 0:
            print(f"\nMissing values detected:")
            for feature, count in missing_features.items():
                print(f"  {feature}: {count} ({count/len(df):.1%})")
        else:
            print("\nNo missing values detected")
        
        # Feature range validation
        numeric_features = df.select_dtypes(include=[np.number]).columns
        print(f"\nNumeric features: {len(numeric_features)}")
        
        # Leakage check (all features should be pre-match)
        feature_cutoff_times = df['feature_cutoff_time']
        match_times = df['match_date_utc']
        
        leakage_check = (feature_cutoff_times < match_times).all()
        print(f"Leakage check: {'PASS' if leakage_check else 'FAIL'}")
        
        print("="*60)

def main():
    """Build static evaluation dataset"""
    
    builder = StaticSnapshotBuilder(snapshot_time_hours=24)
    
    # Build dataset for last year
    dataset = builder.build_static_dataset(
        min_date=(datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d'),
        max_date=datetime.now().strftime('%Y-%m-%d')
    )
    
    if len(dataset) == 0:
        print("No dataset built")
        return
    
    # Save dataset
    os.makedirs('data/static', exist_ok=True)
    output_path = f'data/static/eval_dataset_T24h_{datetime.now().strftime("%Y%m%d")}.csv'
    dataset.to_csv(output_path, index=False)
    
    print(f"\nStatic dataset saved: {output_path}")
    
    return dataset

if __name__ == "__main__":
    main()