"""
BetGenius AI - Match Context Builder (V2)

Automatically builds match_context_v2 entries for new matches with strict
pre-match timestamps to prevent data leakage.

This service:
1. Detects new matches without context data
2. Computes rest days and schedule congestion using ONLY past matches
3. Stores results in match_context_v2 with as_of_time = match_date - 1 hour

Design:
- Can run as part of automated scheduler (every N minutes)
- Can run standalone for backfill
- Guaranteed leak-free via strict time-based filtering
"""

import logging
import psycopg2
import os
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class MatchContextBuilder:
    """Builds match_context_v2 entries for matches"""
    
    def __init__(self, database_url: Optional[str] = None):
        """Initialize context builder with database connection"""
        self.database_url = database_url or os.environ.get('DATABASE_URL')
        if not self.database_url:
            raise ValueError("DATABASE_URL not provided")
    
    def build_context_for_new_matches(self, lookback_hours: int = 48) -> int:
        """
        Build context for recent matches that don't have context yet
        
        Args:
            lookback_hours: How far back to check for new matches (default: 48h)
        
        Returns:
            Number of new context rows created
        """
        try:
            with psycopg2.connect(self.database_url) as conn:
                with conn.cursor() as cursor:
                    # Find matches without context that are upcoming or recent
                    # Use fixtures table as primary source (more reliable for upcoming matches)
                    # Falls back to matches table for historical data
                    cursor.execute("""
                        SELECT * FROM (
                            SELECT f.match_id, f.home_team_id, f.away_team_id, f.kickoff_at as match_date
                            FROM fixtures f
                            LEFT JOIN match_context_v2 mc ON f.match_id = mc.match_id
                            WHERE mc.match_id IS NULL
                              AND f.kickoff_at > NOW() - INTERVAL '%s hours'
                            
                            UNION
                            
                            SELECT m.match_id, m.home_team_id, m.away_team_id, m.match_date_utc as match_date
                            FROM matches m
                            LEFT JOIN match_context_v2 mc ON m.match_id = mc.match_id
                            WHERE mc.match_id IS NULL
                              AND m.home_team_id IS NOT NULL
                              AND m.away_team_id IS NOT NULL
                              AND m.match_date_utc > NOW() - INTERVAL '%s hours'
                        ) combined
                        ORDER BY match_date
                    """ % (lookback_hours, lookback_hours))
                    
                    matches_needing_context = cursor.fetchall()
                    
                    if not matches_needing_context:
                        logger.debug("No new matches needing context")
                        return 0
                    
                    logger.info(f"🔨 Building context for {len(matches_needing_context)} matches...")
                    
                    # Build context using leak-free SQL
                    # Use fixtures as primary source, with team name matching for historical lookups
                    # Fallback to team ID matching for matches table
                    cursor.execute("""
                        WITH base AS (
                            SELECT * FROM (
                                -- Use fixtures table as primary source (has team names for upcoming matches)
                                SELECT
                                    f.match_id,
                                    f.home_team_id,
                                    f.away_team_id,
                                    f.home_team,
                                    f.away_team,
                                    f.kickoff_at as match_date_utc
                                FROM fixtures f
                                LEFT JOIN match_context_v2 mc ON f.match_id = mc.match_id
                                WHERE mc.match_id IS NULL
                                  AND f.kickoff_at > NOW() - INTERVAL '%s hours'
                                
                                UNION
                                
                                -- Fallback to matches table for historical data with team IDs
                                SELECT
                                    m.match_id,
                                    m.home_team_id,
                                    m.away_team_id,
                                    NULL as home_team,
                                    NULL as away_team,
                                    m.match_date_utc
                                FROM matches m
                                LEFT JOIN match_context_v2 mc ON m.match_id = mc.match_id
                                WHERE mc.match_id IS NULL
                                  AND m.home_team_id IS NOT NULL
                                  AND m.away_team_id IS NOT NULL
                                  AND m.match_date_utc > NOW() - INTERVAL '%s hours'
                            ) combined
                        ),
                        
                        -- Look up previous matches using team names (for fixtures) or team IDs (for matches)
                        last_home_match AS (
                            SELECT
                                b.match_id,
                                MAX(GREATEST(
                                    COALESCE(pf.kickoff_at, '1900-01-01'::timestamp),
                                    COALESCE(pm.match_date_utc, '1900-01-01'::timestamp)
                                )) AS prev_home_match_date
                            FROM base b
                            LEFT JOIN fixtures pf
                                ON b.home_team IS NOT NULL
                               AND (pf.home_team = b.home_team OR pf.away_team = b.home_team)
                               AND pf.kickoff_at < b.match_date_utc
                               AND pf.status = 'finished'
                            LEFT JOIN matches pm
                                ON b.home_team_id IS NOT NULL
                               AND (pm.home_team_id = b.home_team_id OR pm.away_team_id = b.home_team_id)
                               AND pm.match_date_utc < b.match_date_utc
                            GROUP BY b.match_id
                        ),
                        
                        last_away_match AS (
                            SELECT
                                b.match_id,
                                MAX(GREATEST(
                                    COALESCE(pf.kickoff_at, '1900-01-01'::timestamp),
                                    COALESCE(pm.match_date_utc, '1900-01-01'::timestamp)
                                )) AS prev_away_match_date
                            FROM base b
                            LEFT JOIN fixtures pf
                                ON b.away_team IS NOT NULL
                               AND (pf.home_team = b.away_team OR pf.away_team = b.away_team)
                               AND pf.kickoff_at < b.match_date_utc
                               AND pf.status = 'finished'
                            LEFT JOIN matches pm
                                ON b.away_team_id IS NOT NULL
                               AND (pm.home_team_id = b.away_team_id OR pm.away_team_id = b.away_team_id)
                               AND pm.match_date_utc < b.match_date_utc
                            GROUP BY b.match_id
                        ),
                        
                        home_congestion AS (
                            SELECT
                                b.match_id,
                                COUNT(DISTINCT COALESCE(pf.match_id, pm.match_id)) FILTER (
                                    WHERE COALESCE(pf.kickoff_at, pm.match_date_utc) >= b.match_date_utc - interval '3 days'
                                      AND COALESCE(pf.kickoff_at, pm.match_date_utc) < b.match_date_utc
                                ) AS matches_home_last_3d,
                                COUNT(DISTINCT COALESCE(pf.match_id, pm.match_id)) FILTER (
                                    WHERE COALESCE(pf.kickoff_at, pm.match_date_utc) >= b.match_date_utc - interval '7 days'
                                      AND COALESCE(pf.kickoff_at, pm.match_date_utc) < b.match_date_utc
                                ) AS matches_home_last_7d
                            FROM base b
                            LEFT JOIN fixtures pf
                                ON b.home_team IS NOT NULL
                               AND (pf.home_team = b.home_team OR pf.away_team = b.home_team)
                               AND pf.kickoff_at < b.match_date_utc
                               AND pf.status = 'finished'
                            LEFT JOIN matches pm
                                ON b.home_team_id IS NOT NULL
                               AND (pm.home_team_id = b.home_team_id OR pm.away_team_id = b.home_team_id)
                               AND pm.match_date_utc < b.match_date_utc
                            GROUP BY b.match_id
                        ),
                        
                        away_congestion AS (
                            SELECT
                                b.match_id,
                                COUNT(DISTINCT COALESCE(pf.match_id, pm.match_id)) FILTER (
                                    WHERE COALESCE(pf.kickoff_at, pm.match_date_utc) >= b.match_date_utc - interval '3 days'
                                      AND COALESCE(pf.kickoff_at, pm.match_date_utc) < b.match_date_utc
                                ) AS matches_away_last_3d,
                                COUNT(DISTINCT COALESCE(pf.match_id, pm.match_id)) FILTER (
                                    WHERE COALESCE(pf.kickoff_at, pm.match_date_utc) >= b.match_date_utc - interval '7 days'
                                      AND COALESCE(pf.kickoff_at, pm.match_date_utc) < b.match_date_utc
                                ) AS matches_away_last_7d
                            FROM base b
                            LEFT JOIN fixtures pf
                                ON b.away_team IS NOT NULL
                               AND (pf.home_team = b.away_team OR pf.away_team = b.away_team)
                               AND pf.kickoff_at < b.match_date_utc
                               AND pf.status = 'finished'
                            LEFT JOIN matches pm
                                ON b.away_team_id IS NOT NULL
                               AND (pm.home_team_id = b.away_team_id OR pm.away_team_id = b.away_team_id)
                               AND pm.match_date_utc < b.match_date_utc
                            GROUP BY b.match_id
                        )
                        
                        INSERT INTO match_context_v2 (
                            match_id,
                            as_of_time,
                            rest_days_home,
                            rest_days_away,
                            matches_home_last_3d,
                            matches_home_last_7d,
                            matches_away_last_3d,
                            matches_away_last_7d,
                            derby_flag,
                            generation_version
                        )
                        SELECT
                            b.match_id,
                            b.match_date_utc - interval '1 hour' AS as_of_time,
                            CASE 
                                WHEN lhm.prev_home_match_date <= '1900-01-01'::timestamp THEN 30.0
                                ELSE COALESCE(EXTRACT(EPOCH FROM (b.match_date_utc - lhm.prev_home_match_date)) / 86400.0, 30.0)
                            END AS rest_days_home,
                            CASE 
                                WHEN lam.prev_away_match_date <= '1900-01-01'::timestamp THEN 30.0
                                ELSE COALESCE(EXTRACT(EPOCH FROM (b.match_date_utc - lam.prev_away_match_date)) / 86400.0, 30.0)
                            END AS rest_days_away,
                            COALESCE(hc.matches_home_last_3d, 0),
                            COALESCE(hc.matches_home_last_7d, 0),
                            COALESCE(ac.matches_away_last_3d, 0),
                            COALESCE(ac.matches_away_last_7d, 0),
                            FALSE AS derby_flag,
                            2 AS generation_version
                        FROM base b
                        LEFT JOIN last_home_match   lhm ON lhm.match_id = b.match_id
                        LEFT JOIN last_away_match   lam ON lam.match_id = b.match_id
                        LEFT JOIN home_congestion   hc  ON hc.match_id  = b.match_id
                        LEFT JOIN away_congestion   ac  ON ac.match_id  = b.match_id
                        ON CONFLICT (match_id) DO NOTHING
                    """ % (lookback_hours, lookback_hours))
                    
                    rows_inserted = cursor.rowcount
                    conn.commit()
                    
                    if rows_inserted > 0:
                        logger.info(f"✅ Built context for {rows_inserted} matches")
                    
                    return rows_inserted
                    
        except Exception as e:
            logger.error(f"❌ Failed to build match context: {e}")
            return 0
    
    def validate_context_integrity(self) -> dict:
        """
        Validate that match_context_v2 has no post-match contamination
        
        Returns:
            Dictionary with validation results
        """
        try:
            with psycopg2.connect(self.database_url) as conn:
                with conn.cursor() as cursor:
                    # Check for post-match contamination
                    cursor.execute("""
                        SELECT COUNT(*) AS bad_rows
                        FROM match_context_v2 mc
                        JOIN matches m ON mc.match_id = m.match_id
                        WHERE mc.as_of_time > m.match_date_utc
                    """)
                    
                    bad_rows = cursor.fetchone()[0]
                    
                    # Get total rows
                    cursor.execute("SELECT COUNT(*) FROM match_context_v2")
                    total_rows = cursor.fetchone()[0]
                    
                    # Get stats
                    cursor.execute("""
                        SELECT 
                            ROUND(AVG(rest_days_home), 2) as avg_rest_home,
                            ROUND(AVG(rest_days_away), 2) as avg_rest_away,
                            ROUND(AVG(matches_home_last_7d), 2) as avg_congestion_home,
                            ROUND(AVG(matches_away_last_7d), 2) as avg_congestion_away
                        FROM match_context_v2
                    """)
                    
                    stats = cursor.fetchone()
                    
                    return {
                        'total_rows': total_rows,
                        'contaminated_rows': bad_rows,
                        'clean_percentage': 100.0 if bad_rows == 0 else (100.0 * (total_rows - bad_rows) / total_rows),
                        'avg_rest_home': float(stats[0]) if stats[0] else 0.0,
                        'avg_rest_away': float(stats[1]) if stats[1] else 0.0,
                        'avg_congestion_home': float(stats[2]) if stats[2] else 0.0,
                        'avg_congestion_away': float(stats[3]) if stats[3] else 0.0,
                        'is_clean': bad_rows == 0
                    }
                    
        except Exception as e:
            logger.error(f"❌ Validation failed: {e}")
            return {'error': str(e)}


def build_context_for_recent_matches(lookback_hours: int = 48) -> int:
    """
    Convenience function to build context for recent matches
    
    Args:
        lookback_hours: How far back to check (default: 48h)
    
    Returns:
        Number of rows created
    """
    builder = MatchContextBuilder()
    return builder.build_context_for_new_matches(lookback_hours)


if __name__ == "__main__":
    # Standalone execution
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    print("=" * 80)
    print("  MATCH CONTEXT BUILDER (V2)")
    print("=" * 80)
    print()
    
    builder = MatchContextBuilder()
    
    # Build context
    rows_created = builder.build_context_for_new_matches(lookback_hours=168)  # 1 week
    
    # Validate
    print()
    print("Running validation...")
    validation = builder.validate_context_integrity()
    
    print()
    print("=" * 80)
    print("  VALIDATION RESULTS")
    print("=" * 80)
    print(f"Total rows: {validation.get('total_rows', 0)}")
    print(f"Contaminated rows: {validation.get('contaminated_rows', 0)}")
    print(f"Clean percentage: {validation.get('clean_percentage', 0):.2f}%")
    print()
    print(f"Average rest days (home): {validation.get('avg_rest_home', 0):.2f}")
    print(f"Average rest days (away): {validation.get('avg_rest_away', 0):.2f}")
    print(f"Average congestion (home): {validation.get('avg_congestion_home', 0):.2f}")
    print(f"Average congestion (away): {validation.get('avg_congestion_away', 0):.2f}")
    print()
    
    if validation.get('is_clean'):
        print("✅ VALIDATION PASSED - No post-match contamination detected")
    else:
        print("❌ VALIDATION FAILED - Post-match contamination detected!")
    
    print("=" * 80)
