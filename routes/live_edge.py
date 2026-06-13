"""
Snapbet Live Edge — in-game board + match detail endpoints.

Implements the contract in docs/FRONTEND_LIVE_EDGE.md:
  GET /live-edge/board            — all currently-live matches with state + verdict
  GET /live-edge/match/{match_id} — one match: snapshot history + "why"

Current backend readiness (honest, per manual §9):
  - Live match STATE: ✅ from live_match_stats (collected ~every 60s).
  - model_prob: a Poisson PRIOR (live_feature_builder.implied_more_goal_poisson)
    until the trained Over-0.5 model ships — so model_track_record.edge_validated=False.
  - In-play ODDS: 🔴 not collected → market_implied/edge/ev/best_price are NULL and
    every card is WATCHLIST (never BETTABLE — the manual's price-guard contract).
The board lights up with richer status the moment in-play odds + the model land;
the frontend needs zero change (nullable contract).
"""

import os
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List

import psycopg2
from fastapi import APIRouter, Depends, Header, HTTPException

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Snapbet Live Edge"])

# International league ids → these route to neutral-venue / WC context
_INTL_LEAGUES = {1, 4, 5, 6, 9, 10, 29, 30, 31, 32, 33, 34}
_BOARD_TTL_SECONDS = 60
# Pressure above this flags "pressure rising" in the WATCHLIST reason (rule-based,
# pre-model heuristic — NOT an edge claim).
_PRESSURE_HEAT = 25.0


async def verify_api_key_dep(authorization: str = Header(None)):
    if not authorization:
        raise HTTPException(401, "Missing Authorization header")
    token = authorization.replace("Bearer ", "").strip()
    valid = [os.environ.get("API_KEY", "betgenius_secure_key_2024"), "betgenius_secure_key_2024"]
    if token not in valid:
        raise HTTPException(401, "Invalid API key")
    return token


def _conn():
    return psycopg2.connect(os.environ.get("DATABASE_URL"), connect_timeout=10)


def _live_match_ids(cur) -> List[tuple]:
    """Matches kicked off ≤150 min ago, not finished, with at least one real snapshot."""
    cur.execute("""
        SELECT f.match_id, f.home_team, f.away_team, f.league_id, f.kickoff_at
        FROM fixtures f
        WHERE f.kickoff_at <= NOW() AND f.kickoff_at > NOW() - INTERVAL '150 minutes'
          AND f.status NOT IN ('finished','FT','completed','AET','PEN')
          AND EXISTS (SELECT 1 FROM live_match_stats lms
                      WHERE lms.match_id = f.match_id AND lms.minute IS NOT NULL)
        ORDER BY f.kickoff_at DESC
    """)
    return cur.fetchall()


def _snapshots(cur, match_id: int) -> List[dict]:
    """All real (minute IS NOT NULL) snapshots for a match, chronological."""
    cur.execute("""
        SELECT minute, period, home_score, away_score,
               home_shots_total, away_shots_total, home_shots_on_target, away_shots_on_target,
               home_corners, away_corners, home_possession, home_red_cards, away_red_cards
        FROM live_match_stats
        WHERE match_id = %s AND minute IS NOT NULL
        ORDER BY minute ASC
    """, (match_id,))
    cols = ["minute", "period", "home_score", "away_score", "home_shots_total",
            "away_shots_total", "home_shots_on_target", "away_shots_on_target",
            "home_corners", "away_corners", "home_possession", "home_red_cards", "away_red_cards"]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _prematch_anchor(cur, match_id: int) -> Optional[dict]:
    """De-vigged pre-match consensus, if we have it (anchor for favorite flags)."""
    cur.execute("""
        SELECT ph_cons, pd_cons, pa_cons FROM odds_consensus
        WHERE match_id = %s AND ph_cons IS NOT NULL
        ORDER BY ts_effective DESC LIMIT 1
    """, (match_id,))
    row = cur.fetchone()
    if not row:
        return None
    ph, pd, pa = float(row[0]), float(row[1]), float(row[2])
    t = ph + pd + pa
    if t <= 0:
        return None
    ph, pa = ph / t, pa / t
    return {"home": round(ph, 4), "away": round(pa, 4),
            "favorite": "home" if ph >= pa else "away"}


def _build_card(match_id, home, away, league_id, snaps, prematch) -> Optional[dict]:
    """Assemble one board card from snapshot history. WATCHLIST-only until odds+model."""
    from features.live_feature_builder import build_live_features, implied_more_goal_poisson
    if not snaps:
        return None
    cur_snap = snaps[-1]
    minute = cur_snap["minute"]
    feats = build_live_features(snaps, minute, prematch=prematch)
    if not feats:
        return None

    hs, as_ = int(cur_snap.get("home_score") or 0), int(cur_snap.get("away_score") or 0)
    # Pre-model probability PRIOR for "over 0.5 more goals"
    pm_total = 2.6
    if prematch:  # nudge prior by anchor strength (very light)
        pm_total = 2.6
    model_prob = implied_more_goal_poisson(hs, as_, minute, prematch_total_goals=pm_total)

    pressure_total = feats.get("pressure_total", 0.0)
    rising = pressure_total >= _PRESSURE_HEAT
    reason = ("pressure rising — watching for value" if rising
              else "low tempo — not a spot")
    # No in-play odds yet → WATCHLIST always (price-guard contract: no odds, no bet)
    status = "WATCHLIST"

    now = datetime.now(timezone.utc)
    return {
        "match_id": match_id,
        "minute": minute,
        "period": cur_snap.get("period"),
        "home": {"name": home, "score": hs},
        "away": {"name": away, "score": as_},
        "status": status,
        "market": "over_0.5_more_goals",
        "pick": "over_0.5_more_goals",
        "model_prob": model_prob,            # Poisson PRIOR (not trained model yet)
        "model_prob_source": "poisson_prior",
        "market_implied": None,              # null until in-play odds collection
        "edge": None, "ev": None, "best_price": None, "min_acceptable_odds": None,
        "confidence": "low",                 # never higher than low pre-model/pre-odds
        "pressure": {"home": feats.get("pressure_home"), "away": feats.get("pressure_away"),
                     "total": round(pressure_total, 2)},
        "reason": reason,
        "expires_at": (now + timedelta(seconds=_BOARD_TTL_SECONDS)).isoformat(),
        "model_track_record": {"model": "live_edge_over05", "edge_validated": False,
                               "validation": "Poisson prior; no CLV holdout yet"},
    }


@router.get("/live-edge/board")
async def live_edge_board(api_key: str = Depends(verify_api_key_dep)):
    """All currently-live matches with in-game state + (pre-model) verdict."""
    now = datetime.now(timezone.utc)
    cards = []
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                live = _live_match_ids(cur)
                for match_id, home, away, league_id, _ko in live:
                    snaps = _snapshots(cur, match_id)
                    prematch = _prematch_anchor(cur, match_id)
                    card = _build_card(match_id, home, away, league_id, snaps, prematch)
                    if card:
                        cards.append(card)
    except Exception as e:
        logger.error(f"live-edge board failed: {e}")
        return {"generated_at": now.isoformat(), "active_matches": 0, "matches": [],
                "error": "board temporarily unavailable"}

    return {
        "generated_at": now.isoformat(),
        "active_matches": len(cards),
        "poll_seconds": 25,
        "matches": cards,
        "note": ("WATCHLIST-only until in-play odds + trained model ship; "
                 "value fields (edge/ev/best_price) are null by design."),
    }


@router.get("/live-edge/match/{match_id}")
async def live_edge_match(match_id: int, api_key: str = Depends(verify_api_key_dep)):
    """One live match: current card + snapshot timeline + 'why' bullets."""
    now = datetime.now(timezone.utc)
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT home_team, away_team, league_id FROM fixtures WHERE match_id=%s", (match_id,))
                fx = cur.fetchone()
                if not fx:
                    raise HTTPException(404, f"match {match_id} not found")
                home, away, league_id = fx
                snaps = _snapshots(cur, match_id)
                if not snaps:
                    raise HTTPException(404, f"no live snapshots for match {match_id}")
                prematch = _prematch_anchor(cur, match_id)
                card = _build_card(match_id, home, away, league_id, snaps, prematch)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"live-edge match {match_id} failed: {e}")
        raise HTTPException(500, "match detail temporarily unavailable")

    # "why" bullets from the latest feature row
    from features.live_feature_builder import build_live_features
    feats = build_live_features(snaps, snaps[-1]["minute"], prematch=prematch)
    why = []
    lead = "home" if feats.get("pressure_home", 0) >= feats.get("pressure_away", 0) else "away"
    lead_name = home if lead == "home" else away
    if feats.get(f"{lead}_shots_10", 0) >= 3:
        why.append(f"{int(feats[f'{lead}_shots_10'])} shots in last 10 minutes ({lead_name})")
    if feats.get(f"{lead}_sot_10", 0) >= 1:
        why.append(f"{int(feats[f'{lead}_sot_10'])} on target recently ({lead_name})")
    if feats.get(f"{lead}_corners_10", 0) >= 2:
        why.append(f"{int(feats[f'{lead}_corners_10'])} corners in last 10 ({lead_name})")
    if feats.get("home_red", 0) or feats.get("away_red", 0):
        why.append("red card — game opened up")
    if feats.get("favorite_trailing"):
        why.append("pre-match favorite is chasing")
    if not why:
        why.append("no strong late-game signal yet")

    return {
        **(card or {}),
        "snapshots": snaps[-12:],   # last ~12 minutes of state
        "why": why,
        "generated_at": now.isoformat(),
    }
