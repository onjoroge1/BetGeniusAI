"""
Automated V2 Model Retraining with Threshold Triggers

This job monitors the model and triggers retraining when:
1. Match Volume: 50+ new finished matches since last training
2. Model Staleness: Model not trained in 14+ days
3. Accuracy Drift: Recent accuracy drops below threshold

Runs once per day via scheduler (at 03:00 UTC).
"""

import os
import logging
import psycopg2
import json
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

MODEL_DIR = Path("models/v2_lightgbm")
MODEL_META_FILE = MODEL_DIR / "model_metadata.json"
MIN_NEW_MATCHES = 50
MAX_MODEL_AGE_DAYS = 14
MIN_ACCURACY_THRESHOLD = 0.48


def get_model_metadata() -> dict:
    """Load model metadata from file"""
    try:
        if MODEL_META_FILE.exists():
            with open(MODEL_META_FILE) as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"Could not load model metadata: {e}")
    return {}


def save_model_metadata(meta: dict):
    """Save model metadata to file"""
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    with open(MODEL_META_FILE, 'w') as f:
        json.dump(meta, f, indent=2, default=str)


def check_match_volume_trigger(conn) -> tuple[bool, int]:
    """
    Check if enough new matches have accumulated since last training.
    
    Returns:
        (trigger_needed, new_match_count)
    """
    meta = get_model_metadata()
    last_trained_at = meta.get('trained_at')
    
    if not last_trained_at:
        logger.info("📊 RETRAIN CHECK: No training history found, using 30-day lookback")
        last_trained_at = (datetime.utcnow() - timedelta(days=30)).isoformat()
    
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COUNT(*)
        FROM matches m
        WHERE m.outcome IS NOT NULL
        AND m.match_date_utc > %s::timestamp
    """, (last_trained_at,))
    
    new_matches = cursor.fetchone()[0]
    cursor.close()
    
    trigger = new_matches >= MIN_NEW_MATCHES
    logger.info(f"📊 RETRAIN CHECK: {new_matches} new matches since {last_trained_at[:10]} (threshold: {MIN_NEW_MATCHES})")
    
    return trigger, new_matches


def check_model_staleness_trigger() -> tuple[bool, int]:
    """
    Check if model is too old.
    
    Returns:
        (trigger_needed, days_since_training)
    """
    meta = get_model_metadata()
    last_trained_at = meta.get('trained_at')
    
    if not last_trained_at:
        logger.info("📊 RETRAIN CHECK: No training date found - model needs initial training")
        return True, 999
    
    trained_str = last_trained_at.replace('Z', '').replace('+00:00', '')
    trained_dt = datetime.fromisoformat(trained_str)
    age_days = (datetime.utcnow() - trained_dt).days
    
    trigger = age_days >= MAX_MODEL_AGE_DAYS
    logger.info(f"📊 RETRAIN CHECK: Model age = {age_days} days (threshold: {MAX_MODEL_AGE_DAYS})")
    
    return trigger, age_days


def check_accuracy_drift_trigger(conn) -> tuple[bool, float]:
    """
    Check if recent V2 model accuracy has drifted below threshold.
    Uses v2_predictions table which stores actual V2 LightGBM outputs.
    
    Returns:
        (trigger_needed, recent_accuracy)
    """
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT COUNT(*) FROM information_schema.tables 
        WHERE table_name = 'v2_predictions'
    """)
    has_v2_table = cursor.fetchone()[0] > 0
    
    if has_v2_table:
        cursor.execute("""
            SELECT 
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE v2.prediction = m.outcome) as correct
            FROM v2_predictions v2
            JOIN matches m ON v2.match_id = m.match_id
            WHERE m.match_date_utc >= NOW() - INTERVAL '14 days'
            AND m.outcome IS NOT NULL
        """)
    else:
        cursor.execute("""
            SELECT 
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE prediction = actual_outcome) as correct
            FROM (
                SELECT 
                    cp.match_id,
                    CASE 
                        WHEN cp.consensus_h > cp.consensus_d AND cp.consensus_h > cp.consensus_a THEN 'H'
                        WHEN cp.consensus_a > cp.consensus_d AND cp.consensus_a > cp.consensus_h THEN 'A'
                        ELSE 'D'
                    END as prediction,
                    m.outcome as actual_outcome
                FROM consensus_predictions cp
                JOIN matches m ON cp.match_id = m.match_id
                WHERE m.match_date_utc >= NOW() - INTERVAL '14 days'
                AND m.outcome IS NOT NULL
            ) subq
        """)
    
    result = cursor.fetchone()
    cursor.close()
    
    if not result or result[0] == 0:
        logger.info("📊 RETRAIN CHECK: No recent predictions to evaluate accuracy")
        return False, 0.0
    
    total, correct = result
    accuracy = correct / total if total > 0 else 0.0
    
    trigger = accuracy < MIN_ACCURACY_THRESHOLD
    logger.info(f"📊 RETRAIN CHECK: Recent accuracy = {accuracy:.1%} ({correct}/{total}) (threshold: {MIN_ACCURACY_THRESHOLD:.0%})")
    
    return trigger, accuracy


def run_training() -> dict:
    """
    Execute the V2 production training script.
    
    Returns:
        Training result dictionary
    """
    import subprocess
    import sys
    
    logger.info("🚀 RETRAIN: Starting V2 production training...")
    start_time = datetime.utcnow()
    
    env = os.environ.copy()
    env['LD_LIBRARY_PATH'] = "/nix/store/xvzz97yk73hw03v5dhhz3j47ggwf1yq1-gcc-13.2.0-lib/lib"
    
    try:
        result = subprocess.run(
            [sys.executable, "training/train_v2_production.py"],
            capture_output=True,
            text=True,
            timeout=1800,
            cwd=os.getcwd(),
            env=env
        )
        
        success = result.returncode == 0
        duration = (datetime.utcnow() - start_time).total_seconds()
        
        if success:
            meta = get_model_metadata()
            meta['trained_at'] = datetime.utcnow().isoformat() + 'Z'
            meta['training_duration_seconds'] = duration
            save_model_metadata(meta)
            
            logger.info(f"✅ RETRAIN: Training completed in {duration:.0f}s")
        else:
            logger.error(f"❌ RETRAIN: Training failed - {result.stderr[:500]}")
        
        return {
            "success": success,
            "duration_seconds": duration,
            "stdout": result.stdout[-1000:] if result.stdout else "",
            "stderr": result.stderr[-500:] if result.stderr else ""
        }
        
    except subprocess.TimeoutExpired:
        logger.error("❌ RETRAIN: Training timed out after 30 minutes")
        return {"success": False, "error": "timeout"}
    except Exception as e:
        logger.error(f"❌ RETRAIN: Training error - {e}")
        return {"success": False, "error": str(e)}


async def auto_retrain_job(force: bool = False) -> dict:
    """
    Main automated retraining job.
    
    Checks all triggers and runs training if any are met.
    
    Args:
        force: If True, skip trigger checks and retrain immediately
    
    Returns:
        dict with check results and training status
    """
    start_time = datetime.utcnow()
    result = {
        "checked_at": start_time.isoformat(),
        "triggers": {},
        "training_triggered": False,
        "training_result": None
    }
    
    try:
        conn = psycopg2.connect(os.environ.get('DATABASE_URL'))
        
        if force:
            logger.info("🔄 RETRAIN: Force mode enabled - skipping trigger checks")
            result["training_triggered"] = True
            result["triggers"]["force"] = True
        else:
            match_trigger, new_matches = check_match_volume_trigger(conn)
            staleness_trigger, model_age = check_model_staleness_trigger()
            accuracy_trigger, recent_acc = check_accuracy_drift_trigger(conn)
            
            result["triggers"] = {
                "match_volume": {"triggered": match_trigger, "new_matches": new_matches, "threshold": MIN_NEW_MATCHES},
                "model_staleness": {"triggered": staleness_trigger, "age_days": model_age, "threshold": MAX_MODEL_AGE_DAYS},
                "accuracy_drift": {"triggered": accuracy_trigger, "recent_accuracy": round(recent_acc, 3), "threshold": MIN_ACCURACY_THRESHOLD}
            }
            
            result["training_triggered"] = match_trigger or staleness_trigger or accuracy_trigger
        
        conn.close()
        
        if result["training_triggered"]:
            triggered_by = [k for k, v in result["triggers"].items() if v.get("triggered")]
            logger.info(f"🔔 RETRAIN: Training triggered by: {', '.join(triggered_by)}")
            result["training_result"] = run_training()
        else:
            logger.info("✅ RETRAIN: All checks passed - no retraining needed")
        
        result["duration_ms"] = int((datetime.utcnow() - start_time).total_seconds() * 1000)
        return result
        
    except Exception as e:
        logger.error(f"❌ RETRAIN: Job failed - {e}")
        result["error"] = str(e)
        return result


if __name__ == "__main__":
    import asyncio
    logging.basicConfig(level=logging.INFO)
    result = asyncio.run(auto_retrain_job())
    print(json.dumps(result, indent=2))
