# 🧪 Quick Test Guide - Enhanced Metrics & CLV

## ⚡ Quick Start

### 1. Test Enhanced Metrics Endpoint

```bash
# Basic test - all data
curl "http://localhost:8000/metrics/evaluation?window=all" \
  -H "Authorization: Bearer betgenius_secure_key_2024" | python -m json.tool

# With pretty formatting (if jq installed)
curl -s "http://localhost:8000/metrics/evaluation?window=all" \
  -H "Authorization: Bearer betgenius_secure_key_2024" | jq '.'
```

**Expected Output:**
```json
{
  "status": "success",
  "league": "All Leagues",
  "window": "all",
  "sample_size": 48,
  "accuracy_metrics": {
    "brier_score": 0.5713,
    "log_loss": 0.8973,
    "hit_rate": 0.5625,
    "model_grade": "B-"
  },
  "clv_analysis": {
    "status": "no_closing_odds",
    "message": "No closing odds available yet for CLV analysis"
  }
}
```

---

### 2. Run Automated Test Suite

```bash
./test_enhanced_metrics.sh
```

Tests all endpoint variations:
- All leagues, all time
- Last 30 days (default)
- Last 7 days
- Specific league filtering
- With/without CLV analysis

---

### 3. Add Match Results (Batch)

```bash
python add_match_results_batch.py
```

**What it does:**
1. Finds completed matches needing results
2. Fetches final scores from API-Football
3. Submits to `/metrics/result` endpoint
4. Shows progress for each match

---

## 📋 Individual Curl Commands

### Test Different Time Windows

```bash
# Last 7 days
curl "http://localhost:8000/metrics/evaluation?window=7d" \
  -H "Authorization: Bearer betgenius_secure_key_2024"

# Last 14 days
curl "http://localhost:8000/metrics/evaluation?window=14d" \
  -H "Authorization: Bearer betgenius_secure_key_2024"

# Last 30 days (default)
curl "http://localhost:8000/metrics/evaluation?window=30d" \
  -H "Authorization: Bearer betgenius_secure_key_2024"

# Last 90 days
curl "http://localhost:8000/metrics/evaluation?window=90d" \
  -H "Authorization: Bearer betgenius_secure_key_2024"

# All time
curl "http://localhost:8000/metrics/evaluation?window=all" \
  -H "Authorization: Bearer betgenius_secure_key_2024"
```

### Test League Filtering

```bash
# Premier League
curl "http://localhost:8000/metrics/evaluation?league=Premier%20League&window=all" \
  -H "Authorization: Bearer betgenius_secure_key_2024"

# Serie A
curl "http://localhost:8000/metrics/evaluation?league=Serie%20A&window=all" \
  -H "Authorization: Bearer betgenius_secure_key_2024"

# La Liga
curl "http://localhost:8000/metrics/evaluation?league=La%20Liga&window=all" \
  -H "Authorization: Bearer betgenius_secure_key_2024"
```

### Test CLV Options

```bash
# With CLV (default)
curl "http://localhost:8000/metrics/evaluation?include_clv=true&window=all" \
  -H "Authorization: Bearer betgenius_secure_key_2024"

# Without CLV
curl "http://localhost:8000/metrics/evaluation?include_clv=false&window=all" \
  -H "Authorization: Bearer betgenius_secure_key_2024"
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

## 📊 Compare Endpoints

### Enhanced (uses odds_accuracy_evaluation view)
```bash
curl "http://localhost:8000/metrics/evaluation?window=30d" \
  -H "Authorization: Bearer betgenius_secure_key_2024"
```

**Advantages:**
✅ Uses all odds snapshots (not just manual predictions)  
✅ Includes CLV analysis when closing odds available  
✅ Broader dataset coverage  
✅ Model performance grading  

### Legacy (uses metrics_per_match table)
```bash
curl "http://localhost:8000/metrics/summary?window=30d" \
  -H "Authorization: Bearer betgenius_secure_key_2024"
```

**Limitations:**
⚠️ Only manual predictions (via /predict endpoint)  
⚠️ No CLV analysis  
⚠️ Limited to explicitly predicted matches  

---

## 🎯 Manual Scripts Available

### 1. Test Enhanced Metrics
```bash
./test_enhanced_metrics.sh
```

### 2. Batch Add Results
```bash
python add_match_results_batch.py
```

### 3. Automated Metrics Calculation (runs every 6 hours automatically)
```bash
python calculate_metrics_results.py --limit 50
```

---

## ✅ Current System Status

**Database:**
- ✅ `odds_accuracy_evaluation` view active
- ✅ 48 matches with results
- ✅ Enhanced metrics endpoint working
- ⏳ Closing odds: Not yet available (CLV pending)

**Automation:**
- ✅ Metrics calculation: Every 6 hours (03:00, 09:00, 15:00, 21:00 UTC)
- ✅ CLV monitoring: Every 60 seconds
- ✅ Closing line sampler: Every 60 seconds

**Next Steps:**
1. Run `./test_enhanced_metrics.sh` to test all endpoints
2. Run `python add_match_results_batch.py` to add more results
3. Monitor closing odds collection for CLV analysis
4. Check metrics regularly with `/metrics/evaluation`
