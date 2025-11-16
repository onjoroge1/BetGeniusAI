#!/usr/bin/env bash
#
# BetGenius AI - V2 Model Training Wrapper
# 
# This script sets the correct library path before running Python training.
# Use this instead of calling the Python script directly.
#
# Usage:
#   ./scripts/train_v2.sh --use-transformed     # Train with transformed features (recommended)
#   ./scripts/train_v2.sh                        # Train with raw features
#   ./scripts/train_v2.sh --max-samples 500      # Quick test run
#

set -e

# Set library path for LightGBM
export LD_LIBRARY_PATH="$(gcc -print-file-name=libgomp.so | xargs dirname):$LD_LIBRARY_PATH"

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Run Python training script
cd "$PROJECT_ROOT"
python scripts/train_v2_standalone.py "$@"
