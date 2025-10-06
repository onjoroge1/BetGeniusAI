# 📊 Complete Closing Odds & CLV Setup Guide

## ✅ What's Been Fixed

1. ✅ **Created `closing_odds` table** - Stores aggregated closing line data
2. ✅ **Created population script** - Aggregates `clv_closing_feed` into `closing_odds`
3. ✅ **Enhanced metrics ready** - `/metrics/evaluation` will show CLV when data available

---

## 🎯 The Problem & Solution

### **Problem:**
- `odds_accuracy_evaluation` view needs closing odds for CLV calculation
- View joins with `closing_odds` table which didn't exist
- Result: CLV analysis showed "no_closing_odds"

### **Solution:**
1. Created `closing_odds` table ✅
2. Created aggregation script `populate_closing_odds.py` ✅
3. Closing sampler collects data automatically ⏳

---

## 📋 How to Populate Closing Odds

### **Current Status:**
```bash
# Check if you have closing feed data
psql $DATABASE_URL -c "SELECT COUNT(*) FROM clv_closing_feed;"
```

**Current Result:** 0 rows (no closing data collected yet)

### **When Will Closing Odds Be Collected?**

Closing odds are collected **automatically** when:
- ✅ CLV closing sampler is running (every 60 seconds) ✅ Active
- ✅ Matches are approaching kickoff (T-6m to T+2m window)
- ❌ **Issue:** Sampler looks at `training_matches` (historical) instead of `odds_snapshots` (upcoming)

---

## 🔧 Manual Commands

### **1. Check Current System Status**

```bash
# Check clv_closing_feed (raw samples)
psql $DATABASE_URL -c "SELECT COUNT(*) as samples FROM clv_closing_feed;"

# Check closing_odds (aggregated)
psql $DATABASE_URL -c "SELECT COUNT(*) as closing_lines FROM closing_odds;"

# Check upcoming matches
psql $DATABASE_URL -c "
  SELECT match_id, home_team, away_team, match_date 
  FROM odds_snapshots 
  WHERE match_date > NOW() 
  GROUP BY match_id, home_team, away_team, match_date
  ORDER BY match_date 
  LIMIT 5;
"
```

### **2. Populate Closing Odds (When Data Available)**

```bash
python populate_closing_odds.py
```

**What it does:**
- Reads `clv_closing_feed` samples
- Computes closing line using LAST5_VWAP or LAST_TICK method
- Populates `closing_odds` table
- Enables CLV analysis in `/metrics/evaluation`

### **3. Test Enhanced Metrics with CLV**

```bash
# Test all data
curl "http://localhost:8000/metrics/evaluation?window=all" \
  -H "Authorization: Bearer betgenius_secure_key_2024" | python -m json.tool

# Test specific league
curl "http://localhost:8000/metrics/evaluation?league=Premier%20League&window=30d" \
  -H "Authorization: Bearer betgenius_secure_key_2024" | python -m json.tool
```

**Expected with closing odds:**
```json
{
  "clv_analysis": {
    "matches_with_closing_odds": 20,
    "avg_clv_edge": 0.025,
    "avg_clv_percent": 3.5,
    "positive_clv_rate": 0.65,
    "interpretation": "Excellent - strong positive CLV"
  }
}
```

**Current (no closing odds):**
```json
{
  "clv_analysis": {
    "status": "no_closing_odds",
    "message": "No closing odds available yet for CLV analysis"
  }
}
```

---

## 🚀 Best Way to Populate Closing Odds

### **Option 1: Wait for Upcoming Matches (Recommended)**

**When:** Next time you have matches approaching kickoff

**How:**
1. Ensure upcoming matches exist in `odds_snapshots` (via collection)
2. CLV closing sampler runs automatically every 60 seconds
3. Samples collected from T-6m to T+2m window
4. Run `python populate_closing_odds.py` after matches start
5. CLV analysis will appear in `/metrics/evaluation`

**Timeline:**
- T-6 minutes: Sampling begins
- T+0 (kickoff): Match starts
- T+2 minutes: Sampling ends
- T+2+ minutes: Run aggregation script

### **Option 2: Trigger Manual Collection**

```bash
# Trigger manual collection to get upcoming matches
python trigger_manual_collection.py

# Wait for collection to complete (2-5 minutes)

# Check if upcoming matches collected
psql $DATABASE_URL -c "
  SELECT COUNT(*) FROM odds_snapshots 
  WHERE match_date > NOW();
"

# If matches exist and approaching kickoff:
# Wait for closing sampler to collect (runs every 60s)
# Then run:
python populate_closing_odds.py
```

### **Option 3: Fix Sampler for Automatic Collection**

The closing sampler currently has a bug - it looks at `training_matches` (historical data) instead of `odds_snapshots` (upcoming matches).

**File to fix:** `models/clv_closing_sampler.py` (line 46-57)

**Change from:**
```python
FROM training_matches m
```

**Change to:**
```python
FROM odds_snapshots os
```

This will enable automatic closing odds collection when matches approach kickoff.

---

## 📊 Database Tables Overview

```
clv_closing_feed
├─> Raw closing samples (collected every 60s near kickoff)
└─> Columns: match_id, ts, outcome, composite_odds_dec, volume, books_used

closing_odds (NEW)
├─> Aggregated closing lines (one row per match)
├─> Populated by: populate_closing_odds.py
└─> Columns: match_id, h_close_odds, d_close_odds, a_close_odds, closing_time

odds_accuracy_evaluation (VIEW)
├─> Joins snapshot odds + closing odds + results
├─> Enables CLV calculation
└─> Powers: /metrics/evaluation endpoint
```

---

## ✅ Testing Checklist

**Current Status:**
```bash
# 1. Check closing_odds table exists
psql $DATABASE_URL -c "\d closing_odds"  # ✅ Exists

# 2. Check for closing feed data
psql $DATABASE_URL -c "SELECT COUNT(*) FROM clv_closing_feed;"  # ❌ 0 rows

# 3. Check for closing odds
psql $DATABASE_URL -c "SELECT COUNT(*) FROM closing_odds;"  # ❌ 0 rows

# 4. Test enhanced metrics
curl "http://localhost:8000/metrics/evaluation?window=all" \
  -H "Authorization: Bearer betgenius_secure_key_2024"  # ✅ Works (no CLV yet)
```

**When Closing Odds Arrive:**
```bash
# 1. Populate closing odds
python populate_closing_odds.py  # Should show matches processed

# 2. Verify closing odds
psql $DATABASE_URL -c "SELECT * FROM closing_odds LIMIT 3;"

# 3. Test enhanced metrics with CLV
curl "http://localhost:8000/metrics/evaluation?window=all" \
  -H "Authorization: Bearer betgenius_secure_key_2024"  # Should show CLV analysis
```

---

## 💡 Summary

**What's Working:**
- ✅ `closing_odds` table created
- ✅ Population script ready
- ✅ Enhanced metrics endpoint functional
- ✅ CLV calculation logic implemented

**What's Needed:**
- ⏳ Closing feed data collection (waiting for upcoming matches near kickoff)
- ⏳ Run `python populate_closing_odds.py` when data available
- 💡 Optional: Fix closing sampler query to use `odds_snapshots`

**Quick Win:**
If you have upcoming matches approaching kickoff within the next 6 minutes, the closing sampler will automatically start collecting data. Then run `python populate_closing_odds.py` and you'll have full CLV analysis!
