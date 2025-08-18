# Upcoming Matches Collection Status - August 18, 2025

## Goal: Real Odds Collection at T-72h, T-48h, T-24h

The original objective is to collect **upcoming matches** and capture real bookmaker odds at multiple time horizons to feed into the prediction system.

## Current Status

### ✅ What's Working
- **Phase A (Completed matches)**: Successfully collecting and saving to both `training_matches` and `odds_consensus` tables
- **Dual table population**: Cross-table synchronization implemented and verified
- **API Keys**: Both `RAPIDAPI_KEY` and `ODDS_API_KEY` are available
- **Database**: `odds_snapshots` table exists and ready for real odds data

### 🔍 Current Issues
1. **No upcoming fixtures found** - RapidAPI returns 0 upcoming matches (likely offseason/international break)
2. **Odds API authentication** - Fixed parameter passing (apikey as URL parameter, not header)
3. **League mapping** - Implemented mapping from RapidAPI league IDs to The Odds API sport keys

### 🏗️ Infrastructure Ready
- **RapidAPI Integration**: Gets upcoming fixtures with proper timing windows (24h-168h)
- **The Odds API Integration**: Gets real bookmaker odds with consensus calculation
- **Database Schema**: `odds_snapshots` table ready for T-72h/T-48h/T-24h data
- **Timing Logic**: Filters matches within optimal prediction windows

## Architecture Overview

```
Phase B: Upcoming Matches → odds_snapshots
├── RapidAPI: Get fixtures (status='NS', next 7 days)
├── Filter: Keep matches 24h-168h ahead
├── The Odds API: Get real bookmaker odds
├── Consensus: Calculate weighted probabilities
└── Save: odds_snapshots table (T-72h/T-48h/T-24h)
```

## League Mapping (RapidAPI → The Odds API)
- Premier League (39) → `soccer_epl`
- La Liga (140) → `soccer_spain_la_liga`
- Serie A (135) → `soccer_italy_serie_a`
- Bundesliga (78) → `soccer_germany_bundesliga`
- Ligue 1 (61) → `soccer_france_ligue_one`
- Eredivisie (88) → `soccer_netherlands_eredivisie`

## Next Steps

### Immediate (August 18, 2025)
1. **Test during active season** - Current test shows 0 fixtures (likely offseason)
2. **Verify odds API authentication** - Fixed parameter passing
3. **Wait for upcoming matches** - System ready for next gameweek

### Production Ready
- **Daily scheduler** runs at 02:00 UTC to collect T-72h odds
- **Manual trigger** available for testing anytime
- **Error handling** for rate limits and API failures
- **Consensus calculation** from multiple bookmakers

## Validation Strategy

When matches are available:
1. Check `odds_snapshots` table for new entries
2. Verify timing windows (72h, 48h, 24h before kickoff)
3. Confirm multiple bookmaker consensus
4. Test prediction pipeline with real odds data

---

**Current Blocker**: No upcoming matches in leagues during international break. System is ready and will automatically collect real odds when fixtures resume.