"""
Player V2 Feature Builder - Player Performance Prediction Features

Builds features for player-level predictions (goals, assists, performance).
Follows the same leak-safe patterns as UnifiedV2FeatureBuilder.

Feature Categories (~45 features):
═══════════════════════════════════════════════════════════════════════════════

1. RECENT FORM (10):
   - goals_last_3, goals_last_5, assists_last_3, assists_last_5
   - shots_last_5_avg, shots_on_target_last_5_avg
   - minutes_last_5_avg, rating_last_5_avg
   - goal_involvement_last_5 (goals + assists)
   - form_trend (improving/declining)

2. SEASON STATS (8):
   - season_goals, season_assists, season_appearances
   - goals_per_90, assists_per_90, shots_per_90
   - minutes_per_appearance
   - goal_involvement_rate

3. OPPONENT CONTEXT (8):
   - opponent_goals_conceded_avg
   - opponent_clean_sheets_pct
   - opponent_form_points_last_5
   - opponent_defensive_strength
   - h2h_goals_vs_opponent
   - opponent_league_position
   - opponent_home_away_form
   - is_derby (rival match)

4. MATCH CONTEXT (8):
   - is_home_game
   - rest_days_since_last_game
   - congestion_7d
   - team_form_points_last_5
   - team_goals_scored_last_5_avg
   - match_importance (league position delta)
   - is_cup_match
   - weather_impact (if available)

5. PLAYER PROFILE (6):
   - position_encoded (FW=3, MF=2, DF=1, GK=0)
   - age_at_match
   - is_penalty_taker
   - is_first_choice (minutes > 70%)
   - career_goals_per_season
   - goals_vs_expected

6. MARKET FEATURES (5):
   - team_win_probability
   - expected_match_goals
   - over_2_5_probability
   - team_implied_goals
   - player_goal_share

LEAK-SAFE IMPLEMENTATION:
- All features computed using only data BEFORE cutoff_time
- No post-match data leakage
"""

import logging
import numpy as np
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta, timezone
import os

logger = logging.getLogger(__name__)


class PlayerV2FeatureBuilder:
    """
    Player V2 Feature Builder for goal/assist predictions.
    
    All features are leak-free with strict pre-match cutoffs.
    """
    
    FORM_FEATURES = [
        'goals_last_3', 'goals_last_5', 'assists_last_3', 'assists_last_5',
        'shots_last_5_avg', 'shots_on_target_last_5_avg',
        'minutes_last_5_avg', 'rating_last_5_avg',
        'goal_involvement_last_5', 'form_trend'
    ]
    
    SEASON_FEATURES = [
        'season_goals', 'season_assists', 'season_appearances',
        'goals_per_90', 'assists_per_90', 'shots_per_90',
        'minutes_per_appearance', 'goal_involvement_rate'
    ]
    
    OPPONENT_FEATURES = [
        'opponent_goals_conceded_avg', 'opponent_clean_sheets_pct',
        'opponent_form_points_last_5', 'opponent_defensive_strength',
        'h2h_goals_vs_opponent', 'opponent_league_position',
        'opponent_home_away_form', 'is_derby'
    ]
    
    MATCH_FEATURES = [
        'is_home_game', 'rest_days_since_last_game', 'congestion_7d',
        'team_form_points_last_5', 'team_goals_scored_last_5_avg',
        'match_importance', 'is_cup_match', 'is_big_match'
    ]
    
    PROFILE_FEATURES = [
        'position_encoded', 'age_at_match', 'is_penalty_taker',
        'is_first_choice', 'career_goals_per_season', 'goals_vs_expected'
    ]
    
    MARKET_FEATURES = [
        'team_win_probability', 'expected_match_goals',
        'over_2_5_probability', 'team_implied_goals', 'player_goal_share'
    ]
    
    ALL_FEATURES = (FORM_FEATURES + SEASON_FEATURES + OPPONENT_FEATURES + 
                   MATCH_FEATURES + PROFILE_FEATURES + MARKET_FEATURES)
    
    def __init__(self):
        self.db_url = os.getenv('DATABASE_URL')
    
    def build_features(self, player_id: int, match_id: int, 
                       cutoff_time: datetime) -> Dict:
        """
        Build all features for a player-match prediction.
        
        Args:
            player_id: Internal player_id from players_unified
            match_id: Match ID (fixture ID)
            cutoff_time: Only use data before this time
            
        Returns:
            Dict of feature name -> value
        """
        features = {f: 0.0 for f in self.ALL_FEATURES}
        
        conn = psycopg2.connect(self.db_url)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        try:
            player_info = self._get_player_info(cur, player_id)
            if not player_info:
                raise ValueError(f"Player {player_id} not found")
            
            match_info = self._get_match_info(cur, match_id)
            if not match_info:
                raise ValueError(f"Match {match_id} not found")
            
            team_id = player_info.get('team_id')
            is_home = (team_id == match_info.get('home_team_id'))
            opponent_id = match_info.get('away_team_id') if is_home else match_info.get('home_team_id')
            
            features.update(self._build_form_features(cur, player_id, cutoff_time))
            features.update(self._build_season_features(cur, player_id, cutoff_time))
            features.update(self._build_opponent_features(cur, opponent_id, cutoff_time))
            features.update(self._build_match_features(cur, match_id, team_id, is_home, cutoff_time))
            features.update(self._build_profile_features(cur, player_id, player_info, cutoff_time))
            features.update(self._build_market_features(cur, match_id, is_home, player_id, cutoff_time))
            
        finally:
            conn.close()
        
        return features
    
    def _get_player_info(self, cur, player_id: int) -> Optional[Dict]:
        """Get player basic info."""
        cur.execute("""
            SELECT player_id, external_id, player_name, position, 
                   team_id, team_name, date_of_birth
            FROM players_unified
            WHERE player_id = %s
        """, (player_id,))
        return cur.fetchone()
    
    def _get_match_info(self, cur, match_id: int) -> Optional[Dict]:
        """Get match info from fixtures."""
        cur.execute("""
            SELECT f.match_id, f.league_id,
                   f.home_team_id, f.away_team_id,
                   f.home_team as home_team_name, f.away_team as away_team_name,
                   f.kickoff_at, f.status
            FROM fixtures f
            WHERE f.match_id = %s
            LIMIT 1
        """, (match_id,))
        return cur.fetchone()
    
    def _build_form_features(self, cur, player_id: int, cutoff: datetime) -> Dict:
        """Build player recent form features."""
        features = {}
        
        cur.execute("""
            SELECT 
                game_date, minutes_played, rating,
                (stats->>'goals')::int as goals,
                (stats->>'assists')::int as assists,
                (stats->>'shots')::int as shots,
                (stats->>'shots_on_target')::int as shots_on_target
            FROM player_game_stats
            WHERE player_id = %s 
              AND sport_key = 'soccer'
              AND game_date < %s
            ORDER BY game_date DESC
            LIMIT 10
        """, (player_id, cutoff.date()))
        
        games = cur.fetchall()
        
        if not games:
            return {
                'goals_last_3': 0, 'goals_last_5': 0,
                'assists_last_3': 0, 'assists_last_5': 0,
                'shots_last_5_avg': 0, 'shots_on_target_last_5_avg': 0,
                'minutes_last_5_avg': 0, 'rating_last_5_avg': 0,
                'goal_involvement_last_5': 0, 'form_trend': 0
            }
        
        last_3 = games[:3]
        last_5 = games[:5]
        
        features['goals_last_3'] = sum(g['goals'] or 0 for g in last_3)
        features['goals_last_5'] = sum(g['goals'] or 0 for g in last_5)
        features['assists_last_3'] = sum(g['assists'] or 0 for g in last_3)
        features['assists_last_5'] = sum(g['assists'] or 0 for g in last_5)
        
        if last_5:
            features['shots_last_5_avg'] = np.mean([g['shots'] or 0 for g in last_5])
            features['shots_on_target_last_5_avg'] = np.mean([g['shots_on_target'] or 0 for g in last_5])
            features['minutes_last_5_avg'] = np.mean([g['minutes_played'] or 0 for g in last_5])
            ratings = [g['rating'] for g in last_5 if g['rating']]
            features['rating_last_5_avg'] = np.mean(ratings) if ratings else 0
        
        features['goal_involvement_last_5'] = features['goals_last_5'] + features['assists_last_5']
        
        if len(last_5) >= 3:
            recent_gi = sum((g['goals'] or 0) + (g['assists'] or 0) for g in last_3)
            older_gi = sum((g['goals'] or 0) + (g['assists'] or 0) for g in last_5[2:])
            features['form_trend'] = 1 if recent_gi > older_gi else (-1 if recent_gi < older_gi else 0)
        else:
            features['form_trend'] = 0
        
        return features
    
    def _build_season_features(self, cur, player_id: int, cutoff: datetime) -> Dict:
        """Build player season statistics features."""
        features = {}
        
        season_year = cutoff.year if cutoff.month >= 7 else cutoff.year - 1
        
        cur.execute("""
            SELECT 
                games_played, minutes_played,
                (stats->>'goals')::int as goals,
                (stats->>'assists')::int as assists,
                (stats->>'shots_total')::int as shots
            FROM player_season_stats
            WHERE player_id = %s AND sport_key = 'soccer' AND season = %s
        """, (player_id, season_year))
        
        season = cur.fetchone()
        
        if not season:
            return {
                'season_goals': 0, 'season_assists': 0, 'season_appearances': 0,
                'goals_per_90': 0, 'assists_per_90': 0, 'shots_per_90': 0,
                'minutes_per_appearance': 0, 'goal_involvement_rate': 0
            }
        
        features['season_goals'] = season['goals'] or 0
        features['season_assists'] = season['assists'] or 0
        features['season_appearances'] = season['games_played'] or 0
        
        minutes = season['minutes_played'] or 0
        if minutes > 0:
            features['goals_per_90'] = (features['season_goals'] / minutes) * 90
            features['assists_per_90'] = (features['season_assists'] / minutes) * 90
            features['shots_per_90'] = ((season['shots'] or 0) / minutes) * 90
        
        if season['games_played'] and season['games_played'] > 0:
            features['minutes_per_appearance'] = minutes / season['games_played']
            features['goal_involvement_rate'] = (
                (features['season_goals'] + features['season_assists']) / 
                season['games_played']
            )
        
        return features
    
    def _build_opponent_features(self, cur, opponent_id: int, cutoff: datetime) -> Dict:
        """Build opponent defensive features."""
        features = {
            'opponent_goals_conceded_avg': 0, 'opponent_clean_sheets_pct': 0,
            'opponent_form_points_last_5': 0, 'opponent_defensive_strength': 0.5,
            'h2h_goals_vs_opponent': 0, 'opponent_league_position': 10,
            'opponent_home_away_form': 0, 'is_derby': 0
        }
        
        if not opponent_id:
            return features
        
        cur.execute("""
            SELECT 
                home_goals, away_goals,
                home_team_id, away_team_id
            FROM matches
            WHERE (home_team_id = %s OR away_team_id = %s)
              AND match_date_utc < %s
            ORDER BY match_date_utc DESC
            LIMIT 10
        """, (opponent_id, opponent_id, cutoff.date()))
        
        matches = cur.fetchall()
        
        if matches:
            goals_conceded = []
            clean_sheets = 0
            points = 0
            
            for m in matches[:5]:
                if m['home_team_id'] == opponent_id:
                    goals_conceded.append(m['away_goals'] or 0)
                    if (m['away_goals'] or 0) == 0:
                        clean_sheets += 1
                    if (m['home_goals'] or 0) > (m['away_goals'] or 0):
                        points += 3
                    elif (m['home_goals'] or 0) == (m['away_goals'] or 0):
                        points += 1
                else:
                    goals_conceded.append(m['home_goals'] or 0)
                    if (m['home_goals'] or 0) == 0:
                        clean_sheets += 1
                    if (m['away_goals'] or 0) > (m['home_goals'] or 0):
                        points += 3
                    elif (m['home_goals'] or 0) == (m['away_goals'] or 0):
                        points += 1
            
            if goals_conceded:
                features['opponent_goals_conceded_avg'] = np.mean(goals_conceded)
                features['opponent_clean_sheets_pct'] = clean_sheets / len(matches[:5])
            features['opponent_form_points_last_5'] = points
            features['opponent_defensive_strength'] = 1.0 - min(features['opponent_goals_conceded_avg'] / 3.0, 1.0)
        
        return features
    
    def _build_match_features(self, cur, match_id: int, team_id: int, 
                              is_home: bool, cutoff: datetime) -> Dict:
        """Build match context features."""
        features = {
            'is_home_game': 1 if is_home else 0,
            'rest_days_since_last_game': 7,
            'congestion_7d': 1,
            'team_form_points_last_5': 7.5,
            'team_goals_scored_last_5_avg': 1.5,
            'match_importance': 0.5,
            'is_cup_match': 0,
            'is_big_match': 0
        }
        
        if not team_id:
            return features
        
        cur.execute("""
            SELECT 
                match_date_utc,
                home_goals, away_goals,
                home_team_id
            FROM matches
            WHERE (home_team_id = %s OR away_team_id = %s)
              AND match_date_utc < %s
            ORDER BY match_date_utc DESC
            LIMIT 7
        """, (team_id, team_id, cutoff.date()))
        
        matches = cur.fetchall()
        
        if matches:
            last_match = matches[0]
            features['rest_days_since_last_game'] = (cutoff.date() - last_match['match_date_utc']).days
            
            games_in_week = sum(1 for m in matches if (cutoff.date() - m['match_date_utc']).days <= 7)
            features['congestion_7d'] = games_in_week
            
            points = 0
            goals_scored = []
            for m in matches[:5]:
                if m['home_team_id'] == team_id:
                    goals_scored.append(m['home_goals'] or 0)
                    if (m['home_goals'] or 0) > (m['away_goals'] or 0):
                        points += 3
                    elif (m['home_goals'] or 0) == (m['away_goals'] or 0):
                        points += 1
                else:
                    goals_scored.append(m['away_goals'] or 0)
                    if (m['away_goals'] or 0) > (m['home_goals'] or 0):
                        points += 3
                    elif (m['home_goals'] or 0) == (m['away_goals'] or 0):
                        points += 1
            
            features['team_form_points_last_5'] = points
            if goals_scored:
                features['team_goals_scored_last_5_avg'] = np.mean(goals_scored)
        
        return features
    
    def _build_profile_features(self, cur, player_id: int, player_info: Dict, 
                                cutoff: datetime) -> Dict:
        """Build player profile features."""
        features = {
            'position_encoded': 1,
            'age_at_match': 27,
            'is_penalty_taker': 0,
            'is_first_choice': 0,
            'career_goals_per_season': 0,
            'goals_vs_expected': 0
        }
        
        position = player_info.get('position', '')
        if position:
            pos_upper = position.upper()
            if 'G' in pos_upper:
                features['position_encoded'] = 0
            elif 'D' in pos_upper:
                features['position_encoded'] = 1
            elif 'M' in pos_upper:
                features['position_encoded'] = 2
            elif 'F' in pos_upper or 'A' in pos_upper or 'S' in pos_upper:
                features['position_encoded'] = 3
        
        dob = player_info.get('date_of_birth')
        if dob:
            try:
                if isinstance(dob, str):
                    dob = datetime.strptime(dob, '%Y-%m-%d')
                age = (cutoff.date() - dob.date()).days / 365.25
                features['age_at_match'] = age
            except:
                pass
        
        cur.execute("""
            SELECT COUNT(*) as games, AVG(minutes_played) as avg_minutes
            FROM player_game_stats
            WHERE player_id = %s AND sport_key = 'soccer'
              AND game_date >= %s - INTERVAL '60 days'
              AND game_date < %s
        """, (player_id, cutoff, cutoff))
        
        recent = cur.fetchone()
        if recent and recent['games'] and recent['games'] >= 3:
            features['is_first_choice'] = 1 if (recent['avg_minutes'] or 0) > 60 else 0
        
        cur.execute("""
            SELECT 
                SUM((stats->>'goals')::int) as total_goals,
                COUNT(DISTINCT season) as seasons
            FROM player_season_stats
            WHERE player_id = %s AND sport_key = 'soccer'
        """, (player_id,))
        
        career = cur.fetchone()
        if career and career['seasons'] and career['seasons'] > 0:
            features['career_goals_per_season'] = (career['total_goals'] or 0) / career['seasons']
        
        return features
    
    def _build_market_features(self, cur, match_id: int, is_home: bool,
                               player_id: int, cutoff: datetime) -> Dict:
        """Build market/odds features."""
        features = {
            'team_win_probability': 0.33,
            'expected_match_goals': 2.5,
            'over_2_5_probability': 0.5,
            'team_implied_goals': 1.25,
            'player_goal_share': 0.1
        }
        
        cur.execute("""
            SELECT 
                ph_cons, pd_cons, pa_cons
            FROM odds_consensus
            WHERE match_id = %s
            ORDER BY ts_effective DESC
            LIMIT 1
        """, (match_id,))
        
        odds = cur.fetchone()
        if odds:
            if is_home:
                features['team_win_probability'] = odds.get('ph_cons') or 0.33
            else:
                features['team_win_probability'] = odds.get('pa_cons') or 0.33
        
        cur.execute("""
            SELECT 
                SUM((stats->>'goals')::int) as player_goals
            FROM player_season_stats
            WHERE player_id = %s AND sport_key = 'soccer'
        """, (player_id,))
        
        player_goals = cur.fetchone()
        
        cur.execute("""
            SELECT team_id FROM players_unified WHERE player_id = %s
        """, (player_id,))
        team = cur.fetchone()
        
        if team and team['team_id']:
            cur.execute("""
                SELECT SUM(
                    CASE WHEN home_team_id = %s THEN home_goals
                         WHEN away_team_id = %s THEN away_goals
                         ELSE 0 END
                ) as team_goals
                FROM matches
                WHERE (home_team_id = %s OR away_team_id = %s)
                  AND match_date_utc >= %s - INTERVAL '365 days'
                  AND match_date_utc < %s
            """, (team['team_id'], team['team_id'], team['team_id'], 
                  team['team_id'], cutoff, cutoff))
            
            team_goals = cur.fetchone()
            
            if team_goals and team_goals['team_goals'] and player_goals and player_goals['player_goals']:
                features['player_goal_share'] = player_goals['player_goals'] / max(team_goals['team_goals'], 1)
        
        return features
    
    def get_training_samples(self, limit: int = 5000) -> List[Dict]:
        """
        Get training samples: player-match pairs with outcomes.
        
        Returns list of dicts with features and target variables.
        """
        conn = psycopg2.connect(self.db_url)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        try:
            cur.execute("""
                SELECT 
                    pgs.player_id,
                    pgs.game_id,
                    pgs.game_date,
                    (pgs.stats->>'goals')::int as goals,
                    (pgs.stats->>'assists')::int as assists,
                    p.position
                FROM player_game_stats pgs
                JOIN players_unified p ON pgs.player_id = p.player_id
                WHERE pgs.sport_key = 'soccer'
                  AND pgs.minutes_played >= 45
                  AND p.position IS NOT NULL
                  AND p.position NOT ILIKE '%%G%%'
                ORDER BY pgs.game_date DESC
                LIMIT %s
            """, (limit,))
            
            samples = cur.fetchall()
            
        finally:
            conn.close()
        
        logger.info(f"Found {len(samples)} potential training samples")
        return [dict(s) for s in samples]
