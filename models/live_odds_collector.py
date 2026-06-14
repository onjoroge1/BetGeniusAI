"""
In-play odds collector (Snapbet Live Edge, Layer 2).

Pulls live prices from API-Football /odds/live — ONE global call returns every
in-play fixture with its current odds, so this is one request per cycle no matter
how many matches are live. Maps each live fixture to our fixtures.match_id and
stores the markets the Live Edge product needs into live_odds_snapshots.

This is the piece that unblocks edge/CLV: with live prices we can finally compute
model_prob - market_implied and validate strategy specs.

Target markets (API-Football market ids):
  59 = Fulltime Result        → live 1X2  (de-vig → live win-prob market)
  25 = Match Goals (O/U)       → totals (line in handicap)
  36 = Over/Under Line         → totals (alt source/lines)
  69 = Both Teams To Score     → BTTS
Run every ~60s while matches are live (scheduler).
"""

import os
import logging
import requests
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

BASE_URL = "https://api-football-v1.p.rapidapi.com/v3"
TARGET_MARKETS = {59: "Fulltime Result", 25: "Match Goals", 36: "Over/Under Line",
                  69: "Both Teams To Score"}
# Selections we keep per market (skip exotic legs)
_KEEP = {
    59: {"Home", "Draw", "Away"},
    69: {"Yes", "No"},
    25: {"Over", "Under"},
    36: {"Over", "Under"},
}


class LiveOddsCollector:
    def __init__(self):
        self.api_key = os.getenv("RAPIDAPI_KEY")
        self.db_url = os.getenv("DATABASE_URL")
        if not self.api_key:
            raise ValueError("RAPIDAPI_KEY not set")
        self.headers = {"x-rapidapi-key": self.api_key,
                        "x-rapidapi-host": "api-football-v1.p.rapidapi.com"}

    def _fixture_to_match(self, cur, api_fixture_ids: List[int]) -> Dict[int, int]:
        """
        Map API-Football fixture ids → our match_id. Internationals were seeded
        with match_id == api fixture id; clubs map via matches.api_football_fixture_id.
        Returns {api_fixture_id: our_match_id} for fixtures we actually track.
        """
        if not api_fixture_ids:
            return {}
        ids = tuple(set(api_fixture_ids))
        mapping = {}
        # direct: fixtures.match_id IS the api id (WC/international seeding)
        cur.execute("SELECT match_id, league_id FROM fixtures WHERE match_id = ANY(%s)", (list(ids),))
        for mid, lid in cur.fetchall():
            mapping[mid] = (mid, lid)
        # club: via matches table
        cur.execute("""
            SELECT m.api_football_fixture_id, m.match_id, f.league_id
            FROM matches m JOIN fixtures f ON f.match_id = m.match_id
            WHERE m.api_football_fixture_id = ANY(%s)
        """, (list(ids),))
        for api_id, mid, lid in cur.fetchall():
            mapping[api_id] = (mid, lid)
        return mapping

    def collect_live_odds(self) -> Dict:
        """One cycle: fetch all in-play odds, store the ones for tracked matches."""
        stats = {"live_fixtures": 0, "tracked": 0, "rows": 0, "errors": 0}
        try:
            r = requests.get(f"{BASE_URL}/odds/live", headers=self.headers, timeout=30)
            if r.status_code != 200:
                logger.warning(f"live odds API {r.status_code}: {r.text[:120]}")
                stats["errors"] = 1
                return stats
            resp = r.json().get("response", [])
        except Exception as e:
            logger.error(f"live odds fetch failed: {e}")
            stats["errors"] = 1
            return stats

        stats["live_fixtures"] = len(resp)
        if not resp:
            return stats

        import psycopg2
        conn = psycopg2.connect(self.db_url)
        cur = conn.cursor()
        try:
            api_ids = [fx.get("fixture", {}).get("id") for fx in resp if fx.get("fixture")]
            fmap = self._fixture_to_match(cur, [i for i in api_ids if i])
            now = datetime.now(timezone.utc)

            for fx in resp:
                api_id = fx.get("fixture", {}).get("id")
                if api_id not in fmap:
                    continue  # not a match we track
                match_id, league_id = fmap[api_id]
                stats["tracked"] += 1
                minute = (fx.get("fixture", {}).get("status", {}) or {}).get("elapsed")

                for mk in fx.get("odds", []):
                    mid = mk.get("id")
                    if mid not in TARGET_MARKETS:
                        continue
                    keep = _KEEP.get(mid, set())
                    for v in mk.get("values", []):
                        sel = v.get("value")
                        odd = v.get("odd")
                        # market 59/69 use direct selection names; 25/36 use Over/Under
                        sel_norm = sel
                        if mid in (25, 36) and sel not in keep:
                            continue
                        if mid in (59, 69) and sel not in keep:
                            continue
                        try:
                            od = float(odd)
                        except (TypeError, ValueError):
                            continue
                        if od <= 1.0:
                            continue
                        line = v.get("handicap")
                        try:
                            line = float(line) if line is not None else None
                        except (TypeError, ValueError):
                            line = None
                        cur.execute("""
                            INSERT INTO live_odds_snapshots
                              (match_id, league_id, ts_snapshot, minute, market_id,
                               market_name, selection, line, odds_decimal, implied_prob)
                            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        """, (match_id, league_id, now, minute, mid,
                              TARGET_MARKETS[mid], sel_norm, line, round(od, 3),
                              round(1.0 / od, 4)))
                        stats["rows"] += 1
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"live odds store failed: {e}")
            stats["errors"] += 1
        finally:
            cur.close()
            conn.close()

        logger.info(f"📈 Live odds: {stats['live_fixtures']} in-play, "
                    f"{stats['tracked']} tracked, {stats['rows']} rows stored")
        return stats


def collect_live_odds_job() -> Dict:
    return LiveOddsCollector().collect_live_odds()
