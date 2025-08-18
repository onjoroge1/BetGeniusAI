#!/usr/bin/env python3
"""
Direct test of upcoming matches collection system
Tests the RapidAPI and Odds API integration
"""
import os
import asyncio
import aiohttp
from datetime import datetime, timedelta

async def test_rapidapi_upcoming():
    """Test RapidAPI for upcoming matches"""
    rapid_api_key = os.environ.get('RAPIDAPI_KEY')
    if not rapid_api_key:
        print("❌ RAPIDAPI_KEY not found")
        return
    
    print("🔍 Testing RapidAPI for upcoming matches...")
    
    # Test Premier League (39)
    league_id = 39
    current_date = datetime.utcnow()
    end_date = current_date + timedelta(days=7)
    
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
                print(f"📊 RapidAPI Status: {response.status}")
                
                if response.status == 200:
                    data = await response.json()
                    fixtures = data.get('response', [])
                    print(f"✅ Found {len(fixtures)} upcoming fixtures")
                    
                    # Show first few matches
                    for i, fixture in enumerate(fixtures[:3]):
                        try:
                            match_date = fixture.get('fixture', {}).get('date', '')
                            home_team = fixture['teams']['home']['name']
                            away_team = fixture['teams']['away']['name']
                            match_id = fixture['fixture']['id']
                            
                            # Calculate timing
                            match_dt = datetime.fromisoformat(match_date.replace('Z', '+00:00')).replace(tzinfo=None)
                            hours_until = (match_dt - current_date).total_seconds() / 3600
                            
                            print(f"  Match {i+1}: {home_team} vs {away_team}")
                            print(f"    ID: {match_id}")
                            print(f"    Date: {match_date}")
                            print(f"    Hours until: {hours_until:.1f}h")
                            print(f"    Timing window: {'✅ Yes' if 24 <= hours_until <= 168 else '❌ No'}")
                            print()
                        except Exception as e:
                            print(f"  Error parsing fixture {i+1}: {e}")
                            
                else:
                    error_text = await response.text()
                    print(f"❌ RapidAPI Error: {error_text}")
                    
    except Exception as e:
        print(f"❌ RapidAPI Exception: {e}")

async def test_odds_api():
    """Test The Odds API for real bookmaker odds"""
    odds_api_key = os.environ.get('ODDS_API_KEY')
    if not odds_api_key:
        print("❌ ODDS_API_KEY not found")
        return
    
    print("\n🎰 Testing The Odds API...")
    
    # Test with Premier League
    url = "https://api.the-odds-api.com/v4/sports/soccer_epl/odds"
    params = {
        'apikey': odds_api_key,
        'regions': 'eu',
        'markets': 'h2h',
        'oddsFormat': 'decimal',
        'dateFormat': 'iso'
    }
    headers = {}
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, params=params) as response:
                print(f"📊 Odds API Status: {response.status}")
                
                if response.status == 200:
                    data = await response.json()
                    print(f"✅ Found {len(data)} events with odds")
                    
                    # Show first few events
                    for i, event in enumerate(data[:3]):
                        home_team = event.get('home_team', 'Unknown')
                        away_team = event.get('away_team', 'Unknown')
                        start_time = event.get('commence_time', '')
                        
                        bookmakers = event.get('bookmakers', [])
                        print(f"  Event {i+1}: {home_team} vs {away_team}")
                        print(f"    Start: {start_time}")
                        print(f"    Bookmakers: {len(bookmakers)}")
                        
                        # Show odds from first bookmaker
                        if bookmakers:
                            first_book = bookmakers[0]
                            book_name = first_book.get('title', 'Unknown')
                            markets = first_book.get('markets', [])
                            
                            for market in markets:
                                if market.get('key') == 'h2h':
                                    outcomes = market.get('outcomes', [])
                                    print(f"    {book_name} odds:")
                                    for outcome in outcomes:
                                        print(f"      {outcome.get('name', 'Unknown')}: {outcome.get('price', 'N/A')}")
                        print()
                        
                else:
                    error_text = await response.text()
                    print(f"❌ Odds API Error: {error_text}")
                    
    except Exception as e:
        print(f"❌ Odds API Exception: {e}")

async def main():
    """Run all tests"""
    print("🚀 Testing Real Data APIs for Upcoming Matches Collection")
    print("=" * 60)
    
    await test_rapidapi_upcoming()
    await test_odds_api()
    
    print("\n✅ Direct API testing complete!")

if __name__ == "__main__":
    asyncio.run(main())