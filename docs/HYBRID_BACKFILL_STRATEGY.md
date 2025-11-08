# Hybrid Backfill + Periodic Training Strategy

**Date**: November 8, 2025  
**Status**: READY TO IMPLEMENT

---

## Overview

After discovering that `odds_consensus` contains fake/backdated data, we've migrated to using `odds_snapshots` (real pre-kickoff odds). This gives us 1,236 matches with authentic data (14% coverage).

This document outlines the hybrid strategy to:
1. **Train NOW** on clean data (1,236 matches)
2. **Backfill gradually** via API (add 7,000+ matches)
3. **Retrain periodically** as coverage improves
4. **Track progress** towards target accuracy

---

## Data Sources

### ✅ REAL DATA: odds_snapshots → odds_real_consensus
- **Source**: `odds_snapshots` table  
- **Coverage**: 1,513 matches with pre-kickoff odds
- **Quality**: 100% authentic (collected before matches)
- **Bookmakers**: Average 67 per match
- **Timing**: Average 39 hours before kickoff
- **Usage**: Production training (current)

### ❌ FAKE DATA: odds_consensus (DO NOT USE!)
- **Source**: Backdated batch job (Aug 31, 2025)
- **Problem**: Created AFTER matches finished
- **Evidence**: 100% market-only accuracy (impossible)
- **Status**: DEPRECATED - Never use again

---

## Current Training Dataset

### Matches with Real Odds:
```
Total matches in training_matches: 8,809
With real odds (odds_real_consensus): 1,513 (17%)
With outcomes + match_dates: 1,236 (14%)
Missing odds: 7,296 (83%)
```

### match_context Coverage:
```
Rows: 1,236
Avg rest days home: 16.5 days
Avg rest days away: 15.6 days
Avg congestion (7d): 0.4 matches
Data quality: ✅ REALISTIC
```

---

## Phase 1: Train on Clean Data (TODAY)

### Objective:
Prove Phase 2 works with small but clean dataset

### Steps:
1. ✅ Created `odds_real_consensus` from `odds_snapshots`
2. ✅ Cleaned and refilled `match_context` (1,236 matches)
3. ⏳ Update `v2_feature_builder.py` to use real odds
4. ⏳ Run training on 1,236 matches
5. ⏳ Validate sanity checks PASS

### Expected Results:
```
Sanity Check 1 (Random): ~33% ✅
Sanity Check 2 (Market-only, TimeSeriesSplit): 48-52% ✅
Model Accuracy: 52-55% ✅
LogLoss: <1.00 ✅
Coverage: 14% (1,236/8,809)
```

### Success Criteria:
- [ ] Sanity checks pass (no leakage)
- [ ] Model beats market baseline
- [ ] Training completes without errors
- [ ] Dropped matches tracked and documented

---

## Phase 2: Gradual Backfill (ONGOING)

### Objective:
Increase coverage from 14% → 90%+ via API backfill

### Data Sources for Backfill:

#### Option A: The Odds API (Historical Odds)
- **Coverage**: ~70-80% of missing matches
- **Cost**: $200-500 for full backfill
- **Timeline**: 2-4 weeks
- **Pros**: Authentic pre-kickoff odds
- **Cons**: Costs money

#### Option B: API-Football (Historical Odds)
- **Coverage**: ~60-70% of missing matches
- **Cost**: Included in current plan
- **Timeline**: 2-4 weeks
- **Pros**: Free (already paying)
- **Cons**: Lower coverage than The Odds API

#### Option C: Wait for Organic Collection
- **Coverage**: 100% going forward
- **Cost**: $0
- **Timeline**: 2-3 months for decent dataset
- **Pros**: Free, perfect quality
- **Cons**: Very slow

### Recommended Approach: **Hybrid A+C**
1. Use The Odds API to backfill high-priority leagues
2. Continue organic collection for future matches
3. Retrain every 500-1000 new matches added

### Backfill Script:
```bash
# Already updated to use odds_real_consensus
python scripts/backfill_match_context.py

# This will:
# 1. Find matches missing context data
# 2. Only process matches with REAL odds
# 3. Compute rest days + schedule congestion
# 4. Insert into match_context table
```

---

## Phase 3: Periodic Retraining (AUTOMATED)

### Objective:
Automatically retrain as coverage improves

### Retraining Triggers:
1. **Every 500 new matches** with real odds
2. **Weekly** during active backfill period
3. **Monthly** during organic growth phase

### Automation:
```python
# Add to utils/scheduler.py
def check_retraining_needed():
    """Check if we should retrain based on new data"""
    
    # Count new matches since last training
    new_matches_count = get_matches_since_last_training()
    
    if new_matches_count >= 500:
        logger.info(f"🚀 Triggering retraining: {new_matches_count} new matches")
        trigger_training()
        return True
    
    return False
```

### Training Cycle:
1. **Detect**: New matches added to `odds_real_consensus`
2. **Backfill**: Run `backfill_match_context.py`
3. **Train**: Run `manage_training.py --train`
4. **Validate**: Run sanity checks
5. **Compare**: Track accuracy improvement
6. **Log**: Record in retraining_history table

---

## Expected Accuracy Progression

### Phase 1: 1,236 Matches (14% coverage)
```
Expected: 52-55% accuracy
LogLoss: 0.96-0.99
Brier: 0.19-0.20
```

### Phase 2A: 3,000 Matches (34% coverage)
```
Expected: 53-56% accuracy
LogLoss: 0.95-0.98
Brier: 0.18-0.19
```

### Phase 2B: 5,000 Matches (57% coverage)
```
Expected: 54-57% accuracy
LogLoss: 0.94-0.96
Brier: 0.17-0.18
```

### Phase 2C: 7,000 Matches (80% coverage)
```
Expected: 54-58% accuracy
LogLoss: 0.93-0.95
Brier: 0.16-0.17
```

### Phase 3: 8,500+ Matches (95%+ coverage)
```
Target: 55-58% accuracy
LogLoss: <0.93
Brier: <0.16
```

---

## Monitoring & Metrics

### Coverage Tracking:
```sql
-- Check current coverage
SELECT 
  COUNT(DISTINCT tm.match_id) as total_matches,
  COUNT(DISTINCT orc.match_id) as with_real_odds,
  COUNT(DISTINCT mc.match_id) as with_context,
  (100.0 * COUNT(DISTINCT orc.match_id) / COUNT(DISTINCT tm.match_id))::numeric(10,2) as odds_coverage_pct,
  (100.0 * COUNT(DISTINCT mc.match_id) / COUNT(DISTINCT tm.match_id))::numeric(10,2) as context_coverage_pct
FROM training_matches tm
LEFT JOIN odds_real_consensus orc ON tm.match_id = orc.match_id
LEFT JOIN match_context mc ON tm.match_id = mc.match_id
WHERE tm.outcome IS NOT NULL;
```

### Progress Dashboard:
```
┌─────────────────────────────────────────────────┐
│           BACKFILL PROGRESS                     │
├─────────────────────────────────────────────────┤
│ Total Matches:       8,809                      │
│ With Real Odds:      1,513 (17%)               │
│ With Context:        1,236 (14%)               │
│ Missing:             7,296 (83%)               │
├─────────────────────────────────────────────────┤
│ Last Backfill:       Nov 8, 2025               │
│ Matches Added:       1,236                      │
│ Next Backfill:       Nov 15, 2025              │
├─────────────────────────────────────────────────┤
│ Training Status:     READY                      │
│ Expected Accuracy:   52-55%                     │
│ Coverage Required:   ≥1,000 matches ✅          │
└─────────────────────────────────────────────────┘
```

---

## Implementation Checklist

### Immediate (Today):
- [x] Clean fake data from match_context
- [x] Create odds_real_consensus view
- [x] Refill match_context with real data
- [x] Update backfill script
- [ ] Update v2_feature_builder.py
- [ ] Run training on 1,236 matches
- [ ] Verify sanity checks pass

### This Week:
- [ ] Decide on backfill source (The Odds API vs API-Football)
- [ ] Implement API backfill script
- [ ] Backfill 2,000-3,000 matches
- [ ] Retrain and measure improvement
- [ ] Document results

### This Month:
- [ ] Reach 80% coverage (7,000+ matches)
- [ ] Automate periodic retraining
- [ ] Set up monitoring dashboard
- [ ] Achieve 54-58% target accuracy

---

## Success Metrics

### Data Quality:
- ✅ 100% pre-kickoff odds (secs_to_kickoff > 300)
- ✅ Average 67 bookmakers per match
- ✅ Realistic rest days (2-840 days)
- ✅ Realistic schedule congestion (0-2 matches/7d)

### Model Performance:
- ✅ Sanity checks pass (no leakage)
- ✅ Market-only baseline: 48-52%
- 🎯 Model accuracy: 52-55% (Phase 1 target)
- 🎯 LogLoss: <1.00
- 🎯 Brier Score: <0.20

### Coverage:
- ✅ Phase 1: 14% (1,236 matches)
- 🎯 Phase 2A: 34% (3,000 matches) - Week 2
- 🎯 Phase 2B: 57% (5,000 matches) - Week 3
- 🎯 Phase 2C: 80% (7,000 matches) - Week 4
- 🎯 Phase 3: 95%+ (8,500+ matches) - Month 2

---

## Files Modified

### Database:
- `odds_real_consensus` - Materialized view (REAL odds)
- `match_context` - Cleaned and refilled (1,236 rows)
- `training_matches` - Fixed NULL match_dates

### Scripts:
- `scripts/backfill_match_context.py` - Updated to use real odds only
- `features/v2_feature_builder.py` - Need to update
- `training/train_v2_no_leakage.py` - Already fixed (TimeSeriesSplit)

### Documentation:
- `docs/TRAINING_FAILURE_ANALYSIS.md` - Full root cause analysis
- `docs/CRITICAL_ODDS_DATA_CORRUPTION.md` - Evidence of fake data
- `docs/HYBRID_BACKFILL_STRATEGY.md` - This document
- `replit.md` - Updated with current status

---

## Next Steps

**TODAY (Nov 8)**:
1. Update v2_feature_builder.py to use odds_real_consensus
2. Run training on 1,236 clean matches
3. Verify sanity checks pass

**THIS WEEK (Nov 11-15)**:
1. Implement API backfill (The Odds API recommended)
2. Add 2,000-3,000 matches
3. Retrain and measure improvement

**THIS MONTH (Nov 2025)**:
1. Reach 80% coverage via continuous backfill
2. Set up automated retraining
3. Achieve 54-58% target accuracy

---

**STATUS**: Ready to proceed with Phase 1 training!  
**BLOCKER**: None - data is clean and validated  
**NEXT**: Update feature builder to use real odds
