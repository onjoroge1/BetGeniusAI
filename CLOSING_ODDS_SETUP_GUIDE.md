# Closing Odds Setup Guide

## 🎯 Problem Identified

The `odds_accuracy_evaluation` view needs closing odds for CLV analysis, but the `closing_odds` table was missing!

## ✅ What's Fixed

### 1. Created `closing_odds` Table
```sql
CREATE TABLE closing_odds (
    match_id BIGINT PRIMARY KEY,
    h_close_odds NUMERIC(10, 4),
    d_close_odds NUMERIC(10, 4),
    a_close_odds NUMERIC(10, 4),
    closing_time TIMESTAMPTZ,
    avg_books_closing INTEGER,
    method_used VARCHAR(20),
    samples_used INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### 2. Created Population Script
**`populate_closing_odds.py`** - Aggregates `clv_closing_feed` samples into `closing_odds` table

---

## 📊 How Closing Odds Work

### Data Flow:
```
1. CLV Closing Sampler (runs every 60s)
   ├─> Monitors matches near kickoff (T-6m to T+2m)
   ├─> Samples composite odds from odds_snapshots
   └─> Stores in clv_closing_feed table

2. Closing Odds Aggregator
   ├─> Reads clv_closing_feed samples
   ├─> Computes closing line (LAST5_VWAP or LAST_TICK)
   └─> Populates closing_odds table

3. odds_accuracy_evaluation view
   ├─> Joins closing_odds with snapshot odds
   ├─> Enables CLV calculation
   └─> Powers /metrics/evaluation endpoint
```

---

## 🚀 How to Populate Closing Odds

### Method 1: Manual Population (Current Data)

If you already have `clv_closing_feed` data:

```bash
python populate_closing_odds.py
```

**Output:**
```
🔄 POPULATE CLOSING ODDS TABLE
==================================================

📊 Found 15 matches with closing samples
⏳ Processing...

  ✅ Match 1234567: H=1.850 D=3.600 A=4.200 (LAST5_VWAP)
  ✅ Match 1234568: H=2.100 D=3.400 A=3.800 (LAST5_AVG)
  ...

==================================================
✅ Complete! Populated closing odds for 15/15 matches
```

### Method 2: Automatic Collection (Future Matches)

**Status:** Closing sampler runs every 60 seconds automatically

**How it works:**
1. **T-6 minutes before kickoff:** Sampler starts monitoring
2. **Every 60 seconds:** Collects composite odds → `clv_closing_feed`
3. **T+2 minutes after kickoff:** Sampling window closes
4. **Run aggregator:** Computes closing line → `closing_odds`

**Important:** Closing sampler currently looks at `training_matches` for upcoming matches, but upcoming matches are in `odds_snapshots`. This needs to be fixed for automatic collection.

---

## 🔧 Quick Fix for Automatic Collection

The closing sampler needs to check `odds_snapshots` instead of `training_matches`:

**File:** `models/clv_closing_sampler.py`

**Change this:**
```python
cursor.execute("""
    SELECT 
        m.match_id,
        COALESCE(lm.league_name, CAST(m.league_id AS text)) as league_name,
        m.match_date as kickoff_at
    FROM training_matches m              # ❌ Wrong table
    LEFT JOIN league_map lm ON m.league_id = lm.league_id
    WHERE m.match_date >= %s
      AND m.match_date <= %s
      AND m.match_date > NOW()          # This filters out all historical data
    ORDER BY m.match_date
""", (window_start, window_end))
```

**To this:**
```python
cursor.execute("""
    SELECT DISTINCT
        os.match_id,
        os.league,
        os.match_date as kickoff_at
    FROM odds_snapshots os
    WHERE os.match_date >= %s
      AND os.match_date <= %s
      AND os.match_date > NOW()
    ORDER BY os.match_date
""", (window_start, window_end))
```

---

## 📋 Testing Closing Odds

### 1. Check if closing odds exist:
```bash
psql $DATABASE_URL -c "SELECT COUNT(*) FROM closing_odds;"
```

### 2. View sample closing odds:
```bash
psql $DATABASE_URL -c "
  SELECT match_id, h_close_odds, d_close_odds, a_close_odds, 
         method_used, avg_books_closing 
  FROM closing_odds 
  LIMIT 5;
"
```

### 3. Test enhanced metrics with CLV:
```bash
curl "http://localhost:8000/metrics/evaluation?window=all" \
  -H "Authorization: Bearer betgenius_secure_key_2024" | python -m json.tool
```

**Expected (with closing odds):**
```json
{
  "clv_analysis": {
    "matches_with_closing_odds": 15,
    "avg_clv_edge": 0.025,
    "avg_clv_percent": 3.5,
    "positive_clv_rate": 0.65,
    "interpretation": "Excellent - strong positive CLV"
  }
}
```

---

## 🎯 Current Status

✅ **Fixed:**
- closing_odds table created
- Population script ready
- Enhanced metrics endpoint working

⏳ **Pending:**
- clv_closing_feed has 0 rows (no upcoming matches sampled yet)
- Closing sampler needs query fix to find upcoming matches
- Once fixed, closing odds will collect automatically

---

## 💡 Next Steps

1. **Immediate (if you have historical closing data):**
   ```bash
   python populate_closing_odds.py
   ```

2. **For future matches (fix sampler):**
   - Update `clv_closing_sampler.py` query to use `odds_snapshots`
   - Restart workflow
   - Wait for matches in T-6m to T+2m window
   - Closing odds will collect automatically

3. **Test CLV analysis:**
   ```bash
   curl "http://localhost:8000/metrics/evaluation?window=all" \
     -H "Authorization: Bearer betgenius_secure_key_2024"
   ```
