# Curl Commands for BetGenius AI API

## 🔑 Setup

Replace `YOUR_API_KEY` with your actual API key in all commands below.

```bash
# Set your API key as environment variable (optional, for convenience)
export API_KEY="your_api_key_here"
export BASE_URL="http://localhost:8000"
```

---

## 📊 `/predict-v2` - V2 SELECT Predictions

### Basic Usage

```bash
curl -X GET "http://localhost:8000/predict-v2?match_id=1379062" \
  -H "X-API-Key: YOUR_API_KEY"
```

### With Environment Variable

```bash
curl -X GET "${BASE_URL}/predict-v2?match_id=1379062" \
  -H "X-API-Key: ${API_KEY}"
```

### Pretty Print with jq

```bash
curl -s "http://localhost:8000/predict-v2?match_id=1379062" \
  -H "X-API-Key: YOUR_API_KEY" | jq '.'
```

### Extract Specific Fields

```bash
# Get just the prediction outcome
curl -s "http://localhost:8000/predict-v2?match_id=1379062" \
  -H "X-API-Key: YOUR_API_KEY" | jq -r '.prediction.predicted_outcome'

# Get confidence and EV
curl -s "http://localhost:8000/predict-v2?match_id=1379062" \
  -H "X-API-Key: YOUR_API_KEY" | jq '{
    outcome: .prediction.predicted_outcome,
    confidence: (.prediction.confidence * 100 | tostring + "%"),
    ev: (.prediction.expected_value * 100 | tostring + "%")
  }'

# Get probabilities
curl -s "http://localhost:8000/predict-v2?match_id=1379062" \
  -H "X-API-Key: YOUR_API_KEY" | jq '.prediction.probabilities'
```

### Full Summary

```bash
curl -s "http://localhost:8000/predict-v2?match_id=1379062" \
  -H "X-API-Key: YOUR_API_KEY" | jq '{
    match: .match_info,
    outcome: .prediction.predicted_outcome,
    confidence: (.prediction.confidence * 100 | tostring + "%"),
    ev: (.prediction.expected_value * 100 | tostring + "%"),
    probabilities: {
      home: (.prediction.probabilities.home * 100 | tostring + "%"),
      draw: (.prediction.probabilities.draw * 100 | tostring + "%"),
      away: (.prediction.probabilities.away * 100 | tostring + "%")
    },
    ai_summary: .ai_analysis.summary
  }'
```

---

## 📋 `/market` - All Upcoming Matches (V1 + V2)

### Get All Matches

```bash
curl -X GET "http://localhost:8000/market" \
  -H "X-API-Key: YOUR_API_KEY" | jq '.'
```

### List Match IDs and Teams

```bash
curl -s "http://localhost:8000/market" \
  -H "X-API-Key: YOUR_API_KEY" | jq -r '.[] | "\(.match_id): \(.home_team) vs \(.away_team)"'
```

### Show Matches with V2 Available

```bash
curl -s "http://localhost:8000/market" \
  -H "X-API-Key: YOUR_API_KEY" | jq '.[] | select(.v2_prediction != null) | {
    match_id: .match_id,
    teams: "\(.home_team) vs \(.away_team)",
    v2_outcome: .v2_prediction.predicted_outcome,
    v2_confidence: (.v2_prediction.confidence * 100 | tostring + "%")
  }'
```

### Compare V1 vs V2

```bash
curl -s "http://localhost:8000/market" \
  -H "X-API-Key: YOUR_API_KEY" | jq '.[] | select(.v2_prediction != null) | {
    match: "\(.home_team) vs \(.away_team)",
    v1: .v1_prediction.predicted_outcome,
    v2: .v2_prediction.predicted_outcome,
    v2_confidence: (.v2_prediction.confidence * 100)
  }'
```

---

## 🥈 `/predict` - V1 Consensus Predictions

### Basic Usage

```bash
curl -X GET "http://localhost:8000/predict?match_id=1379062" \
  -H "X-API-Key: YOUR_API_KEY" | jq '.'
```

### With AI Analysis (Optional)

```bash
curl -X GET "http://localhost:8000/predict?match_id=1379062&include_ai=true" \
  -H "X-API-Key: YOUR_API_KEY" | jq '.'
```

---

## 🔧 Example Response Handling

### Check if V2 is Available (404 vs 200)

```bash
# This script checks status code
MATCH_ID=1379062
STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
  "http://localhost:8000/predict-v2?match_id=${MATCH_ID}" \
  -H "X-API-Key: YOUR_API_KEY")

if [ "$STATUS" = "200" ]; then
  echo "✅ V2 prediction available for match ${MATCH_ID}"
  curl -s "http://localhost:8000/predict-v2?match_id=${MATCH_ID}" \
    -H "X-API-Key: YOUR_API_KEY" | jq '.'
elif [ "$STATUS" = "404" ]; then
  echo "⚠️  V2 prediction not available (below quality threshold)"
  echo "💡 Falling back to V1..."
  curl -s "http://localhost:8000/predict?match_id=${MATCH_ID}" \
    -H "X-API-Key: YOUR_API_KEY" | jq '.'
else
  echo "❌ Error: HTTP ${STATUS}"
fi
```

### Loop Through All Matches

```bash
# Get all match IDs
MATCH_IDS=$(curl -s "http://localhost:8000/market" \
  -H "X-API-Key: YOUR_API_KEY" | jq -r '.[].match_id')

# Test V2 for each match
for MATCH_ID in $MATCH_IDS; do
  echo "Testing match ${MATCH_ID}..."
  curl -s "http://localhost:8000/predict-v2?match_id=${MATCH_ID}" \
    -H "X-API-Key: YOUR_API_KEY" | jq -r '
      if .prediction then
        "✅ V2 Available: \(.prediction.predicted_outcome) (\(.prediction.confidence * 100)%)"
      else
        "⚠️  V2 Unavailable"
      end
    '
done
```

---

## 📊 Expected Responses

### Success (200 OK)

```json
{
  "match_info": {
    "match_id": 1379062,
    "home_team": "Arsenal",
    "away_team": "Chelsea",
    "league": "Premier League",
    "kickoff_at": "2025-11-02T15:00:00Z"
  },
  "prediction": {
    "predicted_outcome": "H",
    "confidence": 0.68,
    "expected_value": 0.035,
    "probabilities": {
      "home": 0.58,
      "draw": 0.24,
      "away": 0.18
    },
    "model_version": "v2_lightgbm_enriched"
  },
  "ai_analysis": {
    "summary": "Arsenal's strong home form suggests a home win...",
    "key_factors": ["Arsenal unbeaten in 8 home matches", "..."],
    "risk_assessment": "Medium-Low"
  },
  "timestamp": "2025-10-27T20:30:00Z"
}
```

### Not Available (404)

```json
{
  "error": "No V2 prediction available",
  "reason": "Match does not meet V2 SELECT quality criteria",
  "criteria": {
    "required_confidence": 0.62,
    "required_ev": 0.0,
    "actual_confidence": 0.58,
    "actual_ev": -0.012
  },
  "suggestion": "Use /predict endpoint for V1 prediction"
}
```

### Rate Limit (429)

```json
{
  "error": "Rate limit exceeded: 60 per 1 minute"
}
```

### Invalid Match ID (404)

```json
{
  "detail": "Match not found"
}
```

### Authentication Error (403)

```json
{
  "detail": "Invalid API key"
}
```

---

## 🎯 Quick Reference Card

| Endpoint | Method | Purpose | Rate Limit |
|----------|--------|---------|------------|
| `/market` | GET | All matches (V1 + V2) | 60/min |
| `/predict` | GET | V1 prediction (free) | 60/min |
| `/predict-v2` | GET | V2 SELECT (premium) | 60/min |

### Parameters

| Endpoint | Parameter | Required | Description |
|----------|-----------|----------|-------------|
| `/predict` | `match_id` | Yes | Match ID to predict |
| `/predict` | `include_ai` | No | Include AI analysis (default: false) |
| `/predict-v2` | `match_id` | Yes | Match ID to predict |

### Headers

All endpoints require:
```
X-API-Key: your_api_key_here
```

---

## 💡 Tips

### Save Response to File

```bash
curl -s "http://localhost:8000/predict-v2?match_id=1379062" \
  -H "X-API-Key: YOUR_API_KEY" > prediction.json
```

### Time the Request

```bash
time curl -s "http://localhost:8000/predict-v2?match_id=1379062" \
  -H "X-API-Key: YOUR_API_KEY" | jq '.'
```

### Check Response Headers

```bash
curl -i "http://localhost:8000/predict-v2?match_id=1379062" \
  -H "X-API-Key: YOUR_API_KEY"
```

### Verbose Output (Debug)

```bash
curl -v "http://localhost:8000/predict-v2?match_id=1379062" \
  -H "X-API-Key: YOUR_API_KEY"
```

---

## 🔄 Production URL

When using your deployed app, replace `localhost:8000` with your production URL:

```bash
# Development
export BASE_URL="http://localhost:8000"

# Production (example)
export BASE_URL="https://your-app.repl.co"

# Then use
curl "${BASE_URL}/predict-v2?match_id=1379062" \
  -H "X-API-Key: YOUR_API_KEY"
```
