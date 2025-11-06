"""
V2 LightGBM Prediction Service
Loads trained V2 LightGBM model (52.7% accuracy, 75.9% @ 62% threshold)

NOW WITH FULL 46-FEATURE PIPELINE RESTORED
"""
import pickle
import json
import logging
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Dict, Optional
from functools import lru_cache
import sys
sys.path.append('.')
from features.v2_feature_builder import get_v2_feature_builder

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
        self.feature_builder = None
        self._load_model()
        
        # Initialize feature builder
        try:
            self.feature_builder = get_v2_feature_builder()
            logger.info("✅ V2 Feature Builder initialized")
        except Exception as e:
            logger.warning(f"⚠️  Feature builder initialization failed: {e}")
            logger.warning("⚠️  Falling back to market-only features")
    
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
    
    def ensure_feature_parity(self, features_dict: Dict[str, float]) -> np.ndarray:
        """
        Ensure feature parity with trained model
        
        CRITICAL SAFETY: Prevents the 12/46 feature bleed that was causing
        accuracy degradation. Validates all required features are present
        and orders them correctly.
        
        Args:
            features_dict: Dictionary of feature name -> value
            
        Returns:
            Numpy array with features in correct order
            
        Raises:
            ValueError: If required features are missing
        """
        incoming = set(features_dict.keys())
        required = set(self.feature_cols)
        
        missing = required - incoming
        extra = incoming - required
        
        if missing:
            logger.error(f"❌ FEATURE PARITY FAILURE: Missing {len(missing)} features")
            logger.error(f"   First 10 missing: {list(missing)[:10]}")
            raise ValueError(f"Missing {len(missing)} required features for V2 model")
        
        if extra:
            logger.warning(f"⚠️  Extra features will be ignored: {len(extra)}")
        
        # Build feature vector in exact trained order
        feature_vector = []
        for col in self.feature_cols:
            value = features_dict.get(col, 0.0)
            if value is None or np.isnan(value):
                value = 0.0  # Impute missing as 0
            feature_vector.append(float(value))
        
        return np.array(feature_vector).reshape(1, -1)
    
    def predict(
        self,
        match_id: Optional[int] = None,
        market_probs: Optional[Dict[str, float]] = None
    ) -> Optional[Dict]:
        """
        Generate V2 LightGBM prediction with FULL 46-feature pipeline
        
        Args:
            match_id: Match ID to build features for (preferred)
            market_probs: Current market probabilities {home, draw, away}
                         Only used as fallback if feature builder unavailable
        
        Returns:
            {
                'probabilities': {home, draw, away},
                'confidence': max probability,
                'prediction': 'home' | 'draw' | 'away',
                'feature_source': 'full_pipeline' | 'market_only'
            }
        """
        try:
            feature_source = 'market_only'
            
            # Try to build full features from database
            if match_id and self.feature_builder:
                try:
                    features = self.feature_builder.build_features(match_id)
                    feature_source = 'full_pipeline'
                    logger.info(f"✅ Built {len(features)} features for match {match_id}")
                except Exception as e:
                    logger.warning(f"⚠️  Feature building failed for match {match_id}: {e}")
                    logger.warning("⚠️  Falling back to market-only features")
                    features = None
            else:
                features = None
            
            # Fallback to market-only features
            if not features:
                if not market_probs:
                    logger.error("❌ No match_id and no market_probs provided")
                    return None
                
                # Use market features only (legacy MVP mode)
                features = {
                    'p_last_home': market_probs.get('home', 0.33),
                    'p_last_draw': market_probs.get('draw', 0.33),
                    'p_last_away': market_probs.get('away', 0.33),
                    'p_open_home': market_probs.get('home', 0.33),
                    'p_open_draw': market_probs.get('draw', 0.33),
                    'p_open_away': market_probs.get('away', 0.33),
                    'market_entropy': self._calc_entropy(market_probs),
                    'favorite_margin': max(market_probs.values()) - min(market_probs.values()),
                }
                
                # Zero-fill missing features (SUBOPTIMAL - causes accuracy loss)
                for col in self.feature_cols:
                    if col not in features:
                        features[col] = 0.0
                
                logger.warning(f"⚠️  Using market-only mode - expect reduced accuracy")
            
            # Validate feature parity and build array
            X = self.ensure_feature_parity(features)
            
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
                'prediction': prediction,
                'feature_source': feature_source
            }
            
        except Exception as e:
            logger.error(f"V2 LightGBM prediction failed: {e}")
            logger.exception(e)
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
