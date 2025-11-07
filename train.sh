#!/bin/bash
#
# Convenience script for leakage-free training
# Handles LibGOMP configuration automatically
#

# Set LibGOMP path for LightGBM
export LD_LIBRARY_PATH="$(gcc -print-file-name=libgomp.so | xargs dirname):$LD_LIBRARY_PATH"

# Check which training to run
if [ "$1" == "--manage" ]; then
    # Use training manager
    echo "🚀 Running managed training (with auto-detection)..."
    python scripts/manage_training.py --train
elif [ "$1" == "--check" ]; then
    # Check status only
    python scripts/manage_training.py --check
else
    # Run direct training
    echo "🚀 Running leakage-free training directly..."
    echo "   Expected duration: 2-3 hours"
    echo "   Expected accuracy: 52-55% (NOT 90%!)"
    echo ""
    python -u training/train_v2_no_leakage.py
fi
