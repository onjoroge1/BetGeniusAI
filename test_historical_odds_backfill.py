#!/usr/bin/env python3
"""Test API-Football historical odds backfill for existing training matches"""

import os
import requests
import psycopg2
from datetime import datetime

RAPIDAPI_KEY = os.environ.get('RAPIDAPI_KEY')
BASE_URL = "https://api-football-v1.p.rapidapi.com/v3"
HEADERS = {
    "X-RapidAPI-Key": RAPIDAPI_KEY,
    "X-RapidAPI-Host": "api-football-v1.p.rapidapi.com"
}
DATABASE_URL = os.environ.get('DATABASE_URL')

def get_sample_matches_without_odds():
    """Get sample matches from training_matches that don't have odds"""
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    
    # Get 5 recent matches without odds from different leagues
    cursor.execute("""
        SELECT DISTINCT ON (tm.league_id)
            tm.match_id,
            tm.league_id,
            lm.league_name,
            tm.home_team,
            tm.away_team,
            tm.match_date,
            tm.season
        FROM training_matches tm
        LEFT JOIN odds_snapshots os ON tm.match_id = os.match_id
        LEFT JOIN league_map lm ON tm.league_id = lm.league_id
        WHERE os.match_id IS NULL
        ORDER BY tm.league_id, tm.match_date DESC
        LIMIT 5
    """)
    
    matches = cursor.fetchall()
    cursor.close()
    conn.close()
    
    return matches

def test_odds_for_match(match_id, home_team, away_team, league_name):
    """Test fetching odds for a specific match"""
    print(f"\n📊 Testing: {home_team} vs {away_team} ({league_name})")
    print(f"   Match ID: {match_id}")
    
    # Try to get odds for this fixture
    odds_url = f"{BASE_URL}/odds"
    params = {"fixture": str(match_id)}
    
    try:
        response = requests.get(odds_url, headers=HEADERS, params=params, timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            odds_list = data.get('response', [])
            
            if odds_list:
                bookmakers = odds_list[0].get('bookmakers', [])
                print(f"   ✅ Found odds from {len(bookmakers)} bookmakers")
                
                # Show sample bookmaker
                if bookmakers:
                    sample = bookmakers[0]
                    bets = sample.get('bets', [])
                    match_winner = next((b for b in bets if b['name'] == 'Match Winner'), None)
                    
                    if match_winner:
                        print(f"   Sample ({sample['name']}):")
                        for v in match_winner['values']:
                            print(f"      {v['value']}: {v['odd']}")
                
                return True
            else:
                print(f"   ⚠️  No odds data available")
                return False
        else:
            print(f"   ❌ Request failed: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False

def main():
    print("🔍 TESTING HISTORICAL ODDS BACKFILL")
    print("=" * 70)
    print("\nFetching sample matches without odds from database...")
    
    matches = get_sample_matches_without_odds()
    
    if not matches:
        print("❌ No matches found without odds")
        return
    
    print(f"✅ Found {len(matches)} sample matches to test\n")
    print("=" * 70)
    
    success_count = 0
    
    for match_id, league_id, league_name, home, away, match_date, season in matches:
        success = test_odds_for_match(match_id, home, away, league_name or f"League {league_id}")
        if success:
            success_count += 1
    
    print("\n" + "=" * 70)
    print(f"\n📊 RESULTS:")
    print(f"   Tested: {len(matches)} matches")
    print(f"   With odds available: {success_count}")
    print(f"   Success rate: {success_count/len(matches)*100:.1f}%")
    
    if success_count > 0:
        print("\n✅ API-Football can backfill historical odds!")
        print(f"✅ Recommended: Backfill all {9586} matches without odds")
    else:
        print("\n⚠️  Historical odds may not be available in free tier")
        print("   Consider: Test with different match IDs or date ranges")

if __name__ == "__main__":
    main()
