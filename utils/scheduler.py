"""
BetGenius AI Backend - Task Scheduler
Background scheduler for automated data collection and model updates
"""

import asyncio
import logging
from datetime import datetime, time
from typing import Optional
import threading
import json
import psycopg2
import os
import sys
from models.automated_collector import AutomatedCollector

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger(__name__)

class BackgroundScheduler:
    """
    Background scheduler for automated tasks
    Runs daily collection cycles without blocking the main application
    """
    
    def __init__(self):
        self.collector = AutomatedCollector()
        self.is_running = False
        self.scheduler_thread: Optional[threading.Thread] = None
        # Enhanced scheduling for odds nuance capture
        # Weekdays: every 6 hours (02:00, 08:00, 14:00, 20:00 UTC)
        # Weekends: every 3 hours for better coverage
        self.weekday_hours = [2, 8, 14, 20]  # Every 6 hours
        self.weekend_hours = [2, 5, 8, 11, 14, 17, 20, 23]  # Every 3 hours
        # Metrics calculation schedule (every 6 hours)
        self.metrics_hours = [3, 9, 15, 21]  # Offset by 1 hour from data collection
        self.last_metrics_calculation: Optional[datetime] = None
        # CLV Club alert producer (runs every 60 seconds)
        self.last_clv_producer_run: Optional[datetime] = None
        # CLV Club TTL cleanup (runs every 5 minutes)
        self.last_clv_ttl_cleanup: Optional[datetime] = None
        # Phase 2: Closing sampler (runs every 60 seconds)
        self.last_closing_sampler_run: Optional[datetime] = None
        # Phase 2: Closing settler (runs every 60 seconds)
        self.last_closing_settler_run: Optional[datetime] = None
        # Daily Brief: Runs once per day at 00:05 UTC
        self.last_daily_brief_run: Optional[datetime] = None
        # Phase B: Fresh odds collection (HIGH PRIORITY - runs every 60 seconds)
        self.last_phase_b_run: Optional[datetime] = None
        # Scheduled collection state tracking (prevents duplicate runs)
        self.last_scheduled_collection_run: Optional[datetime] = None
        self.last_scheduled_collection_hour: Optional[int] = None
        # Background task tracking (for non-blocking execution)
        self.tasks: dict = {}  # name -> asyncio.Task
        self.last_run: dict = {}  # name -> datetime
        
    def start_scheduler(self):
        """Start the background scheduler"""
        if self.is_running:
            logger.warning("Scheduler already running")
            return
        
        self.is_running = True
        self.scheduler_thread = threading.Thread(target=self._run_scheduler, daemon=True)
        self.scheduler_thread.start()
        logger.info("Background scheduler started - enhanced schedule: 6h weekdays, 3h weekends")
        logger.info("Automated metrics calculation enabled - runs every 6 hours at 03:00, 09:00, 15:00, 21:00 UTC")
        logger.info("🎯 Phase B: Fresh odds collection enabled - HIGH PRIORITY every 60 seconds")
        logger.info("CLV Club alert producer enabled - runs every 60 seconds")
        logger.info("CLV Club Phase 2: Closing sampler + settler enabled - runs every 60 seconds")
        logger.info("CLV Daily Brief enabled - runs once per day at 00:05 UTC")
    
    def stop_scheduler(self):
        """Stop the background scheduler"""
        self.is_running = False
        if self.scheduler_thread:
            self.scheduler_thread.join(timeout=5)
        logger.info("Background scheduler stopped")
    
    async def _spawn(self, name: str, coro, timeout: Optional[int] = None):
        """
        Spawn a background task with timeout and reentrancy protection.
        Skips if task is already running.
        
        Args:
            name: Task name for tracking
            coro: Coroutine function to execute
            timeout: Optional timeout in seconds
        """
        # Check if task is already running
        if name in self.tasks:
            task = self.tasks[name]
            if not task.done():
                logger.debug(f"⏭️  {name}: skipped (already running)")
                return
        
        async def wrapper():
            started = datetime.utcnow()
            logger.debug(f"▶️  {name}: start")
            try:
                if timeout:
                    await asyncio.wait_for(coro(), timeout=timeout)
                else:
                    await coro()
                elapsed = (datetime.utcnow() - started).total_seconds()
                logger.info(f"✅ {name}: completed in {elapsed:.1f}s")
            except asyncio.TimeoutError:
                logger.error(f"⏱️  {name}: TIMEOUT after {timeout}s")
            except Exception as e:
                logger.exception(f"💥 {name}: failed - {e}")
        
        # Mark as running immediately to prevent duplicate spawns
        self.last_run[name] = datetime.utcnow()
        self.tasks[name] = asyncio.create_task(wrapper())
    
    def _run_scheduler(self):
        """Main scheduler loop"""
        loop = None
        try:
            logger.info("🔧 _run_scheduler: Creating new event loop...")
            asyncio.set_event_loop(asyncio.new_event_loop())
            loop = asyncio.get_event_loop()
            logger.info("🔧 _run_scheduler: Starting scheduler loop...")
            loop.run_until_complete(self._scheduler_loop())
        except Exception as e:
            logger.error(f"❌ Scheduler loop failed: {e}", exc_info=True)
        finally:
            if loop:
                logger.info("🔧 _run_scheduler: Closing event loop")
                loop.close()
    
    def _get_last_collection_date(self):
        """Get the last collection date from log file"""
        try:
            import json
            with open('data/collection_log.json', 'r') as f:
                log_data = json.load(f)
            
            if log_data and len(log_data) > 0:
                latest = log_data[-1]
                timestamp_str = latest.get('timestamp', '')
                if timestamp_str:
                    from datetime import datetime
                    timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                    return timestamp.date()
        except Exception:
            pass
        return None
    
    def _get_last_collection_timestamp(self, hour: int):
        """Get last collection timestamp for specific hour"""
        try:
            import json
            with open('data/collection_log.json', 'r') as f:
                log_data = json.load(f)
            
            if log_data and len(log_data) > 0:
                # Look for collections from this hour in last 24 hours
                now = datetime.utcnow()
                for entry in reversed(log_data):
                    timestamp_str = entry.get('timestamp', '')
                    if timestamp_str:
                        timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                        # Check if within last 24h and same hour
                        if (now - timestamp).total_seconds() < 86400 and timestamp.hour == hour:
                            return timestamp
        except Exception:
            pass
        return None

    async def _scheduler_loop(self):
        """Enhanced scheduler loop for frequent odds collection and metrics tracking"""
        logger.info("🚀 Enhanced scheduler started - capturing odds nuances with frequent collection")
        logger.info("📊 Automated metrics tracking enabled - calculates accuracy every 6 hours")
        logger.info("🎯 CLV Club alert producer enabled - scanning for opportunities every 60 seconds")
        
        while self.is_running:
            try:
                now = datetime.utcnow()
                current_hour = now.hour
                current_minute = now.minute
                weekday = now.weekday()  # 0=Monday, 6=Sunday
                is_weekend = weekday >= 5  # Saturday or Sunday
                
                # Determine collection hours based on day type
                target_hours = self.weekend_hours if is_weekend else self.weekday_hours
                
                # Check if current hour is a target hour and within collection window (first 15 minutes)
                if current_hour in target_hours and current_minute < 15:
                    
                    # Resilient state tracking: Check if we already ran for this hour
                    # This prevents duplicate runs during the 15-minute window
                    should_run = False
                    
                    if self.last_scheduled_collection_hour != current_hour:
                        # New hour - definitely run
                        should_run = True
                    elif not self.last_scheduled_collection_run:
                        # No previous run recorded - run it
                        should_run = True
                    elif (now - self.last_scheduled_collection_run).total_seconds() > 3600:
                        # More than 1 hour since last run - run it
                        should_run = True
                    
                    if should_run:
                        # Update state IMMEDIATELY to prevent duplicate runs
                        self.last_scheduled_collection_run = now
                        self.last_scheduled_collection_hour = current_hour
                        
                        day_type = "weekend" if is_weekend else "weekday"
                        logger.info(f"🔄 SCHEDULER: Starting {day_type} collection cycle at {now.strftime('%H:%M:%S')} UTC")
                        logger.info(f"📅 Hour {current_hour:02d}:00 - capturing odds nuances for market efficiency")
                        
                        # Use background task for daily collection to avoid blocking
                        async def run_collection():
                            try:
                                results = await self.collector.daily_collection_cycle()
                                logger.info(f"✅ Enhanced collection completed: {results.get('new_matches_collected', 0)} new matches")
                                logger.info(f"📊 Fresh odds snapshots: {results.get('new_odds_collected', 0)}")
                                logger.info(f"💾 Total matches in DB: {results.get('total_matches_in_db', 'unknown')}")
                            except Exception as e:
                                logger.error(f"❌ Enhanced collection failed at {current_hour:02d}:00: {e}")
                        
                        await self._spawn(f"daily_collection_{current_hour}", run_collection, timeout=600)
                    
                    else:
                        logger.debug(f"📋 Collection already completed at {current_hour:02d}:00 (state-tracked)")
                
                else:
                    # Log next collection time for visibility
                    next_hour = None
                    for hour in sorted(target_hours):
                        if hour > current_hour or (hour <= current_hour and hour == target_hours[0]):
                            next_hour = hour
                            break
                    
                    if next_hour is None:
                        next_hour = target_hours[0]  # Next day first collection
                    
                    if current_hour not in target_hours or current_minute >= 15:
                        logger.debug(f"⏰ Next collection: {next_hour:02d}:00 UTC ({'weekend' if is_weekend else 'weekday'} schedule)")
                
                # Check for metrics calculation schedule (every 6 hours at offset times)
                if current_hour in self.metrics_hours and current_minute < 15:
                    # Check if we already calculated metrics at this hour today
                    if not self.last_metrics_calculation or (now - self.last_metrics_calculation).total_seconds() > 3600:
                        logger.info(f"📊 SCHEDULER: Running metrics calculation at {now.strftime('%H:%M:%S')} UTC")
                        await self._spawn("metrics_calc", self._run_metrics_calculation, timeout=120)
                        self.last_metrics_calculation = now
                
                # 🎯 HIGH PRIORITY: Run Phase B (fresh odds collection) every 60 seconds
                # Use background task with 5-minute timeout to prevent blocking
                if "phase_b" not in self.last_run or (now - self.last_run["phase_b"]).total_seconds() >= 60:
                    await self._spawn("phase_b", self._run_phase_b_fresh_odds, timeout=300)
                
                # Run CLV Club alert producer every 60 seconds (background task)
                if "clv_producer" not in self.last_run or (now - self.last_run["clv_producer"]).total_seconds() >= 60:
                    await self._spawn("clv_producer", self._run_clv_alert_producer, timeout=30)
                
                # Run CLV Club TTL cleanup every 5 minutes (300 seconds) - background task
                if "clv_cleanup" not in self.last_run or (now - self.last_run["clv_cleanup"]).total_seconds() >= 300:
                    await self._spawn("clv_cleanup", self._run_clv_ttl_cleanup, timeout=60)
                
                # Phase 2: Run closing sampler every 60 seconds (background task)
                if "closing_sampler" not in self.last_run or (now - self.last_run["closing_sampler"]).total_seconds() >= 60:
                    await self._spawn("closing_sampler", self._run_closing_sampler, timeout=30)
                
                # Phase 2: Run closing settler every 60 seconds (background task)
                if "closing_settler" not in self.last_run or (now - self.last_run["closing_settler"]).total_seconds() >= 60:
                    await self._spawn("closing_settler", self._run_closing_settler, timeout=30)
                
                # CLV Daily Brief: Run once per day at 00:05 UTC (background task)
                if current_hour == 0 and current_minute >= 5 and current_minute < 15:
                    # Check if we already ran today
                    today_date = now.date()
                    last_run_date = self.last_daily_brief_run.date() if self.last_daily_brief_run else None
                    
                    if last_run_date != today_date:
                        await self._spawn("daily_brief", self._run_daily_brief, timeout=120)
                        self.last_daily_brief_run = now
                
                # Check every 1 second for responsive scheduling (background tasks run independently)
                await asyncio.sleep(1)
                
                # Every 15 minutes, run safety net to fill missing buckets
                if "safety_net" not in self.last_run or (now - self.last_run["safety_net"]).total_seconds() >= 900:
                    await self._spawn("safety_net", self._run_safety_net, timeout=120)
                    
            except Exception as e:
                logger.error(f"Scheduler loop error: {e}")
                await asyncio.sleep(300)  # Wait 5 minutes before retry
    
    async def _run_safety_net(self):
        """Run the 15-minute safety net to fill missing buckets"""
        try:
            logger.info("🛡️ Running 15-minute safety net check...")
            
            from models.bucket_filler import BucketFiller
            filler = BucketFiller()
            results = await filler.fill_missing_buckets()
            
            if results['buckets_filled'] > 0:
                logger.info(f"🛡️ Safety net filled {results['buckets_filled']} missing buckets")
            else:
                logger.debug("🛡️ Safety net: no missing buckets found")
                
        except Exception as e:
            logger.error(f"🛡️ Safety net error: {e}")
    
    async def _run_metrics_calculation(self):
        """Run automated metrics calculation for completed matches"""
        try:
            logger.info("📊 Running automated metrics calculation...")
            
            from calculate_metrics_results import MetricsResultsCalculator
            
            calculator = MetricsResultsCalculator()
            stats = calculator.process_completed_matches(limit=50)
            
            if stats['metrics_computed'] > 0:
                logger.info(f"✅ Metrics calculation complete: {stats['metrics_computed']} matches processed")
                logger.info(f"   Results fetched: {stats['results_fetched']}, Errors: {stats['errors']}")
            else:
                logger.debug("📊 No new metrics computed (no completed matches found)")
            
            self.last_metrics_calculation = datetime.utcnow()
                
        except Exception as e:
            logger.error(f"📊 Metrics calculation error: {e}")
    
    async def _run_phase_b_fresh_odds(self):
        """
        🎯 FAST Phase B: Targeted odds collection for matches needing refresh
        Queries DB for upcoming fixtures, fetches odds per-match (not per-league)
        Completes in <30s with bounded concurrency
        """
        try:
            import time
            import asyncio
            import psycopg2
            
            start_time = time.time()
            
            # Step 1: Query upcoming fixtures needing odds (within 6-168h, missing fresh snapshots)
            database_url = os.environ.get('DATABASE_URL')
            if not database_url:
                logger.error("Phase B: DATABASE_URL not found")
                return
            
            matches_needing_odds = []
            with psycopg2.connect(database_url) as conn:
                with conn.cursor() as cursor:
                    # Find matches 6-168h ahead WITH recent odds but NO predictions
                    cursor.execute("""
                        SELECT DISTINCT f.match_id, f.league_id, f.kickoff_at
                        FROM fixtures f
                        INNER JOIN odds_snapshots o ON f.match_id = o.match_id 
                            AND o.ts_snapshot > NOW() - INTERVAL '48 hours'
                        LEFT JOIN consensus_predictions cp ON f.match_id = cp.match_id
                        WHERE f.kickoff_at BETWEEN NOW() + INTERVAL '6 hours' 
                            AND NOW() + INTERVAL '168 hours'
                        AND f.status = 'NS'
                        AND cp.match_id IS NULL
                        ORDER BY f.kickoff_at
                        LIMIT 50
                    """)
                    matches_needing_odds = cursor.fetchall()
            
            if not matches_needing_odds:
                logger.debug(f"🎯 Phase B: No matches need odds refresh (completed in {int((time.time()-start_time)*1000)}ms)")
                return
            
            logger.info(f"🎯 Phase B: {len(matches_needing_odds)} matches have recent odds, building predictions...")
            
            # Build consensus predictions from ALL recent odds (from automated collector + any other source)
            # The automated collector runs at startup and populates odds_snapshots
            # Phase B's job is to build predictions from those odds
            try:
                consensus_count = self.build_consensus_predictions()
                elapsed_ms = int((time.time() - start_time) * 1000)
                
                if consensus_count > 0:
                    logger.info(f"✅ Phase B: Built {consensus_count} new predictions in {elapsed_ms}ms")
                else:
                    logger.debug(f"🎯 Phase B: 0 new predictions ({elapsed_ms}ms)")
            except Exception as consensus_error:
                logger.error(f"❌ Phase B consensus failed: {consensus_error}")
                
        except Exception as e:
            logger.error(f"🎯 Phase B error: {e}")
    
    async def _run_clv_alert_producer(self):
        """Run CLV Club alert producer"""
        try:
            from models.clv_alert_producer import run_clv_alert_producer
            
            stats = run_clv_alert_producer()
            
            if not stats.get('enabled'):
                logger.debug("CLV Club disabled in config")
                return
            
            if stats.get('alerts_created', 0) > 0:
                logger.info(f"🎯 CLV Producer: {stats['alerts_created']} alerts created " +
                           f"from {stats['opportunities_found']} opportunities")
            else:
                logger.debug(f"🎯 CLV Producer: {stats['fixtures_scanned']} fixtures scanned, " +
                            f"{stats['opportunities_found']} opportunities, 0 alerts (gated)")
            
            self.last_clv_producer_run = datetime.utcnow()
                
        except Exception as e:
            logger.error(f"🎯 CLV Producer error: {e}")
    
    async def _run_clv_ttl_cleanup(self):
        """Archive expired CLV alerts to history table"""
        try:
            import psycopg2
            import os
            
            database_url = os.environ.get('DATABASE_URL')
            if not database_url:
                return
            
            with psycopg2.connect(database_url) as conn:
                cursor = conn.cursor()
                
                # Archive alerts expired >1 hour ago to history table
                cursor.execute("""
                    WITH archived AS (
                        DELETE FROM clv_alerts 
                        WHERE expires_at < NOW() - INTERVAL '1 hour'
                        RETURNING *
                    )
                    INSERT INTO clv_alerts_history 
                    SELECT * FROM archived
                """)
                
                archived_count = cursor.rowcount
                conn.commit()
                
                if archived_count > 0:
                    logger.info(f"🧹 CLV TTL Cleanup: Archived {archived_count} expired alerts")
                else:
                    logger.info("🧹 CLV TTL Cleanup: No expired alerts to archive (all clear)")
            
            self.last_clv_ttl_cleanup = datetime.utcnow()
                
        except Exception as e:
            logger.error(f"🧹 CLV TTL Cleanup error: {e}")
    
    async def _run_closing_sampler(self):
        """Run Phase 2 closing sampler (collects composite odds near kickoff)"""
        try:
            from models.clv_closing_sampler import CLVClosingSampler
            
            sampler = CLVClosingSampler()
            sampler.run_cycle()
            
            self.last_closing_sampler_run = datetime.utcnow()
                
        except Exception as e:
            logger.error(f"📊 Closing Sampler error: {e}")
    
    async def _run_closing_settler(self):
        """Run Phase 2 closing settler (settles alerts with realized CLV)"""
        try:
            from models.clv_closing_settler import CLVClosingSettler
            
            settler = CLVClosingSettler()
            settler.run_cycle()
            
            self.last_closing_settler_run = datetime.utcnow()
                
        except Exception as e:
            logger.error(f"⚖️ Closing Settler error: {e}")
    
    async def _run_daily_brief(self):
        """Run CLV Daily Brief aggregation (once per day at 00:05 UTC)"""
        try:
            from models.clv_daily_brief import daily_brief
            
            logger.info("📊 Running CLV Daily Brief aggregation...")
            
            result = await daily_brief.run_daily_brief()
            
            if result.get('status') == 'success':
                logger.info(f"✅ CLV Daily Brief complete: {result['leagues_processed']} leagues processed, " +
                           f"{result['old_rows_deleted']} old rows deleted ({result['duration_ms']}ms)")
            elif result.get('status') == 'disabled':
                logger.debug("CLV Daily Brief disabled in config")
            else:
                logger.error(f"❌ CLV Daily Brief failed: {result.get('error', 'unknown error')}")
            
            self.last_daily_brief_run = datetime.utcnow()
                
        except Exception as e:
            logger.error(f"📊 CLV Daily Brief error: {e}")
    
    def trigger_immediate_collection(self, force=False):
        """Trigger immediate collection cycle (non-blocking)
        
        Args:
            force (bool): If True, bypasses timing restrictions for manual testing
        """
        if not self.is_running:
            logger.warning("Scheduler not running, cannot trigger immediate collection")
            return False
        
        # Run collection in background
        threading.Thread(
            target=self._run_immediate_collection,
            args=(force,),
            daemon=True
        ).start()
        
        if force:
            logger.info("🔧 MANUAL collection cycle triggered (bypassing timing restrictions)")
        else:
            logger.info("Immediate collection cycle triggered")
        return True
    
    def _run_immediate_collection(self, force=False):
        """Run immediate collection in separate thread
        
        Args:
            force (bool): If True, bypasses timing restrictions for manual testing
        """
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            results = loop.run_until_complete(self.collector.daily_collection_cycle())
            if force:
                logger.info(f"🔧 MANUAL collection completed: {results.get('new_matches_collected', 0)} new matches")
            else:
                logger.info(f"Immediate collection completed: {results.get('new_matches_collected', 0)} new matches")
            
            # Build consensus predictions from fresh odds
            try:
                consensus_count = self.build_consensus_predictions()
                if consensus_count > 0:
                    logger.info(f"✅ Built {consensus_count} new consensus predictions")
                else:
                    logger.info("🧮 No new consensus predictions needed")
            except Exception as consensus_error:
                logger.error(f"Consensus building failed: {consensus_error}")
                
        except Exception as e:
            if force:
                logger.error(f"🔧 MANUAL collection failed: {e}")
            else:
                logger.error(f"Immediate collection failed: {e}")
        finally:
            loop.close()
    
    def build_consensus_predictions(self) -> int:
        """Build consensus predictions from odds_snapshots for matches with recent odds"""
        try:
            logger.info("🧮 [CONSENSUS] Starting consensus building for recent matches...")
            database_url = os.environ.get('DATABASE_URL')
            if not database_url:
                logger.error("[CONSENSUS] ❌ DATABASE_URL not found")
                return 0
            
            with psycopg2.connect(database_url) as conn:
                with conn.cursor() as cursor:
                    # Find matches with recent odds that might need consensus for new time buckets
                    cursor.execute("""
                        SELECT DISTINCT o.match_id
                        FROM odds_snapshots o
                        WHERE o.ts_snapshot > NOW() - INTERVAL '48 hours'
                        GROUP BY o.match_id
                        HAVING COUNT(DISTINCT CASE WHEN o.outcome IN ('H','D','A') THEN o.book_id END) >= 2
                    """)
                    
                    matches_needing_consensus = cursor.fetchall()
                    total_candidates = len(matches_needing_consensus)
                    logger.info(f"🧮 [CONSENSUS] Found {total_candidates} candidate matches for consensus building")
                    
                    consensus_built = 0
                    skipped = 0
                    failure_reasons = {
                        'no_bucket_hit': 0,
                        'too_few_triplets': 0, 
                        'devig_failed': 0,
                        'write_conflict': 0
                    }
                    
                    for (match_id,) in matches_needing_consensus:
                        try:
                            # Build consensus for this match using the SQL bucket classifier
                            cursor.execute("""
                                INSERT INTO consensus_predictions 
                                (match_id, time_bucket, consensus_h, consensus_d, consensus_a, 
                                 dispersion_h, dispersion_d, dispersion_a, n_books, created_at)
                                WITH match_odds AS (
                                    SELECT book_id, outcome, implied_prob, secs_to_kickoff
                                    FROM odds_snapshots 
                                    WHERE match_id = %s AND ts_snapshot > NOW() - INTERVAL '24 hours'
                                ),
                                complete_books AS (
                                    SELECT book_id FROM match_odds
                                    GROUP BY book_id HAVING COUNT(DISTINCT outcome) = 3
                                ),
                                clean_odds AS (
                                    SELECT mo.* FROM match_odds mo 
                                    JOIN complete_books cb ON mo.book_id = cb.book_id
                                ),
                                bucket_classified AS (
                                    SELECT *,
                                        CASE 
                                            WHEN secs_to_kickoff BETWEEN 5400 AND 32400 THEN '6h'    -- 1.5-9h (consensus_builder compatible)
                                            WHEN secs_to_kickoff BETWEEN 21600 AND 64800 THEN '12h'  -- 6-18h (consensus_builder compatible)  
                                            WHEN secs_to_kickoff BETWEEN 64800 AND 108000 THEN '24h' -- 18-30h (consensus_builder compatible)
                                            WHEN secs_to_kickoff BETWEEN 129600 AND 216000 THEN '48h'-- 36-60h (consensus_builder compatible)
                                            WHEN secs_to_kickoff BETWEEN 216000 AND 302400 THEN '72h'-- 60-84h (consensus_builder compatible)
                                            WHEN secs_to_kickoff BETWEEN 900 AND 5400 THEN '3h'      -- 0.25-1.5h (consensus_builder compatible)
                                            ELSE 'other'
                                        END as time_bucket
                                    FROM clean_odds
                                    WHERE secs_to_kickoff > 900  -- at least 15 minutes before kickoff
                                ),
                                consensus_calc AS (
                                    SELECT 
                                        time_bucket,
                                        AVG(CASE WHEN outcome = 'H' THEN implied_prob END) as consensus_h,
                                        AVG(CASE WHEN outcome = 'D' THEN implied_prob END) as consensus_d,
                                        AVG(CASE WHEN outcome = 'A' THEN implied_prob END) as consensus_a,
                                        STDDEV(CASE WHEN outcome = 'H' THEN implied_prob END) as dispersion_h,
                                        STDDEV(CASE WHEN outcome = 'D' THEN implied_prob END) as dispersion_d,
                                        STDDEV(CASE WHEN outcome = 'A' THEN implied_prob END) as dispersion_a,
                                        COUNT(DISTINCT book_id) as n_books
                                    FROM bucket_classified
                                    GROUP BY time_bucket
                                    HAVING COUNT(DISTINCT book_id) >= 2
                                )
                                SELECT %s, time_bucket, consensus_h, consensus_d, consensus_a,
                                       COALESCE(dispersion_h, 0), COALESCE(dispersion_d, 0), COALESCE(dispersion_a, 0),
                                       n_books, NOW()
                                FROM consensus_calc
                                ON CONFLICT (match_id, time_bucket) DO NOTHING
                            """, (match_id, match_id))
                            
                            rows_inserted = cursor.rowcount
                            if rows_inserted > 0:
                                consensus_built += rows_inserted
                            else:
                                skipped += 1
                                failure_reasons['no_bucket_hit'] += 1
                            
                        except Exception as e:
                            error_msg = str(e).lower()
                            if 'having count(distinct book_id) >= 2' in error_msg:
                                failure_reasons['too_few_triplets'] += 1
                            elif 'division by zero' in error_msg or 'invalid probability' in error_msg:
                                failure_reasons['devig_failed'] += 1
                            elif 'conflict' in error_msg or 'duplicate' in error_msg:
                                failure_reasons['write_conflict'] += 1
                            else:
                                failure_reasons['devig_failed'] += 1  # Default category
                            
                            logger.warning(f"[CONSENSUS] Failed to build consensus for match {match_id}: {e}")
                            skipped += 1
                    
                    conn.commit()
                    # Log detailed failure telemetry
                    failure_summary = ", ".join([f"{reason}: {count}" for reason, count in failure_reasons.items() if count > 0])
                    logger.info(f"✅ [CONSENSUS] Completed: {consensus_built} new predictions, {skipped} skipped, {total_candidates} total candidates")
                    if failure_summary:
                        logger.info(f"📊 [CONSENSUS] Failure breakdown: {failure_summary}")
                    return consensus_built
                    
        except Exception as e:
            logger.error(f"[CONSENSUS] ❌ Critical error: {e}")
            return 0

# Global scheduler instance
_scheduler_instance: Optional[BackgroundScheduler] = None

def get_scheduler() -> BackgroundScheduler:
    """Get or create global scheduler instance"""
    global _scheduler_instance
    if _scheduler_instance is None:
        _scheduler_instance = BackgroundScheduler()
    return _scheduler_instance

def start_background_scheduler():
    """Start the background scheduler if not already running"""
    scheduler = get_scheduler()
    if not scheduler.is_running:
        scheduler.start_scheduler()
        return True
    return False

def trigger_manual_collection():
    """Trigger manual collection cycle for testing (bypasses timing restrictions)"""
    scheduler = get_scheduler()
    return scheduler.trigger_immediate_collection(force=True)

def stop_background_scheduler():
    """Stop the background scheduler"""
    scheduler = get_scheduler()
    scheduler.stop_scheduler()