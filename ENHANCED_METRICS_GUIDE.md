# Enhanced Metrics & CLV Analysis Guide

## 🎯 Overview

The enhanced metrics system uses the `odds_accuracy_evaluation` view for comprehensive accuracy tracking and CLV (Closing Line Value) analysis.

**Key Advantages:**
- ✅ Unified view of snapshot odds + actual results
- ✅ CLV calculation when closing odds available
- ✅ Automatic Brier score, LogLoss, and hit rate computation
- ✅ Model performance grading (A+ to F)

---

## 📊 API Endpoints

### 1. Enhanced Evaluation (NEW)
**Endpoint:** `GET /metrics/evaluation`

Uses `odds_accuracy_evaluation` view for accuracy + CLV analysis.

**Parameters:**
- `league` (optional): Filter by league name (e.g., "Premier League")
- `window` (optional): Time window - `7d`, `14d`, `30d`, `90d`, `all` (default: `30d`)
- `include_clv` (optional): Include CLV analysis (default: `true`)

**Response:**
```json
{
  "status": "success",
  "league": "All Leagues",
  "window": "30d",
  "sample_size": 48,
  "accuracy_metrics": {
    "brier_score": 0.1912,
    "log_loss": 0.8973,
    "hit_rate": 0.5625,
    "model_grade": "B"
  },
  "clv_analysis": {
    "matches_with_closing_odds": 20,
    "avg_clv_edge": 0.025,
    "avg_clv_percent": 3.5,
    "positive_clv_rate": 0.65,
    "interpretation": "Excellent - strong positive CLV"
  }
}
```

### 2. Legacy Metrics Summary
**Endpoint:** `GET /metrics/summary`

Uses `metrics_per_match` table (manual predictions only).

### 3. Add Match Result
**Endpoint:** `POST /metrics/result`

Manually add match result for accuracy calculation.

---

## 🔧 Testing Commands

### Basic Tests

```bash
# 1. All leagues, all time
curl "http://localhost:8000/metrics/evaluation?window=all" \
  -H "Authorization: Bearer betgenius_secure_key_2024"

# 2. Last 30 days (default)
curl "http://localhost:8000/metrics/evaluation" \
  -H "Authorization: Bearer betgenius_secure_key_2024"

# 3. Last 7 days
curl "http://localhost:8000/metrics/evaluation?window=7d" \
  -H "Authorization: Bearer betgenius_secure_key_2024"

# 4. Specific league
curl "http://localhost:8000/metrics/evaluation?league=Premier%20League&window=all" \
  -H "Authorization: Bearer betgenius_secure_key_2024"

# 5. Without CLV analysis
curl "http://localhost:8000/metrics/evaluation?include_clv=false&window=all" \
  -H "Authorization: Bearer betgenius_secure_key_2024"
```

### Pretty Print (with jq)

```bash
curl -s "http://localhost:8000/metrics/evaluation?window=all" \
  -H "Authorization: Bearer betgenius_secure_key_2024" | jq '.'
```

### Add Single Match Result

```bash
curl -X POST "http://localhost:8000/metrics/result" \
  -H "Authorization: Bearer betgenius_secure_key_2024" \
  -H "Content-Type: application/json" \
  -d '{
    "match_id": 1451180,
    "home_goals": 0,
    "away_goals": 2,
    "league": "UEFA Europa League"
  }'
```

---

## 🚀 Manual Scripts

### 1. Test Enhanced Metrics (Quick)

```bash
./test_enhanced_metrics.sh
```

Runs all endpoint variations and displays results.

### 2. Batch Add Match Results

```bash
python add_match_results_batch.py
```

**What it does:**
1. Finds completed matches needing results
2. Fetches final scores from API-Football
3. Submits to `/metrics/result` endpoint
4. Updates accuracy metrics automatically

**Output:**
```
🔄 BATCH MATCH RESULTS PROCESSOR
==================================================

📋 Fetching matches needing results...
📊 Found 15 matches needing results

[1/15] Processing match 1451180...
  ✅ Result: 0-2 (FT)
  ✅ Submitted successfully

...

✅ Complete! Added 15 match results
```

### 3. Calculate Metrics (Automated - runs every 6 hours)

```bash
python calculate_metrics_results.py --limit 50
```

This runs automatically via scheduler at:
- 03:00 UTC
- 09:00 UTC
- 15:00 UTC
- 21:00 UTC

---

## 📈 Metrics Interpretation

### Brier Score
- **Range:** 0 (perfect) to 1 (worst)
- **Good:** < 0.20
- **Excellent:** < 0.15

### Log Loss
- **Range:** 0+ (lower is better)
- **Good:** < 1.0
- **Excellent:** < 0.85

### Hit Rate
- **Range:** 0 to 1
- **Good:** > 0.55
- **Excellent:** > 0.60

### Model Grade
- **A+/A/A-:** Exceptional performance
- **B+/B/B-:** Good performance
- **C+/C/C-:** Average performance
- **D/F:** Needs improvement

### CLV Analysis

**avg_clv_percent interpretation:**
- `> 5%`: Exceptional - significantly beating closing line
- `2-5%`: Excellent - strong positive CLV
- `0-2%`: Positive - beating closing line
- `-2 to 0%`: Neutral - tracking closing line
- `< -2%`: Negative - below closing line

---

## 🔄 Current Status

**Last Run:** Check with:
```bash
curl "http://localhost:8000/metrics/evaluation?window=all" \
  -H "Authorization: Bearer betgenius_secure_key_2024" | python -m json.tool
```

**Current Metrics:**
- 48 matches evaluated
- Brier Score: 0.5713 (needs improvement)
- LogLoss: 0.8973 (good)
- Hit Rate: 56.25% (acceptable)
- Model Grade: B-
- Closing odds: Not yet available

**Next Steps:**
1. Collect more closing odds data
2. Run batch result processor regularly
3. Monitor CLV when closing odds available
4. Track improvement over time

---

## 💡 Tips

1. **For accurate CLV:** Ensure closing line sampler is running
2. **For better metrics:** Add more match results via batch script
3. **For league analysis:** Use `?league=League%20Name` parameter
4. **For recent performance:** Use `?window=7d` or `?window=14d`
