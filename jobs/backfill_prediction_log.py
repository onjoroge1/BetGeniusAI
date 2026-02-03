"""
Backfill prediction_log from consensus_predictions table.

This script migrates historical V1 consensus predictions to the unified
prediction_log table for training data collection and accuracy tracking.
"""

import os
import sys
import logging
from datetime import datetime

import psycopg2
from psycopg2.extras import execute_values

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def backfill_v1_from_consensus(batch_size: int = 1000) -> dict:
    """
    Migrate consensus_predictions to prediction_log.
    
    Returns stats about the migration.
    """
    stats = {
        'total_consensus': 0,
        'already_migrated': 0,
        'newly_migrated': 0,
        'errors': 0
    }
    
    try:
        with psycopg2.connect(os.environ.get('DATABASE_URL')) as conn:
            with conn.cursor() as cursor:
                # Count total consensus predictions
                cursor.execute("SELECT COUNT(*) FROM consensus_predictions")
                stats['total_consensus'] = cursor.fetchone()[0]
                
                # Count already migrated
                cursor.execute("""
                    SELECT COUNT(*) FROM prediction_log 
                    WHERE model_version = 'v1_consensus'
                """)
                stats['already_migrated'] = cursor.fetchone()[0]
                
                # Get predictions not yet in prediction_log
                cursor.execute("""
                    SELECT 
                        cp.match_id,
                        f.league_id,
                        cp.consensus_h,
                        cp.consensus_d,
                        cp.consensus_a,
                        cp.created_at,
                        f.kickoff_at
                    FROM consensus_predictions cp
                    LEFT JOIN fixtures f ON cp.match_id = f.match_id
                    WHERE NOT EXISTS (
                        SELECT 1 FROM prediction_log pl 
                        WHERE pl.match_id = cp.match_id 
                        AND pl.model_version = 'v1_consensus'
                    )
                    ORDER BY cp.created_at DESC
                    LIMIT %s
                """, (batch_size,))
                
                rows = cursor.fetchall()
                
                if not rows:
                    logger.info("No new predictions to migrate")
                    return stats
                
                # Prepare batch insert
                values = []
                for row in rows:
                    match_id, league_id, h, d, a, created_at, kickoff_at = row
                    
                    # Skip rows with missing probability data
                    if h is None or d is None or a is None:
                        continue
                    
                    # Determine pick
                    probs = {'H': float(h), 'D': float(d), 'A': float(a)}
                    pick = max(probs, key=probs.get)
                    confidence = max(probs.values())
                    
                    values.append((
                        match_id,
                        league_id,  # Can be NULL
                        'v1_consensus',
                        1,  # cascade_level
                        float(h),
                        float(d),
                        float(a),
                        pick,
                        confidence,
                        created_at,
                        kickoff_at
                    ))
                
                # Batch insert with conflict handling
                insert_query = """
                    INSERT INTO prediction_log (
                        match_id, league_id, model_version, cascade_level,
                        prob_home, prob_draw, prob_away, pick, confidence,
                        predicted_at, kickoff_at
                    ) VALUES %s
                    ON CONFLICT (match_id, model_version) DO NOTHING
                """
                
                execute_values(cursor, insert_query, values)
                stats['newly_migrated'] = cursor.rowcount
                conn.commit()
                
                logger.info(f"Migrated {stats['newly_migrated']} predictions")
                
    except Exception as e:
        logger.error(f"Migration error: {e}")
        stats['errors'] = 1
    
    return stats


def backfill_results_from_matches() -> dict:
    """
    Settle predictions by matching with actual results from fixtures/historical_odds.
    """
    stats = {
        'settled': 0,
        'errors': 0
    }
    
    try:
        with psycopg2.connect(os.environ.get('DATABASE_URL')) as conn:
            with conn.cursor() as cursor:
                # Update predictions with actual results from historical_odds via fixtures join
                cursor.execute("""
                    UPDATE prediction_log pl
                    SET 
                        actual_result = ho.result,
                        is_correct = (pl.pick = ho.result),
                        settled_at = NOW()
                    FROM fixtures f
                    JOIN historical_odds ho ON 
                        f.home_team = ho.home_team 
                        AND f.away_team = ho.away_team
                        AND DATE(f.kickoff_at) = ho.match_date
                    WHERE pl.match_id = f.match_id
                      AND ho.result IS NOT NULL
                      AND ho.result IN ('H', 'D', 'A')
                      AND pl.actual_result IS NULL
                    RETURNING pl.id
                """)
                
                stats['settled'] = cursor.rowcount
                conn.commit()
                
                logger.info(f"Settled {stats['settled']} predictions from fixtures")
                
                logger.info(f"Settled {stats['settled']} predictions using historical data")
                
    except Exception as e:
        logger.error(f"Settlement error: {e}")
        stats['errors'] = 1
    
    return stats


def run_full_backfill():
    """Run full backfill and settlement."""
    logger.info("=" * 50)
    logger.info("PREDICTION LOG BACKFILL")
    logger.info("=" * 50)
    
    # Step 1: Migrate V1 predictions
    logger.info("\n1. Migrating V1 consensus predictions...")
    migration_stats = backfill_v1_from_consensus(batch_size=10000)
    logger.info(f"   Total in consensus: {migration_stats['total_consensus']}")
    logger.info(f"   Already migrated: {migration_stats['already_migrated']}")
    logger.info(f"   Newly migrated: {migration_stats['newly_migrated']}")
    
    # Step 2: Settle with results
    logger.info("\n2. Settling predictions with actual results...")
    settlement_stats = backfill_results_from_matches()
    logger.info(f"   Predictions settled: {settlement_stats['settled']}")
    
    # Step 3: Report accuracy
    logger.info("\n3. Current accuracy by model:")
    try:
        with psycopg2.connect(os.environ.get('DATABASE_URL')) as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT 
                        model_version,
                        COUNT(*) as total,
                        SUM(CASE WHEN is_correct THEN 1 ELSE 0 END) as correct,
                        ROUND(AVG(CASE WHEN is_correct THEN 1.0 ELSE 0.0 END) * 100, 2) as accuracy
                    FROM prediction_log
                    WHERE actual_result IS NOT NULL
                    GROUP BY model_version
                    ORDER BY model_version
                """)
                
                for row in cursor.fetchall():
                    model, total, correct, accuracy = row
                    logger.info(f"   {model}: {correct}/{total} = {accuracy}%")
                    
    except Exception as e:
        logger.error(f"Accuracy report error: {e}")
    
    logger.info("\n" + "=" * 50)
    logger.info("BACKFILL COMPLETE")
    logger.info("=" * 50)


if __name__ == "__main__":
    run_full_backfill()
