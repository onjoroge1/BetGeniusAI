#!/usr/bin/env python3
"""
Backfill match_context_v2 for ALL training matches

This script populates match_context_v2 for historical training data,
ensuring we have clean context features for model training.
"""
import os
import psycopg2
from datetime import datetime

DATABASE_URL = os.environ.get('DATABASE_URL')

def backfill_training_matches():
    """Build context for all training matches that need it"""
    
    print("📚 Starting historical backfill for training_matches...")
    print("=" * 80)
    
    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor() as cursor:
            # Check current coverage
            cursor.execute("""
                SELECT 
                    COUNT(DISTINCT tm.match_id) as total,
                    COUNT(DISTINCT mc.match_id) as with_context
                FROM training_matches tm
                LEFT JOIN match_context_v2 mc ON tm.match_id = mc.match_id
                WHERE tm.match_date >= '2020-01-01'
                  AND tm.outcome IN ('Home','Draw','Away')
            """)
            total, with_context = cursor.fetchone()
            missing = total - with_context
            
            print(f"Training matches (2020+): {total:,}")
            print(f"With context_v2: {with_context:,}")
            print(f"Missing context: {missing:,}")
            print()
            
            if missing == 0:
                print("✅ All training matches already have context!")
                return 0
            
            print(f"🔨 Building context for {missing:,} training matches...")
            print("   This may take 5-10 minutes...")
            print()
            
            # Build context using ONLY past matches (leak-free)
            cursor.execute("""
                WITH base AS (
                    SELECT
                        m.match_id,
                        m.home_team_id,
                        m.away_team_id,
                        m.match_date,
                        (m.match_date - INTERVAL '1 hour') AS as_of_time
                    FROM training_matches m
                    LEFT JOIN match_context_v2 mc ON m.match_id = mc.match_id
                    WHERE mc.match_id IS NULL  -- Only matches without context
                      AND m.match_date >= '2020-01-01'
                      AND m.outcome IN ('Home','Draw','Away')
                      AND m.home_team_id IS NOT NULL
                      AND m.away_team_id IS NOT NULL
                ),
                rest_days AS (
                    SELECT
                        base.match_id,
                        
                        -- Rest days for home team (days since last match)
                        COALESCE(
                            EXTRACT(EPOCH FROM (base.as_of_time - MAX(
                                CASE WHEN m2.home_team_id = base.home_team_id OR m2.away_team_id = base.home_team_id
                                THEN m2.match_date END
                            ))) / 86400.0,
                            14.0
                        ) AS rest_days_home,
                        
                        -- Rest days for away team
                        COALESCE(
                            EXTRACT(EPOCH FROM (base.as_of_time - MAX(
                                CASE WHEN m2.home_team_id = base.away_team_id OR m2.away_team_id = base.away_team_id
                                THEN m2.match_date END
                            ))) / 86400.0,
                            14.0
                        ) AS rest_days_away
                    FROM base
                    LEFT JOIN training_matches m2 ON (
                        (m2.home_team_id = base.home_team_id OR m2.away_team_id = base.home_team_id OR
                         m2.home_team_id = base.away_team_id OR m2.away_team_id = base.away_team_id)
                        AND m2.match_date < base.as_of_time
                    )
                    GROUP BY base.match_id, base.as_of_time
                ),
                congestion AS (
                    SELECT
                        base.match_id,
                        
                        -- Home team: matches in last 3/7 days
                        COUNT(DISTINCT CASE 
                            WHEN (m3.home_team_id = base.home_team_id OR m3.away_team_id = base.home_team_id)
                                 AND m3.match_date >= base.as_of_time - INTERVAL '3 days'
                                 AND m3.match_date < base.as_of_time
                            THEN m3.match_id END
                        ) AS matches_home_last_3d,
                        
                        COUNT(DISTINCT CASE 
                            WHEN (m3.home_team_id = base.home_team_id OR m3.away_team_id = base.home_team_id)
                                 AND m3.match_date >= base.as_of_time - INTERVAL '7 days'
                                 AND m3.match_date < base.as_of_time
                            THEN m3.match_id END
                        ) AS matches_home_last_7d,
                        
                        -- Away team: matches in last 3/7 days
                        COUNT(DISTINCT CASE 
                            WHEN (m3.home_team_id = base.away_team_id OR m3.away_team_id = base.away_team_id)
                                 AND m3.match_date >= base.as_of_time - INTERVAL '3 days'
                                 AND m3.match_date < base.as_of_time
                            THEN m3.match_id END
                        ) AS matches_away_last_3d,
                        
                        COUNT(DISTINCT CASE 
                            WHEN (m3.home_team_id = base.away_team_id OR m3.away_team_id = base.away_team_id)
                                 AND m3.match_date >= base.as_of_time - INTERVAL '7 days'
                                 AND m3.match_date < base.as_of_time
                            THEN m3.match_id END
                        ) AS matches_away_last_7d
                    FROM base
                    LEFT JOIN training_matches m3 ON (
                        m3.match_date < base.as_of_time
                    )
                    GROUP BY base.match_id
                )
                INSERT INTO match_context_v2 (
                    match_id, as_of_time,
                    rest_days_home, rest_days_away,
                    matches_home_last_3d, matches_home_last_7d,
                    matches_away_last_3d, matches_away_last_7d,
                    derby_flag, generation_version
                )
                SELECT
                    base.match_id,
                    base.as_of_time,
                    rd.rest_days_home,
                    rd.rest_days_away,
                    cg.matches_home_last_3d,
                    cg.matches_home_last_7d,
                    cg.matches_away_last_3d,
                    cg.matches_away_last_7d,
                    FALSE as derby_flag,
                    2 as generation_version
                FROM base
                JOIN rest_days rd ON base.match_id = rd.match_id
                JOIN congestion cg ON base.match_id = cg.match_id
                ON CONFLICT (match_id) DO NOTHING
            """)
            
            rows_created = cursor.rowcount
            conn.commit()
            
            print()
            print("=" * 80)
            print(f"✅ Backfill complete!")
            print(f"   Created {rows_created:,} new context rows")
            print("=" * 80)
            
            # Validation
            cursor.execute("""
                SELECT COUNT(*) as contaminated
                FROM match_context_v2 mc
                JOIN training_matches m ON mc.match_id = m.match_id
                WHERE mc.as_of_time > m.match_date
            """)
            contaminated = cursor.fetchone()[0]
            
            if contaminated > 0:
                print(f"⚠️  WARNING: Found {contaminated} contaminated rows!")
                return rows_created
            
            print("✅ Validation passed: 0% post-match contamination")
            print()
            
            # Final coverage report
            cursor.execute("""
                SELECT 
                    COUNT(DISTINCT tm.match_id) as total,
                    COUNT(DISTINCT mc.match_id) as with_context,
                    ROUND(100.0 * COUNT(DISTINCT mc.match_id) / COUNT(DISTINCT tm.match_id), 1) as coverage_pct
                FROM training_matches tm
                LEFT JOIN match_context_v2 mc ON tm.match_id = mc.match_id
                LEFT JOIN odds_real_consensus orc ON tm.match_id = orc.match_id
                WHERE tm.match_date >= '2020-01-01'
                  AND tm.outcome IN ('Home','Draw','Away')
                  AND orc.match_id IS NOT NULL
            """)
            total, with_context, coverage = cursor.fetchone()
            
            print("📊 Final Coverage (training matches with odds):")
            print(f"   Total: {total:,}")
            print(f"   With context_v2: {with_context:,}")
            print(f"   Coverage: {coverage}%")
            
            return rows_created

if __name__ == "__main__":
    try:
        rows = backfill_training_matches()
        print()
        print(f"🎯 Ready for V2.3 training with {rows:,} new clean context rows!")
    except Exception as e:
        print(f"❌ Error: {e}")
        raise
