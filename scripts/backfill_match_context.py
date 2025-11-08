"""
Phase 2 Data Collection - Match Context Backfill

Backfills match_context table with:
- Rest days (home/away)
- Schedule congestion (7-day window)
- Derby detection

Uses DatabaseContextComputer (no API calls needed!)

CRITICAL: Only processes matches with REAL pre-kickoff odds from odds_real_consensus.
The odds_real_consensus view is built from odds_snapshots (authentic data).
Never use odds_consensus table - it contains fake/backdated data!
"""

import sys
import os
import logging
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor

sys.path.append('.')
from agents.fetchers.interfaces import DatabaseContextComputer

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class MatchContextBackfiller:
    """Backfill match_context using DatabaseContextComputer"""
    
    def __init__(self):
        self.database_url = os.getenv('DATABASE_URL')
        if not self.database_url:
            raise ValueError("DATABASE_URL not set")
        
        self.conn = psycopg2.connect(self.database_url)
        self.context_computer = DatabaseContextComputer(self.database_url)
        
        # Stats
        self.stats = {
            'total_matches': 0,
            'already_exists': 0,
            'success': 0,
            'failed': 0,
            'start_time': None,
            'end_time': None
        }
    
    def discover_missing_matches(self, limit: int = 10000) -> list:
        """Find matches missing context data (only for matches with REAL odds)"""
        logger.info("🔍 Discovering matches without context data...")
        logger.info("   ⚠️  ONLY processing matches with REAL pre-kickoff odds from odds_real_consensus")
        
        query = """
            SELECT 
                tm.match_id,
                tm.league_id,
                tm.season,
                tm.match_date
            FROM training_matches tm
            -- CRITICAL: Only backfill matches with REAL odds
            INNER JOIN odds_real_consensus orc ON tm.match_id = orc.match_id
            LEFT JOIN match_context mc ON tm.match_id = mc.match_id
            WHERE mc.match_id IS NULL
              AND tm.match_date >= '2020-01-01'
              AND tm.match_date IS NOT NULL
              AND tm.outcome IS NOT NULL
            ORDER BY tm.match_date DESC
            LIMIT %s
        """
        
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, (limit,))
            matches = cur.fetchall()
        
        logger.info(f"✅ Found {len(matches)} matches needing context data (with real odds)")
        return matches
    
    def upsert_context(self, match_id: int, context_data: dict):
        """Insert or update match_context"""
        query = """
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
            cur.execute(query, (
                match_id,
                context_data['rest_days_home'],
                context_data['rest_days_away'],
                context_data['schedule_congestion_home_7d'],
                context_data['schedule_congestion_away_7d'],
                context_data['derby_flag']
            ))
            self.conn.commit()
    
    def record_lineage(self, match_id: int, source: str, success: bool, error: str = None):
        """Record data lineage"""
        query = """
            INSERT INTO data_lineage (
                entity_type,
                entity_id,
                source,
                success,
                error_message
            )
            VALUES (%s, %s, %s, %s, %s)
        """
        
        with self.conn.cursor() as cur:
            cur.execute(query, (
                'match',
                str(match_id),
                source,
                success,
                error
            ))
            self.conn.commit()
    
    def backfill_batch(self, matches: list, batch_size: int = 100):
        """Backfill a batch of matches"""
        total = len(matches)
        logger.info(f"\n🚀 Starting backfill of {total} matches...")
        logger.info(f"   Batch size: {batch_size}")
        
        for i, match in enumerate(matches, 1):
            match_id = match['match_id']
            
            try:
                # Compute context from database
                result = self.context_computer.compute(match_id)
                
                if result.success:
                    # Upsert to database
                    self.upsert_context(match_id, result.data)
                    
                    # Record success
                    self.record_lineage(match_id, 'database-computed', True)
                    
                    self.stats['success'] += 1
                    
                    if i % batch_size == 0:
                        logger.info(f"   ✅ Processed {i}/{total} matches ({self.stats['success']} success, {self.stats['failed']} failed)")
                else:
                    self.stats['failed'] += 1
                    self.record_lineage(match_id, 'database-computed', False, result.error)
                    logger.warning(f"   ⚠️  Failed match {match_id}: {result.error}")
                    
            except Exception as e:
                self.stats['failed'] += 1
                self.record_lineage(match_id, 'database-computed', False, str(e))
                logger.error(f"   ❌ Error processing match {match_id}: {e}")
        
        logger.info(f"\n✅ Batch complete: {self.stats['success']} success, {self.stats['failed']} failed")
    
    def run(self, limit: int = 10000):
        """Run full backfill"""
        logger.info("="*60)
        logger.info("  PHASE 2 DATA COLLECTION - Match Context Backfill")
        logger.info("="*60)
        
        self.stats['start_time'] = datetime.now()
        
        # Discover gaps
        matches = self.discover_missing_matches(limit=limit)
        self.stats['total_matches'] = len(matches)
        
        if len(matches) == 0:
            logger.info("✅ No matches need backfilling - all up to date!")
            return
        
        # Backfill
        self.backfill_batch(matches, batch_size=100)
        
        self.stats['end_time'] = datetime.now()
        
        # Report
        self.print_summary()
    
    def print_summary(self):
        """Print backfill summary"""
        duration = (self.stats['end_time'] - self.stats['start_time']).total_seconds()
        rate = self.stats['success'] / duration if duration > 0 else 0
        
        logger.info("\n" + "="*60)
        logger.info("  BACKFILL SUMMARY")
        logger.info("="*60)
        logger.info(f"Total matches:     {self.stats['total_matches']}")
        logger.info(f"✅ Success:        {self.stats['success']}")
        logger.info(f"❌ Failed:         {self.stats['failed']}")
        logger.info(f"⏱️  Duration:       {duration:.1f}s")
        logger.info(f"📊 Rate:           {rate:.1f} matches/sec")
        logger.info("="*60)
        
        # Success rate
        if self.stats['total_matches'] > 0:
            success_rate = (self.stats['success'] / self.stats['total_matches']) * 100
            logger.info(f"Success rate: {success_rate:.1f}%")
        
        logger.info("\n✅ Phase 2 context data collection complete!")


def main():
    """Run match context backfill"""
    try:
        backfiller = MatchContextBackfiller()
        backfiller.run(limit=5000)  # Start with 5000 matches
        
    except Exception as e:
        logger.error(f"❌ Backfill error: {e}")
        logger.exception(e)
        sys.exit(1)


if __name__ == "__main__":
    main()
