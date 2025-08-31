#!/usr/bin/env python3
"""
Quick Auto-Retraining Trigger
Simulates the automatic retraining that happens after collection cycles
"""

import sys
from datetime import datetime

def trigger_auto_retrain():
    """Trigger auto-retraining as it would happen after collection"""
    
    print("🔄 BetGenius AI - Auto-Retraining Trigger")
    print("=" * 40)
    
    try:
        from models.automated_collector import AutomatedDataCollector
        
        print("📊 Initializing automated collector...")
        collector = AutomatedDataCollector()
        
        print(f"⚡ Triggering auto-retraining with threshold: 10 matches")
        print(f"⏱️  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Use async function properly
        import asyncio
        
        async def run_retrain():
            success = await collector.auto_retrain_if_needed(min_new_matches=10)
            return success
            
        success = asyncio.run(run_retrain())
        
        if success:
            print("✅ Auto-retraining completed successfully!")
            print("🎯 Models have been updated with latest training data")
        else:
            print("ℹ️  Auto-retraining skipped - insufficient new data or already trained")
            
        return success
        
    except Exception as e:
        print(f"❌ Auto-retraining failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = trigger_auto_retrain()
    sys.exit(0 if success else 1)