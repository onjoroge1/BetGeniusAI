# /market API - Live Match Enhancements & Improvements

**Date**: November 1, 2025  
**Status**: 📋 Enhancement Roadmap

---

## 🎯 **Current State Analysis**

### ✅ What We Have Now

| Feature | Status | Notes |
|---------|--------|-------|
| **match_id for live matches** | ✅ YES | Works for any status (live/upcoming) |
| **Basic match info** | ✅ | Teams, league, kickoff time |
| **Real-time odds** | ✅ | Updated every 60s from 35+ bookmakers |
| **V1 + V2 predictions** | ✅ | Market consensus + ML model |
| **Team logos** | ⚠️ | ~30% coverage |

### ❌ What We're Missing (High Value for Bettors)

| Missing Feature | Value for Bettors | Priority |
|-----------------|-------------------|----------|
| **Live Score** | 🔥 Critical | P0 |
| **Match Statistics** | 🔥 Critical | P0 |
| **Match Events Timeline** | 🔥 High | P1 |
| **In-Play Odds Velocity** | 🔥 High | P1 |
| **Lineup Information** | 🔥 High | P1 |
| **Team Form Trends** | Medium | P2 |
| **Weather/Venue Info** | Medium | P2 |
| **Referee Stats** | Low | P3 |

---

## 📊 **PRIORITY 0: Live Match Statistics (CRITICAL)**

### What Bettors Need During Live Matches

```json
{
  "live_data": {
    "current_score": {
      "home": 1,
      "away": 2,
      "status": "In Play",
      "minute": 67
    },
    "statistics": {
      "possession": {"home": 58, "away": 42},
      "shots_on_target": {"home": 4, "away": 6},
      "shots_total": {"home": 12, "away": 14},
      "corners": {"home": 5, "away": 3},
      "yellow_cards": {"home": 2, "away": 1},
      "red_cards": {"home": 0, "away": 0},
      "fouls": {"home": 9, "away": 7},
      "dangerous_attacks": {"home": 28, "away": 34}
    },
    "momentum": {
      "last_10_min": "away",
      "pressure_index": 0.72,
      "xg_home": 1.2,
      "xg_away": 1.8
    }
  }
}
```

### Implementation Plan

**Step 1: Database Schema Addition**
```sql
CREATE TABLE live_match_stats (
    id SERIAL PRIMARY KEY,
    match_id BIGINT REFERENCES fixtures(match_id),
    minute INT,
    home_score INT,
    away_score INT,
    home_possession INT,
    away_possession INT,
    home_shots_total INT,
    away_shots_total INT,
    home_shots_on_target INT,
    away_shots_on_target INT,
    home_corners INT,
    away_corners INT,
    home_yellow_cards INT,
    away_yellow_cards INT,
    home_red_cards INT,
    away_red_cards INT,
    home_fouls INT,
    away_fouls INT,
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    source TEXT
);

CREATE INDEX idx_live_stats_match ON live_match_stats(match_id, timestamp DESC);
```

**Step 2: Data Collection**
- **API-Football**: Provides live statistics API
- **The Odds API**: Live scores available
- **Polling**: Every 30-60 seconds for live matches

**Step 3: API Enhancement**
```python
# Add to /market endpoint for live matches
if status == "live":
    # Get latest live statistics
    cursor.execute("""
        SELECT home_score, away_score, minute,
               home_possession, away_possession,
               home_shots_on_target, away_shots_on_target,
               home_corners, away_corners,
               home_yellow_cards, away_yellow_cards
        FROM live_match_stats
        WHERE match_id = %s
        ORDER BY timestamp DESC
        LIMIT 1
    """, (match_id,))
    
    if live_stats_row:
        match_obj["live_data"] = {
            "current_score": {...},
            "statistics": {...}
        }
```

---

## 📈 **PRIORITY 1: Match Events Timeline**

### What Bettors Need

```json
{
  "events": [
    {
      "minute": 67,
      "type": "goal",
      "team": "away",
      "player": "Mohamed Salah",
      "score": {"home": 1, "away": 2},
      "timestamp": "2025-11-01T15:23:45Z"
    },
    {
      "minute": 62,
      "type": "yellow_card",
      "team": "home",
      "player": "Casemiro",
      "timestamp": "2025-11-01T15:18:30Z"
    },
    {
      "minute": 45,
      "type": "substitution",
      "team": "home",
      "player_out": "Bruno Fernandes",
      "player_in": "Scott McTominay",
      "timestamp": "2025-11-01T15:01:15Z"
    }
  ]
}
```

### Database Schema

```sql
CREATE TABLE match_events (
    id SERIAL PRIMARY KEY,
    match_id BIGINT REFERENCES fixtures(match_id),
    minute INT,
    event_type VARCHAR(50), -- goal, yellow_card, red_card, substitution, penalty
    team VARCHAR(10), -- 'home' or 'away'
    player_name TEXT,
    detail TEXT, -- e.g., "Normal Goal", "Penalty", "Free Kick"
    score_home INT,
    score_away INT,
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    source TEXT
);

CREATE INDEX idx_events_match ON match_events(match_id, minute DESC);
```

---

## ⚡ **PRIORITY 1: Real-Time Odds Velocity**

### Why This Matters for Bettors

Bettors need to see:
- **How fast odds are moving** (indicates market confidence)
- **Which bookmakers are leading** (sharpest odds)
- **Odds divergence** (arbitrage opportunities)

### Enhanced Odds Response

```json
{
  "odds": {
    "books": {
      "pinnacle": {"home": 3.15, "draw": 2.94, "away": 2.63}
    },
    "novig_current": {"home": 0.309, "draw": 0.309, "away": 0.382},
    "velocity": {
      "last_5_min": {
        "home": -0.05,
        "away": +0.08
      },
      "trend": "away_tightening",
      "sharpest_book": "pinnacle",
      "divergence_score": 0.12
    },
    "snapshots": [
      {"time": "15:25:00", "pinnacle_away": 2.63},
      {"time": "15:20:00", "pinnacle_away": 2.71},
      {"time": "15:15:00", "pinnacle_away": 2.85}
    ]
  }
}
```

### Implementation

**Already have the data** - odds_snapshots table has timestamps!

```python
# Calculate odds velocity
cursor.execute("""
    SELECT ts_snapshot, odds_decimal
    FROM odds_snapshots
    WHERE match_id = %s 
        AND book_id = 'pinnacle'
        AND outcome = 'A'
        AND ts_snapshot > NOW() - INTERVAL '15 minutes'
    ORDER BY ts_snapshot DESC
    LIMIT 10
""", (match_id,))

odds_history = cursor.fetchall()

# Calculate velocity: Δ odds / Δ time
if len(odds_history) >= 2:
    velocity = (odds_history[0][1] - odds_history[-1][1]) / 15  # per minute
```

---

## 🎯 **PRIORITY 1: Lineup Information**

### What Bettors Need

```json
{
  "lineups": {
    "home": {
      "formation": "4-3-3",
      "starting_xi": [
        {"number": 1, "name": "A. Onana", "position": "GK"},
        {"number": 20, "name": "Dalot", "position": "RB"}
      ],
      "substitutes": [...],
      "injuries_suspensions": [
        {"name": "Lisandro Martinez", "status": "injured", "return_date": "2025-11-15"}
      ]
    },
    "away": {...}
  },
  "key_battles": {
    "striker_vs_defender": ["E. Haaland vs V. van Dijk"],
    "midfield_duel": ["Rodri vs Casemiro"]
  }
}
```

### Database Schema

```sql
CREATE TABLE match_lineups (
    id SERIAL PRIMARY KEY,
    match_id BIGINT REFERENCES fixtures(match_id),
    team VARCHAR(10), -- 'home' or 'away'
    formation VARCHAR(10),
    starting_xi JSONB,
    substitutes JSONB,
    injuries JSONB,
    confirmed BOOLEAN DEFAULT FALSE,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

---

## 🌐 **Enhanced Single Match Endpoint Response**

### For Live Matches: `/market?match_id=X&status=live`

```json
{
  "match_id": 1374261,
  "status": "LIVE",
  "kickoff_at": "2025-11-01T15:00:00Z",
  "league": {...},
  "home": {...},
  "away": {...},
  
  "live_data": {
    "current_score": {"home": 1, "away": 2},
    "minute": 67,
    "period": "2nd Half",
    "statistics": {
      "possession": {"home": 58, "away": 42},
      "shots_on_target": {"home": 4, "away": 6},
      "corners": {"home": 5, "away": 3}
    },
    "momentum": {
      "last_10_min": "away",
      "dangerous_attacks": {"home": 28, "away": 34}
    }
  },
  
  "events": [
    {"minute": 67, "type": "goal", "team": "away", "player": "M. Salah"},
    {"minute": 62, "type": "yellow_card", "team": "home", "player": "Casemiro"}
  ],
  
  "odds": {
    "books": {...},
    "velocity": {
      "last_5_min": {"away": +0.08},
      "trend": "away_tightening"
    },
    "snapshots": [...]
  },
  
  "models": {
    "v1_consensus": {...},
    "v2_lightgbm": {...},
    "v2_live_adjusted": {
      "probs": {"home": 0.15, "draw": 0.22, "away": 0.63},
      "adjustment_reason": "Score: 1-2, Momentum: Away, xG: 1.2 vs 1.8"
    }
  },
  
  "betting_insights": {
    "value_picks": [
      {"market": "away_win", "ev": 0.08, "confidence": 0.63}
    ],
    "live_edges": [
      {"insight": "Away team dominating possession and shots"}
    ]
  }
}
```

### For Upcoming Matches: `/market?match_id=X`

```json
{
  "match_id": 1374261,
  "status": "UPCOMING",
  "kickoff_at": "2025-11-01T20:00:00Z",
  
  "pre_match_intel": {
    "team_news": {
      "home": {
        "injuries": ["Lisandro Martinez (knee)"],
        "suspensions": [],
        "confirmed_lineup": false,
        "formation_likely": "4-2-3-1"
      },
      "away": {...}
    },
    "head_to_head": {
      "last_5_meetings": [
        {"date": "2024-10-15", "score": "1-2", "venue": "away"},
        {"date": "2024-03-12", "score": "2-1", "venue": "home"}
      ],
      "home_wins": 2,
      "draws": 1,
      "away_wins": 2
    },
    "recent_form": {
      "home_last_5": "W-W-D-L-W",
      "away_last_5": "W-W-W-D-W",
      "home_goals_per_game": 1.8,
      "away_goals_per_game": 2.4
    },
    "venue_stats": {
      "name": "Old Trafford",
      "home_record_this_season": "5W-2D-1L",
      "weather_forecast": "Clear, 15°C, 10mph wind"
    }
  },
  
  "odds": {...},
  "models": {...},
  
  "betting_insights": {
    "key_factors": [
      "Home team missing key defender",
      "Away team on 5-match winning streak",
      "Historical H2H favors away team slightly"
    ],
    "value_picks": [...],
    "recommended_markets": [
      {"market": "over_2.5_goals", "reasoning": "Both teams averaging 2+ goals"}
    ]
  }
}
```

---

## 🚀 **Implementation Roadmap**

### Phase 1: Live Score & Basic Stats (Week 1)
- [ ] Create `live_match_stats` table
- [ ] Set up API-Football live data collector (30s polling)
- [ ] Add live score to `/market` response for live matches
- [ ] Add basic statistics (shots, corners, cards)
- [ ] **Estimated Time**: 8-12 hours
- [ ] **Value**: 🔥🔥🔥 Critical for live betting

### Phase 2: Match Events & Timeline (Week 1-2)
- [ ] Create `match_events` table
- [ ] Collect goal, card, substitution events
- [ ] Add events array to `/market` response
- [ ] **Estimated Time**: 4-6 hours
- [ ] **Value**: 🔥🔥 High - bettors want to see what just happened

### Phase 3: Odds Velocity & Trends (Week 2)
- [ ] Calculate odds movement from existing `odds_snapshots`
- [ ] Add velocity metrics to odds response
- [ ] Show 15-minute odds history
- [ ] **Estimated Time**: 3-4 hours
- [ ] **Value**: 🔥🔥 High - indicates market sentiment

### Phase 4: Pre-Match Intelligence (Week 2-3)
- [ ] Create `match_lineups` table
- [ ] Create `team_news` table
- [ ] Collect lineup confirmations 2h before kickoff
- [ ] Add pre-match intel section
- [ ] **Estimated Time**: 6-8 hours
- [ ] **Value**: 🔥 Medium-High - helps pre-match analysis

### Phase 5: Advanced Insights (Week 3-4)
- [ ] Calculate xG (expected goals) from shot data
- [ ] Add momentum indicators
- [ ] Weather integration
- [ ] Venue statistics
- [ ] **Estimated Time**: 8-10 hours
- [ ] **Value**: Medium - nice-to-have enhancements

---

## 💰 **Data Source Costs**

| Source | Feature | Cost | Frequency |
|--------|---------|------|-----------|
| **API-Football** | Live scores | ✅ Included | Every 30s |
| **API-Football** | Live statistics | ✅ Included | Every 30s |
| **API-Football** | Match events | ✅ Included | Every 30s |
| **API-Football** | Lineups | ✅ Included | 2h before kickoff |
| **The Odds API** | Real-time odds | ✅ Have it | Every 60s |
| **OpenAI** | AI insights | ✅ Have it | On-demand |

**Total Additional Cost**: $0 (we already have API-Football access!)

---

## 🎯 **Quick Wins (Implement Today)**

### 1. Answer to Question 1: **YES** ✅

The `match_id` parameter **already works for live matches**:

```bash
# Get single live match
curl "http://localhost:8000/market?match_id=1374261" \
  -H "Authorization: Bearer betgenius_secure_key_2024"
```

This works regardless of status - it's status-agnostic!

---

### 2. Real-Time Odds (Already Have It!) ✅

We already collect odds every 60 seconds in `odds_snapshots` table. We can:

**Quick Implementation** (30 minutes):
```python
# Add odds velocity to /market endpoint
def calculate_odds_velocity(match_id, book_id='pinnacle'):
    cursor.execute("""
        SELECT ts_snapshot, odds_decimal
        FROM odds_snapshots
        WHERE match_id = %s 
            AND book_id = %s
            AND outcome = 'A'
            AND ts_snapshot > NOW() - INTERVAL '15 minutes'
        ORDER BY ts_snapshot DESC
    """, (match_id, book_id))
    
    snapshots = cursor.fetchall()
    if len(snapshots) >= 2:
        latest = snapshots[0][1]
        oldest = snapshots[-1][1]
        velocity = (latest - oldest) / 15  # per minute
        return {
            "velocity_per_min": velocity,
            "direction": "tightening" if velocity < 0 else "drifting",
            "recent_snapshots": snapshots[:5]
        }
```

---

## 📋 **Recommended Implementation Order**

### This Week (High Impact)
1. ✅ **match_id for live matches** - Already works!
2. 🔧 **Live scores** - 4 hours to implement
3. 🔧 **Basic live statistics** - 4 hours to implement
4. 🔧 **Odds velocity** - 2 hours to implement

### Next Week (Medium Impact)
5. 🔧 **Match events timeline** - 6 hours
6. 🔧 **Pre-match team news** - 6 hours
7. 🔧 **H2H history** - 4 hours

### Later (Nice-to-Have)
8. 🔧 **Weather/venue info** - 3 hours
9. 🔧 **Advanced xG metrics** - 8 hours
10. 🔧 **Referee statistics** - 4 hours

---

## 🎯 **Summary: What Bettors Value Most**

| Feature | Bettor Value | Effort | ROI |
|---------|--------------|--------|-----|
| **Live Score** | 🔥🔥🔥 Critical | 4h | ⭐⭐⭐⭐⭐ |
| **Live Statistics** | 🔥🔥🔥 Critical | 4h | ⭐⭐⭐⭐⭐ |
| **Match Events** | 🔥🔥 High | 6h | ⭐⭐⭐⭐ |
| **Odds Velocity** | 🔥🔥 High | 2h | ⭐⭐⭐⭐⭐ |
| **Team Lineups** | 🔥🔥 High | 6h | ⭐⭐⭐⭐ |
| **H2H History** | 🔥 Medium | 4h | ⭐⭐⭐ |
| **Weather** | Medium | 3h | ⭐⭐ |
| **Referee Stats** | Low | 4h | ⭐ |

---

**Next Steps**: Should I implement Phase 1 (Live Score + Basic Stats) now? This would take ~8 hours and provide critical value for bettors.
