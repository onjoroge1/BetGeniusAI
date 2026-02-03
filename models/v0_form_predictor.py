"""
V0 Form-Only Predictor

Predicts match results using only form data (ELO, recent results, H2H).
No odds data required - can predict ANY match with team IDs.

This is the fallback predictor when V1/V3 can't make predictions.
"""

import os
import json
import logging
from typing import Dict, Optional
from datetime import datetime

import numpy as np
import joblib
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from models.team_elo import TeamELOManager, INITIAL_ELO

logger = logging.getLogger(__name__)

MODEL_DIR = "models/saved"
MODEL_NAME = "v0_form_model"


class V0FormPredictor:
    """Predicts match results using form-only features."""
    
    def __init__(self):
        self.model = None
        self.scaler = None
        self.metadata = None
        self.elo_manager = TeamELOManager()
        self.engine = create_engine(os.environ['DATABASE_URL'])
        self._load_model()
    
    def _load_model(self):
        """Load the trained model and scaler."""
        pkl_path = f"{MODEL_DIR}/{MODEL_NAME}_latest.pkl"
        scaler_path = f"{MODEL_DIR}/{MODEL_NAME}_scaler.pkl"
        meta_path = f"{MODEL_DIR}/{MODEL_NAME}_latest_meta.json"
        
        if not os.path.exists(pkl_path):
            logger.warning(f"V0 model not found at {pkl_path}")
            return
        
        try:
            self.model = joblib.load(pkl_path)
            
            if os.path.exists(scaler_path):
                self.scaler = joblib.load(scaler_path)
            
            if os.path.exists(meta_path):
                with open(meta_path, 'r') as f:
                    self.metadata = json.load(f)
            
            acc = self.metadata.get('cv_accuracy_mean', 0) if self.metadata else 0
            logger.info(f"V0 Form model loaded: {acc:.1%} accuracy")
        except Exception as e:
            logger.error(f"Failed to load V0 model: {e}")
            self.model = None
    
    def is_available(self) -> bool:
        """Check if the predictor is ready."""
        return self.model is not None
    
    def predict(self, match_id: int, 
                home_team_id: int = None,
                away_team_id: int = None,
                kickoff_at: datetime = None,
                league_id: int = None) -> Optional[Dict]:
        """
        Predict match result probabilities.
        
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
                        SELECT home_team_id, away_team_id FROM fixtures
                        WHERE match_id = :match_id
                    """), {'match_id': match_id})
                    row = result.fetchone()
                    if row:
                        home_team_id = row.home_team_id
                        away_team_id = row.away_team_id
            
            if not home_team_id or not away_team_id:
                logger.debug(f"Missing team IDs for match {match_id}")
                return None
            
            home_elo = self.elo_manager.get_team_elo(home_team_id)
            away_elo = self.elo_manager.get_team_elo(away_team_id)
            
            elo_diff = home_elo - away_elo
            elo_expected = 1.0 / (1.0 + 10 ** ((away_elo - home_elo - 100) / 400.0))
            home_advantage = 100.0
            
            def get_tier(elo):
                if elo >= 1700:
                    return 3
                elif elo >= 1550:
                    return 2
                elif elo >= 1400:
                    return 1
                else:
                    return 0
            
            elo_tier_diff = get_tier(home_elo) - get_tier(away_elo)
            
            X = np.array([[elo_diff, elo_expected, home_advantage, elo_tier_diff]])
            
            if self.scaler:
                X = self.scaler.transform(X)
            
            probs = self.model.predict_proba(X)[0]
            
            class_map = {0: 'H', 1: 'D', 2: 'A'}
            
            prob_h = float(probs[0])
            prob_d = float(probs[1])
            prob_a = float(probs[2])
            
            pred_idx = np.argmax(probs)
            predicted = class_map[pred_idx]
            confidence = float(probs[pred_idx])
            
            return {
                'model': 'v0_form',
                'model_type': 'form_only',
                'match_id': match_id,
                'probabilities': {
                    'H': prob_h,
                    'D': prob_d,
                    'A': prob_a
                },
                'prediction': predicted,
                'confidence': confidence,
                'features_used': 4,
                'elo_home': round(home_elo, 1),
                'elo_away': round(away_elo, 1),
                'elo_expected': round(elo_expected, 4),
                'data_quality': 'form_only'
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
            'trained_at': self.metadata.get('trained_at')
        }


_predictor_instance = None

def get_v0_predictor() -> V0FormPredictor:
    """Get singleton V0 predictor instance."""
    global _predictor_instance
    if _predictor_instance is None:
        _predictor_instance = V0FormPredictor()
    return _predictor_instance


if __name__ == "__main__":
    predictor = V0FormPredictor()
    print(f"V0 Predictor available: {predictor.is_available()}")
    print(f"Model info: {predictor.get_model_info()}")
    
    with predictor.engine.connect() as conn:
        result = conn.execute(text("""
            SELECT match_id, home_team, away_team FROM fixtures 
            WHERE status = 'scheduled' AND kickoff_at > NOW()
            AND home_team_id IS NOT NULL
            LIMIT 3
        """))
        for row in result:
            pred = predictor.predict(row.match_id)
            if pred:
                print(f"\n{row.home_team} vs {row.away_team}:")
                print(f"  Prediction: {pred['prediction']} ({pred['confidence']:.1%})")
                print(f"  ELO: Home={pred['elo_home']}, Away={pred['elo_away']}")
                print(f"  Probabilities: H={pred['probabilities']['H']:.1%}, D={pred['probabilities']['D']:.1%}, A={pred['probabilities']['A']:.1%}")
