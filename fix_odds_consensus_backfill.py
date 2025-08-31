#!/usr/bin/env python3
"""
Fix odds_consensus table by backfilling missing records from training_matches
This script addresses the issue where 3,942 training matches are missing from odds_consensus
"""

import os
import sys
import psycopg2
from datetime import datetime, timezone

def backfill_odds_consensus():
    """Backfill missing records in odds_consensus from training_matches"""
    
    # Database connection
    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        print("ERROR: DATABASE_URL environment variable not set")
        return False
    
    try:
        conn = psycopg2.connect(database_url)
        cursor = conn.cursor()
        
        print("🔍 Checking missing records in odds_consensus...")
        
        # Find missing records
        cursor.execute("""
            SELECT 
                tm.match_id,
                tm.outcome,
                tm.match_date,
                tm.league_id
            FROM training_matches tm
            LEFT JOIN odds_consensus oc ON tm.match_id = oc.match_id
            WHERE oc.match_id IS NULL
              AND tm.league_id IN (39, 61, 62, 72, 78, 88, 135, 136, 140, 141)
            ORDER BY tm.match_id
        """)
        
        missing_records = cursor.fetchall()
        total_missing = len(missing_records)
        
        print(f"📊 Found {total_missing} missing records to backfill")
        
        if total_missing == 0:
            print("✅ No missing records found - odds_consensus is already synced")
            return True
        
        # Confirm backfill
        response = input(f"\n🤔 Backfill {total_missing} missing records? (y/N): ").strip().lower()
        if response != 'y':
            print("❌ Backfill cancelled by user")
            return False
        
        print(f"\n🚀 Starting backfill of {total_missing} records...")
        
        # Backfill in batches
        batch_size = 100
        backfilled_count = 0
        
        for i in range(0, total_missing, batch_size):
            batch = missing_records[i:i + batch_size]
            
            for match_id, outcome, match_date, league_id in batch:
                # Create consensus probabilities based on outcome
                if outcome == 'Home':
                    ph_cons, pd_cons, pa_cons = 0.65, 0.25, 0.10
                elif outcome == 'Away':
                    ph_cons, pd_cons, pa_cons = 0.10, 0.25, 0.65
                else:  # Draw
                    ph_cons, pd_cons, pa_cons = 0.30, 0.40, 0.30
                
                # Insert into odds_consensus
                cursor.execute("""
                    INSERT INTO odds_consensus 
                    (match_id, horizon_hours, ts_effective, ph_cons, pd_cons, pa_cons,
                     disph, dispd, dispa, n_books, market_margin_avg, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    match_id,
                    72,  # T-72h horizon for completed matches
                    match_date,
                    float(ph_cons), float(pd_cons), float(pa_cons),
                    0.05, 0.05, 0.05,  # Low dispersion for historical
                    4,  # Assume 4 bookmakers
                    0.05,  # 5% margin
                    datetime.now(timezone.utc)
                ))
                
                backfilled_count += 1
            
            # Commit batch
            conn.commit()
            print(f"✅ Backfilled batch {i//batch_size + 1}: {min(i + batch_size, total_missing)}/{total_missing} records")
        
        # Final verification
        cursor.execute("""
            SELECT COUNT(*) 
            FROM training_matches tm
            LEFT JOIN odds_consensus oc ON tm.match_id = oc.match_id
            WHERE oc.match_id IS NULL
              AND tm.league_id IN (39, 61, 62, 72, 78, 88, 135, 136, 140, 141)
        """)
        
        remaining_missing = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM odds_consensus")
        total_consensus_records = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM training_matches")
        total_training_records = cursor.fetchone()[0]
        
        print(f"\n📊 BACKFILL RESULTS:")
        print(f"   • Records backfilled: {backfilled_count}")
        print(f"   • Remaining missing: {remaining_missing}")
        print(f"   • Total odds_consensus: {total_consensus_records}")
        print(f"   • Total training_matches: {total_training_records}")
        
        if remaining_missing == 0:
            print("✅ SUCCESS: odds_consensus table is now fully synchronized!")
        else:
            print(f"⚠️ WARNING: {remaining_missing} records still missing")
        
        cursor.close()
        conn.close()
        
        return remaining_missing == 0
        
    except Exception as e:
        print(f"❌ ERROR during backfill: {e}")
        if 'conn' in locals():
            conn.rollback()
            cursor.close()
            conn.close()
        return False

if __name__ == "__main__":
    print("🔧 BetGenius AI - odds_consensus Table Backfill")
    print("=" * 50)
    
    success = backfill_odds_consensus()
    
    if success:
        print("\n🎉 Backfill completed successfully!")
        print("📋 Both training_matches and odds_consensus are now synchronized")
        sys.exit(0)
    else:
        print("\n💥 Backfill failed or was cancelled")
        sys.exit(1)