"""
Backfill Agent - Automated Data Gap Discovery and Filling

Responsibilities:
1. Discover missing data (lineups, referee, weather, odds)
2. Prioritize by league tier and recency
3. Fetch from multiple sources (API-Football, Weather APIs, etc.)
4. Normalize and upsert with lineage tracking
5. Handle retries with exponential backoff
6. Schedule nightly backfill runs

Architecture:
    Discovery → Priority Queue → Fetchers → Normalization → Upsert + Lineage
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set
from queue import PriorityQueue
from datetime import datetime, timedelta
import psycopg2
from psycopg2.extras import RealDictCursor
import os

logger = logging.getLogger(__name__)


@dataclass(order=True)
class BackfillTask:
    """
    Prioritized backfill task
    
    Priority calculation:
    - Tier 1 leagues: priority 100-200
    - Tier 2 leagues: priority 200-300
    - Tier 3 leagues: priority 300-400
    - Recent matches (last 30 days): +0 bonus
    - Old matches: +days_old penalty
    """
    priority: int
    match_id: int = field(compare=False)
    league_id: int = field(compare=False)
    season: int = field(compare=False)
    match_date: datetime = field(compare=False)
    missing_data: Set[str] = field(compare=False, default_factory=set)
    
    @classmethod
    def calculate_priority(cls, league_id: int, match_date: datetime, 
                          league_tier: int = 2) -> int:
        """
        Calculate task priority (lower = higher priority)
        
        Args:
            league_id: League identifier
            league_tier: 1 (top), 2 (mid), 3 (low)
            match_date: When match was played
            
        Returns:
            Priority value (100-1000)
        """
        # Base priority by tier
        tier_priorities = {1: 100, 2: 200, 3: 300}
        base = tier_priorities.get(league_tier, 400)
        
        # Recency bonus (recent matches = higher priority)
        days_old = (datetime.now() - match_date).days
        recency_penalty = min(days_old, 365)  # Cap at 1 year
        
        priority = base + recency_penalty
        return priority


class GapDiscovery:
    """Discover missing data in the database"""
    
    def __init__(self, db_conn):
        self.conn = db_conn
        
        # League tier mapping (Priority 1 = Top 5 leagues)
        self.league_tiers = {
            39: 1,   # Premier League
            140: 1,  # La Liga
            135: 1,  # Serie A
            78: 1,   # Bundesliga
            61: 1,   # Ligue 1
            94: 2,   # Primeira Liga
            88: 2,   # Eredivisie
            203: 2,  # Super Lig
            # Add more as needed
        }
    
    def discover_missing_lineups(self, limit: int = 1000) -> List[BackfillTask]:
        """
        Find matches without player availability data (Phase 2)
        
        Returns list of tasks ordered by priority
        """
        # Note: player_availability table created in Phase 2
        # For now, return empty until we start collecting
        logger.info("   Lineup discovery: Skipping (table created, collection not started)")
        return []
    
    def discover_missing_referees(self, limit: int = 1000) -> List[BackfillTask]:
        """Find matches without referee assignments (Phase 2)"""
        # Note: Referees table created, but no ref_id in training_matches yet
        # Using simple version for now
        logger.info("   Referee discovery: Checking for gaps...")
        
        # For now, return all recent matches as needing referee data
        query = """
            SELECT 
                tm.match_id,
                tm.league_id,
                tm.season,
                tm.match_date as kickoff_at
            FROM training_matches tm
            WHERE tm.match_date >= '2023-01-01'
              AND tm.match_date < NOW()
              AND tm.outcome IS NOT NULL
            ORDER BY tm.match_date DESC
            LIMIT %s
        """
        
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, (limit,))
            matches = cur.fetchall()
        
        tasks = []
        for m in matches:
            tier = self.league_tiers.get(m['league_id'], 3)
            priority = BackfillTask.calculate_priority(
                m['league_id'],
                m['match_date'],
                tier
            )
            
            task = BackfillTask(
                priority=priority,
                match_id=m['match_id'],
                league_id=m['league_id'],
                season=m['season'],
                match_date=m['match_date'],
                missing_data={'referee'}
            )
            tasks.append(task)
        
        logger.info(f"🔍 Discovered {len(tasks)} matches missing referee data")
        return tasks
    
    def discover_missing_weather(self, limit: int = 500) -> List[BackfillTask]:
        """Find matches without weather data (last 2 years only) - Phase 2"""
        query = """
            SELECT 
                tm.match_id,
                tm.league_id,
                tm.season,
                tm.match_date as kickoff_at
            FROM training_matches tm
            LEFT JOIN match_weather mw ON tm.match_id = mw.match_id
            WHERE mw.match_id IS NULL
              AND tm.match_date >= NOW() - INTERVAL '2 years'
              AND tm.match_date < NOW()
              AND tm.outcome IS NOT NULL
            ORDER BY tm.match_date DESC
            LIMIT %s
        """
        
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, (limit,))
            matches = cur.fetchall()
        
        tasks = []
        for m in matches:
            tier = self.league_tiers.get(m['league_id'], 3)
            priority = BackfillTask.calculate_priority(
                m['league_id'],
                m['match_date'],
                tier
            )
            
            task = BackfillTask(
                priority=priority,
                match_id=m['match_id'],
                league_id=m['league_id'],
                season=m['season'],
                match_date=m['match_date'],
                missing_data={'weather'}
            )
            tasks.append(task)
        
        logger.info(f"🔍 Discovered {len(tasks)} matches missing weather data")
        return tasks
    
    def discover_missing_context(self, limit: int = 1000) -> List[BackfillTask]:
        """Find matches without match_context (rest days, schedule, etc.) - Phase 2"""
        query = """
            SELECT 
                tm.match_id,
                tm.league_id,
                tm.season,
                tm.match_date as kickoff_at
            FROM training_matches tm
            LEFT JOIN match_context mc ON tm.match_id = mc.match_id
            WHERE mc.match_id IS NULL
              AND tm.match_date >= '2020-01-01'
              AND tm.match_date < NOW()
              AND tm.outcome IS NOT NULL
            ORDER BY tm.match_date DESC
            LIMIT %s
        """
        
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, (limit,))
            matches = cur.fetchall()
        
        tasks = []
        for m in matches:
            tier = self.league_tiers.get(m['league_id'], 3)
            priority = BackfillTask.calculate_priority(
                m['league_id'],
                m['match_date'],
                tier
            )
            
            task = BackfillTask(
                priority=priority,
                match_id=m['match_id'],
                league_id=m['league_id'],
                season=m['season'],
                match_date=m['match_date'],
                missing_data={'context'}
            )
            tasks.append(task)
        
        logger.info(f"🔍 Discovered {len(tasks)} matches missing context data")
        return tasks


class BackfillAgent:
    """Main backfill orchestrator"""
    
    def __init__(self, database_url: Optional[str] = None):
        """Initialize backfill agent"""
        self.database_url = database_url or os.getenv('DATABASE_URL')
        if not self.database_url:
            raise ValueError("DATABASE_URL not provided")
        
        self.conn = psycopg2.connect(self.database_url)
        self.discovery = GapDiscovery(self.conn)
        self.task_queue = PriorityQueue()
        
        # Stats
        self.stats = {
            'tasks_discovered': 0,
            'tasks_completed': 0,
            'tasks_failed': 0,
            'api_calls': 0,
            'start_time': None
        }
        
        logger.info("✅ Backfill Agent initialized")
    
    def discover_all_gaps(self, limit_per_type: int = 500):
        """
        Discover all data gaps and populate task queue
        
        Args:
            limit_per_type: Maximum tasks to discover per data type
        """
        logger.info("🔍 Starting gap discovery...")
        
        all_tasks = []
        
        # Discover missing data
        all_tasks.extend(self.discovery.discover_missing_lineups(limit_per_type))
        all_tasks.extend(self.discovery.discover_missing_referees(limit_per_type))
        all_tasks.extend(self.discovery.discover_missing_weather(limit_per_type // 2))
        all_tasks.extend(self.discovery.discover_missing_context(limit_per_type))
        
        # Add to priority queue
        for task in all_tasks:
            self.task_queue.put(task)
        
        self.stats['tasks_discovered'] = len(all_tasks)
        
        logger.info(f"✅ Discovered {len(all_tasks)} total backfill tasks")
        logger.info(f"   Queue size: {self.task_queue.qsize()}")
        
        return len(all_tasks)
    
    def process_task(self, task: BackfillTask) -> bool:
        """
        Process a single backfill task
        
        Args:
            task: Task to process
            
        Returns:
            True if successful, False if failed
        """
        try:
            logger.info(f"⚙️  Processing match {task.match_id} (priority {task.priority})")
            logger.info(f"   Missing: {task.missing_data}")
            
            # TODO: Implement actual fetchers
            # For now, just placeholder
            
            if 'lineups' in task.missing_data:
                # fetch_lineups_from_api(task.match_id)
                logger.info(f"   [STUB] Would fetch lineups for match {task.match_id}")
            
            if 'referee' in task.missing_data:
                # fetch_referee_from_api(task.match_id)
                logger.info(f"   [STUB] Would fetch referee for match {task.match_id}")
            
            if 'weather' in task.missing_data:
                # fetch_weather_from_api(task.match_id, task.match_date)
                logger.info(f"   [STUB] Would fetch weather for match {task.match_id}")
            
            if 'context' in task.missing_data:
                # calculate_context_features(task.match_id)
                logger.info(f"   [STUB] Would calculate context for match {task.match_id}")
            
            # Record lineage
            # record_data_lineage(task.match_id, task.missing_data)
            
            self.stats['tasks_completed'] += 1
            return True
            
        except Exception as e:
            logger.error(f"❌ Task failed for match {task.match_id}: {e}")
            self.stats['tasks_failed'] += 1
            return False
    
    def run_batch(self, max_tasks: int = 100, max_duration_seconds: int = 300):
        """
        Run a batch of backfill tasks
        
        Args:
            max_tasks: Maximum tasks to process
            max_duration_seconds: Maximum runtime
        """
        logger.info(f"🚀 Starting backfill batch (max {max_tasks} tasks, {max_duration_seconds}s)")
        
        self.stats['start_time'] = time.time()
        tasks_processed = 0
        
        while (not self.task_queue.empty() and 
               tasks_processed < max_tasks and
               (time.time() - self.stats['start_time']) < max_duration_seconds):
            
            task = self.task_queue.get()
            self.process_task(task)
            tasks_processed += 1
            
            # Rate limiting (be nice to APIs)
            time.sleep(0.5)
        
        elapsed = time.time() - self.stats['start_time']
        
        logger.info(f"✅ Batch complete")
        logger.info(f"   Processed: {tasks_processed} tasks")
        logger.info(f"   Completed: {self.stats['tasks_completed']}")
        logger.info(f"   Failed: {self.stats['tasks_failed']}")
        logger.info(f"   Remaining: {self.task_queue.qsize()}")
        logger.info(f"   Duration: {elapsed:.1f}s")
    
    def get_stats(self) -> Dict:
        """Get backfill statistics"""
        return {
            **self.stats,
            'queue_size': self.task_queue.qsize(),
            'success_rate': (
                self.stats['tasks_completed'] / max(1, self.stats['tasks_completed'] + self.stats['tasks_failed'])
            ) * 100
        }
    
    def close(self):
        """Clean up resources"""
        self.conn.close()
        logger.info("🔒 Backfill Agent closed")


def main():
    """Main entry point for backfill agent"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    logger.info("="*60)
    logger.info("  BetGenius AI - Backfill Agent")
    logger.info("="*60)
    
    try:
        # Initialize agent
        agent = BackfillAgent()
        
        # Discover gaps
        num_tasks = agent.discover_all_gaps(limit_per_type=100)
        
        if num_tasks == 0:
            logger.info("✨ No data gaps found - database is complete!")
            return
        
        # Process batch
        agent.run_batch(max_tasks=50, max_duration_seconds=120)
        
        # Print stats
        stats = agent.get_stats()
        logger.info("\n" + "="*60)
        logger.info("  Backfill Statistics")
        logger.info("="*60)
        logger.info(f"  Tasks discovered:  {stats['tasks_discovered']}")
        logger.info(f"  Tasks completed:   {stats['tasks_completed']}")
        logger.info(f"  Tasks failed:      {stats['tasks_failed']}")
        logger.info(f"  Success rate:      {stats['success_rate']:.1f}%")
        logger.info(f"  Queue remaining:   {stats['queue_size']}")
        logger.info("="*60)
        
    except Exception as e:
        logger.error(f"❌ Backfill agent error: {e}")
        raise
    finally:
        agent.close()


if __name__ == "__main__":
    main()
