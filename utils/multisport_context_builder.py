"""
MultisportContextBuilder — Assembles full prediction context for NBA / NHL matches.

Fetches:
  - Fixture info (teams, time, league)
  - Recent form (last 10 results per team)
  - Head-to-head record (last 10 meetings)
  - Season standings (W/L, home/away, streak, PPG)
  - Current odds (moneyline, spread, totals)
  - Rest / back-to-back context
"""

import os
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

import psycopg2
import psycopg2.extras

logger = logging.getLogger(__name__)

DB_URL = os.environ.get("DATABASE_URL")


class MultisportContextBuilder:

    def __init__(self, db_url: Optional[str] = None):
        self.db_url = db_url or DB_URL

    def _conn(self):
        return psycopg2.connect(self.db_url, connect_timeout=10)

    def build_context(self, event_id: str, sport_key: str) -> Dict:
        with self._conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                fixture = self._get_fixture(cur, event_id, sport_key)
                if not fixture:
                    return {}

                home = fixture["home_team"]
                away = fixture["away_team"]

                home_form = self._get_recent_form(cur, sport_key, home, limit=10)
                away_form = self._get_recent_form(cur, sport_key, away, limit=10)
                h2h = self._get_h2h(cur, sport_key, home, away, limit=10)
                home_stats = self._get_team_stats(cur, sport_key, home)
                away_stats = self._get_team_stats(cur, sport_key, away)
                odds = self._get_latest_odds(cur, event_id)
                rest = self._get_rest_context(cur, sport_key, home, away, fixture["commence_time"])

        return {
            "match_info": {
                "event_id": event_id,
                "sport_key": sport_key,
                "sport": fixture.get("sport", sport_key),
                "league_name": fixture.get("league_name", ""),
                "home_team": home,
                "away_team": away,
                "commence_time": str(fixture["commence_time"]),
            },
            "home_team": {
                "name": home,
                "recent_form": home_form,
                "season_stats": home_stats,
                "rest": rest.get("home", {}),
            },
            "away_team": {
                "name": away,
                "recent_form": away_form,
                "season_stats": away_stats,
                "rest": rest.get("away", {}),
            },
            "h2h": h2h,
            "odds": odds,
        }

    def _get_fixture(self, cur, event_id: str, sport_key: str) -> Optional[Dict]:
        cur.execute(
            """SELECT event_id, sport, sport_key, league_name,
                      home_team, away_team, commence_time, status
               FROM multisport_fixtures
               WHERE event_id = %s AND sport_key = %s
               LIMIT 1""",
            (event_id, sport_key),
        )
        return cur.fetchone()

    def _get_recent_form(self, cur, sport_key: str, team: str, limit: int = 10) -> List[Dict]:
        cur.execute(
            """SELECT home_team, away_team, home_score, away_score, outcome, match_date
               FROM multisport_training
               WHERE sport_key = %s
                 AND (home_team = %s OR away_team = %s)
                 AND outcome IS NOT NULL
               ORDER BY match_date DESC
               LIMIT %s""",
            (sport_key, team, team, limit),
        )
        rows = cur.fetchall()
        results = []
        for r in rows:
            is_home = r["home_team"] == team
            opponent = r["away_team"] if is_home else r["home_team"]
            team_score = r["home_score"] if is_home else r["away_score"]
            opp_score = r["away_score"] if is_home else r["home_score"]
            won = (is_home and r["outcome"] == "H") or (not is_home and r["outcome"] == "A")
            results.append({
                "opponent": opponent,
                "venue": "Home" if is_home else "Away",
                "result": "W" if won else "L",
                "score": f"{team_score}-{opp_score}",
                "date": str(r["match_date"]),
            })
        return results

    def _get_h2h(self, cur, sport_key: str, home: str, away: str, limit: int = 10) -> List[Dict]:
        cur.execute(
            """SELECT home_team, away_team, home_score, away_score, outcome, match_date
               FROM multisport_training
               WHERE sport_key = %s
                 AND outcome IS NOT NULL
                 AND ((home_team = %s AND away_team = %s) OR (home_team = %s AND away_team = %s))
               ORDER BY match_date DESC
               LIMIT %s""",
            (sport_key, home, away, away, home, limit),
        )
        rows = cur.fetchall()
        meetings = []
        for r in rows:
            winner = r["home_team"] if r["outcome"] == "H" else r["away_team"]
            meetings.append({
                "date": str(r["match_date"]),
                "home_team": r["home_team"],
                "away_team": r["away_team"],
                "score": f"{r['home_score']}-{r['away_score']}",
                "winner": winner,
            })
        return meetings

    def _get_team_stats(self, cur, sport_key: str, team: str) -> Dict:
        cur.execute(
            """SELECT wins, losses, ties, points_for, points_against,
                      home_record, away_record, streak, last_10,
                      conference, division, playoff_position, stats_json
               FROM multisport_team_stats
               WHERE sport_key = %s AND team_name = %s
               ORDER BY stat_date DESC
               LIMIT 1""",
            (sport_key, team),
        )
        row = cur.fetchone()
        if not row:
            return {}

        w = row["wins"] or 0
        l = row["losses"] or 0
        total = w + l
        ppg = round(float(row["points_for"]) / max(total, 1), 1) if row["points_for"] else 0
        papg = round(float(row["points_against"]) / max(total, 1), 1) if row["points_against"] else 0

        return {
            "wins": w,
            "losses": l,
            "win_pct": round(w / max(total, 1), 3),
            "home_record": row["home_record"] or "",
            "away_record": row["away_record"] or "",
            "streak": row["streak"] or "",
            "last_10": row["last_10"] or "",
            "points_per_game": ppg,
            "points_against_per_game": papg,
            "conference": row["conference"] or "",
            "division": row["division"] or "",
            "playoff_position": row["playoff_position"],
        }

    def _get_latest_odds(self, cur, event_id: str) -> Dict:
        cur.execute(
            """SELECT home_odds, away_odds, home_prob, away_prob,
                      home_spread, home_spread_odds, away_spread_odds,
                      total_line, over_odds, under_odds,
                      overround, n_bookmakers, is_consensus, ts_recorded
               FROM multisport_odds_snapshots
               WHERE event_id = %s AND is_consensus = true
               ORDER BY ts_recorded DESC
               LIMIT 1""",
            (event_id,),
        )
        row = cur.fetchone()
        if not row:
            return {}
        return {
            "home_odds": float(row["home_odds"]) if row["home_odds"] else None,
            "away_odds": float(row["away_odds"]) if row["away_odds"] else None,
            "home_prob": float(row["home_prob"]) if row["home_prob"] else None,
            "away_prob": float(row["away_prob"]) if row["away_prob"] else None,
            "home_spread": float(row["home_spread"]) if row["home_spread"] else None,
            "home_spread_odds": float(row["home_spread_odds"]) if row["home_spread_odds"] else None,
            "away_spread_odds": float(row["away_spread_odds"]) if row["away_spread_odds"] else None,
            "total_line": float(row["total_line"]) if row["total_line"] else None,
            "over_odds": float(row["over_odds"]) if row["over_odds"] else None,
            "under_odds": float(row["under_odds"]) if row["under_odds"] else None,
            "overround": float(row["overround"]) if row["overround"] else None,
            "n_bookmakers": row["n_bookmakers"],
            "recorded_at": str(row["ts_recorded"]),
        }

    def _get_rest_context(self, cur, sport_key: str, home: str, away: str, commence_time) -> Dict:
        result = {"home": {}, "away": {}}
        for team, key in [(home, "home"), (away, "away")]:
            cur.execute(
                """SELECT match_date
                   FROM multisport_training
                   WHERE sport_key = %s AND (home_team = %s OR away_team = %s)
                     AND outcome IS NOT NULL
                   ORDER BY match_date DESC
                   LIMIT 1""",
                (sport_key, team, team),
            )
            row = cur.fetchone()
            if row and commence_time:
                last_game = row["match_date"]
                try:
                    ct = commence_time if isinstance(commence_time, datetime) else datetime.fromisoformat(str(commence_time))
                    game_date = ct.date() if hasattr(ct, 'date') else ct
                    delta = (game_date - last_game).days
                except Exception:
                    delta = None
                is_b2b = delta is not None and delta <= 1
                result[key] = {
                    "last_game_date": str(last_game),
                    "rest_days": delta,
                    "is_back_to_back": is_b2b,
                }
            else:
                result[key] = {"last_game_date": None, "rest_days": None, "is_back_to_back": False}
        return result
