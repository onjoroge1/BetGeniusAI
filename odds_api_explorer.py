"""
The Odds API Explorer - Check available endpoints and sports
"""

import os
import requests
import json

def explore_odds_api():
    """Explore The Odds API to understand available endpoints"""
    
    api_key = os.environ.get('ODDS_API_KEY')
    base_url = "https://api.the-odds-api.com/v4"
    
    print("EXPLORING THE ODDS API")
    print("=" * 30)
    
    # 1. Get available sports
    print("1. Available Sports:")
    try:
        response = requests.get(f"{base_url}/sports", params={'api_key': api_key})
        response.raise_for_status()
        sports = response.json()
        
        soccer_sports = [s for s in sports if 'soccer' in s['key']]
        print(f"Found {len(soccer_sports)} soccer leagues:")
        
        for sport in soccer_sports[:10]:  # Show first 10
            print(f"  {sport['key']}: {sport['title']}")
            
    except Exception as e:
        print(f"Error fetching sports: {e}")
        return
    
    # 2. Try getting current odds for EPL
    print(f"\n2. Current Odds Sample (EPL):")
    try:
        epl_key = 'soccer_epl'
        response = requests.get(
            f"{base_url}/sports/{epl_key}/odds",
            params={
                'api_key': api_key,
                'regions': 'uk',
                'markets': 'h2h',
                'oddsFormat': 'decimal'
            }
        )
        response.raise_for_status()
        odds_data = response.json()
        
        print(f"Found {len(odds_data)} current matches")
        if odds_data:
            match = odds_data[0]
            print(f"Sample match: {match['home_team']} vs {match['away_team']}")
            print(f"Commence time: {match['commence_time']}")
            if match.get('bookmakers'):
                bookmaker = match['bookmakers'][0]
                print(f"Sample bookmaker: {bookmaker['key']}")
                
    except Exception as e:
        print(f"Error fetching current odds: {e}")
    
    # 3. Check if historical endpoint exists
    print(f"\n3. Historical Odds Test:")
    try:
        response = requests.get(
            f"{base_url}/historical/sports/{epl_key}/odds",
            params={
                'api_key': api_key,
                'regions': 'uk',
                'markets': 'h2h',
                'date': '2024-12-01'
            }
        )
        print(f"Historical endpoint status: {response.status_code}")
        if response.status_code == 200:
            historical_data = response.json()
            print(f"Historical matches found: {len(historical_data)}")
        else:
            print("Historical endpoint not available with current plan")
            
    except Exception as e:
        print(f"Historical endpoint error: {e}")
    
    # 4. Check usage
    print(f"\n4. API Usage:")
    try:
        response = requests.get(f"{base_url}/sports", params={'api_key': api_key})
        remaining = response.headers.get('x-requests-remaining', 'Unknown')
        used = response.headers.get('x-requests-used', 'Unknown')
        print(f"Requests remaining: {remaining}")
        print(f"Requests used: {used}")
        
    except Exception as e:
        print(f"Error checking usage: {e}")

if __name__ == "__main__":
    explore_odds_api()