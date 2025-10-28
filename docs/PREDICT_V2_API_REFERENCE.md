# /predict-v2 API Reference

## Endpoint
```
POST /predict-v2
```

## Authentication
Requires API key in `Authorization` header:
```
Authorization: Bearer betgenius_secure_key_2024
```

## Request Body
```json
{
  "match_id": 1444554,
  "include_analysis": true,
  "include_additional_markets": false
}
```

### Parameters
- `match_id` (integer, required) - Match identifier
- `include_analysis` (boolean, optional, default: true) - Include AI analysis
- `include_additional_markets` (boolean, optional) - Accepted but not used

---

## Response Structure

### ✅ Success Response (HTTP 200)
**Returned when match qualifies for V2 SELECT:**
- `conf_v2 >= 0.62` (confidence threshold)
- `ev_live > 0` (positive expected value)

```json
{
  "match_info": {
    "match_id": 1444554,
    "home_team": "Arsenal",
    "away_team": "Chelsea",
    "venue": "Emirates Stadium",
    "date": "2025-10-29T15:00:00+00:00",
    "league": "Premier League"
  },
  "predictions": {
    "home_win": 0.650,
    "draw": 0.220,
    "away_win": 0.130,
    "confidence": 0.650,
    "recommended_bet": "home_win",
    "recommendation_tone": "confident",
    "ev_live": 0.095
  },
  "model_info": {
    "type": "v2_lightgbm_select",
    "version": "1.0.0",
    "performance": "75.9% hit rate @ 17.3% coverage",
    "confidence_threshold": 0.62,
    "bookmaker_count": 12
  },
  "comprehensive_analysis": {
    "explanation": "Arsenal shows strong home advantage...",
    "confidence_factors": [
      "Home form: 4W-1D in last 5",
      "Head-to-head dominance: 3-0-2 vs Chelsea",
      "Key players available"
    ],
    "betting_recommendations": {
      "primary": "Home Win @ 1.54",
      "risk_level": "Low"
    },
    "risk_assessment": "Low",
    "team_analysis": { ... },
    "ai_summary": "Strong home win opportunity with 9.5% edge"
  },
  "processing_time": 1.234,
  "timestamp": "2025-10-28T22:35:00.123456"
}
```

### ❌ Not Qualified Response (HTTP 403)
**Returned when match doesn't meet V2 SELECT criteria:**

```json
{
  "detail": {
    "error": "Not eligible for V2 Select",
    "reason": "Match doesn't meet high-confidence criteria",
    "conf_v2": 0.520,
    "ev_live": -0.037,
    "threshold": {
      "min_conf": 0.62,
      "min_ev": 0.0
    },
    "suggestion": "Try /predict for standard predictions or check /market"
  }
}
```

### 🔍 Other Error Responses

**404 - Match Not Found:**
```json
{
  "detail": "Match 1444554 not found"
}
```

**422 - No Market Data:**
```json
{
  "detail": "No market data available"
}
```

**401 - Unauthorized:**
```json
{
  "detail": "Invalid or missing API key"
}
```

---

## Field Descriptions

### `predictions` Object
| Field | Type | Description |
|-------|------|-------------|
| `home_win` | float | Probability of home win (0.000-1.000) |
| `draw` | float | Probability of draw (0.000-1.000) |
| `away_win` | float | Probability of away win (0.000-1.000) |
| `confidence` | float | Model confidence (matches highest probability) |
| `recommended_bet` | string | One of: `"home_win"`, `"draw"`, `"away_win"` |
| `recommendation_tone` | string | Always `"confident"` for V2 SELECT (≥0.62) |
| `ev_live` | float | Expected value vs market (positive = edge) |

### `model_info` Object
| Field | Type | Description |
|-------|------|-------------|
| `type` | string | Always `"v2_lightgbm_select"` |
| `version` | string | Model version |
| `performance` | string | Historical performance metrics |
| `confidence_threshold` | float | Minimum confidence for V2 SELECT (0.62) |
| `bookmaker_count` | integer | Number of bookmakers in consensus |

---

## Comparison: /predict vs /predict-v2

| Feature | /predict | /predict-v2 |
|---------|----------|-------------|
| **Model** | V1 Simple Weighted Consensus | V2 LightGBM (5-fold ensemble) |
| **Coverage** | 100% of matches | 15-25% (high-confidence only) |
| **Accuracy** | 54.3% (3-way) | 75.9% @ 62% threshold |
| **Confidence Filter** | None | conf ≥ 0.62, EV > 0 |
| **Response Format** | ✅ Consistent | ✅ Consistent (aligned) |
| **AI Analysis** | Optional | Optional |
| **Tier** | Free (authenticated) | Premium (authenticated) |

---

## Usage Examples

### Basic Request (No AI)
```bash
curl -X POST "http://localhost:8000/predict-v2" \
  -H "Authorization: Bearer betgenius_secure_key_2024" \
  -H "Content-Type: application/json" \
  -d '{
    "match_id": 1444554,
    "include_analysis": false
  }'
```

### Full Request (With AI Analysis)
```bash
curl -X POST "http://localhost:8000/predict-v2" \
  -H "Authorization: Bearer betgenius_secure_key_2024" \
  -H "Content-Type: application/json" \
  -d '{
    "match_id": 1444554,
    "include_analysis": true
  }'
```

### Finding Eligible Matches
```bash
# First, check market board for V2 predictions
curl -H "Authorization: Bearer betgenius_secure_key_2024" \
  "http://localhost:8000/market"

# Look for matches with:
# - v2_confidence >= 0.62
# - v2_ev > 0
# Then use that match_id in /predict-v2
```

---

## Response Structure Alignment

✅ **ALIGNED with /predict endpoint** (as of Oct 28, 2025)

Both endpoints now return identical structure for:
- `match_info` object
- `predictions` object (including `recommended_bet` and `recommendation_tone`)
- `model_info` object (with type-specific fields)
- `comprehensive_analysis` object (when `include_analysis: true`)

**V2-Specific Fields:**
- `predictions.ev_live` - Expected value over market
- `model_info.confidence_threshold` - V2 SELECT threshold (0.62)

---

## Quality Gates (V2 SELECT Criteria)

A match qualifies for V2 SELECT when:

1. **Confidence** ≥ 0.62 (62%)
2. **Expected Value** > 0 (positive edge over market)
3. **Market Data** available (minimum 3 bookmakers)

Approximately **15-25% of matches** qualify for V2 SELECT.

---

**Last Updated:** October 28, 2025  
**Status:** ✅ Production Ready
