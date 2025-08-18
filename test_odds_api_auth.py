#!/usr/bin/env python3
"""
Test The Odds API authentication with different methods
"""
import os
import asyncio
import aiohttp
import requests

def test_odds_api_sync():
    """Test The Odds API with requests (synchronous)"""
    odds_api_key = os.environ.get('ODDS_API_KEY')
    if not odds_api_key:
        print("❌ ODDS_API_KEY not found")
        return False
    
    print("🔑 Testing The Odds API authentication methods...")
    
    # Method 1: API key as query parameter
    print("\n1️⃣ Testing API key as query parameter:")
    url = f"https://api.the-odds-api.com/v4/sports/soccer_epl/odds?apikey={odds_api_key}&regions=eu&markets=h2h&oddsFormat=decimal"
    
    try:
        response = requests.get(url, timeout=10)
        print(f"   Status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"   ✅ Success! Found {len(data)} events with odds")
            return True
        else:
            print(f"   ❌ Error: {response.text}")
            
    except Exception as e:
        print(f"   ❌ Exception: {e}")
    
    # Method 2: API key in header
    print("\n2️⃣ Testing API key in header:")
    url = "https://api.the-odds-api.com/v4/sports/soccer_epl/odds"
    headers = {'X-API-Key': odds_api_key}
    params = {'regions': 'eu', 'markets': 'h2h', 'oddsFormat': 'decimal'}
    
    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
        print(f"   Status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"   ✅ Success! Found {len(data)} events with odds")
            return True
        else:
            print(f"   ❌ Error: {response.text}")
            
    except Exception as e:
        print(f"   ❌ Exception: {e}")
    
    return False

async def test_odds_api_async():
    """Test The Odds API with aiohttp (asynchronous)"""
    odds_api_key = os.environ.get('ODDS_API_KEY')
    if not odds_api_key:
        return False
    
    print("\n3️⃣ Testing with aiohttp (async):")
    url = f"https://api.the-odds-api.com/v4/sports/soccer_epl/odds"
    params = {
        'apikey': odds_api_key,
        'regions': 'eu',
        'markets': 'h2h',
        'oddsFormat': 'decimal'
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as response:
                print(f"   Status: {response.status}")
                
                if response.status == 200:
                    data = await response.json()
                    print(f"   ✅ Success! Found {len(data)} events with odds")
                    return True
                else:
                    error_text = await response.text()
                    print(f"   ❌ Error: {error_text}")
                    
    except Exception as e:
        print(f"   ❌ Exception: {e}")
    
    return False

def main():
    print("🧪 Testing The Odds API Authentication")
    print("=" * 50)
    
    # Test sync first
    sync_success = test_odds_api_sync()
    
    # Test async
    async_success = asyncio.run(test_odds_api_async())
    
    print(f"\n📊 Results:")
    print(f"   Sync requests: {'✅ Working' if sync_success else '❌ Failed'}")
    print(f"   Async aiohttp: {'✅ Working' if async_success else '❌ Failed'}")
    
    if sync_success or async_success:
        print(f"\n🎉 The Odds API is accessible! Authentication method identified.")
    else:
        print(f"\n💔 The Odds API authentication failed with all methods.")

if __name__ == "__main__":
    main()