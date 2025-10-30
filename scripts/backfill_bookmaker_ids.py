#!/usr/bin/env python3
"""
Backfill script to replace legacy hash-based book_ids with stable bookmaker keys.

This script:
1. Fetches all bookmakers from The Odds API
2. Generates hash mappings (hash(title) % 1000 → key)
3. Updates odds_snapshots to replace hash IDs with bookmaker keys
4. Populates bookmaker_xwalk with all bookmaker mappings
"""
import os
import requests
import psycopg2
from psycopg2.extras import execute_batch

def fetch_all_bookmakers():
    """Fetch bookmakers from multiple sports to get comprehensive list"""
    api_key = os.getenv('ODDS_API_KEY')
    if not api_key:
        print("Error: ODDS_API_KEY not found")
        return {}
    
    bookmaker_map = {}
    
    # Fetch from multiple sports to get max bookmaker coverage
    sports = [
        'soccer_epl',
        'soccer_spain_la_liga', 
        'soccer_italy_serie_a',
        'soccer_germany_bundesliga',
        'soccer_france_ligue_one',
        'soccer_uefa_champs_league'
    ]
    
    for sport in sports:
        try:
            url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds"
            params = {
                'apiKey': api_key,
                'regions': 'eu,us,au',
                'markets': 'h2h',
                'oddsFormat': 'decimal'
            }
            
            print(f"Fetching bookmakers from {sport}...")
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                
                for event in data:
                    for bookmaker in event.get('bookmakers', []):
                        title = bookmaker.get('title', '')
                        key = bookmaker.get('key', '')
                        if title and key:
                            hash_id = str(hash(title) % 1000)
                            bookmaker_map[hash_id] = {
                                'key': key,
                                'title': title
                            }
            else:
                print(f"  Warning: {sport} returned {response.status_code}")
                
        except Exception as e:
            print(f"  Error fetching {sport}: {e}")
            continue
    
    print(f"\n✅ Found {len(bookmaker_map)} unique bookmakers")
    return bookmaker_map

def get_legacy_book_ids(cursor):
    """Get all unique numeric book_ids from odds_snapshots"""
    cursor.execute("""
        SELECT DISTINCT book_id 
        FROM odds_snapshots 
        WHERE book_id NOT LIKE 'apif:%'
        AND book_id ~ '^[0-9]+$'  -- Only numeric IDs
        ORDER BY book_id
    """)
    return [row[0] for row in cursor.fetchall()]

def backfill_odds_snapshots(cursor, bookmaker_map):
    """Update odds_snapshots to replace hash IDs with bookmaker keys"""
    
    legacy_ids = get_legacy_book_ids(cursor)
    print(f"\nFound {len(legacy_ids)} legacy numeric book_ids in odds_snapshots")
    
    updates = []
    unmapped = []
    
    for legacy_id in legacy_ids:
        if legacy_id in bookmaker_map:
            bookmaker_key = bookmaker_map[legacy_id]['key']
            bookmaker_title = bookmaker_map[legacy_id]['title']
            updates.append((bookmaker_key, legacy_id))
            print(f"  {legacy_id} → {bookmaker_key} ({bookmaker_title})")
        else:
            unmapped.append(legacy_id)
    
    if unmapped:
        print(f"\n⚠️  Warning: {len(unmapped)} book_ids cannot be mapped:")
        for book_id in unmapped[:10]:
            print(f"    - {book_id}")
        if len(unmapped) > 10:
            print(f"    ... and {len(unmapped) - 10} more")
    
    if updates:
        print(f"\n🔄 Updating {len(updates)} book_id mappings in odds_snapshots...")
        
        # Handle duplicates by deleting legacy rows that would conflict
        print("  Checking for potential conflicts...")
        for bookmaker_key, legacy_id in updates:
            # Delete rows where updating would create duplicate
            cursor.execute("""
                DELETE FROM odds_snapshots
                WHERE book_id = %s
                AND EXISTS (
                    SELECT 1 FROM odds_snapshots o2
                    WHERE o2.match_id = odds_snapshots.match_id
                    AND o2.market = odds_snapshots.market
                    AND o2.outcome = odds_snapshots.outcome
                    AND o2.book_id = %s
                )
            """, (legacy_id, bookmaker_key))
            deleted = cursor.rowcount
            if deleted > 0:
                print(f"  Deleted {deleted} duplicate rows for {legacy_id} → {bookmaker_key}")
        
        # Now safe to update
        for bookmaker_key, legacy_id in updates:
            cursor.execute("""
                UPDATE odds_snapshots 
                SET book_id = %s 
                WHERE book_id = %s
            """, (bookmaker_key, legacy_id))
        
        print(f"✅ Updated {len(updates)} book_ids")
    
    return len(updates), len(unmapped)

def populate_bookmaker_xwalk(cursor, bookmaker_map):
    """Populate bookmaker_xwalk with all bookmaker mappings"""
    
    print(f"\n🔄 Populating bookmaker_xwalk with {len(bookmaker_map)} mappings...")
    
    values = []
    for hash_id, info in bookmaker_map.items():
        values.append((hash_id, info['key'], True))
    
    # Insert all mappings
    execute_batch(cursor, """
        INSERT INTO bookmaker_xwalk (theodds_book_id, canonical_name, is_active)
        VALUES (%s, %s, %s)
        ON CONFLICT (canonical_name) 
        DO UPDATE SET 
            theodds_book_id = EXCLUDED.theodds_book_id,
            is_active = EXCLUDED.is_active,
            updated_at = NOW()
    """, values)
    
    print(f"✅ Populated {len(values)} bookmaker mappings")

def main():
    print("="*60)
    print("Bookmaker ID Backfill Script")
    print("="*60)
    
    # Step 1: Fetch all bookmakers
    bookmaker_map = fetch_all_bookmakers()
    
    if not bookmaker_map:
        print("❌ No bookmakers fetched. Exiting.")
        return
    
    # Step 2: Connect to database
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        print("❌ DATABASE_URL not found")
        return
    
    conn = psycopg2.connect(database_url)
    cursor = conn.cursor()
    
    try:
        # Step 3: Backfill odds_snapshots
        updated, unmapped = backfill_odds_snapshots(cursor, bookmaker_map)
        
        # Step 4: Populate bookmaker_xwalk
        populate_bookmaker_xwalk(cursor, bookmaker_map)
        
        # Commit all changes
        conn.commit()
        
        print("\n" + "="*60)
        print("✅ BACKFILL COMPLETE")
        print("="*60)
        print(f"  Bookmakers mapped: {len(bookmaker_map)}")
        print(f"  Odds updated: {updated}")
        print(f"  Unmapped IDs: {unmapped}")
        print(f"  bookmaker_xwalk rows: {len(bookmaker_map)}")
        
    except Exception as e:
        print(f"\n❌ Error during backfill: {e}")
        conn.rollback()
        raise
    
    finally:
        cursor.close()
        conn.close()

if __name__ == '__main__':
    main()
