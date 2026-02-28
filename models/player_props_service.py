"""
BetGenius AI - Player Props Service
Exposes Player V2 predictions as bettable market probabilities
"""

import os
import pickle
import logging
import numpy as np
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone, timedelta
from pathlib import Path
from sqlalchemy import create_engine, text

logger = logging.getLogger(__name__)

MODEL_DIR = Path("artifacts/models/player_v2")


class PlayerPropsService:
    """Service for player prop predictions integrated with parlay system"""
    
    def __init__(self):
        self.database_url = os.environ.get('DATABASE_URL')
        if not self.database_url:
            raise ValueError("DATABASE_URL environment variable required")
        
        self.engine = create_engine(
            self.database_url,
            pool_pre_ping=True,
            pool_recycle=300
        )
        
        self.goal_involvement_model = None
        self.goals_model = None
        self.feature_cols = None
        self._load_models()
    
    def _load_models(self):
        """Load trained Player V2 models"""
        try:
            latest_file = MODEL_DIR / "latest.json"
            if latest_file.exists():
                import json
                with open(latest_file, 'r') as f:
                    version = json.load(f).get('version')
                
                gi_file = MODEL_DIR / f"goal_involvement_{version}.pkl"
                if gi_file.exists():
                    with open(gi_file, 'rb') as f:
                        gi_data = pickle.load(f)
                        self.goal_involvement_model = gi_data['models']
                        self.feature_cols = gi_data['feature_cols']
                    logger.info(f"Loaded goal involvement model v{version}")
                
                goals_file = MODEL_DIR / f"goals_regression_{version}.pkl"
                if goals_file.exists():
                    with open(goals_file, 'rb') as f:
                        goals_data = pickle.load(f)
                        self.goals_model = goals_data['models']
                    logger.info(f"Loaded goals regression model v{version}")
            else:
                logger.warning("No Player V2 models found - using heuristic predictions")
        except Exception as e:
            logger.error(f"Failed to load Player V2 models: {e}")
    
    def get_player_form(self, player_id: int, lookback_games: int = 5) -> Dict:
        """Get player's recent form statistics"""
        with self.engine.connect() as conn:
            result = conn.execute(text("""
                SELECT 
                    COUNT(*) as games,
                    AVG(minutes_played) as avg_minutes,
                    AVG((stats->>'goals')::float) as avg_goals,
                    AVG((stats->>'assists')::float) as avg_assists,
                    AVG((stats->>'shots_total')::float) as avg_shots,
                    AVG((stats->>'rating')::float) as avg_rating,
                    SUM((stats->>'goals')::int) as total_goals,
                    SUM((stats->>'assists')::int) as total_assists
                FROM (
                    SELECT * FROM player_game_stats
                    WHERE player_id = :player_id
                    AND sport_key = 'soccer'
                    ORDER BY game_date DESC
                    LIMIT :limit
                ) recent_games
            """), {'player_id': player_id, 'limit': lookback_games})
            
            row = result.fetchone()
            if row and row.games and row.games >= 2:
                return {
                    'games': row.games,
                    'avg_minutes': float(row.avg_minutes or 0),
                    'avg_goals': float(row.avg_goals or 0),
                    'avg_assists': float(row.avg_assists or 0),
                    'avg_shots': float(row.avg_shots or 0),
                    'avg_rating': float(row.avg_rating or 6.5),
                    'total_goals': int(row.total_goals or 0),
                    'total_assists': int(row.total_assists or 0),
                    'goal_involvement_rate': (row.total_goals + row.total_assists) / row.games if row.games > 0 else 0
                }
        
        return {
            'games': 0,
            'avg_minutes': 0,
            'avg_goals': 0,
            'avg_assists': 0,
            'avg_shots': 0,
            'avg_rating': 6.5,
            'total_goals': 0,
            'total_assists': 0,
            'goal_involvement_rate': 0
        }
    
    def get_player_info(self, player_id: int) -> Optional[Dict]:
        """Get player details"""
        with self.engine.connect() as conn:
            result = conn.execute(text("""
                SELECT 
                    player_id,
                    player_name,
                    team_id,
                    position,
                    nationality
                FROM players_unified
                WHERE player_id = :player_id
            """), {'player_id': player_id})
            
            row = result.fetchone()
            if row:
                return {
                    'player_id': row.player_id,
                    'name': row.player_name,
                    'team_id': row.team_id,
                    'position': row.position,
                    'nationality': row.nationality
                }
        return None
    
    def predict_anytime_scorer(self, player_id: int, match_id: int = None) -> Dict:
        """Predict probability of player scoring (anytime scorer)"""
        player = self.get_player_info(player_id)
        if not player:
            return {'error': 'Player not found', 'probability': 0}
        
        form = self.get_player_form(player_id)
        
        base_prob = 0.05
        
        position = player.get('position', '').lower()
        if 'forward' in position or 'attacker' in position or 'striker' in position:
            base_prob = 0.18
        elif 'midfielder' in position:
            base_prob = 0.10
        elif 'defender' in position:
            base_prob = 0.04
        elif 'goalkeeper' in position:
            base_prob = 0.001
        
        if form['games'] >= 3:
            form_adjustment = form['avg_goals'] * 0.25
            base_prob = base_prob * 0.65 + (base_prob + form_adjustment) * 0.35
        
        if form['avg_shots'] > 3:
            base_prob *= 1.10
        elif form['avg_shots'] > 2:
            base_prob *= 1.05
        
        if form['avg_rating'] > 7.5:
            base_prob *= 1.08
        elif form['avg_rating'] < 6.5:
            base_prob *= 0.92
        
        if form['avg_minutes'] < 60:
            base_prob *= form['avg_minutes'] / 90
        
        probability = max(0.01, min(0.28, base_prob))
        
        confidence = min(1.0, form['games'] / 5)
        
        return {
            'player_id': player_id,
            'player_name': player['name'],
            'position': player['position'],
            'market': 'anytime_scorer',
            'probability': round(probability, 4),
            'confidence': round(confidence, 2),
            'form': {
                'games_played': form['games'],
                'goals_last_5': form['total_goals'],
                'avg_shots': round(form['avg_shots'], 1),
                'avg_rating': round(form['avg_rating'], 1)
            }
        }
    
    def predict_goals_scored(self, player_id: int, match_id: int = None) -> Dict:
        """Predict number of goals player will score"""
        player = self.get_player_info(player_id)
        if not player:
            return {'error': 'Player not found'}
        
        form = self.get_player_form(player_id)
        
        expected_goals = form['avg_goals'] if form['games'] >= 3 else 0.15
        
        from scipy.stats import poisson
        
        prob_0 = poisson.pmf(0, expected_goals)
        prob_1 = poisson.pmf(1, expected_goals)
        prob_2_plus = 1 - poisson.cdf(1, expected_goals)
        
        return {
            'player_id': player_id,
            'player_name': player['name'],
            'position': player['position'],
            'expected_goals': round(expected_goals, 2),
            'probabilities': {
                '0_goals': round(prob_0, 4),
                '1_goal': round(prob_1, 4),
                '2_plus_goals': round(prob_2_plus, 4)
            },
            'confidence': min(1.0, form['games'] / 5)
        }
    
    def get_top_scorer_picks(self, match_ids: List[int] = None, 
                             limit: int = 10) -> List[Dict]:
        """Get top scorer predictions across matches"""
        with self.engine.connect() as conn:
            if match_ids:
                match_filter = "AND f.match_id = ANY(:match_ids)"
                params = {
                    'match_ids': match_ids,
                    'limit': limit * 3
                }
            else:
                match_filter = ""
                params = {'limit': limit * 3}
            
            result = conn.execute(text(f"""
                SELECT DISTINCT
                    p.player_id,
                    p.player_name,
                    p.team_id,
                    p.position,
                    f.match_id,
                    f.home_team,
                    f.away_team,
                    f.kickoff_at
                FROM players_unified p
                JOIN fixtures f ON (p.team_id = f.home_team_id OR p.team_id = f.away_team_id)
                WHERE f.status = 'scheduled'
                AND f.kickoff_at > NOW()
                AND f.kickoff_at < NOW() + INTERVAL '7 days'
                AND p.position IS NOT NULL
                AND LOWER(p.position) LIKE '%forward%'
                   OR LOWER(p.position) LIKE '%attacker%'
                   OR LOWER(p.position) LIKE '%striker%'
                {match_filter}
                ORDER BY f.kickoff_at ASC
                LIMIT :limit
            """), params)
            
            players = []
            for row in result:
                pred = self.predict_anytime_scorer(row.player_id, row.match_id)
                if pred.get('probability', 0) > 0.15:
                    players.append({
                        **pred,
                        'match_id': row.match_id,
                        'match': f"{row.home_team} vs {row.away_team}",
                        'kickoff_at': row.kickoff_at.isoformat() if row.kickoff_at else None
                    })
        
        players.sort(key=lambda x: x['probability'], reverse=True)
        return players[:limit]
    
    def get_player_props_for_parlay(self, player_id: int, match_id: int) -> Dict:
        """Get player prop predictions formatted for parlay builder"""
        scorer_pred = self.predict_anytime_scorer(player_id, match_id)
        goals_pred = self.predict_goals_scored(player_id, match_id)
        
        if 'error' in scorer_pred:
            return {'error': scorer_pred['error']}
        
        return {
            'player_id': player_id,
            'player_name': scorer_pred['player_name'],
            'match_id': match_id,
            'position': scorer_pred['position'],
            'markets': {
                'anytime_scorer': {
                    'probability': scorer_pred['probability'],
                    'confidence': scorer_pred['confidence']
                },
                '2_plus_goals': {
                    'probability': goals_pred['probabilities']['2_plus_goals'],
                    'confidence': goals_pred['confidence']
                },
                'to_assist': {
                    'probability': round(scorer_pred['probability'] * 0.7, 4),
                    'confidence': scorer_pred['confidence']
                }
            },
            'form': scorer_pred['form']
        }
