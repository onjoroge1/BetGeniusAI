#!/bin/bash
# Quick test script for /predict-v2 endpoint using curl

BASE_URL="http://localhost:8000"
API_KEY="your_api_key_here"  # Replace with your actual API key

echo "🧪 Testing /predict-v2 endpoint"
echo "================================"

# Test 1: Get upcoming matches
echo -e "\n1️⃣ Fetching upcoming matches..."
curl -s "${BASE_URL}/market" \
  -H "X-API-Key: ${API_KEY}" | jq -r '.[] | "\(.match_id): \(.home_team) vs \(.away_team)"' | head -5

# Test 2: Get V2 prediction for specific match
MATCH_ID=1379062  # Replace with actual match ID
echo -e "\n2️⃣ Testing V2 prediction for match ${MATCH_ID}..."
curl -s "${BASE_URL}/predict-v2?match_id=${MATCH_ID}" \
  -H "X-API-Key: ${API_KEY}" | jq '.'

# Test 3: Pretty print prediction summary
echo -e "\n3️⃣ V2 Prediction Summary:"
curl -s "${BASE_URL}/predict-v2?match_id=${MATCH_ID}" \
  -H "X-API-Key: ${API_KEY}" | jq '{
    match: .match_info,
    outcome: .prediction.predicted_outcome,
    confidence: (.prediction.confidence * 100 | tostring + "%"),
    ev: (.prediction.expected_value * 100 | tostring + "%"),
    probabilities: {
      home: (.prediction.probabilities.home * 100 | tostring + "%"),
      draw: (.prediction.probabilities.draw * 100 | tostring + "%"),
      away: (.prediction.probabilities.away * 100 | tostring + "%")
    }
  }'

# Test 4: Check rate limiting
echo -e "\n4️⃣ Testing rate limiting (10 rapid requests)..."
for i in {1..10}; do
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${BASE_URL}/predict-v2?match_id=${MATCH_ID}" \
    -H "X-API-Key: ${API_KEY}")
  echo "Request $i: HTTP $STATUS"
done

echo -e "\n✅ Tests complete!\n"
