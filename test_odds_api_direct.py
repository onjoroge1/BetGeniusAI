#!/usr/bin/env python3

import os
import requests
import asyncio
import aiohttp

# Test The Odds API with different authentication methods
async def test_odds_api_auth():
    print("🔑 Testing The Odds API Authentication Methods")
    print("=" * 50)
    
    api_key = os.environ.get('ODDS_API_KEY')
    if not api_key:
        print("❌ No ODDS_API_KEY found in environment")
        return
    
    print(f"🔑 API Key exists (length: {len(api_key)})")
    
    # Test 1: Query parameter
    print("\n1️⃣ Testing with query parameter:")
    url = f"https://api.the-odds-api.com/v4/sports?apiKey={api_key}"
    
    try:
        response = requests.get(url, timeout=10)
        print(f"   Status: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"   ✅ Success! Found {len(data)} sports")
            # Look for soccer
            soccer_sports = [s for s in data if 'soccer' in s.get('title', '').lower()]
            print(f"   ⚽ Soccer sports: {len(soccer_sports)}")
        else:
            print(f"   ❌ Error: {response.text}")
    except Exception as e:
        print(f"   ❌ Exception: {e}")
    
    # Test 2: Header authentication  
    print("\n2️⃣ Testing with X-API-KEY header:")
    url = "https://api.the-odds-api.com/v4/sports"
    headers = {'X-API-KEY': api_key}
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        print(f"   Status: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"   ✅ Success! Found {len(data)} sports")
        else:
            print(f"   ❌ Error: {response.text}")
    except Exception as e:
        print(f"   ❌ Exception: {e}")
    
    # Test 3: Authorization header
    print("\n3️⃣ Testing with Authorization header:")
    headers = {'Authorization': f'Bearer {api_key}'}
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        print(f"   Status: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"   ✅ Success! Found {len(data)} sports")
        else:
            print(f"   ❌ Error: {response.text}")
    except Exception as e:
        print(f"   ❌ Exception: {e}")

if __name__ == "__main__":
    asyncio.run(test_odds_api_auth())