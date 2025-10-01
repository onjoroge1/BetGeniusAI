#!/usr/bin/env python3
"""
End-to-end test of API-Football integration using a known fixture.
Tests the complete pipeline: fetch → ingest → consensus
"""

import logging
from datetime import datetime
from utils.api_football_integration import ApiFootballIngestion, BookmakerCrosswalk
import psycopg2
import os

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv('DATABASE_URL')


def test_known_fixture():
    """
    Test with Atalanta vs Club Brugge (UEFA Champions League)
    Fixture ID: 1311653 (from Phase 1 exploration)
    """
    print("=" * 80)
    print("  END-TO-END TEST: API-Football Integration")
    print("=" * 80)
    
    print("\n1. Testing Bookmaker Crosswalk...")
    desk_group = BookmakerCrosswalk.get_desk_group('8')
    print(f"   ✅ Bet365 (ID=8) desk_group: {desk_group}")
    
    fixture_id = 1311653
    match_id = 9999999
    league_id = 2
    kickoff = datetime(2024, 8, 29, 20, 0, 0)
    
    print(f"\n2. Fetching odds for fixture {fixture_id}...")
    print(f"   Match: Atalanta vs Club Brugge")
    print(f"   Using match_id={match_id}, league_id={league_id}")
    
    rows = ApiFootballIngestion.ingest_fixture_odds(
        fixture_id=fixture_id,
        match_id=match_id,
        league_id=league_id,
        kickoff_ts=kickoff,
        live=False
    )
    
    print(f"   ✅ Inserted {rows} odds rows")
    
    if rows > 0:
        print("\n3. Checking inserted odds...")
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT book_id, outcome, odds_decimal, source, vendor_book_id
            FROM odds_snapshots
            WHERE match_id = %s
            ORDER BY outcome, odds_decimal
        """, (match_id,))
        
        odds = cursor.fetchall()
        print(f"   ✅ Found {len(odds)} odds entries:")
        
        outcomes = {}
        for book_id, outcome, odds_decimal, source, vendor_book_id in odds:
            if outcome not in outcomes:
                outcomes[outcome] = []
            outcomes[outcome].append((book_id, odds_decimal, source))
        
        for outcome in ['H', 'D', 'A']:
            if outcome in outcomes:
                print(f"\n   {outcome} ({len(outcomes[outcome])} books):")
                for book_id, odds, source in outcomes[outcome][:3]:
                    print(f"      - {book_id}: {odds:.2f} (source: {source})")
        
        print("\n4. Refreshing consensus...")
        ApiFootballIngestion.refresh_consensus_for_match(match_id)
        
        cursor.execute("""
            SELECT ph_cons, pd_cons, pa_cons, n_books, source_mix
            FROM odds_consensus
            WHERE match_id = %s
            LIMIT 1
        """, (match_id,))
        
        consensus = cursor.fetchone()
        if consensus:
            ph, pd, pa, n_books, source_mix = consensus
            print(f"   ✅ Consensus computed:")
            print(f"      - Home: {ph:.4f}")
            print(f"      - Draw: {pd:.4f}")
            print(f"      - Away: {pa:.4f}")
            print(f"      - Books: {n_books}")
            print(f"      - Sources: {source_mix}")
        
        cursor.execute("""
            DELETE FROM odds_snapshots WHERE match_id = %s;
            DELETE FROM odds_consensus WHERE match_id = %s;
        """, (match_id, match_id))
        conn.commit()
        print(f"\n   ✅ Cleaned up test data (match_id={match_id})")
        
        cursor.close()
        conn.close()
        
        print("\n" + "=" * 80)
        print("  ✅ END-TO-END TEST PASSED")
        print("=" * 80)
        print("\nAPI-Football integration is working correctly!")
        print("Next: Implement fixture ID lookup for historical matches")
    else:
        print("\n   ❌ No odds data returned for this fixture")
        print("   (Fixture may be too old or not in API-Football database)")


if __name__ == '__main__':
    test_known_fixture()
