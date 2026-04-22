"""
V3 LightGBM Prediction Service - Draw-Enhanced Model

Loads trained V3 model with 24 features:
- V2 Core (11): Market probabilities, dispersion, volatility, coverage, overround
- League ECE (3): Expected Calibration Error, tier weights, historical edge
- H2H Draw (2): Historical draw rate, matches used
- Match Closeness (4): Prob gap, favourite strength, draw ratio, competitiveness
- League Draw Context (2): League draw rate, deviation from average
- Draw Market Structure (2): Draw dispersion ratio, draw overround share

Usage:
    from models.v3_predictor import get_v3_predictor
    predictor = get_v3_predictor()
    result = predictor.predict(match_id=12345)
"""

import os
import json
import pickle
import logging
import numpy as np
from pathlib import Path
from typing import Dict, Optional
from functools import lru_cache

import sys
sys.path.append('.')
from features.v3_feature_builder import V3FeatureBuilder

logger = logging.getLogger(__name__)


class V3Predictor:
    """
    V3 LightGBM prediction service - Draw-Enhanced Edition

    Features:
    - 24-feature pipeline (pruned dead features, added draw-specific signals)
    - Class-weighted training for better draw prediction
    - np.nan for missing features (LightGBM native handling)
    - Confidence-calibrated predictions
    - Graceful fallback when features unavailable
    """

    def __init__(self, model_dir: str = "artifacts/models/v3_sharp"):
        self.model_dir = Path(model_dir)
        self.models = None
        self.feature_cols = None
        self.metadata = None
        self.feature_builder = None
        self._load_model()
        self._init_feature_builder()

    def _load_model(self):
        """Load trained V3 LightGBM ensemble"""
        try:
            model_path = self.model_dir / "lgbm_ensemble.pkl"
            with open(model_path, "rb") as f:
                self.models = pickle.load(f)

            features_path = self.model_dir / "features.json"
            with open(features_path) as f:
                self.feature_cols = json.load(f)

            metadata_path = self.model_dir / "metadata.json"
            with open(metadata_path) as f:
                self.metadata = json.load(f)

            metrics = self.metadata.get('oof_metrics', {})
            logger.info(f"✅ V3 LightGBM loaded: {len(self.models)} models, "
                       f"{len(self.feature_cols)} features, "
                       f"{metrics.get('accuracy_3way', 0)*100:.1f}% accuracy")

            # Log draw-specific metrics if available
            draw_f1 = metrics.get('draw_f1')
            if draw_f1 is not None:
                logger.info(f"   Draw F1: {draw_f1*100:.1f}%, "
                           f"Precision: {metrics.get('draw_precision', 0)*100:.1f}%, "
                           f"Recall: {metrics.get('draw_recall', 0)*100:.1f}%")

        except FileNotFoundError:
            logger.warning("⚠️  V3 model not found - train with training/train_v3_sharp.py")
            raise RuntimeError("V3 model not available - run training first")
        except Exception as e:
            logger.error(f"❌ Failed to load V3 LightGBM: {e}")
            raise

    def _init_feature_builder(self):
        """Initialize V3 feature builder"""
        try:
            self.feature_builder = V3FeatureBuilder()
            logger.info("✅ V3 Feature Builder initialized")
        except Exception as e:
            logger.error(f"❌ Feature builder initialization failed: {e}")
            raise

    def predict(self, match_id: int) -> Optional[Dict]:
        """
        Generate V3 prediction for a match

        Args:
            match_id: Match ID to predict

        Returns:
            {
                'probabilities': {home, draw, away},
                'confidence': max probability,
                'prediction': 'home' | 'draw' | 'away',
                'model': 'v3_sharp',
                'features_used': count of non-NaN features,
                'total_features': total feature count
            }
        """
        try:
            features = self.feature_builder.build_features(match_id)

            # Count non-NaN features (use np.nan awareness)
            non_nan_features = sum(
                1 for v in features.values()
                if v is not None and not (isinstance(v, float) and np.isnan(v))
            )

            # Build feature vector — np.nan for missing (LightGBM handles natively)
            feature_vector = np.array([
                features.get(col, np.nan) for col in self.feature_cols
            ]).reshape(1, -1)

            all_preds = []
            for model in self.models:
                preds = model.predict(feature_vector, num_iteration=model.best_iteration)
                all_preds.append(preds)

            ensemble_preds = np.mean(all_preds, axis=0)[0]

            total = sum(ensemble_preds)
            if total <= 0:
                h, d, a = 1/3, 1/3, 1/3
            else:
                h, d, a = ensemble_preds[0]/total, ensemble_preds[1]/total, ensemble_preds[2]/total

            probs = {'home': float(h), 'draw': float(d), 'away': float(a)}

            # REVERTED: draw boost was causing over-prediction of draws in production.
            # Training already uses class-weighted samples (draws ~1.2x), so no
            # inference-time boost is needed. Use raw argmax.
            prediction = max(probs, key=probs.get)
            raw_confidence = max(probs.values())

            # Extract calibration data from features for confidence calibration
            dispersions = {
                'home': features.get('book_dispersion_home', 0.0),
                'draw': features.get('book_dispersion_draw', 0.0),
                'away': features.get('book_dispersion_away', 0.0),
            }
            book_coverage = features.get('book_coverage', 0)
            bookmaker_count = int(book_coverage) if book_coverage and not (isinstance(book_coverage, float) and np.isnan(book_coverage)) else 0

            return {
                'probabilities': probs,
                'confidence': raw_confidence,
                'raw_confidence': raw_confidence,
                'prediction': prediction,
                'model': 'v3_sharp',
                'features_used': non_nan_features,
                'total_features': len(self.feature_cols),
                # Calibration data for compute_unified_confidence()
                'dispersions': dispersions,
                'bookmaker_count': bookmaker_count,
            }

        except Exception as e:
            logger.error(f"V3 prediction failed for match {match_id}: {e}")
            return None

    def get_model_info(self) -> Dict:
        """Get model metadata and performance info"""
        metrics = self.metadata.get('oof_metrics', {})
        return {
            'model_type': self.metadata.get('model_type', 'V3_Sharp_LightGBM'),
            'n_features': len(self.feature_cols),
            'n_models': len(self.models) if self.models else 0,
            'metrics': metrics,
            'trained_at': self.metadata.get('trained_at'),
            'training_window_start': self.metadata.get('training_window_start'),
            'improvements': self.metadata.get('improvements', []),
            'feature_categories': {
                'v2_core': 11,
                'league_ece': 3,
                'h2h_draw': 2,
                'match_closeness': 4,
                'league_draw_context': 2,
                'draw_market_structure': 2,
            }
        }


_predictor = None


@lru_cache(maxsize=1)
def get_v3_predictor() -> V3Predictor:
    """Get singleton V3 predictor instance"""
    global _predictor
    if _predictor is None:
        _predictor = V3Predictor()
    return _predictor
