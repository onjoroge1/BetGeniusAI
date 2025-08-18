#!/usr/bin/env python3
"""
Fix scheduler timing issue - should only run at 02:00 UTC, not immediately
"""

import os
from datetime import datetime, time, date

def diagnose_scheduler_issue():
    """Diagnose the scheduler timing issue"""
    
    print("🔍 SCHEDULER TIMING DIAGNOSIS")
    print("=" * 40)
    
    now = datetime.utcnow()
    today = now.date()
    current_time = now.time()
    collection_time = time(hour=2, minute=0)  # 02:00 UTC
    
    print(f"📅 Current Date: {today}")
    print(f"⏰ Current Time: {current_time.strftime('%H:%M:%S')} UTC")
    print(f"🎯 Target Time: {collection_time.strftime('%H:%M:%S')} UTC")
    
    # Check collection log
    try:
        import json
        with open('data/collection_log.json', 'r') as f:
            log_data = json.load(f)
        
        if log_data and len(log_data) > 0:
            latest = log_data[-1]
            timestamp_str = latest.get('timestamp', '')
            if timestamp_str:
                timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                last_collection_date = timestamp.date()
                print(f"📋 Last Collection: {last_collection_date}")
                print(f"📊 Matches Collected: {latest.get('new_matches_collected', 0)}")
    except Exception as e:
        print(f"⚠️ Collection log error: {e}")
        last_collection_date = None
    
    # Analyze the issue
    print(f"\n🧪 ISSUE ANALYSIS:")
    
    should_run_logic = current_time >= collection_time and last_collection_date != today
    print(f"   • current_time >= collection_time: {current_time >= collection_time}")
    print(f"   • last_collection_date != today: {last_collection_date != today}")
    print(f"   • Scheduler should run: {should_run_logic}")
    
    print(f"\n❌ PROBLEM IDENTIFIED:")
    print(f"   • Scheduler runs whenever current_time >= 02:00 UTC")
    print(f"   • At 14:10 UTC, this condition is TRUE")
    print(f"   • Should only run ONCE per day at 02:00 UTC, not throughout the day")
    
    print(f"\n✅ SOLUTION:")
    print(f"   • Change logic to run only within 02:00-02:30 UTC window")
    print(f"   • Or track if collection already attempted today")
    print(f"   • Prevent multiple runs per day")

def create_fixed_scheduler():
    """Create the corrected scheduler logic"""
    
    scheduler_fix = '''
    async def _scheduler_loop(self):
        """Scheduler loop that runs daily collection ONLY at 02:00 UTC"""
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
                        
                        logger.info(f"✅ Scheduled collection completed: {results.get('new_matches_collected', 0)} new matches")
                        
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
                await asyncio.sleep(300)
    '''
    
    print("🔧 FIXED SCHEDULER LOGIC:")
    print(scheduler_fix)

if __name__ == "__main__":
    diagnose_scheduler_issue()
    create_fixed_scheduler()