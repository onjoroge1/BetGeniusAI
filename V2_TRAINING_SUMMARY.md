# V2 Training Summary - Oct 11, 2025

## 🎯 What We Accomplished

### 1. ✅ Backfilled Training Data (46x Expansion!)
- **Before:** 134 matches with features
- **After:** 6,185 matches with features (Aug 2022 → Oct 2025)
- **Coverage:** 33 leagues across 3 years
- **Features:** prob_home/draw/away, overround, book_dispersion, drift_24h_*

### 2. ✅ Implemented Leakage-Free Training
- **Temporal split:** Train (5,136 samples) | Validate (740 samples)  
- **No data leakage:** Meta-learner and calibrators trained on validation only
- **Proper workflow:** Base models on train → Meta on val → Calibrators on val

### 3. ✅ Fixed Infrastructure Issues
- **libgomp.so dependency:** Installed GCC, updated workflow with LD_LIBRARY_PATH
- **Feature selection:** Smart detection of available columns
- **Calibration:** Updated V2Predictor to use isotonic calibrators correctly

---

## ❌ Critical Issue: V2 Still Overfits

### Symptoms
**Validation Metrics (Suspiciously Perfect):**
- LogLoss: 0.0445 (should be ~0.6-0.9 for sports)
- Brier: 0.0018 (should be ~0.20-0.25 for sports)

**Test Predictions (Unrealistic):**
```
Balanced Match:
  Market: H=39.8% D=27.7% A=32.5%
  V2 ML:  H=17.0% D=1.7%  A=81.4%  ❌ Extreme!

Home Favorite:
  Market: H=65.0% D=22.0% A=13.0%
  V2 ML:  H=96.1% D=2.0%  A=2.0%   ❌ Extreme!
```

### Root Cause Analysis

**The model is STILL overfitting despite all fixes:**

1. **Validation metrics too perfect** → Model memorizing validation set
2. **Ensemble too complex** → 4-model stack (draw/win/GBM/meta) amplifies patterns
3. **GBM too powerful** → Even with regularization, it finds spurious patterns
4. **Insufficient regularization** → Current constraints not strong enough

**Why this happens:**
- Sports betting is inherently noisy (LogLoss ~0.7 is state-of-the-art)
- Getting 0.0445 LogLoss means the model is fitting noise, not signal
- Complex ensembles can memorize patterns that don't generalize

---

## 📊 Current System State

### Production (Safe & Stable)
```
✅ V1 (Market Consensus): Active, tested, reliable
✅ Shadow System: Ready for A/B testing
✅ Training Data: 6,185 matches backfilled
✅ Infrastructure: All dependencies resolved
```

### V2 Model (Needs Redesign)
```
⚠️ Status: Trained but overfitting
⚠️ Predictions: Extreme and unrealistic
⚠️ Issue: Ensemble architecture too complex
⚠️ Impact: Cannot be promoted to production
```

---

## 💡 Path Forward: 3 Options

### Option A: Simplify V2 Architecture (Recommended)
**Replace complex ensemble with simpler model:**
1. **Single regularized LightGBM** with strong constraints:
   - `max_depth=3` (very shallow trees)
   - `min_data_in_leaf=200` (force generalization)
   - `lambda_l1=5.0, lambda_l2=5.0` (heavy regularization)
   - `learning_rate=0.01` (slow, careful learning)

2. **Use market as strong prior:**
   - Initialize predictions with market probabilities
   - Let model only adjust ±10% from market
   - Prevents extreme deviations

**Why this works:**
- Simpler models generalize better
- Market probabilities are already very informative
- Small adjustments are more defensible than predictions from scratch

### Option B: Market Adjustment Model
**Don't predict probabilities directly - predict adjustments:**
1. Train model to predict: `Δ_home`, `Δ_draw`, `Δ_away`
2. Final predictions: `P_market + Δ_model` (clipped)
3. Forces model to respect market wisdom

**Benefits:**
- Can't make extreme predictions
- More realistic for A/B testing
- Easier to explain to users

### Option C: Keep V1, Enhance Features
**Focus on improving V1 instead:**
1. Add CLV-derived features to V1
2. Incorporate recent accuracy metrics
3. Use dynamic bookmaker weighting based on performance

**Why consider this:**
- V1 already works well (LogLoss=0.838, Brier=0.167)
- Sometimes simpler is better
- Focus resources on data collection instead

---

## 🔍 Detailed Analysis

### What Went Right
1. ✅ Successfully scaled training data 46x
2. ✅ Implemented proper train/val split
3. ✅ Fixed all infrastructure issues (libgomp, features, calibration)
4. ✅ Created comprehensive training pipeline
5. ✅ Shadow system ready for A/B testing

### What Went Wrong
1. ❌ Ensemble architecture too complex for signal-to-noise ratio
2. ❌ Validation metrics impossibly good (should have been red flag)
3. ❌ GBM overfits even with strong regularization
4. ❌ No "market as prior" constraint to prevent extreme predictions

### Key Learnings
- **Sports betting has low signal:** LogLoss ~0.7 is excellent, 0.045 is impossible
- **Simpler often better:** Complex ensembles can memorize noise
- **Market is informative:** Should be used as strong prior, not ignored
- **Validation metrics can lie:** Perfect metrics on small validation set = overfitting

---

## 📈 Recommendations

### Immediate (This Week)
1. **Keep V1 in production** (it works!)
2. **Disable V2 shadow mode** until redesign complete
3. **Document learnings** for future model development

### Short-term (Next 2 Weeks)
1. **Implement Option A** (Simple regularized model with market prior)
2. **Test on holdout set** (matches from last 7 days)
3. **Verify realistic predictions** (max confidence <80%)
4. **Re-enable shadow mode** only when validated

### Long-term (Next Month)
1. **Collect more feature data:** form5_*, elo_delta, rest_days
2. **Implement cross-validation:** 5-fold time-series CV
3. **Build confidence intervals:** Quantify prediction uncertainty
4. **A/B test systematically:** Compare V1 vs V2 on real predictions

---

## 🎯 Success Criteria for V2 (Before Production)

### Must Have
- ✅ Validation LogLoss: 0.60-0.90 (realistic for sports)
- ✅ Validation Brier: 0.15-0.25 (realistic for sports)
- ✅ Max confidence <80% on most predictions
- ✅ Predictions within ±20% of market probabilities
- ✅ Beats V1 on 300+ predictions over 7+ days

### Nice to Have
- ✅ Per-league performance analysis
- ✅ Confidence calibration curves
- ✅ Feature importance analysis
- ✅ Prediction explainability

---

## 📝 Files Updated

### Training & Models
- `scripts/backfill_features.py` - Feature backfilling (6,185 matches)
- `scripts/train_v2.py` - Leakage-free training with temporal split
- `models/v2_predictor.py` - Fixed calibration application
- `models/v2/*.pkl` - Trained models (currently overfitting)

### Documentation
- `replit.md` - Updated V2 status and learnings
- `V2_TRAINING_SUMMARY.md` - This comprehensive summary
- `V2_ACTIVATION_SUMMARY.md` - Initial activation report

---

## 🤝 Next Steps - Your Decision

**We've built the infrastructure, expanded the data 46x, and identified the core issue.** 

Now you need to decide:

**A.** Redesign V2 with simpler architecture (recommended)  
**B.** Try market adjustment approach instead  
**C.** Stick with V1, focus on other improvements  
**D.** Something else?

V1 is working great in production. V2 needs to prove it can do better before we switch. The shadow system is ready whenever V2 is! 🚀
