#!/usr/bin/env python3
"""
Populate Closing Odds Table
Aggregates clv_closing_feed samples into closing_odds table for odds_accuracy_evaluation view
"""

import os
import psycopg2
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple
import statistics

DATABASE_URL = os.environ.get('DATABASE_URL')

def compute_closing_odds_from_samples(match_id: int, outcome: str) -> Tuple[Optional[float], str, int]:
    """
    Compute closing odds for an outcome from clv_closing_feed samples
    Uses LAST5_VWAP or LAST_TICK method
    
    Returns:
        (closing_odds, method_used, num_samples)
    """
    try:
        with psycopg2.connect(DATABASE_URL) as conn:
            cursor = conn.cursor()
            
            # Get all samples for this match/outcome, ordered by time
            cursor.execute("""
                SELECT composite_odds_dec, volume, ts
                FROM clv_closing_feed
                WHERE match_id = %s AND outcome = %s
                ORDER BY ts DESC
                LIMIT 10
            """, (match_id, outcome))
            
            samples = cursor.fetchall()
            
            if not samples:
                return None, "NO_DATA", 0
            
            # Method 1: LAST5_VWAP (if we have volume and enough samples)
            if len(samples) >= 3:
                recent_5 = samples[:5]
                
                # Check if we have volume data
                has_volume = all(s[1] is not None and s[1] > 0 for s in recent_5)
                
                if has_volume:
                    # Volume-weighted average of last 5
                    total_vol = sum(float(s[1]) for s in recent_5)
                    weighted_sum = sum(float(s[0]) * float(s[1]) for s in recent_5)
                    closing_odds = weighted_sum / total_vol
                    return closing_odds, "LAST5_VWAP", len(recent_5)
                else:
                    # Simple average of last 5 (no volume)
                    odds_values = [float(s[0]) for s in recent_5]
                    closing_odds = statistics.mean(odds_values)
                    return closing_odds, "LAST5_AVG", len(recent_5)
            
            # Method 2: LAST_TICK (only 1-2 samples)
            closing_odds = float(samples[0][0])
            return closing_odds, "LAST_TICK", 1
            
    except Exception as e:
        print(f"❌ Error computing closing odds for match {match_id} outcome {outcome}: {e}")
        return None, "ERROR", 0

def populate_closing_odds_for_match(match_id: int) -> bool:
    """
    Populate closing odds for a specific match from clv_closing_feed samples
    """
    try:
        # Compute closing odds for each outcome
        h_close, h_method, h_samples = compute_closing_odds_from_samples(match_id, 'H')
        d_close, d_method, d_samples = compute_closing_odds_from_samples(match_id, 'D')
        a_close, a_method, a_samples = compute_closing_odds_from_samples(match_id, 'A')
        
        if not h_close and not d_close and not a_close:
            print(f"  ⏭️  No closing data for match {match_id}")
            return False
        
        # Get latest timestamp from samples
        with psycopg2.connect(DATABASE_URL) as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT MAX(ts) FROM clv_closing_feed WHERE match_id = %s
            """, (match_id,))
            
            result = cursor.fetchone()
            closing_time = result[0] if result else None
            
            # Calculate average books used
            cursor.execute("""
                SELECT AVG(books_used) FROM clv_closing_feed WHERE match_id = %s
            """, (match_id,))
            
            result = cursor.fetchone()
            avg_books = result[0] if result else 0
            avg_books = int(avg_books) if avg_books else 0
            
            # Insert or update closing_odds
            cursor.execute("""
                INSERT INTO closing_odds (
                    match_id, h_close_odds, d_close_odds, a_close_odds,
                    closing_time, avg_books_closing, method_used, samples_used
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (match_id) DO UPDATE SET
                    h_close_odds = EXCLUDED.h_close_odds,
                    d_close_odds = EXCLUDED.d_close_odds,
                    a_close_odds = EXCLUDED.a_close_odds,
                    closing_time = EXCLUDED.closing_time,
                    avg_books_closing = EXCLUDED.avg_books_closing,
                    method_used = EXCLUDED.method_used,
                    samples_used = EXCLUDED.samples_used,
                    created_at = NOW()
            """, (
                match_id, h_close, d_close, a_close,
                closing_time, avg_books, 
                f"{h_method}/{d_method}/{a_method}",
                h_samples + d_samples + a_samples
            ))
            
            conn.commit()
            
            print(f"  ✅ Match {match_id}: H={h_close:.3f} D={d_close:.3f} A={a_close:.3f} ({h_method})")
            return True
            
    except Exception as e:
        print(f"  ❌ Error populating closing odds for match {match_id}: {e}")
        return False

def populate_all_closing_odds():
    """
    Populate closing odds for all matches with clv_closing_feed samples
    """
    print("🔄 POPULATE CLOSING ODDS TABLE")
    print("=" * 60)
    
    try:
        with psycopg2.connect(DATABASE_URL) as conn:
            cursor = conn.cursor()
            
            # Get all matches with closing samples
            cursor.execute("""
                SELECT DISTINCT match_id
                FROM clv_closing_feed
                ORDER BY match_id
            """)
            
            match_ids = [row[0] for row in cursor.fetchall()]
            
            if not match_ids:
                print("\n⚠️  No closing feed data found!")
                print("\nℹ️  Closing odds are collected automatically when:")
                print("   • Matches are approaching kickoff (T-6m to T+2m window)")
                print("   • CLV closing sampler is running (every 60 seconds)")
                print("   • Upcoming matches exist in odds_snapshots")
                return
            
            print(f"\n📊 Found {len(match_ids)} matches with closing samples")
            print(f"⏳ Processing...\n")
            
            success_count = 0
            for match_id in match_ids:
                if populate_closing_odds_for_match(match_id):
                    success_count += 1
            
            print(f"\n{'=' * 60}")
            print(f"✅ Complete! Populated closing odds for {success_count}/{len(match_ids)} matches")
            print(f"\n💡 Test the enhanced metrics with closing odds:")
            print(f"   curl 'http://localhost:8000/metrics/evaluation?window=all' \\")
            print(f"        -H 'Authorization: Bearer betgenius_secure_key_2024'")
            
    except Exception as e:
        print(f"\n❌ Error: {e}")

if __name__ == "__main__":
    populate_all_closing_odds()
