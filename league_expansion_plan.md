# BetGenius AI - League Expansion Plan

## Current State (22 Leagues - September 30, 2025)

### Tier 1 European (6 leagues)
- Premier League, La Liga, Serie A, Bundesliga, Ligue 1, Eredivisie

### Tier 2 European (5 leagues)
- Championship, LaLiga2, Serie B, 2. Bundesliga, Ligue 2

### UEFA Competitions (3 leagues) ✅ ADDED SEPT 30
- Champions League (269 matches backfilled), Europa League (256 matches), Conference League (46 matches)

### Americas (4 leagues)
- Brasileirão, Liga MX, MLS, Liga Profesional Argentina

### Other European (4 leagues)
- Primeira Liga, Scottish Premiership, Jupiler Pro League, Süper Lig

---

## PRIORITY 2: English Lower Divisions
**Target Date: Within 2 weeks**

| League Name | Odds API Key | RapidAPI ID |
|-------------|--------------|-------------|
| English League One | `soccer_england_league1` | `45` |
| English League Two | `soccer_england_league2` | `46` |
| FA Cup | `soccer_fa_cup` | `48` |
| EFL Cup | `soccer_england_efl_cup` | `47` |

### INSERT Statement
```sql
INSERT INTO league_map (theodds_sport_key, league_id, league_name)
VALUES
  ('soccer_england_league1', 45, 'League One'),
  ('soccer_england_league2', 46, 'League Two'),
  ('soccer_fa_cup', 48, 'FA Cup'),
  ('soccer_england_efl_cup', 47, 'EFL Cup')
ON CONFLICT (theodds_sport_key) DO NOTHING;
```

---

## PRIORITY 3: Asian & South American Markets
**Target Date: Within 3-4 weeks**

| League Name | Odds API Key | RapidAPI ID |
|-------------|--------------|-------------|
| J League (Japan) | `soccer_japan_j_league` | `98` |
| K League 1 (Korea) | `soccer_korea_kleague1` | `292` |
| Brazil Serie B | `soccer_brazil_serie_b` | `72` |
| Copa Libertadores | `soccer_conmebol_copa_libertadores` | `13` |

### INSERT Statement
```sql
INSERT INTO league_map (theodds_sport_key, league_id, league_name)
VALUES
  ('soccer_japan_j_league', 98, 'J1 League'),
  ('soccer_korea_kleague1', 292, 'K League 1'),
  ('soccer_brazil_serie_b', 72, 'Brasileirão Série B'),
  ('soccer_conmebol_copa_libertadores', 13, 'Copa Libertadores')
ON CONFLICT (theodds_sport_key) DO NOTHING;
```

---

## PRIORITY 4: Northern European Markets
**Target Date: Within 5-6 weeks**

| League Name | Odds API Key | RapidAPI ID |
|-------------|--------------|-------------|
| Denmark Superliga | `soccer_denmark_superliga` | `119` |
| Norway Eliteserien | `soccer_norway_eliteserien` | `103` |
| Sweden Allsvenskan | `soccer_sweden_allsvenskan` | `113` |
| Austria Bundesliga | `soccer_austria_bundesliga` | `218` |
| Switzerland Super League | `soccer_switzerland_superleague` | `207` |

### INSERT Statement
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

---

## PRIORITY 5-7: Additional Markets
See original plan for Greece, Poland, Germany 3. Liga, and other markets.

---

## Backfill Recommendations

### High Priority (Do First)
1. **English League One/Two** - Current season (Aug 2024 - present)
2. **J League / K League** - Last 6 months
3. **Copa Libertadores** - Current tournament only

### Medium Priority (Do Second)
1. **Northern European leagues** - Current active seasons
2. **Brazil Serie B** - Current season

### Low Priority (Optional)
1. **Cup competitions** - Current rounds only
2. **Priority 5-7 leagues** - Start fresh, no backfill

---

## Summary

**Total Potential: 42 leagues** (current 22 + planned 20)

**Next Action:** Run Priority 2 INSERT statement to add English lower divisions
