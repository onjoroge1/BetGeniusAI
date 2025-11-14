# V2 Leakage Fix Plan

## 🔴 **Current Status: LEAKAGE DETECTED**

### Test Results (Nov 14, 2025)

**Step A Optimization (400 matches):**
- Random label sanity: **0.450** accuracy (expected ~0.333) → **FAIL**
- Verdict: Feature leakage present

**Full Training Run (1,370 matches):**
- Sanity Check 1 (random labels): **41.4%** → **FAIL**
- Sanity Check 2 (row permutation): **42.7%** → **FAIL**  
- Sanity Check 3 (market-only baseline): **47.1%** → **PASS** ✅
- Final accuracy: 50.1% (LogLoss 1.0166, Brier 0.2582)

### ✅ **Key Finding**

**Odds features are CLEAN** - Market-only baseline performs exactly as expected (47.1%)

**Leakage is in team/context features:**
- Top leaky suspects based on importance:
  - `away_form_goals_conceded` (importance: 21)
  - `home_form_goals_scored` (importance: 15)
  - `days_since_away_last_match` (importance: 14)
  - `rest_days_away` (importance: 5)
  - `days_since_home_last_match` (importance: 4)

---

## 🎯 **Two-Track Strategy**

### Track 1: Ship Safe V2 (TODAY) ✅

**Goal:** Get a production-ready, guaranteed leak-free V2 model deployed ASAP

**Action:**
```bash
export LD_LIBRARY_PATH="$(gcc -print-file-name=libgomp.so | xargs dirname):$LD_LIBRARY_PATH"
python training/train_v2_odds_only.py
```

**Features:** 17 odds-only features
- Consensus probabilities: `p_open_*`, `p_last_*`
- Market metrics: `num_books_last`, `book_dispersion`, `market_entropy`
- Dispersion: `dispersion_*`
- Market structure: `favorite_margin`
- Drift: `prob_drift_*`, `drift_magnitude`

**Expected Performance:** 48-52% accuracy (realistic, honest)

**Deployment:**
- Replace `/predict-v2` endpoint with odds-only model
- Label as "V2.0 - Market Intelligence Only"
- Use as baseline for CLV calculations

---

### Track 2: Fix & Ship Full V2 (2-3 DAYS)

**Goal:** Identify and fix leaky feature groups, then ship full 50-feature V2

#### Step 1: Isolate Leak (20 minutes)

```bash
export LD_LIBRARY_PATH="$(gcc -print-file-name=libgomp.so | xargs dirname):$LD_LIBRARY_PATH"
python training/leak_detector.py
```

This tests each feature group independently:
- `odds`: Probabilities, dispersion, drift (should be CLEAN)
- `elo`: ELO ratings
- `form`: Form points, goals scored/conceded
- `h2h`: Head-to-head history
- `advanced`: Shots, corners, cards
- `schedule`: Rest days, days_since_*, congestion

**Output:** Ranked list showing which groups have accuracy >40% (leaky)

#### Step 2: Fix Leaky Features (1-2 hours)

Most likely culprits and fixes:

**A. Form Features (`form_*`)**
- **Problem:** Computed using matches that include THIS match
- **Fix:** Ensure form calculation excludes current match
  ```sql
  WHERE past_match_date < :cutoff_time  -- NOT <=
  ```

**B. Schedule Features (`rest_days_*`, `days_since_*`)**
- **Problem:** Computed from fixture schedule that includes future matches
- **Fix:** Filter fixtures strictly
  ```sql
  WHERE fixture_date < :cutoff_time
  ```

**C. Advanced Stats (`avg_shots`, `avg_corners`, etc.)**
- **Problem:** Season aggregates that include all matches
- **Fix:** Compute rolling averages from past matches only
  ```sql
  WHERE match_date < :cutoff_time
  ORDER BY match_date DESC
  LIMIT 10  -- last 10 matches only
  ```

#### Step 3: Verify Fix (10 minutes)

```bash
# Re-run leak detector after fixes
python training/leak_detector.py
```

Expected: All groups show accuracy <40%

#### Step 4: Full Retrain with Clean Features (1 hour)

```bash
python training/train_v2_no_leakage.py
```

Expected after fixes:
- Random label sanity: ~33% accuracy ✅
- Row permutation: ~33% accuracy ✅
- Market baseline: ~47% accuracy ✅
- Real performance: 50-52% (honest, defensible)

#### Step 5: Apply Step A Optimizations

Once leakage is fixed, apply the Step A recommendations:

**Hyperparameters (from Step A results):**
```python
{
    'num_leaves': 31,
    'min_data_in_leaf': 50,
    'feature_fraction': 0.8,
    'lambda_l1': 0.0,
    'lambda_l2': 0.0
}
```

**Class Balancing:**
- Draw weight: **1.30×** (from Step A recommendation)
- Improves draw recall from 0.053 → 0.263

**Meta-Features:**
- `league_tier` (1 for top leagues, 2 for others)
- `favorite_strength` (max_prob - median_prob)

**Expected lift:**
- Baseline (odds-only): 48-50%
- + Hyperparameters: +1.5pp → 51.5%
- + Class balancing: +0.8pp → 52.3%
- + Meta-features: +0.5pp → **52.8%**
- + Clean team features: +0.5pp → **53.3%** ✅

---

## 📋 **Execution Checklist**

### Today (Immediate)
- [ ] Run `train_v2_odds_only.py` to get safe baseline
- [ ] Run `leak_detector.py` to identify guilty feature groups
- [ ] Review leak detector output and identify fix locations

### Tomorrow (Day 1)
- [ ] Fix leaky feature computation in `v2_feature_builder.py`
- [ ] Re-run leak detector to verify all groups clean
- [ ] Full retrain with clean features

### Day 2
- [ ] Apply Step A hyperparameters
- [ ] Apply class balancing (1.30× draw weight)
- [ ] Add meta-features
- [ ] Final validation and deployment

---

## 🤔 **Regarding T-1h Cutoff Question**

**Should we build features for horizons beyond T-1h?**

**Short Answer:** Not yet. Fix the leakage first.

**Why:**

1. **Drift features already capture multi-horizon data**
   - Early odds (T-24h+) → Latest odds (T-0h)
   - This captures smart money movement across time

2. **The leak isn't about timing**
   - It's about form/schedule features using future data
   - Adding T-2h, T-3h won't help if features are structurally leaky

3. **After fixing leakage, we could consider:**
   - T-2h, T-3h, T-6h snapshots for "news sensitivity"
   - But honestly, drift features already do this efficiently

**Recommendation:** Keep T-1h cutoff, focus on fixing feature computation logic.

---

## 📊 **Expected Outcomes**

### Odds-Only V2 (Today)
- Accuracy: **48-50%** (honest baseline)
- Features: **17** (all odds-derived)
- Sanity checks: **PASS** all 3
- Status: **Production-ready** ✅

### Full V2 (After fixes)
- Accuracy: **52-54%** (with optimizations)
- Features: **50** (42 base + 4 context + 4 drift)
- Sanity checks: **PASS** all 3
- Status: **Phase 2 complete** ✅

---

## 🎯 **Success Criteria**

Before marking Phase 2 complete:

✅ **Sanity Checks:**
- Random label: <40% accuracy
- Row permutation: <40% accuracy
- Market baseline: 47-52% accuracy

✅ **Performance:**
- Cross-validation: 52-54% accuracy
- LogLoss: <1.00
- Brier: <0.25

✅ **Feature Quality:**
- All 50 features computed with strict temporal cutoffs
- No future data leakage
- Documented computation logic

✅ **Production Deployment:**
- V2 model at `/predict-v2` endpoint
- CLV calculations using V2 predictions
- Shadow testing against V1 baseline
