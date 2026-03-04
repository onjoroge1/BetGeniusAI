"""
Background V3 Retrain Job
Runs training/train_v3_sharp.py with the new 36-feature set (includes H2H draw rate).
Intended to be run as a one-off job when new features are added.

Usage:
    nohup python jobs/retrain_v3_background.py &> /tmp/v3_retrain.log &
"""
import os
import sys
import subprocess
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

if __name__ == "__main__":
    script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "training", "train_v3_sharp.py")
    logger.info(f"Starting V3 retrain: {script}")
    result = subprocess.run(
        [sys.executable, script],
        cwd=os.path.dirname(script).replace("/training", ""),
        capture_output=False,
    )
    logger.info(f"V3 retrain completed with exit code {result.returncode}")
