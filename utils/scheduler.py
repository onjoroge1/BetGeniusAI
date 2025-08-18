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
from models.automated_collector import AutomatedCollector

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
        self.collection_time = time(hour=2, minute=0)  # 2 AM UTC daily
        
    def start_scheduler(self):
        """Start the background scheduler"""
        if self.is_running:
            logger.warning("Scheduler already running")
            return
        
        self.is_running = True
        self.scheduler_thread = threading.Thread(target=self._run_scheduler, daemon=True)
        self.scheduler_thread.start()
        logger.info("Background scheduler started - daily collection at 02:00 UTC")
    
    def stop_scheduler(self):
        """Stop the background scheduler"""
        self.is_running = False
        if self.scheduler_thread:
            self.scheduler_thread.join(timeout=5)
        logger.info("Background scheduler stopped")
    
    def _run_scheduler(self):
        """Main scheduler loop"""
        asyncio.set_event_loop(asyncio.new_event_loop())
        loop = asyncio.get_event_loop()
        
        try:
            loop.run_until_complete(self._scheduler_loop())
        except Exception as e:
            logger.error(f"Scheduler loop failed: {e}")
        finally:
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
    
    async def _scheduler_loop(self):
        """Scheduler loop that runs daily collection"""
        last_collection_date = self._get_last_collection_date()
        
        while self.is_running:
            try:
                now = datetime.utcnow()
                today = now.date()
                current_time = now.time()
                
                # Define the collection window: 02:00-02:30 UTC
                collection_start = time(hour=2, minute=0)
                collection_end = time(hour=2, minute=30)
                
                # Only run if:
                # 1. We're in the 02:00-02:30 UTC window
                # 2. We haven't collected today yet
                if (collection_start <= current_time <= collection_end and 
                    last_collection_date != today):
                    
                    logger.info(f"🔄 SCHEDULER: Starting daily collection cycle at {current_time.strftime('%H:%M:%S')} UTC")
                    logger.info(f"📅 Target date: {today}, Last collection: {last_collection_date}")
                    
                    try:
                        results = await self.collector.daily_collection_cycle()
                        last_collection_date = today
                        
                        logger.info(f"✅ Scheduled collection completed: {results.get('new_matches_collected', 0)} new matches added to database")
                        logger.info(f"💾 Total matches in DB: {results.get('total_matches_in_db', 'unknown')}")
                        
                    except Exception as e:
                        logger.error(f"❌ Scheduled collection failed: {e}")
                
                elif last_collection_date == today:
                    # Already collected today
                    logger.debug(f"📋 Collection already completed today ({today})")
                    
                elif current_time < collection_start:
                    # Before collection window
                    time_until = (datetime.combine(today, collection_start) - datetime.combine(today, current_time)).total_seconds()
                    logger.debug(f"⏰ Waiting for collection window (current: {current_time.strftime('%H:%M')} UTC, {time_until/3600:.1f}h remaining)")
                
                else:
                    # After collection window, wait for next day
                    logger.debug(f"⏳ Collection window passed, waiting for tomorrow")
                
                # Sleep for 30 minutes before next check
                await asyncio.sleep(1800)
                
            except Exception as e:
                logger.error(f"Scheduler loop error: {e}")
                await asyncio.sleep(300)  # Wait 5 minutes before retry
    
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
        except Exception as e:
            if force:
                logger.error(f"🔧 MANUAL collection failed: {e}")
            else:
                logger.error(f"Immediate collection failed: {e}")
        finally:
            loop.close()

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