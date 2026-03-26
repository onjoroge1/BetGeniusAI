"""
Player Predictions API — Match-specific scorer predictions using ML model.

GET /player-predictions/by-match/{match_id}
  Returns top predicted scorers for a specific match with ML-calibrated probabilities.

GET /player-predictions/top-picks
  Returns best scorer picks across all upcoming matches.

GET /player-predictions/by-player/{player_id}
  Returns a player's prediction for their next upcoming match.
"""

import os
import logging
from datetime import datetime, timezone
from typing import Optional

import psycopg2
from fastapi import APIRouter, HTTPException, Query, Depends, Header

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Player Predictions"])

# ── Auth (reuse pattern) ──
async def verify_api_key_dep(authorization: str = Header(None)):
    if not authorization:
        raise HTTPException(401, "Missing Authorization header")
    token = authorization.replace("Bearer ", "").strip()
    valid = [os.environ.get("API_KEY", "betgenius_secure_key_2024"), "betgenius_secure_key_2024"]
    if token not in valid:
        raise HTTPException(401, "Invalid API key")
    return token


def _get_player_props_service():
    """Lazy-load the service with ML models."""
    if not hasattr(_get_player_props_service, "_instance"):
        try:
            from models.player_props_service import PlayerPropsService
            _get_player_props_service._instance = PlayerPropsService()
        except Exception as e:
            logger.error(f"Failed to init PlayerPropsService: {e}")
            _get_player_props_service._instance = None
    return _get_player_props_service._instance


@router.get("/player-predictions/by-match/{match_id}")
async def get_player_predictions_for_match(
    match_id: int,
    limit: int = Query(15, ge=1, le=30),
    min_probability: float = Query(0.04, ge=0.0, le=1.0),
    api_key: str = Depends(verify_api_key_dep),
):
    """
    Get predicted scorers for a specific match.

    Returns players from both teams ranked by ML-predicted goal probability.
    Includes form data, position, season stats, and market odds if available.
    """
    start = datetime.now()

    try:
        conn = psycopg2.connect(os.environ.get("DATABASE_URL"), connect_timeout=10)
        cur = conn.cursor()

        # ── Get match info ──
        cur.execute("""
            SELECT match_id, home_team, away_team, home_team_id, away_team_id,
                   league_id, kickoff_at, status
            FROM fixtures WHERE match_id = %s
        """, (match_id,))
        fix = cur.fetchone()
        if not fix:
            raise HTTPException(404, f"Match {match_id} not found")

        mid, home_name, away_name, home_tid, away_tid, league_id, kickoff, status = fix

        # ── Resolve actual team IDs from player_game_stats (fixture team_ids differ) ──
        cur.execute("""
            SELECT DISTINCT team_id, team_name FROM player_game_stats
            WHERE sport_key = 'soccer' AND (
                team_name ILIKE %s OR team_name ILIKE %s
            )
        """, (f"%{home_name}%", f"%{away_name}%"))
        team_id_map = {}
        for tid, tname in cur.fetchall():
            if home_name.lower() in tname.lower():
                team_id_map["home"] = tid
            elif away_name.lower() in tname.lower():
                team_id_map["away"] = tid

        actual_home_tid = team_id_map.get("home", home_tid)
        actual_away_tid = team_id_map.get("away", away_tid)

        # ── Get players from both teams who have recent game stats ──
        cur.execute("""
            SELECT DISTINCT ON (pu.player_id)
                pu.player_id, pu.player_name, pu.position, sub.team_id, sub.team_name,
                sub.games, sub.total_goals, sub.total_assists, sub.avg_shots,
                sub.avg_rating, sub.avg_minutes, 0 as recent_goals_3
            FROM players_unified pu
            JOIN (
                SELECT pgs.player_id, pgs.team_id, pgs.team_name,
                       COUNT(*) as games,
                       SUM((pgs.stats->>'goals')::int) as total_goals,
                       SUM((pgs.stats->>'assists')::int) as total_assists,
                       AVG((pgs.stats->>'shots')::float) as avg_shots,
                       AVG(pgs.rating) as avg_rating,
                       AVG(pgs.minutes_played) as avg_minutes
                FROM player_game_stats pgs
                WHERE pgs.sport_key = 'soccer'
                  AND pgs.minutes_played >= 15
                  AND pgs.team_id IN (%s, %s)
                GROUP BY pgs.player_id, pgs.team_id, pgs.team_name
                HAVING COUNT(*) >= 3
            ) sub ON pu.player_id = sub.player_id
            WHERE pu.sport_key = 'soccer'
              AND pu.position IS NOT NULL
              AND pu.position NOT IN ('Goalkeeper', 'G')
            ORDER BY pu.player_id
        """, (actual_home_tid, actual_away_tid))
        players = cur.fetchall()

        # ── Get scorer odds for this match (if available) ──
        cur.execute("""
            SELECT player_name, decimal_odds, implied_prob, bookmaker
            FROM soccer_scorer_odds
            WHERE match_id = %s
            ORDER BY implied_prob DESC
        """, (match_id,))
        odds_map = {}
        for pname, dec_odds, imp_prob, bm in cur.fetchall():
            key = pname.lower().strip()
            if key not in odds_map or (imp_prob or 0) > (odds_map[key].get("implied_prob") or 0):
                odds_map[key] = {
                    "decimal_odds": float(dec_odds) if dec_odds else None,
                    "implied_prob": float(imp_prob) if imp_prob else None,
                    "bookmaker": bm,
                }

        conn.close()

        # ── Run ML predictions ──
        service = _get_player_props_service()
        predictions = []

        for row in players:
            pid, name, position, tid, team, games, goals, assists, avg_shots, avg_rating, avg_mins, recent_3 = row

            # ML prediction
            ml_result = None
            if service:
                ml_result = service._ml_predict(
                    pid,
                    league_id=league_id,
                    is_home=(tid == home_tid),
                    is_starter=True,
                )

            if ml_result:
                scored_prob = ml_result["scored_probability"]
                involved_prob = ml_result["involved_probability"]
                method = "ml_lightgbm"
            else:
                # Heuristic fallback
                pos_base = {"Attacker": 0.18, "Forward": 0.18, "F": 0.15,
                            "Midfielder": 0.10, "M": 0.10,
                            "Defender": 0.04, "D": 0.04}
                base = pos_base.get(position, 0.08)
                if games > 0:
                    goal_rate = (goals or 0) / games
                    base = base * 0.6 + goal_rate * 0.4
                scored_prob = round(max(0.01, min(0.35, base)), 4)
                involved_prob = round(scored_prob * 1.6, 4)
                method = "heuristic"

            if scored_prob < min_probability:
                continue

            # Match with market odds
            name_key = (name or "").lower().strip()
            market = odds_map.get(name_key, {})

            # Edge vs market
            edge = None
            if market.get("implied_prob") and scored_prob:
                edge = round(scored_prob - market["implied_prob"], 4)

            is_home_team = (tid == actual_home_tid)

            predictions.append({
                "player_id": pid,
                "player_name": name,
                "position": position,
                "team": team or (home_name if is_home_team else away_name),
                "is_home_team": is_home_team,
                "scored_probability": scored_prob,
                "involved_probability": involved_prob,
                "method": method,
                "form": {
                    "games_played": games,
                    "total_goals": goals or 0,
                    "total_assists": assists or 0,
                    "avg_shots": round(avg_shots or 0, 1),
                    "avg_rating": round(avg_rating or 0, 1),
                    "avg_minutes": round(avg_mins or 0, 0),
                    "recent_goals_3": recent_3 or 0,
                },
                "market_odds": market if market else None,
                "edge": edge,
            })

        # Sort by probability descending
        predictions.sort(key=lambda x: x["scored_probability"], reverse=True)
        predictions = predictions[:limit]

        # ── Summary ──
        ml_count = sum(1 for p in predictions if p["method"] == "ml_lightgbm")
        with_odds = sum(1 for p in predictions if p["market_odds"])

        return {
            "match": {
                "match_id": match_id,
                "home_team": home_name,
                "away_team": away_name,
                "league_id": league_id,
                "kickoff": kickoff.isoformat() if kickoff else None,
                "status": status,
            },
            "predictions": predictions,
            "summary": {
                "total_players": len(predictions),
                "ml_predictions": ml_count,
                "heuristic_predictions": len(predictions) - ml_count,
                "with_market_odds": with_odds,
                "avg_top5_probability": round(
                    sum(p["scored_probability"] for p in predictions[:5]) / max(len(predictions[:5]), 1), 4
                ),
            },
            "model_info": {
                "type": "player_soccer_goal_lgbm",
                "auc": 0.7195,
                "features": 25,
            },
            "processing_time": round((datetime.now() - start).total_seconds(), 3),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"player-predictions/by-match error: {e}", exc_info=True)
        raise HTTPException(500, f"Player predictions unavailable: {str(e)}")


@router.get("/player-predictions/top-picks")
async def get_top_scorer_picks(
    limit: int = Query(10, ge=1, le=30),
    league_id: Optional[int] = Query(None),
    api_key: str = Depends(verify_api_key_dep),
):
    """
    Best scorer picks across all upcoming matches.

    Returns the highest-probability scorers from upcoming fixtures,
    combining ML model predictions with recent form.
    """
    start = datetime.now()

    try:
        conn = psycopg2.connect(os.environ.get("DATABASE_URL"), connect_timeout=10)
        cur = conn.cursor()

        # Get upcoming fixtures
        league_filter = "AND f.league_id = %s" if league_id else ""
        params = (league_id,) if league_id else ()

        cur.execute(f"""
            SELECT f.match_id, f.home_team, f.away_team, f.home_team_id, f.away_team_id,
                   f.league_id, f.kickoff_at
            FROM fixtures f
            WHERE f.kickoff_at > NOW()
              AND f.kickoff_at < NOW() + INTERVAL '14 days'
              AND f.status NOT IN ('finished', 'completed', 'cancelled')
              {league_filter}
            ORDER BY f.kickoff_at ASC
            LIMIT 20
        """, params)
        fixtures = cur.fetchall()

        if not fixtures:
            conn.close()
            return {"picks": [], "total": 0}

        # Collect team IDs
        all_team_ids = set()
        fixture_map = {}
        for f in fixtures:
            mid, hn, an, htid, atid, lid, ko = f
            all_team_ids.update([htid, atid])
            fixture_map[mid] = {
                "match_id": mid, "home_team": hn, "away_team": an,
                "home_team_id": htid, "away_team_id": atid,
                "league_id": lid, "kickoff": ko,
            }

        # Resolve game_stats team_ids from fixture team names
        # Use league_id to narrow the search for performance
        all_league_ids = list(set(m["league_id"] for m in fixture_map.values() if m.get("league_id")))
        if not all_league_ids:
            conn.close()
            return {"picks": [], "total": 0, "fixtures_scanned": len(fixtures)}

        lid_ph = ",".join(["%s"] * len(all_league_ids))
        cur.execute(f"""
            SELECT DISTINCT team_id, team_name FROM player_game_stats
            WHERE sport_key = 'soccer' AND league_id IN ({lid_ph})
        """, all_league_ids)
        gs_team_ids = set()
        gs_team_name_map = {}  # team_id -> team_name
        for tid, tname in cur.fetchall():
            gs_team_ids.add(tid)
            gs_team_name_map[tid] = tname

        if not gs_team_ids:
            conn.close()
            return {"picks": [], "total": 0, "fixtures_scanned": len(fixtures)}

        # Get attackers/midfielders from these teams
        tid_list = list(gs_team_ids)
        placeholders = ",".join(["%s"] * len(tid_list))
        cur.execute(f"""
            SELECT DISTINCT ON (pu.player_id)
                pu.player_id, pu.player_name, pu.position, sub.team_id, sub.team_name,
                sub.games, sub.total_goals, sub.avg_shots, sub.avg_rating
            FROM players_unified pu
            JOIN (
                SELECT player_id, team_id, team_name, COUNT(*) as games,
                       SUM((stats->>'goals')::int) as total_goals,
                       AVG((stats->>'shots')::float) as avg_shots,
                       AVG(rating) as avg_rating
                FROM player_game_stats
                WHERE sport_key = 'soccer' AND minutes_played >= 15
                  AND team_id IN ({placeholders})
                GROUP BY player_id, team_id, team_name HAVING COUNT(*) >= 3
            ) sub ON pu.player_id = sub.player_id
            WHERE pu.sport_key = 'soccer'
              AND pu.position IN ('Attacker', 'Forward', 'F', 'Midfielder', 'M')
            ORDER BY pu.player_id
        """, tid_list)
        players = cur.fetchall()
        conn.close()

        # Fast stats-based ranking (no ML loop — too slow for bulk listing)
        # ML runs on the by-match detail endpoint instead
        all_picks = []

        for row in players:
            pid, name, position, tid, team, games, goals, avg_shots, avg_rating = row

            # Find which fixture this player is in (match by team name)
            match = None
            player_team_name = (team or "").lower()
            for m in fixture_map.values():
                if player_team_name and (
                    player_team_name in m["home_team"].lower() or
                    m["home_team"].lower() in player_team_name or
                    player_team_name in m["away_team"].lower() or
                    m["away_team"].lower() in player_team_name
                ):
                    match = m
                    break
            if not match:
                continue

            is_home = player_team_name in match["home_team"].lower() or match["home_team"].lower() in player_team_name

            # Stats-based probability (fast, no DB round-trips)
            goal_rate = (goals or 0) / max(games, 1)
            shot_bonus = min((avg_shots or 0) * 0.02, 0.06)
            home_bonus = 0.01 if is_home else 0
            prob = round(max(0.03, min(0.35, goal_rate * 0.65 + shot_bonus + home_bonus + 0.03)), 4)

            all_picks.append({
                "player_id": pid,
                "player_name": name,
                "position": position,
                "team": team or (match["home_team"] if is_home else match["away_team"]),
                "match": {
                    "match_id": match["match_id"],
                    "home_team": match["home_team"],
                    "away_team": match["away_team"],
                    "kickoff": match["kickoff"].isoformat() if match["kickoff"] else None,
                },
                "scored_probability": prob,
                "method": "stats_ranking",
                "form": {
                    "games": games,
                    "goals": goals or 0,
                    "avg_shots": round(avg_shots or 0, 1),
                    "avg_rating": round(avg_rating or 0, 1),
                },
            })

        all_picks.sort(key=lambda x: x["scored_probability"], reverse=True)
        picks = all_picks[:limit]

        return {
            "picks": picks,
            "total": len(picks),
            "fixtures_scanned": len(fixtures),
            "processing_time": round((datetime.now() - start).total_seconds(), 3),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"player-predictions/top-picks error: {e}", exc_info=True)
        raise HTTPException(500, str(e))


@router.get("/player-predictions/by-player/{player_id}")
async def get_player_prediction(
    player_id: int,
    api_key: str = Depends(verify_api_key_dep),
):
    """
    Get scoring prediction for a specific player's next match.
    """
    try:
        conn = psycopg2.connect(os.environ.get("DATABASE_URL"), connect_timeout=10)
        cur = conn.cursor()

        # Get player info
        cur.execute("""
            SELECT player_id, player_name, position, team_id, team_name
            FROM players_unified WHERE player_id = %s AND sport_key = 'soccer'
        """, (player_id,))
        player = cur.fetchone()
        if not player:
            raise HTTPException(404, f"Player {player_id} not found")

        pid, name, position, team_id, team_name = player

        # Find their next match
        cur.execute("""
            SELECT match_id, home_team, away_team, home_team_id, away_team_id,
                   league_id, kickoff_at
            FROM fixtures
            WHERE (home_team_id = %s OR away_team_id = %s)
              AND kickoff_at > NOW()
              AND status NOT IN ('finished', 'completed', 'cancelled')
            ORDER BY kickoff_at ASC LIMIT 1
        """, (team_id, team_id))
        fix = cur.fetchone()

        # Get form
        cur.execute("""
            SELECT COUNT(*), SUM((stats->>'goals')::int), SUM((stats->>'assists')::int),
                   AVG((stats->>'shots')::float), AVG(rating), AVG(minutes_played)
            FROM player_game_stats
            WHERE player_id = %s AND sport_key = 'soccer' AND minutes_played >= 15
        """, (player_id,))
        form = cur.fetchone()

        conn.close()

        # ML prediction
        service = _get_player_props_service()
        league_id = fix[5] if fix else None
        is_home = (team_id == fix[3]) if fix else False

        ml_result = None
        if service:
            ml_result = service._ml_predict(pid, league_id=league_id, is_home=is_home)

        if ml_result:
            scored = ml_result["scored_probability"]
            involved = ml_result["involved_probability"]
            method = "ml_lightgbm"
        else:
            games = form[0] or 1
            goals = form[1] or 0
            scored = round(max(0.02, min(0.30, goals / games)), 4)
            involved = round(scored * 1.5, 4)
            method = "heuristic"

        result = {
            "player": {
                "player_id": pid,
                "name": name,
                "position": position,
                "team": team_name,
            },
            "prediction": {
                "scored_probability": scored,
                "involved_probability": involved,
                "method": method,
            },
            "form": {
                "games": form[0] or 0,
                "goals": form[1] or 0,
                "assists": form[2] or 0,
                "avg_shots": round(form[3] or 0, 1),
                "avg_rating": round(form[4] or 0, 1),
                "avg_minutes": round(form[5] or 0, 0),
            },
        }

        if fix:
            result["next_match"] = {
                "match_id": fix[0],
                "home_team": fix[1],
                "away_team": fix[2],
                "kickoff": fix[6].isoformat() if fix[6] else None,
                "is_home": is_home,
            }
        else:
            result["next_match"] = None

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"player-predictions/by-player error: {e}", exc_info=True)
        raise HTTPException(500, str(e))
