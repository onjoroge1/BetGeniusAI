# V2 Production Training Guide

## Problem: Quick Training vs Full Training

### **The Issue**

The current `train_v2_transformed.py` script is **too quick** because:

1. **Cross-validation**: 
   - Uses `num_boost_round=500` but `early_stopping(25)` 
   - In your log, Fold 1 stopped at **iteration 1** (!)
   - This suggests underfitting

2. **Final model**:
   - Only trains for `num_boost_round=200` iterations
   - No early stopping, no validation
   - This is a quick validation script, not production-grade

### **Why It's Too Fast**

```python
# Current (Quick) Script
model = lgb.train(
    params,
    d_tr,
    num_boost_round=500,      # Max 500 iterations
    valid_sets=[d_va],
    callbacks=[
        lgb.early_stopping(25),  # ❌ Too aggressive - stops if no improvement for 25 rounds
        lgb.log_evaluation(50),
    ],
)

# Final model
final_model = lgb.train(
    params,
    d_full,
    num_boost_round=200,  # ❌ Only 200 iterations, no early stopping
)
```

**Result**: Training completes in ~10 seconds instead of 5-10 minutes

---

## Solution: Production Training Script

### **New Script**: `training/train_v2_production.py`

**Key Differences**:

| Feature | Quick Script | **Production Script** |
|---------|-------------|----------------------|
| Max iterations (CV) | 500 | **2000** ✅ |
| Early stopping | 25 rounds | **100 rounds** ✅ |
| Final model iterations | 200 (fixed) | **120% of avg best iteration** ✅ |
| Learning rate | 0.05 | **0.03** (slower, better convergence) ✅ |
| Regularization | None | **L1=0.1, L2=0.1** ✅ |
| Bagging | None | **0.8 fraction, freq=5** ✅ |
| Max depth | Unlimited | **8** (prevents overfitting) ✅ |
| Min gain to split | 0 | **0.01** ✅ |

**Production Hyperparameters**:

```python
params = {
    "objective": "multiclass",
    "num_class": 3,
    "metric": "multi_logloss",
    "learning_rate": 0.03,         # Lower for better convergence
    "num_leaves": 31,
    "min_data_in_leaf": 30,        # Lower for more flexibility
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,       # Add bagging for robustness
    "bagging_freq": 5,
    "lambda_l1": 0.1,              # L1 regularization
    "lambda_l2": 0.1,              # L2 regularization
    "min_gain_to_split": 0.01,    # Require minimum gain
    "max_depth": 8,                # Limit tree depth
}
```

---

## Usage

### **1. Run Production Training** (Recommended)

```bash
export LD_LIBRARY_PATH="$(gcc -print-file-name=libgomp.so | xargs dirname):$LD_LIBRARY_PATH"
python training/train_v2_production.py
```

**Expected Time**: 5-10 minutes (vs 10 seconds for quick script)

**What Happens**:
- Loads all available training data (648+ matches)
- Trains 5-fold cross-validation with up to **2000 iterations per fold**
- Early stops if no improvement for **100 rounds**
- Tracks best iteration across folds
- Trains final model on full data with **120% of average best iteration**
- Saves to `artifacts/models/v2_production_lgbm.txt`

**Expected Output**:

```
================================================================================
  PRODUCTION TRAINING (Time-Based Cross-Validation)
  Max Iterations: 2000 | Early Stopping: 100 rounds
================================================================================

============================================================
  FOLD 1/5
============================================================
Train: 518 samples | Val: 130 samples
Training with up to 2000 iterations (early stop if no improvement for 100 rounds)...
[100]   valid_0's multi_logloss: 0.987234
[200]   valid_0's multi_logloss: 0.965431
[300]   valid_0's multi_logloss: 0.951234
...
Early stopping, best iteration is:
[456]   valid_0's multi_logloss: 0.945123

📊 Fold 1 Results:
  Best Iteration: 456  ✅ Much more training!
  Accuracy: 0.554
  LogLoss : 0.945
  Brier   : 0.285
```

### **2. Deploy Production Model**

After training completes:

```bash
# Copy production model to active model
cp artifacts/models/v2_production_lgbm.txt artifacts/models/v2_transformed_lgbm.txt
cp artifacts/models/v2_production_features.pkl artifacts/models/v2_transformed_features.pkl

# Server auto-loads on next request (no restart needed if using get_v2_lgbm_predictor cache invalidation)
# But safer to restart:
# Kill server and restart workflow
```

### **3. Verify Deployment**

```bash
# Test endpoint
curl -X POST http://localhost:8000/predict-v2 \
  -H "Content-Type: application/json" \
  -d '{"match_id": 1485849, "include_analysis": false}'
```

---

## When to Use Each Script

### **Use Quick Script** (`train_v2_transformed.py`)
- ✅ **Rapid iteration** during development
- ✅ **Testing new features** before full training
- ✅ **Sanity checks** for data quality
- ✅ **CI/CD validation** (fast feedback)
- ⏱️ Time: ~10-30 seconds

### **Use Production Script** (`train_v2_production.py`)
- ✅ **Final production model**
- ✅ **After backfill** (when you have 2000+ matches)
- ✅ **Monthly retraining** for best performance
- ✅ **When accuracy matters most**
- ⏱️ Time: ~5-10 minutes

---

## Expected Performance

### **Quick Script** (Current):
```
Fold 1: Stopped at iteration 1-70
Final model: 200 iterations (fixed)
OOF Accuracy: 54.2%
Training time: 10 seconds
```

### **Production Script** (New):
```
Fold 1: Stopped at iteration 300-600 (typical)
Final model: ~500 iterations (adaptive based on CV)
OOF Accuracy: 54-55% (slightly better due to better convergence)
Training time: 5-10 minutes
```

---

## Troubleshooting

### **If production training is still too fast**:

1. **Check early stopping**:
   - Look for "Early stopping, best iteration is: [X]"
   - If X < 200, validation set may be too small or noisy

2. **Reduce learning rate further**:
   ```python
   "learning_rate": 0.01,  # Even slower convergence
   ```

3. **Increase early stopping patience**:
   ```python
   lgb.early_stopping(200),  # Wait 200 rounds
   ```

4. **Check validation set size**:
   - Each fold should have 100+ validation samples
   - If < 50 samples, consider reducing `N_SPLITS`

### **If training takes too long** (>30 min):

1. **Increase learning rate**:
   ```python
   "learning_rate": 0.05,  # Faster convergence
   ```

2. **Reduce max iterations**:
   ```python
   num_boost_round=1000,  # Instead of 2000
   ```

3. **Reduce early stopping patience**:
   ```python
   lgb.early_stopping(50),  # Stop sooner
   ```

---

## Model Comparison

After production training, compare models:

```bash
# Check model sizes
ls -lh artifacts/models/v2_*_lgbm.txt

# Expected:
# v2_transformed_lgbm.txt     ~700KB  (Quick: 200 iterations)
# v2_production_lgbm.txt      ~2-3MB  (Production: 500+ iterations)
```

**Larger model = More trees = Better performance** (up to a point)

---

## Automation

For **future auto-retraining**, update `trigger_auto_retrain.py`:

```python
# Use production script instead of quick script
import subprocess

result = subprocess.run([
    "python", "training/train_v2_production.py"
], capture_output=True, text=True)

if result.returncode == 0:
    # Auto-deploy production model
    subprocess.run([
        "cp", 
        "artifacts/models/v2_production_lgbm.txt",
        "artifacts/models/v2_transformed_lgbm.txt"
    ])
```

---

## Summary

**Quick Script** (`train_v2_transformed.py`):
- ⚡ Fast (10 sec)
- 🧪 Development/testing
- 📊 200 iterations
- ✅ Good for iteration

**Production Script** (`train_v2_production.py`):
- 🐢 Slower (5-10 min)
- 🚀 Production deployment
- 📊 500+ iterations (adaptive)
- ✅ Best accuracy

**Recommendation**: Use production script for **all deployments** and **monthly retraining**.
