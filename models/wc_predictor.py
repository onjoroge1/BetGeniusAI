"""
WC Predictor — serves international-match predictions for World Cup 2026.

Decision (from training/train_wc_model.py temporal holdout): pure national-team
ELO beats both a trained LightGBM layer and the majority baseline (61.2% vs
58.8% vs 45.9%). So we serve ELO directly — honest, no noise layer.

This is the international counterpart to the club cascade. It is NOT market-
derived (unlike V3), so it works even before WC odds are liquid.

Usage:
  from models.wc_predictor import WCPredictor
  wc = WCPredictor()                       # loads ratings from national_team_elo
  wc.predict(home_id=9, away_id=6, neutral=True)
  wc.predict_by_name("Spain", "Argentina", neutral=True)
"""

import os
import logging
from typing import Dict, Optional

from models.national_elo import NationalEloModel

logger = logging.getLogger(__name__)

# WC + qualifier + continental league IDs this predictor is authoritative for
INTERNATIONAL_LEAGUE_IDS = {1, 4, 5, 6, 9, 10, 29, 30, 31, 32, 33, 34}

_CANON = {"home": "home_win", "draw": "draw", "away": "away_win"}


class WCPredictor:
    def __init__(self):
        self.elo = NationalEloModel()
        try:
            self.elo.load_ratings()
            self.available = len(self.elo.elos) > 0
            # name -> id lookup (case-insensitive)
            self._by_name = {n.lower(): tid for tid, n in self.elo.names.items()}
            logger.info(f"✅ WCPredictor loaded {len(self.elo.elos)} national-team ratings")
        except Exception as e:
            logger.warning(f"WCPredictor unavailable: {e}")
            self.available = False
            self._by_name = {}

    def is_available(self) -> bool:
        return self.available

    @staticmethod
    def is_international(league_id: Optional[int]) -> bool:
        return league_id in INTERNATIONAL_LEAGUE_IDS

    def predict(self, home_id: int, away_id: int, neutral: bool = True) -> Optional[Dict]:
        """Return a prediction dict in the same shape the cascade expects."""
        if not self.available:
            return None
        if home_id not in self.elo.elos and away_id not in self.elo.elos:
            logger.info(f"WC: neither team {home_id}/{away_id} has an ELO rating")
            return None

        probs = self.elo.predict_proba(home_id, away_id, neutral=neutral)
        pick = max(probs, key=probs.get)
        confidence = probs[pick]
        eh, ea = self.elo._get(home_id), self.elo._get(away_id)

        return {
            "probabilities": probs,
            "prediction": pick,                       # 'home'|'draw'|'away'
            "recommended_bet": _CANON.get(pick, pick),
            "confidence": round(confidence, 4),
            "calibrated_confidence": round(confidence, 4),
            "model_type": "wc_elo",
            "data_source": "national_team_elo",
            "elo_home": round(eh, 1),
            "elo_away": round(ea, 1),
            "elo_diff": round(eh - ea, 1),
            "neutral_venue": neutral,
            # honest provenance: this is a non-market strength model, not a market echo
            "note": "National-team ELO (holdout 61.2% vs 45.9% baseline). Not odds-derived.",
        }

    def predict_by_name(self, home: str, away: str, neutral: bool = True) -> Optional[Dict]:
        hid = self._by_name.get(home.lower())
        aid = self._by_name.get(away.lower())
        if hid is None or aid is None:
            logger.warning(f"WC: unknown team name(s): {home!r}={hid}, {away!r}={aid}")
            return None
        return self.predict(hid, aid, neutral=neutral)


# Lazy singleton for the cascade
_wc_predictor: Optional[WCPredictor] = None

def get_wc_predictor() -> WCPredictor:
    global _wc_predictor
    if _wc_predictor is None:
        _wc_predictor = WCPredictor()
    return _wc_predictor


if __name__ == "__main__":
    import re, logging as _l
    from pathlib import Path
    REPO = Path(__file__).parent.parent
    for ef in [".env.local", ".env"]:
        p = REPO / ef
        if p.exists():
            for line in p.read_text().splitlines():
                m = re.match(r"^([^#=\s][^=]*)=(.*)$", line)
                if m and not os.environ.get(m.group(1).strip()):
                    os.environ[m.group(1).strip()] = m.group(2).strip()
            break
    _l.basicConfig(level=_l.INFO, format="%(message)s")
    wc = WCPredictor()
    for h, a in [("Spain", "Argentina"), ("Brazil", "Germany"),
                 ("France", "England"), ("USA", "Canada"), ("Morocco", "Portugal")]:
        r = wc.predict_by_name(h, a, neutral=True)
        if r:
            p = r["probabilities"]
            print(f"\n{h} vs {a} (neutral):")
            print(f"  ELO {r['elo_home']:.0f} vs {r['elo_away']:.0f}  (diff {r['elo_diff']:+.0f})")
            print(f"  P(home)={p['home']:.0%}  P(draw)={p['draw']:.0%}  P(away)={p['away']:.0%}")
            print(f"  → {r['prediction'].upper()} @ {r['confidence']:.0%}")
