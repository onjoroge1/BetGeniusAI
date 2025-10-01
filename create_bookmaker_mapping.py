#!/usr/bin/env python3
"""Create comprehensive bookmaker mapping between The Odds API and API-Football"""

import os
import requests
import json
import psycopg2

RAPIDAPI_KEY = os.environ.get('RAPIDAPI_KEY')
BASE_URL = "https://api-football-v1.p.rapidapi.com/v3"
HEADERS = {
    "X-RapidAPI-Key": RAPIDAPI_KEY,
    "X-RapidAPI-Host": "api-football-v1.p.rapidapi.com"
}
DATABASE_URL = os.environ.get('DATABASE_URL')

def get_all_api_football_bookmakers():
    """Get complete list of bookmakers from API-Football"""
    url = f"{BASE_URL}/odds/bookmakers"
    response = requests.get(url, headers=HEADERS, timeout=30)
    
    if response.status_code == 200:
        data = response.json()
        return data.get('response', [])
    return []

def get_existing_theodds_bookmakers():
    """Get bookmakers currently used from The Odds API (from odds_snapshots)"""
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT DISTINCT book_id
            FROM odds_snapshots
            ORDER BY book_id
        """)
        
        theodds_books = [row[0] for row in cursor.fetchall()]
        cursor.close()
        conn.close()
        
        return theodds_books
    except:
        # Fallback to known bookmakers
        return [
            'bet365', 'pinnacle', 'williamhill', 'betway', '1xbet',
            'unibet', 'parionssport', 'betclic', 'marathonbet',
            'coral', 'ladbrokes', '888sport', 'betvictor'
        ]

def create_mapping_table():
    """Create bookmaker crosswalk table in database"""
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bookmaker_xwalk (
                id SERIAL PRIMARY KEY,
                rapidapi_book_id INT,
                rapidapi_book_name VARCHAR(128),
                theodds_book_id VARCHAR(64),
                canonical_name VARCHAR(128),
                desk_group VARCHAR(64),
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(rapidapi_book_id, theodds_book_id)
            )
        """)
        
        conn.commit()
        cursor.close()
        conn.close()
        
        return True
    except Exception as e:
        print(f"Error creating table: {e}")
        return False

def create_bookmaker_mapping():
    """Create and analyze bookmaker mapping"""
    print("🗺️  CREATING BOOKMAKER MAPPING")
    print("=" * 70)
    
    # Get bookmakers from both sources
    print("\nFetching API-Football bookmakers...")
    api_football_books = get_all_api_football_bookmakers()
    
    print("Fetching The Odds API bookmakers...")
    theodds_books = get_existing_theodds_bookmakers()
    
    print(f"\n✅ API-Football: {len(api_football_books)} bookmakers")
    print(f"✅ The Odds API: {len(theodds_books)} bookmakers")
    
    # Normalize names for matching
    def normalize_name(name):
        return name.lower().replace(' ', '').replace('-', '').replace('_', '')
    
    # Create mapping
    mapping = []
    
    # Map by normalized name
    api_football_dict = {normalize_name(b['name']): b for b in api_football_books}
    theodds_dict = {normalize_name(b): b for b in theodds_books}
    
    # Find matches
    for norm_name, api_book in api_football_dict.items():
        if norm_name in theodds_dict:
            mapping.append({
                'rapidapi_id': api_book['id'],
                'rapidapi_name': api_book['name'],
                'theodds_id': theodds_dict[norm_name],
                'canonical_name': api_book['name'],
                'match_type': 'exact'
            })
    
    # API-Football only
    api_only = [b for b in api_football_books if normalize_name(b['name']) not in theodds_dict]
    
    # The Odds API only
    theodds_only = [b for b in theodds_books if normalize_name(b) not in api_football_dict]
    
    # Display mapping
    print(f"\n📊 MAPPING ANALYSIS:")
    print(f"  Exact matches: {len(mapping)}")
    print(f"  API-Football exclusive: {len(api_only)}")
    print(f"  The Odds API exclusive: {len(theodds_only)}")
    
    print(f"\n✅ MATCHED BOOKMAKERS ({len(mapping)}):")
    print(f"{'API-Football Name':<25} {'RapidAPI ID':<15} {'The Odds API ID':<20}")
    print("-" * 65)
    for m in sorted(mapping, key=lambda x: x['rapidapi_name']):
        print(f"{m['rapidapi_name']:<25} {m['rapidapi_id']:<15} {m['theodds_id']:<20}")
    
    print(f"\n🆕 API-FOOTBALL EXCLUSIVE ({len(api_only)}):")
    for book in sorted(api_only, key=lambda x: x['name'])[:15]:
        print(f"  • {book['name']} (ID: {book['id']})")
    if len(api_only) > 15:
        print(f"  ... and {len(api_only) - 15} more")
    
    print(f"\n🎯 THE ODDS API EXCLUSIVE ({len(theodds_only)}):")
    for book in sorted(theodds_only)[:15]:
        print(f"  • {book}")
    
    # Save to JSON file
    mapping_data = {
        'matched': mapping,
        'api_football_only': [{'id': b['id'], 'name': b['name']} for b in api_only],
        'theodds_only': theodds_only,
        'summary': {
            'total_api_football': len(api_football_books),
            'total_theodds': len(theodds_books),
            'matched': len(mapping),
            'overlap_percentage': len(mapping) / max(len(api_football_books), len(theodds_books)) * 100
        }
    }
    
    with open('bookmaker_mapping.json', 'w') as f:
        json.dump(mapping_data, f, indent=2)
    
    print(f"\n💾 Mapping saved to: bookmaker_mapping.json")
    
    # Create database table
    print(f"\n🗃️  Creating bookmaker_xwalk table in database...")
    if create_mapping_table():
        print("✅ Table created successfully")
        
        # Insert matched bookmakers
        try:
            conn = psycopg2.connect(DATABASE_URL)
            cursor = conn.cursor()
            
            for m in mapping:
                cursor.execute("""
                    INSERT INTO bookmaker_xwalk 
                    (rapidapi_book_id, rapidapi_book_name, theodds_book_id, canonical_name)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (rapidapi_book_id, theodds_book_id) DO NOTHING
                """, (m['rapidapi_id'], m['rapidapi_name'], m['theodds_id'], m['canonical_name']))
            
            conn.commit()
            cursor.close()
            conn.close()
            
            print(f"✅ Inserted {len(mapping)} bookmaker mappings")
        except Exception as e:
            print(f"❌ Error inserting mappings: {e}")
    
    return mapping_data

if __name__ == "__main__":
    mapping = create_bookmaker_mapping()
    
    print("\n" + "=" * 70)
    print("📋 RECOMMENDATIONS:")
    print("-" * 70)
    
    if mapping['summary']['matched'] >= 5:
        print("✅ Good overlap - Multi-source consensus is viable")
        print(f"   • {mapping['summary']['matched']} shared bookmakers can be cross-validated")
    
    if len(mapping['api_football_only']) > 10:
        print(f"✅ API-Football adds {len(mapping['api_football_only'])} new bookmakers")
        print("   • Increases diversity for CLV detection")
    
    print("\n💡 Next Steps:")
    print("   1. Use bookmaker_mapping.json for source attribution")
    print("   2. Add 'source' column to odds_snapshots table")
    print("   3. Implement gap-filling logic with API-Football")
    print()
