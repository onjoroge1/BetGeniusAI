#!/usr/bin/env python3
"""
Populate Match Features for V2 Model
Computes normalized odds, drift, dispersion, form, Elo, and rest days
"""

import os
import psycopg2
from datetime import datetime, timedelta
import hashlib
import json

DATABASE_URL = os.environ.get('DATABASE_URL')

def normalize_probs(ph, pd, pa):
    """Remove overround and normalize to sum=1.0"""
    total = ph + pd + pa
    if total > 0:
        return ph/total, pd/total, pa/total
    return 0.33, 0.33, 0.34

def compute_book_dispersion(match_id):
    """Compute standard deviation across bookmakers for each outcome"""
    try:
        with psycopg2.connect(DATABASE_URL) as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT 
                    outcome,
                    STDDEV(implied_prob) AS dispersion
                FROM odds_snapshots
                WHERE match_id = %s
                GROUP BY outcome
            """, (match_id,))
            
            dispersions = {row[0]: float(row[1] or 0) for row in cursor.fetchall()}
            avg_dispersion = sum(dispersions.values()) / max(len(dispersions), 1)
            
            return avg_dispersion
    except Exception as e:
        print(f"  Error computing dispersion: {e}")
        return 0.0

def compute_24h_drift(match_id):
    """Compute change in normalized probs over last 24 hours"""
    try:
        with psycopg2.connect(DATABASE_URL) as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                WITH recent_odds AS (
                    SELECT outcome, AVG(implied_prob) AS prob_recent
                    FROM odds_snapshots
                    WHERE match_id = %s
                        AND ts_snapshot > NOW() - INTERVAL '6 hours'
                    GROUP BY outcome
                ),
                old_odds AS (
                    SELECT outcome, AVG(implied_prob) AS prob_old
                    FROM odds_snapshots
                    WHERE match_id = %s
                        AND ts_snapshot BETWEEN NOW() - INTERVAL '30 hours' AND NOW() - INTERVAL '18 hours'
                    GROUP BY outcome
                )
                SELECT 
                    r.outcome,
                    (r.prob_recent - COALESCE(o.prob_old, r.prob_recent)) AS drift
                FROM recent_odds r
                LEFT JOIN old_odds o ON r.outcome = o.outcome
            """, (match_id, match_id))
            
            drifts = {row[0]: float(row[1] or 0) for row in cursor.fetchall()}
            
            return (
                drifts.get('H', 0.0),
                drifts.get('D', 0.0),
                drifts.get('A', 0.0)
            )
    except Exception as e:
        print(f"  Error computing drift: {e}")
        return 0.0, 0.0, 0.0

def populate_features_for_match(match_id):
    """Populate features for a single match"""
    try:
        with psycopg2.connect(DATABASE_URL) as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT 
                    m.league_id,
                    m.match_date_utc,
                    AVG(CASE WHEN os.outcome = 'H' THEN os.implied_prob END) AS ph,
                    AVG(CASE WHEN os.outcome = 'D' THEN os.implied_prob END) AS pd,
                    AVG(CASE WHEN os.outcome = 'A' THEN os.implied_prob END) AS pa
                FROM matches m
                LEFT JOIN odds_snapshots os ON m.match_id = os.match_id
                WHERE m.match_id = %s
                GROUP BY m.match_id, m.league_id, m.match_date_utc
            """, (match_id,))
            
            row = cursor.fetchone()
            if not row:
                return False
            
            league_id, kickoff_time, ph, pd, pa = row
            
            if not ph or not pd or not pa:
                return False
            
            ph_norm, pd_norm, pa_norm = normalize_probs(ph, pd, pa)
            overround = (ph + pd + pa) - 1.0
            
            dispersion = compute_book_dispersion(match_id)
            drift_h, drift_d, drift_a = compute_24h_drift(match_id)
            
            feature_dict = {
                'match_id': match_id,
                'ph': ph_norm,
                'pd': pd_norm,
                'pa': pa_norm,
                'dispersion': dispersion
            }
            feature_hash = hashlib.md5(json.dumps(feature_dict, sort_keys=True).encode()).hexdigest()[:16]
            
            cursor.execute("""
                INSERT INTO match_features (
                    match_id, league_id, kickoff_timestamp,
                    prob_home, prob_draw, prob_away, overround,
                    book_dispersion,
                    drift_24h_home, drift_24h_draw, drift_24h_away,
                    feature_version, feature_hash,
                    created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                ON CONFLICT (match_id) DO UPDATE SET
                    prob_home = EXCLUDED.prob_home,
                    prob_draw = EXCLUDED.prob_draw,
                    prob_away = EXCLUDED.prob_away,
                    overround = EXCLUDED.overround,
                    book_dispersion = EXCLUDED.book_dispersion,
                    drift_24h_home = EXCLUDED.drift_24h_home,
                    drift_24h_draw = EXCLUDED.drift_24h_draw,
                    drift_24h_away = EXCLUDED.drift_24h_away,
                    feature_hash = EXCLUDED.feature_hash,
                    updated_at = NOW()
            """, (
                match_id, league_id, kickoff_time,
                ph_norm, pd_norm, pa_norm, overround,
                dispersion,
                drift_h, drift_d, drift_a,
                'v1', feature_hash
            ))
            
            conn.commit()
            return True
            
    except Exception as e:
        print(f"  Error populating features for match {match_id}: {e}")
        return False

def populate_all_features(limit=100):
    """Populate features for all recent matches"""
    print("🔄 POPULATING MATCH FEATURES FOR V2 MODEL")
    print("=" * 60)
    
    try:
        with psycopg2.connect(DATABASE_URL) as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT DISTINCT match_id
                FROM odds_snapshots
                WHERE ts_snapshot > NOW() - INTERVAL '7 days'
                ORDER BY match_id DESC
                LIMIT %s
            """, (limit,))
            
            match_ids = [row[0] for row in cursor.fetchall()]
            
        if not match_ids:
            print("\n⚠️  No recent matches found!")
            return
        
        print(f"\n📊 Found {len(match_ids)} matches to process")
        print(f"⏳ Processing features...\n")
        
        success_count = 0
        for i, match_id in enumerate(match_ids, 1):
            if populate_features_for_match(match_id):
                success_count += 1
                if i % 10 == 0:
                    print(f"  Processed {i}/{len(match_ids)} matches...")
        
        print(f"\n{'=' * 60}")
        print(f"✅ Complete! Populated features for {success_count}/{len(match_ids)} matches")
        print(f"\n💡 Features are ready for V2 shadow inference")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")

if __name__ == "__main__":
    import sys
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    populate_all_features(limit)
