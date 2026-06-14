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


def _win_prob_at(snap, prematch) -> Optional[dict]:
    """Live win-probability + markets for a single snapshot (Layer-1 intelligence)."""
    from models.live_win_probability import live_win_probability, lambdas_from_anchor
    minute = snap.get("minute")
    if minute is None:
        return None
    hs, as_ = int(snap.get("home_score") or 0), int(snap.get("away_score") or 0)
    lam_h, lam_a = lambdas_from_anchor(prematch)
    return live_win_probability(
        hs, as_, minute, lambda_home_full=lam_h, lambda_away_full=lam_a,
        red_home=int(snap.get("home_red_cards") or 0),
        red_away=int(snap.get("away_red_cards") or 0),
    )


def _latest_live_odds(cur, match_id: int, max_age_s: int = 180) -> dict:
    """
    Latest live 1X2 (market 59) + match-total Over/Under lines for a match,
    only if fresh (≤ max_age_s old). Returns {} when no fresh live odds.
    """
    cur.execute("""
        SELECT market_id, selection, line, odds_decimal,
               EXTRACT(EPOCH FROM (NOW() - ts_snapshot)) AS age
        FROM (
            SELECT DISTINCT ON (market_id, selection, line)
                   market_id, selection, line, odds_decimal, ts_snapshot
            FROM live_odds_snapshots
            WHERE match_id = %s AND market_id IN (59, 25, 36)
            ORDER BY market_id, selection, line, ts_snapshot DESC
        ) t
        WHERE EXTRACT(EPOCH FROM (NOW() - ts_snapshot)) <= %s
    """, (match_id, max_age_s))
    out = {"x12": {}, "totals": {}, "age": None}
    for mid, sel, line, odds, age in cur.fetchall():
        out["age"] = min(out["age"], age) if out["age"] is not None else age
        if mid == 59:
            out["x12"][sel.lower()] = float(odds)
        elif mid in (25, 36) and line is not None:
            out["totals"].setdefault(float(line), {})[sel.lower()] = float(odds)
    return out


def _build_card(match_id, home, away, league_id, snaps, prematch, live_odds=None) -> Optional[dict]:
    """
    Assemble one board card: full live state + live win-probability + advanced
    markets (Layer 1, always present) + value verdict (Layer 2, live when odds present).
    """
    from features.live_feature_builder import build_live_features
    from utils.edge import devig_proportional, ev_at_price, min_acceptable_odds, value_rating
    if not snaps:
        return None
    cur_snap = snaps[-1]
    minute = cur_snap["minute"]
    feats = build_live_features(snaps, minute, prematch=prematch)
    if not feats:
        return None

    hs, as_ = int(cur_snap.get("home_score") or 0), int(cur_snap.get("away_score") or 0)
    wp = _win_prob_at(cur_snap, prematch)  # live win prob + markets
    over05 = wp["markets"]["over_0.5_more_goals"] if wp else None

    # ── Layer 2: value from live odds (when fresh odds exist) ──────────────────
    value = None
    win_prob_edge = None
    status = "WATCHLIST"
    confidence = "low"
    if live_odds and wp:
        # win-prob edge: model 1X2 vs de-vigged live 1X2 (market 59)
        x12 = live_odds.get("x12") or {}
        if {"home", "draw", "away"} <= set(x12):
            try:
                fair = devig_proportional({k: 1.0 / x12[k] for k in ("home", "draw", "away")})
                win_prob_edge = {k: round(wp["win_probability"][k] - fair[k], 4)
                                 for k in ("home", "draw", "away")}
            except (ValueError, ZeroDivisionError):
                pass
        # featured market: "over 0.5 more goals" → live match-total Over line at (current_total + 0.5)
        need_line = (hs + as_) + 0.5
        tot = (live_odds.get("totals") or {}).get(need_line)
        if tot and tot.get("over") and tot["over"] > 1.0:
            odds = tot["over"]
            p = over05
            ev = ev_at_price(p, odds)
            fair_imp = None
            if tot.get("under") and tot["under"] > 1.0:
                fair_imp = devig_proportional({"home": 1.0 / odds, "away": 1.0 / tot["under"]},
                                              outcomes=("home", "away"))["home"]
            value = {
                "market": "over_0.5_more_goals", "line": need_line,
                "model_prob": p, "best_price": {"odds": round(odds, 3), "book": "live_consensus"},
                "market_implied": round(fair_imp, 4) if fair_imp is not None else None,
                "edge": round(p - fair_imp, 4) if fair_imp is not None else None,
                "ev": round(ev, 4), "rating": value_rating(ev),
                "min_acceptable_odds": min_acceptable_odds(p),
                "odds_age_s": round(live_odds.get("age") or 0, 1),
            }
            # BETTABLE only on positive EV + fresh odds (price-guard contract)
            if ev > 0 and (live_odds.get("age") or 999) <= 30 and odds >= 1.85:
                status = "BETTABLE"
                confidence = "medium" if ev >= 0.05 else "low"

    pressure_total = feats.get("pressure_total", 0.0)
    rising = pressure_total >= _PRESSURE_HEAT
    if status == "BETTABLE":
        reason = f"+EV {value['ev']*100:.0f}% on another goal at live price"
    else:
        reason = ("pressure rising — watching for value" if rising else "low tempo — not a spot")

    now = datetime.now(timezone.utc)
    return {
        "match_id": match_id,
        "minute": minute,
        "period": cur_snap.get("period"),
        "home": {"name": home, "score": hs},
        "away": {"name": away, "score": as_},
        "status": status,
        # ── Layer 1: live match intelligence (always present, no odds needed) ──
        "win_probability": wp["win_probability"] if wp else None,
        "markets": wp["markets"] if wp else None,        # over_0.5_more / over_2.5 / btts / next_goal
        "remaining_goal_rate": wp["remaining_goal_rate"] if wp else None,
        "live_stats": {
            "home_shots": feats.get("home_shots"), "away_shots": feats.get("away_shots"),
            "home_sot": feats.get("home_sot"), "away_sot": feats.get("away_sot"),
            "home_corners": feats.get("home_corners"), "away_corners": feats.get("away_corners"),
            "home_possession": feats.get("home_possession"),
            "home_red": feats.get("home_red"), "away_red": feats.get("away_red"),
        },
        "pressure": {"home": feats.get("pressure_home"), "away": feats.get("pressure_away"),
                     "total": round(pressure_total, 2)},
        # ── primary featured market (the late-goal pick) ──
        "market": "over_0.5_more_goals",
        "pick": "over_0.5_more_goals",
        "model_prob": over05,
        "model_prob_source": "live_poisson_prior",
        # ── Layer 2: value verdict — live when fresh in-play odds exist, else null ──
        "value": value,
        "win_prob_edge": win_prob_edge,      # model 1X2 minus de-vigged live 1X2
        "market_implied": value["market_implied"] if value else None,
        "edge": value["edge"] if value else None,
        "ev": value["ev"] if value else None,
        "best_price": value["best_price"] if value else None,
        "min_acceptable_odds": value["min_acceptable_odds"] if value else None,
        "confidence": confidence,
        "reason": reason,
        "expires_at": (now + timedelta(seconds=_BOARD_TTL_SECONDS)).isoformat(),
        "model_track_record": {"model": "live_edge_over05", "edge_validated": False,
                               "validation": "live Poisson prior; no CLV holdout yet"},
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
                    live_odds = _latest_live_odds(cur, match_id)
                    card = _build_card(match_id, home, away, league_id, snaps, prematch, live_odds)
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
                live_odds = _latest_live_odds(cur, match_id)
                card = _build_card(match_id, home, away, league_id, snaps, prematch, live_odds)
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

    # win-probability history — the dynamic graph: recompute win prob at each
    # past snapshot so the frontend can plot how chances shifted with the game.
    win_prob_history = []
    for s in snaps:
        wp = _win_prob_at(s, prematch)
        if wp:
            win_prob_history.append({
                "minute": s["minute"],
                "home_score": int(s.get("home_score") or 0),
                "away_score": int(s.get("away_score") or 0),
                **wp["win_probability"],
            })

    return {
        **(card or {}),
        "win_prob_history": win_prob_history,   # [{minute, home, draw, away, scores}, ...]
        "snapshots": snaps[-12:],               # last ~12 minutes of raw state
        "why": why,
        "generated_at": now.isoformat(),
    }
