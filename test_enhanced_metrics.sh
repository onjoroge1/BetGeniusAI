#!/bin/bash
# Enhanced Metrics Testing Script
# Tests the new odds_accuracy_evaluation endpoint with various filters

API_KEY="betgenius_secure_key_2024"
BASE_URL="http://localhost:8000"

echo "🧪 ENHANCED METRICS EVALUATION TESTING"
echo "========================================"

echo ""
echo "1️⃣  Test: All Leagues, All Time"
echo "----------------------------------------"
curl -s "${BASE_URL}/metrics/evaluation?window=all" \
  -H "Authorization: Bearer ${API_KEY}" | python -m json.tool

echo ""
echo "2️⃣  Test: Last 30 Days (Default)"
echo "----------------------------------------"
curl -s "${BASE_URL}/metrics/evaluation" \
  -H "Authorization: Bearer ${API_KEY}" | python -m json.tool

echo ""
echo "3️⃣  Test: Last 7 Days"
echo "----------------------------------------"
curl -s "${BASE_URL}/metrics/evaluation?window=7d" \
  -H "Authorization: Bearer ${API_KEY}" | python -m json.tool

echo ""
echo "4️⃣  Test: Specific League (Serie A)"
echo "----------------------------------------"
curl -s "${BASE_URL}/metrics/evaluation?league=Serie%20A&window=all" \
  -H "Authorization: Bearer ${API_KEY}" | python -m json.tool

echo ""
echo "5️⃣  Test: Without CLV Analysis"
echo "----------------------------------------"
curl -s "${BASE_URL}/metrics/evaluation?include_clv=false&window=all" \
  -H "Authorization: Bearer ${API_KEY}" | python -m json.tool

echo ""
echo "✅ Enhanced Metrics Testing Complete!"
echo ""
echo "📊 Key Metrics Explained:"
echo "  - Brier Score: Lower is better (0 = perfect, 1 = worst)"
echo "  - Log Loss: Lower is better (<1.0 is good)"
echo "  - Hit Rate: Higher is better (>0.55 is good)"
echo "  - Model Grade: A+ to F rating based on all metrics"
echo ""
echo "📈 CLV Analysis (when closing odds available):"
echo "  - avg_clv_edge: Raw edge in probability units"
echo "  - avg_clv_percent: Percentage edge vs closing line"
echo "  - positive_clv_rate: % of predictions beating closing line"
