"""
Backfill team_injury_summary from player_injuries table.

player_injuries.team_name matches fixtures.home_team / fixtures.away_team exactly,
which is the correct linkage — team IDs use different namespaces between the two tables.

This job upserts only rows where total_impact_score = 0 (stale placeholders created
by the scheduler with no underlying data) so it never overwrites fresh values.

Run:
    python jobs/backfill_team_injury_summary.py
"""

import os
import sys
import logging
import psycopg2

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

HOME_SQL = """
    INSERT INTO team_injury_summary
        (match_id, team_id, team_type, n_injured, n_suspended,
         total_impact_score, key_players_out, ts_computed)
    SELECT
        pi.fixture_id                            AS match_id,
        f.home_team_id                           AS team_id,
        'home'                                   AS team_type,
        COUNT(*)                                 AS n_injured,
        0                                        AS n_suspended,
        COALESCE(SUM(pi.player_value_rating), 0) AS total_impact_score,
        NULL                                     AS key_players_out,
        NOW()                                    AS ts_computed
    FROM player_injuries pi
    JOIN fixtures f ON pi.fixture_id = f.match_id
                   AND pi.team_name  = f.home_team
    WHERE f.status = 'finished'
    GROUP BY pi.fixture_id, f.home_team_id
    ON CONFLICT (match_id, team_id) DO UPDATE SET
        n_injured          = EXCLUDED.n_injured,
        total_impact_score = EXCLUDED.total_impact_score,
        ts_computed        = EXCLUDED.ts_computed
    WHERE team_injury_summary.total_impact_score = 0
"""

AWAY_SQL = """
    INSERT INTO team_injury_summary
        (match_id, team_id, team_type, n_injured, n_suspended,
         total_impact_score, key_players_out, ts_computed)
    SELECT
        pi.fixture_id                            AS match_id,
        f.away_team_id                           AS team_id,
        'away'                                   AS team_type,
        COUNT(*)                                 AS n_injured,
        0                                        AS n_suspended,
        COALESCE(SUM(pi.player_value_rating), 0) AS total_impact_score,
        NULL                                     AS key_players_out,
        NOW()                                    AS ts_computed
    FROM player_injuries pi
    JOIN fixtures f ON pi.fixture_id = f.match_id
                   AND pi.team_name  = f.away_team
    WHERE f.status = 'finished'
    GROUP BY pi.fixture_id, f.away_team_id
    ON CONFLICT (match_id, team_id) DO UPDATE SET
        n_injured          = EXCLUDED.n_injured,
        total_impact_score = EXCLUDED.total_impact_score,
        ts_computed        = EXCLUDED.ts_computed
    WHERE team_injury_summary.total_impact_score = 0
"""

COVERAGE_SQL = """
    SELECT
        COUNT(DISTINCT f.match_id)                                                         AS finished,
        COUNT(DISTINCT tis.match_id) FILTER (WHERE tis.total_impact_score > 0)            AS with_data,
        ROUND(100.0 * COUNT(DISTINCT tis.match_id) FILTER (WHERE tis.total_impact_score > 0)
              / NULLIF(COUNT(DISTINCT f.match_id), 0), 1)                                  AS pct
    FROM fixtures f
    LEFT JOIN team_injury_summary tis ON f.match_id = tis.match_id
    WHERE f.status = 'finished'
"""


def run_backfill(database_url: str) -> dict:
    conn = psycopg2.connect(database_url)
    conn.autocommit = True
    cur = conn.cursor()

    cur.execute(HOME_SQL)
    home_updated = cur.rowcount
    logger.info(f"Home teams updated: {home_updated}")

    cur.execute(AWAY_SQL)
    away_updated = cur.rowcount
    logger.info(f"Away teams updated: {away_updated}")

    cur.execute(COVERAGE_SQL)
    row = cur.fetchone()
    finished, with_data, pct = row if row else (0, 0, 0)
    logger.info(f"Coverage: {with_data}/{finished} finished matches ({pct}%)")

    cur.close()
    conn.close()

    return {
        'home_updated': home_updated,
        'away_updated': away_updated,
        'coverage_pct': float(pct or 0),
        'matches_with_data': int(with_data or 0),
    }


if __name__ == "__main__":
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        logger.error("DATABASE_URL not set")
        sys.exit(1)
    result = run_backfill(db_url)
    logger.info(f"Done: {result}")
