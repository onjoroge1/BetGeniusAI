"""
Multisport edge assembly — pure helpers for the 2-way (no-draw) US sports
endpoints (/market-multisport, /predict-multisport/results).

Kept free of FastAPI/route imports so the test suite can exercise the exact
production assembly logic directly (same pattern as utils/edge.py for soccer).

Inputs mirror what routes/multisport_market.py already holds in memory:
  cons  : consensus row dict  {"home_odds","away_odds","home_prob","away_prob",
                               "n_bookmakers","overround",...}
  books : {bookmaker: {"home": odds|None, "away": odds|None, ...}}
  model : {"home_win": p, "away_win": p, "pick": "H"/"A", ...}

Honesty: model_track_record comes from the registry — all multisport models are
edge_validated=False until they pass a per-sport favorite-baseline holdout
(docs/MULTISPORT_EDGE_PLAN.md, Gate B).
"""

import logging
from typing import Dict, List, Optional

from utils.edge import (
    OUTCOMES_2WAY, build_value_payload, devig_proportional, ev_at_price,
    get_model_track_record, multisport_model_id,
)

logger = logging.getLogger(__name__)


def best_prices_from_books(books: Dict[str, dict]) -> Optional[Dict[str, dict]]:
    """Max home/away decimal odds across the per-book dict the route already has."""
    if not books:
        return None
    bp: Dict[str, dict] = {}
    for book, o in books.items():
        for k in OUTCOMES_2WAY:
            odds = o.get(k)
            if odds and odds > 1.0 and (k not in bp or odds > bp[k]["odds"]):
                bp[k] = {"odds": round(float(odds), 3), "book": book}
    return bp or None


def build_multisport_edge_blocks(cons: Optional[dict], books: Optional[dict],
                                 model: Optional[dict], sport_key: str) -> Optional[dict]:
    """
    Assemble market/value/clv + model_track_record for one upcoming game.
    Returns None when there's no model prediction (nothing to price against);
    degrades to nullable market/value when consensus is missing.
    """
    if not model or model.get("home_win") is None:
        return None
    model_probs = {"home": float(model["home_win"]), "away": float(model["away_win"])}

    market_raw = None
    n_books = None
    if cons and cons.get("home_prob") and cons.get("away_prob"):
        market_raw = {"home": float(cons["home_prob"]), "away": float(cons["away_prob"])}
        n_books = cons.get("n_bookmakers")

    blocks = build_value_payload(
        model_probs, market_raw, best_prices_from_books(books or {}),
        n_books=n_books, outcomes=OUTCOMES_2WAY,
    )
    blocks["model_track_record"] = get_model_track_record(multisport_model_id(sport_key))
    return blocks


def edge_analysis_for_result(model: dict, cons: dict, result: str) -> Optional[dict]:
    """
    Per-finished-game edge record for /predict-multisport/results.
    Measures the pick the model made against the de-vigged market line and the
    realized 1-unit return at consensus odds — the edge-era replacement for the
    bare "correct: true/false".
    """
    if not model or not cons or result not in ("H", "A"):
        return None
    if not (cons.get("home_prob") and cons.get("away_prob")):
        return None

    try:
        fair = devig_proportional(
            {"home": float(cons["home_prob"]), "away": float(cons["away_prob"])},
            OUTCOMES_2WAY,
        )
    except ValueError:
        return None

    pick = model.get("pick", "H")
    pick_key = "home" if pick == "H" else "away"
    p_model = float(model["home_win"] if pick == "H" else model["away_win"])
    p_market = fair[pick_key]
    pick_odds = cons.get("home_odds" if pick == "H" else "away_odds")

    market_fav = "H" if fair["home"] >= fair["away"] else "A"
    won = (pick == result)
    realized = None
    ev_at_consensus = None
    if pick_odds and pick_odds > 1.0:
        realized = round((float(pick_odds) - 1.0) if won else -1.0, 4)
        ev_at_consensus = round(ev_at_price(p_model, float(pick_odds)), 4)

    return {
        "pick": pick,
        "model_prob": round(p_model, 4),
        "market_prob": round(p_market, 4),
        "model_market_gap": round(p_model - p_market, 4),
        "disagreed_with_market": pick != market_fav,
        "ev_at_consensus": ev_at_consensus,
        "won": won,
        "realized_return_1u": realized,
    }


def summarize_edge_metrics(analyses: List[dict]) -> Optional[dict]:
    """
    Aggregate edge metrics over a slate of finished games — the headline block
    for /predict-multisport/results (accuracy buckets become diagnostics).
    """
    rows = [a for a in analyses if a]
    if not rows:
        return None

    priced = [a for a in rows if a.get("realized_return_1u") is not None]
    dis = [a for a in rows if a["disagreed_with_market"]]
    gaps = sorted(a["model_market_gap"] for a in rows)
    mid = len(gaps) // 2
    median_gap = gaps[mid] if len(gaps) % 2 else 0.5 * (gaps[mid - 1] + gaps[mid])

    return {
        "n_games": len(rows),
        "n_priced": len(priced),
        "total_return_1u_at_consensus": round(sum(a["realized_return_1u"] for a in priced), 2) if priced else None,
        "median_model_market_gap": round(median_gap, 4),
        "disagreements": len(dis),
        "disagreement_hit_rate": round(sum(1 for a in dis if a["won"]) / len(dis), 3) if dis else None,
        "note": ("return at CONSENSUS odds (no line shopping); a sustained negative "
                 "total at near-zero gap means the model is mirroring the market — "
                 "see model_track_record.edge_validated"),
    }
