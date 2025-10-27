# BetGenius AI - API Examples & Frontend Integration

This directory contains complete examples for testing and integrating the BetGenius AI V2 prediction API.

## 📁 Files Overview

### Testing Examples
- **`test_predict_v2.py`** - Comprehensive Python test suite with 4 test scenarios
- **`test_predict_v2.sh`** - Quick bash/curl script for command-line testing
- **`quickstart.html`** - Standalone HTML demo (no build required!)

### Frontend Integration
- **`frontend_integration.js`** - Production-ready React/JavaScript components
- **`frontend_styles.css`** - Complete CSS styling for match cards

### Documentation
- **`../docs/V2_DATA_COLLECTION_STRATEGY.md`** - Data collection recommendations

---

## 🚀 Quick Start

### Option 1: HTML Demo (Fastest)
```bash
# Open in browser
open examples/quickstart.html

# Or serve with Python
cd examples
python3 -m http.server 8080
# Visit http://localhost:8080/quickstart.html
```

### Option 2: Python Test Suite
```bash
# Install requests library
pip install requests

# Edit API key in test_predict_v2.py
# Then run:
python examples/test_predict_v2.py
```

### Option 3: Bash/Curl
```bash
# Edit API key in test_predict_v2.sh
chmod +x examples/test_predict_v2.sh
./examples/test_predict_v2.sh
```

---

## 🧪 Test Scenarios Covered

### 1. Single Match V2 Prediction
```python
response = requests.get(
    f"{BASE_URL}/predict-v2?match_id=1379062",
    headers={"X-API-Key": API_KEY}
)
```

**Expected Responses:**
- `200 OK` - V2 prediction available (conf >= 62%, EV > 0)
- `404 Not Found` - Below quality threshold
- `429 Too Many Requests` - Rate limit exceeded

### 2. Batch Testing
Tests multiple matches to check V2 availability rate.

**Typical Results:**
- V2 Available: 15-25% of matches
- Why selective? V2 only returns high-confidence predictions

### 3. V1 vs V2 Comparison
Shows both models side-by-side using `/market` endpoint.

**Key Differences:**
- V1: Always available, 54.3% accuracy
- V2: Selective, 70% accuracy when available

### 4. Error Handling
Tests invalid inputs, missing auth, rate limiting.

---

## 🎨 Frontend Integration Guide

### Step 1: Install API Client

```javascript
import { BetGeniusAPI } from './examples/frontend_integration.js';

const api = new BetGeniusAPI('your_api_key_here');
```

### Step 2: Fetch Market Data

```javascript
// Get all upcoming matches with V1 and V2 predictions
const matches = await api.getMarket();

matches.forEach(match => {
  console.log(`${match.home_team} vs ${match.away_team}`);
  
  // V1 always present
  if (match.v1_prediction) {
    console.log('V1:', match.v1_prediction.predicted_outcome);
  }
  
  // V2 selective
  if (match.v2_prediction) {
    console.log('V2:', match.v2_prediction.predicted_outcome);
    console.log('Confidence:', match.v2_prediction.confidence);
  }
});
```

### Step 3: Get Premium V2 Prediction

```javascript
// For premium users - get detailed V2 analysis
const prediction = await api.getPredictionV2(matchId);

if (prediction.available) {
  console.log('Outcome:', prediction.prediction.predicted_outcome);
  console.log('Confidence:', prediction.prediction.confidence);
  console.log('EV:', prediction.prediction.expected_value);
  console.log('AI:', prediction.ai_analysis.summary);
} else {
  console.log('V2 not available for this match');
}
```

### Step 4: Use React Components

```jsx
import { MatchCard, MarketBoard } from './examples/frontend_integration.js';

function App() {
  return (
    <div>
      <MarketBoard />
    </div>
  );
}
```

---

## 📊 API Response Examples

### `/market` Response
```json
[
  {
    "match_id": 1379062,
    "home_team": "Arsenal",
    "away_team": "Chelsea",
    "kickoff_at": "2025-11-02T15:00:00Z",
    "league_name": "Premier League",
    "home_team_logo": "https://...",
    "away_team_logo": "https://...",
    
    "v1_prediction": {
      "predicted_outcome": "H",
      "home_prob": 0.52,
      "draw_prob": 0.26,
      "away_prob": 0.22
    },
    
    "v2_prediction": {
      "predicted_outcome": "H",
      "confidence": 0.68,
      "expected_value": 0.035,
      "home_prob": 0.58,
      "draw_prob": 0.24,
      "away_prob": 0.18
    },
    
    "best_odds": {
      "home": 1.95,
      "draw": 3.60,
      "away": 4.20
    }
  }
]
```

### `/predict-v2` Response (200 OK)
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
    "summary": "Arsenal's strong home form and Chelsea's defensive vulnerabilities suggest a home win. The model shows 68% confidence.",
    "key_factors": [
      "Arsenal unbeaten in last 8 home matches",
      "Chelsea conceded 12 goals in last 5 away games",
      "H2H: Arsenal won 3 of last 5 meetings"
    ],
    "risk_assessment": "Medium-Low"
  },
  
  "timestamp": "2025-10-27T20:30:00Z"
}
```

### `/predict-v2` Response (404 Not Found)
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

---

## 🔐 Authentication

All endpoints require API key authentication:

```bash
# HTTP Header
X-API-Key: your_api_key_here

# Example
curl -H "X-API-Key: abc123" http://localhost:8000/market
```

---

## ⚡ Rate Limits

| Endpoint | Rate Limit | Notes |
|----------|-----------|-------|
| `/market` | 60/min | Includes V1 + V2 predictions |
| `/predict` | 60/min | V1 predictions (free tier) |
| `/predict-v2` | 60/min | V2 SELECT (premium tier) |

**Rate Limit Response:**
```json
{
  "error": "Rate limit exceeded: 60 per 1 minute"
}
```

**Handling Rate Limits:**
```javascript
if (response.status === 429) {
  const retryAfter = 60; // seconds
  await sleep(retryAfter * 1000);
  // Retry request
}
```

---

## 🎯 V2 SELECT Criteria

V2 predictions are only returned when BOTH criteria are met:

1. **Confidence >= 62%** - Model must be highly confident
2. **Expected Value > 0%** - Positive expected value vs best odds

**Why?** This ensures you only get the best predictions (70% accuracy rate).

**Typical Availability:** 15-25% of all matches

---

## 💡 Best Practices

### 1. Cache Market Data
```javascript
// Don't spam the API - cache for 60 seconds
let cachedMarket = null;
let cacheTime = 0;

async function getMarketCached() {
  if (Date.now() - cacheTime < 60000) {
    return cachedMarket;
  }
  
  cachedMarket = await api.getMarket();
  cacheTime = Date.now();
  return cachedMarket;
}
```

### 2. Handle Errors Gracefully
```javascript
try {
  const prediction = await api.getPredictionV2(matchId);
} catch (error) {
  if (error.message.includes('Rate limit')) {
    // Show "Please wait" message
  } else if (error.message.includes('404')) {
    // Show V1 prediction instead
  } else {
    // Show generic error
  }
}
```

### 3. Show Loading States
```javascript
const [loading, setLoading] = useState(true);
const [data, setData] = useState(null);

useEffect(() => {
  setLoading(true);
  api.getMarket()
    .then(setData)
    .finally(() => setLoading(false));
}, []);

if (loading) return <Spinner />;
```

### 4. Implement Retry Logic
```javascript
async function fetchWithRetry(fn, maxRetries = 3) {
  for (let i = 0; i < maxRetries; i++) {
    try {
      return await fn();
    } catch (error) {
      if (i === maxRetries - 1) throw error;
      await sleep(1000 * (i + 1)); // Exponential backoff
    }
  }
}
```

---

## 🔍 Troubleshooting

### "Invalid API Key" (403)
- Check API key is correct
- Ensure header name is `X-API-Key` (case-sensitive)
- Verify API key has active subscription

### "No V2 prediction available" (404)
- This is normal! V2 is selective (70% accuracy gate)
- Only 15-25% of matches meet quality criteria
- Use `/predict` endpoint for V1 prediction

### "Rate limit exceeded" (429)
- Wait 60 seconds before retrying
- Implement caching to reduce requests
- Consider upgrading API plan

### CORS errors in browser
```javascript
// If running locally, ensure backend has CORS enabled
// Or use a proxy during development

// FastAPI backend (already configured):
app.add_middleware(
  CORSMiddleware,
  allow_origins=["*"],
  allow_methods=["*"],
  allow_headers=["*"],
)
```

---

## 📚 Additional Resources

- **Main Documentation:** `../replit.md`
- **Data Collection Strategy:** `../docs/V2_DATA_COLLECTION_STRATEGY.md`
- **Operations Runbook:** `../docs/CLV_OPERATIONS_RUNBOOK.md`
- **Phase 2 Summary:** `../PHASE_2_OBSERVABILITY_COMPLETE.md`

---

## 🤝 Support

For issues or questions:
1. Check this README first
2. Review API response error messages
3. Test with example scripts
4. Check server logs for details

---

**Happy building! 🚀**
