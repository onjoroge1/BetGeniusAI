# Quick Training Guide - Leakage-Free Model

## 🚨 IMPORTANT: 90.4% Was Data Leakage!

The previous 90.4% accuracy was caused by:
1. Post-kickoff odds leakage
2. Random CV on 2-day window
3. Training on answer key

**All fixed!** Expect realistic 52-55% accuracy now.

---

## ✅ Simple Training (Recommended)

```bash
# Option 1: Direct training (fastest)
./train.sh

# Option 2: Using training manager
./train.sh --manage

# Option 3: Check status only
./train.sh --check
```

**OR** with manual libgomp setup:

```bash
export LD_LIBRARY_PATH="$(gcc -print-file-name=libgomp.so | xargs dirname):$LD_LIBRARY_PATH"
python scripts/manage_training.py --train
```

---

## 📊 What To Expect

### **Expected Output (First 5 Minutes):**

```
======================================================================
  V2-TEAM++ LEAKAGE-FREE TRAINING
  Anti-leakage measures:
    1. Time-based CV with 7-day embargo
    2. Pre-kickoff odds only (T-1h)
    3. Random sampling (not DESC order)
    4. Sanity checks for leakage detection
======================================================================

V2-TEAM++ DATA LOADING (LEAKAGE-FREE)
Date range: 2020-01-01 to 2025-12-31
Pre-kickoff cutoff: T-1h minimum
Limit: 5000 matches

✅ Loaded 5000 matches
   Date range: 2020-04-15 to 2025-06-10
   Outcome distribution:
      Home: 2145 (42.9%)
      Draw: 1302 (26.0%)
      Away: 1553 (31.1%)

🔨 Building features (pre-kickoff only, T-1h)...
   Processed 100/5000 matches...
   Processed 200/5000 matches...
   ...
```

### **Sanity Checks (After Feature Building):**

```
LEAKAGE DETECTION - SANITY CHECKS
======================================================================

🔍 Sanity Check 1: Random Label Shuffle
   Expected: ~33% accuracy, LogLoss ~1.10
   Result: 33.8% accuracy
   ✅ PASS: Random baseline as expected

🔍 Sanity Check 2: Market-Only Baseline
   Expected: 48-52% accuracy (markets are efficient)
   Result: 50.3% accuracy
   ✅ PASS: Market efficiency as expected
```

**If sanity checks FAIL:**
- Random shuffle >40% → LEAKAGE STILL EXISTS
- Market baseline >60% → ODDS ARE POST-KICKOFF

### **Training Progress:**

```
V2-TEAM++ TRAINING (Time-Based CV, Leakage-Free)
======================================================================
CV Strategy: 5-fold Time Series Split
Embargo: 7 days between train/valid

--- Fold 1/5 ---
Train: 800 matches (2020-04-15 to 2022-08-20)
Valid: 800 matches (2022-09-03 to 2023-12-15)
  LogLoss: 0.9845
  Brier:   0.2298
  Accuracy: 52.1%

--- Fold 2/5 ---
...
```

### **Final Metrics (Expected):**

```
OUT-OF-FOLD METRICS (Time-Based CV)
======================================================================
  LogLoss:  0.9723
  Brier:    0.2256
  Accuracy: 53.4%
======================================================================

✅ PASS: Realistic accuracy within expected range (48-60%)
```

**If you see >60% accuracy, there's STILL leakage!**

---

## ⏱️ Duration

- Feature building: **~90-120 minutes** (5000 matches)
- Training: **~15-20 minutes** (5 folds × 3-4 min)
- **Total: ~2-2.5 hours**

---

## 🎯 Success Criteria

✅ Sanity checks both PASS  
✅ Accuracy: **52-55%** (3-way)  
✅ LogLoss: **<1.00**  
✅ Brier: **~0.22-0.24**  

**NOT** 90% - that was leakage!

---

## 🔧 Training on Full Dataset

After confirming sanity checks pass on 5000 matches:

```python
# Edit training/train_v2_no_leakage.py
# Line ~144, change:
limit=None  # From 5000 to None
```

Then rerun:
```bash
./train.sh
```

---

## 📈 Understanding The Results

### **Why 53% is Actually Excellent:**

- **Random guess**: 33% (3-way)
- **Market baseline**: 48-52% (bookmakers are smart)
- **Your model**: 53-55% ← **BEATING THE MARKET!**
- **World-class**: 57-58% (very hard to achieve)

### **Phase 2 Improvement:**

- Phase 1 (46 features): 50-52%
- Phase 2 (50 features): 53-55%
- **Improvement: +2-3%** ← This is what we expected!

---

## 🐛 Troubleshooting

### **"libgomp.so.1: cannot open shared object"**

Use the convenience script:
```bash
./train.sh
```

Or manually set:
```bash
export LD_LIBRARY_PATH="$(gcc -print-file-name=libgomp.so | xargs dirname):$LD_LIBRARY_PATH"
```

### **"No output for 5+ minutes"**

- Python output buffering issue
- Training IS running, just not printing
- Check process: `ps aux | grep train_v2_no_leakage`
- Or use: `python -u training/train_v2_no_leakage.py` (unbuffered)

### **"Accuracy still >70%"**

You have MORE leakage! Check:
1. Are odds truly pre-kickoff? (Query odds_consensus for ts_effective)
2. Is cutoff_time being respected?
3. Run feature ablation test

---

## 📝 Next Steps After Training

1. **Compare to Phase 1**: Validate +2-3% improvement
2. **Deploy to production**: Use trained model for predictions
3. **Monitor CLV**: Track Closing Line Value on real predictions
4. **Plan Phase 3**: Player-aware features for 57-58% target

---

## Quick Reference

```bash
# Check if training needed
./train.sh --check

# Run managed training
./train.sh --manage

# Run direct training
./train.sh

# Monitor progress
tail -f artifacts/models/v2_no_leakage/training.log  # If logs enabled
```

---

**Ready? Let's train!**

```bash
./train.sh
```

Expected time: 2-2.5 hours  
Expected accuracy: 53-55% (NOT 90%!)
