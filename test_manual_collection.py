#!/usr/bin/env python3
"""
Manual Collection Test - Trigger scheduler manually for testing
"""

import sys
import os
import time
import asyncio

# Add the root directory to Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_manual_trigger():
    """Test manual scheduler trigger"""
    
    print("🔧 MANUAL SCHEDULER TEST")
    print("=" * 40)
    
    try:
        # Import after setting path
        from utils.scheduler import trigger_manual_collection, get_scheduler
        
        print("📋 Testing manual collection trigger...")
        
        # Get scheduler instance
        scheduler = get_scheduler()
        print(f"   • Scheduler running: {scheduler.is_running}")
        
        if not scheduler.is_running:
            print("   ⚠️ Scheduler not running - starting it first...")
            from utils.scheduler import start_background_scheduler
            start_background_scheduler()
            time.sleep(2)  # Give it time to start
        
        print("   🔧 Triggering MANUAL collection (bypasses timing restrictions)...")
        
        # Trigger manual collection
        success = trigger_manual_collection()
        
        if success:
            print("   ✅ Manual collection triggered successfully")
            print("   📊 Check the logs above for collection results")
            print("   ⏰ This collection runs OUTSIDE the normal 02:00-02:30 UTC window")
        else:
            print("   ❌ Failed to trigger manual collection")
        
        # Wait a moment for the collection to start
        print("   ⏳ Waiting 10 seconds for collection to begin...")
        time.sleep(10)
        
        print("✅ Manual trigger test completed")
        
    except ImportError as e:
        print(f"❌ Import error: {e}")
        print("   💡 Run this from the main application context or with server running")
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    test_manual_trigger()