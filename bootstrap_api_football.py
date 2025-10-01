#!/usr/bin/env python3
"""
API-Football Bootstrap Script
Validates the entire integration pipeline end-to-end.
"""

import os
import logging
from datetime import datetime
from utils.api_football_integration import BookmakerCrosswalk, ApiFootballIngestion
from utils.gap_fill_worker import GapFillWorker, create_backfill_progress_table
import psycopg2

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv('DATABASE_URL')


def print_section(title: str):
    """Print a formatted section header."""
    print(f"\n{'=' * 80}")
    print(f"  {title}")
    print('=' * 80)


def check_schema():
    """Verify database schema updates."""
    print_section("1. CHECKING DATABASE SCHEMA")
    
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT column_name, data_type, column_default
        FROM information_schema.columns
        WHERE table_name = 'odds_snapshots'
        AND column_name IN ('source', 'vendor_fixture_id', 'vendor_book_id')
        ORDER BY column_name
    """)
    
    columns = cursor.fetchall()
    print(f"✅ odds_snapshots enhanced columns:")
    for col in columns:
        print(f"   - {col[0]}: {col[1]} (default: {col[2]})")
    
    cursor.execute("""
        SELECT indexname FROM pg_indexes
        WHERE tablename = 'odds_snapshots'
        AND indexname LIKE 'idx_snapshots%'
    """)
    
    indexes = cursor.fetchall()
    print(f"\n✅ odds_snapshots indexes:")
    for idx in indexes:
        print(f"   - {idx[0]}")
    
    cursor.execute("""
        SELECT COUNT(*) FROM bookmaker_xwalk
    """)
    xwalk_count = cursor.fetchone()[0]
    print(f"\n✅ bookmaker_xwalk: {xwalk_count} rows")
    
    cursor.close()
    conn.close()


def seed_bookmakers():
    """Seed bookmaker crosswalk from API-Football."""
    print_section("2. SEEDING BOOKMAKER CROSSWALK")
    
    count = BookmakerCrosswalk.seed_from_api_football()
    print(f"✅ Seeded {count} bookmakers from API-Football")
    
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT canonical_name, api_football_book_id, desk_group
        FROM bookmaker_xwalk
        ORDER BY canonical_name
        LIMIT 10
    """)
    
    print("\nSample bookmakers:")
    for row in cursor.fetchall():
        print(f"   - {row[0]}: api_football_id={row[1]}, desk_group={row[2]}")
    
    cursor.close()
    conn.close()


def test_gap_detection():
    """Test gap detection for matches without odds."""
    print_section("3. TESTING GAP DETECTION")
    
    matches = GapFillWorker.find_matches_without_odds(
        time_window_hours=8760,
        historical=True,
        limit=20
    )
    
    print(f"✅ Found {len(matches)} matches with insufficient odds")
    
    if matches:
        print("\nSample matches needing odds:")
        for match_id, league_id, fixture_id, kickoff, n_books in matches[:5]:
            print(f"   - Match {match_id}: fixture={fixture_id}, "
                  f"kickoff={kickoff.strftime('%Y-%m-%d')}, current_books={n_books}")
        
        return matches[0]
    
    return None


def test_ingestion(sample_match):
    """Test odds ingestion for a sample match."""
    print_section("4. TESTING ODDS INGESTION")
    
    if not sample_match:
        print("⚠️  No sample match available for testing")
        return
    
    match_id, league_id, fixture_id, kickoff, n_books = sample_match
    
    print(f"Testing with match {match_id} (fixture {fixture_id})")
    print(f"Current odds books: {n_books}")
    
    rows_inserted = ApiFootballIngestion.ingest_fixture_odds(
        fixture_id=fixture_id,
        match_id=match_id,
        league_id=league_id,
        kickoff_ts=kickoff,
        live=False
    )
    
    if rows_inserted > 0:
        print(f"✅ Inserted {rows_inserted} odds rows from API-Football")
        
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT book_id, outcome, odds_decimal, source
            FROM odds_snapshots
            WHERE match_id = %s
            AND source = 'api_football'
            ORDER BY outcome, book_id
            LIMIT 10
        """, (match_id,))
        
        print("\nSample odds inserted:")
        for row in cursor.fetchall():
            print(f"   - {row[0]}: {row[1]} @ {row[2]} (source: {row[3]})")
        
        cursor.close()
        conn.close()
        
        ApiFootballIngestion.refresh_consensus_for_match(match_id)
        print(f"✅ Consensus refreshed for match {match_id}")
    else:
        print("⚠️  No odds data available for this fixture")


def check_consensus():
    """Check consensus calculation with multi-source data."""
    print_section("5. CHECKING CONSENSUS CALCULATION")
    
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT 
            oc.match_id,
            oc.outcome,
            oc.consensus_odds_decimal,
            oc.n_books,
            oc.source_mix
        FROM odds_consensus oc
        WHERE oc.source_mix IS NOT NULL
        AND oc.source_mix::text LIKE '%api_football%'
        LIMIT 5
    """)
    
    results = cursor.fetchall()
    
    if results:
        print(f"✅ Found {len(results)} consensus entries with API-Football data")
        print("\nSample consensus with multi-source:")
        for row in results:
            match_id, outcome, odds, n_books, source_mix = row
            print(f"   - Match {match_id} {outcome}: {odds:.2f} "
                  f"({n_books} books) | sources: {source_mix}")
    else:
        print("⚠️  No consensus entries with API-Football data yet")
    
    cursor.close()
    conn.close()


def run_pilot_backfill():
    """Run pilot backfill on 10 matches."""
    print_section("6. RUNNING PILOT BACKFILL (10 matches)")
    
    create_backfill_progress_table()
    
    stats = GapFillWorker.run_historical_backfill(batch_size=10)
    
    print(f"\n✅ Pilot backfill complete:")
    print(f"   - Fixtures filled: {stats['filled_fixtures']}")
    print(f"   - Total rows inserted: {stats['total_rows_inserted']}")
    print(f"   - Errors: {stats['errors']}")
    print(f"   - Already sufficient: {stats['already_sufficient']}")
    
    if stats['filled_fixtures'] > 0:
        hit_rate = stats['filled_fixtures'] / (stats['filled_fixtures'] + stats['errors']) * 100
        print(f"   - Hit rate: {hit_rate:.1f}%")


def summary_stats():
    """Print summary statistics."""
    print_section("7. SUMMARY STATISTICS")
    
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT 
            source,
            COUNT(DISTINCT match_id) as matches,
            COUNT(*) as total_rows,
            COUNT(DISTINCT book_id) as unique_books
        FROM odds_snapshots
        GROUP BY source
        ORDER BY source
    """)
    
    print("Odds snapshot coverage by source:")
    for row in cursor.fetchall():
        source, matches, total_rows, unique_books = row
        print(f"   - {source}: {matches} matches, {total_rows} rows, {unique_books} unique books")
    
    cursor.execute("""
        SELECT COUNT(*) FROM training_matches
        WHERE match_id IN (
            SELECT DISTINCT match_id FROM odds_snapshots WHERE source = 'api_football'
        )
    """)
    
    api_football_matches = cursor.fetchone()[0]
    
    cursor.execute("""
        SELECT COUNT(*) FROM training_matches
    """)
    
    total_matches = cursor.fetchone()[0]
    
    print(f"\n✅ API-Football coverage:")
    print(f"   - {api_football_matches} / {total_matches} training matches "
          f"({api_football_matches / total_matches * 100:.1f}%)")
    
    cursor.close()
    conn.close()


def main():
    """Run full bootstrap validation."""
    print_section("API-FOOTBALL INTEGRATION BOOTSTRAP")
    print("Validating end-to-end integration pipeline...")
    
    try:
        check_schema()
        seed_bookmakers()
        sample_match = test_gap_detection()
        test_ingestion(sample_match)
        check_consensus()
        run_pilot_backfill()
        summary_stats()
        
        print_section("✅ BOOTSTRAP COMPLETE")
        print("API-Football integration is operational!")
        print("\nNext steps:")
        print("  1. Monitor pilot backfill results")
        print("  2. Scale backfill to remaining matches")
        print("  3. Enable gap-fill worker in scheduler")
        
    except Exception as e:
        print(f"\n❌ Bootstrap failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == '__main__':
    exit(main())
