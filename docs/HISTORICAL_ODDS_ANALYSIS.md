# Historical Odds Table Analysis & Training Integration Strategy

## Overview

The `historical_odds` table contains **40,940 matches** from 1993-2025 with rich statistical data that can significantly improve V2 model accuracy. This document analyzes the data and provides a pairing strategy with `match_context_v2`.

---

## Data Summary

### Table Statistics

| Metric | Value |
|--------|-------|
| Total Matches | 40,940 |
| Date Range | July 1993 - November 2025 |
| Leagues | 21 |
| With Shots Data | 36,074 (88%) |
| With Corners Data | 36,084 (88%) |
| With Pinnacle Odds | 30,290 (74%) |
| Recent (2024+) | 6,047 matches |

### League Coverage (2024+)

| League Code | Description | Matches | Has Stats |
|-------------|-------------|---------|-----------|
| SP2 | Spain Segunda | 693 | ✅ |
| SP1 | Spain La Liga | 580 | ✅ |
| I1 | Italy Serie A | 580 | ✅ |
| I2 | Italy Serie B | 570 | ✅ |
| E0 | England Premier League | 564 | ✅ |
| T1 | Turkey Super Lig | 552 | ✅ |
| P1 | Portugal Primeira Liga | 477 | ✅ |
| D1 | Germany Bundesliga | 469 | ✅ |
| N1 | Netherlands Eredivisie | 468 | ✅ |
| B1 | Belgium Pro League | 464 | ✅ |
| D2 | Germany 2. Bundesliga | 459 | ✅ |

### Available Data Fields

```
Match Info:
├─ match_date, season, league
├─ home_team, away_team
├─ home_goals, away_goals, result

Bookmaker Odds (8 books):
├─ b365_h/d/a (Bet365)
├─ bw_h/d/a (Betway)
├─ iw_h/d/a (Interwetten)
├─ lb_h/d/a (Ladbrokes)
├─ ps_h/d/a (Pinnacle)
├─ wh_h/d/a (William Hill)
├─ sj_h/d/a (Stan James)
├─ vc_h/d/a (VC Bet)

Market Aggregates:
├─ avg_h/d/a (Average odds)
├─ max_h/d/a (Maximum odds)

Asian Handicap:
├─ ah_line, ah_home_odds, ah_away_odds

Over/Under:
├─ ou_line, over_odds, under_odds

Match Statistics:
├─ home_shots, away_shots
├─ home_shots_target, away_shots_target
├─ home_corners, away_corners
├─ home_fouls, away_fouls
├─ home_yellows, away_yellows
├─ home_reds, away_reds
```

---

## Team Name Matching Analysis

### Successful Linkage Examples

| Historical Team | Training Team | Matched Rows |
|-----------------|---------------|--------------|
| Napoli | Napoli | 31 |
| Udinese | Udinese | 31 |
| Atalanta | Atalanta | 30 |
| Verona | Verona | 30 |
| Inter | Inter | 29 |
| RB Leipzig | RB Leipzig | 27 |
| Valencia | Valencia | 26 |

**Finding:** Direct name matching works for ~500+ matches across major European leagues.

### League Code Mapping

| Historical Code | API-Football League ID | League Name |
|-----------------|----------------------|-------------|
| E0 | 39 | Premier League |
| SP1 | 140 | La Liga |
| I1 | 135 | Serie A |
| D1 | 78 | Bundesliga |
| P1 | 94 | Primeira Liga |
| N1 | 88 | Eredivisie |
| B1 | 144 | Belgian Pro League |
| T1 | 203 | Turkish Super Lig |

---

## Feature Extraction Strategy

### 1. Direct Statistics Features

Compute rolling averages from `historical_odds` for matched teams:

```sql
-- Example: Get team's average shots in last 5 matches
SELECT 
    AVG(CASE WHEN home_team = 'Liverpool' THEN home_shots ELSE away_shots END) as avg_shots,
    AVG(CASE WHEN home_team = 'Liverpool' THEN home_shots_target ELSE away_shots_target END) as avg_sot,
    AVG(CASE WHEN home_team = 'Liverpool' THEN home_corners ELSE away_corners END) as avg_corners
FROM historical_odds
WHERE (home_team = 'Liverpool' OR away_team = 'Liverpool')
    AND match_date < '2024-12-01'
ORDER BY match_date DESC
LIMIT 5;
```

### 2. Derived Features

| Feature | Formula | Expected Impact |
|---------|---------|-----------------|
| `shot_efficiency` | `goals / shots` | Attack quality |
| `shot_accuracy` | `shots_on_target / shots` | Finishing ability |
| `discipline_score` | `yellows + reds * 2` | Card propensity |
| `corner_dominance` | `home_corners / (home_corners + away_corners)` | Set piece threat |
| `defensive_solidity` | `1 / (goals_conceded_avg + 0.1)` | Defense rating |

### 3. H2H Features from Historical

```sql
-- Head-to-head history
SELECT 
    SUM(CASE WHEN result = 'H' THEN 1 ELSE 0 END) as h2h_home_wins,
    SUM(CASE WHEN result = 'D' THEN 1 ELSE 0 END) as h2h_draws,
    SUM(CASE WHEN result = 'A' THEN 1 ELSE 0 END) as h2h_away_wins,
    AVG(home_goals + away_goals) as h2h_avg_goals
FROM historical_odds
WHERE home_team = 'Liverpool' AND away_team = 'Everton'
    OR home_team = 'Everton' AND away_team = 'Liverpool';
```

---

## Pairing Strategy with match_context_v2

### Current match_context_v2 Structure

```
match_id (bigint)
as_of_time (timestamp)
rest_days_home (numeric)
rest_days_away (numeric)
matches_home_last_3d (int)
matches_home_last_7d (int)
matches_away_last_3d (int)
matches_away_last_7d (int)
derby_flag (boolean)
```

### Integration Points

| Feature Source | match_context_v2 | historical_odds | Combined Value |
|----------------|------------------|-----------------|----------------|
| Rest days | ✅ `rest_days_*` | ❌ Not available | Use context_v2 |
| Schedule congestion | ✅ `matches_*_last_7d` | ❌ Not available | Use context_v2 |
| Shot stats | ❌ Not available | ✅ Full history | Use historical |
| Corner stats | ❌ Not available | ✅ Full history | Use historical |
| Card stats | ❌ Not available | ✅ Full history | Use historical |
| Form (goals) | ❌ Partial | ✅ Full history | Use historical |
| Historical odds | ❌ Not available | ✅ 8 bookmakers | Use historical |

### Recommended Join Strategy

```sql
-- Create enhanced training view
CREATE OR REPLACE VIEW enhanced_training_data AS
SELECT 
    tm.*,
    mc.rest_days_home,
    mc.rest_days_away,
    mc.matches_home_last_7d as congestion_home_7d,
    mc.matches_away_last_7d as congestion_away_7d,
    -- Historical stats (computed separately per team)
    h_home.avg_shots as home_avg_shots,
    h_home.avg_corners as home_avg_corners,
    h_away.avg_shots as away_avg_shots,
    h_away.avg_corners as away_avg_corners
FROM training_matches tm
LEFT JOIN match_context_v2 mc ON tm.fixture_id = mc.match_id
LEFT JOIN LATERAL (
    SELECT 
        AVG(CASE WHEN home_team = tm.home_team THEN home_shots ELSE away_shots END) as avg_shots,
        AVG(CASE WHEN home_team = tm.home_team THEN home_corners ELSE away_corners END) as avg_corners
    FROM historical_odds
    WHERE (home_team = tm.home_team OR away_team = tm.home_team)
        AND match_date < tm.match_date::date
    LIMIT 5
) h_home ON true
LEFT JOIN LATERAL (
    SELECT 
        AVG(CASE WHEN home_team = tm.away_team THEN home_shots ELSE away_shots END) as avg_shots,
        AVG(CASE WHEN home_team = tm.away_team THEN home_corners ELSE away_corners END) as avg_corners
    FROM historical_odds
    WHERE (home_team = tm.away_team OR away_team = tm.away_team)
        AND match_date < tm.match_date::date
    LIMIT 5
) h_away ON true;
```

---

## Implementation Recommendations

### Phase 1: Direct Linkage (Immediate)

1. Add team name normalization function
2. Create lookup view for matched teams
3. Compute 5-match rolling averages for shots/corners

**Expected Matches:** ~500-800 matches linkable directly

### Phase 2: Fuzzy Matching (1-2 days)

1. Implement Levenshtein distance matching
2. Create team name synonym table
3. Handle common variations (FC, United, City, etc.)

**Expected Additional Matches:** ~1,000-2,000 more

### Phase 3: ID-Based Linking (Optional)

1. Add `api_football_id` to historical_odds if available
2. Use fixture ID resolver to cross-reference
3. Build permanent linkage table

---

## Expected Accuracy Impact

| Feature Group | Current Source | With Historical | Expected Impact |
|---------------|----------------|-----------------|-----------------|
| Shot efficiency | ❌ None | ✅ 36K matches | +0.5-1% |
| Corner dominance | ❌ None | ✅ 36K matches | +0.3-0.5% |
| Discipline/cards | ❌ None | ✅ 36K matches | +0.2-0.3% |
| Historical H2H | Partial (training_matches) | ✅ Full history | +0.3-0.5% |
| Pinnacle consensus | ❌ Only recent | ✅ 30K matches | +0.5-1% |

**Total Expected Impact:** +1.5-3% accuracy improvement

---

## Summary

### Key Findings

1. **Rich Data Available:** 40,940 matches with detailed statistics
2. **Good Linkage Potential:** ~500-2,000 matches can be directly linked
3. **Complementary to match_context_v2:** Historical provides stats, context provides schedule
4. **Significant Accuracy Potential:** +1.5-3% improvement possible

### Action Items

1. ✅ Unified V2 feature builder already queries historical_odds
2. ⏳ Add team name normalization for better matching
3. ⏳ Create league code → league_id mapping table
4. ⏳ Backfill historical stats to match_features table

### Priority

**HIGH** - This is one of the lowest-effort, highest-impact improvements available. The data exists, the unified feature builder already queries it, and the expected accuracy gain (1.5-3%) exceeds most other optimizations.
