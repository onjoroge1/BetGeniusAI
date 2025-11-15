# V2.1 Implementation - Next Steps

## ✅ What We've Accomplished

### 1. Feature Transformation Complete
- **Reduced leakage:** 81.61% → 27.01% uniqueness
- **Formula fixed:** `rest_advantage = (rest_h+1)/(rest_a+1)` ensures parity = 1.0
- **Features:** 46 total (40 base + 2 transformed context + 4 drift)

### 2. Code Ready
- ✅ `features/v2_feature_builder_transformed.py` - Leak-resistant builder
- ✅ `training/leak_detector_ablation.py` - Updated for transformed support
- ✅ `training/train_v2_transformed.py` - Production training script

---

## 🚀 Immediate Next Steps

### Step 1: Run Ablation Test (Optional but Recommended)
**Purpose:** Confirm transformed features pass sanity checks

```bash
export V2_USE_TRANSFORMED=1
export LD_LIBRARY_PATH="$(gcc -print-file-name=libgomp.so | xargs dirname):$LD_LIBRARY_PATH"
python training/leak_detector_ablation.py
```

**What to look for:**
- All test groups should show random-label accuracy **< 0.40**
- Specifically check "Odds + Context_Transformed" test
- Full model test should also be < 0.40

**Note:** This takes ~30-45 minutes for 1000 matches. You can skip if you trust the 27.01% uniqueness result.

---

### Step 2: Train V2.1 Model (CRITICAL)
**Purpose:** Create production-ready leak-free model

```bash
export LD_LIBRARY_PATH="$(gcc -print-file-name=libgomp.so | xargs dirname):$LD_LIBRARY_PATH"
python training/train_v2_transformed.py
```

**Timeline:** ~60-90 minutes for 5000 matches

**What the script does:**
1. Loads 5000 matches with context data (2020-2025)
2. Builds 46 features using transformed builder
3. **Sanity check:** Random-label test (must be <0.40)
4. Trains 5-fold TimeSeriesSplit CV with 7-day embargo
5. Reports OOF metrics (target: 52-54% accuracy)
6. Saves final model to `artifacts/models/v2_transformed_lgbm.txt`

**Expected Results:**
- Random-label sanity: **0.33-0.38** (< 0.40 = PASS)
- OOF Accuracy: **52-54%** (A- grade)
- OOF LogLoss: **~1.00-1.05**
- OOF Brier: **~0.185-0.195**

---

### Step 3: Wire into API with A/B Testing

Once training succeeds, integrate V2.1 into your prediction API:

**Option A: Add to existing /predict-v2 endpoint**

```python
# In your predict_v2 handler
def predict_v2(match_id: int, use_v2_1: bool = False):
    if use_v2_1:
        # Use transformed builder + model
        from features.v2_feature_builder_transformed import V2FeatureBuilderTransformed
        builder = V2FeatureBuilderTransformed()
        model_path = "artifacts/models/v2_transformed_lgbm.txt"
    else:
        # Use V2.0 odds-only (current)
        builder = get_v2_feature_builder()
        model_path = "artifacts/models/v2_odds_only.txt"
    
    features = builder.build_features(match_id, cutoff_time)
    # ... rest of prediction logic
```

**Option B: A/B Test at API Level**

```python
import random

@app.get("/predict-v2/{match_id}")
def predict_v2_ab(match_id: int):
    # 50/50 split
    use_v2_1 = random.random() < 0.5
    
    if use_v2_1:
        model_version = "v2.1_full"
        prediction = predict_with_v2_1(match_id)
    else:
        model_version = "v2.0_odds_only"
        prediction = predict_with_v2_0(match_id)
    
    # Log for analysis
    log_prediction(match_id, model_version, prediction)
    
    return prediction
```

---

### Step 4: Monitor and Auto-Promote

Use your existing shadow system to compare:
- **V2.0 Odds-only:** 49.5% accuracy (baseline)
- **V2.1 Full:** Expected 52-54% accuracy

**Metrics to track:**
- Accuracy (3-way and 2-way)
- Brier score
- LogLoss
- CLV / Edge capture
- ROI on simulated bets

**Auto-promotion criteria:**
- V2.1 beats V2.0 by **>2pp** accuracy sustained over 100+ matches
- Brier score improvement **>0.01**
- No regression in CLV capture

---

## 📊 Performance Benchmarks

| Model | Features | Accuracy | Brier | LogLoss | Status |
|-------|----------|----------|-------|---------|--------|
| V1 Consensus | 3 odds | 54.3% | 0.191 | 0.973 | Production |
| V2.0 Odds-only | 18 odds | 49.5% | ~0.25 | ~1.08 | Clean baseline |
| V2.1 Full (Target) | 46 transformed | **52-54%** | **0.185-0.195** | **1.00-1.05** | **In training** |

---

## ⚠️ Known Performance Note

**Feature building is slow:** ~30-60 seconds per 100 matches due to per-match DB queries.

**For production:**
- Pre-compute context features in batch (match_context table already does this)
- Builder just reads from table → much faster
- Current implementation is fine for 5k training run

**For immediate speedup (optional):**
- Reduce sample size to 3000 matches
- Still representative for 2020-2025 data

---

## 🎯 Decision Points

### Do I need to run ablation tests?
**Skip if:** You trust the 27.01% uniqueness result and want to go straight to training  
**Run if:** You want confirmation that random-label accuracy is <0.40 before investing in full training

### What if V2.1 doesn't reach 52%?
- **50-51% is still clean and valuable** - better than V2.0 odds-only (49.5%)
- Can still deploy with A/B testing
- Iterate on feature engineering (Phase 3 enhancements)

### What if sanity check fails (>0.40)?
- Try binned features instead: `use_binned=True` in factory function
- Bins reduce uniqueness to 2.04% (very aggressive)
- May sacrifice 1-2pp accuracy but guarantees cleanliness

---

## 📝 Quick Reference Commands

```bash
# Run ablation test (optional, ~30-45 min)
export V2_USE_TRANSFORMED=1
export LD_LIBRARY_PATH="$(gcc -print-file-name=libgomp.so | xargs dirname):$LD_LIBRARY_PATH"
python training/leak_detector_ablation.py

# Train V2.1 model (critical, ~60-90 min)
export LD_LIBRARY_PATH="$(gcc -print-file-name=libgomp.so | xargs dirname):$LD_LIBRARY_PATH"
python training/train_v2_transformed.py

# Check training output
cat artifacts/models/v2_transformed_features.pkl  # Feature info
ls -lh artifacts/models/v2_transformed_lgbm.txt  # Model file
```

---

## ✅ Success Criteria

Training is successful if:
1. ✅ Random-label sanity: **<0.40** (PASS)
2. ✅ OOF Accuracy: **≥50%** (acceptable), **≥52%** (target)
3. ✅ OOF LogLoss: **<1.10**
4. ✅ Model file saved successfully

Then ready for API integration and A/B testing!

---

*Last updated: Current session*  
*Status: Ready for training run*
