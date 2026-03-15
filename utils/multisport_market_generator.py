"""
MultisportMarketGenerator — Sport-specific betting markets for NBA / NHL

Generates 5 market types, each option includes:
  model_prob, implied_prob, decimal_odds, edge

  1. Moneyline        — Model H/A probs vs market implied
  2. Spread           — Point spread / puck line with edge
  3. Game Total O/U   — Total points/goals over/under
  4. First Half Total — Derived as fraction of game total
  5. Team Totals      — Per-team scoring projection from season PPG
"""

import logging
import math
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

FIRST_HALF_FRACTION = {
    "basketball_nba": 0.49,
    "icehockey_nhl": 0.51,
}

SPORT_LABELS = {
    "basketball_nba": {"spread": "Point Spread", "total": "Game Total", "unit": "points"},
    "icehockey_nhl": {"spread": "Puck Line", "total": "Game Total", "unit": "goals"},
}


class MultisportMarketGenerator:

    def generate_markets(
        self,
        sport_key: str,
        prediction: Dict,
        odds: Dict,
        home_stats: Dict,
        away_stats: Dict,
    ) -> List[Dict]:
        markets = []

        markets.append(self._moneyline(sport_key, prediction, odds))
        markets.append(self._spread(sport_key, prediction, odds))
        markets.append(self._game_total(sport_key, prediction, odds, home_stats, away_stats))
        markets.append(self._first_half_total(sport_key, prediction, odds, home_stats, away_stats))
        markets.append(self._team_totals(sport_key, prediction, home_stats, away_stats, odds))

        return [m for m in markets if m is not None]

    def _moneyline(self, sport_key: str, prediction: Dict, odds: Dict) -> Dict:
        prob_home = prediction.get("prob_home", 0.5)
        prob_away = prediction.get("prob_away", 0.5)

        mkt_home = odds.get("home_prob")
        mkt_away = odds.get("away_prob")

        home_edge = round(prob_home - (mkt_home or prob_home), 4) if mkt_home else None
        away_edge = round(prob_away - (mkt_away or prob_away), 4) if mkt_away else None

        return {
            "market": "Moneyline",
            "type": "moneyline",
            "options": [
                {
                    "label": "Home Win",
                    "model_prob": round(prob_home, 4),
                    "implied_prob": round(mkt_home, 4) if mkt_home else None,
                    "decimal_odds": round(odds.get("home_odds", 0), 3) if odds.get("home_odds") else None,
                    "edge": home_edge,
                },
                {
                    "label": "Away Win",
                    "model_prob": round(prob_away, 4),
                    "implied_prob": round(mkt_away, 4) if mkt_away else None,
                    "decimal_odds": round(odds.get("away_odds", 0), 3) if odds.get("away_odds") else None,
                    "edge": away_edge,
                },
            ],
        }

    def _spread(self, sport_key: str, prediction: Dict, odds: Dict) -> Optional[Dict]:
        spread = odds.get("home_spread")
        if spread is None:
            return None

        labels = SPORT_LABELS.get(sport_key, SPORT_LABELS["basketball_nba"])

        home_sp_odds = odds.get("home_spread_odds")
        away_sp_odds = odds.get("away_spread_odds")

        home_implied = self._odds_to_prob(home_sp_odds) if home_sp_odds else 0.5
        away_implied = self._odds_to_prob(away_sp_odds) if away_sp_odds else 0.5

        model_home_cover = prediction.get("prob_home", 0.5)
        if abs(spread) > 0:
            adjustment = min(abs(spread) * 0.02, 0.10)
            if spread < 0:
                model_home_cover = max(0.01, model_home_cover - adjustment)
            else:
                model_home_cover = min(0.99, model_home_cover + adjustment)

        return {
            "market": labels["spread"],
            "type": "spread",
            "line": spread,
            "options": [
                {
                    "label": f"Home {spread:+.1f}",
                    "model_prob": round(model_home_cover, 4),
                    "implied_prob": round(home_implied, 4),
                    "decimal_odds": round(home_sp_odds, 3) if home_sp_odds else None,
                    "edge": round(model_home_cover - home_implied, 4),
                },
                {
                    "label": f"Away {-spread:+.1f}",
                    "model_prob": round(1 - model_home_cover, 4),
                    "implied_prob": round(away_implied, 4),
                    "decimal_odds": round(away_sp_odds, 3) if away_sp_odds else None,
                    "edge": round((1 - model_home_cover) - away_implied, 4),
                },
            ],
        }

    def _game_total(self, sport_key: str, prediction: Dict, odds: Dict,
                    home_stats: Dict, away_stats: Dict) -> Optional[Dict]:
        total = odds.get("total_line")
        if total is None:
            return None

        over_odds = odds.get("over_odds")
        under_odds = odds.get("under_odds")

        over_implied = self._odds_to_prob(over_odds) if over_odds else 0.5
        under_implied = self._odds_to_prob(under_odds) if under_odds else 0.5

        home_ppg = home_stats.get("points_per_game", 0) or 0
        away_ppg = away_stats.get("points_per_game", 0) or 0
        expected_total = home_ppg + away_ppg

        if expected_total > 0:
            model_over = 0.5 + min(max((expected_total - total) * 0.03, -0.20), 0.20)
        else:
            model_over = 0.5

        model_under = 1.0 - model_over

        labels = SPORT_LABELS.get(sport_key, SPORT_LABELS["basketball_nba"])

        return {
            "market": labels["total"],
            "type": "total",
            "line": total,
            "options": [
                {
                    "label": f"Over {total}",
                    "model_prob": round(model_over, 4),
                    "implied_prob": round(over_implied, 4),
                    "decimal_odds": round(over_odds, 3) if over_odds else None,
                    "edge": round(model_over - over_implied, 4),
                },
                {
                    "label": f"Under {total}",
                    "model_prob": round(model_under, 4),
                    "implied_prob": round(under_implied, 4),
                    "decimal_odds": round(under_odds, 3) if under_odds else None,
                    "edge": round(model_under - under_implied, 4),
                },
            ],
        }

    def _first_half_total(self, sport_key: str, prediction: Dict, odds: Dict,
                          home_stats: Dict, away_stats: Dict) -> Optional[Dict]:
        total = odds.get("total_line")
        if total is None:
            return None

        frac = FIRST_HALF_FRACTION.get(sport_key, 0.49)
        fh_line = round(total * frac, 1)
        if sport_key == "icehockey_nhl":
            fh_line = round(fh_line * 2) / 2

        label = "1st Half Total" if sport_key == "basketball_nba" else "1st Period Total"

        home_ppg = home_stats.get("points_per_game", 0) or 0
        away_ppg = away_stats.get("points_per_game", 0) or 0
        expected_fh = (home_ppg + away_ppg) * frac

        if expected_fh > 0:
            model_over = 0.5 + min(max((expected_fh - fh_line) * 0.03, -0.15), 0.15)
        else:
            model_over = 0.5

        model_under = 1.0 - model_over

        over_odds_val = odds.get("over_odds")
        under_odds_val = odds.get("under_odds")
        fh_over_odds = round(over_odds_val * 1.02, 3) if over_odds_val else None
        fh_under_odds = round(under_odds_val * 1.02, 3) if under_odds_val else None

        fh_over_implied = self._odds_to_prob(fh_over_odds) if fh_over_odds else 0.5
        fh_under_implied = self._odds_to_prob(fh_under_odds) if fh_under_odds else 0.5

        return {
            "market": label,
            "type": "first_half_total",
            "line": fh_line,
            "derived_from": f"{frac:.0%} of game total {total}",
            "options": [
                {
                    "label": f"Over {fh_line}",
                    "model_prob": round(model_over, 4),
                    "implied_prob": round(fh_over_implied, 4),
                    "decimal_odds": fh_over_odds,
                    "edge": round(model_over - fh_over_implied, 4),
                },
                {
                    "label": f"Under {fh_line}",
                    "model_prob": round(model_under, 4),
                    "implied_prob": round(fh_under_implied, 4),
                    "decimal_odds": fh_under_odds,
                    "edge": round(model_under - fh_under_implied, 4),
                },
            ],
        }

    def _team_totals(
        self,
        sport_key: str,
        prediction: Dict,
        home_stats: Dict,
        away_stats: Dict,
        odds: Dict,
    ) -> Dict:
        total_line = odds.get("total_line")
        home_ppg = home_stats.get("points_per_game", 0) or 0
        away_ppg = away_stats.get("points_per_game", 0) or 0

        prob_home = prediction.get("prob_home", 0.5)
        prob_away = prediction.get("prob_away", 0.5)

        if total_line and home_ppg and away_ppg:
            ratio = home_ppg / max(home_ppg + away_ppg, 1)
            home_proj = round(total_line * ratio, 1)
            away_proj = round(total_line * (1 - ratio), 1)
        elif home_ppg and away_ppg:
            home_proj = home_ppg
            away_proj = away_ppg
        else:
            home_proj = None
            away_proj = None

        home_implied = round(1.0 / max(prob_home * 2, 0.01), 3) if prob_home else None
        away_implied = round(1.0 / max(prob_away * 2, 0.01), 3) if prob_away else None

        return {
            "market": "Team Totals",
            "type": "team_totals",
            "projections": {
                "home": {
                    "projected_total": home_proj,
                    "season_ppg": home_ppg,
                    "model_prob": round(prob_home, 4),
                    "implied_prob": round(prob_home, 4),
                    "decimal_odds": home_implied,
                    "edge": 0.0,
                },
                "away": {
                    "projected_total": away_proj,
                    "season_ppg": away_ppg,
                    "model_prob": round(prob_away, 4),
                    "implied_prob": round(prob_away, 4),
                    "decimal_odds": away_implied,
                    "edge": 0.0,
                },
            },
        }

    @staticmethod
    def _odds_to_prob(decimal_odds: float) -> float:
        if not decimal_odds or decimal_odds <= 1.0:
            return 0.5
        return round(1.0 / decimal_odds, 4)
