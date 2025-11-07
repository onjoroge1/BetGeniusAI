# Data Leakage Fix Summary

## 🚨 CRITICAL ISSUES FOUND (90.4% Accuracy Red Flag)

### **Root Causes:**

1. **Post-Kickoff Odds Leakage** ⚠️
   - `p_last_*` features pulled from odds_consensus WITHOUT pre-kickoff filter
   - Query: `ORDER BY ts_effective DESC LIMIT 1` → gets LATEST odds (likely closing/post-kickoff)
   - This is literally training on the answer key!

2. **Date Range Bug** ⚠️
   - Training script: `ORDER BY match_date DESC LIMIT 1000`
   - Result: Only got matches from June 10-12, 2025 (2 days!)
   - Massive temporal correlation between CV folds

3. **Random CV on Correlated Data** ⚠️
   - Using random 5-fold KFold on 2-day window
   - Same teams, same leagues, same market conditions across folds
   - No temporal generalization

4. **Cutoff Time Not Enforced** ⚠️
   - `cutoff_time` parameter existed but was NEVER USED in SQL queries
   - No validation that features are strictly pre-kickoff

---

## ✅ FIXES IMPLEMENTED

### **1. Fixed V2FeatureBuilder (features/v2_feature_builder.py)**

**Before:**
```python
query = text("""
    SELECT ph_cons as p_last_home, ...
    FROM odds_consensus
    WHERE match_id = :match_id
    ORDER BY ts_effective DESC  -- NO CUTOFF!
    LIMIT 1
""")
```

**After:**
```python
query = text("""
    SELECT ph_cons as p_last_home, ...
    FROM odds_consensus
    WHERE match_id = :match_id
      AND ts_effective <= :cutoff_time  -- PRE-KICKOFF ONLY!
    ORDER BY ts_effective DESC
    LIMIT 1
""")

# Now actually passes cutoff_time to query
result = conn.execute(query, {
    "match_id": match_id,
    "cutoff_time": cutoff_time
})
```

### **2. Created Leakage-Free Training Script (training/train_v2_no_leakage.py)**

**Key Features:**

✅ **Time-Based CV with Embargo**
```python
class PurgedTimeSeriesSplit:
    """Time-based CV with 7-day embargo between train/valid"""
    # Prevents temporal leakage and ensures realistic evaluation
```

✅ **Pre-Kickoff Enforcement**
```python
# Calculate cutoff (1 hour before kickoff)
kickoff_time = pd.to_datetime(row['match_date'])
cutoff_time = kickoff_time - timedelta(hours=1)

# Build features with strict cutoff
features = builder.build_features(match_id, cutoff_time=cutoff_time)
```

✅ **Random Sampling (not DESC order)**
```python
ORDER BY RANDOM()  -- Sample across full date range
LIMIT 5000
```

✅ **Sanity Checks**
```python
def run_sanity_checks(df):
    """
    1. Random label shuffle → expect ~33% acc
    2. Market-only baseline → expect 48-52% acc
    
    If shuffle > 40% → LEAKAGE!
    If market > 60% → ODDS LEAKAGE!
    """
```

---

## 📊 EXPECTED RESULTS (After Fixes)

| Metric | Before (Leaked) | After (Fixed) |
|--------|----------------|---------------|
| **3-Way Accuracy** | 90.4% 🚨 | 52-55% ✅ |
| **LogLoss** | 0.198 | ~0.95-1.00 |
| **Brier Score** | 0.038 | ~0.22-0.24 |

**If you still see >60% accuracy after fixes, you have MORE leakage!**

---

## 🔧 HOW TO RUN FIXED TRAINING

### **Option 1: Quick Test (Recommended First)**

```bash
# Run on 5000 matches with all safeguards
python training/train_v2_no_leakage.py
```

**Expected Output:**
```
🔍 Sanity Check 1: Random Label Shuffle
   Result: 33.2% accuracy
   ✅ PASS: Random baseline as expected

🔍 Sanity Check 2: Market-Only Baseline
   Result: 50.1% accuracy
   ✅ PASS: Market efficiency as expected

OUT-OF-FOLD METRICS (Time-Based CV)
  LogLoss:  0.9847
  Brier:    0.2301
  Accuracy: 53.8%

✅ PASS: Realistic accuracy within expected range (48-60%)
```

### **Option 2: Full Production Training**

```bash
# After confirming sanity checks pass, train on full dataset
# Edit train_v2_no_leakage.py, set limit=None

python training/train_v2_no_leakage.py
```

---

## 🧪 VERIFICATION CHECKLIST

Before trusting your model:

- [ ] Sanity Check 1 (Random Shuffle): **<40% accuracy**
- [ ] Sanity Check 2 (Market Baseline): **48-52% accuracy**
- [ ] Final Model Accuracy: **52-55% range**
- [ ] LogLoss: **~0.95-1.00** (not 0.20!)
- [ ] Brier Score: **~0.22-0.24** (not 0.04!)
- [ ] Date Range: **2020-2025** (not 2 days!)
- [ ] CV Strategy: **Time-based with embargo** (not random!)

---

## 🔍 DEBUGGING REMAINING LEAKAGE

If you STILL see >60% accuracy after fixes:

### **Step 1: Check Odds Timestamps**
```sql
-- Verify odds are actually PRE-kickoff
SELECT 
    mc.match_id,
    f.kickoff_at,
    oc.ts_effective,
    EXTRACT(EPOCH FROM (oc.ts_effective - f.kickoff_at))/3600 as hours_before_kickoff
FROM match_context mc
JOIN fixtures f ON mc.match_id = f.fixture_id
JOIN odds_consensus oc ON mc.match_id = oc.match_id
ORDER BY RANDOM()
LIMIT 100;

-- hours_before_kickoff should be POSITIVE (before kickoff)
-- If negative → LEAKAGE!
```

### **Step 2: Feature Ablation**
```python
# Drop features one family at a time
drop_features = ['p_last_home', 'p_last_draw', 'p_last_away']  # Try this first
X_ablated = X.drop(columns=drop_features)

# Retrain
# If accuracy drops from 90% → 50%, these features were leaking!
```

### **Step 3: Permutation Importance**
```python
from sklearn.inspection import permutation_importance

# Check mutual information
# Any feature with MI > 0.5 is suspicious
```

---

## 📝 REMAINING WORK

### **TODO - Immediate:**

1. ✅ Fix V2FeatureBuilder cutoff enforcement (DONE)
2. ✅ Create leakage-free training script (DONE)
3. ⏳ **Run training with fixes and validate 52-55% accuracy**
4. ⏳ Compare Phase 1 (46 features) vs Phase 2 (50 features) improvement
5. ⏳ Update manage_training.py to use leakage-free script

### **TODO - Future Enhancements:**

- Add opening odds (`p_open_*`) from earliest snapshot
- Implement proper odds drift calculation (open → T-1h)
- Add temporal volatility features (std dev across snapshots)
- Feature caching for faster training (materialized table)
- CLV-based model evaluation and auto-promotion

---

## 🎯 SUCCESS CRITERIA

**Phase 2 Model is successful if:**

✅ Passes all sanity checks  
✅ Accuracy: **53-55%** (3-way) - realistic improvement over Phase 1  
✅ LogLoss: **<1.00** - better than market baseline  
✅ Calibrated predictions (ECE < 0.05)  
✅ Positive CLV on holdout set  

**NOT** 90% accuracy - that's leakage, not skill!

---

## 💡 KEY LEARNINGS

1. **Always enforce pre-kickoff cutoffs** - Don't trust parameter names, verify the SQL!
2. **Use time-based CV** - Random splits hide temporal overfitting
3. **Sanity checks are mandatory** - Random shuffle and market baseline catch most leaks
4. **Realistic expectations** - 52-55% is EXCELLENT for sports betting
5. **90% = 🚨** - If it seems too good to be true, it is!

---

**Ready to retrain with fixes?**

```bash
python training/train_v2_no_leakage.py
```

This will take ~2-3 hours but give you a REAL, trustworthy Phase 2 model.
