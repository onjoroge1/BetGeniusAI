"""
BetGenius AI Backend - Task Scheduler
Background scheduler for automated data collection and model updates
"""

import asyncio
import logging
from datetime import datetime, time
from typing import Optional
import threading
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
    
    async def _scheduler_loop(self):
        """Scheduler loop that runs daily collection"""
        last_collection_date = None
        
        while self.is_running:
            try:
                now = datetime.utcnow()
                today = now.date()
                current_time = now.time()
                
                # Check if it's time for daily collection
                if (last_collection_date != today and 
                    current_time >= self.collection_time):
                    
                    logger.info("Starting scheduled daily collection cycle")
                    
                    try:
                        results = await self.collector.daily_collection_cycle()
                        
                        if results.get("new_matches_collected", 0) > 0:
                            logger.info(f"Scheduled collection completed: {results['new_matches_collected']} new matches")
                        else:
                            logger.info("Scheduled collection completed: no new matches found")
                        
                        last_collection_date = today
                        
                    except Exception as e:
                        logger.error(f"Scheduled collection failed: {e}")
                
                # Sleep for 1 hour before checking again
                await asyncio.sleep(3600)
                
            except Exception as e:
                logger.error(f"Scheduler loop error: {e}")
                await asyncio.sleep(300)  # Wait 5 minutes before retry
    
    def trigger_immediate_collection(self):
        """Trigger immediate collection cycle (non-blocking)"""
        if not self.is_running:
            logger.warning("Scheduler not running, cannot trigger immediate collection")
            return False
        
        # Run collection in background
        threading.Thread(
            target=self._run_immediate_collection,
            daemon=True
        ).start()
        
        logger.info("Immediate collection cycle triggered")
        return True
    
    def _run_immediate_collection(self):
        """Run immediate collection in separate thread"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            results = loop.run_until_complete(self.collector.daily_collection_cycle())
            logger.info(f"Immediate collection completed: {results.get('new_matches_collected', 0)} new matches")
        except Exception as e:
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

def stop_background_scheduler():
    """Stop the background scheduler"""
    scheduler = get_scheduler()
    scheduler.stop_scheduler()