# 🎯 V2 Full Features: Enhanced Implementation Plan
## (Incorporating Architect Review - Nov 15, 2025)

## 🔬 Critical Findings from Architect Review

### ✅ What We Got Right
1. **Ablation testing approach** - Systematic feature group testing is sound
2. **Time-feature hypothesis** - Highly likely source of leak
3. **Phased approach** - Diagnosis → Fix → Deploy is correct

### ⚠️ Critical Improvements Needed

#### 1. **Ablation Script Enhancement (BEFORE running)**
```python
# Current limitation: Hard-coded 1K matches
# Risk: False negatives, missing edge cases

# Required fixes:
✅ Expand to full training coverage (>3K matches, not just recent 1K)
✅ Persist per-fold diagnostics (detect multi-way interactions)
✅ Log fold-level random-label scores (not just mean)
✅ Add collision count analysis (fingerprint uniqueness quantification)
```

#### 2. **Optimal Feature Transformation**
```python
# Architect recommendation: COMBINE Option 1 + Option 2

# Option 1: Bin time features (coarse buckets)
rest_days_bin = bin_days(rest_days)  # [0-2, 3-4, 5-7, 8+]

# Option 2: Use relative ratios (team advantage)
rest_advantage = rest_days_home / (rest_days_away + 1)
congestion_advantage = congestion_away / (congestion_home + 1)

# Result: 4 features → 2 features
# - Loses exact timing (reduces leak)
# - Preserves relative advantage (keeps signal)

# ❌ Don't use Option 3 (z-scores): Volatile in small leagues
# ❌ Don't use Option 4 (drop entirely): Forfeit known edge
```

#### 3. **Data Freshness Audit (CRITICAL)**
```python
# MUST verify: match_context table has no post-match contamination

# Query to check:
SELECT 
    mc.match_id,
    mc.created_at,
    mc.updated_at,
    tm.match_date,
    EXTRACT(EPOCH FROM (mc.created_at - tm.match_date))/3600 as hours_delta
FROM match_context mc
JOIN training_matches tm ON mc.match_id = tm.match_id
WHERE mc.created_at > tm.match_date  -- POST-MATCH UPDATES!
ORDER BY hours_delta DESC
LIMIT 100;

# If ANY rows returned → LEAK STILL EXISTS
# If zero rows → Safe to proceed
```

#### 4. **Performance Front-Loading**
```
Timeline risk: Feature builds could bottleneck

Solution: Parallelize BEFORE ablation testing
- Batch database queries
- Cache team-level computations
- Multi-threaded feature building

Expected: 30 min → 3-5 min for 1K matches
Critical: Enables rapid iteration on variants
```

---

## 🚀 Revised Implementation Plan

### 🔧 PHASE 0: Pre-Flight Checks (2-3 hours) - NEW!

#### Task 0.1: Data Freshness Audit ⏱️ 30 min
**CRITICAL: Verify no post-match data in match_context**

```sql
-- Check 1: No post-match updates
SELECT COUNT(*) FROM match_context mc
JOIN training_matches tm ON mc.match_id = tm.match_id
WHERE mc.created_at > tm.match_date;
-- Expected: 0

-- Check 2: Sample context timestamps
SELECT 
    match_id, 
    created_at, 
    rest_days_home, 
    rest_days_away
FROM match_context
ORDER BY RANDOM()
LIMIT 20;
-- Manually verify these make sense
```

**If contaminated → Fix data pipeline first, THEN proceed**

---

#### Task 0.2: Fingerprint Collision Analysis ⏱️ 1 hour

```python
# Quantify how unique time-feature combinations are

import pandas as pd
from sqlalchemy import create_engine, text

query = """
SELECT 
    rest_days_home,
    rest_days_away,
    schedule_congestion_home_7d,
    schedule_congestion_away_7d,
    COUNT(*) as collision_count
FROM match_context
GROUP BY 1,2,3,4
HAVING COUNT(*) > 1
ORDER BY collision_count DESC;
"""

# Expected output:
# High collision rate (many duplicates) → Time features generic → Low leak risk
# Low collision rate (mostly unique) → Time features specific → HIGH leak risk

# Example:
# (3, 5, 2, 1) → 47 matches  ✅ GOOD (generic pattern)
# (3, 5, 2, 1) → 2 matches   ⚠️  BAD (near-unique)
# (7, 4, 3, 2) → 1 match     ❌ VERY BAD (unique fingerprint)
```

**Decision rule:**
- Collision rate > 20%: Time features safe
- Collision rate 10-20%: Borderline, apply transformations
- Collision rate < 10%: HIGH RISK, must transform

---

#### Task 0.3: Optimize Feature Builder ⏱️ 2 hours

**Before running ablation, make it fast!**

```python
# Create: features/v2_feature_builder_fast.py

class V2FeatureBuilderFast(V2FeatureBuilder):
    """Optimized version with batching and caching"""
    
    def build_features_batch(self, match_ids, cutoff_times):
        """Build features for multiple matches at once"""
        
        # Single query for all matches
        query = text("""
            SELECT match_id, home_team_id, away_team_id, ...
            FROM training_matches
            WHERE match_id IN :match_ids
        """)
        
        # Cache team-level computations
        @lru_cache(maxsize=10000)
        def get_team_stats(team_id, cutoff_date):
            # Compute once, reuse across matches
            pass
        
        # Parallel execution
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {
                executor.submit(build_odds_batch, match_ids): 'odds',
                executor.submit(build_form_batch, team_ids): 'form',
                # ...
            }
        
        return features_dict

# Expected speedup: 10-20x
# 1000 matches: 30 min → 2-3 min
# 3000 matches: 90 min → 5-8 min
```

---

### 🔬 PHASE A: Enhanced Diagnosis (Day 1-2)

#### Task A1: Run Enhanced Ablation Test ⏱️ 4-6 hours

**Updated script: `training/leak_detector_ablation_v2.py`**

```python
# Key improvements:
✅ Full training coverage (3K+ matches, not just 1K)
✅ Per-fold diagnostics (log each fold's random-label accuracy)
✅ Collision analysis (quantify fingerprint uniqueness)
✅ Feature interaction matrix (test pairwise combinations)

# Example output:
"""
FOLD DIAGNOSTICS:
Fold 1: 0.418 ❌ (2023 Q1 data)
Fold 2: 0.402 ❌ (2023 Q2 data)
Fold 3: 0.389 ⚠️  (2023 Q3 data)
Fold 4: 0.376 ✅ (2023 Q4 data)
Fold 5: 0.441 ❌ (2024 data)

→ Leak worse in recent data!
→ Suggests time-window specific issue
"""

# Collision analysis:
"""
FINGERPRINT UNIQUENESS:
4-tuple (rest_h, rest_a, cong_h, cong_a):
  Unique tuples: 847 / 3142 = 27% ❌ HIGH RISK
  Mean collisions: 3.7 matches per pattern
  Max collisions: 23 matches (pattern: 3,3,1,1)

→ 73% of matches have near-unique time signatures
→ CONFIRMS time-feature leak hypothesis
"""
```

**Command:**
```bash
export LD_LIBRARY_PATH="$(gcc -print-file-name=libgomp.so | xargs dirname):$LD_LIBRARY_PATH"
python training/leak_detector_ablation_v2.py --full-coverage --persist-folds
```

---

#### Task A2: Prototype Binned + Relative Features ⏱️ 2 hours

**Create: `features/v2_feature_builder_transformed.py`**

```python
def _build_context_features_transformed(self, match_id, cutoff_time):
    """Transform time features to reduce leakage"""
    
    # Get raw values
    rest_h_raw = get_rest_days_home(match_id, cutoff_time)
    rest_a_raw = get_rest_days_away(match_id, cutoff_time)
    cong_h_raw = get_congestion_home(match_id, cutoff_time)
    cong_a_raw = get_congestion_away(match_id, cutoff_time)
    
    # Transformation 1: Bin exact days to coarse buckets
    def bin_rest_days(days):
        if days <= 2: return 0      # Short rest
        elif days <= 4: return 1    # Normal rest
        elif days <= 7: return 2    # Good rest
        else: return 3              # Extended rest
    
    def bin_congestion(count):
        if count == 0: return 0     # Light schedule
        elif count == 1: return 1   # Normal schedule
        elif count == 2: return 2   # Busy schedule
        else: return 3              # Congested schedule
    
    # Transformation 2: Use relative ratios (team advantage)
    # Avoids absolute values, preserves signal
    rest_advantage = rest_h_raw / (rest_a_raw + 1)  # +1 to avoid div/0
    congestion_disadvantage = (cong_h_raw + 1) / (cong_a_raw + 1)
    
    # Result: 4 raw features → 2 transformed features
    return {
        'rest_advantage': rest_advantage,  # >1 = home team more rested
        'congestion_ratio': congestion_disadvantage  # >1 = home team busier
    }
    
    # Alternative: Keep binned absolute values
    # return {
    #     'rest_home_bin': bin_rest_days(rest_h_raw),
    #     'rest_away_bin': bin_rest_days(rest_a_raw),
    #     'congestion_home_bin': bin_congestion(cong_h_raw),
    #     'congestion_away_bin': bin_congestion(cong_a_raw)
    # }
```

**Test on pilot slice:**
```python
# Regenerate features for 500 matches
# Compare sanity checks:

# Original (exact days):
# - Random label: 42% ❌

# Transformed (binned + relative):
# - Random label: 37% ✅ (expected)
```

---

#### Task A3: Remove Duplicate Features ⏱️ 30 min

```python
# Edit: features/v2_feature_builder.py

def _build_schedule_features(self, ...):
    """
    DEPRECATED: Merged into context features
    
    This method previously calculated:
    - days_since_home_last_match
    - days_since_away_last_match
    
    These are IDENTICAL to rest_days_* in context features!
    """
    return {}  # Empty dict, no longer used

# Result: 50 features → 48 features
# - Remove: days_since_home_last_match, days_since_away_last_match
# - Keep: rest_days_home, rest_days_away (in context)
# - OR: Replace both with rest_advantage (transformed)
```

---

### 🔧 PHASE B: Fix & Retrain (Day 3-4)

#### Task B1: Full Clean Retraining ⏱️ 6 hours

**Script: `training/train_v2_clean_final.py`**

```python
# Configuration:
FEATURES = 'transformed'  # Use binned + relative time features
N_MATCHES = 3000+  # Full coverage, not just recent 1K
CV_STRATEGY = 'TimeSeriesSplit'  # 5 folds + 7-day embargo

# Feature set (46-48 total):
✅ Odds intelligence: 17 features
✅ ELO ratings: 3 features
✅ Form metrics: 6 features
✅ Home advantage: 2 features
✅ H2H history: 3 features
✅ Advanced stats: 8 features
✅ Context (transformed): 2 features (rest_advantage, congestion_ratio)
✅ Drift features: 4 features
✅ Meta features: 2 features (league_tier, favorite_strength)

# Total: 47 features

# Sanity checks (all must pass):
assert random_label_accuracy < 0.40
assert row_permutation_accuracy < 0.40
assert market_baseline_accuracy in [0.45, 0.52]

# Training:
python training/train_v2_clean_final.py \
  --features=transformed \
  --output-dir=artifacts/models/v2_clean \
  --apply-step-a-optimizations
```

**Expected results:**
```
V2.1 Clean Model (Transformed Features)
=======================================
Features: 47 (odds + team + transformed context + drift + meta)
Accuracy: 52.4% (3-way) ✅ Target: 52-54%
LogLoss: 0.98 ✅ Target: <1.00
Brier: 0.244 ✅ Target: <0.25

Sanity Checks:
- Random labels: 37.2% ✅ PASS (<40%)
- Row permutation: 38.1% ✅ PASS (<40%)
- Market baseline: 48.7% ✅ PASS (45-52%)

Per-Fold Performance:
- Fold 1: 51.8%
- Fold 2: 52.3%
- Fold 3: 53.1%
- Fold 4: 52.7%
- Fold 5: 52.1%
Mean: 52.4%, Std: 0.48% (stable!)
```

---

#### Task B2: Comprehensive Validation ⏱️ 2 hours

```python
# Script: training/validate_v2_comprehensive.py

# Validation battery:
✅ Leakage tests (random label, row permutation)
✅ Time-based CV (no future leakage)
✅ Feature importance (no single feature dominates)
✅ Calibration curves (predicted vs actual probabilities)
✅ Per-league evaluation (no league overfitting)
✅ Confidence tiers (accuracy at 50%, 60%, 70% conf)
✅ CLV simulation (profitability vs market)

# Example output:
"""
VALIDATION RESULTS: V2.1 Clean
================================

Leakage Tests:
  Random labels:     37.2% ✅
  Row permutation:   38.1% ✅
  Future info:       0 cases ✅

Feature Importance (Top 10):
  1. p_last_home:          8.2%
  2. p_last_away:          7.9%
  3. elo_diff:             6.4%
  4. drift_magnitude:      5.1%
  5. favorite_margin:      4.8%
  ...
  No single feature >10% ✅

Calibration (Brier by Confidence):
  50-60%: 0.281 (good)
  60-70%: 0.213 (excellent)
  70%+:   0.172 (superb)

Per-League Accuracy:
  Premier League: 54.2%
  La Liga:        53.1%
  Bundesliga:     52.8%
  Serie A:        51.9%
  Ligue 1:        52.4%
  All others:     51.7%
  → No severe overfitting ✅

CLV Simulation (vs consensus):
  Hit rate: 53.2%
  Mean CLV: +0.021 (2.1 cents per dollar)
  Kelly ROI: +4.3% per year
  → Profitable edge ✅
"""
```

---

### 🚀 PHASE C: Production Deploy (Day 5-6)

#### Task C1: A/B Testing with Shadow System ⏱️ 4 hours

```python
# Update: main.py /predict-v2 endpoint

# Traffic split:
# - 50% V2.0 (odds-only, 49.5%)
# - 50% V2.1 (clean full, 52.4%)

# Both models run on every request (shadow mode)
# User gets one, we log both

def predict_v2_with_ab_test(match_id, api_key):
    # Run both models
    v2_0_result = predict_odds_only(match_id)
    v2_1_result = predict_clean_full(match_id)
    
    # Decide which to serve
    import random
    if random.random() < 0.5:
        served_model = 'v2.0'
        served_result = v2_0_result
    else:
        served_model = 'v2.1'
        served_result = v2_1_result
    
    # Log both for comparison
    log_ab_test_prediction(
        match_id=match_id,
        served_model=served_model,
        v2_0_probs=v2_0_result['probabilities'],
        v2_1_probs=v2_1_result['probabilities'],
        timestamp=datetime.utcnow()
    )
    
    return served_result

# After 7 days:
# - Compare Brier scores
# - Compare hit rates
# - Compare CLV
# - Auto-promote winner
```

---

## 📊 Revised Timeline

### Week 1: Diagnosis & Fix (Nov 15-21)

| Day | Phase | Tasks | Hours |
|-----|-------|-------|-------|
| **Day 1** | 0: Pre-flight | Data audit, collision analysis, optimize builder | 3h |
|  | A: Diagnose | Enhanced ablation test | 4h |
|  |  | **Total Day 1** | **7h** |
| **Day 2** | A: Diagnose | Prototype transformed features | 2h |
|  |  | Remove duplicates | 0.5h |
|  |  | Test pilot slice | 2h |
|  |  | **Total Day 2** | **4.5h** |
| **Day 3** | B: Fix | Full clean retraining | 6h |
|  |  | **Total Day 3** | **6h** |
| **Day 4** | B: Fix | Comprehensive validation | 2h |
|  |  | Fix any issues | 2h |
|  |  | **Total Day 4** | **4h** |
| **Day 5** | C: Deploy | A/B testing setup | 3h |
|  |  | Shadow system integration | 2h |
|  |  | **Total Day 5** | **5h** |
| **Day 6** | C: Deploy | Monitoring & docs | 2h |
|  |  | Production cutover | 1h |
|  |  | **Total Day 6** | **3h** |

**Total Effort:** ~30 hours over 6 days

---

## ✅ Updated Success Criteria

### Phase 0: Pre-Flight Complete
- [ ] Match_context has zero post-match updates ✅
- [ ] Collision rate analyzed and documented
- [ ] Feature builder optimized (< 5 min for 1K matches)

### Phase A: Diagnosis Complete
- [ ] Enhanced ablation test run on 3K+ matches
- [ ] Per-fold diagnostics reveal leak source
- [ ] Transformed features tested on pilot slice
- [ ] Sanity checks pass with transformations

### Phase B: Clean Model Ready
- [ ] V2.1 trained with 47 transformed features
- [ ] Accuracy: 52-54% on validation
- [ ] All sanity checks < 40%
- [ ] Comprehensive validation passed

### Phase C: Production Deployed
- [ ] A/B testing infrastructure live
- [ ] Shadow system tracking both models
- [ ] 7-day validation period complete
- [ ] Auto-promotion to V2.1

---

## 🎯 Expected Final Outcome

```
V2.1 PRODUCTION MODEL (Nov 21, 2025)
=====================================

Architecture:
- LightGBM ensemble (5 models, CV-trained)
- 47 features (transformed time features)
- Hyperparameters: Step A optimized

Performance:
- Accuracy: 53.2% (3-way) ← Beats V1's 54.3%? Not quite, but close
- LogLoss: 0.97
- Brier: 0.24
- Hit rate @ 62%: 76%+ (selective)

Quality Assurance:
✅ All leakage tests passed (<40%)
✅ 7-day A/B test shows improvement over V2.0
✅ CLV positive vs market consensus
✅ Production-validated on 500+ matches

Status: PRODUCTION PRIMARY MODEL
```

---

## 🚨 De-Risking Strategies

### Risk 1: Data contamination in match_context
**Probability:** Low  
**Detection:** Task 0.1 (SQL audit)  
**Mitigation:** If found, fix pipeline first, delay 1-2 days

### Risk 2: Transformation loses too much signal
**Probability:** Medium  
**Detection:** Pilot slice accuracy < 51%  
**Mitigation:** Try different binning strategy, use 4 binned features instead of 2 relative

### Risk 3: Leak persists after transformation
**Probability:** Low  
**Detection:** Sanity still > 40%  
**Mitigation:** Fall back to V2.0 odds-only, investigate deeper

### Risk 4: Feature builder too slow
**Probability:** Medium (if not optimized)  
**Detection:** Task 0.3 takes > 8h  
**Mitigation:** Precompute features offline, cache to DB

---

## 🔗 Next Steps (Immediate)

1. **Run Task 0.1:** Data freshness audit (30 min)
2. **Run Task 0.2:** Collision analysis (1 hour)
3. **Run Task 0.3:** Optimize feature builder (2 hours)
4. **Run Task A1:** Enhanced ablation test (4 hours)

**Total today:** ~7-8 hours of focused work

**Command to start:**
```bash
# Step 1: Data audit
psql $DATABASE_URL -f scripts/audit_match_context.sql

# Step 2: Collision analysis
python training/analyze_fingerprints.py

# Step 3: Optimize builder (create fast version)
# ... manual coding ...

# Step 4: Run enhanced ablation
export LD_LIBRARY_PATH="$(gcc -print-file-name=libgomp.so | xargs dirname):$LD_LIBRARY_PATH"
python training/leak_detector_ablation_v2.py --full-coverage
```

**Ready to proceed? 🚀**
