"""
BetGenius AI Backend - Task Scheduler
Background scheduler for automated data collection and model updates
"""

import asyncio
import logging
from datetime import datetime, time as dt_time
from typing import Optional
import threading
import json
import psycopg2
import os
import sys
import time
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
        # Live data collection (runs every 60 seconds for live matches)
        self.last_live_data_run: Optional[datetime] = None
        # AI analysis triggers (runs every 60 seconds, checks if analysis needed)
        self.last_ai_analysis_run: Optional[datetime] = None
        # Fixture ID resolver (runs every 60 seconds to link fixtures with API-Football IDs)
        self.last_fixture_resolver_run: Optional[datetime] = None
        # TBD Fixture Resolver (runs every 5 minutes to update placeholder teams)
        self.last_tbd_resolver_run: Optional[datetime] = None
        # Momentum calculator (Phase 2 - runs every 60 seconds for live matches)
        self.last_momentum_calc_run: Optional[datetime] = None
        # Live market engine (Phase 2 - runs every 60 seconds for in-play predictions)
        self.last_live_markets_run: Optional[datetime] = None
        # Stale data cleanup (Phase 2 - runs every 30 minutes to remove old live data)
        self.last_stale_cleanup_run: Optional[datetime] = None
        # Scheduled collection state tracking (prevents duplicate runs)
        self.last_scheduled_collection_run: Optional[datetime] = None
        self.last_scheduled_collection_hour: Optional[int] = None
        # Seed collection trigger (when 10-min window empty)
        self.last_seed_collection_run: Optional[datetime] = None
        self.last_odds_10m_check: Optional[datetime] = None
        self.consecutive_empty_checks: int = 0
        # Background task tracking (for non-blocking execution)
        self.tasks: dict = {}  # name -> asyncio.Task
        self.last_run: dict = {}  # name -> datetime
        # Match context builder (V2 - runs every 5 minutes to populate match_context_v2)
        self.last_context_builder_run: Optional[datetime] = None
        # Fixtures to matches sync (runs every 15 minutes to sync finished fixtures)
        self.last_fixtures_sync_run: Optional[datetime] = None
        # Team linkage (runs every 15 minutes to link fixtures to teams for logos)
        self.last_team_linkage_run: Optional[datetime] = None
        # Auto-retrain check (runs once per day at 03:00 UTC)
        self.last_retrain_check_run: Optional[datetime] = None
        # WC 2026 Prep: International qualifier collection (runs daily at 04:00 UTC)
        self.last_intl_qualifier_run: Optional[datetime] = None
        # Fixture seeding (runs every 4 hours to discover new upcoming matches)
        self.last_fixture_seed: Optional[datetime] = None
        
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
        logger.info("🎲 The Odds API Phase B: Continuous collection enabled - every 60 seconds (100k/day limit)")
        logger.info("⚽ API-Football Phase B: Continuous collection enabled - every 60 seconds (75k/day limit)")
        logger.info("🔗 Fixture ID Resolver enabled - runs every 60 seconds to link API-Football IDs")
        logger.info("🔄 TBD Fixture Resolver enabled - runs every 5 minutes to update placeholder teams")
        logger.info("CLV Club alert producer enabled - runs every 60 seconds")
        logger.info("CLV Club Phase 2: Closing sampler + settler enabled - runs every 60 seconds")
        logger.info("CLV Daily Brief enabled - runs once per day at 00:05 UTC")
        logger.info("🌍 WC 2026 Prep: International qualifier collection enabled - runs daily at 04:00 UTC")
        logger.info("⚽🏀 Player Stats Collection enabled - runs daily at 05:00 UTC for major leagues")
        logger.info("📊 Phase 2 Momentum Engine enabled - runs every 60 seconds for live matches")
        logger.info("🎲 Phase 2 Live Market Engine enabled - runs every 60 seconds for in-play predictions")
        logger.info("🗑️  Phase 2 Stale Data Cleanup enabled - runs every 30 minutes to remove old live data")
        logger.info("🔨 Match Context Builder (V2) enabled - runs every 5 minutes to populate match_context_v2")
        logger.info("🔥 PHASE 1: Trending Scores enabled - runs every 5 minutes to pre-compute hot/trending scores")
        logger.info("🔄 Fixtures→Matches Sync enabled - runs every 15 minutes to sync finished fixtures")
        logger.info("🔗 Team Linkage enabled - runs every 15 minutes to link fixtures for logos")
        logger.info("🤖 Auto-Retrain enabled - runs daily at 03:00 UTC (triggers: 50+ new matches, 14-day staleness, accuracy drift)")
        logger.info("🎯 V3 Sharp Book Collection enabled - runs every 5 minutes to track Pinnacle odds")
        logger.info("📊 V3 League ECE Calculator enabled - runs weekly Sunday 02:00 UTC")
        logger.info("🏥 V3 Injury Collection enabled - runs every 6 hours for player context")
        logger.info("🏀🏒 Multi-Sport Odds Collection enabled - runs every 60 minutes for NBA/NHL/MLB")
        logger.info("📊 Multi-Sport Results enabled - runs every hour to fetch completed scores")
        logger.info("🏀⚾ API-Sports Data Collection enabled - runs every hour for team/player data")
        logger.info("🎰 Parlay Generation enabled - runs every 5 minutes to generate AI-curated parlays")
    
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
        
        self._loop_count = 0
        
        while self.is_running:
            try:
                now = datetime.utcnow()
                current_hour = now.hour
                current_minute = now.minute
                weekday = now.weekday()  # 0=Monday, 6=Sunday
                is_weekend = weekday >= 5  # Saturday or Sunday
                self._loop_count += 1
                
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
                
                # STAGGER 60s tasks into 3 groups to prevent DB connection stampede
                # Group A (loop % 3 == 0): Odds collection
                # Group B (loop % 3 == 1): CLV + settlement
                # Group C (loop % 3 == 2): Live data + resolver
                group = self._loop_count % 3
                
                # GROUP A: Odds collection tasks
                if group == 0:
                    if "phase_b" not in self.last_run or (now - self.last_run["phase_b"]).total_seconds() >= 55:
                        await self._spawn("phase_b", self._run_phase_b_fresh_odds, timeout=300)
                    
                    if "theodds_phase_b" not in self.last_run or (now - self.last_run["theodds_phase_b"]).total_seconds() >= 55:
                        await self._spawn("theodds_phase_b", self._run_theodds_phase_b, timeout=600)
                    
                    if "api_football_phase_b" not in self.last_run or (now - self.last_run["api_football_phase_b"]).total_seconds() >= 55:
                        await self._spawn("api_football_phase_b", self._run_api_football_phase_b, timeout=300)
                
                # GROUP B: CLV + settlement tasks
                if group == 1:
                    if "clv_producer" not in self.last_run or (now - self.last_run["clv_producer"]).total_seconds() >= 55:
                        await self._spawn("clv_producer", self._run_clv_alert_producer, timeout=30)
                    
                    if "clv_cleanup" not in self.last_run or (now - self.last_run["clv_cleanup"]).total_seconds() >= 300:
                        await self._spawn("clv_cleanup", self._run_clv_ttl_cleanup, timeout=60)
                    
                    if "closing_sampler" not in self.last_run or (now - self.last_run["closing_sampler"]).total_seconds() >= 55:
                        await self._spawn("closing_sampler", self._run_closing_sampler, timeout=30)
                    
                    if "closing_settler" not in self.last_run or (now - self.last_run["closing_settler"]).total_seconds() >= 55:
                        await self._spawn("closing_settler", self._run_closing_settler, timeout=30)
                
                # CLV Daily Brief: Run once per day at 00:05 UTC (background task)
                if current_hour == 0 and current_minute >= 5 and current_minute < 15:
                    # Check if we already ran today
                    today_date = now.date()
                    last_run_date = self.last_daily_brief_run.date() if self.last_daily_brief_run else None
                    
                    if last_run_date != today_date:
                        await self._spawn("daily_brief", self._run_daily_brief, timeout=120)
                        self.last_daily_brief_run = now
                
                # GROUP C: Resolver + live data tasks
                if group == 2:
                    if "fixture_resolver" not in self.last_run or (now - self.last_run["fixture_resolver"]).total_seconds() >= 55:
                        await self._spawn("fixture_resolver", self._run_fixture_id_resolver, timeout=90)
                    
                    if "live_data" not in self.last_run or (now - self.last_run["live_data"]).total_seconds() >= 55:
                        await self._spawn("live_data", self._run_live_data_collection, timeout=60)
                    
                    if "ai_analysis" not in self.last_run or (now - self.last_run["ai_analysis"]).total_seconds() >= 55:
                        await self._spawn("ai_analysis", self._run_live_ai_analysis, timeout=90)
                    
                    if "momentum_calc" not in self.last_run or (now - self.last_run["momentum_calc"]).total_seconds() >= 55:
                        await self._spawn("momentum_calc", self._run_momentum_calculator, timeout=30)
                    
                    if "live_markets" not in self.last_run or (now - self.last_run["live_markets"]).total_seconds() >= 55:
                        await self._spawn("live_markets", self._run_live_market_engine, timeout=30)
                
                # TBD resolver runs every 5 min regardless of group
                if "tbd_resolver" not in self.last_run or (now - self.last_run["tbd_resolver"]).total_seconds() >= 300:
                    await self._spawn("tbd_resolver", self._run_tbd_fixture_resolver, timeout=60)
                
                # 🗑️ PHASE 2: Stale data cleanup - runs every 30 minutes to remove old live data
                if "stale_cleanup" not in self.last_run or (now - self.last_run["stale_cleanup"]).total_seconds() >= 1800:
                    await self._spawn("stale_cleanup", self._cleanup_stale_live_data, timeout=30)
                
                # 🔨 Match Context Builder (V2) - runs every 5 minutes to populate match_context_v2
                if "context_builder" not in self.last_run or (now - self.last_run["context_builder"]).total_seconds() >= 300:
                    await self._spawn("context_builder", self._run_match_context_builder, timeout=60)
                
                # 🔥 PHASE 1: Trending Scores Computation - runs every 5 minutes to pre-compute hot/trending scores
                if "trending_scores" not in self.last_run or (now - self.last_run["trending_scores"]).total_seconds() >= 300:
                    await self._spawn("trending_scores", self._run_trending_scores_computation, timeout=120)
                
                # 🎰 Parlay Generation - runs every 5 minutes to generate AI-curated parlays
                if "parlay_generation" not in self.last_run or (now - self.last_run["parlay_generation"]).total_seconds() >= 300:
                    await self._spawn("parlay_generation", self._run_parlay_generation, timeout=60)
                
                # 🎰 Parlay Settlement - runs every 15 minutes to settle finished parlays
                if "parlay_settlement" not in self.last_run or (now - self.last_run["parlay_settlement"]).total_seconds() >= 900:
                    await self._spawn("parlay_settlement", self._run_parlay_settlement, timeout=60)
                
                # 🔄 Fixtures→Matches Sync - runs every 15 minutes to sync finished fixtures
                if "fixtures_sync" not in self.last_run or (now - self.last_run["fixtures_sync"]).total_seconds() >= 900:
                    await self._spawn("fixtures_sync", self._run_fixtures_to_matches_sync, timeout=120)
                
                # 🔗 Team Linkage - runs every 15 minutes to link fixtures to teams for logos
                if "team_linkage" not in self.last_run or (now - self.last_run["team_linkage"]).total_seconds() >= 900:
                    await self._spawn("team_linkage", self._run_team_linkage, timeout=60)
                
                # 🤖 Auto-Retrain Check - runs once per day at 03:00 UTC
                current_hour = now.hour
                if current_hour == 3:
                    if "auto_retrain" not in self.last_run or (now - self.last_run["auto_retrain"]).total_seconds() >= 86400:
                        await self._spawn("auto_retrain", self._run_auto_retrain_check, timeout=1800)
                
                # 📊 V0: ELO Update - runs once per day at 04:00 UTC to update team ratings
                if current_hour == 4:
                    if "elo_update" not in self.last_run or (now - self.last_run["elo_update"]).total_seconds() >= 86400:
                        await self._spawn("elo_update", self._run_elo_update, timeout=300)
                
                # 🎯 V3: Sharp Book Collection - runs every 5 minutes to track Pinnacle odds
                if "sharp_book" not in self.last_run or (now - self.last_run["sharp_book"]).total_seconds() >= 300:
                    await self._spawn("sharp_book", self._run_sharp_book_collection, timeout=120)
                
                # 🏀🏒 Multi-Sport Odds Collection - runs every 60 minutes for NBA/NHL/MLB (reduced from 5min to slow DB growth)
                if "multisport_odds" not in self.last_run or (now - self.last_run["multisport_odds"]).total_seconds() >= 3600:
                    await self._spawn("multisport_odds", self._run_multisport_odds_collection, timeout=120)
                
                # 📊 Multi-Sport Results - runs every hour to fetch completed game scores
                if "multisport_results" not in self.last_run or (now - self.last_run["multisport_results"]).total_seconds() >= 3600:
                    await self._spawn("multisport_results", self._run_multisport_results_collection, timeout=60)
                
                # 🏀⚾ API-Sports Data - runs every hour to sync team data
                if "api_sports" not in self.last_run or (now - self.last_run["api_sports"]).total_seconds() >= 3600:
                    await self._spawn("api_sports", self._run_api_sports_collection, timeout=180)
                
                # 🏀🏒🏈 Multi-Sport Comprehensive Data - runs every 2 hours (matches, team stats, standings)
                if "multisport_data" not in self.last_run or (now - self.last_run["multisport_data"]).total_seconds() >= 7200:
                    await self._spawn("multisport_data", self._run_multisport_data_collection, timeout=300)
                
                # 📊 V3: League ECE Calculator - runs weekly on Sunday at 02:00 UTC
                if now.weekday() == 6 and now.hour == 2:  # Sunday 02:00 UTC
                    if "league_ece" not in self.last_run or (now - self.last_run["league_ece"]).total_seconds() >= 86400:
                        await self._spawn("league_ece", self._run_league_ece_calculation, timeout=300)
                
                # 🏥 V3: Injury Collection - runs every 6 hours
                if "injury_collection" not in self.last_run or (now - self.last_run["injury_collection"]).total_seconds() >= 21600:
                    await self._spawn("injury_collection", self._run_injury_collection, timeout=300)
                
                # 🌍 WC 2026 Prep: International Qualifier Collection - runs daily at 04:00 UTC
                if current_hour == 4:
                    if "intl_qualifiers" not in self.last_run or (now - self.last_run["intl_qualifiers"]).total_seconds() >= 86400:
                        await self._spawn("intl_qualifiers", self._run_intl_qualifier_collection, timeout=600)
                
                # ⚽🏀 Player Stats Collection - runs daily at 05:00 UTC
                if current_hour == 5:
                    if "player_stats" not in self.last_run or (now - self.last_run["player_stats"]).total_seconds() >= 86400:
                        await self._spawn("player_stats", self._run_player_stats_collection, timeout=900)
                
                # 🎰 Player Prop Odds Collection - runs every 2 hours for NBA/NHL
                if "player_prop_odds" not in self.last_run or (now - self.last_run["player_prop_odds"]).total_seconds() >= 7200:
                    await self._spawn("player_prop_odds", self._run_player_prop_odds_collection, timeout=300)
                
                # ⚽ Soccer Scorer Odds Collection - runs every 4 hours for anytime goalscorer markets
                if "soccer_scorer_odds" not in self.last_run or (now - self.last_run["soccer_scorer_odds"]).total_seconds() >= 14400:
                    await self._spawn("soccer_scorer_odds", self._run_soccer_scorer_odds_collection, timeout=600)
                
                # 🌱 Fixture Seeding - runs every 4 hours to discover new upcoming matches
                if "fixture_seeding" not in self.last_run or (now - self.last_run["fixture_seeding"]).total_seconds() >= 14400:
                    await self._spawn("fixture_seeding", self._run_fixture_seeding, timeout=300)
                
                # Check every 1 second for responsive scheduling (background tasks run independently)
                await asyncio.sleep(1)
                
                # Every 15 minutes, run safety net to fill missing buckets
                if "safety_net" not in self.last_run or (now - self.last_run["safety_net"]).total_seconds() >= 900:
                    await self._spawn("safety_net", self._run_safety_net, timeout=120)
                
                # Seed collection trigger: if 10-min window empty for 15 minutes, trigger small collection
                if "seed_check" not in self.last_run or (now - self.last_run["seed_check"]).total_seconds() >= 60:
                    await self._spawn("seed_check", self._check_and_trigger_seed_collection, timeout=30)
                    
            except Exception as e:
                logger.error(f"Scheduler loop error: {e}")
                await asyncio.sleep(300)  # Wait 5 minutes before retry
    
    async def _check_and_trigger_seed_collection(self):
        """Check if 10-min odds window is empty, trigger seed collection if needed"""
        try:
            import psycopg2
            
            database_url = os.environ.get('DATABASE_URL')
            if not database_url:
                return
            
            with psycopg2.connect(database_url, connect_timeout=10) as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT COUNT(*) FROM odds_snapshots WHERE ts_snapshot > NOW() - INTERVAL '10 minutes'")
                    result = cursor.fetchone()
                    odds_10m_count = result[0] if result else 0
                    
                    cursor.execute("SELECT COUNT(*) FROM fixtures WHERE kickoff_at > NOW() AND kickoff_at < NOW() + INTERVAL '7 days'")
                    result = cursor.fetchone()
                    upcoming_fixtures_count = result[0] if result else 0
            
            now = datetime.utcnow()
            
            if upcoming_fixtures_count < 10:
                logger.warning(f"🌱 FIXTURE STARVATION: Only {upcoming_fixtures_count} upcoming fixtures - triggering fixture seeding")
                if not hasattr(self, 'last_fixture_seed') or not self.last_fixture_seed or (now - self.last_fixture_seed).total_seconds() >= 7200:
                    async def run_fixture_seed():
                        try:
                            results = await self.collector.seed_upcoming_fixtures()
                            logger.info(f"🌱 Fixture seeding completed: {results.get('fixtures_inserted', 0)} fixtures inserted")
                            self.last_fixture_seed = datetime.utcnow()
                        except Exception as e:
                            logger.error(f"🌱 Fixture seeding failed: {e}")
                    
                    await self._spawn("fixture_seeding", run_fixture_seed, timeout=300)
                else:
                    logger.info(f"🌱 Fixtures low ({upcoming_fixtures_count}) but seeding ran recently")
            
            if odds_10m_count == 0:
                # 10-min window is empty - increment counter
                self.consecutive_empty_checks += 1
                logger.info(f"🌱 SEED: 10-min window empty ({self.consecutive_empty_checks}/15min)")
                
                # If empty for 15 minutes (15 consecutive 60s checks), trigger seed collection
                if self.consecutive_empty_checks >= 15:
                    # Check if we've run seed collection in the last 30 minutes
                    if not self.last_seed_collection_run or (now - self.last_seed_collection_run).total_seconds() >= 1800:
                        logger.info(f"🌱 SEED TRIGGER FIRING: 10-min window empty for {self.consecutive_empty_checks}min, triggering seed collection...")
                        
                        # Trigger a small targeted collection (top 50 upcoming fixtures)
                        async def run_seed():
                            try:
                                results = await self.collector.daily_collection_cycle()
                                logger.info(f"🌱 Seed collection completed: {results.get('new_odds_collected', 0)} new odds")
                                self.last_seed_collection_run = datetime.utcnow()
                                self.consecutive_empty_checks = 0  # Reset counter after successful seed
                            except Exception as e:
                                logger.error(f"🌱 Seed collection failed: {e}")
                        
                        await self._spawn("seed_collection", run_seed, timeout=300)
                    else:
                        logger.info(f"🌱 SEED: Window empty ({self.consecutive_empty_checks}min) but seed ran recently")
                else:
                    pass  # Already logged above
            else:
                # Fresh odds exist - reset counter
                if self.consecutive_empty_checks > 0:
                    logger.info(f"🌱 SEED: 10-min window restored ({odds_10m_count} odds), reset counter from {self.consecutive_empty_checks}")
                self.consecutive_empty_checks = 0
                
        except Exception as e:
            logger.error(f"🌱 Seed check error: {e}")
    
    async def _run_fixture_seeding(self):
        """Run fixture seeding to discover and insert new upcoming matches from API-Football"""
        try:
            logger.info("🌱 Running scheduled fixture seeding...")
            
            results = await self.collector.seed_upcoming_fixtures()
            
            if results.get('fixtures_inserted', 0) > 0:
                logger.info(f"🌱 Fixture seeding: {results['fixtures_inserted']} fixtures inserted from {results.get('leagues_processed', 0)} leagues")
            else:
                logger.info(f"🌱 Fixture seeding: No new fixtures found (checked {results.get('leagues_processed', 0)} leagues)")
                
        except Exception as e:
            logger.error(f"🌱 Fixture seeding error: {e}")
    
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
        🎯 FAST Phase B: Targeted prediction building for matches with fresh odds
        - Finds matches with fresh odds (last 10min) but stale/no predictions
        - Builds predictions every minute for those matches
        - Completes in <30s, non-blocking
        """
        logger.info("🚀 Phase B START: Beginning execution...")
        try:
            import time
            import psycopg2
            
            start_time = time.time()
            logger.info("🚀 Phase B: Imports successful, starting queries...")
            
            # Step 1: Query matches needing predictions (fresh odds, stale/no predictions)
            database_url = os.environ.get('DATABASE_URL')
            if not database_url:
                logger.error("Phase B: DATABASE_URL not found")
                return
            
            # Check if we have fresh odds (10min window)
            logger.info("🔍 Phase B: Checking for fresh odds...")
            has_fresh_odds = False
            with psycopg2.connect(database_url, connect_timeout=10) as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT EXISTS(SELECT 1 FROM odds_snapshots WHERE ts_snapshot > NOW() - INTERVAL '10 minutes')")
                    result = cursor.fetchone()
                    has_fresh_odds = result[0] if result else False
            logger.info(f"🔍 Phase B: Fresh odds check complete (has_fresh={has_fresh_odds})")
            
            # Use wider window (60min) if no fresh odds, to keep predictions growing between collections
            recent_window = '10 minutes' if has_fresh_odds else '60 minutes'
            logger.info(f"🔍 Phase B: Using {recent_window} window for target search...")
            
            # Find targets with recent odds but stale/no predictions
            target_matches = []
            with psycopg2.connect(database_url, connect_timeout=10) as conn:
                with conn.cursor() as cursor:
                    # Status can be 'NS' or 'scheduled' (different APIs use different conventions)
                    cursor.execute(f"""
                        WITH upcoming AS (
                            SELECT f.match_id
                            FROM fixtures f
                            WHERE f.kickoff_at BETWEEN NOW() + INTERVAL '6 hours' 
                                AND NOW() + INTERVAL '168 hours'
                            AND f.status IN ('NS', 'scheduled')
                        ),
                        recent_odds AS (
                            SELECT DISTINCT os.match_id
                            FROM odds_snapshots os
                            WHERE os.ts_snapshot > NOW() - INTERVAL '{recent_window}'
                        ),
                        stale_preds AS (
                            SELECT u.match_id
                            FROM upcoming u
                            LEFT JOIN LATERAL (
                                SELECT MAX(cp.created_at) AS last_pred_at
                                FROM consensus_predictions cp
                                WHERE cp.match_id = u.match_id
                            ) p ON TRUE
                            WHERE p.last_pred_at IS NULL 
                                OR p.last_pred_at < NOW() - INTERVAL '30 minutes'
                        )
                        SELECT sp.match_id
                        FROM stale_preds sp
                        JOIN recent_odds ro USING (match_id)
                        ORDER BY sp.match_id
                        LIMIT 50
                    """)
                    target_matches = [row[0] for row in cursor.fetchall()]
            logger.info(f"🔍 Phase B: Found {len(target_matches)} target matches needing predictions")
            
            # Step 2: ALWAYS refresh odds_consensus from odds_snapshots (critical for CLV + predictions!)
            # This runs every minute regardless of whether predictions are needed
            try:
                from models.database import DatabaseManager
                db_manager = DatabaseManager()
                consensus_refreshed = db_manager.refresh_odds_consensus_from_snapshots(lookback_minutes=1440)
                if consensus_refreshed > 0:
                    logger.info(f"🔄 Phase B: Refreshed {consensus_refreshed} odds_consensus rows")
            except Exception as refresh_error:
                logger.error(f"❌ Phase B consensus refresh failed: {refresh_error}")
            
            if not target_matches:
                logger.debug(f"🎯 Phase B: No matches need predictions (completed in {int((time.time()-start_time)*1000)}ms)")
                return
            
            logger.info(f"🎯 Phase B: Building predictions for {len(target_matches)} matches with fresh odds...")
            
            # Step 3: Build predictions for target matches
            try:
                built_count = self.build_consensus_predictions()
                elapsed_ms = int((time.time() - start_time) * 1000)
                
                if built_count > 0:
                    logger.info(f"📈 consensus_predictions: built={built_count} for {len(target_matches)} targets ({elapsed_ms}ms)")
                else:
                    logger.debug(f"🎯 Phase B: 0 predictions built ({elapsed_ms}ms)")
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
    
    async def _run_theodds_phase_b(self):
        """
        🎲 The Odds API Phase B: Continuous odds collection every 60 seconds
        Primary source for multi-bookmaker odds (21+ bookmakers)
        100,000 requests/day limit = ~69 req/min capacity (plenty of headroom)
        """
        try:
            logger.info("🎲 The Odds API Phase B: Starting collection...")
            
            # Call The Odds API collection method
            results = await self.collector.collect_upcoming_odds_snapshots()
            
            if results.get("new_odds_collected", 0) > 0:
                logger.info(f"🎲 The Odds API: {results['new_odds_collected']} odds snapshots collected " +
                           f"from {results.get('upcoming_matches_found', 0)} matches")
            else:
                logger.debug(f"🎲 The Odds API: No new odds collected")
                
        except Exception as e:
            logger.error(f"🎲 The Odds API Phase B error: {e}")
    
    async def _run_api_football_phase_b(self):
        """
        ⚽ API-Football Phase B: Continuous odds collection every 60 seconds
        Complements The Odds API for comprehensive multi-source market coverage
        75,000 requests/day limit = ~52 req/min capacity (plenty of headroom)
        """
        try:
            logger.info("⚽ API-Football Phase B: Starting collection...")
            
            # Use existing method from automated_collector
            results = await self.collector.collect_upcoming_odds_apifootball()
            
            if results.get("rows_inserted", 0) > 0:
                logger.info(f"⚽ API-Football: {results['rows_inserted']} odds rows collected " +
                           f"from {results.get('fixtures_processed', 0)} fixtures")
            else:
                logger.debug(f"⚽ API-Football: No new odds collected")
                
        except Exception as e:
            logger.error(f"⚽ API-Football Phase B error: {e}")
    
    async def _run_fixture_id_resolver(self):
        """
        🔗 PHASE 2: Fixture ID Resolver
        Automatically resolves and links fixtures to API-Football IDs using 3-pass approach:
        1. Sync from cache (for known matches)
        2. Sync recent fixtures from cache
        3. API search for unresolved fixtures (limit 10 per cycle to avoid rate limits)
        Runs every 60 seconds
        """
        try:
            from models.fixture_id_resolver import FixtureIDResolver
            
            logger.debug("🔗 Fixture ID Resolver: Starting...")
            resolver = FixtureIDResolver()
            results = resolver.resolve_all(api_search_limit=10)  # Limit to 10 API calls per cycle
            
            if results["total_resolved"] > 0:
                logger.info(f"🔗 Fixture ID Resolver: Resolved {results['total_resolved']} fixtures "
                          f"(Pass1: {results['pass1_table_join']}, "
                          f"Pass2: {results['pass2_cache_lookup']}, "
                          f"Pass3: {results['pass3_api_search']})")
            
        except Exception as e:
            logger.error(f"🔗 Fixture ID Resolver error: {e}")
    
    async def _run_tbd_fixture_resolver(self):
        """
        🔄 PHASE 2: TBD Fixture Resolver
        Automatically updates fixtures with "TBD" placeholder teams:
        1. Queries The Odds API to check if teams have been determined
        2. Updates fixtures table with real team names
        3. Cleans up old finished TBD fixtures (24h retention)
        Runs every 5 minutes
        """
        try:
            from models.tbd_fixture_resolver import run_tbd_resolution
            
            logger.debug("🔄 TBD Fixture Resolver: Starting...")
            run_tbd_resolution()
            
        except Exception as e:
            logger.error(f"🔄 TBD Fixture Resolver error: {e}")
    
    async def _run_live_data_collection(self):
        """
        🔴 PHASE 1: Live match data collection
        Collects real-time scores, statistics, and events from API-Football
        Runs every 60 seconds for live matches
        """
        try:
            from models.live_data_collector import collect_live_data
            
            logger.debug("🔴 Live data collection: Starting...")
            collect_live_data()  # Synchronous function
            
        except Exception as e:
            logger.error(f"🔴 Live data collection error: {e}")
    
    async def _run_live_ai_analysis(self):
        """
        🤖 PHASE 1: AI analysis triggers
        Checks all live matches and triggers OpenAI analysis when:
        - Time interval reached (every 4 minutes)
        - Significant odds movement (>5% change)
        - Key events (goals, red cards)
        Runs every 60 seconds
        """
        try:
            from models.live_ai_analyzer import analyze_live_matches
            
            logger.debug("🤖 AI analysis: Checking live matches...")
            analyze_live_matches()  # Synchronous function
            
        except Exception as e:
            logger.error(f"🤖 AI analysis error: {e}")
    
    async def _run_momentum_calculator(self):
        """
        📊 PHASE 2: Momentum calculator
        Calculates 0-100 momentum scores for live matches based on:
        - Shots on target (35% weight)
        - Dangerous attacks (20% weight)
        - Possession differential (10% weight)
        - xG differential (20% weight)
        - Odds velocity (15% weight)
        - Discipline modifiers (red cards)
        Uses exponential decay to emphasize recent events
        Runs every 60 seconds
        """
        try:
            from models.momentum_calculator import calculate_momentum
            
            logger.debug("📊 Momentum: Calculating...")
            calculate_momentum()  # Synchronous function
            
        except Exception as e:
            logger.error(f"📊 Momentum calculator error: {e}")
    
    async def _run_live_market_engine(self):
        """
        🎲 PHASE 2: Live market engine
        Generates in-play predictions for:
        - Win/Draw/Win (1X2 live)
        - Over/Under 2.5 (live line)
        - Next Goal (home/none/away)
        Uses time-aware blending of market + pre-match model + momentum
        Runs every 60 seconds
        """
        try:
            from models.live_market_engine import compute_live_markets
            
            logger.debug("🎲 Live markets: Computing...")
            compute_live_markets()  # Synchronous function
            
        except Exception as e:
            logger.error(f"🎲 Live market engine error: {e}")
    
    async def _cleanup_stale_live_data(self):
        """
        🗑️ PHASE 2: Stale data cleanup
        Removes live match data that's older than 4 hours to prevent stale data issues
        Also updates fixture status to 'finished' for completed matches
        """
        try:
            database_url = os.environ.get('DATABASE_URL')
            if not database_url:
                logger.error("🗑️ Cleanup: DATABASE_URL not found")
                return
            
            with psycopg2.connect(database_url, connect_timeout=10) as conn:
                with conn.cursor() as cursor:
                    # Delete stale live match stats (>4 hours old)
                    cursor.execute("""
                        DELETE FROM live_match_stats
                        WHERE timestamp < NOW() - INTERVAL '4 hours'
                    """)
                    deleted_stats = cursor.rowcount
                    
                    # Delete stale live momentum data (>4 hours old)
                    cursor.execute("""
                        DELETE FROM live_momentum
                        WHERE updated_at < NOW() - INTERVAL '4 hours'
                    """)
                    deleted_momentum = cursor.rowcount
                    
                    # Delete stale match events (>4 hours old)
                    cursor.execute("""
                        DELETE FROM match_events
                        WHERE timestamp < NOW() - INTERVAL '4 hours'
                    """)
                    deleted_events = cursor.rowcount
                    
                    # Update fixture status for matches that are clearly finished
                    # (kicked off >4 hours ago and have no recent live data)
                    cursor.execute("""
                        UPDATE fixtures
                        SET status = 'finished'
                        WHERE status = 'scheduled'
                          AND kickoff_at <= NOW()
                          AND kickoff_at < NOW() - INTERVAL '4 hours'
                          AND NOT EXISTS (
                              SELECT 1 FROM live_match_stats lms
                              WHERE lms.match_id = fixtures.match_id
                              AND lms.timestamp > NOW() - INTERVAL '10 minutes'
                          )
                    """)
                    updated_fixtures = cursor.rowcount
                    
                    conn.commit()
                    
                    if deleted_stats > 0 or deleted_momentum > 0 or deleted_events > 0 or updated_fixtures > 0:
                        logger.info(f"🗑️ Cleanup complete: {deleted_stats} stats, {deleted_momentum} momentum, {deleted_events} events deleted, {updated_fixtures} fixtures marked finished")
            
            self.last_run["stale_cleanup"] = datetime.utcnow()
            
        except Exception as e:
            logger.error(f"🗑️ Stale data cleanup error: {e}")
            self.last_run["stale_cleanup"] = datetime.utcnow()
    
    async def _run_match_context_builder(self):
        """
        🔨 Match Context Builder (V2)
        Automatically builds match_context_v2 entries for new matches
        Uses strict pre-match timestamps to prevent data leakage
        Runs every 5 minutes
        """
        try:
            from models.match_context_builder import build_context_for_recent_matches
            
            logger.debug("🔨 Context builder: Checking for new matches...")
            rows_created = build_context_for_recent_matches(lookback_hours=48)
            
            if rows_created > 0:
                logger.info(f"🔨 Context builder: Built context for {rows_created} new matches")
            
            self.last_run["context_builder"] = datetime.utcnow()
            
        except Exception as e:
            logger.error(f"🔨 Match context builder error: {e}")
            self.last_run["context_builder"] = datetime.utcnow()
    
    async def _run_clv_ttl_cleanup(self):
        """Archive expired CLV alerts to history table"""
        try:
            import psycopg2
            import os
            
            database_url = os.environ.get('DATABASE_URL')
            if not database_url:
                return
            
            with psycopg2.connect(database_url, connect_timeout=10) as conn:
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
        """Run Phase 2 closing capture (collects closing odds near kickoff)"""
        try:
            from models.closing_capture import run_closing_capture
            
            stats = run_closing_capture()
            
            if stats.get('odds_captured', 0) > 0:
                logger.debug(f"📸 Closing capture: {stats['odds_captured']} odds captured " +
                           f"(capture rate: {stats.get('capture_rate_24h', 0):.1f}%)")
            
            self.last_closing_sampler_run = datetime.utcnow()
                
        except Exception as e:
            logger.error(f"📸 Closing capture error: {e}")
    
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
            
            with psycopg2.connect(database_url, connect_timeout=10) as conn:
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
                                    WHERE match_id = %s AND ts_snapshot > NOW() - INTERVAL '96 hours'
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
                                            WHEN secs_to_kickoff BETWEEN 5400 AND 32400 THEN '6h'    -- 1.5-9h
                                            WHEN secs_to_kickoff BETWEEN 21600 AND 64800 THEN '12h'  -- 6-18h
                                            WHEN secs_to_kickoff BETWEEN 64800 AND 108000 THEN '24h' -- 18-30h
                                            WHEN secs_to_kickoff BETWEEN 108000 AND 151200 THEN '36h'-- 30-42h (NEW - closes the gap!)
                                            WHEN secs_to_kickoff BETWEEN 151200 AND 237600 THEN '48h'-- 42-66h
                                            WHEN secs_to_kickoff BETWEEN 237600 AND 324000 THEN '72h'-- 66-90h
                                            WHEN secs_to_kickoff BETWEEN 900 AND 5400 THEN '3h'      -- 0.25-1.5h
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

    async def _run_trending_scores_computation(self):
        """
        🔥 PHASE 1: Compute trending and hot scores
        Pre-computed scores cached for <5ms serving
        Runs every 5 minutes
        """
        try:
            from jobs.compute_trending_scores import compute_trending_scores_job
            logger.info("🔥 TRENDING: Starting scores computation...")
            success = await compute_trending_scores_job()
            if success:
                logger.info("✅ TRENDING: Scores computation completed successfully")
            else:
                logger.warning("⚠️ TRENDING: Scores computation completed with warnings")
        except ImportError:
            logger.warning("⚠️ TRENDING: compute_trending_scores module not found - skipping")
        except Exception as e:
            logger.error(f"❌ TRENDING: Scores computation failed - {e}", exc_info=True)

    async def _run_parlay_generation(self):
        """
        🎰 Parlay Generation Job
        Generates AI-curated parlays with correlation adjustments and edge calculation.
        Runs every 5 minutes.
        """
        try:
            from models.parlay_builder import ParlayBuilder
            logger.info("🎰 PARLAY: Starting parlay generation...")
            builder = ParlayBuilder()
            saved_count = builder.refresh_parlays()
            if saved_count > 0:
                logger.info(f"✅ PARLAY: Generated and saved {saved_count} parlays")
            else:
                logger.debug("🎰 PARLAY: No new parlays to generate")
        except ImportError:
            logger.warning("⚠️ PARLAY: parlay_builder module not found - skipping")
        except Exception as e:
            logger.error(f"❌ PARLAY: Parlay generation failed - {e}", exc_info=True)
        
        try:
            from models.automated_parlay_generator import AutomatedParlayGenerator
            logger.info("🎰 AUTO-PARLAY: Starting automated same-match parlay generation...")
            gen = AutomatedParlayGenerator()
            result = gen.generate_all_upcoming_parlays(hours_ahead=48)
            total = result.get('total_parlays_generated', 0)
            matches = result.get('matches_processed', 0)
            if total > 0:
                logger.info(f"✅ AUTO-PARLAY: Generated {total} parlays from {matches} matches")
            else:
                logger.debug("🎰 AUTO-PARLAY: No new automated parlays to generate")
        except ImportError:
            logger.debug("⚠️ AUTO-PARLAY: automated_parlay_generator module not ready - skipping")
        except Exception as e:
            logger.error(f"❌ AUTO-PARLAY: Automated parlay generation failed - {e}", exc_info=True)
        
        try:
            from models.player_parlay_generator import PlayerParlayGenerator
            logger.info("⚽ PLAYER-PARLAY: Starting player scorer parlay generation...")
            gen = PlayerParlayGenerator()
            result = gen.generate_all_player_parlays(hours_ahead=72)
            total = result.get('parlays_generated', 0)
            legs = result.get('legs_generated', 0)
            if total > 0:
                logger.info(f"✅ PLAYER-PARLAY: Generated {total} player parlays from {legs} scorer picks")
            else:
                logger.debug(f"⚽ PLAYER-PARLAY: {result.get('status', 'no parlays')}")
        except ImportError:
            logger.debug("⚠️ PLAYER-PARLAY: player_parlay_generator module not ready - skipping")
        except Exception as e:
            logger.error(f"❌ PLAYER-PARLAY: Player parlay generation failed - {e}", exc_info=True)

    async def _run_parlay_settlement(self):
        """
        🎰 Parlay Settlement Job
        Settles finished parlays and tracks performance.
        Runs every 15 minutes.
        """
        try:
            from jobs.settle_parlays import settle_parlays_job
            logger.info("🎰 SETTLEMENT: Starting parlay settlement...")
            result = await settle_parlays_job()
            settled = result.get('settled', 0)
            if settled > 0:
                logger.info(f"✅ SETTLEMENT: Settled {settled} parlays (Won: {result.get('won', 0)}, Lost: {result.get('lost', 0)})")
            else:
                logger.debug("🎰 SETTLEMENT: No parlays to settle")
        except ImportError:
            logger.warning("⚠️ SETTLEMENT: settle_parlays module not found - skipping")
        except Exception as e:
            logger.error(f"❌ SETTLEMENT: Parlay settlement failed - {e}", exc_info=True)
        
        try:
            from models.automated_parlay_generator import AutomatedParlayGenerator
            logger.info("🎰 AUTO-SETTLE: Starting automated parlay settlement...")
            gen = AutomatedParlayGenerator()
            result = gen.settle_parlays()
            settled = result.get('settled', 0)
            if settled > 0:
                logger.info(f"✅ AUTO-SETTLE: Settled {settled} automated parlays (Won: {result.get('won', 0)}, Lost: {result.get('lost', 0)})")
            else:
                logger.debug("🎰 AUTO-SETTLE: No automated parlays to settle")
        except ImportError:
            logger.debug("⚠️ AUTO-SETTLE: automated_parlay_generator module not ready - skipping")
        except Exception as e:
            logger.error(f"❌ AUTO-SETTLE: Automated parlay settlement failed - {e}", exc_info=True)
        
        try:
            from jobs.settle_parlays import settle_player_parlays_job
            logger.info("⚽ PLAYER-SETTLE: Starting player parlay settlement...")
            result = await settle_player_parlays_job()
            settled = result.get('settled', 0)
            if settled > 0:
                logger.info(f"✅ PLAYER-SETTLE: Settled {settled} player parlays (Won: {result.get('won', 0)}, Lost: {result.get('lost', 0)})")
            else:
                logger.debug("⚽ PLAYER-SETTLE: No player parlays to settle")
        except ImportError:
            logger.debug("⚠️ PLAYER-SETTLE: settle_player_parlays_job not available - skipping")
        except Exception as e:
            logger.error(f"❌ PLAYER-SETTLE: Player parlay settlement failed - {e}", exc_info=True)
        
        try:
            from jobs.settle_parlays import settle_match_parlay_legs_job
            result = await settle_match_parlay_legs_job()
            settled = result.get('settled', 0)
            if settled > 0:
                logger.info(f"✅ MATCH-LEGS-SETTLE: Settled {settled} match parlay legs (Won: {result.get('won', 0)}, Lost: {result.get('lost', 0)})")
        except ImportError:
            pass
        except Exception as e:
            logger.error(f"❌ MATCH-LEGS-SETTLE: Failed - {e}")

    async def _run_fixtures_to_matches_sync(self):
        """
        🔄 Fixtures→Matches Sync Job
        Syncs finished fixtures with results to the matches table.
        Runs every 15 minutes.
        """
        try:
            from jobs.sync_fixtures_to_matches import sync_fixtures_to_matches_job
            logger.info("🔄 SYNC: Starting fixtures→matches sync...")
            result = await sync_fixtures_to_matches_job()
            synced = result.get('synced', 0)
            skipped = result.get('skipped', 0)
            errors = result.get('errors', 0)
            if synced > 0:
                logger.info(f"✅ SYNC: Completed - synced={synced}, skipped={skipped}, errors={errors}")
            else:
                logger.debug(f"🔄 SYNC: No new fixtures to sync")
        except ImportError:
            logger.warning("⚠️ SYNC: sync_fixtures_to_matches module not found - skipping")
        except Exception as e:
            logger.error(f"❌ SYNC: Fixtures→matches sync failed - {e}", exc_info=True)

    async def _run_team_linkage(self):
        """
        🔗 Team Linkage Job
        Links fixtures to teams table by matching team names.
        Populates home_team_id and away_team_id for logo URLs.
        Runs every 15 minutes.
        """
        try:
            from models.team_linkage import TeamLinkageService
            
            service = TeamLinkageService()
            conn = psycopg2.connect(os.environ.get('DATABASE_URL'), connect_timeout=10)
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT match_id, home_team, away_team, league_id
                FROM fixtures
                WHERE kickoff_at > NOW() - INTERVAL '2 hours'
                  AND home_team != 'TBD' AND away_team != 'TBD'
                  AND (home_team_id IS NULL OR away_team_id IS NULL)
                ORDER BY kickoff_at ASC
                LIMIT 100
            """)
            fixtures = cursor.fetchall()
            
            if not fixtures:
                logger.debug("🔗 LINKAGE: No fixtures to link")
                conn.close()
                return
            
            logger.info(f"🔗 LINKAGE: Starting team linkage for {len(fixtures)} fixtures...")
            linked = 0
            for match_id, home, away, league_id in fixtures:
                result = service.link_fixture(match_id, home, away, league_id)
                if result and result.get('success'):
                    linked += 1
            
            conn.close()
            logger.info(f"✅ LINKAGE: Linked {linked}/{len(fixtures)} fixtures to teams")
        except ImportError:
            logger.warning("⚠️ LINKAGE: team_linkage module not found - skipping")
        except Exception as e:
            logger.error(f"❌ LINKAGE: Team linkage failed - {e}", exc_info=True)

    async def _run_auto_retrain_check(self):
        """
        🤖 Auto-Retrain Check Job
        Checks triggers and retrains V2 model if needed.
        Runs daily at 03:00 UTC.
        
        Triggers:
        1. Match Volume: 50+ new finished matches
        2. Model Staleness: Model not trained in 14+ days
        3. Accuracy Drift: Recent accuracy below 48%
        """
        try:
            from jobs.auto_retrain import auto_retrain_job
            logger.info("🤖 RETRAIN: Starting auto-retrain check...")
            result = await auto_retrain_job()
            
            if result.get('training_triggered'):
                training_result = result.get('training_result', {})
                if training_result.get('success'):
                    logger.info(f"✅ RETRAIN: Model retrained successfully in {training_result.get('duration_seconds', 0):.0f}s")
                else:
                    logger.warning(f"⚠️ RETRAIN: Training failed - {training_result.get('error', 'unknown')}")
            else:
                triggers = result.get('triggers', {})
                logger.info(f"✅ RETRAIN: No retraining needed - match_vol={triggers.get('match_volume', {}).get('new_matches', 0)}, age={triggers.get('model_staleness', {}).get('age_days', 0)}d")
        except ImportError:
            logger.warning("⚠️ RETRAIN: auto_retrain module not found - skipping")
        except Exception as e:
            logger.error(f"❌ RETRAIN: Auto-retrain check failed - {e}", exc_info=True)

    async def _run_elo_update(self):
        """
        📊 V0: ELO Update Job
        Updates team ELO ratings from recent match results.
        Runs daily at 04:00 UTC.
        """
        try:
            from models.team_elo import TeamELOManager
            from datetime import datetime as dt, timedelta
            
            logger.info("📊 ELO: Starting daily ELO update...")
            manager = TeamELOManager()
            
            since_date = dt.utcnow() - timedelta(days=7)
            count = manager.update_elos_since(since_date)
            
            if count > 0:
                logger.info(f"✅ ELO: Updated ratings for {count} matches")
            else:
                logger.info("✅ ELO: No new matches to process")
                
            stats = manager.get_elo_stats()
            logger.info(f"📊 ELO Stats: {stats['total_teams']} teams, avg={stats['avg_elo']:.0f}")
            
        except ImportError:
            logger.warning("⚠️ ELO: team_elo module not found - skipping")
        except Exception as e:
            logger.error(f"❌ ELO: Update failed - {e}", exc_info=True)

    async def _run_sharp_book_collection(self):
        """
        🎯 V3: Sharp Book Collection
        Tracks Pinnacle and other sharp bookmaker odds separately.
        Runs every 5 minutes for V3 feature engineering.
        Also populates odds_consensus from sharp books to expand training data.
        """
        try:
            from models.sharp_book_collector import run_sharp_book_collection
            logger.info("🎯 SHARP: Starting sharp book collection...")
            results = run_sharp_book_collection()
            total_stored = sum(r.get('odds_stored', 0) for r in results.values() if isinstance(r, dict))
            logger.info(f"✅ SHARP: Collection complete - {total_stored} odds stored")
            
            from models.database import DatabaseManager
            db = DatabaseManager()
            consensus_created = db.populate_consensus_from_sharp_books()
            if consensus_created > 0:
                logger.info(f"📊 SHARP→TRAINING: Created {consensus_created} new training samples from sharp book data")
        except ImportError:
            logger.warning("⚠️ SHARP: sharp_book_collector module not found - skipping")
        except Exception as e:
            logger.error(f"❌ SHARP: Collection failed - {e}", exc_info=True)

    async def _run_multisport_odds_collection(self):
        """
        🏀🏒 Multi-Sport Odds Collection
        Collects odds for NBA, NHL, and MLB from The Odds API.
        Runs every 60 minutes (reduced from 5min to slow DB growth).
        """
        try:
            from models.multisport_collector import run_multisport_collection
            logger.info("🏀🏒 MULTISPORT: Starting odds collection...")
            results = run_multisport_collection()
            
            for sport, data in results.items():
                if isinstance(data, dict):
                    if data.get('status') == 'off_season':
                        logger.debug(f"  ⏸️ {sport}: off-season")
                    elif 'events' in data:
                        logger.info(f"  ✅ {sport}: {data.get('events', 0)} events, {data.get('odds_stored', 0)} odds")
        except ImportError:
            logger.warning("⚠️ MULTISPORT: multisport_collector module not found - skipping")
        except Exception as e:
            logger.error(f"❌ MULTISPORT: Odds collection failed - {e}", exc_info=True)

    async def _run_multisport_results_collection(self):
        """
        📊 Multi-Sport Results Collection
        Fetches completed game scores for NBA, NHL, MLB.
        Runs every hour.
        """
        try:
            from models.multisport_collector import run_multisport_results
            logger.info("📊 MULTISPORT: Fetching results...")
            results = run_multisport_results()
            total_updated = sum(r.get('results_updated', 0) for r in results.values() if isinstance(r, dict))
            if total_updated > 0:
                logger.info(f"✅ MULTISPORT: {total_updated} results updated")
        except ImportError:
            logger.warning("⚠️ MULTISPORT: multisport_collector module not found - skipping")
        except Exception as e:
            logger.error(f"❌ MULTISPORT: Results collection failed - {e}", exc_info=True)

    async def _run_multisport_data_collection(self):
        """
        🏀🏒🏈 Multi-Sport Comprehensive Data Collection
        Collects match results, team stats, standings for NBA, NHL, NFL.
        Runs every 2 hours.
        """
        try:
            from models.multisport_data_collector import run_multisport_collection
            logger.info("🏀🏒🏈 MULTISPORT-DATA: Starting comprehensive collection...")
            results = run_multisport_collection()
            
            for sport, data in results.items():
                if isinstance(data, dict):
                    if data.get('status') == 'off_season':
                        logger.debug(f"  ⏸️ {sport}: off-season")
                    elif 'error' in data:
                        logger.warning(f"  ⚠️ {sport}: {data.get('error')}")
                    else:
                        games = data.get('games', {})
                        standings = data.get('standings', {})
                        stored = games.get('stored', 0)
                        teams = standings.get('stored', 0)
                        if stored > 0 or teams > 0:
                            logger.info(f"  ✅ {sport}: {stored} games, {teams} team stats")
        except ImportError:
            logger.warning("⚠️ MULTISPORT-DATA: multisport_data_collector module not found - skipping")
        except Exception as e:
            logger.error(f"❌ MULTISPORT-DATA: Collection failed - {e}", exc_info=True)

    async def _run_api_sports_collection(self):
        """
        🏀⚾ API-Sports Data Collection
        Collects team/player data from API-Basketball and API-Baseball.
        Runs every hour for V3 features.
        """
        try:
            from models.api_sports_collector import run_api_sports_collection
            logger.info("🏀⚾ API-SPORTS: Starting data collection...")
            results = run_api_sports_collection()
            
            for sport, data in results.items():
                if isinstance(data, dict):
                    if data.get('status') == 'off_season':
                        logger.debug(f"  ⏸️ {sport}: off-season")
                    elif 'error' in data:
                        logger.warning(f"  ⚠️ {sport}: {data.get('error')}")
                    else:
                        teams = sum(d.get('teams', 0) for d in data.values() if isinstance(d, dict))
                        games = sum(d.get('games', 0) for d in data.values() if isinstance(d, dict))
                        if teams > 0 or games > 0:
                            logger.info(f"  ✅ {sport}: {teams} teams, {games} games synced")
        except ImportError:
            logger.warning("⚠️ API-SPORTS: api_sports_collector module not found - skipping")
        except Exception as e:
            logger.error(f"❌ API-SPORTS: Data collection failed - {e}", exc_info=True)

    async def _run_league_ece_calculation(self):
        """
        📊 V3: League ECE Calculator
        Calculates Expected Calibration Error per league for prediction weighting.
        Runs weekly on Sunday at 02:00 UTC.
        """
        try:
            from jobs.league_ece_calculator import run_league_ece_calculation
            logger.info("📊 ECE: Starting league calibration calculation...")
            results = run_league_ece_calculation()
            if 'error' not in results:
                logger.info(f"✅ ECE: {results.get('leagues_updated', 0)} leagues updated")
            else:
                logger.warning(f"⚠️ ECE: {results.get('error')}")
        except ImportError:
            logger.warning("⚠️ ECE: league_ece_calculator module not found - skipping")
        except Exception as e:
            logger.error(f"❌ ECE: Calculation failed - {e}", exc_info=True)

    async def _run_injury_collection(self):
        """
        🏥 V3: Injury Collection
        Collects injury/suspension data from API-Football.
        Runs every 6 hours.
        """
        try:
            from jobs.injury_collector import run_injury_collection
            logger.info("🏥 INJURY: Starting injury collection...")
            results = run_injury_collection()
            if 'error' not in results:
                logger.info(f"✅ INJURY: {results.get('injuries_stored', 0)} injuries, "
                           f"{results.get('summaries_updated', 0)} summaries")
            else:
                logger.warning(f"⚠️ INJURY: {results.get('error')}")
        except ImportError:
            logger.warning("⚠️ INJURY: injury_collector module not found - skipping")
        except Exception as e:
            logger.error(f"❌ INJURY: Collection failed - {e}", exc_info=True)

    async def _run_intl_qualifier_collection(self):
        """
        🌍 WC 2026 Prep: International Qualifier Collection
        Collects WC qualifier matches from all confederations.
        Runs daily at 04:00 UTC.
        """
        try:
            from models.international_match_collector import InternationalMatchCollector
            logger.info("🌍 INTL: Starting WC qualifier collection...")
            
            collector = InternationalMatchCollector()
            results = collector.collect_current_qualifiers()
            
            total_matches = sum(r.get('matches', 0) for r in results.values())
            total_inserted = sum(r.get('inserted', 0) for r in results.values())
            
            if total_inserted > 0:
                logger.info(f"✅ INTL: {total_matches} matches collected, {total_inserted} new")
            else:
                logger.info(f"✅ INTL: {total_matches} matches checked, no new data")
                
        except ImportError:
            logger.warning("⚠️ INTL: international_match_collector module not found - skipping")
        except Exception as e:
            logger.error(f"❌ INTL: Qualifier collection failed - {e}", exc_info=True)

    async def _run_player_stats_collection(self):
        """
        ⚽🏀🏒 Multi-Sport Player Stats Collection
        Collects player statistics from ALL leagues in league_map plus NBA/NHL.
        Runs daily at 05:00 UTC.
        """
        try:
            from models.multisport_player_collector import MultiSportPlayerCollector
            import psycopg2
            
            logger.info("⚽🏀🏒 PLAYER STATS: Starting comprehensive daily collection...")
            
            collector = MultiSportPlayerCollector()
            total_players = 0
            leagues_processed = 0
            
            database_url = os.environ.get('DATABASE_URL')
            if not database_url:
                logger.error("❌ PLAYER STATS: DATABASE_URL not set")
                return
            
            with psycopg2.connect(database_url, connect_timeout=10) as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT DISTINCT league_id, league_name 
                        FROM league_map 
                        WHERE theodds_sport_key LIKE 'soccer_%'
                        ORDER BY league_id
                    """)
                    soccer_leagues = cur.fetchall()
            
            priority_leagues = {39, 140, 135, 78, 61, 2, 3}
            
            for league_id, league_name in soccer_leagues:
                try:
                    if league_id in priority_leagues or leagues_processed < 20:
                        result = collector.collect_soccer_player_stats(league_id, 2024)
                        players = result.get('players', 0)
                        total_players += players
                        leagues_processed += 1
                        if players > 0:
                            logger.info(f"✅ PLAYER STATS: {league_name} ({league_id}) - {players} players")
                        time.sleep(0.5)
                except Exception as e:
                    logger.warning(f"⚠️ PLAYER STATS: {league_name} ({league_id}) failed - {e}")
            
            try:
                logger.info("🏀 PLAYER STATS: Collecting NBA data...")
                nba_result = collector.collect_nba_player_stats(league_id=12, season="2024-2025")
                nba_players = nba_result.get('players', 0)
                total_players += nba_players
                logger.info(f"✅ PLAYER STATS: NBA - {nba_players} players")
            except Exception as e:
                logger.warning(f"⚠️ PLAYER STATS: NBA collection failed - {e}")
            
            try:
                logger.info("🏒 PLAYER STATS: Collecting NHL data...")
                nhl_result = collector.collect_nhl_player_stats(league_id=57, season=2024)
                nhl_players = nhl_result.get('players', 0)
                total_players += nhl_players
                logger.info(f"✅ PLAYER STATS: NHL - {nhl_players} players")
            except Exception as e:
                logger.warning(f"⚠️ PLAYER STATS: NHL collection failed - {e}")
            
            logger.info(f"✅ PLAYER STATS: Collection complete - {total_players} players from {leagues_processed} soccer leagues + NBA + NHL")
            
            try:
                logger.info("📊 GAME STATS: Collecting player game-by-game stats from recent fixtures...")
                game_result = collector.collect_soccer_game_stats_batch(days_back=7, limit=50)
                games_collected = game_result.get('fixtures_processed', 0)
                players_collected = game_result.get('players_collected', 0)
                logger.info(f"✅ GAME STATS: {players_collected} player stats from {games_collected} fixtures")
            except Exception as e:
                logger.warning(f"⚠️ GAME STATS: Game-by-game collection failed - {e}")
            
            try:
                logger.info("🎰 PARLAY STATS: Collecting player stats for pending player parlays...")
                parlay_result = collector.collect_stats_for_pending_player_parlays(limit=50)
                parlay_fixtures = parlay_result.get('fixtures_processed', 0)
                parlay_players = parlay_result.get('players_collected', 0)
                logger.info(f"✅ PARLAY STATS: {parlay_players} player stats from {parlay_fixtures} parlay fixtures")
            except Exception as e:
                logger.warning(f"⚠️ PARLAY STATS: Collection failed - {e}")
            
        except ImportError:
            logger.warning("⚠️ PLAYER STATS: multisport_player_collector module not found - skipping")
        except Exception as e:
            logger.error(f"❌ PLAYER STATS: Collection failed - {e}", exc_info=True)

    async def _run_player_prop_odds_collection(self):
        """
        🎰 Player Prop Odds Collection Job
        Collects player prop odds from The Odds API for NBA/NHL.
        Runs every 2 hours.
        """
        try:
            from models.player_prop_odds_collector import collect_player_props_job
            logger.info("🎰 PLAYER PROPS: Starting odds collection for NBA/NHL...")
            result = collect_player_props_job()
            
            if result.get('success'):
                metrics = result.get('metrics', {})
                logger.info(f"✅ PLAYER PROPS: Collected {metrics.get('props_collected', 0)} props from {metrics.get('events_processed', 0)} events")
            else:
                logger.warning(f"⚠️ PLAYER PROPS: Collection had issues - {result.get('error', 'unknown')}")
                
        except ImportError:
            logger.debug("⚠️ PLAYER PROPS: player_prop_odds_collector module not ready - skipping")
        except Exception as e:
            logger.error(f"❌ PLAYER PROPS: Collection failed - {e}", exc_info=True)

    async def _run_soccer_scorer_odds_collection(self):
        """
        ⚽ Soccer Scorer Odds Collection Job
        Collects anytime goalscorer odds from The Odds API for EPL, La Liga, Serie A, Bundesliga, Ligue 1, MLS.
        Runs every 4 hours.
        """
        try:
            from models.soccer_scorer_odds import SoccerScorerOddsCollector
            logger.info("⚽ SOCCER SCORER ODDS: Starting collection for all supported leagues...")
            collector = SoccerScorerOddsCollector()
            result = await asyncio.get_event_loop().run_in_executor(None, collector.collect_all_soccer_scorer_odds)

            total_odds = result.get('total_odds_collected', 0)
            total_events = result.get('total_events_processed', 0)
            total_matched = result.get('total_events_matched', 0)
            logger.info(
                f"✅ SOCCER SCORER ODDS: {total_odds} odds collected from "
                f"{total_events} events ({total_matched} matched) across {len(result.get('leagues', {}))} leagues"
            )

        except ImportError:
            logger.debug("⚠️ SOCCER SCORER ODDS: soccer_scorer_odds module not ready - skipping")
        except Exception as e:
            logger.error(f"❌ SOCCER SCORER ODDS: Collection failed - {e}", exc_info=True)


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