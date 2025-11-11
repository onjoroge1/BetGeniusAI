# Team Logo Enrichment Strategy

## Executive Summary

**Current Status:**
- ✅ **337 teams (56.4%)** have logos
- ❌ **260 teams (43.6%)** need enrichment
- 🎯 **100% logo coverage** for teams with API-Football IDs

## Key Discovery: API-Sports.io Logo URL Pattern

Team logos follow a predictable URL pattern:
```
https://media.api-sports.io/football/teams/{team_id}.png
```

**Example:**
- Manchester United (ID: 33): `https://media.api-sports.io/football/teams/33.png`
- Arsenal (ID: 42): `https://media.api-sports.io/football/teams/42.png`

## Current System Architecture

### 1. Teams Table Schema
```sql
CREATE TABLE teams (
    team_id         SERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    api_football_team_id  INTEGER,      -- API-Football ID
    logo_url        TEXT,                -- Constructed or fetched URL
    country         TEXT,
    slug            TEXT,
    logo_last_synced_at   TIMESTAMP,
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);
```

### 2. Logo Sources

#### Primary Source: API-Football Enrichment
**File:** `models/team_enrichment.py`

The `TeamEnrichmentService`:
1. Searches for teams by name using fuzzy matching
2. Fetches team metadata (ID, name, logo, country)
3. **NEW:** Constructs logo URL from team ID as fallback
4. Stores in `teams` table

**Multi-Pass Search Strategy:**
- Pass 1: Exact match with league filter
- Pass 2: Normalized name with league filter  
- Pass 3: Normalized name without league filter
- Pass 4: Fuzzy substring matching (0.75+ threshold)

#### Fallback: Logo URL Constructor
**File:** `utils/logo_constructor.py`

Simple utility that constructs logo URLs directly:
```python
def construct_logo_url(api_football_team_id: int) -> str:
    return f"https://media.api-sports.io/football/teams/{api_football_team_id}.png"
```

**Use Cases:**
- Safety net for teams with API ID but no logo (currently 0)
- Faster logo construction without API calls
- Reliable fallback when API response lacks logo

### 3. Data Flow

```
Fixtures Table (team names)
        ↓
TeamEnrichmentService.enrich_teams_from_fixtures()
        ↓
API-Football Search (/teams?search=name)
        ↓
Extract: {id, name, logo, country}
        ↓
Construct logo URL (if API missing)
        ↓
Upsert to teams table
        ↓
Link fixtures (home_team_id, away_team_id)
        ↓
/market API (join fixtures ↔ teams for logos)
```

## Improvements Made (Nov 2025)

### 1. Logo URL Constructor (`utils/logo_constructor.py`)
- **Purpose:** Construct logos directly from team IDs
- **Benefit:** 100% logo coverage for enriched teams
- **Usage:**
  ```python
  from utils.logo_constructor import construct_logo_url
  logo_url = construct_logo_url(33)  # Manchester United
  ```

### 2. Enhanced Enrichment Service
**Changes to `models/team_enrichment.py`:**
```python
# OLD: Relied only on API response
logo_url = team.get('logo')

# NEW: Construct from ID as fallback
logo_url = team.get('logo')
if not logo_url and team_id:
    logo_url = f"https://media.api-sports.io/football/teams/{team_id}.png"
```

**Benefits:**
- Guaranteed logo URL when we have team ID
- Works even if API response omits logo field
- More resilient to API changes

### 3. Enrichment Script (`scripts/enrich_team_logos.py`)
**Features:**
- Status dashboard showing coverage
- Batch enrichment with rate limiting
- Backfill safety net
- Automatic fixture linking

**Usage:**
```bash
# Show current status
python scripts/enrich_team_logos.py --status

# Enrich 50 teams
python scripts/enrich_team_logos.py --limit 50

# Force re-fetch all teams
python scripts/enrich_team_logos.py --limit 100 --force
```

## Teams Needing Enrichment

### Sample (10 of 260):
1. Arsenal
2. Atletico-MG
3. Bodo/Glimt
4. Brighton
5. Chapecoense-sc
6. Chelsea
7. Crystal Palace
8. Estudiantes L.P.
9. FC Andorra
10. FC Copenhagen

### Why They're Missing Logos

These teams exist in `fixtures` table but not in `teams` table with API IDs:
- Added from API-Football fixtures data
- Names need fuzzy matching to API-Football teams database
- Requires API search (1 request/team, rate limited)

## How to Enrich Missing Logos

### Option 1: Use Enrichment Script (Recommended)
```bash
# Step 1: Check current status
python scripts/enrich_team_logos.py --status

# Step 2: Enrich 50 teams (takes ~50 seconds due to rate limiting)
python scripts/enrich_team_logos.py --limit 50

# Step 3: Verify improvement
python scripts/enrich_team_logos.py --status
```

### Option 2: Manual Python
```python
from models.team_enrichment import get_team_enrichment_service

service = get_team_enrichment_service()

# Enrich 50 teams
result = service.enrich_teams_from_fixtures(limit=50)
print(f"Enriched: {result['teams_enriched']}")

# Link fixtures to teams
link_result = service.link_fixtures_to_teams()
print(f"Linked: {link_result['fixtures_linked']} fixtures")
```

### Option 3: Automated Scheduler (Future Enhancement)
Could add to `utils/scheduler.py`:
```python
schedule.every().day.at("02:00").do(enrich_daily_logos)

def enrich_daily_logos():
    service = get_team_enrichment_service()
    service.enrich_teams_from_fixtures(limit=50)  # 50 per day
```

## Rate Limiting & API Costs

### Current Implementation
- **Rate limit:** 1 request/second (in `team_enrichment.py:331`)
- **Batch size:** 50 teams (recommended)
- **Time:** ~50 seconds per batch

### API-Football Quota
- Uses `RAPIDAPI_KEY` environment variable
- Endpoint: `/teams?search={name}`
- Cost: Depends on RapidAPI plan

### Optimization Strategies

1. **League filtering:** Reduce false positives
   ```python
   service.search_team_by_name("Arsenal", league_id=39)  # Premier League
   ```

2. **Batch scheduling:** Enrich during off-peak hours
   ```bash
   crontab -e
   0 2 * * * cd /path/to/project && python scripts/enrich_team_logos.py --limit 50
   ```

3. **Fuzzy match threshold:** Adjust for accuracy vs coverage
   ```python
   # In team_enrichment.py line 159
   if best['score'] < 0.75:  # Lower = more lenient matching
   ```

## Verification & Monitoring

### Check Logo Coverage
```sql
SELECT 
    COUNT(*) as total_teams,
    COUNT(logo_url) as teams_with_logos,
    ROUND(100.0 * COUNT(logo_url) / COUNT(*), 1) as coverage_pct
FROM teams;
```

### Find Teams Without Logos
```sql
SELECT name, country, api_football_team_id
FROM teams
WHERE logo_url IS NULL
  AND name NOT IN ('TBD', '')
ORDER BY name
LIMIT 20;
```

### Verify Logo URLs Work
```bash
# Test a sample logo URL
curl -I https://media.api-sports.io/football/teams/33.png
# Should return: HTTP/1.1 200 OK
```

## Troubleshooting

### Issue: Logo URL Returns 404
**Cause:** Invalid team ID or team doesn't exist in API-Sports
**Solution:**
```python
# Re-search for team
service = get_team_enrichment_service()
team_data = service.search_team_by_name("Team Name", league_id=39)
if team_data:
    print(f"Correct ID: {team_data['api_football_team_id']}")
```

### Issue: Enrichment Finds No Matches
**Cause:** Team name mismatch or threshold too strict
**Solutions:**
1. Lower fuzzy match threshold (line 159 in `team_enrichment.py`)
2. Add manual team name mapping
3. Try different search variations

### Issue: Rate Limit Exceeded
**Cause:** Too many API requests
**Solution:**
```python
# Increase delay between requests
# In team_enrichment.py line 331:
time.sleep(2)  # Changed from 1 second to 2 seconds
```

## Future Enhancements

### 1. Manual Team Mappings
For teams that can't be auto-matched:
```python
MANUAL_MAPPINGS = {
    'Chapecoense-sc': {'api_id': 146, 'name': 'Chapecoense'},
    'Estudiantes L.P.': {'api_id': 451, 'name': 'Estudiantes de La Plata'}
}
```

### 2. League Logo Support
Extend to fetch league logos:
```sql
ALTER TABLE leagues ADD COLUMN logo_url TEXT;
```

### 3. Logo CDN Caching
Cache logos locally or use CDN:
```python
# Download and store in attached_assets/team_logos/
# Serve via static file endpoint
```

### 4. Fallback Logo Generator
Use team initials to generate placeholder logos:
```python
def generate_placeholder_logo(team_name: str) -> str:
    # Use service like UI Avatars or Dicebear
    initials = ''.join([word[0] for word in team_name.split()[:2]])
    return f"https://ui-avatars.com/api/?name={initials}&size=128"
```

## Key Takeaways

1. **Logo URL Pattern Works:** `https://media.api-sports.io/football/teams/{id}.png` is reliable
2. **100% Coverage Possible:** When we have API ID, we can always construct logo URL
3. **260 Teams Need Enrichment:** Run enrichment script to improve coverage
4. **Rate Limiting Required:** 1 request/sec to avoid API throttling
5. **Fuzzy Matching Works:** 0.75+ threshold provides good accuracy

## Related Files

- **Enrichment Service:** `models/team_enrichment.py`
- **Logo Constructor:** `utils/logo_constructor.py`
- **Enrichment Script:** `scripts/enrich_team_logos.py`
- **Market API:** `main.py` (lines 6000-6700 - joins fixtures ↔ teams for logos)
- **Teams Endpoint:** `main.py:/teams` (API for frontend team selection)

## Commands Reference

```bash
# Show status
python scripts/enrich_team_logos.py --status

# Enrich 50 teams
python scripts/enrich_team_logos.py --limit 50

# Force re-fetch
python scripts/enrich_team_logos.py --limit 100 --force

# Check database directly
psql $DATABASE_URL -c "SELECT COUNT(*) - COUNT(logo_url) as missing FROM teams;"

# Test logo URL
curl -I https://media.api-sports.io/football/teams/33.png
```
