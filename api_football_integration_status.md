# API-Football Integration - Implementation Status

## ✅ COMPLETED COMPONENTS

### 1. Database Schema ✅
- **odds_snapshots** enhanced with:
  - `source` column (TEXT, default 'theodds')
  - `vendor_fixture_id` column (BIGINT)
  - `vendor_book_id` column (TEXT)
- **Indexes** created:
  - `idx_snapshots_event_mkt_ts` (match_id, market, ts_snapshot DESC)
  - `idx_snapshots_source` (source)
- **odds_consensus** enhanced with:
  - `source_mix` column (JSONB) for multi-source tracking
- **bookmaker_xwalk** table created:
  - canonical_name (PRIMARY KEY)
  - api_football_book_id, theodds_book_id
  - desk_group (for CLV deduplication)
  - Seeded with 31 API-Football bookmakers

### 2. API-Football Client ✅
**File**: `utils/api_football_client.py`

- **ApiFootballClient** class:
  - Exponential backoff retry logic (1s, 2s, 4s, 8s delays)
  - Handles 429 (rate limit) and 503 (unavailable) errors
  - 30-second timeout with graceful degradation
  - Methods:
    - `get_bookmakers()` - Fetch all 31 bookmakers
    - `get_odds_by_fixture(fixture_id, live)` - Fetch odds for fixture
    - `get_fixture_by_api_football_id()` - Get fixture details

- **OddsMapper** class:
  - Market mapping (Match Winner/1X2 → h2h, Over/Under → totals, Handicap → spreads)
  - Outcome mapping (Home → H, Draw → D, Away → A)
  - Bookmaker canonicalization (desk_group generation)

### 3. Integration Logic ✅
**File**: `utils/api_football_integration.py`

- **BookmakerCrosswalk** class:
  - `seed_from_api_football()` - Populates bookmaker_xwalk from API
  - `get_desk_group()` - Lookup desk_group by API-Football ID
  - **Status**: 31 bookmakers seeded successfully

- **ApiFootballIngestion** class:
  - `ingest_fixture_odds()` - Core ingestion function
    - Fetches odds from API-Football
    - Maps to internal format (H/D/A outcomes)
    - Stores with source='api_football', book_id='apif:{id}'
    - Upserts with timestamp-based conflict resolution
  - `refresh_consensus_for_match()` - Multi-source consensus
    - Desk deduplication via bookmaker_xwalk
    - Source mix tracking (JSONB: {"theodds": 0.62, "api_football": 0.38})
    - Distinct book count by desk_group

### 4. Gap Fill Worker ✅
**File**: `utils/gap_fill_worker.py`

- **GapFillWorker** class:
  - `find_matches_without_odds()` - Detects gaps
    - Configurable MIN_BOOKS_THRESHOLD (default: 3)
    - Historical vs upcoming mode
    - Batch size limiting
  - `gap_fill_batch()` - Batch processing
    - Inter-fixture delay (250ms) for rate limiting
    - Error handling and stats tracking
  - `run_gap_fill_for_upcoming()` - T-72h window
  - `run_historical_backfill()` - Historical mode

- **Backfill Progress Tracking**:
  - `backfill_state` table created
  - Tracks: match_id, fixture_id, status, attempts, errors

### 5. Testing Infrastructure ✅
- **bootstrap_api_football.py** - End-to-end validation
- **test_api_football_end_to_end.py** - Known fixture testing
- **find_live_fixtures_for_test.py** - Live fixture discovery

---

## ⚠️ CRITICAL DISCOVERY: Fixture ID Gap

### The Problem
**ALL 9,846 training matches have NULL fixture_id**

```sql
SELECT COUNT(*) FROM training_matches WHERE fixture_id IS NOT NULL;
-- Result: 0
```

### Why This Matters
- API-Football requires fixture_id to fetch odds
- Gap fill worker can't operate without fixture_ids
- Historical backfill blocked until fixture matching implemented

### Current Data Status
- **9,846 matches** in training_matches (ALL with NULL fixture_id)
- **260 matches** have existing odds (but also NULL fixture_id, NULL match_date)
- **9,586 matches** completely without odds

---

## 🔧 WHAT'S NEEDED: Fixture ID Lookup System

### Option 1: Search-Based Matching (Recommended)
Implement fixture lookup by team names + date:

```python
def find_fixture_id_by_match(home_team: str, away_team: str, date: datetime, league_id: int) -> Optional[int]:
    """
    Search API-Football for fixture by team names and date.
    Returns fixture_id if found.
    """
    # /v3/fixtures?team={team_id}&date={date}
    # Match by team names and date
    # Return fixture.id
```

**Challenges**:
- Team name variations (e.g., "Manchester United" vs "Man United")
- Need API-Football team ID → name mapping
- Additional API calls (rate limiting concern)

### Option 2: Manual Fixture ID Backfill
- Export training_matches CSV
- Use external tool to match to API-Football
- Import fixture_ids back

### Option 3: Forward-Looking Only
- Accept that historical matches can't be backfilled
- Focus on NEW matches going forward
- Populate fixture_id during initial match discovery

---

## ✅ VALIDATED CAPABILITIES

### What Works (Tested)
1. ✅ Bookmaker crosswalk seeding (31 bookmakers)
2. ✅ Database schema enhancements
3. ✅ API-Football client with retry logic
4. ✅ Gap detection logic (finds 0 matches because all have NULL fixture_id)
5. ✅ Consensus calculation with multi-source support

### What's Blocked
- ❌ Historical odds backfill (no fixture_ids)
- ❌ End-to-end testing (no testable fixtures with odds)
- ❌ Gap fill worker execution (no fixture_ids to query)

---

## 📊 INTEGRATION ARCHITECTURE

### Data Flow (When Fixture IDs Available)
```
API-Football (fixture_id)
         ↓
    ApiFootballClient.get_odds_by_fixture()
         ↓
    OddsMapper (market/outcome mapping)
         ↓
    odds_snapshots (source='api_football', book_id='apif:X')
         ↓
    refresh_consensus_for_match()
         ↓
    odds_consensus (with source_mix JSONB)
```

### Multi-Source Consensus Algorithm
1. Fetch latest odds from odds_snapshots (both theodds and api_football)
2. Join with bookmaker_xwalk to get desk_group
3. Deduplicate by desk_group (e.g., Bet365 mobile/web = same desk)
4. Calculate trimmed mean consensus
5. Store source_mix: `{"theodds": N, "api_football": M}`

---

## 🚀 NEXT STEPS

### Immediate (To Unblock Backfill)
1. **Implement fixture lookup system** (Option 1 above)
   - Add `search_fixtures_by_teams_and_date()` to ApiFootballClient
   - Build team name matching logic (fuzzy match or canonical mapping)
   - Backfill fixture_ids for training_matches

2. **Test with real fixtures**
   - Find current season matches with odds
   - Validate end-to-end ingestion
   - Verify consensus calculation

### Phase 2 (After Fixture Lookup)
3. **Run pilot backfill** (100 matches)
   - Measure hit rate (expected: 20-30%)
   - Validate data quality
   - Check CLV Club compatibility

4. **Scale historical backfill** (9,586 matches)
   - Batch size: 200 matches
   - Inter-fixture delay: 250ms
   - Progress tracking via backfill_state table

5. **Enable gap-fill scheduler**
   - Post-OddsAPI cron: Fill gaps from The Odds API failures
   - T-60m cron: Pre-kickoff final sweep

---

## 📁 FILES CREATED

### Core Integration
- `utils/api_football_client.py` - API client with retry logic
- `utils/api_football_integration.py` - Ingestion + consensus
- `utils/gap_fill_worker.py` - Gap detection + backfill

### Testing
- `bootstrap_api_football.py` - End-to-end validation
- `test_api_football_end_to_end.py` - Known fixture test
- `find_live_fixtures_for_test.py` - Live fixture discovery

### Documentation
- `phase1_findings_summary.txt` - Phase 1 exploration results
- `bookmaker_mapping.json` - API-Football bookmaker list
- `api_football_integration_status.md` - This status document

---

## 🎯 SUMMARY

### ✅ What's Built
- Complete API-Football integration infrastructure
- Multi-source odds pipeline with desk deduplication
- Gap detection and backfill framework
- Bookmaker crosswalk (31 bookmakers)
- Robust retry logic and error handling

### ⚠️ What's Blocked
- Fixture ID lookup system (required for backfill)
- Historical odds backfill (9,586 matches)

### 🔑 Key Decision Point
**Choose fixture lookup strategy**:
- A) Implement automated search-based matching (2-3 days dev)
- B) Manual fixture ID backfill (1-2 days manual work)
- C) Forward-looking only (accept historical gap, focus on new matches)

**Recommendation**: Option A (automated matching) for long-term sustainability
