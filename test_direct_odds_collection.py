#!/usr/bin/env python3

import asyncio
import os
import aiohttp
import psycopg2
from datetime import datetime

async def test_direct_odds_collection():
    """Test direct odds collection for one match"""
    print("🎯 Direct Odds Collection Test")
    print("=" * 40)
    
    # Get The Odds API key
    api_key = os.environ.get('ODDS_API_KEY')
    database_url = os.environ.get('DATABASE_URL')
    
    if not api_key or not database_url:
        print("❌ Missing API key or database URL")
        return
    
    print(f"1️⃣ Testing The Odds API connection...")
    
    # Get Premier League odds
    url = "https://api.the-odds-api.com/v4/sports/soccer_epl/odds"
    params = {
        'apiKey': api_key,
        'regions': 'eu',
        'markets': 'h2h',
        'oddsFormat': 'decimal'
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as response:
            print(f"   Status: {response.status}")
            
            if response.status == 200:
                data = await response.json()
                print(f"   Found {len(data)} events")
                
                if data:
                    event = data[0]
                    print(f"   First event: {event.get('home_team')} vs {event.get('away_team')}")
                    print(f"   Bookmakers: {len(event.get('bookmakers', []))}")
                    
                    # Process first bookmaker's odds
                    bookmakers = event.get('bookmakers', [])
                    if bookmakers:
                        print(f"\n2️⃣ Testing database insertion...")
                        
                        book = bookmakers[0]
                        book_title = book.get('title', 'Unknown')
                        markets = book.get('markets', [])
                        
                        if markets:
                            market = markets[0]
                            outcomes = market.get('outcomes', [])
                            
                            # Prepare test data
                            match_id = 9999999  # Test match ID
                            league_id = 39
                            timestamp = datetime.utcnow()
                            
                            test_odds = []
                            for outcome in outcomes:
                                # Map team names to H/D/A format
                                outcome_name = outcome.get('name', 'Unknown')
                                if outcome_name == 'Draw':
                                    outcome_code = 'D'
                                elif outcome_name == event.get('home_team'):
                                    outcome_code = 'H'
                                else:  # Away team
                                    outcome_code = 'A'
                                    
                                test_odds.append({
                                    'match_id': match_id,
                                    'league_id': league_id,
                                    'book_id': book_title,
                                    'timestamp': timestamp,
                                    'secs_to_kickoff': 3600,
                                    'outcome': outcome_code,  # H/D/A only
                                    'odds_decimal': outcome.get('price', 1.0),
                                    'implied_prob': 1.0 / outcome.get('price', 1.0)
                                })
                            
                            # Test database insertion
                            try:
                                with psycopg2.connect(database_url) as conn:
                                    cursor = conn.cursor()
                                    
                                    saved_count = 0
                                    for odds in test_odds:
                                        insert_sql = """
                                            INSERT INTO odds_snapshots 
                                            (match_id, league_id, book_id, market, ts_snapshot, secs_to_kickoff,
                                             outcome, odds_decimal, implied_prob, market_margin, created_at)
                                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                                            ON CONFLICT (match_id, book_id, market, outcome) DO UPDATE SET
                                            odds_decimal = EXCLUDED.odds_decimal,
                                            implied_prob = EXCLUDED.implied_prob,
                                            ts_snapshot = EXCLUDED.ts_snapshot,
                                            secs_to_kickoff = EXCLUDED.secs_to_kickoff
                                        """
                                        
                                        values = (
                                            odds['match_id'],
                                            odds['league_id'],
                                            odds['book_id'],
                                            'h2h',
                                            odds['timestamp'],
                                            odds['secs_to_kickoff'],
                                            odds['outcome'],
                                            odds['odds_decimal'],
                                            odds['implied_prob'],
                                            0.05,  # market_margin
                                            odds['timestamp']
                                        )
                                        
                                        cursor.execute(insert_sql, values)
                                        saved_count += 1
                                    
                                    conn.commit()
                                    print(f"   ✅ Successfully saved {saved_count} test odds")
                                    
                                    # Verify data
                                    cursor.execute("SELECT COUNT(*) FROM odds_snapshots WHERE match_id = %s", (match_id,))
                                    count = cursor.fetchone()[0]
                                    print(f"   📊 Total odds for test match: {count}")
                                    
                            except Exception as db_error:
                                print(f"   ❌ Database error: {db_error}")
                            
                        else:
                            print("   No markets found")
                    else:
                        print("   No bookmakers found")
            else:
                error_text = await response.text()
                print(f"   ❌ API Error: {error_text}")

if __name__ == "__main__":
    asyncio.run(test_direct_odds_collection())