"""
Multisport Market Endpoint — GET /market-multisport

Mirrors the soccer /market endpoint structure for NBA, NHL, NCAAB, NFL.
Returns fixtures with bookmaker odds, consensus probabilities, model predictions,
spread/totals, and per-sport season status.
"""

import os
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

import psycopg2
from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Multisport Market"])

SUPPORTED_SPORTS = {
    "basketball_nba": {"name": "NBA", "season_start_month": 10, "season_end_month": 6},
    "icehockey_nhl": {"name": "NHL", "season_start_month": 10, "season_end_month": 6},
    "basketball_ncaab": {"name": "NCAA Basketball", "season_start_month": 11, "season_end_month": 4},
    "americanfootball_nfl": {"name": "NFL", "season_start_month": 9, "season_end_month": 2},
    "basketball_euroleague": {"name": "EuroLeague", "season_start_month": 10, "season_end_month": 5},
}


def _get_season_status(sport_key: str) -> dict:
    """Determine if a sport is in-season, off-season, or in playoffs."""
    info = SUPPORTED_SPORTS.get(sport_key, {})
    now = datetime.now(timezone.utc)
    month = now.month
    start = info.get("season_start_month", 1)
    end = info.get("season_end_month", 12)

    # Handle wrap-around seasons (e.g. NFL Sept→Feb)
    if start <= end:
        in_season = start <= month <= end
    else:
        in_season = month >= start or month <= end

    return {
        "in_season": in_season,
        "status": "in_season" if in_season else "off_season",
        "season_window": f"{_month_name(start)}–{_month_name(end)}",
    }


def _month_name(m: int) -> str:
    return ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][m - 1]


def _get_model_confidence_note(sport_key: str, training_samples: int) -> Optional[str]:
    """Flag sports with limited training data."""
    if training_samples < 100:
        return f"Low training data ({training_samples} samples) — predictions may be less reliable"
    if training_samples < 300:
        return f"Moderate training data ({training_samples} samples)"
    return None


# ── Dependency: reuse verify_api_key from main ──
from fastapi import Header, HTTPException

async def verify_api_key_dep(authorization: str = Header(None)):
    if not authorization:
        raise HTTPException(401, "Missing Authorization header")
    token = authorization.replace("Bearer ", "").strip()
    valid_keys = [
        os.environ.get("API_KEY", "betgenius_secure_key_2024"),
        "betgenius_secure_key_2024",
    ]
    if token not in valid_keys:
        raise HTTPException(401, "Invalid API key")
    return token


@router.get("/market-multisport")
async def get_multisport_market(
    sport: str = Query("basketball_nba", description="Sport key"),
    status: str = Query("upcoming", description="upcoming, finished, or all"),
    limit: int = Query(25, ge=1, le=100),
    event_id: Optional[str] = Query(None, description="Get single event by ID"),
    api_key: str = Depends(verify_api_key_dep),
):
    """
    Multisport market endpoint — upcoming/finished fixtures with odds, model picks, and results.

    Similar to GET /market for soccer but adapted for binary-outcome sports (no draw).

    Sports: basketball_nba, icehockey_nhl, basketball_ncaab, americanfootball_nfl, basketball_euroleague
    """
    if sport not in SUPPORTED_SPORTS:
        raise HTTPException(400, f"Unsupported sport: {sport}. Supported: {', '.join(SUPPORTED_SPORTS.keys())}")

    start_time = datetime.now()

    try:
        conn = psycopg2.connect(os.environ.get("DATABASE_URL"), connect_timeout=10)
        cur = conn.cursor()

        # ── Season status ──
        season = _get_season_status(sport)

        # ── Training data count for confidence note ──
        cur.execute("SELECT COUNT(*) FROM multisport_training WHERE sport_key = %s", (sport,))
        training_count = cur.fetchone()[0]
        confidence_note = _get_model_confidence_note(sport, training_count)

        # ── Build query based on status ──
        if event_id:
            where_clause = "f.sport_key = %s AND f.event_id = %s"
            params = (sport, event_id)
            order_clause = "f.commence_time DESC"
        elif status == "upcoming":
            where_clause = "f.sport_key = %s AND f.commence_time > NOW() AND (f.status IS NULL OR f.status NOT IN ('finished', 'completed'))"
            params = (sport,)
            order_clause = "f.commence_time ASC"
        elif status == "finished":
            where_clause = "f.sport_key = %s AND f.status IN ('finished', 'completed')"
            params = (sport,)
            order_clause = "f.commence_time DESC"
        else:  # all
            where_clause = "f.sport_key = %s"
            params = (sport,)
            order_clause = "f.commence_time DESC"

        cur.execute(f"""
            SELECT f.event_id, f.home_team, f.away_team, f.commence_time,
                   f.league_name, f.status, f.home_score, f.away_score, f.outcome,
                   f.home_team_id, f.away_team_id
            FROM multisport_fixtures f
            WHERE {where_clause}
            ORDER BY {order_clause}
            LIMIT %s
        """, (*params, limit))
        fixtures = cur.fetchall()

        # ── Gather event_ids for batch odds lookup ──
        event_ids = [r[0] for r in fixtures]

        # ── Consensus odds (latest per event) ──
        consensus_odds = {}
        if event_ids:
            placeholders = ",".join(["%s"] * len(event_ids))
            cur.execute(f"""
                SELECT DISTINCT ON (event_id)
                    event_id, home_odds, away_odds, home_prob, away_prob,
                    home_spread, total_line, over_odds, under_odds,
                    n_bookmakers, overround
                FROM multisport_odds_snapshots
                WHERE event_id IN ({placeholders}) AND is_consensus = true
                ORDER BY event_id, ts_recorded DESC
            """, event_ids)
            for r in cur.fetchall():
                consensus_odds[r[0]] = {
                    "home_odds": float(r[1]) if r[1] else None,
                    "away_odds": float(r[2]) if r[2] else None,
                    "home_prob": float(r[3]) if r[3] else None,
                    "away_prob": float(r[4]) if r[4] else None,
                    "home_spread": float(r[5]) if r[5] else None,
                    "total_line": float(r[6]) if r[6] else None,
                    "over_odds": float(r[7]) if r[7] else None,
                    "under_odds": float(r[8]) if r[8] else None,
                    "n_bookmakers": r[9],
                    "overround": float(r[10]) if r[10] else None,
                }

        # ── Bookmaker odds (latest per event+bookmaker) ──
        bookmaker_odds = {}
        if event_ids:
            cur.execute(f"""
                SELECT DISTINCT ON (event_id, bookmaker)
                    event_id, bookmaker, home_odds, away_odds,
                    home_spread, home_spread_odds, away_spread_odds,
                    total_line, over_odds, under_odds
                FROM multisport_odds_snapshots
                WHERE event_id IN ({placeholders}) AND is_consensus = false AND bookmaker IS NOT NULL
                ORDER BY event_id, bookmaker, ts_recorded DESC
            """, event_ids)
            for r in cur.fetchall():
                eid = r[0]
                if eid not in bookmaker_odds:
                    bookmaker_odds[eid] = {}
                bookmaker_odds[eid][r[1]] = {
                    "home": float(r[2]) if r[2] else None,
                    "away": float(r[3]) if r[3] else None,
                    "spread": float(r[4]) if r[4] else None,
                    "spread_home_odds": float(r[5]) if r[5] else None,
                    "spread_away_odds": float(r[6]) if r[6] else None,
                    "total_line": float(r[7]) if r[7] else None,
                    "over_odds": float(r[8]) if r[8] else None,
                    "under_odds": float(r[9]) if r[9] else None,
                }

        # ── Match results for finished games ──
        results_map = {}
        if event_ids:
            cur.execute(f"""
                SELECT event_id, home_score, away_score, result, overtime
                FROM multisport_match_results
                WHERE event_id IN ({placeholders})
            """, event_ids)
            for r in cur.fetchall():
                results_map[r[0]] = {
                    "home_score": r[1],
                    "away_score": r[2],
                    "result": r[3],
                    "overtime": r[4],
                }

        conn.close()

        # ── V3 model predictions (batch) ──
        model_predictions = {}
        try:
            from models.multisport_v3_predictor import get_multisport_predictor
            predictor = get_multisport_predictor(sport)
            if predictor:
                from dateutil.parser import parse as _dt_parse
                for fix in fixtures:
                    eid, home, away, ct = fix[0], fix[1], fix[2], fix[3]
                    try:
                        game_dt = ct if isinstance(ct, datetime) else _dt_parse(str(ct))
                        pred = predictor.predict(
                            sport_key=sport, event_id=eid,
                            home_team=home, away_team=away, game_date=game_dt
                        )
                        if pred:
                            model_predictions[eid] = {
                                "home_win": round(pred["prob_home"], 3),
                                "away_win": round(pred["prob_away"], 3),
                                "pick": pred.get("pick", "H"),
                                "confidence": round(pred.get("confidence", 0), 3),
                                "features_used": pred.get("features_used", 0),
                            }
                    except Exception as e:
                        logger.debug(f"Model prediction failed for {eid}: {e}")
        except Exception as e:
            logger.warning(f"Multisport predictor unavailable for {sport}: {e}")

        # ── Build response ──
        matches = []
        for fix in fixtures:
            eid = fix[0]
            fix_status = fix[5] or "scheduled"
            is_finished = fix_status in ("finished", "completed")

            cons = consensus_odds.get(eid, {})
            books = bookmaker_odds.get(eid, {})
            model = model_predictions.get(eid)
            result = results_map.get(eid)

            # Use fixture scores if result not in results table
            if not result and fix[6] is not None and fix[7] is not None and is_finished:
                result = {
                    "home_score": fix[6], "away_score": fix[7],
                    "result": fix[8], "overtime": None,
                }

            match = {
                "event_id": eid,
                "status": "FINISHED" if is_finished else "UPCOMING",
                "commence_time": fix[3].isoformat() if fix[3] else None,
                "league": {
                    "name": fix[4] or SUPPORTED_SPORTS[sport]["name"],
                    "sport_key": sport,
                },
                "home": {"name": fix[1], "team_id": fix[9]},
                "away": {"name": fix[2], "team_id": fix[10]},
                "odds": {
                    "consensus": cons if cons else None,
                    "books": books if books else {},
                    "book_count": len(books),
                },
                "spread": {
                    "line": cons.get("home_spread"),
                    "total": cons.get("total_line"),
                    "over_odds": cons.get("over_odds"),
                    "under_odds": cons.get("under_odds"),
                } if cons else None,
                "model": {
                    "predictions": model,
                    "source": "v3_multisport",
                    "no_draw": True,
                } if model else None,
            }

            if result:
                result_text = f"{'Home' if result['result'] == 'H' else 'Away'} Win"
                if result.get("overtime"):
                    result_text += " (OT)"
                match["final_result"] = {
                    "score": {"home": result["home_score"], "away": result["away_score"]},
                    "result": result["result"],
                    "result_text": result_text,
                    "overtime": result.get("overtime", False),
                }

                # Model accuracy check (if model predicted this game)
                if model and result["result"]:
                    correct = (model["pick"] == result["result"])
                    match["model"]["correct"] = correct

            matches.append(match)

        processing_time = round((datetime.now() - start_time).total_seconds(), 3)

        return {
            "sport": sport,
            "sport_name": SUPPORTED_SPORTS[sport]["name"],
            "season": season,
            "matches": matches,
            "total_count": len(matches),
            "live_data_available": False,
            "model_info": {
                "type": "v3_multisport_lgbm",
                "no_draw": True,
                "training_samples": training_count,
                "confidence_note": confidence_note,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "processing_time": processing_time,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"market-multisport error: {e}", exc_info=True)
        raise HTTPException(500, f"Market data temporarily unavailable: {str(e)}")


@router.get("/market-multisport/sports")
async def list_sports(api_key: str = Depends(verify_api_key_dep)):
    """
    List all supported sports with season status, fixture counts, and model readiness.
    Use this to populate sport selection UI.
    """
    try:
        conn = psycopg2.connect(os.environ.get("DATABASE_URL"), connect_timeout=10)
        cur = conn.cursor()

        sports = []
        for sport_key, info in SUPPORTED_SPORTS.items():
            season = _get_season_status(sport_key)

            # Fixture counts
            cur.execute("""
                SELECT
                    COUNT(*) FILTER (WHERE commence_time > NOW() AND (status IS NULL OR status NOT IN ('finished','completed'))),
                    COUNT(*) FILTER (WHERE status IN ('finished','completed')),
                    COUNT(*)
                FROM multisport_fixtures WHERE sport_key = %s
            """, (sport_key,))
            upcoming, finished, total = cur.fetchone()

            # Upcoming with odds
            cur.execute("""
                SELECT COUNT(DISTINCT f.event_id)
                FROM multisport_fixtures f
                JOIN multisport_odds_snapshots o ON f.event_id = o.event_id AND o.is_consensus = true
                WHERE f.sport_key = %s AND f.commence_time > NOW()
                  AND (f.status IS NULL OR f.status NOT IN ('finished','completed'))
            """, (sport_key,))
            upcoming_with_odds = cur.fetchone()[0]

            # Training data
            cur.execute("SELECT COUNT(*) FROM multisport_training WHERE sport_key = %s", (sport_key,))
            training = cur.fetchone()[0]

            # Model available?
            model_available = False
            try:
                from models.multisport_v3_predictor import get_multisport_predictor
                p = get_multisport_predictor(sport_key)
                model_available = p is not None
            except Exception:
                pass

            sports.append({
                "sport_key": sport_key,
                "name": info["name"],
                "season": season,
                "fixtures": {
                    "upcoming": upcoming,
                    "upcoming_with_odds": upcoming_with_odds,
                    "finished": finished,
                    "total": total,
                },
                "model": {
                    "available": model_available,
                    "training_samples": training,
                    "confidence_note": _get_model_confidence_note(sport_key, training),
                },
                "live_data_available": False,
            })

        conn.close()

        return {
            "sports": sports,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        logger.error(f"market-multisport/sports error: {e}", exc_info=True)
        raise HTTPException(500, str(e))
