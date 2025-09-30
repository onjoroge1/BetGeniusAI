# BetGenius AI - League Expansion Plan

## Current State (19 Leagues)

### Tier 1 European (6 leagues)
- Premier League, La Liga, Serie A, Bundesliga, Ligue 1, Eredivisie

### Tier 2 European (5 leagues)
- Championship, LaLiga2, Serie B, 2. Bundesliga, Ligue 2

### Americas (4 leagues)
- Brasileirão, Liga MX, MLS, Liga Profesional Argentina

### Other European (4 leagues)
- Primeira Liga, Scottish Premiership, Jupiler Pro League, Süper Lig

---

## PRIORITY 1: UEFA Competitions (High Priority)
**Target Date: Within 1 week**
**Rationale: Maximum bookmaker coverage, high betting volume, international appeal**

| League Name | Odds API Key | RapidAPI ID | Notes |
|-------------|--------------|-------------|-------|
| UEFA Champions League | `soccer_uefa_champs_league` | `2` | Top tier European competition |
| UEFA Europa League | `soccer_uefa_europa_league` | `3` | Second tier European competition |
| UEFA Conference League | `soccer_uefa_europa_conference_league` | `4` | Third tier European competition |

### INSERT Statement - Priority 1
```sql
INSERT INTO league_map (theodds_sport_key, league_id, league_name)
VALUES
  ('soccer_uefa_champs_league', 2, 'UEFA Champions League'),
  ('soccer_uefa_europa_league', 3, 'UEFA Europa League'),
  ('soccer_uefa_europa_conference_league', 4, 'UEFA Conference League')
ON CONFLICT (theodds_sport_key) DO NOTHING;
```

**Backfill Required: YES**
- UEFA competitions have historical data available
- Recommend backfilling current season (2024/25) matches
- High data quality with comprehensive bookmaker coverage

---

## PRIORITY 2: English Lower Divisions (High Priority)
**Target Date: Within 2 weeks**
**Rationale: Strong bookmaker coverage, complement existing Championship data**

| League Name | Odds API Key | RapidAPI ID | Notes |
|-------------|--------------|-------------|-------|
| English League One | `soccer_england_league1` | `45` | Third tier English football |
| English League Two | `soccer_england_league2` | `46` | Fourth tier English football |
| FA Cup | `soccer_fa_cup` | `48` | England's primary knockout competition |
| EFL Cup | `soccer_england_efl_cup` | `47` | League Cup competition |

### INSERT Statement - Priority 2
```sql
INSERT INTO league_map (theodds_sport_key, league_id, league_name)
VALUES
  ('soccer_england_league1', 45, 'League One'),
  ('soccer_england_league2', 46, 'League Two'),
  ('soccer_fa_cup', 48, 'FA Cup'),
  ('soccer_england_efl_cup', 47, 'EFL Cup')
ON CONFLICT (theodds_sport_key) DO NOTHING;
```

**Backfill Required: PARTIAL**
- League competitions: YES (full season data)
- Cup competitions: CURRENT ROUND ONLY (single-elimination format)

---

## PRIORITY 3: Asian & South American Markets (Medium-High Priority)
**Target Date: Within 3-4 weeks**
**Rationale: Growing betting markets, diverse timezone coverage, strong regional interest**

| League Name | Odds API Key | RapidAPI ID | Notes |
|-------------|--------------|-------------|-------|
| J League (Japan) | `soccer_japan_j_league` | `98` | Top tier Japanese football |
| K League 1 (Korea) | `soccer_korea_kleague1` | `292` | Top tier Korean football |
| Brazil Serie B | `soccer_brazil_serie_b` | `72` | Second tier Brazilian football |
| Copa Libertadores | `soccer_conmebol_copa_libertadores` | `13` | Premier South American club competition |

### INSERT Statement - Priority 3
```sql
INSERT INTO league_map (theodds_sport_key, league_id, league_name)
VALUES
  ('soccer_japan_j_league', 98, 'J1 League'),
  ('soccer_korea_kleague1', 292, 'K League 1'),
  ('soccer_brazil_serie_b', 72, 'Brasileirão Série B'),
  ('soccer_conmebol_copa_libertadores', 13, 'Copa Libertadores')
ON CONFLICT (theodds_sport_key) DO NOTHING;
```

**Backfill Required: YES**
- All leagues have strong historical data
- Copa Libertadores: current tournament only

---

## PRIORITY 4: Northern European Markets (Medium Priority)
**Target Date: Within 5-6 weeks**
**Rationale: Good bookmaker coverage, stable leagues, complement Eredivisie data**

| League Name | Odds API Key | RapidAPI ID | Notes |
|-------------|--------------|-------------|-------|
| Denmark Superliga | `soccer_denmark_superliga` | `119` | Top tier Danish football |
| Norway Eliteserien | `soccer_norway_eliteserien` | `103` | Top tier Norwegian football |
| Sweden Allsvenskan | `soccer_sweden_allsvenskan` | `113` | Top tier Swedish football |
| Austria Bundesliga | `soccer_austria_bundesliga` | `218` | Top tier Austrian football |
| Switzerland Super League | `soccer_switzerland_superleague` | `207` | Top tier Swiss football |

### INSERT Statement - Priority 4
```sql
INSERT INTO league_map (theodds_sport_key, league_id, league_name)
VALUES
  ('soccer_denmark_superliga', 119, 'Superliga'),
  ('soccer_norway_eliteserien', 103, 'Eliteserien'),
  ('soccer_sweden_allsvenskan', 113, 'Allsvenskan'),
  ('soccer_austria_bundesliga', 218, 'Austrian Bundesliga'),
  ('soccer_switzerland_superleague', 207, 'Swiss Super League')
ON CONFLICT (theodds_sport_key) DO NOTHING;
```

**Backfill Required: PARTIAL**
- Current season only (some leagues have winter breaks)
- Focus on active seasons

---

## PRIORITY 5: Southern/Eastern European Markets (Medium Priority)
**Target Date: Within 7-8 weeks**
**Rationale: Moderate bookmaker coverage, growing markets**

| League Name | Odds API Key | RapidAPI ID | Notes |
|-------------|--------------|-------------|-------|
| Greece Super League | `soccer_greece_super_league` | `197` | Top tier Greek football |
| Poland Ekstraklasa | `soccer_poland_ekstraklasa` | `106` | Top tier Polish football |

### INSERT Statement - Priority 5
```sql
INSERT INTO league_map (theodds_sport_key, league_id, league_name)
VALUES
  ('soccer_greece_super_league', 197, 'Super League Greece'),
  ('soccer_poland_ekstraklasa', 106, 'Ekstraklasa')
ON CONFLICT (theodds_sport_key) DO NOTHING;
```

**Backfill Required: YES**
- Current season recommended

---

## PRIORITY 6: German Third Tier (Low-Medium Priority)
**Target Date: Within 9-10 weeks**
**Rationale: Completes German football pyramid, good for deep learning**

| League Name | Odds API Key | RapidAPI ID | Notes |
|-------------|--------------|-------------|-------|
| 3. Liga (Germany) | `soccer_germany_liga3` | `80` | Third tier German football |

### INSERT Statement - Priority 6
```sql
INSERT INTO league_map (theodds_sport_key, league_id, league_name)
VALUES
  ('soccer_germany_liga3', 80, '3. Liga')
ON CONFLICT (theodds_sport_key) DO NOTHING;
```

**Backfill Required: PARTIAL**
- Current season only

---

## PRIORITY 7: Oceania & Other Markets (Low Priority)
**Target Date: After 10 weeks / Future consideration**
**Rationale: Limited bookmaker coverage, timezone considerations**

| League Name | Odds API Key | RapidAPI ID | Notes |
|-------------|--------------|-------------|-------|
| A-League (Australia) | `soccer_australia_aleague` | `188` | Top tier Australian football |
| Chile Primera | `soccer_chile_campeonato` | `265` | Top tier Chilean football |
| China Super League | `soccer_china_superleague` | `169` | Top tier Chinese football |

### INSERT Statement - Priority 7
```sql
INSERT INTO league_map (theodds_sport_key, league_id, league_name)
VALUES
  ('soccer_australia_aleague', 188, 'A-League'),
  ('soccer_chile_campeonato', 265, 'Primera División Chile'),
  ('soccer_china_superleague', 169, 'Super League')
ON CONFLICT (theodds_sport_key) DO NOTHING;
```

**Backfill Required: NO**
- Start with upcoming matches only
- Limited historical value

---

## Implementation Roadmap

### Phase 1: Foundation (Weeks 1-2)
- **Week 1**: Add UEFA competitions (Priority 1)
  - Run INSERT statement for Priority 1
  - Backfill current season UCL/UEL/UECL matches
  - Test odds collection for international competitions
  
- **Week 2**: Add English lower divisions (Priority 2)
  - Run INSERT statement for Priority 2
  - Backfill League One/Two current season
  - Monitor cup competition data quality

### Phase 2: Market Expansion (Weeks 3-6)
- **Week 3-4**: Add Asian & South American leagues (Priority 3)
  - Run INSERT statement for Priority 3
  - Test timezone-adjusted collection schedules
  - Validate bookmaker coverage in Asian markets
  
- **Week 5-6**: Add Northern European leagues (Priority 4)
  - Run INSERT statement for Priority 4
  - Focus on active seasons only
  - Monitor data quality metrics

### Phase 3: Consolidation (Weeks 7-10)
- **Week 7-8**: Add Southern/Eastern European leagues (Priority 5)
  - Run INSERT statement for Priority 5
  - Evaluate model performance with new data
  
- **Week 9-10**: Add German third tier (Priority 6)
  - Run INSERT statement for Priority 6
  - Complete German football pyramid

### Phase 4: Long-term (After Week 10)
- Evaluate performance across all leagues
- Add Priority 7 leagues based on user demand
- Consider seasonal leagues (MLS, Scandinavian summer leagues)

---

## Backfill Strategy

### High Priority Backfill (Do First)
1. **UEFA Champions League** - Current season group stage + knockout rounds
2. **UEFA Europa League** - Current season group stage + knockout rounds
3. **English League One/Two** - Current season (Aug 2024 - present)
4. **J League / K League** - Last 6 months

### Medium Priority Backfill (Do Second)
1. **Copa Libertadores** - Current tournament only
2. **Northern European leagues** - Current active seasons
3. **Brazil Serie B** - Current season

### Low Priority Backfill (Optional)
1. **Cup competitions** - Current rounds only
2. **Priority 5-7 leagues** - Start fresh, no backfill

---

## API Rate Limit Considerations

### The Odds API
- Current usage: 19 leagues
- After Priority 1-3: 30 leagues (+11)
- After Priority 1-6: 38 leagues (+19)
- **Recommendation**: Monitor API quota closely, may need to upgrade plan

### RapidAPI Football
- No significant change in request volume
- Backfill operations will temporarily increase usage
- **Recommendation**: Perform backfills during off-peak hours

---

## Data Quality Monitoring

### Pre-Launch Checklist (for each new league)
1. ✅ Verify odds collection from ≥8 bookmakers
2. ✅ Confirm match data availability in RapidAPI
3. ✅ Test prediction pipeline with sample matches
4. ✅ Validate league_name display formatting
5. ✅ Check timezone handling for non-European leagues

### Post-Launch Monitoring (first 2 weeks)
1. Monitor CLV Club alert quality per league
2. Track bookmaker coverage consistency
3. Evaluate model accuracy for new leagues
4. Adjust collection windows if needed (T-72h, T-48h, T-24h)

---

## Summary

**Total New Leagues: 23**
- Priority 1: 3 leagues (UEFA competitions)
- Priority 2: 4 leagues (English lower tiers + cups)
- Priority 3: 4 leagues (Asia & South America)
- Priority 4: 5 leagues (Northern Europe)
- Priority 5: 2 leagues (Southern/Eastern Europe)
- Priority 6: 1 league (German third tier)
- Priority 7: 3 leagues (Oceania & others)
- **Future: 1 league (remaining minor leagues)**

**Final Coverage: 42 leagues** (current 19 + new 23)

**Estimated Timeline: 10 weeks** for Priority 1-6 implementation

**Critical Success Factors:**
1. Start with UEFA competitions (highest ROI)
2. Monitor API quota usage closely
3. Backfill strategically (focus on high-priority leagues)
4. Validate data quality before full deployment
5. Adjust collection schedules for non-European timezones

**Next Step:** Run Priority 1 INSERT statement to add UEFA competitions immediately.
