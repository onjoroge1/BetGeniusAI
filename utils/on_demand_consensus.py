"""
On-Demand Consensus Builder
==========================

Builds consensus predictions on-demand from odds_snapshots when no pre-computed
consensus exists. Persists the result to consensus_predictions table.
"""

import os
import psycopg2
from datetime import datetime

async def build_on_demand_consensus(match_id):
    """
    Build consensus prediction from odds_snapshots for a match that doesn't have
    pre-computed consensus. Uses the same bucket logic as scheduler.
    """
    
    try:
        with psycopg2.connect(os.environ['DATABASE_URL']) as conn:
            with conn.cursor() as cursor:
                
                # Use same SQL as scheduler with aligned bucket ranges
                cursor.execute("""
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
                                WHEN secs_to_kickoff BETWEEN 5400 AND 32400 THEN '6h'    -- 1.5-9h 
                                WHEN secs_to_kickoff BETWEEN 21600 AND 64800 THEN '12h'  -- 6-18h
                                WHEN secs_to_kickoff BETWEEN 64800 AND 108000 THEN '24h' -- 18-30h
                                WHEN secs_to_kickoff BETWEEN 129600 AND 216000 THEN '48h'-- 36-60h
                                WHEN secs_to_kickoff BETWEEN 216000 AND 302400 THEN '72h'-- 60-84h
                                WHEN secs_to_kickoff BETWEEN 900 AND 5400 THEN '3h'      -- 0.25-1.5h
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
                        WHERE time_bucket != 'other'  -- Only valid buckets
                        GROUP BY time_bucket
                        HAVING COUNT(DISTINCT book_id) >= 2
                    )
                    INSERT INTO consensus_predictions 
                    (match_id, time_bucket, consensus_h, consensus_d, consensus_a, 
                     dispersion_h, dispersion_d, dispersion_a, n_books, created_at)
                    SELECT %s, time_bucket, consensus_h, consensus_d, consensus_a,
                           COALESCE(dispersion_h, 0), COALESCE(dispersion_d, 0), COALESCE(dispersion_a, 0),
                           n_books, NOW()
                    FROM consensus_calc
                    ON CONFLICT (match_id, time_bucket) DO NOTHING
                    RETURNING match_id, time_bucket, consensus_h, consensus_d, consensus_a, n_books
                """, (match_id, match_id))
                
                results = cursor.fetchall()
                conn.commit()
                
                if results:
                    # Successfully created on-demand consensus
                    # Return the best bucket (highest book count)
                    best_result = max(results, key=lambda x: x[5])  # x[5] = n_books
                    
                    match_id, time_bucket, consensus_h, consensus_d, consensus_a, n_books = best_result
                    
                    # Ensure probabilities sum to 1
                    total = consensus_h + consensus_d + consensus_a
                    if total > 0:
                        consensus_h /= total
                        consensus_d /= total  
                        consensus_a /= total
                    else:
                        # Fallback to equal probabilities
                        consensus_h = consensus_d = consensus_a = 1/3
                    
                    # Determine prediction
                    probs = {'home_win': consensus_h, 'draw': consensus_d, 'away_win': consensus_a}
                    prediction = max(probs.keys(), key=lambda k: probs[k])
                    confidence = max(probs.values())
                    
                    print(f"[ON_DEMAND] Built consensus for match {match_id}: {len(results)} bucket(s), {n_books} books")
                    
                    return {
                        'probabilities': probs,
                        'confidence': confidence,
                        'prediction': prediction,
                        'quality_score': confidence,
                        'bookmaker_count': n_books,
                        'model_type': 'on_demand_consensus',
                        'data_source': f'odds_snapshots_{time_bucket}',
                        'metadata': {
                            'time_bucket': time_bucket,
                            'n_books': n_books,
                            'data_ok': True,
                            'consensus_buckets': len(results),
                            'prob_sum_valid': True
                        }
                    }
                else:
                    print(f"[ON_DEMAND] No consensus possible for match {match_id}: insufficient data")
                    return None
                    
    except Exception as e:
        print(f"[ON_DEMAND] Error building consensus for match {match_id}: {e}")
        return None