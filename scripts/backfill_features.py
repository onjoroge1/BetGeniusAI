#!/usr/bin/env python3
"""
Backfill match_features table with training data from odds_consensus.
This populates features for all historical training matches to enable
better V2 model training.
"""

import os
import psycopg2
from datetime import datetime

def backfill_features():
    """Backfill match_features from training_matches + odds_consensus"""
    
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise ValueError("DATABASE_URL not set")
    
    conn = psycopg2.connect(db_url)
    cur = conn.cursor()
    
    print("🔍 Checking current feature coverage...")
    cur.execute("""
        SELECT 
            COUNT(DISTINCT tm.match_id) as total_training,
            COUNT(DISTINCT oc.match_id) as with_odds,
            COUNT(DISTINCT mf.match_id) as with_features
        FROM training_matches tm
        LEFT JOIN odds_consensus oc ON tm.match_id = oc.match_id
        LEFT JOIN match_features mf ON tm.match_id = mf.match_id
        WHERE tm.outcome IS NOT NULL
    """)
    total, with_odds, with_features = cur.fetchone()
    print(f"   Total training matches: {total:,}")
    print(f"   With odds consensus: {with_odds:,}")
    print(f"   Already have features: {with_features:,}")
    print(f"   🎯 Can backfill: {with_odds - with_features:,} matches\n")
    
    if with_odds <= with_features:
        print("✅ All available matches already have features!")
        cur.close()
        conn.close()
        return
    
    print("📊 Backfilling match_features from odds_consensus...")
    
    # Insert features for matches that have odds but no features yet
    cur.execute("""
        INSERT INTO match_features (
            match_id,
            league_id,
            kickoff_timestamp,
            prob_home,
            prob_draw,
            prob_away,
            overround,
            book_dispersion,
            drift_24h_home,
            drift_24h_draw,
            drift_24h_away,
            feature_version,
            created_at,
            updated_at
        )
        SELECT 
            tm.match_id,
            COALESCE(tm.league_id, oc.league_id) as league_id,
            COALESCE(tm.match_date, oc.ts_effective)::timestamptz as kickoff_timestamp,
            oc.ph_cons as prob_home,
            oc.pd_cons as prob_draw,
            oc.pa_cons as prob_away,
            COALESCE(oc.market_margin_avg, 0.065) as overround,
            COALESCE((oc.disph + oc.dispd + oc.dispa) / 3.0, 0.018) as book_dispersion,
            0.0 as drift_24h_home,  -- Historical data: no drift available
            0.0 as drift_24h_draw,
            0.0 as drift_24h_away,
            'backfill_v2' as feature_version,
            NOW() as created_at,
            NOW() as updated_at
        FROM training_matches tm
        INNER JOIN odds_consensus oc ON tm.match_id = oc.match_id
        LEFT JOIN match_features mf ON tm.match_id = mf.match_id
        WHERE tm.outcome IS NOT NULL
          AND mf.match_id IS NULL  -- Only insert if not already present
        ON CONFLICT (match_id) DO NOTHING;
    """)
    
    inserted = cur.rowcount
    conn.commit()
    
    print(f"✅ Backfilled {inserted:,} match features!\n")
    
    # Final stats
    cur.execute("""
        SELECT 
            COUNT(*) as trainable_matches,
            MIN(tm.match_date) as earliest,
            MAX(tm.match_date) as latest,
            COUNT(CASE WHEN tm.outcome = 'H' THEN 1 END) as home_wins,
            COUNT(CASE WHEN tm.outcome = 'D' THEN 1 END) as draws,
            COUNT(CASE WHEN tm.outcome = 'A' THEN 1 END) as away_wins
        FROM match_features mf
        INNER JOIN training_matches tm ON mf.match_id = tm.match_id
        WHERE tm.outcome IS NOT NULL
    """)
    total, earliest, latest, h, d, a = cur.fetchone()
    
    print("📈 Final Training Dataset:")
    print(f"   Total trainable matches: {total:,}")
    print(f"   Date range: {earliest} → {latest}")
    print(f"   Outcome distribution:")
    print(f"      Home wins: {h:,} ({100*h/total:.1f}%)")
    print(f"      Draws: {d:,} ({100*d/total:.1f}%)")
    print(f"      Away wins: {a:,} ({100*a/total:.1f}%)")
    
    cur.close()
    conn.close()
    
    print("\n✅ Backfill complete! Ready for V2 retraining 🚀")

if __name__ == "__main__":
    backfill_features()
