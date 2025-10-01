#!/usr/bin/env python3
"""
Find live/upcoming fixtures from API-Football for testing.
"""

import requests
import os
from datetime import datetime, timedelta

RAPIDAPI_KEY = os.getenv('RAPIDAPI_KEY')
host = 'api-football-v1.p.rapidapi.com'

headers = {
    'x-rapidapi-key': RAPIDAPI_KEY,
    'x-rapidapi-host': host
}

today = datetime.now().strftime('%Y-%m-%d')
tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')

print("Searching for upcoming fixtures with odds...")
print(f"Date range: {today} to {tomorrow}\n")

response = requests.get(
    f'https://{host}/v3/fixtures',
    headers=headers,
    params={'league': 39, 'season': 2024, 'next': 5},
    timeout=30
)

if response.status_code == 200:
    data = response.json()
    fixtures = data.get('response', [])
    
    print(f"Found {len(fixtures)} upcoming Premier League fixtures:\n")
    
    for fixture in fixtures[:3]:
        fixture_id = fixture['fixture']['id']
        date = fixture['fixture']['date']
        home_team = fixture['teams']['home']['name']
        away_team = fixture['teams']['away']['name']
        
        print(f"Fixture {fixture_id}: {home_team} vs {away_team}")
        print(f"  Date: {date}")
        
        odds_response = requests.get(
            f'https://{host}/v3/odds',
            headers=headers,
            params={'fixture': fixture_id},
            timeout=30
        )
        
        if odds_response.status_code == 200:
            odds_data = odds_response.json()
            if odds_data.get('response') and len(odds_data['response']) > 0:
                bookmakers = odds_data['response'][0].get('bookmakers', [])
                print(f"  ✅ {len(bookmakers)} bookmakers have odds")
                print(f"  Test with: python test_api_football_with_fixture.py {fixture_id}\n")
            else:
                print(f"  ❌ No odds available yet\n")
        else:
            print(f"  ❌ Error fetching odds: {odds_response.status_code}\n")
else:
    print(f"Error: {response.status_code}")
    print(response.text)
