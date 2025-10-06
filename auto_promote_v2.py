#!/usr/bin/env python3
"""
Auto-Promotion Script for V2 Model
Checks if V2 beats V1 on all thresholds and promotes if criteria met
"""

import os
import psycopg2
from datetime import datetime, timedelta
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get('DATABASE_URL')

PROMOTION_THRESHOLDS = {
    'min_matches': 300,
    'max_logloss_delta': -0.05,
    'max_brier_delta': -0.02,
    'min_clv_hit_rate': 0.55,
    'required_streak_days': 7
}

def get_config_value(key: str, default: str = "") -> str:
    """Get configuration value from model_config table"""
    try:
        with psycopg2.connect(DATABASE_URL) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT config_value FROM model_config WHERE config_key = %s",
                (key,)
            )
            result = cursor.fetchone()
            return result[0] if result else default
    except Exception as e:
        logger.error(f"Error reading config {key}: {e}")
        return default

def set_config_value(key: str, value: str):
    """Set configuration value in model_config table"""
    try:
        with psycopg2.connect(DATABASE_URL) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE model_config 
                SET config_value = %s, updated_at = NOW()
                WHERE config_key = %s
            """, (value, key))
            conn.commit()
    except Exception as e:
        logger.error(f"Error setting config {key}: {e}")

def get_model_metrics(window_days: int = 30):
    """Get comparison metrics between v1 and v2"""
    try:
        with psycopg2.connect(DATABASE_URL) as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                WITH predictions AS (
                    SELECT 
                        mil.model_version,
                        mil.p_home,
                        mil.p_draw,
                        mil.p_away,
                        mr.outcome AS actual_outcome,
                        co.h_close_odds AS ph_close,
                        co.d_close_odds AS pd_close,
                        co.a_close_odds AS pa_close
                    FROM model_inference_logs mil
                    JOIN match_results mr ON mil.match_id = mr.match_id
                    LEFT JOIN closing_odds co ON mil.match_id = co.match_id
                    WHERE mil.scored_at > NOW() - INTERVAL '%s days'
                        AND mr.outcome IS NOT NULL
                ),
                metrics_per_model AS (
                    SELECT
                        model_version,
                        COUNT(*) AS n_matches,
                        
                        -AVG(
                            LN(CASE actual_outcome
                                WHEN 'H' THEN GREATEST(p_home, 0.001)
                                WHEN 'D' THEN GREATEST(p_draw, 0.001)
                                WHEN 'A' THEN GREATEST(p_away, 0.001)
                            END)
                        ) AS log_loss,
                        
                        AVG(
                            POWER(CASE WHEN actual_outcome = 'H' THEN 1 ELSE 0 END - p_home, 2) +
                            POWER(CASE WHEN actual_outcome = 'D' THEN 1 ELSE 0 END - p_draw, 2) +
                            POWER(CASE WHEN actual_outcome = 'A' THEN 1 ELSE 0 END - p_away, 2)
                        ) AS brier_score,
                        
                        AVG(CASE
                            WHEN ph_close IS NOT NULL THEN
                                CASE WHEN (
                                    (actual_outcome = 'H' AND (1.0/p_home) > ph_close) OR
                                    (actual_outcome = 'D' AND (1.0/p_draw) > pd_close) OR
                                    (actual_outcome = 'A' AND (1.0/p_away) > pa_close)
                                ) THEN 1.0 ELSE 0.0 END
                            END
                        ) AS clv_hit_rate
                        
                    FROM predictions
                    GROUP BY model_version
                )
                SELECT * FROM metrics_per_model
            """, (window_days,))
            
            rows = cursor.fetchall()
            
        metrics = {}
        for row in rows:
            model_version, n_matches, log_loss, brier, clv_hit = row
            metrics[model_version] = {
                'n_matches': n_matches,
                'log_loss': float(log_loss) if log_loss else None,
                'brier_score': float(brier) if brier else None,
                'clv_hit_rate': float(clv_hit) if clv_hit else None
            }
        
        return metrics
        
    except Exception as e:
        logger.error(f"Error getting model metrics: {e}")
        return {}

def check_promotion_criteria():
    """Check if V2 meets promotion thresholds"""
    logger.info("=" * 60)
    logger.info("V2 AUTO-PROMOTION CHECK")
    logger.info("=" * 60)
    
    primary_model = get_config_value('PRIMARY_MODEL_VERSION', 'v1')
    logger.info(f"Current primary model: {primary_model}")
    
    if primary_model == 'v2':
        logger.info("✓ V2 is already primary model")
        return False
    
    metrics = get_model_metrics(window_days=30)
    
    if 'v1' not in metrics or 'v2' not in metrics:
        logger.warning("⚠️  Insufficient data for both v1 and v2")
        return False
    
    v1 = metrics['v1']
    v2 = metrics['v2']
    
    logger.info(f"\nV1 Metrics (30d):")
    logger.info(f"  Matches: {v1['n_matches']}")
    logger.info(f"  LogLoss: {v1['log_loss']:.4f}")
    logger.info(f"  Brier: {v1['brier_score']:.4f}")
    logger.info(f"  CLV Hit Rate: {v1['clv_hit_rate']:.3f}" if v1['clv_hit_rate'] else "  CLV Hit Rate: N/A")
    
    logger.info(f"\nV2 Metrics (30d):")
    logger.info(f"  Matches: {v2['n_matches']}")
    logger.info(f"  LogLoss: {v2['log_loss']:.4f}")
    logger.info(f"  Brier: {v2['brier_score']:.4f}")
    logger.info(f"  CLV Hit Rate: {v2['clv_hit_rate']:.3f}" if v2['clv_hit_rate'] else "  CLV Hit Rate: N/A")
    
    checks = {}
    
    checks['min_matches'] = v2['n_matches'] >= PROMOTION_THRESHOLDS['min_matches']
    logger.info(f"\n✓ Min matches: {v2['n_matches']} >= {PROMOTION_THRESHOLDS['min_matches']}" if checks['min_matches'] 
                else f"\n✗ Min matches: {v2['n_matches']} < {PROMOTION_THRESHOLDS['min_matches']}")
    
    delta_logloss = v2['log_loss'] - v1['log_loss']
    checks['logloss'] = delta_logloss <= PROMOTION_THRESHOLDS['max_logloss_delta']
    logger.info(f"✓ LogLoss delta: {delta_logloss:.4f} <= {PROMOTION_THRESHOLDS['max_logloss_delta']}" if checks['logloss']
                else f"✗ LogLoss delta: {delta_logloss:.4f} > {PROMOTION_THRESHOLDS['max_logloss_delta']}")
    
    delta_brier = v2['brier_score'] - v1['brier_score']
    checks['brier'] = delta_brier <= PROMOTION_THRESHOLDS['max_brier_delta']
    logger.info(f"✓ Brier delta: {delta_brier:.4f} <= {PROMOTION_THRESHOLDS['max_brier_delta']}" if checks['brier']
                else f"✗ Brier delta: {delta_brier:.4f} > {PROMOTION_THRESHOLDS['max_brier_delta']}")
    
    if v2['clv_hit_rate']:
        checks['clv'] = v2['clv_hit_rate'] >= PROMOTION_THRESHOLDS['min_clv_hit_rate']
        logger.info(f"✓ CLV hit rate: {v2['clv_hit_rate']:.3f} >= {PROMOTION_THRESHOLDS['min_clv_hit_rate']}" if checks['clv']
                    else f"✗ CLV hit rate: {v2['clv_hit_rate']:.3f} < {PROMOTION_THRESHOLDS['min_clv_hit_rate']}")
    else:
        checks['clv'] = False
        logger.info("✗ CLV hit rate: No closing odds available")
    
    current_streak = int(get_config_value('PROMOTE_STREAK_DAYS', '0'))
    
    if all(checks.values()):
        new_streak = current_streak + 1
        set_config_value('PROMOTE_STREAK_DAYS', str(new_streak))
        logger.info(f"\n🔥 All thresholds met! Streak: {new_streak}/{PROMOTION_THRESHOLDS['required_streak_days']} days")
        
        if new_streak >= PROMOTION_THRESHOLDS['required_streak_days']:
            logger.info(f"\n🎉 PROMOTION TRIGGERED: V2 beat V1 for {new_streak} consecutive days!")
            promote_v2()
            return True
        else:
            logger.info(f"⏳ Need {PROMOTION_THRESHOLDS['required_streak_days'] - new_streak} more days to promote")
            return False
    else:
        logger.info(f"\n⚠️  Not all thresholds met. Resetting streak from {current_streak} to 0")
        set_config_value('PROMOTE_STREAK_DAYS', '0')
        return False

def promote_v2():
    """Promote V2 to primary model"""
    logger.info("\n" + "=" * 60)
    logger.info("PROMOTING V2 TO PRIMARY MODEL")
    logger.info("=" * 60)
    
    set_config_value('PRIMARY_MODEL_VERSION', 'v2')
    set_config_value('PROMOTE_STREAK_DAYS', '0')
    
    logger.info("✅ V2 is now the primary model!")
    logger.info("📊 V1 will continue running in shadow mode for monitoring")
    logger.info("🔄 Consider developing V3 for next round of improvements")

if __name__ == "__main__":
    check_promotion_criteria()
