#!/usr/bin/env python3
"""
Capture current bookmaker ID mappings by calling The Odds API
and generating the same hash IDs that automated_collector.py uses.
"""
import os
import requests
import psycopg2

# Use same hash seed as main process (if set)
# This won't help if PYTHONHASHSEED is random, but worth trying

def capture_bookmaker_mappings():
    """Fetch bookmaker names from The Odds API and generate mappings"""
    
    api_key = os.getenv('ODDS_API_KEY')
    if not api_key:
        print("Error: ODDS_API_KEY not found")
        return
    
    # Fetch from a sample sport
    url = f"https://api.the-odds-api.com/v4/sports/soccer_italy_serie_a/odds"
    params = {
        'apiKey': api_key,
        'regions': 'eu',
        'markets': 'h2h',
        'oddsFormat': 'decimal'
    }
    
    print("Fetching live bookmaker data from The Odds API...")
    response = requests.get(url, params=params)
    
    if response.status_code != 200:
        print(f"API Error: {response.status_code}")
        print(response.text)
        return
    
    data = response.json()
    
    if not data or not isinstance(data, list):
        print("No data returned from API")
        return
    
    # Collect all unique bookmakers
    bookmaker_map = {}
    for event in data:
        for bookmaker in event.get('bookmakers', []):
            title = bookmaker.get('title', '')
            key = bookmaker.get('key', '')
            if title:
                book_id = hash(title) % 1000
                bookmaker_map[book_id] = {
                    'title': title,
                    'key': key
                }
    
    print(f"\nFound {len(bookmaker_map)} unique bookmakers:\n")
    print(f"{'ID':<6} {'Title':<30} {'Key':<20}")
    print("="*60)
    
    for book_id in sorted(bookmaker_map.keys()):
        info = bookmaker_map[book_id]
        print(f"{book_id:<6} {info['title']:<30} {info['key']:<20}")
    
    # Generate SQL INSERT statements
    print("\n\nSQL INSERT statements:")
    print("="*60)
    print("INSERT INTO bookmaker_xwalk (theodds_book_id, canonical_name, is_active) VALUES")
    
    items = sorted(bookmaker_map.items())
    for i, (book_id, info) in enumerate(items):
        canonical = info['key']  # Use The Odds API key as canonical name
        comma = "," if i < len(items) - 1 else ";"
        print(f"  ('{book_id}', '{canonical}', true){comma}  -- {info['title']}")
    
    print("\nON CONFLICT (canonical_name) DO UPDATE SET")
    print("  theodds_book_id = EXCLUDED.theodds_book_id,")
    print("  is_active = EXCLUDED.is_active,")
    print("  updated_at = NOW();")
    
    return bookmaker_map

if __name__ == '__main__':
    capture_bookmaker_mappings()
