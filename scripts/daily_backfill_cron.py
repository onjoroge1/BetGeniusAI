#!/usr/bin/env python3
"""
Daily Backfill for Match Context and Historical Odds

Runs daily to:
1. Backfill match_context for new matches from last 30 days
2. Preserve historical odds snapshots for CLV analysis
3. Update TBD fixtures with resolved team information

Designed to run as a cron job or scheduled workflow.

Usage:
    python scripts/daily_backfill_cron.py
    
Schedule (crontab):
    # Run daily at 3 AM UTC
    0 3 * * * cd /path/to/project && python scripts/daily_backfill_cron.py
"""

import os
import sys
import logging
from datetime import datetime, timedelta
import psycopg2
from psycopg2.extras import RealDictCursor

sys.path.append('.')
from agents.fetchers.interfaces import DatabaseContextComputer

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class DailyBackfillJob:
    """Daily backfill for match context and historical odds preservation"""
    
    def __init__(self):
        self.database_url = os.getenv('DATABASE_URL')
        if not self.database_url:
            raise ValueError("DATABASE_URL not set")
        
        self.conn = psycopg2.connect(self.database_url)
        self.context_computer = DatabaseContextComputer(self.database_url)
        
        self.stats = {
            'match_context_new': 0,
            'match_context_updated': 0,
            'historical_odds_preserved': 0,
            'errors': 0
        }
    
    def get_recent_matches_needing_context(self, days: int = 30) -> list:
        """Find recent matches missing context data"""
        cutoff_date = datetime.now() - timedelta(days=days)
        
        query = """
            SELECT 
                tm.match_id,
                tm.match_date,
                tm.league_id,
                mc.match_id as has_context
            FROM training_matches tm
            LEFT JOIN match_context mc ON tm.match_id = mc.match_id
            WHERE tm.match_date >= %s
              AND tm.outcome IS NOT NULL
            ORDER BY tm.match_date DESC
        """
        
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, (cutoff_date,))
            matches = cur.fetchall()
        
        return matches
    
    def upsert_match_context(self, match_id: int, context_data: dict) -> str:
        """Insert or update match_context, return action taken"""
        # Check if exists
        check_query = "SELECT match_id FROM match_context WHERE match_id = %s"
        
        with self.conn.cursor() as cur:
            cur.execute(check_query, (match_id,))
            exists = cur.fetchone() is not None
        
        # Upsert
        upsert_query = """
            INSERT INTO match_context (
                match_id,
                rest_days_home,
                rest_days_away,
                schedule_congestion_home_7d,
                schedule_congestion_away_7d,
                derby_flag
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (match_id)
            DO UPDATE SET
                rest_days_home = EXCLUDED.rest_days_home,
                rest_days_away = EXCLUDED.rest_days_away,
                schedule_congestion_home_7d = EXCLUDED.schedule_congestion_home_7d,
                schedule_congestion_away_7d = EXCLUDED.schedule_congestion_away_7d,
                derby_flag = EXCLUDED.derby_flag,
                created_at = NOW()
        """
        
        with self.conn.cursor() as cur:
            cur.execute(upsert_query, (
                match_id,
                context_data['rest_days_home'],
                context_data['rest_days_away'],
                context_data['schedule_congestion_home_7d'],
                context_data['schedule_congestion_away_7d'],
                context_data['derby_flag']
            ))
            self.conn.commit()
        
        return 'updated' if exists else 'inserted'
    
    def preserve_historical_odds(self, days: int = 7):
        """Preserve historical odds snapshots for recent matches"""
        cutoff_date = datetime.now() - timedelta(days=days)
        
        # Find matches with odds data but no historical preservation
        query = """
            SELECT DISTINCT
                o.match_id,
                COUNT(*) as odds_count
            FROM odds o
            JOIN fixtures f ON o.match_id = f.fixture_id
            WHERE f.kickoff_at >= %s
              AND o.market_type IN ('h2h', 'spreads', 'totals')
            GROUP BY o.match_id
            HAVING COUNT(*) > 0
            ORDER BY o.match_id DESC
            LIMIT 100
        """
        
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, (cutoff_date,))
            matches = cur.fetchall()
        
        logger.info(f"   Found {len(matches)} matches with recent odds data")
        
        # For each match, ensure historical odds are preserved
        for match in matches:
            match_id = match['match_id']
            
            # Check if historical_odds snapshot exists
            check_query = """
                SELECT COUNT(*) as count 
                FROM historical_odds 
                WHERE match_id = %s
            """
            
            with self.conn.cursor() as cur:
                cur.execute(check_query, (match_id,))
                snapshot_exists = cur.fetchone()[0] > 0
            
            if not snapshot_exists:
                # Create snapshot from current odds
                snapshot_query = """
                    INSERT INTO historical_odds (
                        match_id,
                        market_type,
                        outcome,
                        bookmaker,
                        odds_value,
                        snapshot_time
                    )
                    SELECT 
                        match_id,
                        market_type,
                        outcome,
                        bookmaker,
                        odds_decimal,
                        NOW() as snapshot_time
                    FROM odds
                    WHERE match_id = %s
                      AND market_type IN ('h2h', 'spreads', 'totals')
                    ON CONFLICT (match_id, market_type, outcome, bookmaker, snapshot_time) 
                    DO NOTHING
                """
                
                try:
                    with self.conn.cursor() as cur:
                        cur.execute(snapshot_query, (match_id,))
                        self.conn.commit()
                        self.stats['historical_odds_preserved'] += 1
                except Exception as e:
                    logger.warning(f"   Failed to preserve odds for match {match_id}: {e}")
    
    def backfill_match_context(self):
        """Backfill match context for recent matches"""
        logger.info("\n📊 MATCH CONTEXT BACKFILL (Last 30 Days)")
        logger.info("="*60)
        
        matches = self.get_recent_matches_needing_context(days=30)
        logger.info(f"Found {len(matches)} recent matches")
        
        for match in matches:
            match_id = match['match_id']
            
            try:
                # Compute context
                result = self.context_computer.compute(match_id)
                
                if result.success:
                    action = self.upsert_match_context(match_id, result.data)
                    
                    if action == 'inserted':
                        self.stats['match_context_new'] += 1
                    else:
                        self.stats['match_context_updated'] += 1
                else:
                    self.stats['errors'] += 1
                    logger.warning(f"   Failed match {match_id}: {result.error}")
                    
            except Exception as e:
                self.stats['errors'] += 1
                logger.error(f"   Error processing match {match_id}: {e}")
        
        logger.info(f"✅ Match context: {self.stats['match_context_new']} new, {self.stats['match_context_updated']} updated")
    
    def run(self):
        """Run daily backfill job"""
        logger.info("="*70)
        logger.info(f"  DAILY BACKFILL JOB - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info("="*70)
        
        try:
            # Step 1: Backfill match context
            self.backfill_match_context()
            
            # Step 2: Preserve historical odds
            logger.info("\n📊 HISTORICAL ODDS PRESERVATION (Last 7 Days)")
            logger.info("="*60)
            self.preserve_historical_odds(days=7)
            logger.info(f"✅ Preserved odds for {self.stats['historical_odds_preserved']} matches")
            
            # Summary
            logger.info("\n" + "="*70)
            logger.info("  DAILY BACKFILL SUMMARY")
            logger.info("="*70)
            logger.info(f"Match Context - New:      {self.stats['match_context_new']}")
            logger.info(f"Match Context - Updated:  {self.stats['match_context_updated']}")
            logger.info(f"Historical Odds Preserved: {self.stats['historical_odds_preserved']}")
            logger.info(f"Errors:                   {self.stats['errors']}")
            logger.info("="*70)
            logger.info("✅ Daily backfill complete!")
            
        except Exception as e:
            logger.error(f"❌ Daily backfill failed: {e}")
            logger.exception(e)
            raise
        finally:
            self.conn.close()


def main():
    """Run daily backfill"""
    try:
        job = DailyBackfillJob()
        job.run()
        sys.exit(0)
        
    except Exception as e:
        logger.error(f"❌ Job failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
