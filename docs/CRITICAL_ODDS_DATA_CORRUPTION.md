# 🚨 CRITICAL: Odds Data Completely Corrupted

## Executive Summary

**The entire odds_consensus table contains FAKE/BACKDATED data that was created AFTER matches finished.**

Training cannot proceed until real pre-kickoff odds data is obtained.

---

## Evidence of Data Corruption

### Smoking Gun Example:
```sql
Match ID: 1223598
Kickoff Time: 2024-08-17 16:30:00
ts_effective: 2024-08-17 16:30:00  ← Claims to be "at kickoff"
created_at:   2025-08-31 18:00:35  ← CREATED 379 DAYS LATER!
Outcome: Draw ← Result was KNOWN when "odds" were created
```

### Full Dataset Analysis:
- **100% of "AT-KO" odds** created on 2025-08-31 18:00:35
- **20% POST-KICKOFF** odds (ts_effective > match_date)
- **0% TRUE PRE-KICKOFF** odds (ts_effective < match_date)

### Impact:
```
Market-Only Sanity Check: 100% accuracy ← IMPOSSIBLE WITHOUT CHEATING!
Expected: 48-52% (efficient markets)
Actual: 100% (because "odds" know the results)
```

---

## Root Cause

Someone ran a batch job on **August 31, 2025** that:
1. Took historical match results
2. Back-calculated "odds" to fit the results
3. Set `ts_effective` to match kickoff times (backdating)
4. Inserted into `odds_consensus` table

This is not real betting market data - it's reverse-engineered from results.

---

## Why Training Failed

### Phase 1: Low Coverage (42.6%)
- Only 42.6% of matches had ANY odds
- Because we required `n_books >= 3`
- Many matches have no odds at all

### Phase 2: Perfect Leakage (100% accuracy)
- The "odds" that DO exist are fake
- Created AFTER results were known
- Model memorizes the embedded results → 100% accuracy
- This is why:
  - Random shuffle: 40% (should be ~33%) ← Leakage
  - Market-only: 100% (should be 48-52%) ← Severe leakage

---

## What Tables Have Real Data?

Checking:
- ❌ `odds_consensus` - FAKE (backdated)
- ❓ `historical_odds` - Checking...
- ❓ `odds_snapshots` - Checking...
- ❓ `closing_odds` - Checking...

---

## Required Actions

### Immediate (Block Training):
1. ✅ **STOP ALL TRAINING** - Current model will be worthless
2. ✅ **Document this issue** - Prevent future confusion
3. ⏳ **Audit other odds tables** - Find real data source

### Short-term (Get Real Data):
1. **Option A**: Find real-time odds collection
   - Check `odds_snapshots` table
   - Check external API logs
   - Verify `created_at <= kickoff_at`

2. **Option B**: Re-collect odds data
   - The Odds API (historical odds available)
   - API-Football (historical odds available)
   - Ensure `created_at` is BEFORE `match_date`

3. **Option C**: Use subset with real data
   - Filter to only future matches (not historical)
   - Collect odds in real-time going forward
   - Start with smaller, clean dataset

### Long-term (Data Pipeline Fix):
1. **Validation Rules**:
   ```sql
   -- Enforce at insert time
   CHECK (created_at <= match_date - INTERVAL '1 hour')
   CHECK (ts_effective <= match_date)
   ```

2. **Real-time Collection**:
   - Collect odds BEFORE matches start
   - Never backdate timestamps
   - Store creation metadata

3. **Audit Trail**:
   - Track data source for each row
   - Flag any backdated data
   - Alert on suspicious patterns

---

## Impact on Project Timeline

### Can't Train Phase 2 Until:
- ❌ Fix odds data source
- ❌ Get real pre-kickoff odds
- ❌ Verify sanity checks pass

### Estimated Delay:
- **2-4 weeks** if using API historical data
- **2-3 months** if collecting real-time going forward
- **Immediate** if clean data source found in database

---

## Recommendations

1. **Immediate**: Check if `odds_snapshots` or `historical_odds` have real data
2. **If not**: Use The Odds API to backfill historical odds (costs money)
3. **Going forward**: Set up real-time odds collection pipeline
4. **Document**: Add data quality checks to prevent this again

---

## Files Involved

### Corrupted:
- `odds_consensus` table - ALL DATA FAKE

### To Check:
- `odds_snapshots` - May have real data
- `historical_odds` - May have real data  
- `closing_odds` - May have real data

### Fixed (But Can't Use Yet):
- `features/v2_feature_builder.py` - Has anti-leakage validation
- `training/train_v2_no_leakage.py` - Has time-based CV for sanity checks
- `odds_prekickoff_clean` view - Would work IF data was real

---

## Next Steps

1. Run audit on all odds tables
2. If no real data found → halt Phase 2, collect new data
3. If real data found → switch pipeline to use it
4. Re-run training with clean data
5. Verify sanity checks pass (market-only ~50%, shuffle ~33%)

**DO NOT TRAIN until this is resolved!**
