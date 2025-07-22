"""
Head-to-Head Features - Historical matchup analysis between specific teams
Only uses matches prior to current match to prevent data leakage
"""

import os
import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text
from datetime import datetime, timedelta
from typing import Dict, Optional

class HeadToHeadFeatures:
    def __init__(self):
        self.database_url = os.environ.get('DATABASE_URL')
        self.engine = create_engine(self.database_url)
    
    def extract_h2h_features(self, home_team_id: int, away_team_id: int, 
                           match_date: datetime, window_matches: int = 10) -> Dict:
        """
        Extract head-to-head features between two specific teams
        
        Args:
            home_team_id: Home team ID
            away_team_id: Away team ID  
            match_date: Current match date
            window_matches: Number of recent H2H matches to analyze
            
        Returns:
            Dict with H2H features
        """
        try:
            h2h_stats = self._get_h2h_history(home_team_id, away_team_id, match_date, window_matches)
            
            h2h_features = {
                # Basic H2H record
                'h2h_total_matches': h2h_stats['total_matches'],
                'h2h_home_wins': h2h_stats['home_wins'],
                'h2h_away_wins': h2h_stats['away_wins'],
                'h2h_draws': h2h_stats['draws'],
                
                # Win rates
                'h2h_home_win_rate': h2h_stats['home_win_rate'],
                'h2h_away_win_rate': h2h_stats['away_win_rate'],
                'h2h_draw_rate': h2h_stats['draw_rate'],
                
                # Goal statistics
                'h2h_avg_home_goals': h2h_stats['avg_home_goals'],
                'h2h_avg_away_goals': h2h_stats['avg_away_goals'],
                'h2h_avg_total_goals': h2h_stats['avg_total_goals'],
                'h2h_goal_difference': h2h_stats['avg_home_goals'] - h2h_stats['avg_away_goals'],
                
                # Dominance indicators
                'h2h_home_dominance': h2h_stats['home_win_rate'] - h2h_stats['away_win_rate'],
                'h2h_competitive_ratio': min(h2h_stats['home_win_rate'], h2h_stats['away_win_rate']) / max(h2h_stats['home_win_rate'], h2h_stats['away_win_rate']) if max(h2h_stats['home_win_rate'], h2h_stats['away_win_rate']) > 0 else 1.0,
                
                # Recent form (last 3 H2H)
                'h2h_recent_home_wins': h2h_stats['recent_home_wins'],
                'h2h_recent_away_wins': h2h_stats['recent_away_wins'],
                'h2h_recent_draws': h2h_stats['recent_draws'],
                
                # Time since last meeting
                'h2h_days_since_last': h2h_stats['days_since_last'],
                'h2h_has_recent_history': int(h2h_stats['days_since_last'] <= 365),
                
                # Pattern indicators
                'h2h_high_scoring': int(h2h_stats['avg_total_goals'] > 2.5),
                'h2h_low_scoring': int(h2h_stats['avg_total_goals'] < 2.0),
                'h2h_draw_tendency': int(h2h_stats['draw_rate'] > 0.3)
            }
            
            return h2h_features
            
        except Exception as e:
            print(f"Error extracting H2H features: {e}")
            return self._default_h2h_features()
    
    def _get_h2h_history(self, home_team_id: int, away_team_id: int, 
                        current_date: datetime, window_matches: int) -> Dict:
        """Get head-to-head history between two teams"""
        
        with self.engine.connect() as conn:
            # Get all previous matches between these teams (either home/away combination)
            query = text("""
                SELECT 
                    match_date,
                    home_team_id,
                    away_team_id,
                    home_goals,
                    away_goals,
                    outcome
                FROM training_matches
                WHERE ((home_team_id = :home_id AND away_team_id = :away_id) OR
                       (home_team_id = :away_id AND away_team_id = :home_id))
                AND match_date < :current_date
                AND outcome IN ('Home', 'Draw', 'Away')
                AND home_goals IS NOT NULL 
                AND away_goals IS NOT NULL
                ORDER BY match_date DESC
                LIMIT :window_matches
            """)
            
            matches = conn.execute(query, {
                'home_id': home_team_id,
                'away_id': away_team_id,
                'current_date': current_date,
                'window_matches': window_matches
            }).fetchall()
        
        if not matches:
            return self._default_h2h_stats()
        
        total_matches = len(matches)
        home_wins = 0
        away_wins = 0
        draws = 0
        total_home_goals = 0
        total_away_goals = 0
        
        # Recent matches (last 3)
        recent_matches = matches[:3]
        recent_home_wins = 0
        recent_away_wins = 0
        recent_draws = 0
        
        for i, match in enumerate(matches):
            # Determine perspective (current home team's performance in H2H)
            if match.home_team_id == home_team_id:
                # Current home team was home in this H2H match
                if match.outcome == 'Home':
                    home_wins += 1
                    if i < 3:
                        recent_home_wins += 1
                elif match.outcome == 'Away':
                    away_wins += 1
                    if i < 3:
                        recent_away_wins += 1
                else:  # Draw
                    draws += 1
                    if i < 3:
                        recent_draws += 1
                
                total_home_goals += match.home_goals
                total_away_goals += match.away_goals
                
            else:
                # Current home team was away in this H2H match
                if match.outcome == 'Away':
                    home_wins += 1
                    if i < 3:
                        recent_home_wins += 1
                elif match.outcome == 'Home':
                    away_wins += 1
                    if i < 3:
                        recent_away_wins += 1
                else:  # Draw
                    draws += 1
                    if i < 3:
                        recent_draws += 1
                
                total_home_goals += match.away_goals
                total_away_goals += match.home_goals
        
        # Calculate statistics
        avg_home_goals = total_home_goals / total_matches
        avg_away_goals = total_away_goals / total_matches
        avg_total_goals = (total_home_goals + total_away_goals) / total_matches
        
        home_win_rate = home_wins / total_matches
        away_win_rate = away_wins / total_matches
        draw_rate = draws / total_matches
        
        # Days since last meeting
        last_match_date = matches[0].match_date
        days_since_last = (current_date.date() - last_match_date.date()).days
        
        return {
            'total_matches': total_matches,
            'home_wins': home_wins,
            'away_wins': away_wins,
            'draws': draws,
            'home_win_rate': home_win_rate,
            'away_win_rate': away_win_rate,
            'draw_rate': draw_rate,
            'avg_home_goals': avg_home_goals,
            'avg_away_goals': avg_away_goals,
            'avg_total_goals': avg_total_goals,
            'recent_home_wins': recent_home_wins,
            'recent_away_wins': recent_away_wins,
            'recent_draws': recent_draws,
            'days_since_last': days_since_last
        }
    
    def _default_h2h_stats(self) -> Dict:
        """Default H2H stats when no historical data available"""
        return {
            'total_matches': 0,
            'home_wins': 0,
            'away_wins': 0,
            'draws': 0,
            'home_win_rate': 0.45,  # Slight home advantage default
            'away_win_rate': 0.35,
            'draw_rate': 0.20,
            'avg_home_goals': 1.3,
            'avg_away_goals': 1.1,
            'avg_total_goals': 2.4,
            'recent_home_wins': 0,
            'recent_away_wins': 0,
            'recent_draws': 0,
            'days_since_last': 999  # No recent history
        }
    
    def _default_h2h_features(self) -> Dict:
        """Default H2H features when extraction fails"""
        return {
            'h2h_total_matches': 0,
            'h2h_home_wins': 0,
            'h2h_away_wins': 0,
            'h2h_draws': 0,
            'h2h_home_win_rate': 0.45,
            'h2h_away_win_rate': 0.35,
            'h2h_draw_rate': 0.20,
            'h2h_avg_home_goals': 1.3,
            'h2h_avg_away_goals': 1.1,
            'h2h_avg_total_goals': 2.4,
            'h2h_goal_difference': 0.2,
            'h2h_home_dominance': 0.1,
            'h2h_competitive_ratio': 0.78,
            'h2h_recent_home_wins': 0,
            'h2h_recent_away_wins': 0,
            'h2h_recent_draws': 0,
            'h2h_days_since_last': 999,
            'h2h_has_recent_history': 0,
            'h2h_high_scoring': 0,
            'h2h_low_scoring': 0,
            'h2h_draw_tendency': 0
        }

def test_h2h_features():
    """Test head-to-head feature extraction"""
    h2h_extractor = HeadToHeadFeatures()
    
    with h2h_extractor.engine.connect() as conn:
        # Find a match with team IDs
        result = conn.execute(text("""
            SELECT home_team_id, away_team_id, match_date
            FROM training_matches 
            WHERE home_team_id IS NOT NULL 
            AND away_team_id IS NOT NULL
            ORDER BY match_date DESC 
            LIMIT 1
        """)).fetchone()
    
    if result:
        features = h2h_extractor.extract_h2h_features(
            home_team_id=result.home_team_id,
            away_team_id=result.away_team_id,
            match_date=result.match_date
        )
        
        print("✅ H2H features extracted successfully:")
        for key, value in features.items():
            print(f"  {key}: {value}")
    else:
        print("❌ No test data available")

if __name__ == "__main__":
    test_h2h_features()