#!/usr/bin/env python3

import asyncio
import aiohttp
import os
from datetime import datetime

async def debug_odds_collection():
    """Debug why odds collection isn't working"""
    print("🔍 Debug: Odds Collection Issue")
    print("=" * 50)
    
    # Test 1: Check one upcoming match timing
    print("\n1️⃣ Getting one upcoming match for timing analysis...")
    headers = {'Authorization': 'Bearer betgenius_secure_key_2024'}
    
    async with aiohttp.ClientSession() as session:
        # Get one upcoming Premier League match
        async with session.get('http://localhost:8000/matches/upcoming?league_id=39&limit=1', headers=headers) as response:
            if response.status == 200:
                data = await response.json()
                matches = data.get('matches', [])
                
                if matches:
                    match = matches[0]
                    print(f"   Match: {match['home_team']} vs {match['away_team']}")
                    print(f"   Date: {match['date']}")
                    print(f"   Match ID: {match['match_id']}")
                    
                    # Calculate timing
                    match_date = datetime.fromisoformat(match['date'].replace('Z', '+00:00')).replace(tzinfo=None)
                    current_time = datetime.utcnow()
                    hours_until = (match_date - current_time).total_seconds() / 3600
                    
                    print(f"   Hours until match: {hours_until:.1f}")
                    print(f"   In collection window (24h-168h)? {24 <= hours_until <= 168}")
                    
                    # Test 2: Check The Odds API for this exact match
                    print(f"\n2️⃣ Checking The Odds API for Premier League matches...")
                    
                    api_key = os.environ.get('ODDS_API_KEY')
                    odds_url = "https://api.the-odds-api.com/v4/sports/soccer_epl/odds"
                    odds_params = {
                        'apiKey': api_key,
                        'regions': 'eu',
                        'markets': 'h2h',
                        'oddsFormat': 'decimal'
                    }
                    
                    async with session.get(odds_url, params=odds_params) as odds_response:
                        if odds_response.status == 200:
                            odds_data = await odds_response.json()
                            print(f"   Found {len(odds_data)} events in The Odds API")
                            
                            # Look for our match
                            for event in odds_data:
                                home_team = event.get('home_team', '')
                                away_team = event.get('away_team', '')
                                
                                if (match['home_team'].lower() in home_team.lower() or
                                    match['away_team'].lower() in away_team.lower()):
                                    print(f"   ✅ MATCH FOUND: {home_team} vs {away_team}")
                                    print(f"   Commence: {event.get('commence_time')}")
                                    print(f"   Bookmakers: {len(event.get('bookmakers', []))}")
                                    
                                    if event.get('bookmakers'):
                                        bookmaker = event['bookmakers'][0]
                                        print(f"   Example bookmaker: {bookmaker.get('title')}")
                                        if bookmaker.get('markets'):
                                            market = bookmaker['markets'][0]
                                            outcomes = [f"{o['name']}:{o['price']}" for o in market.get('outcomes', [])]
                                        print(f"   Example odds: {outcomes}")
                                    return
                            
                            print(f"   ⚠️ Our match not found in The Odds API results")
                            print(f"   First few events:")
                            for i, event in enumerate(odds_data[:3]):
                                print(f"     {i+1}. {event.get('home_team')} vs {event.get('away_team')}")
                                
                        else:
                            print(f"   ❌ Odds API error: {odds_response.status}")
                            
                else:
                    print("   No upcoming matches found")
            else:
                print(f"   ❌ Internal API error: {response.status}")

if __name__ == "__main__":
    asyncio.run(debug_odds_collection())