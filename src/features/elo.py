"""
Elo Rating System - Track team strength over time
Strict time ordering to prevent data leakage
"""

import os
import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text
from datetime import datetime
from typing import Dict, Optional, Tuple

class EloRatingSystem:
    def __init__(self, initial_rating: float = 1500, k_factor: float = 20):
        """
        Initialize Elo rating system
        
        Args:
            initial_rating: Starting Elo rating for new teams
            k_factor: Elo update factor (higher = more volatile)
        """
        self.database_url = os.environ.get('DATABASE_URL')
        self.engine = create_engine(self.database_url)
        self.initial_rating = initial_rating
        self.k_factor = k_factor
        self.team_ratings = {}  # Cache for current ratings
    
    def get_team_elo_pre_match(self, team_id: int, match_date: datetime) -> float:
        """
        Get team's Elo rating just before a specific match
        Only considers matches before the given date
        
        Args:
            team_id: Team identifier
            match_date: Date of the match we're predicting
            
        Returns:
            Elo rating before the match
        """
        try:
            with self.engine.connect() as conn:
                # Get all matches for this team before the current match
                query = text("""
                    SELECT 
                        match_date,
                        home_team_id,
                        away_team_id,
                        home_goals,
                        away_goals,
                        outcome
                    FROM training_matches
                    WHERE (home_team_id = :team_id OR away_team_id = :team_id)
                    AND match_date < :match_date
                    AND outcome IN ('Home', 'Draw', 'Away')
                    AND home_goals IS NOT NULL
                    AND away_goals IS NOT NULL
                    ORDER BY match_date ASC
                """)
                
                matches = conn.execute(query, {
                    'team_id': team_id,
                    'match_date': match_date
                }).fetchall()
            
            # Start with initial rating
            current_elo = self.initial_rating
            
            # Process each match chronologically to build up rating
            for match in matches:
                current_elo = self._update_elo_after_match(
                    team_id=team_id,
                    current_elo=current_elo,
                    match=match
                )
            
            return current_elo
            
        except Exception as e:
            print(f"Error getting Elo for team {team_id}: {e}")
            return self.initial_rating
    
    def _update_elo_after_match(self, team_id: int, current_elo: float, match) -> float:
        """Update Elo rating after a match result"""
        
        # Determine if team was home or away
        is_home = (match.home_team_id == team_id)
        opponent_id = match.away_team_id if is_home else match.home_team_id
        
        # Get opponent's Elo (we'd need to calculate this too, but for now use initial)
        opponent_elo = self.initial_rating  # Simplified for now
        
        # Calculate expected result (0-1 scale)
        expected_score = self._calculate_expected_score(current_elo, opponent_elo)
        
        # Determine actual result
        actual_score = self._get_actual_score(team_id, match)
        
        # Calculate goal difference multiplier
        goal_diff_multiplier = self._calculate_goal_diff_multiplier(match)
        
        # Update Elo
        elo_change = self.k_factor * goal_diff_multiplier * (actual_score - expected_score)
        new_elo = current_elo + elo_change
        
        return new_elo
    
    def _calculate_expected_score(self, team_elo: float, opponent_elo: float) -> float:
        """Calculate expected match result using Elo formula"""
        rating_diff = opponent_elo - team_elo
        expected = 1 / (1 + 10**(rating_diff / 400))
        return expected
    
    def _get_actual_score(self, team_id: int, match) -> float:
        """Get actual match result (1=win, 0.5=draw, 0=loss)"""
        if match.outcome == 'Draw':
            return 0.5
        elif (match.home_team_id == team_id and match.outcome == 'Home') or \
             (match.away_team_id == team_id and match.outcome == 'Away'):
            return 1.0
        else:
            return 0.0
    
    def _calculate_goal_diff_multiplier(self, match) -> float:
        """Calculate multiplier based on goal difference (bigger wins = bigger Elo changes)"""
        goal_diff = abs(match.home_goals - match.away_goals)
        
        if goal_diff <= 1:
            return 1.0
        elif goal_diff == 2:
            return 1.2
        elif goal_diff == 3:
            return 1.4
        else:
            return 1.6
    
    def extract_elo_features(self, match_id: int, home_team_id: int, away_team_id: int, 
                           match_date: datetime) -> Dict:
        """
        Extract Elo-based features for a match
        
        Args:
            match_id: Match identifier
            home_team_id: Home team ID
            away_team_id: Away team ID
            match_date: Match date
            
        Returns:
            Dict with Elo features
        """
        try:
            # Get pre-match Elo ratings
            home_elo = self.get_team_elo_pre_match(home_team_id, match_date)
            away_elo = self.get_team_elo_pre_match(away_team_id, match_date)
            
            # Calculate derived features
            elo_diff = home_elo - away_elo
            elo_avg = (home_elo + away_elo) / 2
            
            # Expected probabilities based on Elo
            home_expected = self._calculate_expected_score(home_elo, away_elo)
            away_expected = self._calculate_expected_score(away_elo, home_elo)
            
            # Strength categories
            home_strength_category = self._get_strength_category(home_elo)
            away_strength_category = self._get_strength_category(away_elo)
            
            elo_features = {
                'home_elo_pre': home_elo,
                'away_elo_pre': away_elo,
                'elo_diff': elo_diff,
                'elo_avg': elo_avg,
                'elo_diff_abs': abs(elo_diff),
                'home_elo_expected': home_expected,
                'away_elo_expected': away_expected,
                'elo_match_quality': 1 - (abs(elo_diff) / 800),  # Closer ratings = higher quality
                'home_elo_strength': home_strength_category,
                'away_elo_strength': away_strength_category,
                'strength_mismatch': abs(home_strength_category - away_strength_category)
            }
            
            return elo_features
            
        except Exception as e:
            print(f"Error extracting Elo features for match {match_id}: {e}")
            return self._default_elo_features()
    
    def _get_strength_category(self, elo: float) -> int:
        """Categorize team strength based on Elo (0=weak, 3=strong)"""
        if elo < 1400:
            return 0  # Weak
        elif elo < 1500:
            return 1  # Below average
        elif elo < 1600:
            return 2  # Above average
        else:
            return 3  # Strong
    
    def _default_elo_features(self) -> Dict:
        """Default Elo features when calculation fails"""
        return {
            'home_elo_pre': self.initial_rating,
            'away_elo_pre': self.initial_rating,
            'elo_diff': 0,
            'elo_avg': self.initial_rating,
            'elo_diff_abs': 0,
            'home_elo_expected': 0.5,
            'away_elo_expected': 0.5,
            'elo_match_quality': 1.0,
            'home_elo_strength': 1,
            'away_elo_strength': 1,
            'strength_mismatch': 0
        }
    
    def bulk_calculate_elo_ratings(self) -> Dict[int, float]:
        """
        Calculate Elo ratings for all teams across all matches
        Returns final ratings for each team
        """
        print("📊 Calculating Elo ratings for all teams...")
        
        team_ratings = {}
        
        with self.engine.connect() as conn:
            # Get all matches in chronological order
            query = text("""
                SELECT 
                    match_id,
                    match_date,
                    home_team_id,
                    away_team_id,
                    home_goals,
                    away_goals,
                    outcome
                FROM training_matches
                WHERE outcome IN ('Home', 'Draw', 'Away')
                AND home_goals IS NOT NULL
                AND away_goals IS NOT NULL
                AND home_team_id IS NOT NULL
                AND away_team_id IS NOT NULL
                ORDER BY match_date ASC
            """)
            
            matches = conn.execute(query).fetchall()
        
        processed_matches = 0
        
        for match in matches:
            home_id = match.home_team_id
            away_id = match.away_team_id
            
            # Initialize ratings if not seen before
            if home_id not in team_ratings:
                team_ratings[home_id] = self.initial_rating
            if away_id not in team_ratings:
                team_ratings[away_id] = self.initial_rating
            
            # Get current ratings
            home_elo = team_ratings[home_id]
            away_elo = team_ratings[away_id]
            
            # Calculate new ratings after this match
            home_new_elo = self._update_elo_after_match_detailed(
                home_elo, away_elo, match, is_home=True
            )
            away_new_elo = self._update_elo_after_match_detailed(
                away_elo, home_elo, match, is_home=False
            )
            
            # Update ratings
            team_ratings[home_id] = home_new_elo
            team_ratings[away_id] = away_new_elo
            
            processed_matches += 1
        
        print(f"✅ Processed {processed_matches} matches")
        print(f"📈 Calculated ratings for {len(team_ratings)} teams")
        
        return team_ratings
    
    def _update_elo_after_match_detailed(self, team_elo: float, opponent_elo: float, 
                                       match, is_home: bool) -> float:
        """Detailed Elo update with proper opponent rating"""
        
        # Calculate expected result
        expected_score = self._calculate_expected_score(team_elo, opponent_elo)
        
        # Get actual result
        if match.outcome == 'Draw':
            actual_score = 0.5
        elif (is_home and match.outcome == 'Home') or (not is_home and match.outcome == 'Away'):
            actual_score = 1.0
        else:
            actual_score = 0.0
        
        # Goal difference multiplier
        goal_diff_multiplier = self._calculate_goal_diff_multiplier(match)
        
        # Update Elo
        elo_change = self.k_factor * goal_diff_multiplier * (actual_score - expected_score)
        new_elo = team_elo + elo_change
        
        return new_elo

def test_elo_system():
    """Test Elo rating system"""
    elo_system = EloRatingSystem()
    
    # Test with a real match
    with elo_system.engine.connect() as conn:
        result = conn.execute(text("""
            SELECT match_id, home_team_id, away_team_id, match_date
            FROM training_matches 
            WHERE home_team_id IS NOT NULL 
            AND away_team_id IS NOT NULL
            ORDER BY match_date DESC 
            LIMIT 1
        """)).fetchone()
    
    if result:
        features = elo_system.extract_elo_features(
            match_id=result.match_id,
            home_team_id=result.home_team_id,
            away_team_id=result.away_team_id,
            match_date=result.match_date
        )
        
        print("✅ Elo features extracted successfully:")
        for key, value in features.items():
            print(f"  {key}: {value:.3f}")
    else:
        print("❌ No test data available")

if __name__ == "__main__":
    test_elo_system()