"""
V2 Prediction Model - Enhanced Two-Step Draw + GBM + Meta-Learner
Production model with trained classifiers and per-league calibration
"""

import numpy as np
from typing import Dict, List, Tuple, Optional
import logging
import pickle
import json
from pathlib import Path
import lightgbm as lgb

logger = logging.getLogger(__name__)

MODEL_DIR = Path('models/v2')
CAL_DIR = MODEL_DIR / 'calibration'

FEATURES = [
    'prob_home', 'prob_draw', 'prob_away',
    'overround', 'book_dispersion',
    'drift_24h_home', 'drift_24h_draw', 'drift_24h_away',
]

class V2Predictor:
    """
    V2 Model: Two-step draw classifier + GBM + meta-learner with calibration
    
    Architecture:
    1. Draw classifier: Binary model for Draw vs Not-Draw
    2. Win classifier: Binary model for Home vs Away (given Not-Draw)
    3. GBM multiclass: Full 3-way prediction
    4. Meta-learner: Combines all three predictions
    5. Per-league isotonic calibration (fallback: global)
    """
    
    def __init__(self):
        self.model_version = "v2"
        self.is_trained = False
        self.draw_model = None
        self.win_model = None
        self.gbm_model = None
        self.meta_model = None
        self.calibrators = {}
        self.manifest = None
        
    def predict(self, features: Dict) -> Tuple[float, float, float, str]:
        """
        Generate V2 predictions
        
        Args:
            features: Dict with keys prob_home, prob_draw, prob_away, 
                     book_dispersion, drift_24h_*, form5_*, elo_delta, etc.
        
        Returns:
            (p_home, p_draw, p_away, reason_code)
        """
        
        if not self.is_trained:
            return self._fallback_prediction(features)
        
        try:
            p_home, p_draw, p_away, reason = self._ensemble_predict(features)
            
            league_id = str(features.get('league_id', ''))
            if league_id in self.calibrators:
                p_home, p_draw, p_away = self._apply_calibration(
                    p_home, p_draw, p_away, league_id
                )
                reason = f"{reason}+CAL_LEAGUE_{league_id}"
            elif 'global' in self.calibrators:
                p_home, p_draw, p_away = self._apply_calibration(
                    p_home, p_draw, p_away, 'global'
                )
                reason = f"{reason}+CAL_GLOBAL_FALLBACK"
            else:
                reason = f"{reason}+NO_CALIBRATION"
            
            return p_home, p_draw, p_away, reason
            
        except Exception as e:
            logger.error(f"V2 prediction error: {e}")
            return self._fallback_prediction(features)
    
    def _fallback_prediction(self, features: Dict) -> Tuple[float, float, float, str]:
        """
        Fallback to market-implied probabilities when model unavailable
        Uses normalized market consensus from features
        """
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
    
    def _ensemble_predict(self, features: Dict) -> Tuple[float, float, float, str]:
        """
        Ensemble prediction combining draw classifier + win model + GBM
        
        1. p_draw = draw_classifier(x)
        2. p_home_given_not_draw = win_classifier(x)
        3. p_home_2step = (1 - p_draw) * p_home_given_not_draw
        4. p_away_2step = (1 - p_draw) * (1 - p_home_given_not_draw)
        5. [pH_gbm, pD_gbm, pA_gbm] = gbm(x)
        6. meta_logit([pH_2step, pD_2step, pA_2step, pH_gbm, pD_gbm, pA_gbm]) → final probs
        """
        
        X = self._extract_features(features)
        
        # Step 1: Draw classifier
        p_draw = self.draw_model.predict_proba(X)[0, 1]
        
        # Step 2: Win classifier
        p_home_given_not_draw = self.win_model.predict_proba(X)[0, 1]
        
        # Step 3: Two-step predictions
        p_home_2step = (1 - p_draw) * p_home_given_not_draw
        p_draw_2step = p_draw
        p_away_2step = (1 - p_draw) * (1 - p_home_given_not_draw)
        
        # Step 4: GBM multiclass
        gbm_probs = self.gbm_model.predict(X)[0]
        p_home_gbm, p_draw_gbm, p_away_gbm = gbm_probs
        
        # Step 5: Meta-learner
        X_meta = np.array([[
            p_home_2step, p_draw_2step, p_away_2step,
            p_home_gbm, p_draw_gbm, p_away_gbm
        ]])
        
        meta_probs = self.meta_model.predict_proba(X_meta)[0]
        p_home, p_draw, p_away = meta_probs
        
        # Determine reason code
        draw_dominant = p_draw_2step > max(p_home_2step, p_away_2step)
        gbm_dominant = abs(p_home_gbm - p_home_2step) > 0.1 or abs(p_away_gbm - p_away_2step) > 0.1
        
        if draw_dominant and p_draw > 0.3:
            reason = "RC_DRAW_2STEP_DOMINANT"
        elif gbm_dominant:
            reason = "RC_GBM_DOMINANT"
        else:
            reason = "RC_ENSEMBLE_BALANCED"
        
        return p_home, p_draw, p_away, reason
    
    def _apply_calibration(
        self, 
        p_home: float, 
        p_draw: float, 
        p_away: float, 
        league_key: str
    ) -> Tuple[float, float, float]:
        """
        Apply isotonic calibration with safety clamps
        Clamps to [0.02, 0.98] and renormalizes
        """
        
        calibrator = self.calibrators.get(league_key, {})
        
        if not calibrator:
            return p_home, p_draw, p_away
        
        try:
            # Apply isotonic calibrators
            p_home_cal = calibrator['home'].predict([p_home])[0]
            p_draw_cal = calibrator['draw'].predict([p_draw])[0]
            p_away_cal = calibrator['away'].predict([p_away])[0]
            
            # Safety clamps to prevent extreme predictions
            p_home_cal = np.clip(p_home_cal, 0.02, 0.98)
            p_draw_cal = np.clip(p_draw_cal, 0.02, 0.98)
            p_away_cal = np.clip(p_away_cal, 0.02, 0.98)
            
            # Renormalize
            total = p_home_cal + p_draw_cal + p_away_cal
            if total > 0:
                return p_home_cal/total, p_draw_cal/total, p_away_cal/total
            else:
                return p_home, p_draw, p_away
                
        except Exception as e:
            logger.error(f"Calibration error for league {league_key}: {e}")
            return p_home, p_draw, p_away
    
    def load_models(self, model_path: str = None):
        """
        Load trained V2 models and calibration artifacts
        
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
            # Load manifest
            with open(manifest_path, 'r') as f:
                self.manifest = json.load(f)
            
            logger.info(f"Loading V2 models from {model_dir}")
            logger.info(f"  Version: {self.manifest.get('version')}")
            logger.info(f"  Trained: {self.manifest.get('trained_at')}")
            
            # Load sklearn models
            with open(model_dir / 'draw_model.pkl', 'rb') as f:
                self.draw_model = pickle.load(f)
            
            with open(model_dir / 'win_model.pkl', 'rb') as f:
                self.win_model = pickle.load(f)
            
            with open(model_dir / 'meta_model.pkl', 'rb') as f:
                self.meta_model = pickle.load(f)
            
            # Load GBM
            self.gbm_model = lgb.Booster(model_file=str(model_dir / 'gbm_model.txt'))
            
            # Load calibrators
            cal_dir = model_dir / 'calibration'
            if cal_dir.exists():
                for cal_file in cal_dir.glob('*.pkl'):
                    league_key = cal_file.stem
                    with open(cal_file, 'rb') as f:
                        self.calibrators[league_key] = pickle.load(f)
                
                logger.info(f"  Loaded {len(self.calibrators)} calibrators")
            
            self.is_trained = True
            logger.info("✓ V2 models loaded successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error loading V2 models: {e}")
            self.is_trained = False
            return False
