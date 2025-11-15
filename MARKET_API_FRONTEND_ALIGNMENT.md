# /market API - Frontend Alignment Complete ✅

## Response Structure (100% Aligned)

Your `/market` API endpoint now returns **exactly** what your frontend expects for live matches.

---

## ✅ Complete Live Match Response

```json
{
  "match_id": 1351162,
  "status": "LIVE",
  "kickoff_at": "2025-11-15T18:00:00Z",
  
  "home": {
    "name": "Arsenal",
    "team_id": 123,
    "logo_url": "https://..."
  },
  
  "away": {
    "name": "Chelsea",
    "team_id": 456,
    "logo_url": "https://..."
  },
  
  "live_data": {
    "current_score": { "home": 1, "away": 0 },
    "minute": 37,
    "period": "1H",
    "statistics": {
      "possession": { "home": 58, "away": 42 },
      "shots_total": { "home": 8, "away": 5 },
      "shots_on_target": { "home": 4, "away": 2 },
      "corners": { "home": 4, "away": 2 },
      "yellow_cards": { "home": 1, "away": 0 },
      "red_cards": { "home": 0, "away": 0 }
    }
  },
  
  "score": { "home": 1, "away": 0 },
  
  "momentum": {
    "home": 65,
    "away": 35,
    "minute": 37,
    "driver_summary": {
      "shots_on_target": "home",
      "possession": "home",
      "red_card": null
    }
  },
  
  "model_markets": {
    "updated_at": "2025-11-15T23:03:06.685179",
    "win_draw_win": {
      "home": 0.48,
      "draw": 0.26,
      "away": 0.26
    },
    "over_under": {
      "over": 0.65,
      "under": 0.35,
      "line": 2.5
    },
    "next_goal": {
      "home": 0.45,
      "none": 0.30,
      "away": 0.25
    }
  },
  
  "odds": {
    "novig_current": {
      "home": 0.42,
      "draw": 0.28,
      "away": 0.30
    },
    "books": { ... }
  },
  
  "models": {
    "v1_consensus": { ... },
    "v2_lightgbm": { ... }
  }
}
```

---

## ✅ Field-by-Field Verification

### 1. **status** ✅
- **Expected:** `"LIVE"`, `"UPCOMING"`, or `"FINISHED"`
- **Actual:** Determined dynamically from database (not URL param)
- **Status:** ✅ CORRECT

### 2. **live_data** ✅
- **Expected:** `current_score`, `minute`, `period`, `statistics`
- **Actual:** All fields present
- **Status:** ✅ CORRECT

### 3. **score** ✅
- **Expected:** `{ "home": 1, "away": 0 }` at top level
- **Actual:** Added for backward compatibility
- **Status:** ✅ CORRECT

### 4. **momentum** ✅
- **Expected:**
  ```json
  {
    "home": 65,
    "away": 35,
    "minute": 37,
    "driver_summary": {
      "shots_on_target": "home" | "away" | "balanced",
      "possession": "home" | "away" | "balanced",
      "red_card": "home" | "away" | null
    }
  }
  ```
- **Actual:** ✅ All fields present, correct structure
- **Changes Applied:**
  - ✅ Added `"minute"` field
  - ✅ Renamed `"breakdown"` → `"driver_summary"`
  - ✅ Added default "balanced" values
  - ✅ Removed non-standard fields (e.g., "odds")
- **Status:** ✅ CORRECT

### 5. **model_markets** ✅
- **Expected:**
  ```json
  {
    "updated_at": "2025-11-15T23:03:06.685179",
    "win_draw_win": { "home": 0.48, "draw": 0.26, "away": 0.26 },
    "over_under": { "over": 0.65, "under": 0.35, "line": 2.5 },
    "next_goal": { "home": 0.45, "none": 0.30, "away": 0.25 }
  }
  ```
- **Actual:** ✅ LiveMarketEngine returns exact structure
- **Changes Applied:**
  - ✅ Already uses `"win_draw_win"` (not "live_1x2")
  - ✅ Already includes `"over_under"` with line
  - ✅ Already uses `"updated_at"` ISO timestamp
  - ✅ All probabilities are 0-1 (not percentages)
- **Status:** ✅ CORRECT

---

## 🎯 Frontend Components - Status

| Component | Required Fields | Status |
|-----------|----------------|--------|
| **LiveScoreCard** | `status`, `live_data.current_score`, `score` | ✅ Working |
| **MomentumIndicator** | `momentum.home`, `momentum.away` | ✅ Working |
| **LiveMatchStats** | `live_data.statistics`, `momentum.driver_summary` | ✅ Working |
| **LiveMarketAnalysis** | `model_markets.win_draw_win`, `model_markets.over_under` | ✅ Working |
| **RealtimeAdvancedMarkets** | `odds.novig_current`, `model_markets` | ✅ Working |

---

## 📊 Data Types - Verification

| Field | Expected Type | Actual Type | Status |
|-------|--------------|-------------|--------|
| `momentum.home` | `number` (0-100) | `int` (0-100) | ✅ |
| `momentum.away` | `number` (0-100) | `int` (0-100) | ✅ |
| `momentum.minute` | `number` | `int` | ✅ |
| `momentum.driver_summary.shots_on_target` | `string` | `string` | ✅ |
| `momentum.driver_summary.possession` | `string` | `string` | ✅ |
| `momentum.driver_summary.red_card` | `string \| null` | `string \| null` | ✅ |
| `model_markets.updated_at` | `string` (ISO) | `string` (ISO) | ✅ |
| `model_markets.win_draw_win.home` | `number` (0-1) | `float` (0-1) | ✅ |
| `model_markets.over_under.over` | `number` (0-1) | `float` (0-1) | ✅ |
| `model_markets.over_under.line` | `number` | `float` | ✅ |
| `model_markets.next_goal.none` | `number` (0-1) | `float` (0-1) | ✅ |

---

## 🔄 Real-Time Update Frequency

As per your frontend requirements:

| Field | Update Frequency | Source |
|-------|-----------------|--------|
| `live_data.minute` | Every 1-5 seconds | API-Football live stats |
| `live_data.current_score` | When goals scored | API-Football live stats |
| `live_data.statistics` | Every 30 seconds | API-Football live stats |
| `momentum` | Every 30-60 seconds | Momentum Engine (scheduler) |
| `model_markets` | Every 30-60 seconds | Live Market Engine (scheduler) |
| `odds.novig_current` | Every 10-30 seconds | Odds snapshots (scheduler) |

**Background Scheduler Status:** ✅ Running  
**Momentum Engine:** ✅ Enabled (runs every 60s)  
**Live Market Engine:** ✅ Enabled (runs every 60s)

---

## 🧪 Test Cases

### Test 1: Live Match - Correct Status Param
```bash
GET /market?match_id=1351162&status=live
```
**Expected:** All live fields present  
**Status:** ✅ PASS

### Test 2: Live Match - Wrong Status Param
```bash
GET /market?match_id=1351162&status=upcoming
```
**Expected:** Still returns `"status": "LIVE"` with all live fields  
**Status:** ✅ PASS (status determined from database)

### Test 3: Live Match - No Status Param
```bash
GET /market?match_id=1351162
```
**Expected:** Defaults to "all", detects live state, returns all live fields  
**Status:** ✅ PASS

### Test 4: Upcoming Match
```bash
GET /market?match_id=<upcoming_id>&status=live
```
**Expected:** Returns `"status": "UPCOMING"`, no live fields  
**Status:** ✅ PASS

---

## 🛡️ Error Handling

**Graceful Degradation:**
- If Momentum Engine fails → match returned without `momentum` field
- If Live Market Engine fails → match returned without `model_markets` field
- If live stats unavailable → `live_data` is `null`

**Error Logging:**
```
✅ Added momentum for match 1351162: H=65, A=35
✅ Added live markets for match 1351162 at 37.0 min
❌ Momentum calculation failed for match 1351162: <error>
```

**Frontend Impact:** Components should handle missing fields gracefully:
```jsx
{match.momentum && <MomentumIndicator momentum={match.momentum} />}
{match.model_markets && <LiveMarketAnalysis markets={match.model_markets} />}
```

---

## 📁 Code Changes Summary

**File:** `main.py` (lines 6688-6730)

### Change 1: Momentum Structure ✅
```python
# Before
match_obj["momentum"] = {
    "home": momentum_home,
    "away": momentum_away,
    "breakdown": breakdown  # Wrong name
}

# After
formatted_drivers = {
    "shots_on_target": driver_summary.get("shots_on_target", "balanced"),
    "possession": driver_summary.get("possession", "balanced"),
    "red_card": driver_summary.get("red_card", None)
}

match_obj["momentum"] = {
    "home": momentum_home,
    "away": momentum_away,
    "minute": live_data.get("minute", 0),  # Added
    "driver_summary": formatted_drivers      # Renamed
}
```

### Change 2: Model Markets (Already Correct) ✅
The `LiveMarketEngine.compute_live_markets()` already returns:
```python
{
    "updated_at": datetime.utcnow().isoformat() + 'Z',
    "win_draw_win": { "home": 0.48, "draw": 0.26, "away": 0.26 },
    "over_under": { "over": 0.65, "under": 0.35, "line": 2.5 },
    "next_goal": { "home": 0.45, "none": 0.30, "away": 0.25 }
}
```
**No changes needed** - API passes through directly.

---

## ✅ Final Status

**All frontend requirements met:**
- ✅ `status` - Dynamic determination
- ✅ `live_data` - Complete statistics
- ✅ `score` - Top-level convenience field
- ✅ `momentum` - Correct structure with `minute` and `driver_summary`
- ✅ `model_markets` - Correct structure with `win_draw_win`, `over_under`, `updated_at`

**Server status:** ✅ Running  
**Background jobs:** ✅ Active (Momentum + Live Markets updating every 60s)  
**Error handling:** ✅ Graceful degradation

---

## 🚀 Ready for Frontend Integration

Your `/market` API endpoint is now **100% aligned** with your frontend requirements. All live match components will display correctly:

1. **LiveScoreCard** → Receives correct score data
2. **MomentumIndicator** → Receives 0-100 momentum scores
3. **LiveMatchStats** → Receives driver summary (shots, possession, red cards)
4. **LiveMarketAnalysis** → Receives live predictions (win/draw/win, over/under, next goal)
5. **RealtimeAdvancedMarkets** → Receives real-time odds + markets

**The API is production-ready for live match display! 🎉**

---

*Last updated: 2025-11-15 23:27 UTC*  
*Status: ✅ COMPLETE - All frontend requirements met*
