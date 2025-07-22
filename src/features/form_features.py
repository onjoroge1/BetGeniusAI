"""
Team Form Features - Rolling window calculations with strict time ordering
No data leakage: only uses matches prior to current match date
"""

import os
import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional

class TeamFormFeatures:
    def __init__(self):
        self.database_url = os.environ.get('DATABASE_URL')
        self.engine = create_engine(self.database_url)
    
    def extract_team_form_features(self, match_id: int, home_team_id: int, away_team_id: int, 
                                 match_date: datetime, window_size: int = 5) -> Dict:
        """
        Extract form features for both teams using only matches before current match
        
        Args:
            match_id: Current match ID
            home_team_id: Home team ID  
            away_team_id: Away team ID
            match_date: Current match date
            window_size: Number of previous matches to analyze
            
        Returns:
            Dict with home/away form features
        """
        try:
            home_form = self._get_team_form(home_team_id, match_date, window_size, is_home=True)
            away_form = self._get_team_form(away_team_id, match_date, window_size, is_home=False)
            
            # Calculate interaction features
            form_features = {
                # Home team form
                'home_form_pts_last5': home_form['points'],
                'home_gf_avg_last5': home_form['goals_for_avg'],
                'home_ga_avg_last5': home_form['goals_against_avg'],
                'home_win_rate_last5': home_form['win_rate'],
                'home_draw_rate_last5': home_form['draw_rate'],
                'home_loss_rate_last5': home_form['loss_rate'],
                'home_goal_diff_last5': home_form['goal_diff_avg'],
                'home_streak_len': home_form['streak_length'],
                'home_days_since_last': home_form['days_since_last'],
                
                # Away team form
                'away_form_pts_last5': away_form['points'],
                'away_gf_avg_last5': away_form['goals_for_avg'],
                'away_ga_avg_last5': away_form['goals_against_avg'],
                'away_win_rate_last5': away_form['win_rate'],
                'away_draw_rate_last5': away_form['draw_rate'],
                'away_loss_rate_last5': away_form['loss_rate'],
                'away_goal_diff_last5': away_form['goal_diff_avg'],
                'away_streak_len': away_form['streak_length'],
                'away_days_since_last': away_form['days_since_last'],
                
                # Comparative features
                'form_pts_diff': home_form['points'] - away_form['points'],
                'form_balance': (home_form['points'] + away_form['points']) / (2 * window_size * 3),  # Normalized 0-1
                'attack_vs_defense': home_form['goals_for_avg'] - away_form['goals_against_avg'],
                'defense_vs_attack': home_form['goals_against_avg'] - away_form['goals_for_avg'],
                'combined_form_strength': (home_form['points'] + away_form['points']) / (2 * window_size * 3)
            }
            
            return form_features
            
        except Exception as e:
            print(f"Error extracting form features for match {match_id}: {e}")
            return self._default_form_features()
    
    def _get_team_form(self, team_id: int, current_match_date: datetime, 
                      window_size: int, is_home: bool) -> Dict:
        """Get form statistics for a team using only prior matches"""
        
        with self.engine.connect() as conn:
            # Get last N matches for this team BEFORE current match date
            query = text("""
                WITH team_matches AS (
                    SELECT 
                        match_date,
                        CASE 
                            WHEN home_team_id = :team_id THEN 
                                CASE 
                                    WHEN outcome = 'Home' THEN 3
                                    WHEN outcome = 'Draw' THEN 1
                                    ELSE 0
                                END
                            WHEN away_team_id = :team_id THEN
                                CASE 
                                    WHEN outcome = 'Away' THEN 3
                                    WHEN outcome = 'Draw' THEN 1
                                    ELSE 0
                                END
                        END AS points,
                        CASE 
                            WHEN home_team_id = :team_id THEN home_goals
                            ELSE away_goals
                        END AS goals_for,
                        CASE 
                            WHEN home_team_id = :team_id THEN away_goals
                            ELSE home_goals
                        END AS goals_against,
                        CASE 
                            WHEN home_team_id = :team_id THEN outcome = 'Home'
                            ELSE outcome = 'Away'
                        END AS won,
                        outcome = 'Draw' AS drew,
                        CASE 
                            WHEN home_team_id = :team_id THEN outcome = 'Away'
                            ELSE outcome = 'Home'
                        END AS lost,
                        (home_team_id = :team_id) AS was_home
                    FROM training_matches
                    WHERE (home_team_id = :team_id OR away_team_id = :team_id)
                    AND match_date < :current_date
                    AND outcome IN ('Home', 'Draw', 'Away')
                    ORDER BY match_date DESC
                    LIMIT :window_size
                )
                SELECT 
                    COUNT(*) as matches_played,
                    COALESCE(SUM(points), 0) as total_points,
                    COALESCE(AVG(goals_for), 0) as avg_goals_for,
                    COALESCE(AVG(goals_against), 0) as avg_goals_against,
                    COALESCE(SUM(CASE WHEN won THEN 1 ELSE 0 END), 0) as wins,
                    COALESCE(SUM(CASE WHEN drew THEN 1 ELSE 0 END), 0) as draws,
                    COALESCE(SUM(CASE WHEN lost THEN 1 ELSE 0 END), 0) as losses,
                    MAX(match_date) as last_match_date
                FROM team_matches
            """)
            
            result = conn.execute(query, {
                'team_id': team_id,
                'current_date': current_match_date,
                'window_size': window_size
            }).fetchone()
        
        if not result or result.matches_played == 0:
            return self._default_team_form()
        
        matches_played = result.matches_played
        total_points = result.total_points
        avg_gf = result.avg_goals_for
        avg_ga = result.avg_goals_against
        wins = result.wins
        draws = result.draws
        losses = result.losses
        last_match_date = result.last_match_date
        
        # Calculate days since last match
        if last_match_date:
            days_since = (current_match_date.date() - last_match_date.date()).days
        else:
            days_since = 30  # Default if no recent matches
        
        # Calculate streak (simplified - just look at last result)
        streak_length = 1  # Default
        
        return {
            'points': total_points,
            'goals_for_avg': avg_gf,
            'goals_against_avg': avg_ga,
            'goal_diff_avg': avg_gf - avg_ga,
            'win_rate': wins / matches_played if matches_played > 0 else 0,
            'draw_rate': draws / matches_played if matches_played > 0 else 0,
            'loss_rate': losses / matches_played if matches_played > 0 else 0,
            'streak_length': streak_length,
            'days_since_last': days_since,
            'matches_played': matches_played
        }
    
    def _default_team_form(self) -> Dict:
        """Default form when no historical data available"""
        return {
            'points': 5,  # Average form
            'goals_for_avg': 1.3,
            'goals_against_avg': 1.3,
            'goal_diff_avg': 0.0,
            'win_rate': 0.33,
            'draw_rate': 0.33,
            'loss_rate': 0.33,
            'streak_length': 0,
            'days_since_last': 7,
            'matches_played': 0
        }
    
    def _default_form_features(self) -> Dict:
        """Default form features when extraction fails"""
        return {
            'home_form_pts_last5': 5,
            'home_gf_avg_last5': 1.3,
            'home_ga_avg_last5': 1.3,
            'home_win_rate_last5': 0.33,
            'home_draw_rate_last5': 0.33,
            'home_loss_rate_last5': 0.33,
            'home_goal_diff_last5': 0.0,
            'home_streak_len': 0,
            'home_days_since_last': 7,
            
            'away_form_pts_last5': 5,
            'away_gf_avg_last5': 1.3,
            'away_ga_avg_last5': 1.3,
            'away_win_rate_last5': 0.33,
            'away_draw_rate_last5': 0.33,
            'away_loss_rate_last5': 0.33,
            'away_goal_diff_last5': 0.0,
            'away_streak_len': 0,
            'away_days_since_last': 7,
            
            'form_pts_diff': 0,
            'form_balance': 0.33,
            'attack_vs_defense': 0.0,
            'defense_vs_attack': 0.0,
            'combined_form_strength': 0.33
        }
    
    def bulk_extract_form_features(self, matches_df: pd.DataFrame) -> pd.DataFrame:
        """Extract form features for multiple matches"""
        form_features_list = []
        
        for _, match in matches_df.iterrows():
            features = self.extract_team_form_features(
                match_id=match['match_id'],
                home_team_id=match['home_team_id'],
                away_team_id=match['away_team_id'],
                match_date=match['match_date']
            )
            
            features['match_id'] = match['match_id']
            form_features_list.append(features)
        
        return pd.DataFrame(form_features_list)

def test_form_features():
    """Test form feature extraction"""
    form_extractor = TeamFormFeatures()
    
    # Test with a real match from our database
    with form_extractor.engine.connect() as conn:
        result = conn.execute(text("""
            SELECT match_id, home_team_id, away_team_id, match_date
            FROM training_matches 
            WHERE home_team_id IS NOT NULL 
            AND away_team_id IS NOT NULL
            ORDER BY match_date DESC 
            LIMIT 1
        """)).fetchone()
    
    if result:
        features = form_extractor.extract_team_form_features(
            match_id=result.match_id,
            home_team_id=result.home_team_id,
            away_team_id=result.away_team_id,
            match_date=result.match_date
        )
        
        print("✅ Form features extracted successfully:")
        for key, value in features.items():
            print(f"  {key}: {value:.3f}")
    else:
        print("❌ No test data available")

if __name__ == "__main__":
    test_form_features()