"""
V2-NBA Predictor
Binary classification for NBA games using LightGBM
"""

import os
import logging
import joblib
import numpy as np
from datetime import datetime, timezone
from typing import Dict, List, Optional
from sqlalchemy import create_engine, text

logger = logging.getLogger(__name__)


class V2NBAPredictor:
    """NBA match predictor using V2 LightGBM model"""
    
    def __init__(self):
        self.model = None
        self.feature_names = []
        self.accuracy = 0.0
        self.loaded = False
        self._load_model()
        self.engine = create_engine(os.environ.get('DATABASE_URL', ''))
    
    def _load_model(self):
        """Load trained model from artifacts"""
        model_path = os.path.join(
            os.path.dirname(__file__), 
            'artifacts', 
            'v2_nba_model.joblib'
        )
        
        if not os.path.exists(model_path):
            logger.warning("V2-NBA model not found. Train with: python training/train_v2_nba.py")
            return
        
        try:
            model_data = joblib.load(model_path)
            self.model = model_data['model']
            self.feature_names = model_data['feature_names']
            self.accuracy = model_data.get('accuracy', 0)
            self.trained_at = model_data.get('trained_at', 'unknown')
            self.loaded = True
            logger.info(f"V2-NBA model loaded: {self.accuracy:.1%} accuracy, {len(self.feature_names)} features")
        except Exception as e:
            logger.error(f"Failed to load V2-NBA model: {e}")
    
    def get_upcoming_games(self, limit: int = 20) -> List[Dict]:
        """Get upcoming NBA games with odds"""
        query = """
            SELECT DISTINCT ON (event_id)
                event_id,
                home_team,
                away_team,
                commence_time,
                home_odds,
                away_odds,
                home_prob,
                away_prob,
                overround,
                n_bookmakers,
                home_spread,
                total_line,
                home_spread_odds,
                away_spread_odds,
                over_odds,
                under_odds
            FROM multisport_odds_snapshots
            WHERE sport_key = 'basketball_nba'
            AND commence_time > NOW()
            ORDER BY event_id, ts_recorded DESC
            LIMIT :limit
        """
        
        with self.engine.connect() as conn:
            result = conn.execute(text(query), {'limit': limit})
            rows = result.fetchall()
            
        games = []
        for row in rows:
            games.append({
                'event_id': row[0],
                'home_team': row[1],
                'away_team': row[2],
                'commence_time': row[3].isoformat() if row[3] else None,
                'home_odds': float(row[4]) if row[4] else None,
                'away_odds': float(row[5]) if row[5] else None,
                'home_prob': float(row[6]) if row[6] else None,
                'away_prob': float(row[7]) if row[7] else None,
                'overround': float(row[8]) if row[8] else None,
                'n_bookmakers': int(row[9]) if row[9] else 1,
                'home_spread': float(row[10]) if row[10] else None,
                'total_line': float(row[11]) if row[11] else None,
                'home_spread_odds': float(row[12]) if row[12] else None,
                'away_spread_odds': float(row[13]) if row[13] else None,
                'over_odds': float(row[14]) if row[14] else None,
                'under_odds': float(row[15]) if row[15] else None
            })
        
        return games
    
    def predict_game(self, game: Dict) -> Dict:
        """Predict outcome for a single game"""
        if not self.loaded:
            implied_home = game.get('home_prob') or (1 / game['home_odds'] if game.get('home_odds') else 0.5)
            implied_away = game.get('away_prob') or (1 / game['away_odds'] if game.get('away_odds') else 0.5)
            
            return {
                'event_id': game.get('event_id'),
                'home_team': game.get('home_team'),
                'away_team': game.get('away_team'),
                'commence_time': game.get('commence_time'),
                'prediction': 'Home Win' if implied_home > implied_away else 'Away Win',
                'home_prob': round(implied_home * 100, 1),
                'away_prob': round(implied_away * 100, 1),
                'confidence': 'market_implied',
                'model_status': 'not_loaded',
                'home_odds': game.get('home_odds'),
                'away_odds': game.get('away_odds')
            }
        
        features = []
        for fname in self.feature_names:
            val = game.get(fname)
            if val is None:
                if 'prob' in fname:
                    val = 0.5
                elif 'odds' in fname:
                    val = 2.0
                else:
                    val = 0.0
            features.append(float(val))
        
        X = np.array([features])
        
        away_prob = self.model.predict_proba(X)[0][1]
        home_prob = 1 - away_prob
        
        implied_home = game.get('home_prob') or (1 / game['home_odds'] if game.get('home_odds') else 0.5)
        implied_away = game.get('away_prob') or (1 / game['away_odds'] if game.get('away_odds') else 0.5)
        
        home_edge = (home_prob - implied_home) * 100
        away_edge = (away_prob - implied_away) * 100
        
        if home_prob > away_prob:
            prediction = 'Home Win'
            confidence = 'high' if home_prob > 0.65 else 'medium' if home_prob > 0.55 else 'low'
        else:
            prediction = 'Away Win'
            confidence = 'high' if away_prob > 0.65 else 'medium' if away_prob > 0.55 else 'low'
        
        return {
            'event_id': game.get('event_id'),
            'home_team': game.get('home_team'),
            'away_team': game.get('away_team'),
            'commence_time': game.get('commence_time'),
            'prediction': prediction,
            'home_prob': round(home_prob * 100, 1),
            'away_prob': round(away_prob * 100, 1),
            'implied_home_prob': round(implied_home * 100, 1),
            'implied_away_prob': round(implied_away * 100, 1),
            'home_edge': round(home_edge, 2),
            'away_edge': round(away_edge, 2),
            'confidence': confidence,
            'model_status': 'loaded',
            'model_accuracy': round(self.accuracy * 100, 1),
            'home_odds': game.get('home_odds'),
            'away_odds': game.get('away_odds'),
            'spread': game.get('home_spread'),
            'total': game.get('total_line')
        }
    
    def predict_all_upcoming(self, limit: int = 20) -> List[Dict]:
        """Predict all upcoming NBA games"""
        games = self.get_upcoming_games(limit=limit)
        predictions = []
        
        for game in games:
            pred = self.predict_game(game)
            predictions.append(pred)
        
        predictions.sort(key=lambda x: abs(x.get('home_edge', 0) or 0), reverse=True)
        
        return predictions
    
    def predict_matchup(self, home_team: str, away_team: str) -> Optional[Dict]:
        """Find and predict a specific matchup"""
        query = """
            SELECT DISTINCT ON (event_id)
                event_id, home_team, away_team, commence_time,
                home_odds, away_odds, home_prob, away_prob,
                overround, n_bookmakers, home_spread, total_line,
                home_spread_odds, away_spread_odds, over_odds, under_odds
            FROM multisport_odds_snapshots
            WHERE sport_key = 'basketball_nba'
            AND LOWER(home_team) LIKE :home_pattern
            AND LOWER(away_team) LIKE :away_pattern
            ORDER BY event_id, ts_recorded DESC
            LIMIT 1
        """
        
        with self.engine.connect() as conn:
            result = conn.execute(text(query), {
                'home_pattern': f'%{home_team.lower()}%',
                'away_pattern': f'%{away_team.lower()}%'
            })
            row = result.fetchone()
        
        if not row:
            with self.engine.connect() as conn:
                result = conn.execute(text(query.replace(':home_pattern', ':away_pattern').replace(':away_pattern', ':home_pattern')), {
                    'home_pattern': f'%{away_team.lower()}%',
                    'away_pattern': f'%{home_team.lower()}%'
                })
                row = result.fetchone()
        
        if not row:
            return None
        
        game = {
            'event_id': row[0],
            'home_team': row[1],
            'away_team': row[2],
            'commence_time': row[3].isoformat() if row[3] else None,
            'home_odds': float(row[4]) if row[4] else None,
            'away_odds': float(row[5]) if row[5] else None,
            'home_prob': float(row[6]) if row[6] else None,
            'away_prob': float(row[7]) if row[7] else None,
            'overround': float(row[8]) if row[8] else None,
            'n_bookmakers': int(row[9]) if row[9] else 1,
            'home_spread': float(row[10]) if row[10] else None,
            'total_line': float(row[11]) if row[11] else None,
            'home_spread_odds': float(row[12]) if row[12] else None,
            'away_spread_odds': float(row[13]) if row[13] else None,
            'over_odds': float(row[14]) if row[14] else None,
            'under_odds': float(row[15]) if row[15] else None
        }
        
        return self.predict_game(game)
    
    def get_model_status(self) -> Dict:
        """Get model status and info"""
        return {
            'loaded': self.loaded,
            'accuracy': round(self.accuracy * 100, 1) if self.loaded else None,
            'n_features': len(self.feature_names),
            'features': self.feature_names,
            'trained_at': getattr(self, 'trained_at', None),
            'sport': 'basketball_nba'
        }
