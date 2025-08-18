#!/usr/bin/env python3

import asyncio
import os
import sys
import aiohttp
from datetime import datetime, timedelta

# Test complete upcoming matches flow
async def test_upcoming_flow():
    print("🚀 Testing Complete Upcoming Matches Flow")
    print("=" * 50)
    
    # Step 1: Test internal upcoming matches API
    print("\n1️⃣ Testing internal upcoming matches API...")
    try:
        async with aiohttp.ClientSession() as session:
            url = "http://localhost:8000/admin/internal-upcoming/39"  # Premier League
            headers = {"Authorization": "Bearer betgenius_secure_key_2024"}
            
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    upcoming = data.get('upcoming_matches', [])
                    print(f"   ✅ Found {len(upcoming)} upcoming matches")
                    
                    for i, match in enumerate(upcoming[:3]):  # Show first 3
                        print(f"   Match {i+1}: {match['home_team']} vs {match['away_team']}")
                        print(f"            Date: {match['date']}")
                        print(f"            ID: {match['match_id']}")
                else:
                    print(f"   ❌ API returned {response.status}")
                    
    except Exception as e:
        print(f"   ❌ Error: {e}")
    
    # Step 2: Test The Odds API directly for one match
    print("\n2️⃣ Testing The Odds API for Premier League...")
    api_key = os.environ.get('ODDS_API_KEY')
    if not api_key:
        print("   ❌ No ODDS_API_KEY found")
        return
    
    try:
        async with aiohttp.ClientSession() as session:
            url = "https://api.the-odds-api.com/v4/sports/soccer_epl/odds"
            params = {
                'apiKey': api_key,
                'regions': 'eu',
                'markets': 'h2h',
                'oddsFormat': 'decimal',
                'dateFormat': 'iso'
            }
            
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    print(f"   ✅ The Odds API working! Found {len(data)} events")
                    
                    # Show first event
                    if data:
                        event = data[0]
                        print(f"   First event: {event.get('home_team')} vs {event.get('away_team')}")
                        print(f"   Commence: {event.get('commence_time')}")
                        print(f"   Bookmakers: {len(event.get('bookmakers', []))}")
                else:
                    print(f"   ❌ The Odds API error: {response.status}")
                    error_text = await response.text()
                    print(f"   Error: {error_text}")
                    
    except Exception as e:
        print(f"   ❌ Exception: {e}")
    
    # Step 3: Test manual collection trigger
    print("\n3️⃣ Testing manual collection trigger...")
    try:
        async with aiohttp.ClientSession() as session:
            url = "http://localhost:8000/admin/trigger-collection"
            headers = {"Authorization": "Bearer betgenius_secure_key_2024"}
            
            async with session.post(url, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    print(f"   ✅ Collection triggered: {data['status']}")
                else:
                    print(f"   ❌ Trigger failed: {response.status}")
                    
    except Exception as e:
        print(f"   ❌ Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_upcoming_flow())