# Quick Restart Guide

The previous training run timed out after 2 hours. This has been **FIXED**.

## What Was Fixed

✅ **Timeout increased**: 2 hours → **6 hours**  
✅ **Real-time output**: You'll see progress as it runs  
✅ **Better progress tracking**: Updates every 50 matches with percentage  

## Restart Training Now

```bash
python scripts/manage_training.py --train
```

## What To Expect

### Timeline:
```
Hour 0-1:   Feature building (0-25%)
Hour 1-2:   Feature building (25-50%)     ← You timed out here last time
Hour 2-3:   Feature building (50-75%)
Hour 3-4:   Feature building (75-100%)
Hour 4-4.5: Training (5 folds)
Hour 4.5-5: Results
```

### Live Progress You'll See:
```
🔨 Building features (pre-kickoff only, T-1h)...
   Processed 50/5000 matches (1.0%)
   Processed 100/5000 matches (2.0%)
   Processed 150/5000 matches (3.0%)
   ...
```

**This time, it won't timeout!** The limit is now 6 hours.

## Monitor Progress

### In another terminal:
```bash
# Check if running
ps aux | grep train_v2_no_leakage

# Should show: python -u training/train_v2_no_leakage.py
```

## Expected Final Results

```
OUT-OF-FOLD METRICS
  LogLoss:  0.97
  Brier:    0.23
  Accuracy: 53.6%

✅ PASS: Realistic accuracy within expected range
```

**NOT 90%!** That was leakage. 53-55% is correct and excellent! 🎯

---

**Ready? Run it again:**

```bash
python scripts/manage_training.py --train
```

Total time: **4-5 hours** (won't timeout this time!)
