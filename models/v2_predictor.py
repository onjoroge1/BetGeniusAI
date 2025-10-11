"""
V2 Prediction Model - Market-Delta Ridge Regression
Predicts small adjustments from market consensus with hard constraints
"""

import numpy as np
from typing import Dict, List, Tuple, Optional
import logging
import pickle
import json
from pathlib import Path

logger = logging.getLogger(__name__)

MODEL_DIR = Path('models/v2')
CAL_DIR = MODEL_DIR / 'calibration'

FEATURES = [
    'prob_home', 'prob_draw', 'prob_away',
    'overround', 'book_dispersion',
    'drift_24h_home', 'drift_24h_draw', 'drift_24h_away',
]

DELTA_TAU = 1.0  # Max delta logit clamp (matches training)
BLEND_ALPHA = 0.8  # Blend weight (matches training)
MAX_KL_DIVERGENCE = 0.15  # Max KL from market
MAX_PROB_CAP = 0.90  # Max single outcome probability

class V2Predictor:
    """
    V2 Model: Market-Delta Ridge Regression
    
    Architecture:
    1. Convert market probs → logits (strong prior)
    2. Ridge regression predicts delta logits
    3. Clamp deltas to ±τ (hard constraint)
    4. Blend: z_final = z_market + α·Δz
    5. Softmax → probabilities
    6. Isotonic calibration
    7. Guardrails: KL cap, max prob cap
    """
    
    def __init__(self):
        self.model_version = "v2"
        self.is_trained = False
        self.ridge_model = None
        self.iso_calibrators = None
        self.manifest = None
        
    def predict(self, features: Dict) -> Tuple[float, float, float, str]:
        """
        Generate V2 predictions with market-delta approach
        
        Args:
            features: Dict with keys prob_home, prob_draw, prob_away, 
                     book_dispersion, drift_24h_*, etc.
        
        Returns:
            (p_home, p_draw, p_away, reason_code)
        """
        
        if not self.is_trained:
            return self._fallback_prediction(features)
        
        try:
            p_home, p_draw, p_away, reason = self._delta_logit_predict(features)
            
            if self.iso_calibrators:
                p_home, p_draw, p_away = self._apply_calibration(p_home, p_draw, p_away)
                reason = f"{reason}+CAL_GLOBAL"
            else:
                reason = f"{reason}+NO_CALIBRATION"
            
            p_home, p_draw, p_away, reason = self._apply_guardrails(
                p_home, p_draw, p_away, features, reason
            )
            
            return p_home, p_draw, p_away, reason
            
        except Exception as e:
            logger.error(f"V2 prediction error: {e}")
            return self._fallback_prediction(features)
    
    def _fallback_prediction(self, features: Dict) -> Tuple[float, float, float, str]:
        """Fallback to market probabilities when model unavailable"""
        ph = float(features.get('prob_home', 0.33))
        pd = float(features.get('prob_draw', 0.33))
        pa = float(features.get('prob_away', 0.33))
        
        total = ph + pd + pa
        if total > 0:
            ph, pd, pa = ph/total, pd/total, pa/total
        else:
            ph, pd, pa = 0.33, 0.33, 0.34
        
        return ph, pd, pa, "RC_FALLBACK_MARKET"
    
    def _extract_features(self, features: Dict) -> np.ndarray:
        """Extract feature vector from dict"""
        X = []
        for feat in FEATURES:
            val = features.get(feat, 0.0)
            if val is None:
                val = 0.0
            X.append(float(val))
        return np.array([X])
    
    def _extract_market_probs(self, features: Dict) -> np.ndarray:
        """Extract market probabilities"""
        ph = float(features.get('prob_home', 0.33))
        pd = float(features.get('prob_draw', 0.33))
        pa = float(features.get('prob_away', 0.33))
        
        total = ph + pd + pa
        if total > 0:
            ph, pd, pa = ph/total, pd/total, pa/total
        
        return np.array([[ph, pd, pa]])
    
    def _market_logits(self, pm: np.ndarray) -> np.ndarray:
        """Convert market probabilities to normalized logits"""
        pm_clipped = np.clip(pm, 1e-6, 1-1e-6)
        logits = np.log(pm_clipped)
        logits = logits - np.max(logits, axis=1, keepdims=True)
        return logits
    
    def _delta_logit_predict(self, features: Dict) -> Tuple[float, float, float, str]:
        """
        Predict with market-delta ridge regression
        
        1. Get market logits (strong prior)
        2. Predict delta logits with ridge
        3. Clamp deltas to ±τ
        4. Blend: z = z_market + α·Δz
        5. Softmax → probabilities
        """
        
        X = self._extract_features(features)
        pm = self._extract_market_probs(features)
        
        zm = self._market_logits(pm)
        
        dz = self.ridge_model.decision_function(X)
        
        dz_magnitude = np.abs(dz).mean()
        
        dz_clamped = np.clip(dz, -DELTA_TAU, DELTA_TAU)
        
        hit_clamp = np.any(np.abs(dz) > DELTA_TAU)
        
        z_final = zm + BLEND_ALPHA * dz_clamped
        z_final = z_final - np.max(z_final, axis=1, keepdims=True)
        
        probs = np.exp(z_final)
        probs = probs / probs.sum(axis=1, keepdims=True)
        
        p_home, p_draw, p_away = probs[0]
        
        if hit_clamp:
            reason = "RC_DELTA_CLIPPED"
        elif dz_magnitude < 0.1:
            reason = "RC_DELTA_SMALL"
        else:
            reason = "RC_DELTA_MODERATE"
        
        return p_home, p_draw, p_away, reason
    
    def _apply_calibration(
        self, 
        p_home: float, 
        p_draw: float, 
        p_away: float
    ) -> Tuple[float, float, float]:
        """Apply isotonic calibration with safety clamps"""
        
        if not self.iso_calibrators:
            return p_home, p_draw, p_away
        
        try:
            p_home_cal = self.iso_calibrators['home'].predict([p_home])[0]
            p_draw_cal = self.iso_calibrators['draw'].predict([p_draw])[0]
            p_away_cal = self.iso_calibrators['away'].predict([p_away])[0]
            
            p_home_cal = np.clip(p_home_cal, 0.02, 0.98)
            p_draw_cal = np.clip(p_draw_cal, 0.02, 0.98)
            p_away_cal = np.clip(p_away_cal, 0.02, 0.98)
            
            total = p_home_cal + p_draw_cal + p_away_cal
            if total > 0:
                return p_home_cal/total, p_draw_cal/total, p_away_cal/total
            else:
                return p_home, p_draw, p_away
                
        except Exception as e:
            logger.error(f"Calibration error: {e}")
            return p_home, p_draw, p_away
    
    def _apply_guardrails(
        self, 
        p_home: float, 
        p_draw: float, 
        p_away: float, 
        features: Dict,
        reason: str
    ) -> Tuple[float, float, float, str]:
        """
        Apply safety guardrails:
        1. KL divergence cap (max distance from market)
        2. Max probability cap (prevent extreme confidence)
        """
        
        pm = self._extract_market_probs(features)[0]
        probs = np.array([p_home, p_draw, p_away])
        
        eps = 1e-9
        probs_safe = np.clip(probs, eps, 1-eps)
        pm_safe = np.clip(pm, eps, 1-eps)
        kl = np.sum(probs_safe * np.log(probs_safe / pm_safe))
        
        if kl > MAX_KL_DIVERGENCE:
            blend_factor = 0.5
            probs = (1 - blend_factor) * probs + blend_factor * pm
            probs = probs / probs.sum()
            reason = f"{reason}+KL_CAPPED"
        
        max_prob = np.max(probs)
        if max_prob > MAX_PROB_CAP:
            shrink_factor = 0.2
            probs = (1 - shrink_factor) * probs + shrink_factor * pm
            probs = probs / probs.sum()
            reason = f"{reason}+MAX_PROB_CAPPED"
        
        return probs[0], probs[1], probs[2], reason
    
    def load_models(self, model_path: str = None):
        """
        Load trained V2 ridge model and calibration artifacts
        
        Args:
            model_path: Path to model directory (default: models/v2/)
        """
        if model_path:
            model_dir = Path(model_path)
        else:
            model_dir = MODEL_DIR
        
        manifest_path = model_dir / 'manifest.json'
        if not manifest_path.exists():
            logger.warning(f"No manifest found at {manifest_path} - models not trained yet")
            self.is_trained = False
            return False
        
        try:
            with open(manifest_path, 'r') as f:
                self.manifest = json.load(f)
            
            logger.info(f"Loading V2 models from {model_dir}")
            logger.info(f"  Version: {self.manifest.get('version')}")
            logger.info(f"  Trained: {self.manifest.get('trained_at')}")
            logger.info(f"  Architecture: {self.manifest.get('architecture', 'unknown')}")
            
            with open(model_dir / 'ridge_model.pkl', 'rb') as f:
                self.ridge_model = pickle.load(f)
            
            cal_file = CAL_DIR / 'global.pkl'
            if cal_file.exists():
                with open(cal_file, 'rb') as f:
                    self.iso_calibrators = pickle.load(f)
                logger.info(f"  Loaded global calibrators")
            
            self.is_trained = True
            logger.info("✓ V2 ridge model loaded successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error loading V2 models: {e}")
            self.is_trained = False
            return False
