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
from typing import Dict, Optional, Tuple
from functools import lru_cache

import sys
sys.path.append('.')
from features.v3_feature_builder import V3FeatureBuilder
from features.historical_odds_adapter import SPECIALIST_FEATURE_NAMES
from utils.league_calibration import (
    apply_league_calibration, compute_should_surface,
    LEAGUE_CONFIDENCE_MULTIPLIERS,
)

logger = logging.getLogger(__name__)

# Specialist cascade rule:
# Backtest showed strict overrides (conf > 0.50) never fired but specialist was
# +14pp more accurate than main on disagreements regardless of confidence.
# Strategy: when specialist disagrees, FLAG the match as 'uncertain' but still
# display main's pick. Frontend can use the flag to suppress from premium tier.
SPECIALIST_DISAGREEMENT_BEHAVIOR = 'flag_uncertain'  # 'flag_uncertain' | 'override' | 'ignore'


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
        self.specialists = {}  # league_id -> {'models': [...], 'features': [...], 'metadata': {}}
        self._load_model()
        self._init_feature_builder()
        self._load_specialists()

    def _load_specialists(self):
        """Load all available league specialist models."""
        artifacts_dir = Path("artifacts/models")
        if not artifacts_dir.exists():
            return

        for path in artifacts_dir.glob("v3_sharp_specialist_*"):
            try:
                # Parse league_id from directory name
                league_id = int(path.name.split("_")[-1])
                meta_path = path / "metadata.json"
                if not meta_path.exists():
                    continue
                with open(meta_path) as f:
                    meta = json.load(f)
                if not meta.get('gate_passed'):
                    logger.info(f"  Skipping specialist {league_id}: gate not passed")
                    continue
                with open(path / "lgbm_ensemble.pkl", "rb") as f:
                    models = pickle.load(f)
                with open(path / "features.json") as f:
                    features = json.load(f)
                self.specialists[league_id] = {
                    'models': models,
                    'features': features,
                    'metadata': meta,
                }
                logger.info(f"✅ Loaded specialist for league {league_id} ({meta.get('league_code', '?')}): "
                           f"holdout {meta.get('holdout_metrics', {}).get('accuracy', 0)*100:.1f}%")
            except Exception as e:
                logger.warning(f"Failed to load specialist from {path}: {e}")

        if self.specialists:
            logger.info(f"✅ Total specialists loaded: {len(self.specialists)}")

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

    def _run_main_model(self, features: Dict) -> Tuple[Dict[str, float], float, str]:
        """Run main V3 model. Returns (probs, confidence, prediction)."""
        feature_vector = np.array([
            features.get(col, np.nan) for col in self.feature_cols
        ]).reshape(1, -1)
        all_preds = [m.predict(feature_vector, num_iteration=m.best_iteration) for m in self.models]
        ensemble_preds = np.mean(all_preds, axis=0)[0]
        total = sum(ensemble_preds)
        if total <= 0:
            h, d, a = 1/3, 1/3, 1/3
        else:
            h, d, a = ensemble_preds[0]/total, ensemble_preds[1]/total, ensemble_preds[2]/total
        probs = {'home': float(h), 'draw': float(d), 'away': float(a)}
        return probs, max(probs.values()), max(probs, key=probs.get)

    def _run_specialist(self, league_id: int, features: Dict) -> Optional[Tuple[Dict[str, float], float, str]]:
        """Run specialist model if available for this league.
        Returns (probs, confidence, prediction) or None if no specialist."""
        spec = self.specialists.get(league_id)
        if not spec:
            return None
        try:
            feature_vector = np.array([
                features.get(col, np.nan) for col in spec['features']
            ]).reshape(1, -1)
            all_preds = [m.predict(feature_vector, num_iteration=m.best_iteration) for m in spec['models']]
            ensemble_preds = np.mean(all_preds, axis=0)[0]
            total = sum(ensemble_preds)
            if total <= 0:
                return None
            h, d, a = ensemble_preds[0]/total, ensemble_preds[1]/total, ensemble_preds[2]/total
            probs = {'home': float(h), 'draw': float(d), 'away': float(a)}
            return probs, max(probs.values()), max(probs, key=probs.get)
        except Exception as e:
            logger.warning(f"Specialist for league {league_id} failed: {e}")
            return None

    def predict(self, match_id: int) -> Optional[Dict]:
        """
        Generate V3 prediction with specialist cascade + league calibration + should_surface.

        Cascade:
        1. Run main V3 (always)
        2. If league has specialist AND specialist disagrees with main AND specialist
           confidence > 0.50 AND > main confidence + 5pp → use specialist (contrarian signal)
        3. Apply per-league confidence multiplier
        4. Compute should_surface flag based on pick type and confidence

        Returns:
            {
                'probabilities': {home, draw, away},
                'confidence': calibrated max probability,
                'raw_confidence': uncalibrated max probability,
                'prediction': 'home' | 'draw' | 'away',
                'model': 'v3_sharp' or 'v3_specialist',
                'specialist_check': { ... },  # always present
                'should_surface': bool,
                'surface_reason': str,
                'league_multiplier': float,
                'features_used': count,
                'total_features': total,
                'dispersions': {...},
                'bookmaker_count': int,
            }
        """
        try:
            features = self.feature_builder.build_features(match_id)
            non_nan_features = sum(
                1 for v in features.values()
                if v is not None and not (isinstance(v, float) and np.isnan(v))
            )

            # Get league_id for cascade decision
            try:
                import psycopg2
                conn = psycopg2.connect(os.environ.get('DATABASE_URL'), connect_timeout=5)
                cur = conn.cursor()
                cur.execute("SELECT league_id FROM fixtures WHERE match_id = %s", (match_id,))
                row = cur.fetchone()
                league_id = row[0] if row else None
                cur.close(); conn.close()
            except Exception:
                league_id = None

            # 1. Run main V3
            main_probs, main_conf, main_pick = self._run_main_model(features)

            # 2. Run specialist if available
            specialist_probs = None
            specialist_conf = None
            specialist_pick = None
            specialist_used = False
            specialist_check = {
                'league_id': league_id,
                'specialist_available': league_id in self.specialists,
                'specialist_used': False,
                'main_pick': main_pick,
                'main_conf': round(main_conf, 4),
            }

            uncertain_disagreement = False
            if league_id and league_id in self.specialists:
                spec_result = self._run_specialist(league_id, features)
                if spec_result:
                    specialist_probs, specialist_conf, specialist_pick = spec_result
                    specialist_check['specialist_pick'] = specialist_pick
                    specialist_check['specialist_conf'] = round(specialist_conf, 4)
                    specialist_check['agreement'] = specialist_pick == main_pick

                    if specialist_pick != main_pick:
                        uncertain_disagreement = True
                        specialist_check['disagreement'] = True
                        specialist_check['note'] = "Models disagree — flagged uncertain"

            # 3. Always use main pick. Specialist DISAGREEMENT is a signal to flag,
            #    not to override (backtest showed override hurts accuracy).
            probs = main_probs
            pick = main_pick
            raw_confidence = main_conf
            model_id = 'v3_sharp'

            # 4. Apply league calibration to confidence
            calibrated_conf, multiplier = apply_league_calibration(raw_confidence, league_id or 0)

            # 5. should_surface flag — also suppress on specialist disagreement
            should_surface, surface_reason = compute_should_surface(pick, calibrated_conf, probs)
            if uncertain_disagreement and should_surface:
                should_surface = False
                surface_reason = "specialist_disagreement"

            # Calibration data for downstream confidence calc
            dispersions = {
                'home': features.get('book_dispersion_home', 0.0),
                'draw': features.get('book_dispersion_draw', 0.0),
                'away': features.get('book_dispersion_away', 0.0),
            }
            book_coverage = features.get('book_coverage', 0)
            bookmaker_count = int(book_coverage) if book_coverage and not (isinstance(book_coverage, float) and np.isnan(book_coverage)) else 0

            return {
                'probabilities': probs,
                'confidence': calibrated_conf,
                'calibrated_confidence': calibrated_conf,  # explicit alias for /predict response
                'raw_confidence': raw_confidence,
                'prediction': pick,
                'model': model_id,
                'specialist_check': specialist_check,
                'should_surface': should_surface,
                'surface_reason': surface_reason,
                'league_multiplier': multiplier,
                'features_used': non_nan_features,
                'total_features': len(self.feature_cols),
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
