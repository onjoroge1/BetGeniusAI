# V2 Data Leakage - Root Cause Analysis

**Date**: 2025-11-16  
**Status**: 🔴 CRITICAL - Complete data contamination identified

---

## Executive Summary

**Random-label accuracy**: 0.515 (should be <0.40)  
**Root cause**: 100% of `match_context` data created 2-3 months AFTER matches  
**Impact**: All context features (rest_days, congestion) are contaminated  
**Solution**: Remove context features entirely from V2 until data can be rebuilt

---

## Investigation Timeline

### 1. Initial Symptoms
- V2.0 (odds-only): 49.5% accuracy, 0.37 random-label ✅ CLEAN
- V2.1 (transformed): 50.1% accuracy, 0.515 random-label ❌ LEAKY
- Transformation alone (81.61% → 27.01% uniqueness) did NOT fix leak

### 2. Database Audit Results

```sql
SELECT 
    COUNT(*) as total,
    COUNT(CASE WHEN created_at > match_date_utc THEN 1 END) as post_match
FROM match_context mc
JOIN matches m ON mc.match_id = m.match_id;

RESULTS:
total: 700
post_match: 700
percentage: 100.00%
```

**🚨 SMOKING GUN: ALL 700 rows created post-match**

### 3. Timeline Analysis

| Match Date | Context Created | Hours After | Days After |
|------------|----------------|-------------|------------|
| 2025-08-18 | 2025-11-08     | 1,965       | 82 days    |
| 2025-08-23 | 2025-11-08     | 1,850       | 77 days    |
| 2025-08-31 | 2025-11-08     | 1,660       | 69 days    |

**Pattern**: All context data batch-created on Nov 8, 2025, long after matches finished.

---

## Why This Causes Leakage

Even though `rest_days` and `congestion` are technically pre-match facts:

1. **Selection Bias**: Which matches got context data may correlate with outcomes
2. **Computation Bugs**: Post-match processing may have accidentally used outcome data
3. **Match Fingerprinting**: Unique combinations + post-match timing = perfect match IDs
4. **Model Learning**: With 0.515 random accuracy, model has learned to identify specific matches

---

## Attempted Fixes (All Failed)

### ❌ Attempt 1: Remove duplicate schedule features
- Reduced 50 → 48 features
- Leakage persisted

### ❌ Attempt 2: Transform to relative ratios
- `rest_advantage = home_rest / (away_rest + 1)`
- `congestion_ratio = (home_cong + 1) / (away_cong + 1)`
- Reduced uniqueness 81.61% → 27.01%
- **Leakage persisted** (0.515 random accuracy)

### ❌ Attempt 3: Binning
- Not yet tested, but won't work if underlying data is contaminated

---

## The Real Problem

**Transformations can't fix contaminated source data.**

If match_context was created 2-3 months post-match:
- Any bugs in the generation pipeline had access to outcomes
- Selection of which matches to include may be biased
- The model learns to identify matches via context features

---

## Immediate Solution

### Phase 1: Remove Context Features (TODAY)

Create `V2FeatureBuilderNoContext`:
```python
class V2FeatureBuilderNoContext(V2FeatureBuilder):
    def _build_context_features(self, match_id, cutoff_time):
        return {}  # Return empty dict
```

**Expected result**:
- 42 features (40 base + 0 context + 4 drift - 2 deprecated schedule)
- Random-label accuracy <0.40 ✅
- Accuracy ~49-50% (similar to odds-only baseline)

### Phase 2: Rebuild match_context (LATER)

Requirements for clean rebuild:
1. **Strict pre-match timestamps**: `created_at` MUST be before `match_date_utc`
2. **Real-time computation**: Build context as matches are discovered, not batch
3. **Audit trail**: Track when each row was created
4. **Validation**: Check 0% post-match contamination before use

---

## Current Status

| Component | Status | Random Acc | Notes |
|-----------|--------|------------|-------|
| V2.0 odds-only | ✅ CLEAN | 0.37 | Production-ready |
| V2.1 transformed | ❌ LEAKY | 0.515 | Context contaminated |
| V2.2 no-context | ⏳ PENDING | TBD | Next to build |
| match_context rebuild | 📋 BACKLOG | N/A | Future project |

---

## Recommendations

### Immediate (Next 1 hour):
1. ✅ Create V2FeatureBuilderNoContext
2. ✅ Train V2.2 without context features
3. ✅ Verify random-label <0.40
4. ✅ Deploy if clean

### Short-term (Next week):
1. Rebuild match_context with strict pre-match timestamps
2. Add validation checks to prevent future contamination
3. Re-introduce context features once data is clean

### Long-term:
1. Implement real-time context computation for new matches
2. Add automated data quality checks to training pipeline
3. Create monitoring for timestamp anomalies

---

## Key Lesson

**Always audit data timestamps before training!**

A simple SQL check would have caught this on day 1:
```sql
SELECT COUNT(*) FROM match_context mc
JOIN matches m ON mc.match_id = m.match_id
WHERE mc.created_at > m.match_date_utc;
```

If result > 0 → **STOP TRAINING** → Fix data first.

---

## Files Modified

- ✅ `training/train_v2_transformed.py` - Added uniqueness diagnostics
- ✅ `training/leak_detector_ablation.py` - Fixed LightGBM callbacks
- ✅ `features/v2_feature_builder.py` - Fixed feature count validation
- ⏳ `features/v2_feature_builder_no_context.py` - TO CREATE
- ⏳ `training/train_v2_no_context.py` - TO CREATE

---

## Next Steps

**User should approve removing context features before proceeding with V2.2 training.**
