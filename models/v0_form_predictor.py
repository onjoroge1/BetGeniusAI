"""
V0 Form-Only Predictor

Predicts match results using only form data (ELO, recent results).
No odds data required - can predict ANY match with team IDs.

This is the fallback predictor when V1/V3 can't make predictions.
Uses binary expert ensemble with weighted voting (~50% accuracy).

Note: Form-only predictions are ~10-12% less accurate than odds-based
predictions (V1/V3 at 52-53%) but still better than random (33%).
"""

import os
import json
import logging
from typing import Dict, Optional
from datetime import datetime
from collections import defaultdict

import numpy as np
import joblib
from sqlalchemy import create_engine, text

from models.team_elo import TeamELOManager, INITIAL_ELO

logger = logging.getLogger(__name__)

MODEL_DIR = "models/saved"
MODEL_NAME = "v0_form_model"

K_FACTOR = 32
HOME_ADVANTAGE = 100
TIER1_LEAGUES = {39, 140, 78, 135, 61}


class V0FormPredictor:
    """Predicts match results using form-only features with binary experts."""
    
    def __init__(self):
        self.model_data = None
        self.metadata = None
        self.elo_manager = TeamELOManager()
        self.engine = create_engine(os.environ['DATABASE_URL'])
        self.form_cache = defaultdict(list)
        self._load_model()
    
    def _load_model(self):
        """Load the trained model."""
        pkl_path = f"{MODEL_DIR}/{MODEL_NAME}_latest.pkl"
        meta_path = f"{MODEL_DIR}/{MODEL_NAME}_latest_meta.json"
        
        if not os.path.exists(pkl_path):
            logger.warning(f"V0 model not found at {pkl_path}")
            return
        
        try:
            self.model_data = joblib.load(pkl_path)
            
            if os.path.exists(meta_path):
                with open(meta_path, 'r') as f:
                    self.metadata = json.load(f)
            
            acc = self.metadata.get('cv_accuracy_mean', 0) if self.metadata else 0
            model_type = self.model_data.get('model_type', 'unknown')
            leak_free = self.model_data.get('leak_free', False)
            logger.info(f"V0 Form model loaded: {acc:.1%} accuracy, type={model_type}, leak_free={leak_free}")
        except Exception as e:
            logger.error(f"Failed to load V0 model: {e}")
            self.model_data = None
    
    def is_available(self) -> bool:
        """Check if the predictor is ready."""
        return self.model_data is not None and 'experts' in self.model_data
    
    def _get_team_form(self, team_id: int, n: int = 5) -> list:
        """Get recent form for a team from database."""
        if team_id in self.form_cache:
            return self.form_cache[team_id][-n:]
        
        try:
            with self.engine.connect() as conn:
                result = conn.execute(text("""
                    SELECT 
                        CASE 
                            WHEN f.home_team_id = :team_id AND m.outcome = 'H' THEN 'W'
                            WHEN f.away_team_id = :team_id AND m.outcome = 'A' THEN 'W'
                            WHEN m.outcome = 'D' THEN 'D'
                            ELSE 'L'
                        END as result
                    FROM fixtures f
                    JOIN matches m ON f.match_id = m.match_id
                    WHERE (f.home_team_id = :team_id OR f.away_team_id = :team_id)
                    AND f.status = 'finished'
                    AND m.outcome IS NOT NULL
                    ORDER BY f.kickoff_at DESC
                    LIMIT :n
                """), {'team_id': team_id, 'n': n})
                
                form = [row.result for row in result.fetchall()]
                form.reverse()
                self.form_cache[team_id] = form
                return form
        except Exception as e:
            logger.debug(f"Could not get form for team {team_id}: {e}")
            return []
    
    def _build_features(self, home_team_id: int, away_team_id: int, league_id: int = None) -> np.ndarray:
        """Build feature vector for prediction."""
        home_elo = self.elo_manager.get_team_elo(home_team_id)
        away_elo = self.elo_manager.get_team_elo(away_team_id)
        
        home_form = self._get_team_form(home_team_id, 5)
        away_form = self._get_team_form(away_team_id, 5)
        
        def pts(f): 
            return sum(3 if x=='W' else 1 if x=='D' else 0 for x in f)
        def wr(f): 
            return sum(1 for x in f if x=='W') / max(len(f), 1) if f else 0.33
        def dr(f): 
            return sum(1 for x in f if x=='D') / max(len(f), 1) if f else 0.33
        
        elo_diff = home_elo - away_elo
        elo_expected = 1.0 / (1.0 + 10 ** ((away_elo - home_elo - HOME_ADVANTAGE) / 400.0))
        
        features = [
            elo_diff,
            elo_expected,
            HOME_ADVANTAGE,
            home_elo,
            away_elo,
            pts(home_form) - pts(away_form),
            wr(home_form) - wr(away_form),
            dr(home_form) + dr(away_form),
            len(home_form),
            len(away_form),
            1 if league_id in TIER1_LEAGUES else 0,
        ]
        
        return np.array(features).reshape(1, -1), home_elo, away_elo, elo_expected
    
    def predict(self, match_id: int, 
                home_team_id: int = None,
                away_team_id: int = None,
                kickoff_at: datetime = None,
                league_id: int = None) -> Optional[Dict]:
        """
        Predict match result probabilities using binary expert ensemble.
        
        Returns:
            Dict with 'H', 'D', 'A' probabilities and metadata
        """
        if not self.is_available():
            logger.warning("V0 predictor not available")
            return None
        
        try:
            if not home_team_id or not away_team_id:
                with self.engine.connect() as conn:
                    result = conn.execute(text("""
                        SELECT home_team_id, away_team_id, league_id FROM fixtures
                        WHERE match_id = :match_id
                    """), {'match_id': match_id})
                    row = result.fetchone()
                    if row:
                        home_team_id = row.home_team_id
                        away_team_id = row.away_team_id
                        if not league_id:
                            league_id = row.league_id
            
            if not home_team_id or not away_team_id:
                logger.debug(f"Missing team IDs for match {match_id}")
                return None
            
            X, home_elo, away_elo, elo_expected = self._build_features(
                home_team_id, away_team_id, league_id
            )
            
            scaler = self.model_data.get('scaler')
            if scaler:
                X = scaler.transform(X)
            
            experts = self.model_data['experts']
            weights = self.model_data.get('weights', {'home': 0.45, 'draw': 0.20, 'away': 0.35})
            
            hp = experts['home'].predict_proba(X)[0, 1]
            dp = experts['draw'].predict_proba(X)[0, 1]
            ap = experts['away'].predict_proba(X)[0, 1]
            
            raw_probs = np.array([
                hp * weights['home'],
                dp * weights['draw'],
                ap * weights['away']
            ])
            normalized = raw_probs / raw_probs.sum()
            
            prob_h = float(normalized[0])
            prob_d = float(normalized[1])
            prob_a = float(normalized[2])
            
            pred_idx = np.argmax(normalized)
            predicted = ['H', 'D', 'A'][pred_idx]
            confidence = float(normalized[pred_idx])
            
            return {
                'model': 'v0_form',
                'model_type': 'binary_experts_weighted',
                'match_id': match_id,
                'probabilities': {
                    'H': prob_h,
                    'D': prob_d,
                    'A': prob_a
                },
                'prediction': predicted,
                'confidence': confidence,
                'features_used': 11,
                'elo_home': round(home_elo, 1),
                'elo_away': round(away_elo, 1),
                'elo_expected': round(elo_expected, 4),
                'data_quality': 'form_only',
                'leak_free': self.model_data.get('leak_free', False),
                'expected_accuracy': '~50%',
                'note': 'Form-only fallback - less accurate than odds-based predictions'
            }
            
        except Exception as e:
            logger.error(f"V0 prediction error for match {match_id}: {e}")
            return None
    
    def get_model_info(self) -> Dict:
        """Get model information and status."""
        if not self.metadata:
            return {'status': 'not_loaded'}
        
        return {
            'status': 'loaded',
            'accuracy': self.metadata.get('cv_accuracy_mean'),
            'logloss': self.metadata.get('cv_logloss_mean'),
            'n_samples': self.metadata.get('n_samples'),
            'n_features': self.metadata.get('n_features'),
            'model_type': self.metadata.get('model_type'),
            'leak_free': self.metadata.get('leak_free', False),
            'trained_at': self.metadata.get('trained_at'),
            'note': self.metadata.get('note')
        }


_predictor_instance = None


def get_v0_predictor() -> V0FormPredictor:
    """Get singleton instance of V0 predictor."""
    global _predictor_instance
    if _predictor_instance is None:
        _predictor_instance = V0FormPredictor()
    return _predictor_instance
