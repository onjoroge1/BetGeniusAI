"""
V2 LightGBM Prediction Service
Loads trained V2 LightGBM model (52.7% accuracy, 75.9% @ 62% threshold)
"""
import pickle
import json
import logging
import numpy as np
from pathlib import Path
from typing import Dict, Optional
from functools import lru_cache

logger = logging.getLogger(__name__)

class V2LightGBMPredictor:
    """
    V2 LightGBM prediction service
    
    Performance:
    - Overall: 52.7% 3-way accuracy
    - Selective (conf >= 0.62): 75.9% hit rate @ 17.3% coverage
    """
    
    def __init__(self, model_dir: str = "artifacts/models/lgbm_historical_36k"):
        self.model_dir = Path(model_dir)
        self.models = None
        self.feature_cols = None
        self.metadata = None
        self._load_model()
    
    def _load_model(self):
        """Load trained LightGBM ensemble"""
        try:
            # Load models
            model_path = self.model_dir / "lgbm_ensemble.pkl"
            with open(model_path, "rb") as f:
                self.models = pickle.load(f)
            
            # Load features
            features_path = self.model_dir / "features.json"
            with open(features_path) as f:
                self.feature_cols = json.load(f)
            
            # Load metadata
            metadata_path = self.model_dir / "metadata.json"
            with open(metadata_path) as f:
                self.metadata = json.load(f)
            
            logger.info(f"✅ V2 LightGBM loaded: {len(self.models)} models, "
                       f"{self.metadata['oof_metrics']['accuracy_3way']*100:.1f}% accuracy")
            
        except Exception as e:
            logger.error(f"❌ Failed to load V2 LightGBM: {e}")
            raise RuntimeError(f"V2 LightGBM not available: {e}")
    
    def normalize_triplet(self, h: float, d: float, a: float) -> tuple:
        """Normalize probabilities to sum to 1"""
        total = h + d + a
        if total <= 0:
            return (1/3, 1/3, 1/3)
        return (h/total, d/total, a/total)
    
    def predict(
        self,
        market_probs: Dict[str, float]
    ) -> Optional[Dict]:
        """
        Generate V2 LightGBM prediction
        
        NOTE: For MVP, using market-only features since we don't have
        historical feature pipeline integrated yet.
        
        Args:
            market_probs: Current market probabilities {home, draw, away}
        
        Returns:
            {
                'probabilities': {home, draw, away},
                'confidence': max probability,
                'prediction': 'home' | 'draw' | 'away'
            }
        """
        try:
            # For MVP: Use market features only (12 features)
            # Historical features (50) would require database integration
            features = {
                'p_last_home': market_probs.get('home', 0.33),
                'p_last_draw': market_probs.get('draw', 0.33),
                'p_last_away': market_probs.get('away', 0.33),
                'p_open_home': market_probs.get('home', 0.33),
                'p_open_draw': market_probs.get('draw', 0.33),
                'p_open_away': market_probs.get('away', 0.33),
                'prob_home': market_probs.get('home', 0.33),
                'prob_draw': market_probs.get('draw', 0.33),
                'prob_away': market_probs.get('away', 0.33),
                'market_entropy': self._calc_entropy(market_probs),
                'favorite_prob': max(market_probs.values()),
                'underdog_prob': min(market_probs.values()),
            }
            
            # Build feature vector (historical features = 0 for MVP)
            X = []
            for col in self.feature_cols:
                X.append(features.get(col, 0.0))
            X = np.array(X).reshape(1, -1)
            
            # Ensemble prediction (average all folds)
            all_preds = []
            for model in self.models:
                preds = model.predict(X, num_iteration=model.best_iteration)
                all_preds.append(preds)
            
            ensemble_preds = np.mean(all_preds, axis=0)[0]
            
            # Normalize
            h, d, a = self.normalize_triplet(
                ensemble_preds[0], ensemble_preds[1], ensemble_preds[2]
            )
            
            probs = {'home': float(h), 'draw': float(d), 'away': float(a)}
            prediction = max(probs, key=probs.get)
            confidence = max(probs.values())
            
            return {
                'probabilities': probs,
                'confidence': confidence,
                'prediction': prediction
            }
            
        except Exception as e:
            logger.error(f"V2 LightGBM prediction failed: {e}")
            return None
    
    def _calc_entropy(self, probs: Dict[str, float]) -> float:
        """Calculate Shannon entropy"""
        entropy = 0.0
        for p in probs.values():
            if p > 0:
                entropy -= p * np.log(p)
        return entropy


# Singleton
_predictor = None

@lru_cache(maxsize=1)
def get_v2_lgbm_predictor() -> V2LightGBMPredictor:
    """Get singleton V2 LightGBM predictor"""
    global _predictor
    if _predictor is None:
        _predictor = V2LightGBMPredictor()
    return _predictor
