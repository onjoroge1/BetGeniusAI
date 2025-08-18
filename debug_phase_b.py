#!/usr/bin/env python3

import asyncio
import os
import sys
sys.path.append('.')

from models.automated_collector import AutomatedCollector

async def debug_phase_b():
    """Debug why Phase B (upcoming odds collection) isn't working"""
    print("🔍 Debug Phase B: Upcoming Odds Collection")
    print("=" * 50)
    
    collector = AutomatedCollector()
    
    print("\n1️⃣ Testing odds collection for specific match...")
    
    # Test with one specific match
    test_match = {
        'match_id': 1378978,  # Leeds vs Everton
        'home_team': 'Leeds',
        'away_team': 'Everton',
        'date': '2025-08-18T19:00:00+00:00'
    }
    
    league_id = 39  # Premier League
    timing_window = 3  # T-3h window (close to actual 2.9h)
    
    print(f"   Match: {test_match['home_team']} vs {test_match['away_team']}")
    print(f"   Timing: T-{timing_window}h window")
    
    # Call the specific odds collection method
    try:
        result = await collector._collect_and_save_odds(test_match, league_id, timing_window)
        print(f"   Result: {result}")
    except Exception as e:
        print(f"   Error: {e}")
    
    print("\n2️⃣ Checking database for any recent odds...")
    
    import psycopg2
    database_url = os.environ.get('DATABASE_URL')
    
    try:
        with psycopg2.connect(database_url) as conn:
            cursor = conn.cursor()
            
            # Check total odds count
            cursor.execute("SELECT COUNT(*) FROM odds_snapshots")
            total_odds = cursor.fetchone()[0]
            print(f"   Total odds in database: {total_odds}")
            
            # Check recent odds
            cursor.execute("""
                SELECT match_id, book_id, outcome, odds_decimal, created_at 
                FROM odds_snapshots 
                WHERE created_at > NOW() - INTERVAL '10 minutes'
                ORDER BY created_at DESC 
                LIMIT 5
            """)
            recent_odds = cursor.fetchall()
            
            if recent_odds:
                print(f"   Recent odds ({len(recent_odds)}):")
                for odds in recent_odds:
                    print(f"     Match {odds[0]}: {odds[1]} - {odds[2]} = {odds[3]} at {odds[4]}")
            else:
                print("   No recent odds found")
                
    except Exception as db_error:
        print(f"   Database error: {db_error}")

if __name__ == "__main__":
    asyncio.run(debug_phase_b())