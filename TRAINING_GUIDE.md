# LightGBM Training Guide

## Quick Start

Just run this single command:

```bash
python run_training.py
```

That's it! The script will:
1. ✅ Set up the environment (LD_LIBRARY_PATH)
2. ✅ Ask you which training mode you want
3. ✅ Start training in the background
4. ✅ Show you live progress
5. ✅ Tell you what to do next

---

## Training Options

### Option 1: Fast Single-Split (Recommended for Testing)
- **Time**: 10-15 minutes
- **What it does**: Trains once on 2002-2021 data, tests on 2022-2025
- **Use for**: Quick validation, testing changes
- **Output**: Test set predictions and metrics

### Option 2: Full 5-Fold CV (Production-Ready)
- **Time**: 30-40 minutes
- **What it does**: 5-fold cross-validation with time-aware splits
- **Use for**: Final production model, most accurate evaluation
- **Output**: Out-of-fold predictions for entire dataset

---

## Manual Commands (If You Prefer)

### Fast Single-Split
```bash
export LD_LIBRARY_PATH="$(gcc -print-file-name=libgomp.so | xargs dirname):$LD_LIBRARY_PATH"
python training/train_lgbm_single_split.py
```

### Full 5-Fold CV
```bash
export LD_LIBRARY_PATH="$(gcc -print-file-name=libgomp.so | xargs dirname):$LD_LIBRARY_PATH"
python training/train_lgbm_historical_36k.py
```

### Run in Background
```bash
export LD_LIBRARY_PATH="$(gcc -print-file-name=libgomp.so | xargs dirname):$LD_LIBRARY_PATH"
nohup python training/train_lgbm_historical_36k.py > lgbm_training.log 2>&1 &

# Monitor:
tail -f lgbm_training.log
```

---

## After Training Completes

### Check Results

```bash
# Validate promotion gates
python analysis/promotion_gate_checker.py

# Create ensemble if needed
python training/create_simple_ensemble.py

# Optimize per-league thresholds
python analysis/tune_tau_per_league.py
```

---

## Troubleshooting

### Training seems stuck
- Check logs: `tail -f lgbm_training.log` (or `lgbm_fast_training.log`)
- Training is slow on large datasets - this is normal
- Each fold takes ~6-8 minutes for 5-fold CV

### Out of memory
- Use fast single-split instead of 5-fold CV
- Reduce `num_leaves` in training script (currently 31)

### Process killed
- System might have resource limits
- Try running during off-peak hours
- Use fast single-split mode

---

## Expected Output

### During Training
```
Training fold 1/5...
[50]  valid_0's multi_logloss: 0.986
[100] valid_0's multi_logloss: 0.982
[150] valid_0's multi_logloss: 0.981
Early stopping, best iteration: [147]
```

### After Completion
```
✅ Training complete!

Test Results:
  LogLoss:   0.9823
  Accuracy:  54.8%
  Brier:     0.1954

Saved:
  - artifacts/models/lgbm_fold_*.pkl
  - artifacts/eval/oof_preds.parquet
```

---

## File Locations

**Training Scripts**:
- `training/train_lgbm_single_split.py` - Fast version
- `training/train_lgbm_historical_36k.py` - Full CV version

**Outputs**:
- `artifacts/models/` - Trained model files
- `artifacts/eval/oof_preds.parquet` - Out-of-fold predictions
- `artifacts/eval/close_probs.parquet` - Baseline market probabilities

**Logs**:
- `lgbm_fast_training.log` - Fast training logs
- `lgbm_training.log` - Full CV logs

---

## Next Steps After Training

1. **Validate**: `python analysis/promotion_gate_checker.py`
2. **If gates pass**: Deploy to production
3. **If gates fail**: Create ensemble or add features
4. **Always**: Monitor performance in production

**Quick validation**: If LogLoss < 0.98 and accuracy > 54%, you're in good shape!
