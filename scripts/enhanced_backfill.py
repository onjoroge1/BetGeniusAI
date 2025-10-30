#!/usr/bin/env python3
"""
Enhanced backfill: Search ALL available sports to maximize bookmaker coverage
"""
import os
import requests
import psycopg2
from psycopg2.extras import execute_batch
import time

def get_all_sports():
    """Fetch all available sports from The Odds API"""
    api_key = os.getenv('ODDS_API_KEY')
    url = "https://api.the-odds-api.com/v4/sports"
    
    try:
        response = requests.get(url, params={'apiKey': api_key}, timeout=10)
        if response.status_code == 200:
            sports = response.json()
            # Filter for soccer/football sports
            soccer_sports = [s['key'] for s in sports if 'soccer' in s['key'] or 'football' in s['key']]
            return soccer_sports
        return []
    except Exception as e:
        print(f"Error fetching sports: {e}")
        return []

def fetch_all_bookmakers_comprehensive():
    """Fetch bookmakers from ALL sports to get maximum coverage"""
    api_key = os.getenv('ODDS_API_KEY')
    
    sports = get_all_sports()
    print(f"Found {len(sports)} soccer/football sports to search\n")
    
    bookmaker_map = {}
    
    for i, sport in enumerate(sports, 1):
        try:
            url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds"
            params = {
                'apiKey': api_key,
                'regions': 'eu,us,au,uk',  # All regions
                'markets': 'h2h',
                'oddsFormat': 'decimal'
            }
            
            print(f"[{i}/{len(sports)}] Fetching {sport}...", end=' ')
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                new_bookmakers = 0
                
                for event in data:
                    for bookmaker in event.get('bookmakers', []):
                        title = bookmaker.get('title', '')
                        key = bookmaker.get('key', '')
                        if title and key:
                            hash_id = str(hash(title) % 1000)
                            if hash_id not in bookmaker_map:
                                bookmaker_map[hash_id] = {
                                    'key': key,
                                    'title': title
                                }
                                new_bookmakers += 1
                
                print(f"✅ {new_bookmakers} new bookmakers (total: {len(bookmaker_map)})")
            else:
                print(f"❌ HTTP {response.status_code}")
            
            # Rate limiting
            time.sleep(0.5)
                
        except Exception as e:
            print(f"❌ Error: {e}")
            continue
    
    print(f"\n✅ Comprehensive search complete: {len(bookmaker_map)} unique bookmakers")
    return bookmaker_map

def update_unmapped_bookmakers(cursor):
    """Update bookmaker_xwalk with new mappings"""
    
    bookmaker_map = fetch_all_bookmakers_comprehensive()
    
    # Get legacy IDs that are still unmapped
    cursor.execute("""
        SELECT DISTINCT book_id 
        FROM odds_snapshots 
        WHERE book_id NOT LIKE 'apif:%'
        AND book_id ~ '^[0-9]+$'
        AND book_id NOT IN (
            SELECT theodds_book_id 
            FROM bookmaker_xwalk 
            WHERE theodds_book_id IS NOT NULL
        )
        ORDER BY book_id
    """)
    
    unmapped_ids = [row[0] for row in cursor.fetchall()]
    print(f"\nFound {len(unmapped_ids)} unmapped IDs in database")
    
    new_mappings = []
    still_unmapped = []
    
    for book_id in unmapped_ids:
        if book_id in bookmaker_map:
            info = bookmaker_map[book_id]
            new_mappings.append((book_id, info['key'], info['title']))
            print(f"  ✅ {book_id} → {info['key']} ({info['title']})")
        else:
            still_unmapped.append(book_id)
    
    if new_mappings:
        print(f"\n🔄 Inserting {len(new_mappings)} new mappings into bookmaker_xwalk...")
        
        execute_batch(cursor, """
            INSERT INTO bookmaker_xwalk (theodds_book_id, canonical_name, is_active)
            VALUES (%s, %s, true)
            ON CONFLICT (canonical_name) DO UPDATE SET
                theodds_book_id = EXCLUDED.theodds_book_id,
                updated_at = NOW()
        """, [(bid, key, True) for bid, key, title in new_mappings])
        
        print(f"✅ Inserted {len(new_mappings)} new mappings")
        
        # Now update odds_snapshots
        print(f"\n🔄 Updating odds_snapshots...")
        for book_id, key, title in new_mappings:
            # Delete potential duplicates first
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
            """, (book_id, key))
            
            # Update to stable key
            cursor.execute("""
                UPDATE odds_snapshots 
                SET book_id = %s 
                WHERE book_id = %s
            """, (key, book_id))
        
        print(f"✅ Updated odds_snapshots")
    
    if still_unmapped:
        print(f"\n⚠️  Still unmapped: {len(still_unmapped)} IDs")
        for bid in still_unmapped[:20]:
            print(f"    - {bid}")
        if len(still_unmapped) > 20:
            print(f"    ... and {len(still_unmapped) - 20} more")
    
    return len(new_mappings), len(still_unmapped)

def main():
    print("="*60)
    print("Enhanced Bookmaker Backfill - Comprehensive Search")
    print("="*60)
    
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        print("❌ DATABASE_URL not found")
        return
    
    conn = psycopg2.connect(database_url)
    cursor = conn.cursor()
    
    try:
        mapped, unmapped = update_unmapped_bookmakers(cursor)
        
        conn.commit()
        
        print("\n" + "="*60)
        print("✅ ENHANCED BACKFILL COMPLETE")
        print("="*60)
        print(f"  New mappings: {mapped}")
        print(f"  Still unmapped: {unmapped}")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()

if __name__ == '__main__':
    main()
