"""
Test RapidAPI Football access and try different endpoints
"""

import os
import requests
import json
from datetime import datetime, timedelta

def test_api_endpoints():
    """Test various API endpoints to see what data is available"""
    
    api_key = os.environ.get('RAPIDAPI_KEY')
    if not api_key:
        print("❌ RAPIDAPI_KEY not found")
        return
    
    headers = {
        "X-RapidAPI-Key": api_key,
        "X-RapidAPI-Host": "api-football-v1.p.rapidapi.com"
    }
    
    base_url = "https://api-football-v1.p.rapidapi.com/v3"
    
    print("Testing RapidAPI Football access...")
    print("=" * 40)
    
    # Test 1: Check API status
    print("1. Testing API status...")
    try:
        response = requests.get(f"{base_url}/status", headers=headers)
        print(f"Status Code: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"API Status: {json.dumps(data, indent=2)}")
        else:
            print(f"Error: {response.text}")
    except Exception as e:
        print(f"Error: {e}")
    
    print("\n" + "-" * 40)
    
    # Test 2: Get available leagues
    print("2. Testing leagues endpoint...")
    try:
        response = requests.get(f"{base_url}/leagues", headers=headers, params={"current": "true"})
        print(f"Status Code: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            if data.get('response'):
                euro_leagues = []
                for league in data['response'][:10]:  # First 10 leagues
                    league_info = league.get('league', {})
                    if league_info.get('id') in [39, 140, 135, 78, 61]:  # Our target leagues
                        euro_leagues.append({
                            'id': league_info.get('id'),
                            'name': league_info.get('name'),
                            'country': league.get('country', {}).get('name')
                        })
                
                print(f"Found European leagues: {json.dumps(euro_leagues, indent=2)}")
            else:
                print("No leagues data in response")
        else:
            print(f"Error: {response.text}")
    except Exception as e:
        print(f"Error: {e}")
    
    print("\n" + "-" * 40)
    
    # Test 3: Get recent fixtures for Premier League
    print("3. Testing fixtures endpoint (Premier League recent matches)...")
    try:
        # Get matches from last 30 days
        from_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
        to_date = datetime.now().strftime('%Y-%m-%d')
        
        params = {
            "league": 39,  # Premier League
            "from": from_date,
            "to": to_date
        }
        
        response = requests.get(f"{base_url}/fixtures", headers=headers, params=params)
        print(f"Status Code: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            if data.get('response'):
                fixtures = data['response']
                print(f"Found {len(fixtures)} recent fixtures")
                
                # Show first fixture details
                if fixtures:
                    fixture = fixtures[0]
                    sample_data = {
                        'id': fixture.get('fixture', {}).get('id'),
                        'date': fixture.get('fixture', {}).get('date'),
                        'home': fixture.get('teams', {}).get('home', {}).get('name'),
                        'away': fixture.get('teams', {}).get('away', {}).get('name'),
                        'status': fixture.get('fixture', {}).get('status', {}).get('short'),
                        'home_goals': fixture.get('goals', {}).get('home'),
                        'away_goals': fixture.get('goals', {}).get('away')
                    }
                    print(f"Sample fixture: {json.dumps(sample_data, indent=2)}")
            else:
                print("No fixtures in response")
        else:
            print(f"Error: {response.text}")
    except Exception as e:
        print(f"Error: {e}")
    
    print("\n" + "-" * 40)
    
    # Test 4: Try getting historical fixtures with season parameter
    print("4. Testing historical fixtures (Premier League 2023 season)...")
    try:
        params = {
            "league": 39,
            "season": 2023
        }
        
        response = requests.get(f"{base_url}/fixtures", headers=headers, params=params)
        print(f"Status Code: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            if data.get('response'):
                fixtures = data['response']
                finished_fixtures = [f for f in fixtures if f.get('fixture', {}).get('status', {}).get('short') == 'FT']
                print(f"Found {len(fixtures)} total fixtures, {len(finished_fixtures)} finished")
                
                if finished_fixtures:
                    print("✅ Historical data available!")
                    return True
            else:
                print("No historical fixtures found")
        else:
            print(f"Error: {response.text}")
    except Exception as e:
        print(f"Error: {e}")
    
    return False

if __name__ == "__main__":
    has_data = test_api_endpoints()
    
    if has_data:
        print("\n✅ API access confirmed - can proceed with real data collection")
    else:
        print("\n❌ API access limited or no historical data available")
        print("Options:")
        print("1. Use existing training data collection system")
        print("2. Generate realistic synthetic data for development")
        print("3. Check API subscription level")