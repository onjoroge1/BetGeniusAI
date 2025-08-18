#!/usr/bin/env python3
"""
Test to check if we're in season or offseason for major European leagues
"""
import os
import asyncio
import aiohttp
from datetime import datetime, timedelta

async def check_league_season_status():
    """Check if major leagues have upcoming matches"""
    rapid_api_key = os.environ.get('RAPIDAPI_KEY')
    if not rapid_api_key:
        print("❌ RAPIDAPI_KEY not found")
        return

    leagues = {
        39: "Premier League",
        140: "La Liga", 
        135: "Serie A",
        78: "Bundesliga",
        61: "Ligue 1",
        88: "Eredivisie"
    }
    
    print("🏟️ Checking Season Status for Major European Leagues")
    print("=" * 60)
    
    current_date = datetime.utcnow()
    # Check next 30 days for any upcoming matches
    end_date = current_date + timedelta(days=30)
    
    for league_id, league_name in leagues.items():
        print(f"\n🔍 {league_name} (ID: {league_id})")
        
        url = "https://api-football-v1.p.rapidapi.com/v3/fixtures"
        headers = {
            'X-RapidAPI-Key': rapid_api_key,
            'X-RapidAPI-Host': 'api-football-v1.p.rapidapi.com'
        }
        
        params = {
            'league': league_id,
            'season': 2024,
            'status': 'NS',  # Not Started
            'from': current_date.strftime('%Y-%m-%d'),
            'to': end_date.strftime('%Y-%m-%d')
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        fixtures = data.get('response', [])
                        print(f"  📅 Upcoming fixtures in next 30 days: {len(fixtures)}")
                        
                        if fixtures:
                            # Show next match
                            next_match = fixtures[0]
                            home_team = next_match['teams']['home']['name']
                            away_team = next_match['teams']['away']['name']
                            match_date = next_match['fixture']['date']
                            print(f"  🏆 Next match: {home_team} vs {away_team}")
                            print(f"  📅 Date: {match_date}")
                        else:
                            print(f"  😴 No upcoming matches - likely offseason/break")
                            
                    else:
                        print(f"  ❌ API Error: Status {response.status}")
                        
        except Exception as e:
            print(f"  ❌ Exception: {e}")
        
        # Small delay between requests
        await asyncio.sleep(1)
    
    print(f"\n📊 Analysis complete for {len(leagues)} leagues")

if __name__ == "__main__":
    asyncio.run(check_league_season_status())