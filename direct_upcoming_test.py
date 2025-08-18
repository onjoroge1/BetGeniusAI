#!/usr/bin/env python3

import asyncio
import sys
import os
sys.path.append('.')

from models.automated_collector import AutomatedCollector

async def test_direct_upcoming():
    """Test upcoming collection directly"""
    print("🔄 Testing Direct Upcoming Matches Collection")
    print("=" * 50)
    
    collector = AutomatedCollector()
    
    # Test direct upcoming collection
    print("\n1️⃣ Testing upcoming odds snapshots collection...")
    try:
        results = await collector.collect_upcoming_odds_snapshots()
        print(f"📊 Results: {results}")
        
        if results.get('new_odds_collected', 0) > 0:
            print(f"✅ Successfully collected {results['new_odds_collected']} odds snapshots")
        else:
            print("⚠️ No odds collected - checking why...")
            print(f"Upcoming matches found: {results.get('upcoming_matches_found', 0)}")
            print(f"Leagues processed: {len(results.get('leagues_processed', []))}")
            
        if results.get('errors'):
            print(f"❌ Errors: {results['errors']}")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_direct_upcoming())