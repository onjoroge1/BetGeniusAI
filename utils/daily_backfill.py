"""
Daily Backfill Utility
======================

Simple daily backfill runner for consensus predictions.
Called by scheduler at 04:30 UTC daily.
"""

import sys
import os
import subprocess
import logging

logger = logging.getLogger(__name__)

def run_daily_backfill():
    """Run daily consensus backfill to catch any missed matches"""
    logger.info("🔄 [DAILY_BACKFILL] Starting daily consensus backfill...")
    
    try:
        # Run the backfill script with 7-day window (sweep recent data)
        script_path = os.path.join(os.path.dirname(__file__), '..', 'scripts', 'consensus_backfill.py')
        result = subprocess.run(
            [sys.executable, script_path],
            input='y\n',  # Auto-confirm
            text=True,
            capture_output=True,
            timeout=300  # 5 minute timeout
        )
        
        if result.returncode == 0:
            logger.info("✅ [DAILY_BACKFILL] Daily backfill completed successfully")
            backfilled_count = 0
            for line in result.stdout.split('\n'):
                if 'consensus rows created' in line:
                    try:
                        backfilled_count = int(line.split('rows created: ')[1])
                    except:
                        pass
            logger.info(f"[DAILY_BACKFILL] Backfilled {backfilled_count} consensus rows")
        else:
            logger.warning(f"⚠️ [DAILY_BACKFILL] Backfill completed with warnings: {result.stderr}")
            
    except subprocess.TimeoutExpired:
        logger.error("❌ [DAILY_BACKFILL] Backfill timed out after 5 minutes")
    except Exception as e:
        logger.error(f"❌ [DAILY_BACKFILL] Daily backfill failed: {e}")

if __name__ == "__main__":
    run_daily_backfill()