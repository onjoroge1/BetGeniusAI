# 🚀 LightGBM V2: Next Steps

## Current Status
✅ Dataset expanded to **40,769 matches** (36,942 trainable)  
✅ Features extracted: **46 features** per match  
✅ Training infrastructure: **Time-aware CV ready**  
✅ Evaluation framework: **EV/CLV + hit@coverage operational**  

---

## Next Action: Complete Training (30-40 min)

```bash
# Option 1: Full 5-fold CV (recommended for production)
export LD_LIBRARY_PATH="$(gcc -print-file-name=libgomp.so | xargs dirname):$LD_LIBRARY_PATH"
python training/train_lgbm_historical_36k.py

# Option 2: Fast single-split (5-10 min for quick test)
python training/train_lgbm_single_split.py
```

---

## Then: Evaluate & Decide

```bash
# After training completes, run evaluation
python analysis/eval_ev_clv.py
```

**Check These Metrics**:
- ✅ Δ LogLoss ≤ -0.02? (vs 0.9861 baseline)
- ✅ 3-way accuracy 55-60%? (vs 51.8% baseline)
- ✅ EV_close > 0 on high-confidence picks?
- ✅ Hit@coverage better than baseline at 60% threshold?
- ✅ ECE < 0.08 globally?

**If ALL YES**: ✅ Promote to production  
**If ANY NO**: 🔄 Iterate on features/hyperparameters

---

## Selection Policy (Deploy Now)

```python
# Tiered confidence strategy
if max_p >= 0.62 and ev_close > 0 and league_ece <= 0.05:
    pick = argmax(p_model)  # High confidence
elif 0.56 <= max_p < 0.62:
    pick = light_consensus   # Medium confidence
else:
    pick = full_consensus    # Low confidence or pass
```

**Expected Lift**: Based on baseline, this should hit **72.7% @ 21.5% coverage**

---

## Files You Need

**Training**: `training/train_lgbm_historical_36k.py`  
**Evaluation**: `analysis/eval_ev_clv.py`  
**Detailed Docs**: 
- `PHASE2_COMPLETE_SUMMARY.md` (full overview)
- `EVALUATION_FRAMEWORK.md` (metrics details)
- `DATASET_EXPANSION_RESULTS.md` (data stats)

---

## Targets to Beat

| Metric | Baseline | Target |
|--------|----------|--------|
| LogLoss | 0.9861 | 0.94-0.98 |
| 3-way Acc | 51.8% | 55-60% |
| Hit @ 60% cov | 72.7% | 75-80% |
| ECE | 0.0095 | < 0.08 |

**You have 72.6% more data and 283% more features** - the targets are within reach! 🎯
