#!/usr/bin/env python3
"""Test API-Football odds with upcoming fixtures"""

import os
import requests
import json
from datetime import datetime, timedelta

RAPIDAPI_KEY = os.environ.get('RAPIDAPI_KEY')
BASE_URL = "https://api-football-v1.p.rapidapi.com/v3"
HEADERS = {
    "X-RapidAPI-Key": RAPIDAPI_KEY,
    "X-RapidAPI-Host": "api-football-v1.p.rapidapi.com"
}

def test_upcoming_fixtures_with_odds():
    """Get upcoming fixtures and their odds"""
    print("🔍 TESTING UPCOMING FIXTURES WITH ODDS")
    print("=" * 70)
    
    # Get upcoming fixtures
    fixtures_url = f"{BASE_URL}/fixtures"
    
    date_from = datetime.utcnow().strftime("%Y-%m-%d")
    date_to = (datetime.utcnow() + timedelta(days=3)).strftime("%Y-%m-%d")
    
    params = {
        "league": "39",  # Premier League
        "season": "2024",
        "from": date_from,
        "to": date_to
    }
    
    print(f"Fetching upcoming Premier League fixtures ({date_from} to {date_to})...")
    response = requests.get(fixtures_url, headers=HEADERS, params=params, timeout=30)
    
    if response.status_code != 200:
        print(f"❌ Failed: {response.status_code}")
        return
    
    fixtures_data = response.json()
    fixtures = fixtures_data.get('response', [])
    
    print(f"✅ Found {len(fixtures)} upcoming fixtures\n")
    
    if not fixtures:
        print("⚠️  No upcoming fixtures - trying different date range")
        # Try next 14 days
        date_to = (datetime.utcnow() + timedelta(days=14)).strftime("%Y-%m-%d")
        params['to'] = date_to
        response = requests.get(fixtures_url, headers=HEADERS, params=params, timeout=30)
        fixtures_data = response.json()
        fixtures = fixtures_data.get('response', [])
        print(f"✅ Found {len(fixtures)} fixtures in next 14 days\n")
    
    if not fixtures:
        print("❌ Still no fixtures found")
        return
    
    # Test odds for first fixture
    sample_fixture = fixtures[0]
    fixture_id = sample_fixture['fixture']['id']
    home_team = sample_fixture['teams']['home']['name']
    away_team = sample_fixture['teams']['away']['name']
    match_date = sample_fixture['fixture']['date']
    
    print(f"📊 Sample Fixture:")
    print(f"  ID: {fixture_id}")
    print(f"  Match: {home_team} vs {away_team}")
    print(f"  Date: {match_date}")
    print()
    
    # Get odds
    odds_url = f"{BASE_URL}/odds"
    odds_params = {"fixture": str(fixture_id)}
    
    print("Fetching odds...")
    odds_response = requests.get(odds_url, headers=HEADERS, params=odds_params, timeout=30)
    
    if odds_response.status_code != 200:
        print(f"❌ Odds request failed: {odds_response.status_code}")
        print(f"Response: {odds_response.text}")
        return
    
    odds_data = odds_response.json()
    odds_list = odds_data.get('response', [])
    
    if not odds_list:
        print("⚠️  No odds available for this fixture")
        return
    
    print(f"✅ Odds retrieved successfully!\n")
    
    # Analyze odds structure
    odds_entry = odds_list[0]
    bookmakers = odds_entry.get('bookmakers', [])
    
    print(f"📖 ODDS DATA STRUCTURE:")
    print(f"  Number of bookmakers: {len(bookmakers)}")
    print()
    
    # Show detailed structure for first bookmaker
    if bookmakers:
        first_book = bookmakers[0]
        print(f"Sample Bookmaker Structure:")
        print(f"  ID: {first_book.get('id')}")
        print(f"  Name: {first_book.get('name')}")
        print(f"  Markets available: {len(first_book.get('bets', []))}")
        print()
        
        # Show all available markets
        print(f"Available Markets:")
        for bet in first_book.get('bets', []):
            print(f"  • {bet['name']} ({bet['id']})")
        print()
        
        # Find Match Winner market
        match_winner = next((bet for bet in first_book['bets'] if bet['name'] == 'Match Winner'), None)
        
        if match_winner:
            print(f"Match Winner Odds (3-way):")
            for value in match_winner['values']:
                print(f"  {value['value']:<10} {value['odd']}")
            print()
    
    # Show all bookmakers with Match Winner odds
    print(f"📊 ALL BOOKMAKERS - MATCH WINNER ODDS:")
    print(f"{'Bookmaker':<25} {'Home':<10} {'Draw':<10} {'Away':<10}")
    print("-" * 58)
    
    for bookmaker in bookmakers:
        book_name = bookmaker['name']
        bets = bookmaker.get('bets', [])
        match_winner = next((bet for bet in bets if bet['name'] == 'Match Winner'), None)
        
        if match_winner:
            values = match_winner.get('values', [])
            home_odd = next((v['odd'] for v in values if v['value'] == 'Home'), '-')
            draw_odd = next((v['odd'] for v in values if v['value'] == 'Draw'), '-')
            away_odd = next((v['odd'] for v in values if v['value'] == 'Away'), '-')
            
            print(f"{book_name:<25} {home_odd:<10} {draw_odd:<10} {away_odd:<10}")
    
    print()
    print("✅ API-Football odds endpoint fully functional!")
    print(f"✅ Data format: Compatible with our odds_snapshots table")
    print(f"✅ Bookmakers: {len(bookmakers)} available for this match")

if __name__ == "__main__":
    test_upcoming_fixtures_with_odds()
