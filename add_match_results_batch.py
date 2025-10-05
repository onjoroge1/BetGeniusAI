#!/usr/bin/env python3
"""
Batch Add Match Results Script
Fetches results for completed matches and submits to /metrics/result endpoint
"""

import requests
import os
from datetime import datetime, timezone, timedelta

API_KEY = "betgenius_secure_key_2024"
RAPIDAPI_KEY = os.environ.get('RAPIDAPI_KEY')
BASE_URL = "http://localhost:8000"

def fetch_completed_matches_from_db():
    """Get list of prediction snapshots that need results"""
    import psycopg2
    
    conn = psycopg2.connect(os.environ.get('DATABASE_URL'))
    cursor = conn.cursor()
    
    # Find predictions older than 2 hours without results
    sql = """
        SELECT DISTINCT ps.match_id
        FROM prediction_snapshots ps
        WHERE ps.kickoff_at < NOW() - INTERVAL '2 hours'
        AND NOT EXISTS (
            SELECT 1 FROM match_results mr 
            WHERE mr.match_id = ps.match_id
        )
        ORDER BY ps.match_id DESC
        LIMIT 20
    """
    
    cursor.execute(sql)
    match_ids = [row[0] for row in cursor.fetchall()]
    
    cursor.close()
    conn.close()
    
    return match_ids

def get_match_result(match_id):
    """Fetch match result from API-Football"""
    if not RAPIDAPI_KEY:
        print(f"❌ RAPIDAPI_KEY not set")
        return None
    
    url = "https://api-football-v1.p.rapidapi.com/v3/fixtures"
    headers = {
        'X-RapidAPI-Key': RAPIDAPI_KEY,
        'X-RapidAPI-Host': 'api-football-v1.p.rapidapi.com'
    }
    
    try:
        response = requests.get(url, headers=headers, params={'id': match_id}, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            if data.get('response') and len(data['response']) > 0:
                fixture = data['response'][0]
                status = fixture['fixture']['status']['short']
                
                if status in ['FT', 'AET', 'PEN']:
                    return {
                        'match_id': match_id,
                        'home_goals': fixture['goals']['home'],
                        'away_goals': fixture['goals']['away'],
                        'league': fixture['league']['name'],
                        'status': status
                    }
    except Exception as e:
        print(f"❌ Error fetching match {match_id}: {e}")
    
    return None

def submit_result(result_data):
    """Submit result to /metrics/result endpoint"""
    try:
        response = requests.post(
            f"{BASE_URL}/metrics/result",
            headers={
                'Authorization': f'Bearer {API_KEY}',
                'Content-Type': 'application/json'
            },
            json=result_data,
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            return data['success']
        else:
            print(f"❌ Failed to submit: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ Error submitting result: {e}")
        return False

def main():
    print("🔄 BATCH MATCH RESULTS PROCESSOR")
    print("=" * 50)
    
    # Get matches needing results
    print("\n📋 Fetching matches needing results...")
    match_ids = fetch_completed_matches_from_db()
    
    if not match_ids:
        print("✅ No matches need results - all up to date!")
        return
    
    print(f"📊 Found {len(match_ids)} matches needing results")
    
    # Process each match
    results_added = 0
    for i, match_id in enumerate(match_ids, 1):
        print(f"\n[{i}/{len(match_ids)}] Processing match {match_id}...")
        
        # Fetch result from API
        result = get_match_result(match_id)
        
        if result:
            print(f"  ✅ Result: {result['home_goals']}-{result['away_goals']} ({result['status']})")
            
            # Submit to API
            if submit_result(result):
                print(f"  ✅ Submitted successfully")
                results_added += 1
            else:
                print(f"  ❌ Failed to submit")
        else:
            print(f"  ⏳ Match not finished yet or error fetching")
    
    print(f"\n{'=' * 50}")
    print(f"✅ Complete! Added {results_added} match results")
    print(f"\n💡 Run these to view updated metrics:")
    print(f"   curl '{BASE_URL}/metrics/evaluation?window=all' -H 'Authorization: Bearer {API_KEY}'")
    print(f"   curl '{BASE_URL}/metrics/summary?window=30d' -H 'Authorization: Bearer {API_KEY}'")

if __name__ == "__main__":
    main()
