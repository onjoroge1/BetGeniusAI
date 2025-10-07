#!/usr/bin/env python3
"""
Backfill matches table from odds_snapshots
Addresses root cause: AutomatedCollector doesn't populate matches table
"""

import os
import psycopg2
from datetime import datetime

DATABASE_URL = os.environ.get('DATABASE_URL')

def backfill_matches():
    """
    Populate matches table with match_ids from odds_snapshots
    Creates minimal match records so closing sampler can join successfully
    """
    
    with psycopg2.connect(DATABASE_URL) as conn:
        cursor = conn.cursor()
        
        print("🔍 Analyzing odds_snapshots...")
        
        cursor.execute("""
            SELECT 
                COUNT(DISTINCT match_id) as unique_matches,
                MIN(ts_snapshot) as earliest_odds,
                MAX(ts_snapshot) as latest_odds
            FROM odds_snapshots
        """)
        
        unique_matches, earliest, latest = cursor.fetchone()
        print(f"   Found {unique_matches} unique match_ids in odds_snapshots")
        print(f"   Date range: {earliest} to {latest}")
        
        cursor.execute("SELECT COUNT(*) FROM matches")
        existing_count = cursor.fetchone()[0]
        print(f"   Existing matches in matches table: {existing_count}")
        
        print("\n📊 Extracting match metadata from odds_snapshots...")
        
        cursor.execute("""
            WITH match_meta AS (
                SELECT DISTINCT ON (match_id)
                    match_id,
                    league_id,
                    ts_snapshot,
                    secs_to_kickoff
                FROM odds_snapshots
                ORDER BY match_id, ts_snapshot DESC
            ),
            kickoff_calc AS (
                SELECT 
                    match_id,
                    league_id,
                    ts_snapshot + (secs_to_kickoff || ' seconds')::interval as estimated_kickoff
                FROM match_meta
            )
            SELECT 
                match_id,
                league_id,
                estimated_kickoff
            FROM kickoff_calc
            WHERE match_id NOT IN (SELECT match_id FROM matches)
            ORDER BY estimated_kickoff DESC
        """)
        
        new_matches = cursor.fetchall()
        print(f"   Found {len(new_matches)} new matches to insert")
        
        if not new_matches:
            print("\n✅ No new matches to backfill")
            return
        
        print("\n💾 Inserting matches into matches table...")
        
        inserted = 0
        errors = 0
        
        for match_id, league_id, kickoff_time in new_matches:
            try:
                cursor.execute("""
                    INSERT INTO matches 
                    (match_id, league_id, match_date_utc, season)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (match_id) DO NOTHING
                """, (match_id, league_id, kickoff_time, 2024))
                
                if cursor.rowcount > 0:
                    inserted += 1
                    if inserted % 50 == 0:
                        print(f"   Inserted {inserted} matches...")
                        
            except Exception as e:
                errors += 1
                if errors <= 5:
                    print(f"   Error inserting match {match_id}: {e}")
        
        conn.commit()
        
        print(f"\n✅ Backfill complete!")
        print(f"   Inserted: {inserted} matches")
        print(f"   Errors: {errors}")
        
        cursor.execute("SELECT COUNT(*) FROM matches")
        final_count = cursor.fetchone()[0]
        print(f"   Total matches in table: {final_count}")
        
        cursor.execute("""
            SELECT COUNT(*)
            FROM matches m
            INNER JOIN odds_snapshots os ON m.match_id = os.match_id
        """)
        
        joinable = cursor.fetchone()[0]
        print(f"   Matches with odds (joinable): {joinable}")
        
        cursor.execute("""
            SELECT COUNT(DISTINCT m.match_id)
            FROM matches m
            INNER JOIN odds_snapshots os ON m.match_id = os.match_id
            WHERE m.match_date_utc > NOW() - INTERVAL '10 minutes'
              AND m.match_date_utc < NOW() + INTERVAL '10 minutes'
        """)
        
        near_kickoff = cursor.fetchone()[0]
        print(f"   Matches near kickoff (±10 min): {near_kickoff}")
        
        if near_kickoff > 0:
            print("\n🎯 Closing sampler should now find matches!")
        else:
            print("\n⚠️  No matches currently near kickoff")
            print("   Closing sampler will activate when matches approach kickoff time")

if __name__ == "__main__":
    print("="*60)
    print("BACKFILL MATCHES FROM ODDS_SNAPSHOTS")
    print("="*60)
    backfill_matches()
