#!/usr/bin/env python3
"""
Consensus Backfill Script
========================

Backfills consensus_predictions table for historical matches that have
odds_snapshots but no consensus predictions yet.

This script uses the same bucket classification logic as the scheduler
to ensure consistency.
"""

import os
import sys
import psycopg2
from datetime import datetime

def get_db_connection():
    """Get database connection"""
    return psycopg2.connect(os.environ['DATABASE_URL'])

def find_backfill_candidates(days_back=30, min_books=2):
    """Find matches that need consensus backfilling"""
    
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT 
                    os.match_id,
                    COUNT(DISTINCT os.book_id) as unique_books,
                    COUNT(*) as odds_entries,
                    MIN(os.secs_to_kickoff/3600.0) as min_hours_ahead,
                    MAX(os.secs_to_kickoff/3600.0) as max_hours_ahead,
                    MAX(os.ts_snapshot) as latest_snapshot
                FROM odds_snapshots os
                LEFT JOIN consensus_predictions cp ON os.match_id = cp.match_id
                WHERE cp.match_id IS NULL
                  AND os.ts_snapshot > NOW() - INTERVAL '%s days'
                  AND os.outcome IN ('home', 'draw', 'away')
                GROUP BY os.match_id
                HAVING COUNT(DISTINCT os.book_id) >= %s
                ORDER BY latest_snapshot DESC
            """, (days_back, min_books))
            
            candidates = cursor.fetchall()
            return candidates

def build_consensus_for_match(match_id):
    """Build consensus predictions for a specific match using scheduler logic"""
    
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            # Use the same SQL as the scheduler with aligned bucket ranges
            cursor.execute("""
                INSERT INTO consensus_predictions 
                (match_id, time_bucket, consensus_h, consensus_d, consensus_a, 
                 dispersion_h, dispersion_d, dispersion_a, n_books, created_at)
                WITH match_odds AS (
                    SELECT book_id, outcome, implied_prob, secs_to_kickoff
                    FROM odds_snapshots 
                    WHERE match_id = %s
                ),
                complete_books AS (
                    SELECT book_id FROM match_odds
                    GROUP BY book_id HAVING COUNT(DISTINCT outcome) = 3
                ),
                clean_odds AS (
                    SELECT mo.* FROM match_odds mo 
                    JOIN complete_books cb ON mo.book_id = cb.book_id
                ),
                bucket_classified AS (
                    SELECT *,
                        CASE 
                            WHEN secs_to_kickoff BETWEEN 5400 AND 32400 THEN '6h'    -- 1.5-9h (consensus_builder compatible)
                            WHEN secs_to_kickoff BETWEEN 21600 AND 64800 THEN '12h'  -- 6-18h (consensus_builder compatible)  
                            WHEN secs_to_kickoff BETWEEN 64800 AND 108000 THEN '24h' -- 18-30h (consensus_builder compatible)
                            WHEN secs_to_kickoff BETWEEN 129600 AND 216000 THEN '48h'-- 36-60h (consensus_builder compatible)
                            WHEN secs_to_kickoff BETWEEN 216000 AND 302400 THEN '72h'-- 60-84h (consensus_builder compatible)
                            WHEN secs_to_kickoff BETWEEN 900 AND 5400 THEN '3h'      -- 0.25-1.5h (consensus_builder compatible)
                            ELSE 'other'
                        END as time_bucket
                    FROM clean_odds
                    WHERE secs_to_kickoff > 900  -- at least 15 minutes before kickoff
                ),
                consensus_calc AS (
                    SELECT 
                        time_bucket,
                        AVG(CASE WHEN outcome = 'home' THEN implied_prob END) as consensus_h,
                        AVG(CASE WHEN outcome = 'draw' THEN implied_prob END) as consensus_d,
                        AVG(CASE WHEN outcome = 'away' THEN implied_prob END) as consensus_a,
                        STDDEV(CASE WHEN outcome = 'home' THEN implied_prob END) as dispersion_h,
                        STDDEV(CASE WHEN outcome = 'draw' THEN implied_prob END) as dispersion_d,
                        STDDEV(CASE WHEN outcome = 'away' THEN implied_prob END) as dispersion_a,
                        COUNT(DISTINCT book_id) as n_books
                    FROM bucket_classified
                    GROUP BY time_bucket
                    HAVING COUNT(DISTINCT book_id) >= 2
                )
                SELECT %s, time_bucket, consensus_h, consensus_d, consensus_a,
                       COALESCE(dispersion_h, 0), COALESCE(dispersion_d, 0), COALESCE(dispersion_a, 0),
                       n_books, NOW()
                FROM consensus_calc
                ON CONFLICT (match_id, time_bucket) DO NOTHING
            """, (match_id, match_id))
            
            rows_inserted = cursor.rowcount
            conn.commit()
            return rows_inserted

def main():
    """Main backfill execution"""
    
    print("🔄 Consensus Backfill Script")
    print("=" * 40)
    
    # Find candidates
    print("🔍 Finding backfill candidates...")
    candidates = find_backfill_candidates(days_back=30, min_books=2)
    
    if not candidates:
        print("✅ No matches need backfilling!")
        return
    
    print(f"📊 Found {len(candidates)} matches needing consensus backfill")
    
    # Show sample
    print("\n📋 Sample candidates:")
    for i, (match_id, books, odds, min_h, max_h, snapshot) in enumerate(candidates[:5]):
        print(f"  {i+1}. Match {match_id}: {books} books, {odds} odds, {min_h:.1f}-{max_h:.1f}h ahead")
    
    if len(candidates) > 5:
        print(f"  ... and {len(candidates) - 5} more")
    
    # Confirm backfill
    response = input(f"\n🤔 Backfill consensus for {len(candidates)} matches? (y/N): ")
    if response.lower() != 'y':
        print("❌ Backfill cancelled")
        return
    
    # Execute backfill
    print(f"\n🚀 Starting backfill for {len(candidates)} matches...")
    
    success_count = 0
    failure_count = 0
    consensus_rows_created = 0
    
    for i, (match_id, books, odds, min_h, max_h, snapshot) in enumerate(candidates):
        try:
            rows_created = build_consensus_for_match(match_id)
            if rows_created > 0:
                success_count += 1
                consensus_rows_created += rows_created
                print(f"  ✅ Match {match_id}: {rows_created} consensus rows created")
            else:
                print(f"  ⚠️ Match {match_id}: No consensus rows created (bucket/books issue)")
                failure_count += 1
            
        except Exception as e:
            print(f"  ❌ Match {match_id}: ERROR - {e}")
            failure_count += 1
    
    # Summary
    print(f"\n📊 Backfill Results:")
    print(f"  ✅ Successful: {success_count} matches")
    print(f"  ❌ Failed: {failure_count} matches") 
    print(f"  📈 Consensus rows created: {consensus_rows_created}")
    print(f"  ⏱️ Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

if __name__ == "__main__":
    main()