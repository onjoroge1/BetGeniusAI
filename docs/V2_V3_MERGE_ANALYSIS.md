# V2/V3 Model Architecture Analysis & Improvement Recommendations

**Generated:** December 6, 2025  
**Purpose:** Analyze whether to merge V3 into V2 and identify accuracy improvement opportunities

---

## EXECUTIVE SUMMARY

### Should V3 Be Merged Into V2?

**RECOMMENDATION: YES - Merge Phase 2B (V3) into V2**

The current architecture has unnecessary fragmentation:
- V2 uses only **17 of 50 available features** (34% utilization)
- V3 adds 17 new features on a **separate codebase**
- Both use the same LightGBM architecture
- Maintaining two similar models doubles maintenance burden

**Proposed Unified V2:**
```
Current State:
├─ V2 Predictor: 17 odds features → 49.5% accuracy
├─ V3 Predictor: 34 features (17 V2 + 17 new) → 46.8% accuracy (undertrained)
└─ V2 Feature Builder: 50 features available (unused by V2!)

Proposed Unified V2:
├─ V2 Predictor: 50+ features → Target 53-56% accuracy
├─ Features: All V2 (50) + Sharp Book (4) + ECE (3) + Timing (4)
└─ Single training pipeline, single endpoint
```

---

## DATA INVENTORY

### Available Tables & Coverage

| Table | Records | Unique Matches | Purpose |
|-------|---------|----------------|---------|
| training_matches | 11,992 | 11,992 | Historical training data (2022-2025) |
| fixtures | 1,684 | 1,684 | Match metadata |
| matches | 1,490 | 1,490 | Results/outcomes |
| match_context_v2 | 6,727 | 6,727 | Rest days, congestion (leak-free) |
| match_features | 6,185 | 6,185 | Pre-computed features with drift |
| odds_consensus | 8,163 | - | Aggregated odds |
| odds_real_consensus | 1,005 | - | Clean pre-match odds |
| odds_snapshots | 393,554 | 2,666 | Time-series odds for drift |
| sharp_book_odds | 79,420 | 43 | Pinnacle/Betfair/Matchbook |
| league_calibration | 18 | 18 leagues | ECE tier weights |
| historical_odds | 40,940 | 40,940 | Rich data (1993-2025) |
| elo_ratings | 932 | 516 teams | Team strength ratings |

### Key Data Insights

1. **Rich Historical Data Available:**
   - 40,940 matches with full stats (shots, corners, yellows)
   - 30,290 matches with Pinnacle odds
   - 36,080 matches with shots data

2. **Feature Coverage Gaps:**
   - ELO ratings only cover 932 records (limited date range: Sep-Oct 2025)
   - Injury data: 0 records (collector exists but no data)
   - Form features in match_features: 0 records (column exists but empty)

3. **Linkage Statistics:**
   - training_matches → context_v2: 1,281 matches (10.7%)
   - training_matches → odds_consensus: 1,281 matches (10.7%)
   - training_matches → elo: 14,808 joins (duplicates from team matching)
   - fixtures → match_features: 424 matches

---

## V2 CURRENT STATE ANALYSIS

### What V2 Model Uses (17 features)

```json
[
  "p_open_home", "p_open_draw", "p_open_away",
  "p_last_home", "p_last_draw", "p_last_away",
  "num_books_last", "book_dispersion", "market_entropy",
  "dispersion_home", "dispersion_draw", "dispersion_away",
  "favorite_margin",
  "prob_drift_home", "prob_drift_draw", "prob_drift_away", 
  "drift_magnitude"
]
```

### What V2 Feature Builder CAN Produce (50 features)

| Category | Features | Count | Status in V2 |
|----------|----------|-------|--------------|
| Odds | prob_home/draw/away, dispersion, volatility, coverage | 18 | Partial (17) |
| ELO | home_elo, away_elo, elo_diff | 3 | NOT USED |
| Form | points_last_5, goals_scored/conceded | 6 | NOT USED |
| Home Advantage | home_wins_last_10, away_wins_last_10 | 2 | NOT USED |
| H2H | h2h_home_wins, h2h_draws, h2h_away_wins | 3 | NOT USED |
| Advanced Stats | shots, shots_on_target, corners, yellows | 8 | NOT USED |
| Schedule/Rest | rest_days_home/away | 2 | NOT USED |
| Context | congestion_home/away_7d | 4 | NOT USED |
| Drift | prob_drift_*, drift_magnitude | 4 | ✓ USED |

**WASTED POTENTIAL: 33 features available but unused!**

---

## FEATURE COVERAGE ANALYSIS

### 1. Sharp Book Features (V3 Addition)

| Metric | Value |
|--------|-------|
| Total sharp odds collected | 79,420 |
| Unique matches with sharp | 43 |
| Pre-match odds (usable) | 39 matches |
| Post-match odds (unusable for training) | 4 matches |

**Timing Distribution:**
| Window | Odds Count | Matches |
|--------|------------|---------|
| T-24h+ | 40,196 | 20 |
| T-12-24h | 16,059 | 31 |
| T-6-12h | 10,823 | 18 |
| T-1-6h | 7,863 | 18 |
| T-0-1h | 1,627 | 17 |
| Post-match | 2,886 | 17 |

**Assessment:** Sharp book data collection is working well, but only 39 matches have usable pre-match data. Need 1-2 weeks of accumulation for meaningful training.

### 2. League ECE Calibration Features

| Metric | Value |
|--------|-------|
| Leagues calibrated | 18 |
| Matches in calibrated leagues | 1,206 |

**Assessment:** Good coverage for current data. All major leagues have ECE scores.

### 3. Drift Features (Odds Movement)

| Metric | Value |
|--------|-------|
| Matches with odds snapshots | 2,666 |
| Total snapshots | 393,554 |
| Avg hours before kickoff | 34.7h |
| match_features with drift | 6,185 |

**Assessment:** Excellent drift data available but NOT USED by current V2 model despite being in feature list. Investigation needed.

### 4. Injury Features

| Metric | Value |
|--------|-------|
| Injury records | 0 |
| player_injuries table | EXISTS but EMPTY |

**Assessment:** Collector infrastructure exists but no data collected. Requires API-Sports premium access for player data.

### 5. ELO Ratings

| Metric | Value |
|--------|-------|
| Total ELO records | 932 |
| Unique teams | 516 |
| Date range | Sep 21 - Oct 22, 2025 |

**Assessment:** Very limited date range. Only covers 1 month of data. Needs backfill.

### 6. Form & Advanced Stats (historical_odds)

| Metric | Value |
|--------|-------|
| Total historical matches | 40,940 |
| Matches with shots data | 36,074 (88%) |
| Matches with corners data | 36,084 (88%) |
| Matches with Pinnacle odds | 30,290 (74%) |
| Date range | 1993-2025 |

**Assessment:** GOLDMINE! This table has rich data that could significantly improve V2 if properly linked and utilized.

---

## ACCURACY IMPROVEMENT OPPORTUNITIES

### Priority 1: Enable Full V2 Feature Set (HIGH IMPACT)

**Current:** 17 features, 49.5% accuracy  
**Potential:** 50 features, estimated 53-55% accuracy

| Feature Group | Expected Impact | Data Ready? |
|---------------|-----------------|-------------|
| ELO ratings | +1-2% | Limited (1 month) |
| Form metrics | +1-2% | Available via historical_odds |
| H2H history | +0.5-1% | Need to compute |
| Advanced stats | +0.5-1% | Available via historical_odds |
| Context (rest/congestion) | +0.5% | Available in match_context_v2 |

**Action:** Train V2 with full 50 features instead of 17.

### Priority 2: Add Sharp Book Intelligence (MEDIUM IMPACT)

**Current:** 0 features from sharp books  
**Potential:** 4 features, estimated +1-2% accuracy

| Feature | Description | Data Ready? |
|---------|-------------|-------------|
| sharp_prob_home/draw/away | Pinnacle devigged probs | 39 matches |
| soft_vs_sharp_divergence | Recreational vs sharp gap | 39 matches |

**Action:** Wait 1-2 weeks for 200+ matches with pre-match sharp odds.

### Priority 3: Leverage historical_odds Table (HIGH IMPACT)

This table contains 40,940 matches with rich data:
- Pre-match odds from 8+ bookmakers
- Post-match statistics (shots, corners, cards)
- Date range: 1993-2025

**Potential Features:**
- Historical form (goals scored/conceded last 5 matches)
- Historical H2H results
- Team shot efficiency
- Discipline metrics (cards per match)

**Action:** Create linkage between training_matches and historical_odds via team names.

### Priority 4: Expand Training Dataset (MEDIUM IMPACT)

| Dataset | Current | Target | Impact |
|---------|---------|--------|--------|
| Clean trainable matches | 422 | 1,000+ | +1-2% |
| Historical with features | 1,281 | 5,000+ | +2-3% |

**Action:** Backfill match_context_v2 for older training_matches.

---

## RECOMMENDED UNIFIED V2 ARCHITECTURE

### Feature Composition (61 total)

```
UNIFIED V2 FEATURE SET:
═══════════════════════════════════════════════════

Core Odds Features (18):
├─ prob_home, prob_draw, prob_away
├─ book_dispersion_home/draw/away
├─ odds_volatility_home/draw/away
├─ book_coverage, market_overround
├─ num_books, favorite_margin
└─ market_entropy

Drift Features (4):
├─ prob_drift_home, prob_drift_draw, prob_drift_away
└─ drift_magnitude

Team Strength Features (3):
├─ home_elo, away_elo
└─ elo_diff

Form Features (6):
├─ form5_home_points, form5_away_points
├─ home_goals_scored_avg, home_goals_conceded_avg
└─ away_goals_scored_avg, away_goals_conceded_avg

H2H Features (3):
├─ h2h_home_wins, h2h_draws, h2h_away_wins

Advanced Stats Features (8):
├─ home_shots_avg, away_shots_avg
├─ home_shots_target_avg, away_shots_target_avg
├─ home_corners_avg, away_corners_avg
└─ home_yellows_avg, away_yellows_avg

Context Features (4):
├─ rest_days_home, rest_days_away
├─ congestion_home_7d, congestion_away_7d

Sharp Book Features (4) [NEW from V3]:
├─ sharp_prob_home, sharp_prob_draw, sharp_prob_away
└─ soft_vs_sharp_divergence

League ECE Features (3) [NEW from V3]:
├─ league_ece, league_tier_weight
└─ league_historical_edge

Market Timing Features (4) [NEW from V3]:
├─ movement_velocity_24h, steam_move_detected
├─ reverse_line_movement
└─ time_to_kickoff_bucket

TOTAL: 61 features
```

### Implementation Plan

```
PHASE A: IMMEDIATE (Week 1)
═══════════════════════════════════════════════════
1. Update V2 training script to use all 50 V2FeatureBuilder features
2. Train with 422 clean matches
3. Target: 51-53% accuracy

PHASE B: INTEGRATION (Week 2)
═══════════════════════════════════════════════════
1. Merge V3FeatureBuilder sharp/ECE/timing into V2FeatureBuilder
2. Consolidate into single unified_v2_feature_builder.py
3. Update /predict-v2 endpoint
4. Deprecate /predict-v3 (or redirect to v2)

PHASE C: DATA EXPANSION (Weeks 3-4)
═══════════════════════════════════════════════════
1. Backfill match_context_v2 for older matches
2. Create historical_odds → training_matches linkage
3. Compute form/H2H from historical data
4. Target: 1,000+ trainable matches

PHASE D: SHARP INTEGRATION (Weeks 4-6)
═══════════════════════════════════════════════════
1. Accumulate 200+ matches with pre-match sharp odds
2. Retrain with full feature set (61 features)
3. Target: 54-56% accuracy
```

---

## ACCURACY PROJECTION

| Stage | Features | Training Size | Expected Accuracy |
|-------|----------|---------------|-------------------|
| Current V2 | 17 | 1,000 | 49.5% |
| Phase A (Full V2) | 50 | 422 | 51-53% |
| Phase B (Unified) | 57 | 422 | 52-54% |
| Phase C (Expanded) | 57 | 1,000+ | 53-55% |
| Phase D (Sharp) | 61 | 1,000+ | 54-56% |

---

## CONCLUSION

### Key Findings

1. **V2 is severely underutilized** - Only using 17/50 available features
2. **V3 adds value but should merge into V2** - Same architecture, unnecessary separation
3. **Rich historical data exists** - 40,940 matches with stats in historical_odds table
4. **Sharp book collection working** - Need 1-2 weeks for sufficient training data
5. **Main bottleneck is feature utilization, not data volume**

### Recommended Actions

1. **IMMEDIATE:** Run V2 training with full 50 features
2. **SHORT-TERM:** Merge V3 features into V2, consolidate endpoints
3. **MEDIUM-TERM:** Link historical_odds for form/stats features
4. **LONG-TERM:** Build true Phase 3 ensemble stack when V2 hits 54%+

### Expected Outcome

Unified V2 with 61 features achieving **54-56% accuracy** - beating V1's 54.3% baseline and providing a solid foundation for Phase 3 ensemble stack targeting 57-58%.
