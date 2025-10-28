# Comprehensive Analysis: /market TBD Issue & Team Logo Coverage

## 🔍 Executive Summary

**Date:** October 28, 2025  
**Analyst:** System Analysis  

### Problems Identified:
1. **93.9% of fixtures missing team IDs** → No logo linkage in /market
2. **20.6% of fixtures have "TBD" team names** → Placeholder matches
3. **Team logo coverage is excellent (97.9%)** → But not being used

---

## 📊 Current State

### Database Statistics

```sql
Fixtures Table:
- Total fixtures: 1,075
- TBD fixtures: 222 (20.6%)
- Missing team_ids: 1,009 (93.9%)  ← ROOT CAUSE
- Upcoming fixtures: 9

Teams Table:
- Total teams: 142
- Teams with logos: 139 (97.9%)  ← Excellent!
- Teams without logos: 3 (2.1%)
- Teams with API ID: 139 (97.9%)
```

### Schema Analysis

```sql
fixtures table:
  - home_team (text, NOT NULL) ← Team name as string
  - away_team (text, NOT NULL) ← Team name as string
  - home_team_id (integer, NULL) ← Foreign key to teams table
  - away_team_id (integer, NULL) ← Foreign key to teams table

teams table:
  - team_id (integer, PRIMARY KEY)
  - name (text)
  - logo_url (text) ← 97.9% populated!
  - api_football_team_id (integer)
  - country (text)
  - slug (text)
```

---

## 🚨 Problem 1: Missing Team ID Linkage (93.9%)

### Root Cause
The `automated_collector.py` creates fixtures with only team names, NOT team IDs:

```python
INSERT INTO fixtures (
    match_id, league_id, home_team, away_team,  # ← Only names!
    kickoff_at, season, status, updated_at
) VALUES (...)
# Missing: home_team_id, away_team_id
```

### Impact on /market Endpoint

```python
# /market query tries to JOIN teams for logos:
SELECT 
    f.home_team,
    f.away_team,
    ht.logo_url as home_logo,  # ← Always NULL!
    at.logo_url as away_logo   # ← Always NULL!
FROM fixtures f
LEFT JOIN teams ht ON f.home_team_id = ht.team_id  # ← NULLs don't match
LEFT JOIN teams at ON f.away_team_id = at.team_id  # ← NULLs don't match
```

**Result:** Logos never appear, even though teams table has 97.9% coverage!

### Example Data

```sql
Fixtures:
match_id | home_team      | away_team    | home_team_id | away_team_id
---------|----------------|--------------|--------------|-------------
1234567  | Arsenal        | Chelsea      | NULL         | NULL
1234568  | Liverpool      | Man United   | NULL         | NULL

Teams:
team_id | name           | logo_url                              
--------|----------------|---------------------------------------
42      | Arsenal        | https://media.api-football.com/...  
43      | Chelsea        | https://media.api-football.com/...

# JOIN fails because home_team_id/away_team_id are NULL!
```

---

## 🚨 Problem 2: TBD Fixtures (20.6%)

### Root Cause
The Odds API returns "TBD" (To Be Determined) for:
- Playoff matches before teams are decided
- Knockout tournaments before qualifiers finish
- Cup finals before semifinal winners determined

### Example TBD Data

```sql
home_team | away_team | league_name  | kickoff_at           | home_team_id | away_team_id
----------|-----------|--------------|----------------------|--------------|-------------
TBD       | TBD       | NULL         | 2025-10-29 18:00:00  | NULL         | NULL
TBD       | TBD       | NULL         | 2025-10-29 19:45:00  | NULL         | NULL
TBD       | TBD       | NULL         | 2025-10-30 00:30:00  | NULL         | NULL
```

### TBD Enrichment Service
**Status:** EXISTS but not running automatically

File: `models/team_enrichment.py`  
Endpoint: `/admin/enrich-tbd-fixtures` (manual trigger only)

The service:
1. Finds fixtures with "TBD" team names
2. Queries API-Football to get actual team names
3. Updates fixtures with real team data

**Problem:** Not running automatically in background scheduler!

---

## ✅ Solution Architecture

### Phase 1: Fix Team ID Linkage (Immediate)

**Goal:** Link existing fixtures to teams table

```python
# Create team linkage service
def link_fixtures_to_teams():
    """
    Match fixture team names to teams table and populate team_ids
    
    Strategy:
    1. Get all fixtures with NULL team_ids
    2. For each fixture:
       - Match home_team name → teams.name (fuzzy match)
       - Match away_team name → teams.name (fuzzy match)
       - UPDATE fixtures SET home_team_id=X, away_team_id=Y
    3. Create missing teams if not found
    """
    
    # Pseudo-code:
    SELECT match_id, home_team, away_team 
    FROM fixtures 
    WHERE home_team_id IS NULL OR away_team_id IS NULL
    
    for fixture in fixtures:
        home_team_id = find_or_create_team(fixture.home_team, league_id)
        away_team_id = find_or_create_team(fixture.away_team, league_id)
        
        UPDATE fixtures 
        SET home_team_id = home_team_id, away_team_id = away_team_id
        WHERE match_id = fixture.match_id
```

**Expected Impact:**
- Before: 93.9% missing → After: <5% missing (only TBD)
- /market logos: 0% → 95%+ coverage

### Phase 2: Automate TBD Enrichment (Background Job)

**Goal:** Automatically resolve TBD fixtures

```python
# Add to background scheduler (runs every 6 hours)
async def _run_tbd_enrichment(self):
    """
    Background job: Resolve TBD fixtures using API-Football
    Runs every 6 hours to catch newly-determined playoff/knockout matches
    """
    from models.tbd_enrichment import enrich_tbd_fixtures_batch
    
    stats = enrich_tbd_fixtures_batch(
        time_window_hours=36,  # Only enrich matches <36h away
        batch_size=50
    )
    
    logger.info(f"TBD enrichment: {stats['resolved']} fixtures resolved")
```

**Expected Impact:**
- TBD fixtures: 20.6% → <2% (only very far future matches)

### Phase 3: Fill Missing Logos (Background Job)

**Goal:** Enrich teams without logos

```python
# Add to background scheduler (runs daily)
async def _run_logo_enrichment(self):
    """
    Background job: Fetch logos for teams without logo_url
    Runs once per day
    """
    from models.team_enrichment import TeamEnrichmentService
    
    enricher = TeamEnrichmentService()
    stats = enricher.enrich_missing_logos(batch_size=20)
    
    logger.info(f"Logo enrichment: {stats['enriched']} teams updated")
```

**Expected Impact:**
- Team logos: 97.9% → 99%+ (only obscure/non-existent teams missing)

### Phase 4: Update Automated Collector (Prevention)

**Goal:** Link teams when creating NEW fixtures

```python
# In automated_collector.py - BEFORE INSERT
def _create_or_get_team_id(self, team_name: str, league_id: int) -> int:
    """
    Find team in teams table or create new entry
    Returns team_id for foreign key linkage
    """
    # Search teams table by name
    team = self._find_team_by_name(team_name)
    
    if not team:
        # Create new team (logo will be enriched later by background job)
        team_id = self._create_team(
            name=team_name,
            league_id=league_id
        )
    else:
        team_id = team['team_id']
    
    return team_id

# Then in INSERT:
home_team_id = self._create_or_get_team_id(home_team, league_id)
away_team_id = self._create_or_get_team_id(away_team, league_id)

INSERT INTO fixtures (
    match_id, league_id, 
    home_team, away_team,
    home_team_id, away_team_id,  # ← Now populated!
    kickoff_at, season, status
) VALUES (...)
```

---

## 🎯 Implementation Priority

### HIGH PRIORITY (Do First)
✅ **Phase 1: Team ID Linkage** - Fixes 93.9% of missing logos  
- Create `/admin/link-fixtures-to-teams` endpoint
- Run once to backfill all existing fixtures
- Expected time: 5-10 minutes to process 1,075 fixtures

### MEDIUM PRIORITY (Do Second)  
✅ **Phase 2: TBD Enrichment Automation** - Fixes 20.6% TBD matches  
- Add to background scheduler (every 6 hours)
- Use existing TBD enrichment service
- Expected time: 1-2 hours to implement

### MEDIUM PRIORITY (Do Third)
✅ **Phase 4: Update Collector** - Prevents future issues  
- Modify automated_collector.py INSERT logic
- All new fixtures will have team_ids populated
- Expected time: 1-2 hours to implement

### LOW PRIORITY (Nice to Have)
⚪ **Phase 3: Logo Enrichment** - Fixes remaining 2.1%  
- Add to background scheduler (daily)
- Only needed for 3 teams currently
- Expected time: 30 minutes to implement

---

## 📈 Expected Results

### Before Fix:
```
/market endpoint:
- Logos shown: 0/9 matches (0%)
- TBD matches: 9/9 (100%)
- Team linkage: 0/9 matches (0%)
```

### After Phase 1 (Team ID Linkage):
```
/market endpoint:
- Logos shown: 8.5/9 matches (95%)  ← HUGE IMPROVEMENT
- TBD matches: 9/9 (100%)           ← Still TBD, but linked
- Team linkage: 9/9 matches (100%)
```

### After Phase 2 (TBD Automation):
```
/market endpoint:
- Logos shown: 9/9 matches (100%)
- TBD matches: 0/9 (0%)  ← RESOLVED
- Team linkage: 9/9 matches (100%)
```

---

## 🛠️ Existing Services (Can Be Leveraged)

### TeamEnrichmentService
**File:** `models/team_enrichment.py`  
**Status:** ✅ Operational  
**Features:**
- Fuzzy name matching (handles "1. FC Bayern" → "Bayern Munich")
- Multi-pass search strategy (exact → normalized → fuzzy)
- API-Football integration for logos
- 97.9% success rate

### TBD Enrichment Service
**Endpoint:** `/admin/enrich-tbd-fixtures`  
**Status:** ✅ Operational (manual only)  
**Features:**
- Resolves TBD → actual team names
- Uses API-Football fixture data
- Timeboxed (only enriches matches <36h away)
- Needs automation

---

## 🔧 Quick Fix Commands

### Immediate Testing (Check Current State)
```bash
# 1. Check fixtures missing team IDs
curl -s http://localhost:8000/admin/stats/fixtures | jq '.missing_team_ids'

# 2. Check TBD count
curl -s -H "Authorization: Bearer betgenius_secure_key_2024" \
  "http://localhost:8000/market" | jq '[.[] | select(.home_team.name | contains("TBD"))] | length'

# 3. Check team logo coverage
curl -s -H "Authorization: Bearer betgenius_secure_key_2024" \
  "http://localhost:8000/teams?has_logo=false"
```

### Manual Enrichment (Temporary Fix)
```bash
# Enrich TBD fixtures (manual trigger)
curl -X POST http://localhost:8000/admin/enrich-tbd-fixtures \
  -H "Authorization: Bearer betgenius_secure_key_2024"

# Enrich team logos (manual trigger)
curl -X POST http://localhost:8000/admin/enrich-team-logos \
  -H "Authorization: Bearer betgenius_secure_key_2024"
```

---

## 📝 Recommended Next Steps

1. **Create Team Linkage Service** (1-2 hours)
   - Build fuzzy matcher for team names
   - Backfill existing 1,075 fixtures
   - Add to /admin endpoints

2. **Automate TBD Enrichment** (1 hour)
   - Add to background scheduler
   - Run every 6 hours
   - Monitor success rate

3. **Update Automated Collector** (1-2 hours)
   - Link teams on fixture creation
   - Prevent future missing team_ids

4. **Monitor & Validate** (ongoing)
   - Track logo coverage in /market
   - Monitor TBD resolution rate
   - Alert if linkage drops below 95%

---

**Status:** ✅ Analysis Complete  
**Impact:** HIGH - Fixes 93.9% of logo issues  
**Effort:** MEDIUM - 4-6 hours total implementation
