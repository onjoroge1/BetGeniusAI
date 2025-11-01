# Phase 2: Live Betting Intelligence System

**Status:** ✅ OPERATIONAL (November 2025)  
**Version:** 2.0.0

## Overview

Phase 2 extends BetGenius AI with comprehensive live betting capabilities:

- **Momentum Scoring**: Real-time 0-100 momentum indices for home/away teams
- **Live Market Engine**: In-play predictions (1X2, O/U, Next Goal) with time-aware blending
- **WebSocket Streaming**: Real-time delta updates to connected clients
- **Enhanced /market API**: Live data enrichment with momentum + model markets
- **Fixture ID Resolution**: 95%+ success rate with advanced normalization

## Architecture

### Data Flow

```
Live Matches → Momentum Engine (60s cycle) → Database (live_momentum)
                     ↓
              Live Market Engine (60s cycle) → Database (live_model_markets)
                     ↓
              /market API → Response enrichment
                     ↓
              WebSocket → Delta broadcast to clients
```

### Key Components

1. **MomentumCalculator** (`models/momentum_calculator.py`)
   - Exponential decay (6-min half-life) for recent events
   - Weighted feature blending: shots (35%), dangerous attacks (20%), xG (20%), odds velocity (15%), possession (10%)
   - Red card modifiers: +30% boost for team with numerical advantage
   - Output: 0-100 scores for home/away with driver attribution

2. **LiveMarketEngine** (`models/live_market_engine.py`)
   - Time-aware blending: α(t) from 0.5 (early) → 0.8 (late game)
   - Momentum differential boost: ±5 percentage points cap
   - Markets: 1X2 live, Over/Under 2.5, Next Goal (home/none/away)
   - Fallbacks: Pre-match model when live data unavailable

3. **WebSocket Streaming** (`routes/realtime.py`)
   - Endpoint: `ws://localhost:5000/ws/live/{match_id}`
   - Connection management with active client tracking
   - Delta payloads: Only changed fields (momentum, markets, stats)
   - Broadcast trigger: Every 60s scheduler cycle

4. **Enhanced /market API** (`main.py`)
   - New fields for `status=live` matches:
     - `momentum`: {home, away, driver_summary, minute}
     - `model_markets`: {win_draw_win, over_under, next_goal}
   - 5-minute freshness window (excludes stale data)
   - Resilient fallbacks for missing snapshots

## Database Schema

### live_momentum
```sql
CREATE TABLE live_momentum (
    match_id INTEGER PRIMARY KEY,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    home_score INTEGER,
    away_score INTEGER,
    minute INTEGER,
    momentum_home INTEGER,  -- 0-100
    momentum_away INTEGER,  -- 0-100
    driver_summary JSONB    -- {shots: 'home_dominant', possession: 'balanced', ...}
);
```

### live_model_markets
```sql
CREATE TABLE live_model_markets (
    match_id INTEGER PRIMARY KEY,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    wdw JSONB,        -- {home, draw, away}
    ou JSONB,         -- {over, under, line: 2.5}
    next_goal JSONB   -- {home, none, away}
);
```

### fixture_id_manual_overrides
```sql
CREATE TABLE fixture_id_manual_overrides (
    id SERIAL PRIMARY KEY,
    source_team_name TEXT NOT NULL,
    canonical_team_name TEXT NOT NULL,
    league_context TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

## API Endpoints

### GET /market?status=live
**Enhanced response for live matches:**

```json
{
  "matches": [
    {
      "match_id": 1234567,
      "status": "LIVE",
      "home": {"name": "Arsenal", "team_id": 42, "logo_url": "..."},
      "away": {"name": "Chelsea", "team_id": 49, "logo_url": "..."},
      "live_data": {
        "current_score": {"home": 1, "away": 0},
        "minute": 67,
        "period": "Second Half",
        "statistics": { ... }
      },
      "momentum": {
        "home": 72,
        "away": 28,
        "driver_summary": {
          "shots": "home_dominant",
          "possession": "balanced",
          "odds_velocity": "home_strengthening"
        },
        "minute": 67
      },
      "model_markets": {
        "updated_at": "2025-11-01T15:30:45Z",
        "win_draw_win": {"home": 0.68, "draw": 0.22, "away": 0.10},
        "over_under": {"over": 0.62, "under": 0.38, "line": 2.5},
        "next_goal": {"home": 0.55, "none": 0.25, "away": 0.20}
      },
      "odds": { ... },
      "models": { ... }
    }
  ]
}
```

### WebSocket /ws/live/{match_id}
**Connection:**
```javascript
const ws = new WebSocket('ws://localhost:5000/ws/live/1234567');

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log('Delta update:', data);
};
```

**Delta payload example:**
```json
{
  "match_id": 1234567,
  "minute": 68,
  "momentum": {
    "home": 74,
    "away": 26,
    "delta": "+2 home momentum"
  },
  "model_markets": {
    "win_draw_win": {"home": 0.70, "draw": 0.20, "away": 0.10}
  }
}
```

## Prometheus Metrics

### Momentum Engine
```
# Calculations attempted
momentum_calculations_total{status="success|error|no_data|fatal_error"}

# Processing time
momentum_calculation_duration_seconds (histogram)

# Current differential
momentum_differential{match_id="123"} (gauge)
```

### Live Market Engine
```
# Market generation attempts
live_market_generations_total{status="success|error|no_data|fatal_error"}

# Processing time
live_market_generation_duration_seconds (histogram)
```

### WebSocket
```
# Active connections
websocket_connections_active (gauge)

# Messages sent
websocket_messages_sent_total{match_id="123",message_type="delta"} (counter)
```

### Fixture Resolution
```
# Resolution attempts
fixture_resolution_attempts_total{status="success|error",method="cache|table|api|manual_override"}
```

## Alerts (Recommended)

### Grafana Alert Rules

**Momentum Engine Stalled**
```promql
rate(momentum_calculations_total[5m]) == 0
```
→ No momentum calculations in 5 minutes (expected: ~0.0167/s for 60s cycles)

**High Market Generation Error Rate**
```promql
rate(live_market_generations_total{status="error"}[5m]) / 
rate(live_market_generations_total[5m]) > 0.2
```
→ More than 20% of market generations failing

**WebSocket Overload**
```promql
websocket_connections_active > 100
```
→ Consider connection pooling optimization

## Scheduler Jobs

### Phase 2 Jobs (60-second cycles)

1. **Momentum Calculation** (`calculate_momentum`)
   - Frequency: Every 60 seconds
   - Function: `models.momentum_calculator.calculate_momentum()`
   - Output: Updates `live_momentum` table

2. **Live Market Generation** (`compute_live_markets`)
   - Frequency: Every 60 seconds
   - Function: `models.live_market_engine.compute_live_markets()`
   - Output: Updates `live_model_markets` table

3. **Fixture ID Resolution** (`resolve_fixture_ids`)
   - Frequency: Every 60 seconds
   - Function: `models.fixture_id_resolver.resolve_fixture_ids()`
   - Output: Links fixtures → API-Football IDs

## Configuration

### Environment Variables
```bash
DATABASE_URL=postgresql://...
OPENAI_API_KEY=sk-...
ODDS_API_KEY=...
RAPIDAPI_KEY=...
```

### Feature Flags
- Live betting enabled by default for `status=live` matches
- WebSocket endpoint always available
- Momentum/markets auto-populate if live data exists (5-min window)

## Performance

### Target Metrics
- Momentum calculation: <500ms per match
- Market generation: <500ms per match
- /market API (live): <2s for 10 matches
- WebSocket latency: <100ms

### Optimization Tips
1. **Database indexes**: Ensure `live_momentum(match_id)` and `live_model_markets(match_id)` are indexed
2. **Connection pooling**: Use `psycopg2.pool` for high WebSocket concurrency
3. **Caching**: Consider Redis for frequently accessed momentum scores
4. **Rate limiting**: Implement per-client WebSocket message throttling

## Testing

### Manual Testing
```bash
# 1. Start server
python main.py

# 2. Simulate live match (insert test data)
psql $DATABASE_URL -c "INSERT INTO fixtures ..."

# 3. Trigger momentum calculation
curl -X POST http://localhost:5000/admin/trigger-momentum

# 4. Check /market API
curl -H "Authorization: Bearer betgenius_secure_key_2024" \
     "http://localhost:5000/market?status=live"

# 5. Connect WebSocket client
wscat -c ws://localhost:5000/ws/live/1234567
```

### Automated Tests
- Unit tests: `tests/test_momentum_calculator.py`
- Integration tests: `tests/test_live_market_engine.py`
- WebSocket tests: `tests/test_realtime_ws.py`

## Rollout Checklist

- [x] Phase 2 engines deployed
- [x] Database tables created
- [x] Scheduler jobs running (60s cycles)
- [x] /market API extended
- [x] WebSocket endpoint registered
- [x] Prometheus metrics instrumented
- [x] Documentation published
- [ ] Load testing (WebSocket fan-out)
- [ ] AI trigger momentum rules (future)
- [ ] Grafana dashboard (future)

## Troubleshooting

### No momentum scores appearing
**Check:**
1. Are there live matches? (`SELECT * FROM fixtures WHERE status='scheduled' AND kickoff_at <= NOW()`)
2. Is live data being collected? (`SELECT * FROM live_match_stats WHERE timestamp > NOW() - INTERVAL '5 minutes'`)
3. Check scheduler logs for errors

### Model markets returning null
**Check:**
1. Does the match have consensus predictions? (`SELECT * FROM consensus_predictions WHERE match_id=?`)
2. Is momentum data available? (`SELECT * FROM live_momentum WHERE match_id=?`)
3. Check time decay alpha calculation (early game may fallback to pre-match)

### WebSocket not broadcasting
**Check:**
1. Is the match in connection manager? (`ConnectionManager.active_connections`)
2. Are momentum/markets updating in database?
3. Check WebSocket error logs in client console

## Future Enhancements

1. **AI Trigger Improvements**: Add momentum inflection detection (rapid swings trigger analysis)
2. **Historical Playback**: Replay momentum/markets from past matches for strategy backtesting
3. **Multi-Match Dashboard**: WebSocket fan-out to multiple matches simultaneously
4. **Bet Sizing Recommendations**: Use Kelly Criterion with momentum-adjusted edge
5. **Alert System**: Push notifications for high-value betting opportunities

---

**Author:** BetGenius AI Team  
**Last Updated:** November 2025  
**Related Docs:** `docs/PHASE1_LIVE_BETTING.md`, `docs/OPERATIONS_RUNBOOK.md`
