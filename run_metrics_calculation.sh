#!/bin/bash
# 
# Automated Metrics Calculation Runner
# Run this script periodically (e.g., via cron) to check completed matches
#

echo "🎯 Starting BetGenius Accuracy Tracking..."
echo "Checking for completed matches and computing metrics..."

# Run the calculation script
python calculate_metrics_results.py --limit 50

echo "✅ Metrics calculation complete"
echo "Check /metrics/summary API for updated accuracy statistics"
