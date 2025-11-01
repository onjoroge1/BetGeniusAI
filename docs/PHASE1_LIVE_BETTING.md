# Phase 1: Live Betting Intelligence - Technical Documentation

## Overview
Phase 1 introduces comprehensive live betting capabilities including real-time match statistics, event tracking, odds velocity monitoring, and intelligent AI-powered analysis. The system automatically collects live data for ongoing matches and triggers AI insights based on time intervals, odds movements, or significant match events.

## Features Implemented

### 1. Live Data Collection
**Status:** ✅ Fully operational

Real-time data collection from API-Football for all live matches:
- **Match Status:** Current score, minute, period (1st Half, 2nd Half, HT, etc.)
- **Statistics:** Possession%, shots (total/on-target), corners, yellow/red cards
- **Events Timeline:** Goals, cards, substitutions with player names and timestamps
- **Collection Frequency:** Every 60 seconds via automated scheduler

**Database Tables:**
- `live_match_stats` - Current match statistics snapshot
- `match_events` - Chronological event timeline (goals, cards, subs)

**File:** `models/live_data_collector.py`

### 2. Odds Velocity Calculator
**Status:** ✅ Fully operational

Tracks market movements using existing `odds_snapshots` data:
- **Velocity Metrics:** Home/Draw/Away probability changes over time
- **Market Sentiment:** "backing_home", "backing_away", "backing_draw", "mixed"
- **Significant Movement Detection:** Flags >5% odds changes
- **Lookback Windows:** 5, 15, 30 minute windows supported

**Algorithm:**
1. Fetches latest + historical odds snapshots (configurable lookback)
2. Calculates no-vig probabilities from odds
3. Computes velocity (change per minute) for each outcome
4. Determines market sentiment based on largest movement

**File:** `models/odds_velocity.py`

### 3. Intelligent AI Analysis Triggers
**Status:** ✅ Fully operational

OpenAI GPT-4o analysis triggered by:
- **Time-based:** Every 4 minutes during live matches
- **Odds movement:** >5% change in any outcome probability
- **Match events:** Goals, red cards within last 5 minutes

**Analysis Output (JSON):**
```json
{
  "momentum_assessment": "brief description of game flow",
  "key_observations": ["observation 1", "observation 2", "observation 3"],
  "betting_angles": [
    {"market": "market_name", "reasoning": "why", "confidence": "high/medium/low"}
  ],
  "value_shift": "which outcome is gaining/losing value"
}
```

**Database Table:**
- `live_ai_analysis` - Cached AI insights with triggers, minute, statistics snapshot

**File:** `models/live_ai_analyzer.py`

### 4. Enhanced /market API Endpoint
**Status:** ✅ Fully operational

Automatic live data enrichment for ongoing matches:

**New Response Fields (when status="LIVE"):**
```json
{
  "match_id": 123,
  "status": "LIVE",
  "live_data": {
    "current_score": {"home": 1, "away": 0},
    "minute": 67,
    "period": "2nd Half",
    "statistics": {
      "possession": {"home": 58, "away": 42},
      "shots_total": {"home": 15, "away": 8},
      "shots_on_target": {"home": 6, "away": 3},
      "corners": {"home": 7, "away": 4},
      "yellow_cards": {"home": 2, "away": 1},
      "red_cards": {"home": 0, "away": 0}
    }
  },
  "live_events": [
    {"minute": 65, "type": "goal", "team": "home", "player": "John Doe", "detail": null},
    {"minute": 54, "type": "yellow_card", "team": "away", "player": "Jane Smith", "detail": null}
  ],
  "ai_analysis": {
    "minute": 65,
    "trigger": "event_goal_home_65min",
    "momentum": "Home team dominant after recent goal",
    "observations": ["Controlling possession", "Clinical finishing"],
    "betting_angles": [
      {"market": "Over 2.5 Goals", "reasoning": "Home team pressing", "confidence": "high"}
    ],
    "generated_at": "2025-11-01T15:40:00Z"
  },
  "odds": {
    "books": [...],
    "novig_current": {...},
    "velocity": {
      "market_sentiment": "backing_home",
      "significant_movement": true,
      "velocities": {"home": 0.08, "draw": -0.03, "away": -0.05},
      "lookback_minutes": 15
    }
  }
}
```

**Performance:**
- No impact on scheduled matches (fields only added when status="LIVE")
- Live data queries optimized with indexes
- AI analysis pre-cached (no generation delay)

### 5. Automated Scheduler Integration
**Status:** ✅ Fully operational

Two new background jobs running every 60 seconds:

**Job 1: Live Data Collection**
- Identifies live matches (kickoff_at <= NOW, kickoff_at > NOW - 2 hours)
- Fetches latest data from API-Football
- Updates `live_match_stats` and `match_events` tables
- **File:** `utils/scheduler.py` → `_run_live_data_collection()`

**Job 2: AI Analysis Triggers**
- Checks all live matches for trigger conditions
- Generates OpenAI analysis when criteria met
- Stores insights in `live_ai_analysis` table
- **File:** `utils/scheduler.py` → `_run_live_ai_analysis()`

**Scheduler Logs:**
```
INFO: 🔴 Live data collection: Starting...
INFO: 🤖 AI analysis: Checking live matches...
INFO: ✅ live_data: completed in 2.1s
INFO: ✅ ai_analysis: completed in 3.5s
```

## API Usage

### Example: Get Live Match Data
```bash
curl -X GET "https://your-domain.repl.co/market?league_id=39&include_v2=false" \
  -H "x-api-key: your_api_key"
```

**Response for Live Match:**
```json
{
  "matches": [
    {
      "match_id": 12345,
      "status": "LIVE",
      "home": {"name": "Arsenal", "team_id": 42, "logo_url": "..."},
      "away": {"name": "Chelsea", "team_id": 49, "logo_url": "..."},
      "live_data": {
        "current_score": {"home": 2, "away": 1},
        "minute": 78,
        "period": "2nd Half",
        "statistics": {...}
      },
      "live_events": [...],
      "ai_analysis": {...},
      "odds": {
        "velocity": {
          "market_sentiment": "backing_home",
          "significant_movement": true
        }
      }
    }
  ]
}
```

## Database Schema

### live_match_stats
```sql
CREATE TABLE live_match_stats (
    id SERIAL PRIMARY KEY,
    match_id INTEGER REFERENCES fixtures(match_id),
    minute INTEGER,
    period VARCHAR(20),
    home_score INTEGER,
    away_score INTEGER,
    home_possession INTEGER,
    away_possession INTEGER,
    home_shots_total INTEGER,
    away_shots_total INTEGER,
    home_shots_on_target INTEGER,
    away_shots_on_target INTEGER,
    home_corners INTEGER,
    away_corners INTEGER,
    home_yellow_cards INTEGER,
    away_yellow_cards INTEGER,
    home_red_cards INTEGER,
    away_red_cards INTEGER,
    timestamp TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_live_stats_match_ts ON live_match_stats(match_id, timestamp DESC);
```

### match_events
```sql
CREATE TABLE match_events (
    id SERIAL PRIMARY KEY,
    match_id INTEGER REFERENCES fixtures(match_id),
    minute INTEGER,
    event_type VARCHAR(50),
    team VARCHAR(10),
    player_name VARCHAR(255),
    detail VARCHAR(255),
    timestamp TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_events_match_ts ON match_events(match_id, timestamp DESC);
CREATE INDEX idx_events_type ON match_events(event_type);
```

### live_ai_analysis
```sql
CREATE TABLE live_ai_analysis (
    id SERIAL PRIMARY KEY,
    match_id INTEGER REFERENCES fixtures(match_id),
    minute INTEGER,
    analysis_type VARCHAR(50),
    trigger_reason VARCHAR(100),
    home_score INTEGER,
    away_score INTEGER,
    odds_snapshot JSONB,
    statistics_snapshot JSONB,
    ai_insights TEXT,
    key_observations JSONB,
    betting_angles JSONB,
    momentum_assessment TEXT,
    tokens_used INTEGER,
    generated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_ai_analysis_match_ts ON live_ai_analysis(match_id, generated_at DESC);
```

## Configuration

### AI Analysis Triggers
Edit `models/live_ai_analyzer.py`:
```python
self.time_interval_minutes = 4  # Time-based trigger (every N minutes)
self.odds_movement_threshold = 5  # Odds change % to trigger analysis
```

### Live Match Detection
Edit `models/live_data_collector.py`:
```python
# Matches are considered live if:
# kickoff_at <= NOW AND kickoff_at > NOW - INTERVAL '2 hours'
```

## Cost Management

### API Usage
- **API-Football Calls:** ~1 request per live match per minute
- **10 live matches:** ~600 requests/hour = 14,400/day
- **Well within limit:** 75,000 requests/day

### OpenAI Tokens
- **Trigger frequency:** Every 4 minutes (time-based) + event/odds triggers
- **Avg tokens per analysis:** ~400-500 tokens
- **10 live matches:** ~15 analyses/match/90min = 150 total = 75k tokens
- **Cost:** ~$0.15 per match day with 10 concurrent matches

### Optimization Tips
1. Increase `time_interval_minutes` to reduce AI calls
2. Raise `odds_movement_threshold` to reduce movement triggers
3. Disable event triggers for certain event types
4. Use `include_v2=false` on /market endpoint for faster responses

## Testing

### Manual Testing
1. **Verify live data collection:**
   ```sql
   SELECT * FROM live_match_stats ORDER BY timestamp DESC LIMIT 10;
   SELECT * FROM match_events ORDER BY timestamp DESC LIMIT 10;
   ```

2. **Check AI analysis triggers:**
   ```sql
   SELECT match_id, minute, trigger_reason, momentum_assessment, generated_at 
   FROM live_ai_analysis ORDER BY generated_at DESC LIMIT 10;
   ```

3. **Test /market endpoint:**
   ```bash
   curl -X GET "http://localhost:8000/market?include_v2=false" \
     -H "x-api-key: test_key"
   ```

### Scheduler Logs
Monitor scheduler output:
```bash
tail -f /tmp/logs/BetGenius_AI_Server_*.log | grep -E "(Live data|AI analysis)"
```

## Future Enhancements (Phase 2)

Potential improvements for next iteration:
1. **Live betting markets:** Generate live over/under, BTTS predictions
2. **Momentum scoring:** Quantitative momentum metric (0-100)
3. **Expected goals (xG):** Real-time xG calculation from shot data
4. **Cash-out recommendations:** AI-driven cash-out timing suggestions
5. **WebSocket streaming:** Real-time updates to frontend via WebSockets
6. **Historical pattern matching:** Compare live stats to historical comebacks
7. **Multi-language AI:** Localized analysis in user's language

## Troubleshooting

### Issue: No live data appearing
**Solution:**
```sql
-- Check if matches are detected as live
SELECT match_id, home_team, away_team, kickoff_at, 
       NOW() - kickoff_at AS time_since_kickoff
FROM fixtures
WHERE kickoff_at <= NOW() 
  AND kickoff_at > NOW() - INTERVAL '2 hours'
  AND status = 'scheduled';
```

### Issue: AI analysis not triggering
**Solution:**
```python
# Test trigger logic manually
from models.live_ai_analyzer import LiveAIAnalyzer
import os

analyzer = LiveAIAnalyzer(os.environ.get('DATABASE_URL'))
should_trigger, reason = analyzer.should_trigger_analysis(match_id=12345)
print(f"Should trigger: {should_trigger}, Reason: {reason}")
```

### Issue: Scheduler jobs not running
**Solution:**
Check scheduler logs and verify imports:
```bash
grep -E "(live_data|ai_analysis)" /tmp/logs/*.log
```

## Success Criteria ✅

Phase 1 is complete when:
- [x] Live match statistics collected and stored
- [x] Match events timeline captured
- [x] Odds velocity calculated from snapshots
- [x] AI analysis triggers on time/odds/events
- [x] /market API returns live data fields
- [x] Scheduler runs jobs every 60 seconds
- [x] Documentation complete
- [x] End-to-end testing passed

---

**Phase 1 Status:** ✅ COMPLETE
**Last Updated:** November 1, 2025
**Version:** 1.0
