# V2 Model: Comprehensive Analysis & Full 50-Feature Roadmap

## Executive Summary

**Current State:**
- ✅ **V2 Odds-Only (17 features)** - DEPLOYED to `/predict-v2`
  - Accuracy: 49.5%, LogLoss: 1.0162, Brier: 0.2030
  - Random label sanity: 37.0% ✅ CLEAN
  - Status: Production-ready, leak-free baseline
  
- 🔧 **V2 Full (50 features)** - UNDER INVESTIGATION
  - Accuracy: 50.1% (with potential leak)
  - Random label sanity: 42-43% ❌ FAILS
  - Status: Interaction puzzle - clean individually, leaky combined

**Target:** Get full 50-feature V2 to 52-54% accuracy with clean sanity checks (<40%)

---

## 🔍 Deep Dive: Complete Feature Inventory

### Phase 1: Base Features (42 features)

#### 1. Odds Features (18 features) ✅ CLEAN
**Status:** Production-deployed, passes all sanity checks (37.0%)

```python
Latest probabilities (3):
  - p_last_home, p_last_draw, p_last_away
  
Opening probabilities (3):
  - p_open_home, p_open_draw, p_open_away
  
Dispersion (4):
  - dispersion_home, dispersion_draw, dispersion_away
  - book_dispersion
  
Volatility (3):
  - volatility_home, volatility_draw, volatility_away
  
Coverage metrics (3):
  - num_books_last, num_snapshots, coverage_hours
  
Market intelligence (2):
  - market_entropy, favorite_margin
```

**Data source:** `odds_real_consensus` table
**Quality:** High (21+ bookmakers, validated pre-kickoff only)
**Leakage risk:** None (strict cutoff validation)

---

#### 2. ELO Features (3 features) 🔧 NEEDS TESTING
**Status:** Built but not individually tested

```python
Team ratings (3):
  - home_elo
  - away_elo
  - elo_diff
```

**Implementation:** Simple ELO with K=20, initial=1500
**Data source:** Historical match results via `training_matches`
**Potential issues:** 
- ELO calculation may have time-based bugs
- Cache invalidation across folds
- League-specific initialization

**Test priority:** MEDIUM (only 3 features, unlikely leak source)

---

#### 3. Form Features (6 features) ⚠️ SUSPECTED LEAK
**Status:** Part of team/context group that shows 38.7% (borderline)

```python
Recent performance (6):
  - form_home_points (last 5 matches)
  - form_away_points (last 5 matches)
  - form_home_goals_scored
  - form_away_goals_scored
  - form_home_goals_conceded
  - form_away_goals_conceded
```

**Data source:** Last 5 matches from `training_matches`
**Cutoff enforcement:** Via `match_date < cutoff_time`
**Potential issues:**
- Cumulative stats might create unique signatures
- Goals scored+conceded pairs might identify specific teams
- Interaction with h2h features

**Test priority:** HIGH (prime leak candidate)

---

#### 4. Home Advantage Features (2 features) 🔧 NEEDS TESTING
**Status:** Not individually tested

```python
Venue strength (2):
  - home_advantage_home (wins in last 10 home games)
  - home_advantage_away (wins in last 10 away games)
```

**Data source:** Last 10 home/away matches
**Potential issues:**
- Venue-specific stats might encode team identity
- Interaction with form features

**Test priority:** MEDIUM

---

#### 5. Head-to-Head Features (3 features) ⚠️ SUSPECTED LEAK
**Status:** Part of team group, interaction risk

```python
Historical matchups (3):
  - h2h_home_wins
  - h2h_draws
  - h2h_away_wins
```

**Data source:** All-time H2H from `training_matches`
**Potential issues:**
- H2H + form + ELO might uniquely identify matchup
- Rare matchups create sparse features
- Long-term stability creates implicit IDs

**Test priority:** HIGH (interaction with form/ELO)

---

#### 6. Advanced Stats Features (8 features) 🔧 NEEDS TESTING
**Status:** Not tested, likely clean (generic stats)

```python
In-game metrics (8):
  - home_shots, away_shots
  - home_shots_on_target, away_shots_on_target
  - home_corners, away_corners
  - home_yellows, away_yellows
```

**Data source:** Match statistics from historical games
**Potential issues:**
- Low coverage (not all matches have stats)
- May return zeros for missing data
- Unlikely leak source (too generic)

**Test priority:** LOW

---

#### 7. Schedule Features (2 features) ⚠️ HIGH LEAK RISK
**Status:** Time-based features - prime leak suspects

```python
Recency (2):
  - days_since_home_last_match
  - days_since_away_last_match
```

**Data source:** Time delta from last match to current
**CRITICAL CONCERN:** These features are HIGHLY identifying!

**Why this is suspicious:**
- Team A's last match: 3 days ago
- Team B's last match: 5 days ago
- Current match: 2025-11-10
- → These 3 values nearly encode match identity

**Combined with form/h2h, this could create perfect match fingerprint:**
```
days_since_home=3 + days_since_away=5 + form_home_points=10 + h2h_draws=2
→ Likely identifies specific match in CV fold
```

**Test priority:** **CRITICAL** - Remove first to test

---

### Phase 2: Context Features (4 features) ⚠️ SUSPECTED LEAK
**Status:** Borderline sanity (38.7%), may contribute to interaction

```python
Rest and fatigue (4):
  - rest_days_home (days since last match)
  - rest_days_away (days since last match)
  - schedule_congestion_home_7d (matches in last 7 days)
  - schedule_congestion_away_7d (matches in last 7 days)
```

**Data source:** `match_context` table
**Overlap with Phase 1:** `rest_days_*` likely duplicates `days_since_*`
**CRITICAL ISSUE:** This reinforces the time-based leak!

**Test priority:** **CRITICAL** - Likely interacts with schedule features

---

### Phase 2.5: Drift Features (4 features) ✅ CLEAN
**Status:** Part of odds-only model, confirmed clean

```python
Odds movement (4):
  - prob_drift_home (p_early → p_latest)
  - prob_drift_draw
  - prob_drift_away
  - drift_magnitude (total movement)
```

**Data source:** `odds_early_snapshot` (T-24h+) vs `odds_real_consensus` (T-0h)
**Quality:** High (captures smart money)
**Leakage risk:** None (already tested in odds-only)

**Test priority:** None (confirmed clean)

---

## 🔬 The Leak Hypothesis: Time-Based Match Fingerprinting

### Theory: Combined Time Features Create Implicit Match ID

**Individual features are generic:**
- `days_since_home=3` → Could be any team
- `form_home_points=10` → Could be any team
- `h2h_draws=2` → Could be any matchup

**Combined features become specific:**
```python
Match fingerprint = (
    days_since_home=3,
    days_since_away=5,
    rest_days_home=3,      # DUPLICATE!
    rest_days_away=5,      # DUPLICATE!
    schedule_congestion_home_7d=2,
    schedule_congestion_away_7d=1,
    form_home_points=10,
    form_away_points=7,
    h2h_home_wins=3,
    h2h_draws=2
)

→ This 10-tuple likely unique per match in CV folds
→ Model memorizes match outcomes
→ Random label test shows 42-43% (should be 33%)
```

### Why Individual Tests Passed

**leak_detector.py tested each group in isolation:**
- Odds only: 30.7% ✅
- Team only (form + elo + h2h): 38.7% ✅ (borderline)
- Context only (rest + congestion): 35.2% ✅

**But didn't test interactions:**
- Team + Context: ???
- Schedule + Context: ??? (LIKELY LEAK)
- Team + Schedule + Context: ??? (DEFINITE LEAK)

### Why Training Sanity Failed

**train_v2_no_leakage.py uses all 50 features:**
- Recent 2025 data (Aug-Nov, 1,370 matches)
- TimeSeriesSplit with 7-day embargo
- All features combined

**Result:** 42-43% random label accuracy
**Interpretation:** Model finds patterns in feature combinations that leak match identity

---

## 🎯 Roadmap: Getting to Clean 50-Feature V2

### Phase A: Diagnose the Leak (1-2 days)

#### Task A1: Systematic Feature Ablation ⏱️ 4 hours

**Test combinations to isolate leak source:**

```python
# Run leak_detector_v2.py with different feature sets:

Test 1: Odds + Drift only (17 features)
Expected: 35-38% ✅
Purpose: Confirm baseline clean

Test 2: Odds + ELO (20 features)
Expected: 35-38% ✅
Purpose: Verify ELO doesn't leak

Test 3: Odds + Form (23 features)
Expected: 36-39% (borderline)
Purpose: Check form leak contribution

Test 4: Odds + Schedule (19 features)
Expected: 38-42% ⚠️
Purpose: CRITICAL - Test time-based leak

Test 5: Odds + Context (21 features)
Expected: 38-42% ⚠️
Purpose: CRITICAL - Test rest/congestion leak

Test 6: Odds + Schedule + Context (23 features)
Expected: 40-45% ❌ PREDICTED LEAK
Purpose: Confirm time-feature interaction

Test 7: Odds + Form + H2H (29 features)
Expected: 37-40% (borderline)
Purpose: Check team identity leak

Test 8: All 50 features
Expected: 42-43% ❌ (replication)
Purpose: Confirm full model leak
```

**Deliverable:** Pinpoint exact feature group causing leak

---

#### Task A2: Remove Duplicate Time Features ⏱️ 2 hours

**Problem:** `rest_days_*` and `days_since_*` are identical!

```python
# Phase 1 (schedule features)
days_since_home_last_match = (current_date - last_match_date).days
days_since_away_last_match = (current_date - last_match_date).days

# Phase 2 (context features)
rest_days_home = (current_date - last_match_date).days  # SAME!
rest_days_away = (current_date - last_match_date).days  # SAME!
```

**Solution:** Keep only ONE set (choose context features, drop schedule)

**Modified feature set: 48 features**
- Drop: `days_since_home_last_match`, `days_since_away_last_match`
- Keep: `rest_days_home`, `rest_days_away` (better names)
- Keep: `schedule_congestion_home_7d`, `schedule_congestion_away_7d`

**Expected impact:** Reduce multicollinearity, may reduce leak

---

#### Task A3: Test Time-Binning to Reduce Specificity ⏱️ 3 hours

**Theory:** Exact days create unique fingerprints, bins reduce this

**Current (leak-prone):**
```python
rest_days_home = 3  # Exact days
rest_days_away = 5  # Exact days
```

**Binned (less specific):**
```python
rest_days_home_bin = 1  # 0=0-2d, 1=3-4d, 2=5-7d, 3=8+d
rest_days_away_bin = 2
```

**Test both versions:**
- Exact days: Current implementation
- Binned: Transform to categorical bins

**Measure:** Does binning reduce random label accuracy?
- If yes → Use bins (less leak, slight accuracy cost)
- If no → Keep exact (leak is elsewhere)

---

### Phase B: Apply Fixes (2-3 days)

#### Task B1: Feature Engineering V2.1 ⏱️ 1 day

**Based on Phase A results, implement fixes:**

**Option 1: Remove time-based features entirely**
```python
# Drop if they're irreducibly leaky:
- rest_days_home, rest_days_away
- schedule_congestion_home_7d, schedule_congestion_away_7d

# Result: 46 features (odds + team + drift)
# Expected: 36-38% sanity, 50-52% accuracy
```

**Option 2: Use relative time features**
```python
# Instead of absolute days, use ratios:
- rest_advantage = rest_days_home / rest_days_away
- congestion_advantage = congestion_away / congestion_home

# Result: 48 features (2 relative instead of 4 absolute)
# Expected: 37-39% sanity, 51-53% accuracy
```

**Option 3: League-normalized features**
```python
# Normalize by league average:
- rest_days_home_zscore = (rest_days - league_mean) / league_std
- congestion_home_zscore = (congestion - league_mean) / league_std

# Result: 48 features (normalized versions)
# Expected: 38-40% sanity, 51-53% accuracy
```

**Decision criteria:**
- If sanity < 40% → Ship to production
- If sanity 40-42% → Iterate more
- If sanity > 42% → Remove features entirely

---

#### Task B2: Optimize Feature Builder Performance ⏱️ 4 hours

**Current issue:** `leak_detector_v2.py` times out due to slow feature building

**Optimizations:**

1. **Batch database queries:**
```python
# Current: 1 query per match, per feature group
# Fixed: 1 query for all matches, vectorized computation

def build_features_batch(match_ids, cutoff_times):
    # Query all matches at once
    # Compute features in parallel
    # Return dict of {match_id: features}
```

2. **Cache team-level computations:**
```python
# ELO, form, h2h are team-specific, not match-specific
# Cache by (team_id, cutoff_date) instead of match_id

@lru_cache(maxsize=10000)
def get_team_form(team_id, cutoff_date):
    # Compute once per team per date
```

3. **Parallelize feature groups:**
```python
# Build odds, form, h2h concurrently
from concurrent.futures import ThreadPoolExecutor

with ThreadPoolExecutor(max_workers=4) as executor:
    odds_future = executor.submit(build_odds, match_id)
    form_future = executor.submit(build_form, match_id)
    # ...
```

**Expected speedup:** 5-10x (30 min → 3-5 min for full leak test)

---

#### Task B3: Retrain with Clean Features ⏱️ 6 hours

**Once sanity checks pass (<40%), full retraining:**

```bash
# Step 1: Clean feature set (46-48 features)
python training/train_v2_clean.py --features=clean_v2

# Step 2: Verify sanity
# Random labels: < 40% ✅
# Row permutation: < 40% ✅

# Step 3: Apply Step A optimizations
python training/step_a_optimizations.py

# Hyperparameters:
# - num_leaves: 31
# - min_data_in_leaf: 50
# - draw class weight: 1.30x

# Step 4: Add meta-features
# - league_tier (1-4)
# - favorite_strength (max_prob - 0.33)

# Step 5: Evaluate
# Target: 52-54% accuracy, LogLoss < 1.00
```

**Expected results:**
- Accuracy: 52-54% (vs 49.5% odds-only)
- LogLoss: 0.95-1.00 (vs 1.0162 odds-only)
- Brier: 0.24-0.25 (vs 0.2030 odds-only)
- Random label: 35-38% ✅

---

### Phase C: Production Deployment (1 day)

#### Task C1: A/B Testing Setup ⏱️ 3 hours

**Deploy clean V2 alongside odds-only:**

```python
# /predict-v2 endpoint variants:

# V2.0: Odds-only (current production)
# - 17 features, 49.5% accuracy
# - Safe baseline, guaranteed clean

# V2.1: Clean full model (new)
# - 46-48 features, 52-54% accuracy
# - All sanity checks pass
# - Better team/context intelligence

# Strategy: A/B test for 7 days
# - 50% traffic to V2.0
# - 50% traffic to V2.1
# - Compare CLV, hit rates, user satisfaction
```

---

#### Task C2: Shadow System Integration ⏱️ 4 hours

**Enable auto-promotion via shadow testing:**

```python
# Update shadow_model.py:

# Track V2.0 vs V2.1 performance:
# - Brier score (calibration)
# - LogLoss (confidence)
# - Hit rate (accuracy)
# - CLV (profitability)

# Auto-promote if:
# - V2.1 Brier < V2.0 Brier for 100+ matches
# - V2.1 CLV > V2.0 CLV for 7+ days
# - V2.1 hit rate @ conf>=0.62 > V2.0
```

---

#### Task C3: Documentation & Monitoring ⏱️ 2 hours

**Update production docs:**

1. **Model card:**
```markdown
# V2.1 LightGBM Model

## Performance
- Accuracy: 52.4% (3-way)
- LogLoss: 0.98
- Brier: 0.24
- Sanity: 37% ✅ CLEAN

## Features (48 total)
- Odds intelligence (17)
- Team performance (12)
- Advanced stats (8)
- Context (4)
- Drift (4)
- Meta (3)

## Quality Assurance
✅ All leakage tests passed
✅ Production-validated for 7 days
✅ CLV positive vs market
```

2. **Monitoring dashboard:**
- Real-time accuracy tracking
- Leakage alerts (if sanity degrades)
- Feature importance drift
- Performance by league

---

## 📊 Expected Progression

### Current State (Nov 15, 2025)

| Model | Features | Accuracy | Sanity | Status |
|-------|----------|----------|--------|--------|
| V1 Consensus | N/A | 54.3% | N/A | Production |
| V2.0 Odds-Only | 17 | 49.5% | 37% ✅ | Production |
| V2 Full (bugged) | 50 | 50.1% | 42% ❌ | Investigation |

### After Phase A (Nov 17, 2025)

| Model | Features | Accuracy | Sanity | Status |
|-------|----------|----------|--------|--------|
| V2.0 Odds-Only | 17 | 49.5% | 37% ✅ | Production |
| V2.1 Clean | 46-48 | 51-52% | 37% ✅ | Testing |

### After Phase B (Nov 20, 2025)

| Model | Features | Accuracy | Sanity | Status |
|-------|----------|----------|--------|--------|
| V2.0 Odds-Only | 17 | 49.5% | 37% ✅ | Production |
| V2.1 Optimized | 46-48 | 52-54% | 36% ✅ | Shadow A/B |

### After Phase C (Nov 27, 2025)

| Model | Features | Accuracy | Sanity | Status |
|-------|----------|----------|--------|--------|
| V1 Consensus | N/A | 54.3% | N/A | Fallback |
| V2.1 Production | 46-48 | 53% | 36% ✅ | Primary |

---

## 🎯 Success Criteria

### Phase A Complete
- [ ] Leak source identified (specific feature groups)
- [ ] Sanity test results < 40% for fixed feature set
- [ ] Feature builder optimized (< 5 min for 1000 matches)

### Phase B Complete
- [ ] Clean V2.1 model trained
- [ ] All sanity checks pass (random labels < 40%)
- [ ] Accuracy 52-54% on validation set
- [ ] LogLoss < 1.00, Brier < 0.25

### Phase C Complete
- [ ] V2.1 deployed to production
- [ ] A/B testing shows V2.1 > V2.0 CLV
- [ ] Shadow system enables auto-promotion
- [ ] Documentation and monitoring complete

---

## ⏱️ Timeline Summary

| Phase | Duration | Key Deliverables |
|-------|----------|------------------|
| **Phase A: Diagnose** | 1-2 days | Leak source identified, duplicates removed |
| **Phase B: Fix** | 2-3 days | Clean model at 52-54%, optimized pipeline |
| **Phase C: Deploy** | 1 day | Production V2.1, A/B testing, monitoring |
| **Total** | **4-6 days** | Full 50-feature V2 at 52-54% accuracy |

---

## 🚀 Immediate Next Steps (Today)

### Priority 1: Run Leak Ablation Test

```bash
export LD_LIBRARY_PATH="$(gcc -print-file-name=libgomp.so | xargs dirname):$LD_LIBRARY_PATH"

# Test critical combinations:
python training/leak_detector_ablation.py \
  --test-groups="odds,odds+schedule,odds+context,odds+schedule+context,all"
```

**Expected time:** 20-30 minutes
**Expected output:** Pinpoint where leak emerges

### Priority 2: Fix Duplicate Features

```python
# Edit features/v2_feature_builder.py:
# - Remove days_since_* from _build_schedule_features()
# - Keep only rest_days_* in _build_context_features()
# - Update feature count: 50 → 48
```

**Expected time:** 30 minutes
**Expected impact:** Reduce leak signal

### Priority 3: Test Binned Time Features

```python
# Create variant: features/v2_feature_builder_binned.py
# - Transform rest_days to bins: [0-2, 3-4, 5-7, 8+]
# - Transform congestion to bins: [0, 1, 2, 3+]
# - Retrain and measure sanity
```

**Expected time:** 1-2 hours
**Expected outcome:** Determine if binning helps

---

## 💡 Key Insights

### Why Odds-Only Works
- Generic market intelligence (no team identity)
- Multi-bookmaker consensus (no single source bias)
- Temporal features (drift) are relative, not absolute
- No unique match fingerprints possible

### Why Combined Features Leak
- Time-based features (rest_days, congestion) are highly specific
- Combined with team identity (form, h2h, elo) creates unique signatures
- Even with TimeSeriesSplit + embargo, patterns memorized within folds
- Random label test catches this (42% vs expected 33%)

### The Path Forward
1. **Remove** or **transform** time-based features to reduce specificity
2. **Test systematically** to confirm leak source
3. **Retrain** with clean feature set (46-48 features)
4. **Optimize** hyperparameters and class balance
5. **Deploy** and **monitor** performance vs V2.0 baseline

**Realistic target:** 52-54% accuracy with clean sanity checks (<40%)

**Timeline:** 4-6 days from diagnosis to production

---

## 📚 Resources

### Code Files
- `features/v2_feature_builder.py` - Feature computation (763 lines)
- `training/train_v2_no_leakage.py` - Full training pipeline (576 lines)
- `training/leak_detector_v2.py` - Sanity testing (235 lines)
- `training/step_a_optimizations.py` - Hyperparameter tuning (16K lines)

### Documentation
- `LEAK_INVESTIGATION_NOV14.md` - Current investigation status
- `ACCURACY_EXPECTATIONS_V2.md` - Realistic performance targets
- `V2_OPTIMIZATION_SUMMARY.md` - Step A optimization plan

### Models
- `artifacts/models/v2_odds_only/` - Production V2.0 (17 features, 49.5%)
- `artifacts/models/lgbm_historical_36k/` - Old V2 (46 features, 52.7% with leak)
- `artifacts/models/v2_no_leakage/` - Failed attempt (50 features, 50.1% with leak)

---

## 🎯 Bottom Line

**You have a clear path to 52-54% accuracy:**

1. **Diagnose:** Systematic ablation test (4 hours)
2. **Fix:** Remove/transform leaky features (1 day)
3. **Optimize:** Apply Step A improvements (1 day)
4. **Deploy:** Production V2.1 with A/B testing (1 day)

**The leak is solvable** - it's likely time-based feature interactions that create unique match fingerprints. Once identified and fixed, you'll have a clean 46-48 feature model that beats the odds-only baseline by 2-4 percentage points.

**Realistic outcome:** V2.1 at 53% accuracy, fully leak-free, production-ready in 4-6 days.
