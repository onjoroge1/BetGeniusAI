# 🗺️ V2 Full 50-Feature Model: Implementation Roadmap

## 📍 Current Position (Nov 15, 2025)

```
┌─────────────────────────────────────────────────────────────┐
│  PRODUCTION STATUS                                          │
├─────────────────────────────────────────────────────────────┤
│  ✅ V1 Consensus:     54.3% accuracy (B+ rating)           │
│  ✅ V2.0 Odds-Only:   49.5% accuracy (C+ rating, CLEAN)    │
│  🔧 V2 Full (50 ft):  50.1% accuracy (LEAKY - 42% sanity)  │
└─────────────────────────────────────────────────────────────┘
```

**The Challenge:** Individual feature groups test clean, but combined they leak
**The Goal:** Get all 50 features working cleanly at 52-54% accuracy
**The Timeline:** 4-6 days

---

## 🎯 3-Phase Implementation Plan

### ⏱️ PHASE A: DIAGNOSE (Day 1-2) - Find the Leak Source

**Objective:** Pinpoint exactly which features cause leakage when combined

#### Task A1: Run Systematic Ablation Test
**Duration:** 4-6 hours  
**Command:**
```bash
export LD_LIBRARY_PATH="$(gcc -print-file-name=libgomp.so | xargs dirname):$LD_LIBRARY_PATH"
python training/leak_detector_ablation.py
```

**What it tests:**
1. ✅ Odds only (17 features) - BASELINE
2. ✅ Odds + Drift (21 features) - Should be clean
3. ✅ Odds + ELO (20 features) - Test team ratings
4. ⚠️ Odds + Form (23 features) - Test performance stats
5. ⚠️ Odds + Schedule (19 features) - **HIGH RISK**
6. ⚠️ Odds + Context (21 features) - **HIGH RISK**
7. ❌ Odds + Schedule + Context (23 features) - **EXPECTED LEAK**
8. ⚠️ Odds + All Team (29 features) - Test interactions
9. ❌ All 50 features - **REPLICATION**

**Expected Output:**
```
Test                                    Features  Random Acc         Status
--------------------------------------------------------------------------------
1. Odds Only (Baseline)                      17       0.370    ✅ CLEAN
2. Odds + Drift                              21       0.368    ✅ CLEAN
3. Odds + ELO                                20       0.375    ✅ CLEAN
4. Odds + Form                               23       0.387    ⚠️  BORDERLINE
5. Odds + H2H                                20       0.381    ✅ CLEAN
6. Odds + Schedule (SUSPECTED)               19       0.405    ❌ LEAKY ← FOUND IT!
7. Odds + Context (SUSPECTED)                21       0.412    ❌ LEAKY ← FOUND IT!
8. Odds + Schedule + Context (HIGH RISK)     23       0.438    ❌ LEAKY ← CONFIRMED!
9. Odds + All Team Features                  29       0.391    ⚠️  BORDERLINE
10. ALL 50 FEATURES (Replication)            50       0.427    ❌ LEAKY
```

**Diagnosis:** Time-based features (schedule + context) are the leak source!

---

#### Task A2: Fix Duplicate Features
**Duration:** 30 minutes  
**Problem:** `days_since_*` and `rest_days_*` are identical!

**Solution:**
```python
# Edit features/v2_feature_builder.py

# REMOVE from _build_schedule_features():
# - days_since_home_last_match
# - days_since_away_last_match

# KEEP in _build_context_features():
# - rest_days_home
# - rest_days_away
# - schedule_congestion_home_7d
# - schedule_congestion_away_7d
```

**Result:** 50 features → 48 features (remove duplicates)

---

#### Task A3: Test Feature Transformations
**Duration:** 2-3 hours  
**Options to reduce leakage:**

**Option 1: Bin time features**
```python
# Instead of exact days (3, 5, 7...)
# Use bins: [0-2, 3-4, 5-7, 8+]

def bin_rest_days(days):
    if days <= 2: return 0
    elif days <= 4: return 1
    elif days <= 7: return 2
    else: return 3
```

**Option 2: Use relative features**
```python
# Instead of absolute values
# Use ratios between teams

rest_advantage = rest_days_home / (rest_days_away + 1)
congestion_advantage = congestion_away / (congestion_home + 1)
```

**Option 3: League-normalized features**
```python
# Normalize by league average
# Reduces team-specific patterns

rest_days_home_zscore = (rest_days - league_mean) / league_std
```

**Option 4: Drop time features entirely**
```python
# Nuclear option: Remove all time-based features
# Result: 46 features (odds + team + drift)
```

**Test each option:**
```bash
python training/leak_detector_ablation.py --variant=binned
python training/leak_detector_ablation.py --variant=relative
python training/leak_detector_ablation.py --variant=normalized
python training/leak_detector_ablation.py --variant=no_time
```

**Decision criteria:**
- Sanity < 40% → Use this variant
- Sanity 40-42% → Try another transformation
- Sanity > 42% → Remove features entirely

---

### ⏱️ PHASE B: FIX & OPTIMIZE (Day 3-4) - Clean Model at 52-54%

**Objective:** Train leak-free model with optimized features and hyperparameters

#### Task B1: Optimize Feature Builder
**Duration:** 4 hours  
**Problem:** Current builder is slow (30+ minutes for 1000 matches)

**Optimizations:**

1. **Batch queries:**
```python
# Before: 1 query per match per feature group
# After: 1 query for all matches

def build_features_batch(match_ids, cutoff_times):
    # Single query with WHERE match_id IN (...)
    # 10x speedup
```

2. **Cache team computations:**
```python
@lru_cache(maxsize=10000)
def get_team_form(team_id, cutoff_date):
    # Compute once per team per date
    # Reuse across matches
```

3. **Parallel execution:**
```python
from concurrent.futures import ThreadPoolExecutor

# Build odds, form, h2h concurrently
with ThreadPoolExecutor(max_workers=4) as executor:
    futures = [
        executor.submit(build_odds, match_id),
        executor.submit(build_form, match_id),
        # ...
    ]
```

**Expected speedup:** 30 min → 3-5 min for 1000 matches

---

#### Task B2: Train Clean V2.1 Model
**Duration:** 6 hours  
**Pipeline:**

```bash
# Step 1: Build features with clean feature set
python training/train_v2_clean.py \
  --features=clean_v2 \
  --variant=binned  # or relative, normalized, no_time

# Step 2: Verify sanity checks
# Expected: Random label < 40% ✅

# Step 3: Apply Step A optimizations
python training/step_a_optimizations.py \
  --num-leaves=31 \
  --min-data=50 \
  --draw-weight=1.30

# Step 4: Add meta-features
# - league_tier (1-4)
# - favorite_strength (max_prob - 0.33)

# Step 5: Final training
python training/train_v2_final.py \
  --model-name=v2_clean_production \
  --output-dir=artifacts/models/v2_clean
```

**Expected Results:**
```
Model: V2.1 Clean
Features: 46-48 (depends on Phase A decisions)
Accuracy: 52-54% (3-way)
LogLoss: 0.95-1.00
Brier: 0.24-0.25
Sanity: 35-38% ✅
```

---

#### Task B3: Comprehensive Validation
**Duration:** 2 hours  
**Checklist:**

- [ ] Random label test: < 40% ✅
- [ ] Row permutation test: < 40% ✅
- [ ] Market baseline test: 45-50% ✅
- [ ] Time-based CV: No future leakage ✅
- [ ] Feature importance: No single feature dominates
- [ ] Calibration: Brier score competitive
- [ ] Per-league evaluation: No league overfitting

**Validation script:**
```bash
python training/validate_v2_comprehensive.py \
  --model-dir=artifacts/models/v2_clean \
  --run-all-checks
```

---

### ⏱️ PHASE C: DEPLOY (Day 5-6) - Production Release

**Objective:** Safe production deployment with A/B testing and monitoring

#### Task C1: A/B Testing Infrastructure
**Duration:** 3 hours  
**Setup:**

```python
# Update main.py /predict-v2 endpoint

# V2.0: Odds-only (current production)
# - model_path = "artifacts/models/v2_odds_only/"
# - 17 features, 49.5% accuracy
# - Traffic: 50%

# V2.1: Clean full model (new)
# - model_path = "artifacts/models/v2_clean/"
# - 46-48 features, 52-54% accuracy
# - Traffic: 50%

# Routing logic:
import random

def get_v2_model():
    if random.random() < 0.5:
        return load_model("v2_odds_only"), "v2.0"
    else:
        return load_model("v2_clean"), "v2.1"
```

**Tracking:**
```python
# Log which model variant was used
logger.info(f"V2 prediction: match={match_id}, model={model_version}, "
           f"probs={probs}, conf={confidence}")

# Track metrics per variant:
# - Accuracy
# - LogLoss
# - Brier
# - CLV (profitability)
# - User satisfaction
```

---

#### Task C2: Shadow System Auto-Promotion
**Duration:** 4 hours  
**Integration:**

```python
# Update shadow_model.py

# Compare V2.0 vs V2.1 on same matches:
# - Collect predictions from both models
# - Wait for match results
# - Calculate comparative metrics

# Auto-promote V2.1 if:
# 1. Brier score: V2.1 < V2.0 (for 100+ matches)
# 2. Hit rate: V2.1 > V2.0 (at conf >= 0.62)
# 3. CLV: V2.1 > V2.0 (for 7+ days)
# 4. No sanity degradation (still < 40%)

# Gradual rollout:
# Day 1-3: 50/50 split
# Day 4-6: 70/30 split (if V2.1 winning)
# Day 7+: 100% V2.1 (if auto-promote triggered)
```

---

#### Task C3: Monitoring & Documentation
**Duration:** 2 hours  
**Dashboards:**

1. **Model performance:**
   - Real-time accuracy tracking
   - Per-league breakdown
   - Time-series performance
   
2. **Leakage monitoring:**
   - Weekly sanity check runs
   - Alert if random label > 40%
   - Feature importance drift

3. **Business metrics:**
   - CLV vs market
   - Hit rate by confidence tier
   - API usage by model version

**Documentation:**
```markdown
# V2.1 Production Model Card

## Model Details
- Name: V2.1 LightGBM Clean
- Version: 2.1.0
- Date: 2025-11-20
- Features: 48 (odds + team + context + drift)

## Performance
- Accuracy: 53.2% (3-way)
- LogLoss: 0.97
- Brier: 0.24
- Sanity: 36.5% ✅ CLEAN

## Quality Assurance
✅ All leakage tests passed (<40%)
✅ 7-day A/B test: +2.1pp accuracy over V2.0
✅ CLV positive vs market consensus
✅ Production-validated on 500+ matches

## Feature Engineering
- Odds intelligence: 17 features (market consensus)
- Team performance: 11 features (ELO, form, h2h)
- In-game stats: 8 features (shots, corners, cards)
- Context: 4 features (rest, congestion - binned)
- Drift: 4 features (odds movement)
- Meta: 4 features (league tier, favorite strength)

## Known Limitations
- Lower coverage in low-tier leagues
- Performance degrades when <3 bookmakers
- Not optimized for in-play predictions
```

---

## 📊 Progress Tracking Dashboard

### Week 1: Diagnosis & Fix (Nov 15-20)

| Day | Phase | Tasks | Status |
|-----|-------|-------|--------|
| **Day 1** | A: Diagnose | A1: Ablation test (4h) | ⬜ Pending |
|  |  | A2: Remove duplicates (30m) | ⬜ Pending |
|  |  | A3: Test transformations (2h) | ⬜ Pending |
| **Day 2** | A: Diagnose | Complete Phase A | ⬜ Pending |
| **Day 3** | B: Fix | B1: Optimize builder (4h) | ⬜ Pending |
|  |  | B2: Train clean model (6h) | ⬜ Pending |
| **Day 4** | B: Fix | B3: Comprehensive validation (2h) | ⬜ Pending |
|  |  | Complete Phase B | ⬜ Pending |
| **Day 5** | C: Deploy | C1: A/B infrastructure (3h) | ⬜ Pending |
|  |  | C2: Shadow system (4h) | ⬜ Pending |
| **Day 6** | C: Deploy | C3: Monitoring & docs (2h) | ⬜ Pending |
|  |  | **🚀 V2.1 PRODUCTION LAUNCH** | ⬜ Pending |

### Week 2: Validation & Optimization (Nov 21-27)

| Day | Activity | Goal |
|-----|----------|------|
| Day 7-9 | A/B testing | Compare V2.0 vs V2.1 performance |
| Day 10-12 | Shadow validation | Confirm auto-promotion criteria |
| Day 13-14 | Full rollout | 100% traffic to V2.1 |

---

## 🎯 Success Criteria

### Phase A: Diagnosis Complete ✅
- [ ] Leak source identified (specific feature groups)
- [ ] Duplicate features removed
- [ ] Best transformation strategy chosen
- [ ] Sanity test results < 40%

### Phase B: Clean Model Ready ✅
- [ ] V2.1 model trained
- [ ] Accuracy: 52-54% on validation set
- [ ] All sanity checks pass (< 40%)
- [ ] LogLoss < 1.00, Brier < 0.25
- [ ] Feature builder optimized (< 5 min)

### Phase C: Production Deployed ✅
- [ ] A/B testing infrastructure live
- [ ] Shadow system tracking both models
- [ ] Monitoring dashboards operational
- [ ] Documentation complete
- [ ] Auto-promotion enabled

### Final Validation ✅
- [ ] V2.1 beats V2.0 in A/B test
- [ ] CLV positive vs market
- [ ] No user complaints
- [ ] Ready for Phase 3 (ensemble methods)

---

## 🚨 Risk Mitigation

### Risk 1: Leak persists after fixes
**Probability:** Medium  
**Impact:** High  
**Mitigation:**
- Fall back to odds-only V2.0 (49.5%, proven clean)
- Continue using V1 consensus (54.3%, production stable)
- Investigate alternative feature engineering approaches

### Risk 2: Performance degrades (< 51%)
**Probability:** Low  
**Impact:** Medium  
**Mitigation:**
- Team features proven to add value in past models
- Worst case: Match V2.0 performance (49.5%)
- Apply Step A optimizations for +1-2pp lift

### Risk 3: Feature builder too slow
**Probability:** Medium  
**Impact:** Low  
**Mitigation:**
- Batch queries reduce API calls 10x
- Caching reduces redundant computation
- Parallel execution utilizes multi-core
- Worst case: Precompute features offline

### Risk 4: A/B test inconclusive
**Probability:** Low  
**Impact:** Low  
**Mitigation:**
- Run for 14 days instead of 7
- Increase sample size (more matches)
- Focus on high-confidence predictions
- Use CLV as tiebreaker

---

## 📈 Expected Outcomes

### Pessimistic Scenario (30% probability)
- Time features still leak even after transformations
- Remove all time-based features → 46 features
- Accuracy: 51-52% (modest improvement over V2.0)
- Still better than odds-only baseline
- Platform for Phase 3 ensemble methods

### Realistic Scenario (60% probability)
- Binning or relative features solve leak
- Clean model with 48 features
- Accuracy: 52-54% (solid improvement)
- Matches or slightly beats V1 consensus
- Strong foundation for Phase 3

### Optimistic Scenario (10% probability)
- All 50 features work cleanly with minor fixes
- Accuracy: 54-56% (exceeds expectations)
- Beats V1 consensus
- Ready for Phase 3 immediately

---

## 🔗 Related Documents

- **`V2_COMPREHENSIVE_ANALYSIS.md`** - Complete feature inventory and leak theory
- **`LEAK_INVESTIGATION_NOV14.md`** - Current investigation results
- **`ACCURACY_EXPECTATIONS_V2.md`** - Realistic performance benchmarks
- **`STEP_A_READY.md`** - Hyperparameter optimization plan
- **`V2_DRIFT_FEATURES_IMPLEMENTATION.md`** - Drift feature documentation

---

## 🎯 Bottom Line

**Timeline:** 4-6 days from diagnosis to production

**Deliverable:** V2.1 model with 46-48 features at 52-54% accuracy, fully leak-free

**Next Milestone:** Phase 3 ensemble methods targeting 55-58% accuracy

**Risk Level:** Low (fallback to V2.0 odds-only if needed)

**Confidence:** High (clear diagnosis, proven techniques, systematic approach)

---

**Ready to start Phase A? Run the ablation test to pinpoint the leak source! 🚀**

```bash
export LD_LIBRARY_PATH="$(gcc -print-file-name=libgomp.so | xargs dirname):$LD_LIBRARY_PATH"
python training/leak_detector_ablation.py
```
