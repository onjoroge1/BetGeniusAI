# V2 Model Optimization Strategy - Path to 53% Accuracy

**Date**: November 12, 2025  
**Current V2 Performance**: 49.5% accuracy (from Nov 8 training)  
**Target**: 53-55% accuracy  
**Gap**: -3.5pp to -5.5pp  

---

## 📊 CURRENT STATE ANALYSIS

### Training Data Quality
```
✅ Total training matches: 10,240
✅ Matches with real odds: 1,428 (14% of total)
✅ Matches with context data: 1,370 (96% of odds-bearing matches)
⚠️ Matches used in last training: 1,236 (87% of available)
❌ Missing context data: 125 matches (9% gap)
```

### Outcome Distribution (1,428 matches)
```
Home wins: 48.0% (686 matches) ← Slightly overrepresented
Away wins: 28.6% (408 matches) ← Underrepresented
Draws: 23.4% (334 matches) ← Significantly underrepresented (should be ~26-28%)
```

### Odds Data Coverage
```
✅ Latest odds (T-24h): 1,085 matches (76% coverage)
❌ Opening odds (T-7d): 0 matches (0% coverage) ← CRITICAL BLOCKER
```

### Current Hyperparameters
```python
LightGBM Config (from train_v2_no_leakage.py):
- learning_rate: 0.05 (conservative)
- num_leaves: 31 (moderate complexity)
- min_child_samples: 20 (default)
- subsample: 0.8 (80% row sampling)
- colsample_bytree: 0.8 (80% feature sampling)
- class_weight: None ← NOT CONFIGURED (draws underweighted!)
```

---

## 🚨 CRITICAL CONSTRAINT: NO DRIFT FEATURES POSSIBLE

### The Problem
**Opening odds data is NOT available** for historical backfill:
- API-Football tested: Returns empty odds for historical matches
- The Odds API: Only provides current/recent odds, no historical opening lines
- Current collection: Only captures T-24h, T-48h, T-72h snapshots

### Impact on V2 Target
**Planned drift features CANNOT be implemented:**
- ❌ `prob_drift_home` = p_last - p_open
- ❌ `prob_drift_draw` = p_last - p_open
- ❌ `prob_drift_away` = p_last - p_open
- ❌ `drift_magnitude` = sqrt(sum(drifts^2))
- ❌ Expected gain: +0.5-1.0pp accuracy

**REVISED STRATEGY**: Focus on optimization levers that DON'T require opening odds.

---

## 🎯 OPTIMIZATION ROADMAP (WITHOUT DRIFT FEATURES)

### LEVER 1: Complete Context Backfill ✅ **QUICK WIN**
**Current Gap**: 125 matches missing context data (9%)  
**Effort**: 2-3 minutes  
**Expected Gain**: +0.1-0.2pp accuracy (minor, but free)  

**Action**:
```bash
python scripts/backfill_match_context.py
```

---

### LEVER 2: Hyperparameter Tuning 🔴 **HIGH IMPACT**
**Current State**: Using default LightGBM config with no optimization  
**Effort**: 3-4 hours for grid search  
**Expected Gain**: +1.0-2.0pp accuracy  

**Tuning Grid** (based on ENSEMBLE_ROADMAP.md):
```python
{
    'num_leaves': [15, 31, 63],  # Tree complexity
    'min_data_in_leaf': [50, 100, 200],  # Overfitting control
    'learning_rate': [0.03, 0.05, 0.08],  # Step size
    'feature_fraction': [0.7, 0.8, 0.9],  # Feature sampling
    'lambda_l1': [0.0, 0.5, 1.0],  # L1 regularization
    'lambda_l2': [0.0, 0.5, 1.0],  # L2 regularization
}
```

**Best Practices**:
- Use 5-fold TimeSeriesSplit for CV
- Optimize for LogLoss (not accuracy)
- Track overfitting (train vs validation gap)
- Save best params to config file

**Expected Optimal Config** (educated guess):
```python
{
    'num_leaves': 63,  # More complex trees for 1,428 matches
    'min_data_in_leaf': 100,  # Prevent overfitting
    'learning_rate': 0.03,  # Slower, more stable
    'feature_fraction': 0.8,  # Keep default
    'lambda_l1': 0.5,  # Light regularization
    'lambda_l2': 0.5,
}
```

---

### LEVER 3: Class Balancing 🟡 **MEDIUM IMPACT**
**Current State**: Draws underrepresented (23% vs expected 26-28%)  
**Effort**: 30 minutes  
**Expected Gain**: +0.5-1.0pp accuracy  

**Implementation**:
```python
# Option 1: Class weights (preferred)
from sklearn.utils.class_weight import compute_class_weight

class_weights = compute_class_weight(
    'balanced',
    classes=np.unique(y),
    y=y
)
# Result: {H: 0.69, D: 1.27, A: 1.03} ← Draws get 27% more weight

lgbm_params = {
    ...,
    'class_weight': dict(zip(np.unique(y), class_weights))
}

# Option 2: Sample weights (alternative)
sample_weights = y.map({'H': 1.0, 'D': 1.3, 'A': 1.1})
model.fit(X, y, sample_weight=sample_weights)
```

**Why This Helps**:
- Draws are hardest to predict (market baseline ~25% precision)
- Underweighting draws = model ignores them = poor calibration
- Balanced weights = model learns draw patterns better

---

### LEVER 4: Dataset Expansion 🟢 **LONG-TERM GAIN**
**Current State**: 1,428 matches with odds (targeting 5,000)  
**Effort**: Passive (organic growth from daily collection)  
**Expected Gain**: +2.0-3.0pp accuracy (at 5,000 matches)  

**Growth Curve** (from ENSEMBLE_ROADMAP.md):
```
1,236 → 2,000 matches: +1.0pp → 50.5%
2,000 → 3,500 matches: +1.5pp → 52.0%
3,500 → 5,000 matches: +0.5pp → 52.5%
```

**Current Collection Rate**:
- Organic: ~150-200 matches/week (from automated collectors)
- Time to 2,000: ~3-4 weeks
- Time to 5,000: ~18-20 weeks (~4-5 months)

**NO BACKFILLING** (per previous discussions):
- API-Football: No historical odds available
- The Odds API: Expensive ($0.50-1.00 per 1,000 requests)
- Decision: Rely on organic collection

---

### LEVER 5: Feature Engineering Refinement 🟢 **MEDIUM IMPACT**
**Current State**: 50 features, some may be noisy  
**Effort**: 1-2 hours  
**Expected Gain**: +0.3-0.7pp accuracy  

**Quick Wins**:
1. **Add meta-features** (no new data required):
   ```python
   # League tier (1-5 based on quality)
   'league_tier': map_league_to_tier(league_id)
   
   # Odds regime (favorite strength)
   'favorite_strength': max(p_home, p_draw, p_away) - 0.33
   
   # Competitive balance
   'match_balance': 1 - abs(p_home - p_away)
   
   # Entropy (predictability)
   'match_entropy': -sum(p * log(p)) for p in [p_home, p_draw, p_away]
   ```

2. **Feature importance analysis**:
   - Remove features with <1% SHAP importance
   - Reduce noise, improve generalization

3. **Feature interactions** (if dataset allows):
   - `elo_diff * favorite_strength` (dominance signal)
   - `rest_days_diff * schedule_congestion` (fatigue advantage)

---

### LEVER 6: Per-League Calibration 🔵 **LOW PRIORITY**
**Current State**: Single global model for all leagues  
**Effort**: 1-2 hours  
**Expected Gain**: +0.2-0.5pp accuracy  

**Implementation**:
```python
from sklearn.calibration import CalibratedClassifierCV

# After training, calibrate per league tier
for tier in [1, 2, 3, 4, 5]:
    tier_matches = X[X['league_tier'] == tier]
    calibrator = CalibratedClassifierCV(model, method='isotonic', cv=3)
    calibrator.fit(tier_matches, y[tier_indices])
    calibrated_models[tier] = calibrator
```

**Benefit**: Adjust probabilities for league-specific biases (e.g., Serie A more draws, Bundesliga more goals).

---

## 📈 EXPECTED ACCURACY PROGRESSION

### Optimistic Scenario (All Levers)
```
Current baseline: 49.5%
+ Context backfill: +0.2%
+ Hyperparameter tuning: +2.0%
+ Class balancing: +1.0%
+ Feature engineering: +0.7%
+ Per-league calibration: +0.5%
= 53.9% ✅ EXCEEDS TARGET
```

### Conservative Scenario (Minimal Gains)
```
Current baseline: 49.5%
+ Context backfill: +0.1%
+ Hyperparameter tuning: +1.0%
+ Class balancing: +0.5%
+ Feature engineering: +0.3%
+ Per-league calibration: +0.2%
= 51.6% ⚠️ BELOW TARGET
```

### Realistic Scenario (Expected)
```
Current baseline: 49.5%
+ Context backfill: +0.2%
+ Hyperparameter tuning: +1.5%
+ Class balancing: +0.8%
+ Feature engineering: +0.5%
+ Per-league calibration: +0.3%
= 52.8% ⚠️ CLOSE TO TARGET (rounds to 53%)
```

**Verdict**: **53% is achievable** with hyperparameter tuning + class balancing, even WITHOUT drift features.

---

## 🚀 IMPLEMENTATION PLAN

### Week 1 (This Week) - Quick Wins
- [x] ~~Task 1.1: Run comprehensive optimization analysis~~ ✅ COMPLETE
- [ ] **Task 1.2: Complete context backfill (125 matches)** ← PRIORITY
- [ ] **Task 1.3: Add class weight calculation to training script**
- [ ] **Task 1.4: Run baseline retrain with class weights**
- [ ] Target: 49.5% → 50.3% (+0.8pp)

### Week 2 - Hyperparameter Tuning
- [ ] **Task 2.1: Implement grid search script**
- [ ] **Task 2.2: Run tuning on 6x6 grid (216 combinations)**
- [ ] **Task 2.3: Validate best params with 10-fold CV**
- [ ] **Task 2.4: Update train_v2_no_leakage.py with optimal params**
- [ ] Target: 50.3% → 51.8% (+1.5pp)

### Week 3 - Feature Engineering
- [ ] **Task 3.1: Add 4 meta-features (league_tier, favorite_strength, etc.)**
- [ ] **Task 3.2: Run feature importance analysis**
- [ ] **Task 3.3: Remove low-importance features (<1% SHAP)**
- [ ] **Task 3.4: Retrain with refined feature set**
- [ ] Target: 51.8% → 52.3% (+0.5pp)

### Week 4 - Calibration & Validation
- [ ] **Task 4.1: Implement per-league calibration**
- [ ] **Task 4.2: CLV analysis on OOF predictions**
- [ ] **Task 4.3: Validate sanity checks (random: 33%, market: 48-52%)**
- [ ] **Task 4.4: Deploy to /predict-v2 if >=53%**
- [ ] Target: 52.3% → 52.8% (+0.5pp) = **53% ROUNDED**

---

## ✅ SUCCESS CRITERIA

Before deploying V2 to production:
- ✅ **OOF Accuracy**: >= 53.0% (3-way)
- ✅ **LogLoss**: < 1.00
- ✅ **Brier Score**: < 0.22
- ✅ **Sanity Random**: 33% ± 2%
- ✅ **Sanity Market**: 48-52%
- ✅ **Dataset**: >= 1,400 matches (current + backfill)
- ✅ **CLV**: Positive across 3+ leagues
- ✅ **Production Stable**: No errors in training pipeline

---

## 🔮 FUTURE ENHANCEMENTS (Phase 2.5)

Once 53% is achieved and validated:

### Option A: Wait for Organic Growth
- Collect 200 matches/week for 12-16 weeks
- Retrain at 2,000, 3,000, 4,000, 5,000 matches
- Target: 52.8% → 54-55% (at 5,000 matches)

### Option B: Inject External Data
- Add referee statistics (card rates, home bias)
- Add weather data (temperature, precipitation)
- Target: 52.8% → 54% (with injury + referee data)

### Option C: Architectural Changes
- Test XGBoost / CatBoost alternatives
- Explore ensemble of LightGBM variants
- Target: 52.8% → 54-55% (diminishing returns)

**Recommendation**: **Option A** (organic growth) + **Option B** (referee/injury data) = Phase 3 foundation.

---

## 📝 KEY TAKEAWAYS

1. **Drift features are BLOCKED** - API constraints prevent opening odds backfill
2. **53% IS achievable** - Via hyperparameter tuning + class balancing
3. **Timeline: 3-4 weeks** - With focused optimization effort
4. **No expensive backfilling needed** - Work with current 1,428 matches
5. **Phase 3 remains viable** - Once V2 hits 53%, ensemble can push to 55-57%

---

**Next Step**: Complete match_context backfill, then proceed with hyperparameter tuning.
