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
        # Enhanced scheduling for odds nuance capture
        # Weekdays: every 6 hours (02:00, 08:00, 14:00, 20:00 UTC)
        # Weekends: every 3 hours for better coverage
        self.weekday_hours = [2, 8, 14, 20]  # Every 6 hours
        self.weekend_hours = [2, 5, 8, 11, 14, 17, 20, 23]  # Every 3 hours
        
    def start_scheduler(self):
        """Start the background scheduler"""
        if self.is_running:
            logger.warning("Scheduler already running")
            return
        
        self.is_running = True
        self.scheduler_thread = threading.Thread(target=self._run_scheduler, daemon=True)
        self.scheduler_thread.start()
        logger.info("Background scheduler started - enhanced schedule: 6h weekdays, 3h weekends")
    
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
        """Enhanced scheduler loop for frequent odds collection"""
        logger.info("🚀 Enhanced scheduler started - capturing odds nuances with frequent collection")
        
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
                    
                    # Check if we already collected at this hour today
                    last_collection = self._get_last_collection_timestamp(current_hour)
                    
                    if not last_collection or (now - last_collection).total_seconds() > 3600:
                        day_type = "weekend" if is_weekend else "weekday"
                        logger.info(f"🔄 SCHEDULER: Starting {day_type} collection cycle at {now.strftime('%H:%M:%S')} UTC")
                        logger.info(f"📅 Hour {current_hour:02d}:00 - capturing odds nuances for market efficiency")
                        
                        try:
                            results = await self.collector.daily_collection_cycle()
                            
                            logger.info(f"✅ Enhanced collection completed: {results.get('new_matches_collected', 0)} new matches")
                            logger.info(f"📊 Fresh odds snapshots: {results.get('new_odds_collected', 0)}")
                            logger.info(f"💾 Total matches in DB: {results.get('total_matches_in_db', 'unknown')}")
                            
                        except Exception as e:
                            logger.error(f"❌ Enhanced collection failed at {current_hour:02d}:00: {e}")
                    
                    else:
                        logger.debug(f"📋 Collection already completed at {current_hour:02d}:00 today")
                
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
                
                # Check every 10 minutes for more responsive scheduling
                await asyncio.sleep(600)
                
                # Every 15 minutes, run safety net to fill missing buckets
                if now.minute % 15 == 0:
                    await self._run_safety_net()
                    
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