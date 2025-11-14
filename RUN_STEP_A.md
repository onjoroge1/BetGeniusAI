# Running Step A Optimizations

## Current Status
✅ All infrastructure verified and ready:
- 1,044 matches with drift features available
- 50 features (42 base + 4 context + 4 drift)
- Leakage-free baseline at 49.5% accuracy
- Optimization script ready: `training/step_a_optimizations.py`

## The Issue
Feature building is slow (~3 seconds per match):
- 100 matches = ~5 minutes
- 400 matches = ~20 minutes  
- 1,044 matches (full dataset) = ~50-60 minutes

This is because the V2FeatureBuilder makes individual database queries for each match.

## How to Run

### Option 1: Quick Test (Recommended First)
Run with just 100 matches to validate the optimization logic:

```bash
export LD_LIBRARY_PATH="$(gcc -print-file-name=libgomp.so | xargs dirname):$LD_LIBRARY_PATH"
timeout 600 python training/step_a_optimizations.py
```

This will use 400 matches (default) and take ~20 minutes.

### Option 2: Full Optimization
For best results, run with all 1,044 matches:

```bash
# Modify the script to use all matches
sed -i 's/limit=400/limit=1044/' training/step_a_optimizations.py

# Run with 1-hour timeout
export LD_LIBRARY_PATH="$(gcc -print-file-name=libgomp.so | xargs dirname):$LD_LIBRARY_PATH"
timeout 3600 python training/step_a_optimizations.py > step_a_results.log 2>&1 &

# Monitor progress
tail -f step_a_results.log
```

### Option 3: Run Overnight
For convenience, run it in a tmux/screen session:

```bash
# Install tmux if needed
# Start tmux session
tmux new -s optimization

# Inside tmux:
export LD_LIBRARY_PATH="$(gcc -print-file-name=libgomp.so | xargs dirname):$LD_LIBRARY_PATH"
python training/step_a_optimizations.py | tee step_a_results.log

# Detach: Ctrl+B, then D
# Reattach later: tmux attach -t optimization
```

## What You'll Get

After completion, the script outputs:

1. **Sanity Check Results**
   - Confirms no leakage (acc ≈ 0.33 for random labels)

2. **Best Hyperparameters**
   - Optimal `num_leaves`, `min_data_in_leaf`, `feature_fraction`, `lambda_l1/l2`
   - Selected by cross-validated LogLoss

3. **Class Balancing Recommendation**
   - Optimal draw weight (likely 1.30×)
   - Impact on overall accuracy and draw recall

4. **Meta-Features Added**
   - `league_tier` (1 for top leagues, 2 for others)
   - `favorite_strength` (max probability - median)

5. **Per-League Performance**
   - Accuracy and LogLoss breakdown by league
   - Ensures gains aren't from one weird league

## Expected Improvements

| Optimization | Gain | Cumulative |
|--------------|------|------------|
| Baseline | - | 49.5% |
| Drift features (done) | +0.7pp | 50.2% |
| Hyperparameters | +1.5pp | 51.7% |
| Class balancing | +0.8pp | 52.5% |
| Meta-features | +0.5pp | **53.0%** ✅ |

## After Step A Completes

1. Review the output recommendations
2. Update `training/train_v2_no_leakage.py` with:
   - Best hyperparameters from grid search
   - Draw class weight (likely 1.30×)
   - Meta-features in V2FeatureBuilder
3. Retrain V2 model
4. Measure lift vs 49.5% baseline

## Alternative: Skip Optimization, Go Straight to Training

If you want to skip the optimization loop and just retrain with drift features:

```bash
# The drift features are already in V2FeatureBuilder
# Just retrain with existing config
export LD_LIBRARY_PATH="$(gcc -print-file-name=libgomp.so | xargs dirname):$LD_LIBRARY_PATH"
python training/train_v2_no_leakage.py
```

This will give you the +0.7pp lift from drift features (49.5% → 50.2%) immediately.
Then you can optimize later.
