"""
Historical model predictor — wraps lgbm_historical_36k (50.7% OOF).

Builds the 46 expected features from odds_consensus data at inference time.
Features that can't be computed (ELO, volatility, form) use training-set means.
"""

import logging
import math
import pickle
from pathlib import Path
from typing import Dict, Optional

import numpy as np
import psycopg2

logger = logging.getLogger(__name__)

MODEL_DIR = Path("artifacts/models/lgbm_historical_36k")

# Feature order must match training exactly (from features.json)
FEATURE_NAMES = [
    "p_last_home", "p_last_draw", "p_last_away",
    "p_open_home", "p_open_draw", "p_open_away",
    "prob_drift_home", "prob_drift_draw", "prob_drift_away",
    "drift_magnitude",
    "dispersion_home", "dispersion_draw", "dispersion_away",
    "book_dispersion",
    "volatility_home", "volatility_draw", "volatility_away",
    "num_books_last", "num_snapshots", "coverage_hours",
    "home_elo", "away_elo", "elo_diff",
    "market_entropy", "favorite_margin",
    "home_form_points", "home_form_goals_scored", "home_form_goals_conceded",
    "away_form_points", "away_form_goals_scored", "away_form_goals_conceded",
    "home_last10_home_wins", "away_last10_away_wins",
    "h2h_home_wins", "h2h_draws", "h2h_away_wins",
    "adv_home_shots_avg", "adv_home_shots_target_avg",
    "adv_home_corners_avg", "adv_home_yellows_avg",
    "adv_away_shots_avg", "adv_away_shots_target_avg",
    "adv_away_corners_avg", "adv_away_yellows_avg",
    "days_since_home_last_match", "days_since_away_last_match",
]

# Training-set means for features we can't compute at inference time
_DEFAULTS = {
    "prob_drift_home": 0.0, "prob_drift_draw": 0.0, "prob_drift_away": 0.0,
    "drift_magnitude": 0.0,
    "volatility_home": 0.0, "volatility_draw": 0.0, "volatility_away": 0.0,
    "num_snapshots": 1.0, "coverage_hours": 0.0,
    "home_elo": 1500.0, "away_elo": 1500.0, "elo_diff": 0.0,
    "home_form_points": 1.34, "home_form_goals_scored": 1.33,
    "home_form_goals_conceded": 1.37,
    "away_form_points": 1.39, "away_form_goals_scored": 1.37,
    "away_form_goals_conceded": 1.33,
    "home_last10_home_wins": 4.27, "away_last10_away_wins": 2.85,
    "h2h_home_wins": 1.16, "h2h_draws": 0.86, "h2h_away_wins": 1.23,
    "adv_home_shots_avg": 11.87, "adv_home_shots_target_avg": 4.25,
    "adv_home_corners_avg": 4.76, "adv_home_yellows_avg": 2.08,
    "adv_away_shots_avg": 12.12, "adv_away_shots_target_avg": 4.34,
    "adv_away_corners_avg": 4.86, "adv_away_yellows_avg": 2.05,
    "days_since_home_last_match": 20.7, "days_since_away_last_match": 19.9,
}


class HistPredictor:
    """Secondary predictor using the 36k-row historical LightGBM model."""

    def __init__(self, model_dir: Optional[Path] = None):
        self.model_dir = model_dir or MODEL_DIR
        self.models = None
        self._load()

    def _load(self):
        ensemble_path = self.model_dir / "lgbm_ensemble.pkl"
        if not ensemble_path.exists():
            logger.warning(f"HistPredictor: model not found at {ensemble_path}")
            return
        with open(ensemble_path, "rb") as f:
            self.models = pickle.load(f)
        logger.info(f"✅ HistPredictor loaded ({len(self.models)} fold models, {len(FEATURE_NAMES)} features, 50.7% OOF)")

    def predict(self, match_id: int, db_url: str) -> Optional[Dict]:
        """
        Predict outcome probabilities using the historical model.

        Returns dict with 'home', 'draw', 'away' probabilities plus metadata,
        or None if odds data is unavailable.
        """
        if self.models is None:
            return None

        feats = self._build_features(match_id, db_url)
        if feats is None:
            return None

        x = np.array([[feats[f] for f in FEATURE_NAMES]], dtype=np.float64)

        fold_preds = []
        for model in self.models:
            preds = model.predict(x)
            fold_preds.append(preds[0])

        avg = np.mean(fold_preds, axis=0)
        avg /= avg.sum()

        h, d, a = float(avg[0]), float(avg[1]), float(avg[2])
        pick = ["home", "draw", "away"][int(np.argmax(avg))]
        conf = float(np.max(avg))

        return {
            "prediction": pick,
            "probabilities": {"home": h, "draw": d, "away": a},
            "confidence": conf,
            "model": "hist_36k",
            "features_used": sum(1 for f in FEATURE_NAMES if f not in _DEFAULTS or feats[f] != _DEFAULTS.get(f)),
        }

    def _build_features(self, match_id: int, db_url: str) -> Optional[Dict]:
        try:
            conn = psycopg2.connect(db_url)
            cursor = conn.cursor()

            # Get closing odds from odds_consensus (most recent row)
            cursor.execute("""
                SELECT ph_cons, pd_cons, pa_cons,
                       disph, dispd, dispa,
                       n_books, market_margin_avg
                FROM odds_consensus
                WHERE match_id = %s
                ORDER BY ts_effective DESC
                LIMIT 1
            """, (match_id,))
            row = cursor.fetchone()
            if not row or row[0] is None:
                cursor.close()
                conn.close()
                return None

            ph, pd_prob, pa, disph, dispd, dispa, n_books, margin = row

            # Get opening odds (earliest row in odds_consensus)
            cursor.execute("""
                SELECT ph_cons, pd_cons, pa_cons
                FROM odds_consensus
                WHERE match_id = %s
                ORDER BY ts_effective ASC
                LIMIT 1
            """, (match_id,))
            open_row = cursor.fetchone()
            cursor.close()
            conn.close()

            ph_open = open_row[0] if open_row and open_row[0] else ph
            pd_open = open_row[1] if open_row and open_row[1] else pd_prob
            pa_open = open_row[2] if open_row and open_row[2] else pa

        except Exception as e:
            logger.debug(f"HistPredictor._build_features({match_id}): DB error: {e}")
            return None

        feats = dict(_DEFAULTS)

        feats["p_last_home"] = float(ph)
        feats["p_last_draw"] = float(pd_prob)
        feats["p_last_away"] = float(pa)
        feats["p_open_home"] = float(ph_open)
        feats["p_open_draw"] = float(pd_open)
        feats["p_open_away"] = float(pa_open)

        feats["prob_drift_home"] = float(ph) - float(ph_open)
        feats["prob_drift_draw"] = float(pd_prob) - float(pd_open)
        feats["prob_drift_away"] = float(pa) - float(pa_open)
        feats["drift_magnitude"] = math.sqrt(
            feats["prob_drift_home"] ** 2 +
            feats["prob_drift_draw"] ** 2 +
            feats["prob_drift_away"] ** 2
        )

        feats["dispersion_home"] = float(disph) if disph is not None else 0.0
        feats["dispersion_draw"] = float(dispd) if dispd is not None else 0.0
        feats["dispersion_away"] = float(dispa) if dispa is not None else 0.0
        feats["book_dispersion"] = (feats["dispersion_home"] + feats["dispersion_draw"] + feats["dispersion_away"]) / 3

        feats["num_books_last"] = float(n_books) if n_books is not None else 3.0

        eps = 1e-9
        feats["market_entropy"] = -(
            ph * math.log(ph + eps) +
            pd_prob * math.log(pd_prob + eps) +
            pa * math.log(pa + eps)
        )

        sorted_probs = sorted([ph, pd_prob, pa], reverse=True)
        feats["favorite_margin"] = sorted_probs[0] - sorted_probs[1]

        return feats
