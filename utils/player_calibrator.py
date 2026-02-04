"""
Player Probability Calibrator

Applies isotonic regression calibration to raw model probabilities
to correct for overconfidence in player scoring predictions.

Based on historical prediction vs outcome analysis showing:
- 60% predicted → 24.5% actual (catastrophic overconfidence)
- 50% predicted → 39.2% actual
- 40% predicted → 3.3% actual
"""

import os
import logging
import pickle
import numpy as np
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple
from sqlalchemy import create_engine, text

logger = logging.getLogger(__name__)

CALIBRATION_DIR = Path("artifacts/calibration")


class PlayerCalibrator:
    """
    Calibrates raw player scoring probabilities using isotonic regression.
    
    The calibration map is built from historical player parlay leg outcomes
    and applied to future predictions.
    """
    
    def __init__(self):
        self.db_url = os.getenv('DATABASE_URL')
        self.engine = create_engine(self.db_url, pool_pre_ping=True) if self.db_url else None
        self.calibration_map = None
        self.calibration_version = None
        self._load_calibration()
    
    def _load_calibration(self):
        """Load existing calibration map if available."""
        CALIBRATION_DIR.mkdir(parents=True, exist_ok=True)
        calibration_file = CALIBRATION_DIR / "player_isotonic_calibration.pkl"
        
        if calibration_file.exists():
            try:
                with open(calibration_file, 'rb') as f:
                    data = pickle.load(f)
                    self.calibration_map = data.get('calibrator')
                    self.calibration_version = data.get('version')
                    logger.info(f"Loaded player calibration v{self.calibration_version}")
            except Exception as e:
                logger.warning(f"Failed to load calibration: {e}")
    
    def build_calibration(self, min_samples: int = 500) -> Dict:
        """
        Build isotonic regression calibration from historical data.
        
        Returns statistics about the calibration.
        """
        if not self.engine:
            return {'error': 'No database connection'}
        
        with self.engine.connect() as conn:
            result = conn.execute(text("""
                SELECT 
                    model_prob,
                    CASE WHEN result = 'won' THEN 1 ELSE 0 END as outcome
                FROM player_parlay_legs
                WHERE result IN ('won', 'lost')
                AND model_prob IS NOT NULL
            """))
            
            data = result.fetchall()
        
        if len(data) < min_samples:
            return {
                'error': f'Insufficient samples: {len(data)} < {min_samples}',
                'samples': len(data)
            }
        
        model_probs = np.array([float(row.model_prob) for row in data])
        outcomes = np.array([row.outcome for row in data])
        
        from sklearn.isotonic import IsotonicRegression
        
        calibrator = IsotonicRegression(y_min=0.01, y_max=0.95, out_of_bounds='clip')
        calibrator.fit(model_probs, outcomes)
        
        version = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        
        CALIBRATION_DIR.mkdir(parents=True, exist_ok=True)
        calibration_file = CALIBRATION_DIR / "player_isotonic_calibration.pkl"
        
        with open(calibration_file, 'wb') as f:
            pickle.dump({
                'calibrator': calibrator,
                'version': version,
                'samples': len(data),
                'built_at': datetime.now(timezone.utc).isoformat()
            }, f)
        
        self.calibration_map = calibrator
        self.calibration_version = version
        
        buckets = self._compute_calibration_stats(model_probs, outcomes, calibrator)
        
        logger.info(f"Built player calibration v{version} from {len(data)} samples")
        
        return {
            'status': 'success',
            'version': version,
            'samples': len(data),
            'buckets': buckets
        }
    
    def _compute_calibration_stats(self, model_probs, outcomes, calibrator) -> list:
        """Compute before/after calibration statistics by probability bucket."""
        buckets = []
        thresholds = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7]
        
        for i, threshold in enumerate(thresholds):
            lower = thresholds[i-1] if i > 0 else 0
            upper = threshold
            
            mask = (model_probs >= lower) & (model_probs < upper)
            if mask.sum() == 0:
                continue
            
            bucket_probs = model_probs[mask]
            bucket_outcomes = outcomes[mask]
            
            avg_raw = float(bucket_probs.mean())
            actual_rate = float(bucket_outcomes.mean())
            avg_calibrated = float(calibrator.predict(bucket_probs).mean())
            
            buckets.append({
                'range': f'{lower*100:.0f}-{upper*100:.0f}%',
                'count': int(mask.sum()),
                'raw_prob': round(avg_raw * 100, 1),
                'actual_rate': round(actual_rate * 100, 1),
                'calibrated_prob': round(avg_calibrated * 100, 1),
                'improvement': round(abs(actual_rate - avg_calibrated) - abs(actual_rate - avg_raw), 3)
            })
        
        return buckets
    
    def calibrate(self, raw_prob: float) -> float:
        """
        Calibrate a raw model probability.
        
        If no calibration available, applies a conservative scaling factor
        based on observed historical overconfidence.
        """
        if self.calibration_map is not None:
            try:
                calibrated = self.calibration_map.predict([[raw_prob]])[0]
                return float(np.clip(calibrated, 0.01, 0.95))
            except Exception as e:
                logger.warning(f"Calibration predict failed: {e}")
        
        if raw_prob >= 0.5:
            calibrated = raw_prob * 0.45
        elif raw_prob >= 0.3:
            calibrated = raw_prob * 0.50
        else:
            calibrated = raw_prob * 0.60
        
        return float(np.clip(calibrated, 0.01, 0.50))
    
    def get_status(self) -> Dict:
        """Get calibration status."""
        return {
            'calibrated': self.calibration_map is not None,
            'version': self.calibration_version,
            'method': 'isotonic_regression' if self.calibration_map else 'fallback_scaling'
        }


_calibrator_instance = None

def get_calibrator() -> PlayerCalibrator:
    """Get singleton calibrator instance."""
    global _calibrator_instance
    if _calibrator_instance is None:
        _calibrator_instance = PlayerCalibrator()
    return _calibrator_instance


def calibrate_probability(raw_prob: float) -> float:
    """Convenience function to calibrate a probability."""
    return get_calibrator().calibrate(raw_prob)


def build_calibration(min_samples: int = 500) -> Dict:
    """Convenience function to build calibration."""
    return get_calibrator().build_calibration(min_samples)
