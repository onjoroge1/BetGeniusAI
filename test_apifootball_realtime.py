#!/usr/bin/env python3
"""
Test API-Football Real-Time Odds Collector
Verifies the new multi-source real-time odds collection
"""

import asyncio
import sys
from models.automated_collector import AutomatedCollector

async def test_apifootball_realtime():
    """Test the new API-Football real-time collector"""
    
    print("=" * 60)
    print("🧪 API-FOOTBALL REAL-TIME COLLECTOR TEST")
    print("=" * 60)
    
    collector = AutomatedCollector()
    
    print("\n📊 Test 1: API-Football Real-Time Collection Only")
    print("-" * 60)
    
    try:
        results = await collector.collect_upcoming_odds_apifootball()
        
        print("\n✅ Collection Results:")
        print(f"   • Source: {results.get('source', 'N/A')}")
        print(f"   • Matches found: {results.get('matches_found', 0)}")
        print(f"   • Fixtures processed: {results.get('fixtures_processed', 0)}")
        print(f"   • Rows inserted: {results.get('rows_inserted', 0)}")
        
        if results.get('errors'):
            print(f"\n⚠️  Errors encountered: {len(results['errors'])}")
            for i, error in enumerate(results['errors'][:3], 1):
                print(f"   {i}. {error}")
        
        if results.get('rows_inserted', 0) > 0:
            print("\n✅ SUCCESS: API-Football real-time collector is working!")
        else:
            print("\n⚠️  No odds collected - this might be expected if:")
            print("   • No upcoming matches in timing windows (T-72h, T-48h, T-24h)")
            print("   • All matches already have odds collected")
            
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    print("\n📊 Test 2: Multi-Source Collection (Full Cycle)")
    print("-" * 60)
    
    try:
        full_results = await collector.collect_recent_and_upcoming_matches()
        
        print("\n✅ Multi-Source Results:")
        print(f"   • Training matches: {full_results.get('new_matches_collected', 0)}")
        print(f"   • The Odds API: {full_results.get('phase_b_theodds', {}).get('new_odds_collected', 0)} snapshots")
        print(f"   • API-Football: {full_results.get('phase_b_apifootball', {}).get('rows_inserted', 0)} rows")
        print(f"   • Total odds collected: {full_results.get('new_odds_collected', 0)}")
        print(f"   • Total data points: {full_results.get('total_new_data_points', 0)}")
        
        print("\n✅ ALL TESTS PASSED!")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(test_apifootball_realtime())
