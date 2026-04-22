"""
MultisportV3Predictor — NBA / NHL V3 Prediction Model

Provides a standard predict() interface matching V3 soccer:
  - predict(sport_key, event_id, home_team, away_team, game_date) → dict
  - Returns prob_home, prob_away, pick, confidence, features_used

Two-outcome model (H/A). No draw.
"""

import os
import json
import logging
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

import lightgbm as lgb
import numpy as np

from features.multisport_feature_builder import MultisportFeatureBuilder

logger = logging.getLogger(__name__)

SPORT_MODEL_DIRS = {
    'basketball_nba':       'artifacts/models/v3_basketball',
    'icehockey_nhl':        'artifacts/models/v3_hockey',
    'basketball_euroleague': 'artifacts/models/v3_basketball',   # fallback to NBA model
    'americanfootball_nfl':  'artifacts/models/v3_football',
}

_predictor_cache: Dict[str, 'MultisportV3Predictor'] = {}


def get_multisport_predictor(sport_key: str) -> Optional['MultisportV3Predictor']:
    """Get cached predictor; returns None if model not yet trained."""
    if sport_key not in _predictor_cache:
        try:
            _predictor_cache[sport_key] = MultisportV3Predictor(sport_key)
        except FileNotFoundError:
            logger.warning(f"No trained model found for {sport_key}")
            return None
        except Exception as e:
            logger.error(f"Failed to load predictor for {sport_key}: {e}")
            return None
    return _predictor_cache[sport_key]


class MultisportV3Predictor:

    VERSION = '3.0.0'

    def __init__(self, sport_key: str):
        self.sport_key = sport_key
        model_dir_key  = sport_key if sport_key in SPORT_MODEL_DIRS else 'basketball_nba'
        model_dir = Path(SPORT_MODEL_DIRS.get(model_dir_key, 'artifacts/models/v3_basketball'))

        model_path    = model_dir / 'lgbm_model.txt'
        features_path = model_dir / 'features.json'
        meta_path     = model_dir / 'metadata.json'

        if not model_path.exists():
            raise FileNotFoundError(f"No model at {model_path}")

        self.model = lgb.Booster(model_file=str(model_path))

        with open(features_path) as f:
            self.feature_names = json.load(f)

        with open(meta_path) as f:
            self.metadata = json.load(f)

        db_url = os.getenv('DATABASE_URL')
        if not db_url:
            raise RuntimeError("DATABASE_URL not set")
        self.feature_builder = MultisportFeatureBuilder(db_url)

        logger.info(
            f"MultisportV3Predictor loaded: {sport_key} | "
            f"{len(self.feature_names)} features | "
            f"acc={self.metadata.get('oof_metrics', {}).get('accuracy', 0):.3f}"
        )

    # ──────────────────────────────────────────────────────────────────────────

    def predict(
        self,
        sport_key: str,
        event_id: str,
        home_team: str,
        away_team: str,
        game_date,
        cutoff_dt: Optional[datetime] = None,
    ) -> Dict:
        """
        Returns:
          {
            prob_home, prob_away,
            pick ('H' or 'A'),
            recommended_bet (home/away team name),
            confidence,
            features_used,
            model_version,
            feature_values (dict)
          }
        """
        if cutoff_dt is None:
            cutoff_dt = datetime.now(timezone.utc)

        features = self.feature_builder.build_features(
            sport_key=sport_key,
            event_id=event_id,
            home_team=home_team,
            away_team=away_team,
            game_date=game_date,
            cutoff_dt=cutoff_dt,
        )

        x = np.array([[features.get(f, 0.0) for f in self.feature_names]], dtype=float)
        prob_home = float(self.model.predict(x)[0])
        prob_away = 1.0 - prob_home
        prob_home = max(min(prob_home, 0.99), 0.01)
        prob_away = 1.0 - prob_home

        pick        = 'H' if prob_home > prob_away else 'A'
        confidence  = max(prob_home, prob_away)
        rec_bet     = home_team if pick == 'H' else away_team

        non_zero = sum(1 for v in features.values() if v != 0.0)

        # ── Production-validated confidence adjustments (NBA/NHL) ──
        spread = abs(features.get('spread_line', 0.0))
        total  = features.get('total_line', 0.0)
        is_favourite = (pick == 'H' and prob_home >= prob_away) or (pick == 'A' and prob_away > prob_home)
        is_away_pick = (pick == 'A')

        # 1. Spread-based confidence scaling (95% acc at spread>10, 41% at spread≤5)
        if spread > 10:
            confidence = max(confidence, 0.88)  # Floor at 88% for big spreads
        elif spread <= 5:
            confidence = min(confidence, 0.65)  # Cap at 65% for close games

        # 2. Underdog picks: cap confidence (29.2% accuracy when contrarian)
        if not is_favourite:
            confidence = min(confidence, 0.58)

        # 3. Away pick penalty (60.7% vs 87.7% home)
        if is_away_pick and spread <= 5:
            confidence *= 0.85  # Reduce confidence for away picks in close games

        # 4. High total line boost (>230 → 79.7% accuracy)
        if total > 230:
            confidence = min(confidence * 1.05, 0.98)

        # 5. Conviction tier
        if confidence >= 0.85 and spread > 8:
            conviction = 'premium'
        elif confidence >= 0.70:
            conviction = 'strong'
        else:
            conviction = 'standard'

        return {
            'prob_home':       round(prob_home, 4),
            'prob_away':       round(prob_away, 4),
            'pick':            pick,
            'recommended_bet': rec_bet,
            'confidence':      round(confidence, 4),
            'features_used':   non_zero,
            'total_features':  len(self.feature_names),
            'model_version':   self.VERSION,
            'model_type':      'V3_Multisport_LightGBM',
            'sport_key':       sport_key,
            'conviction_tier': conviction,
            'spread_magnitude': round(spread, 1),
            'is_favourite_pick': is_favourite,
            'feature_values':  {k: round(float(v), 4) for k, v in features.items()},
        }

    def predict_from_features(self, features: Dict) -> Dict:
        """Predict directly from a pre-built feature dict (for batch/backtest use)."""
        x = np.array([[features.get(f, 0.0) for f in self.feature_names]], dtype=float)
        prob_home  = float(self.model.predict(x)[0])
        prob_away  = 1.0 - prob_home
        prob_home  = max(min(prob_home, 0.99), 0.01)
        prob_away  = 1.0 - prob_home
        pick       = 'H' if prob_home > prob_away else 'A'
        return {
            'prob_home':  round(prob_home, 4),
            'prob_away':  round(prob_away, 4),
            'pick':       pick,
            'confidence': round(max(prob_home, prob_away), 4),
        }

    @property
    def accuracy(self) -> float:
        return self.metadata.get('oof_metrics', {}).get('accuracy', 0.0)

    @property
    def logloss(self) -> float:
        return self.metadata.get('oof_metrics', {}).get('logloss', 1.0)

    def get_model_info(self) -> Dict:
        return {
            'sport_key':     self.sport_key,
            'version':       self.VERSION,
            'n_features':    len(self.feature_names),
            'n_samples':     self.metadata.get('n_samples', 0),
            'accuracy':      self.accuracy,
            'logloss':       self.logloss,
            'trained_at':    self.metadata.get('trained_at', ''),
            'top_features':  self.metadata.get('feature_importance', [])[:10],
        }
