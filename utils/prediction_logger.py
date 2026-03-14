"""
Unified prediction logging for all model versions (V0, V1, V3).

Logs predictions to the prediction_log table for:
1. Training data collection
2. Model accuracy tracking
3. A/B comparison between models
4. Cascade analytics
"""

import os
import logging
import hashlib
import json
from datetime import datetime, timezone
from typing import Optional, Dict, Any
import psycopg2
from psycopg2.extras import Json

logger = logging.getLogger(__name__)

MODEL_VERSIONS = {
    'v0_form': {'cascade_level': 3, 'description': 'ELO-based form predictor'},
    'v1_consensus': {'cascade_level': 1, 'description': 'Odds-based consensus'},
    'v3_sharp': {'cascade_level': 2, 'description': 'Sharp book ensemble'},
    'v3_sharp_shadow': {'cascade_level': 3, 'description': 'V3 shadow inference alongside V1'},
}


def compute_feature_hash(features: Dict[str, Any]) -> str:
    """Compute a hash of feature values for drift detection."""
    if not features:
        return None
    sorted_features = json.dumps(features, sort_keys=True, default=str)
    return hashlib.sha256(sorted_features.encode()).hexdigest()[:16]


def log_prediction(
    match_id: int,
    model_version: str,
    prob_home: float,
    prob_draw: float,
    prob_away: float,
    pick: str,
    confidence: float,
    league_id: Optional[int] = None,
    kickoff_at: Optional[datetime] = None,
    features_used: Optional[int] = None,
    features: Optional[Dict[str, Any]] = None,
    model_metadata: Optional[Dict[str, Any]] = None
) -> bool:
    """
    Log a prediction to the prediction_log table.
    
    Uses UPSERT to update if a prediction already exists for this match+model.
    """
    if model_version not in MODEL_VERSIONS:
        logger.warning(f"Unknown model version: {model_version}")
        return False
    
    cascade_level = MODEL_VERSIONS[model_version]['cascade_level']
    feature_hash = compute_feature_hash(features) if features else None
    
    try:
        with psycopg2.connect(os.environ.get('DATABASE_URL')) as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO prediction_log (
                        match_id, league_id, model_version, cascade_level,
                        prob_home, prob_draw, prob_away, pick, confidence,
                        features_used, feature_hash, model_metadata,
                        predicted_at, kickoff_at
                    ) VALUES (
                        %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s,
                        NOW(), %s
                    )
                    ON CONFLICT (match_id, model_version) 
                    DO UPDATE SET
                        prob_home = EXCLUDED.prob_home,
                        prob_draw = EXCLUDED.prob_draw,
                        prob_away = EXCLUDED.prob_away,
                        pick = EXCLUDED.pick,
                        confidence = EXCLUDED.confidence,
                        features_used = EXCLUDED.features_used,
                        feature_hash = EXCLUDED.feature_hash,
                        model_metadata = EXCLUDED.model_metadata,
                        predicted_at = NOW()
                """, (
                    match_id, league_id, model_version, cascade_level,
                    prob_home, prob_draw, prob_away, pick, confidence,
                    features_used, feature_hash, Json(model_metadata) if model_metadata else None,
                    kickoff_at
                ))
                conn.commit()
                logger.debug(f"Logged {model_version} prediction for match {match_id}")
                return True
    except Exception as e:
        logger.error(f"Failed to log prediction for match {match_id}: {e}")
        return False


def log_v0_prediction(
    match_id: int,
    prob_home: float,
    prob_draw: float,
    prob_away: float,
    league_id: Optional[int] = None,
    kickoff_at: Optional[datetime] = None,
    elo_home: Optional[float] = None,
    elo_away: Optional[float] = None,
    features: Optional[Dict[str, Any]] = None
) -> bool:
    """Convenience function for logging V0 form predictions."""
    pick = max([('H', prob_home), ('D', prob_draw), ('A', prob_away)], key=lambda x: x[1])[0]
    confidence = max(prob_home, prob_draw, prob_away)
    
    metadata = {
        'elo_home': elo_home,
        'elo_away': elo_away,
        'model_type': 'binary_experts_weighted'
    }
    
    return log_prediction(
        match_id=match_id,
        model_version='v0_form',
        prob_home=prob_home,
        prob_draw=prob_draw,
        prob_away=prob_away,
        pick=pick,
        confidence=confidence,
        league_id=league_id,
        kickoff_at=kickoff_at,
        features_used=11,
        features=features,
        model_metadata=metadata
    )


def log_v1_prediction(
    match_id: int,
    prob_home: float,
    prob_draw: float,
    prob_away: float,
    league_id: Optional[int] = None,
    kickoff_at: Optional[datetime] = None,
    bookmaker_count: Optional[int] = None
) -> bool:
    """Convenience function for logging V1 consensus predictions."""
    pick = max([('H', prob_home), ('D', prob_draw), ('A', prob_away)], key=lambda x: x[1])[0]
    confidence = max(prob_home, prob_draw, prob_away)
    
    metadata = {
        'bookmaker_count': bookmaker_count,
        'source': 'consensus_predictions'
    }
    
    return log_prediction(
        match_id=match_id,
        model_version='v1_consensus',
        prob_home=prob_home,
        prob_draw=prob_draw,
        prob_away=prob_away,
        pick=pick,
        confidence=confidence,
        league_id=league_id,
        kickoff_at=kickoff_at,
        model_metadata=metadata
    )


def log_v3_prediction(
    match_id: int,
    prob_home: float,
    prob_draw: float,
    prob_away: float,
    league_id: Optional[int] = None,
    kickoff_at: Optional[datetime] = None,
    features_used: Optional[int] = None,
    features: Optional[Dict[str, Any]] = None
) -> bool:
    """Convenience function for logging V3 sharp predictions."""
    pick = max([('H', prob_home), ('D', prob_draw), ('A', prob_away)], key=lambda x: x[1])[0]
    confidence = max(prob_home, prob_draw, prob_away)
    
    metadata = {
        'model_type': 'binary_expert_ensemble',
        'source': 'sharp_book_odds'
    }
    
    return log_prediction(
        match_id=match_id,
        model_version='v3_sharp',
        prob_home=prob_home,
        prob_draw=prob_draw,
        prob_away=prob_away,
        pick=pick,
        confidence=confidence,
        league_id=league_id,
        kickoff_at=kickoff_at,
        features_used=features_used,
        features=features,
        model_metadata=metadata
    )


def settle_predictions(match_id: int, actual_result: str) -> int:
    """
    Settle all predictions for a match with the actual result.
    
    Returns the number of predictions settled.
    """
    if actual_result not in ('H', 'D', 'A'):
        logger.error(f"Invalid result: {actual_result}")
        return 0
    
    try:
        with psycopg2.connect(os.environ.get('DATABASE_URL')) as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    UPDATE prediction_log
                    SET actual_result = %s,
                        is_correct = (pick = %s),
                        settled_at = NOW()
                    WHERE match_id = %s
                      AND actual_result IS NULL
                    RETURNING id
                """, (actual_result, actual_result, match_id))
                
                count = cursor.rowcount
                conn.commit()
                
                if count > 0:
                    logger.info(f"Settled {count} predictions for match {match_id} with result {actual_result}")
                return count
    except Exception as e:
        logger.error(f"Failed to settle predictions for match {match_id}: {e}")
        return 0


def get_model_accuracy(model_version: str, days: int = 30) -> Dict[str, Any]:
    """Get accuracy stats for a model over the last N days."""
    try:
        with psycopg2.connect(os.environ.get('DATABASE_URL')) as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT 
                        COUNT(*) as total,
                        SUM(CASE WHEN is_correct THEN 1 ELSE 0 END) as correct,
                        AVG(CASE WHEN is_correct THEN 1.0 ELSE 0.0 END) as accuracy
                    FROM prediction_log
                    WHERE model_version = %s
                      AND actual_result IS NOT NULL
                      AND predicted_at > NOW() - INTERVAL '%s days'
                """, (model_version, days))
                
                row = cursor.fetchone()
                if row:
                    return {
                        'model': model_version,
                        'period_days': days,
                        'total_predictions': row[0] or 0,
                        'correct': row[1] or 0,
                        'accuracy': float(row[2]) if row[2] else None
                    }
                return {'model': model_version, 'total_predictions': 0}
    except Exception as e:
        logger.error(f"Failed to get accuracy for {model_version}: {e}")
        return {'model': model_version, 'error': str(e)}
