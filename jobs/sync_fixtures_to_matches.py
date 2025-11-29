"""
Fixtures to Matches Sync Job
Syncs finished fixtures with results to the matches table.

This job:
1. Finds finished fixtures not yet in matches table
2. Joins with match_results to get scores
3. Inserts into matches table with proper field mapping

Runs every 15 minutes via scheduler.
"""

import os
import logging
import psycopg2
from datetime import datetime

logger = logging.getLogger(__name__)


async def sync_fixtures_to_matches_job() -> dict:
    """
    Sync finished fixtures to matches table.
    
    Returns:
        dict with synced_count and skipped_count
    """
    start_time = datetime.now()
    synced = 0
    skipped = 0
    errors = 0
    
    try:
        conn = psycopg2.connect(os.environ.get('DATABASE_URL'))
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                f.match_id,
                f.league_id,
                f.season,
                f.kickoff_at,
                f.home_team_id,
                f.away_team_id,
                mr.home_goals,
                mr.away_goals,
                mr.outcome
            FROM fixtures f
            INNER JOIN match_results mr ON f.match_id = mr.match_id
            WHERE f.status = 'finished'
            AND f.home_team_id IS NOT NULL
            AND f.away_team_id IS NOT NULL
            AND NOT EXISTS (
                SELECT 1 FROM matches m WHERE m.match_id = f.match_id
            )
            LIMIT 100
        """)
        
        rows = cursor.fetchall()
        
        if not rows:
            logger.info("🔄 SYNC: No fixtures to sync (all up to date)")
            cursor.close()
            conn.close()
            return {"synced": 0, "skipped": 0, "errors": 0, "duration_ms": 0}
        
        logger.info(f"🔄 SYNC: Found {len(rows)} fixtures to sync to matches")
        
        for row in rows:
            match_id, league_id, season, kickoff_at, home_team_id, away_team_id, home_goals, away_goals, outcome = row
            
            if home_goals is None or away_goals is None:
                skipped += 1
                continue
            
            normalized_outcome = None
            if outcome:
                outcome_upper = outcome.upper()
                if outcome_upper in ('H', 'HOME'):
                    normalized_outcome = 'H'
                elif outcome_upper in ('D', 'DRAW'):
                    normalized_outcome = 'D'
                elif outcome_upper in ('A', 'AWAY'):
                    normalized_outcome = 'A'
            
            if not normalized_outcome:
                if home_goals > away_goals:
                    normalized_outcome = 'H'
                elif home_goals < away_goals:
                    normalized_outcome = 'A'
                else:
                    normalized_outcome = 'D'
            
            try:
                cursor.execute("""
                    INSERT INTO matches (
                        match_id, league_id, season, match_date_utc,
                        home_team_id, away_team_id,
                        home_goals, away_goals, outcome,
                        api_football_fixture_id
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (match_id) DO NOTHING
                """, (
                    match_id, league_id, season, 
                    kickoff_at.replace(tzinfo=None) if kickoff_at else None,
                    home_team_id, away_team_id,
                    home_goals, away_goals, normalized_outcome,
                    match_id
                ))
                synced += 1
            except Exception as e:
                logger.warning(f"❌ SYNC: Failed to insert match {match_id}: {e}")
                errors += 1
        
        conn.commit()
        cursor.close()
        conn.close()
        
        duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
        logger.info(f"✅ SYNC: Completed - synced={synced}, skipped={skipped}, errors={errors}, duration={duration_ms}ms")
        
        return {
            "synced": synced,
            "skipped": skipped,
            "errors": errors,
            "duration_ms": duration_ms
        }
        
    except Exception as e:
        logger.error(f"❌ SYNC: Job failed: {e}")
        return {
            "synced": synced,
            "skipped": skipped,
            "errors": errors + 1,
            "error": str(e)
        }
