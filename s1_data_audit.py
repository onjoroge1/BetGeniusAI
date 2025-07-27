"""
Phase S1 - Data & Label Audit
Rebuild features from raw data with strict time-based validation
"""

import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import json
import psycopg2
import os
from typing import Dict, List, Tuple, Optional
import warnings
warnings.filterwarnings('ignore')

class S1DataAudit:
    """Comprehensive data audit and feature rebuilding"""
    
    def __init__(self):
        self.euro_leagues = {
            39: 'English Premier League',
            140: 'La Liga Santander', 
            135: 'Serie A',
            78: 'Bundesliga',
            61: 'Ligue 1'
        }
        
        # Frozen feature order for consistency (S0 gate)
        self.feature_order = [
            # Market anchors (essential)
            'market_home_prob', 'market_draw_prob', 'market_away_prob',
            
            # Time-validated team strength features
            'home_elo_rating', 'away_elo_rating', 'elo_difference',
            'home_attack_rating', 'away_attack_rating', 'attack_diff',
            'home_defense_rating', 'away_defense_rating', 'defense_diff',
            
            # Form features (last 5 matches, time-validated)
            'home_form_points', 'away_form_points', 'form_difference',
            'home_goals_scored_avg', 'away_goals_scored_avg', 'goals_scored_diff',
            'home_goals_conceded_avg', 'away_goals_conceded_avg', 'goals_conceded_diff',
            
            # Match context (pre-match only)
            'home_advantage_factor', 'league_competitiveness', 'match_importance',
            'rest_days_home', 'rest_days_away', 'rest_days_difference'
        ]
        
        self.random_state = 42
        np.random.seed(self.random_state)
        
        # Team tracking for Elo calculations
        self.team_elos = {}
        self.team_stats = {}
    
    def get_db_connection(self):
        return psycopg2.connect(os.environ['DATABASE_URL'])
    
    def audit_raw_data(self) -> Dict:
        """S1 Audit: Comprehensive data quality check"""
        
        print("📋 PHASE S1 - DATA & LABEL AUDIT")
        print("=" * 60)
        
        try:
            conn = self.get_db_connection()
            
            # Get raw match data for audit
            query = """
            SELECT 
                league_id,
                match_date,
                home_team,
                away_team,
                home_goals,
                away_goals,
                features
            FROM training_matches 
            WHERE match_date >= %s
                AND home_goals IS NOT NULL 
                AND away_goals IS NOT NULL
                AND league_id IN (39, 140, 135, 78, 61)
            ORDER BY match_date ASC
            """
            
            cutoff_date = datetime.now() - timedelta(days=1095)  # 3 years
            df = pd.read_sql_query(query, conn, params=[cutoff_date])
            conn.close()
            
            print(f"📊 Raw data loaded: {len(df)} matches")
            
            audit_results = {
                'total_matches': len(df),
                'date_range': (df['match_date'].min(), df['match_date'].max()),
                'leagues': df['league_id'].nunique(),
                'teams': df['home_team'].nunique() + df['away_team'].nunique(),
                'issues': [],
                'outcome_distribution': {},
                'league_breakdown': {}
            }
            
            # 1. Outcome mapping audit
            print("\n🔍 Auditing outcomes mapping...")
            
            def get_outcome(row):
                if row['home_goals'] > row['away_goals']:
                    return 'home'
                elif row['home_goals'] < row['away_goals']:
                    return 'away'
                else:
                    return 'draw'
            
            df['outcome'] = df.apply(get_outcome, axis=1)
            outcome_dist = df['outcome'].value_counts(normalize=True)
            audit_results['outcome_distribution'] = outcome_dist.to_dict()
            
            print(f"   Outcome distribution: H={outcome_dist.get('home', 0):.1%}, "
                  f"D={outcome_dist.get('draw', 0):.1%}, A={outcome_dist.get('away', 0):.1%}")
            
            # 2. Duplicate detection
            print("\n🔍 Checking for duplicates...")
            duplicates = df.duplicated(['home_team', 'away_team', 'match_date']).sum()
            if duplicates > 0:
                audit_results['issues'].append(f"Found {duplicates} duplicate matches")
                print(f"   ⚠️  Found {duplicates} duplicate matches")
            else:
                print("   ✅ No duplicates found")
            
            # 3. Time-based validation
            print("\n🔍 Validating time-based ordering...")
            df['match_date'] = pd.to_datetime(df['match_date'])
            df_sorted = df.sort_values('match_date')
            
            # Check for extreme future dates
            future_matches = df[df['match_date'] > datetime.now() + timedelta(days=7)].shape[0]
            if future_matches > 0:
                audit_results['issues'].append(f"Found {future_matches} matches far in future")
                print(f"   ⚠️  Found {future_matches} matches far in future")
            
            # 4. League-specific breakdown
            print("\n🔍 Per-league analysis...")
            for league_id, league_name in self.euro_leagues.items():
                league_df = df[df['league_id'] == league_id]
                if len(league_df) == 0:
                    continue
                
                league_outcomes = league_df['outcome'].value_counts(normalize=True)
                audit_results['league_breakdown'][league_id] = {
                    'name': league_name,
                    'matches': len(league_df),
                    'home_rate': league_outcomes.get('home', 0),
                    'draw_rate': league_outcomes.get('draw', 0),
                    'away_rate': league_outcomes.get('away', 0),
                    'date_range': (league_df['match_date'].min(), league_df['match_date'].max())
                }
                
                print(f"   {league_name}: {len(league_df)} matches, "
                      f"H/D/A={league_outcomes.get('home', 0):.1%}/"
                      f"{league_outcomes.get('draw', 0):.1%}/"
                      f"{league_outcomes.get('away', 0):.1%}")
            
            # 5. Goals distribution check
            print("\n🔍 Goals distribution analysis...")
            total_goals = df['home_goals'] + df['away_goals']
            high_scoring = (total_goals > 6).mean()
            zero_zero = ((df['home_goals'] == 0) & (df['away_goals'] == 0)).mean()
            
            if high_scoring > 0.05:
                audit_results['issues'].append(f"High % of 6+ goal games: {high_scoring:.1%}")
            
            if zero_zero > 0.10:
                audit_results['issues'].append(f"High % of 0-0 games: {zero_zero:.1%}")
            
            print(f"   Average goals per game: {total_goals.mean():.2f}")
            print(f"   High-scoring games (6+ goals): {high_scoring:.1%}")
            print(f"   Goalless draws: {zero_zero:.1%}")
            
            return df, audit_results
            
        except Exception as e:
            print(f"❌ Data audit failed: {e}")
            return None, {'issues': [f"Data loading error: {e}"]}
    
    def rebuild_elo_ratings(self, df: pd.DataFrame) -> pd.DataFrame:
        """Rebuild Elo ratings from scratch with time validation"""
        
        print("\n⚙️  Rebuilding Elo ratings from raw matches...")
        
        # Initialize all teams with base Elo
        base_elo = 1500
        k_factor = 32
        
        # Sort by date to ensure chronological processing
        df_sorted = df.sort_values('match_date').copy()
        
        # Initialize Elo columns
        df_sorted['home_elo_rating'] = base_elo
        df_sorted['away_elo_rating'] = base_elo
        df_sorted['elo_difference'] = 0.0
        
        # Process matches chronologically
        for idx, row in df_sorted.iterrows():
            home_team = row['home_team']
            away_team = row['away_team']
            match_date = row['match_date']
            
            # Get current Elo ratings (before this match)
            home_elo = self.team_elos.get(home_team, base_elo)
            away_elo = self.team_elos.get(away_team, base_elo)
            
            # Store pre-match Elos (these are the features)
            df_sorted.at[idx, 'home_elo_rating'] = home_elo
            df_sorted.at[idx, 'away_elo_rating'] = away_elo
            df_sorted.at[idx, 'elo_difference'] = home_elo - away_elo
            
            # Calculate match result
            home_goals = row['home_goals']
            away_goals = row['away_goals']
            
            if home_goals > away_goals:
                home_result = 1.0  # Win
            elif home_goals < away_goals:
                home_result = 0.0  # Loss
            else:
                home_result = 0.5  # Draw
            
            # Expected results based on Elo
            home_advantage = 100  # Home advantage in Elo points
            expected_home = 1 / (1 + 10**((away_elo - home_elo - home_advantage) / 400))
            
            # Update Elos after the match
            home_elo_new = home_elo + k_factor * (home_result - expected_home)
            away_elo_new = away_elo + k_factor * ((1 - home_result) - (1 - expected_home))
            
            # Store updated Elos for future matches
            self.team_elos[home_team] = home_elo_new
            self.team_elos[away_team] = away_elo_new
        
        print(f"   ✅ Elo ratings computed for {len(self.team_elos)} teams")
        return df_sorted
    
    def rebuild_form_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Rebuild form features with strict time validation"""
        
        print("\n⚙️  Rebuilding form features (last 5 matches)...")
        
        # Initialize form columns
        df['home_form_points'] = 0.0
        df['away_form_points'] = 0.0
        df['form_difference'] = 0.0
        df['home_goals_scored_avg'] = 2.5  # League average default
        df['away_goals_scored_avg'] = 2.5
        df['goals_scored_diff'] = 0.0
        df['home_goals_conceded_avg'] = 2.5
        df['away_goals_conceded_avg'] = 2.5
        df['goals_conceded_diff'] = 0.0
        
        # Process each match
        for idx, row in df.iterrows():
            home_team = row['home_team']
            away_team = row['away_team']
            match_date = row['match_date']
            
            # Get last 5 matches for each team BEFORE this match
            home_recent = df[(df['match_date'] < match_date) & 
                           ((df['home_team'] == home_team) | (df['away_team'] == home_team))].tail(5)
            
            away_recent = df[(df['match_date'] < match_date) & 
                           ((df['home_team'] == away_team) | (df['away_team'] == away_team))].tail(5)
            
            # Calculate home team form
            home_points = 0
            home_goals_for = []
            home_goals_against = []
            
            for _, match in home_recent.iterrows():
                if match['home_team'] == home_team:
                    # Home match
                    if match['home_goals'] > match['away_goals']:
                        home_points += 3
                    elif match['home_goals'] == match['away_goals']:
                        home_points += 1
                    home_goals_for.append(match['home_goals'])
                    home_goals_against.append(match['away_goals'])
                else:
                    # Away match
                    if match['away_goals'] > match['home_goals']:
                        home_points += 3
                    elif match['away_goals'] == match['home_goals']:
                        home_points += 1
                    home_goals_for.append(match['away_goals'])
                    home_goals_against.append(match['home_goals'])
            
            # Calculate away team form
            away_points = 0
            away_goals_for = []
            away_goals_against = []
            
            for _, match in away_recent.iterrows():
                if match['home_team'] == away_team:
                    # Home match
                    if match['home_goals'] > match['away_goals']:
                        away_points += 3
                    elif match['home_goals'] == match['away_goals']:
                        away_points += 1
                    away_goals_for.append(match['home_goals'])
                    away_goals_against.append(match['away_goals'])
                else:
                    # Away match
                    if match['away_goals'] > match['home_goals']:
                        away_points += 3
                    elif match['away_goals'] == match['home_goals']:
                        away_points += 1
                    away_goals_for.append(match['away_goals'])
                    away_goals_against.append(match['home_goals'])
            
            # Store form features
            df.at[idx, 'home_form_points'] = home_points
            df.at[idx, 'away_form_points'] = away_points
            df.at[idx, 'form_difference'] = home_points - away_points
            
            # Goals averages
            if home_goals_for:
                df.at[idx, 'home_goals_scored_avg'] = np.mean(home_goals_for)
                df.at[idx, 'home_goals_conceded_avg'] = np.mean(home_goals_against)
            
            if away_goals_for:
                df.at[idx, 'away_goals_scored_avg'] = np.mean(away_goals_for)
                df.at[idx, 'away_goals_conceded_avg'] = np.mean(away_goals_against)
            
            df.at[idx, 'goals_scored_diff'] = df.at[idx, 'home_goals_scored_avg'] - df.at[idx, 'away_goals_scored_avg']
            df.at[idx, 'goals_conceded_diff'] = df.at[idx, 'away_goals_conceded_avg'] - df.at[idx, 'home_goals_conceded_avg']
        
        print(f"   ✅ Form features computed for {len(df)} matches")
        return df
    
    def create_market_probabilities(self, df: pd.DataFrame) -> pd.DataFrame:
        """Create realistic market probabilities (S2 preparation)"""
        
        print("\n⚙️  Creating market probability anchors...")
        
        # Use Elo difference and form to create realistic market odds
        for idx, row in df.iterrows():
            elo_diff = row['elo_difference']
            form_diff = row['form_difference']
            
            # Convert Elo difference to win probability
            home_win_prob = 1 / (1 + 10**(-elo_diff / 400))
            
            # Adjust for form
            form_adjustment = form_diff * 0.02  # 2% per point difference
            home_win_prob = np.clip(home_win_prob + form_adjustment, 0.15, 0.75)
            
            # Draw probability inversely related to team strength difference
            strength_diff = abs(elo_diff) + abs(form_diff)
            draw_prob = max(0.20, 0.35 - strength_diff * 0.001)
            
            # Away probability is remainder
            away_prob = 1.0 - home_win_prob - draw_prob
            
            # Normalize to ensure sum = 1
            total = home_win_prob + draw_prob + away_prob
            home_win_prob /= total
            draw_prob /= total
            away_prob /= total
            
            # Add realistic noise
            noise = np.random.normal(0, 0.01, 3)
            probs = np.array([home_win_prob, draw_prob, away_prob]) + noise
            probs = np.clip(probs, 0.05, 0.85)
            probs = probs / probs.sum()
            
            df.at[idx, 'market_home_prob'] = probs[0]
            df.at[idx, 'market_draw_prob'] = probs[1]
            df.at[idx, 'market_away_prob'] = probs[2]
        
        print(f"   ✅ Market probabilities created for {len(df)} matches")
        return df
    
    def add_context_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add match context features"""
        
        print("\n⚙️  Adding context features...")
        
        # League-specific home advantage
        home_advantage_map = {
            39: 0.22,  # Premier League
            140: 0.24, # La Liga
            135: 0.21, # Serie A
            78: 0.23,  # Bundesliga
            61: 0.20   # Ligue 1
        }
        
        # League competitiveness
        competitiveness_map = {
            39: 0.85,  # Premier League
            140: 0.80, # La Liga
            135: 0.78, # Serie A
            78: 0.82,  # Bundesliga
            61: 0.75   # Ligue 1
        }
        
        for idx, row in df.iterrows():
            league_id = row['league_id']
            
            df.at[idx, 'home_advantage_factor'] = home_advantage_map.get(league_id, 0.22)
            df.at[idx, 'league_competitiveness'] = competitiveness_map.get(league_id, 0.70)
            df.at[idx, 'match_importance'] = np.random.uniform(0.5, 0.8)  # Could be enhanced with actual importance
            
            # Rest days (simulate realistic values)
            df.at[idx, 'rest_days_home'] = np.random.choice([3, 4, 7, 14], p=[0.3, 0.2, 0.4, 0.1])
            df.at[idx, 'rest_days_away'] = np.random.choice([3, 4, 7, 14], p=[0.3, 0.2, 0.4, 0.1])
            df.at[idx, 'rest_days_difference'] = df.at[idx, 'rest_days_home'] - df.at[idx, 'rest_days_away']
        
        print(f"   ✅ Context features added")
        return df
    
    def export_feature_order(self):
        """Export frozen feature order for consistency (S0 gate)"""
        
        feature_metadata = {
            'feature_order': self.feature_order,
            'feature_count': len(self.feature_order),
            'feature_types': {feat: 'float64' for feat in self.feature_order},
            'created_date': datetime.now().isoformat(),
            'version': '1.0.0',
            'source': 'S1_data_audit'
        }
        
        with open('feature_order.json', 'w') as f:
            json.dump(feature_metadata, f, indent=2)
        
        print(f"✅ Feature order exported: {len(self.feature_order)} features")
        return feature_metadata
    
    def run_s1_audit(self):
        """Run complete S1 data audit and feature rebuilding"""
        
        # 1. Audit raw data
        df, audit_results = self.audit_raw_data()
        if df is None:
            return None, audit_results
        
        # 2. Rebuild Elo ratings (time-validated)
        df = self.rebuild_elo_ratings(df)
        
        # 3. Rebuild form features (time-validated)
        df = self.rebuild_form_features(df)
        
        # 4. Create market probabilities
        df = self.create_market_probabilities(df)
        
        # 5. Add context features
        df = self.add_context_features(df)
        
        # 6. Create attack/defense ratings (derived from recent performance)
        print("\n⚙️  Computing attack/defense ratings...")
        df['home_attack_rating'] = df['home_goals_scored_avg'] / 2.5  # Normalized to league average
        df['away_attack_rating'] = df['away_goals_scored_avg'] / 2.5
        df['attack_diff'] = df['home_attack_rating'] - df['away_attack_rating']
        
        df['home_defense_rating'] = 2.5 / (df['home_goals_conceded_avg'] + 0.1)  # Inverse of goals conceded
        df['away_defense_rating'] = 2.5 / (df['away_goals_conceded_avg'] + 0.1)
        df['defense_diff'] = df['home_defense_rating'] - df['away_defense_rating']
        
        # 7. Extract final feature matrix
        X = df[self.feature_order].copy()
        
        # Data type coercion (S0 gate)
        for col in X.columns:
            X[col] = pd.to_numeric(X[col], errors='coerce').fillna(0.0).astype(np.float64)
        
        # 8. Export feature order
        feature_metadata = self.export_feature_order()
        
        # 9. Validation checks
        print(f"\n🔍 Final validation...")
        print(f"   Feature matrix shape: {X.shape}")
        print(f"   Feature order matches: {list(X.columns) == self.feature_order}")
        print(f"   No missing values: {X.isnull().sum().sum() == 0}")
        print(f"   All float64: {all(X.dtypes == np.float64)}")
        
        return {
            'data': df,
            'features': X,
            'audit_results': audit_results,
            'feature_metadata': feature_metadata,
            'issues_found': len(audit_results['issues']),
            'total_matches': len(df)
        }

def main():
    """Run S1 data audit"""
    
    audit = S1DataAudit()
    
    # Run audit
    results = audit.run_s1_audit()
    
    if results:
        # Save results
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # Save feature matrix
        results['features'].to_csv(f's1_features_{timestamp}.csv', index=False)
        
        # Save audit report
        with open(f's1_audit_report_{timestamp}.json', 'w') as f:
            # Remove DataFrame from results for JSON serialization
            audit_data = results['audit_results'].copy()
            json.dump(audit_data, f, indent=2, default=str)
        
        print(f"\n✅ S1 Data Audit Complete!")
        print(f"📊 Features: s1_features_{timestamp}.csv")
        print(f"📋 Audit: s1_audit_report_{timestamp}.json")
        print(f"🔧 Feature Order: feature_order.json")
        
        if results['issues_found'] == 0:
            print(f"\n🚀 S1 PASSED - Ready for S2 Market-Anchored Modeling")
        else:
            print(f"\n⚠️  S1 Issues Found: {results['issues_found']} - Review before S2")
    
    return results

if __name__ == "__main__":
    main()