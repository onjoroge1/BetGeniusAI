# /market API Endpoint - Comprehensive Analysis

## 🔴 CRITICAL ISSUES FOUND

### Issue #1: Status Determination Broken
**Location:** `main.py` line 6610  
**Problem:** When a specific `match_id` is requested, the endpoint returns `"status": status.upper()` based on the URL parameter, not the actual match state.

**Example:**
```
Request: /market?match_id=1351162&status=live
Response: { "status": "LIVE", ... }  ← Trusts URL param blindly
```

**Root cause:**
- Line 6014-6038: Single-match query doesn't check if match is actually live
- Line 6610: Uses URL param directly: `"status": status.upper()`

**Expected behavior:**
- Determine actual status from `kickoff_at` + `live_match_stats` existence
- Return "UPCOMING", "LIVE", or "FINISHED" based on data, not URL param

---

### Issue #2: Missing `momentum` Field
**Location:** `main.py` line 6505-6650  
**Problem:** Live matches don't include momentum scores from Phase 2 Momentum Engine

**What's missing:**
```json
{
  "momentum": {
    "home": 65,
    "away": 35,
    "breakdown": { ... }
  }
}
```

**Available but not used:**
- `MomentumCalculator.compute_momentum(match_id)` exists (models/momentum_calculator.py:189)
- Returns `(momentum_home, momentum_away, breakdown)` tuple
- Scores are 0-100 with detailed component breakdown

**Frontend components affected:**
- `MomentumIndicator` - Shows momentum bars (broken without this field)
- `LiveMatchStats` - Displays momentum metrics

---

### Issue #3: Missing `model_markets` Field
**Location:** `main.py` line 6505-6650  
**Problem:** Live matches don't include live market predictions

**What's missing:**
```json
{
  "model_markets": {
    "live_1x2": {
      "home": 0.45,
      "draw": 0.28,
      "away": 0.27
    },
    "next_goal": { ... },
    "minutes_elapsed": 37
  }
}
```

**Available but not used:**
- `LiveMarketEngine.compute_live_markets(match_id, minutes_elapsed)` exists (models/live_market_engine.py:307)
- Returns live 1X2, next goal, and over/under markets
- Uses time-aware blending (market + live stats + momentum)

**Frontend components affected:**
- `LiveMarketAnalysis` - Shows live predictions (broken without this field)
- `LiveScoreCard` - May display updated probabilities

---

### Issue #4: Live Data Conditional Logic Flaw
**Location:** `main.py` line 6511  
**Problem:** Live data only added if `status == "live"` (URL param), not actual match state

**Current code:**
```python
if status == "live":  # ← Wrong! Uses URL param
    cursor.execute(...)  # Get live_match_stats
    live_data = { ... }
```

**Problem:**
- If user requests `/market?match_id=X&status=all`, no live data added
- If match is actually live but URL says `status=upcoming`, no live data

**Expected:**
- Determine actual match state from database
- Add live data for ANY match that has fresh `live_match_stats`

---

## 📊 Data Flow Diagram

```
Current (Broken):
┌─────────────────┐
│ URL Parameter   │
│ status="live"   │ ← Frontend blindly sets this
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ API Returns     │
│ status="LIVE"   │ ← Just echoes URL param
│ (no momentum)   │
│ (no markets)    │
└─────────────────┘

Expected (Fixed):
┌─────────────────┐
│ Database Query  │
│ kickoff_at +    │
│ live_stats      │
└────────┬────────┘
         │
         ▼
┌─────────────────────────┐
│ Determine Actual Status │
│ - kickoff_at > NOW()    │ → "UPCOMING"
│ - kickoff + fresh stats │ → "LIVE" + momentum + markets
│ - status = 'finished'   │ → "FINISHED"
└─────────────────────────┘
```

---

## 🛠️ REQUIRED FIXES

### Fix #1: Dynamic Status Determination
**Before:**
```python
match_obj = {
    "status": status.upper(),  # ← Wrong
    ...
}
```

**After:**
```python
# Determine actual match state
actual_status = self._determine_match_status(
    kickoff_at=kickoff_at,
    db_status=db_status,  # From fixtures.status
    match_id=match_id
)

match_obj = {
    "status": actual_status,  # "UPCOMING", "LIVE", or "FINISHED"
    ...
}
```

**Helper function:**
```python
def _determine_match_status(kickoff_at, db_status, match_id, cursor) -> str:
    """Determine actual match status from database"""
    
    # Already finished in DB
    if db_status == 'finished':
        return "FINISHED"
    
    # Check if match has started
    if kickoff_at > datetime.now(timezone.utc):
        return "UPCOMING"
    
    # Started, check for fresh live data (< 10 min old)
    cursor.execute("""
        SELECT 1 FROM live_match_stats
        WHERE match_id = %s
          AND timestamp > NOW() - INTERVAL '10 minutes'
        LIMIT 1
    """, (match_id,))
    
    has_fresh_data = cursor.fetchone() is not None
    
    return "LIVE" if has_fresh_data else "FINISHED"
```

---

### Fix #2: Add Momentum Field
**Add after line 6640:**
```python
# Add momentum scores for live matches
if actual_status == "LIVE":
    try:
        from models.momentum_calculator import MomentumCalculator
        momentum_calc = MomentumCalculator()
        
        result = momentum_calc.compute_momentum(match_id)
        if result:
            momentum_home, momentum_away, breakdown = result
            match_obj["momentum"] = {
                "home": momentum_home,
                "away": momentum_away,
                "breakdown": breakdown
            }
    except Exception as e:
        logger.error(f"Momentum calculation failed for match {match_id}: {e}")
        # Don't block response if momentum fails
```

---

### Fix #3: Add Model Markets Field
**Add after momentum:**
```python
# Add live market predictions
if actual_status == "LIVE" and live_data:
    try:
        from models.live_market_engine import LiveMarketEngine
        market_engine = LiveMarketEngine()
        
        minutes_elapsed = live_data.get('minute', 0)
        markets = market_engine.compute_live_markets(match_id, minutes_elapsed)
        
        if markets:
            match_obj["model_markets"] = markets
    except Exception as e:
        logger.error(f"Live markets failed for match {match_id}: {e}")
```

---

### Fix #4: Fix Live Data Conditional
**Before:**
```python
if status == "live":  # ← Uses URL param
    cursor.execute(...)
    live_data = { ... }
```

**After:**
```python
if actual_status == "LIVE":  # ← Uses actual match state
    cursor.execute(...)
    live_data = { ... }
```

---

## 🎯 Expected Response Structure (After Fix)

### For Live Match: `/market?match_id=1351162&status=live`
```json
{
  "matches": [
    {
      "match_id": 1351162,
      "status": "LIVE",  ← Determined from data, not URL
      "kickoff_at": "2025-11-15T18:00:00Z",
      "home": { "name": "Arsenal", "logo_url": "..." },
      "away": { "name": "Chelsea", "logo_url": "..." },
      
      "live_data": {  ← Existing (works)
        "current_score": { "home": 1, "away": 0 },
        "minute": 37,
        "period": "1H",
        "statistics": { ... }
      },
      
      "momentum": {  ← NEW - Was missing!
        "home": 65,
        "away": 35,
        "breakdown": {
          "shots_component": 0.45,
          "possession_component": 0.12,
          "xg_component": 0.38,
          "odds_velocity_component": 0.05
        }
      },
      
      "model_markets": {  ← NEW - Was missing!
        "live_1x2": {
          "home": 0.48,
          "draw": 0.26,
          "away": 0.26
        },
        "next_goal": {
          "home": 0.52,
          "none": 0.12,
          "away": 0.36
        },
        "minutes_elapsed": 37
      },
      
      "odds": { ... },
      "models": { ... }
    }
  ]
}
```

---

## 📋 Testing Checklist

After implementing fixes, test:

1. **Upcoming match**: `/market?match_id=X&status=upcoming`
   - ✅ Returns `"status": "UPCOMING"`
   - ✅ No `live_data`, `momentum`, or `model_markets`

2. **Live match (correct status param)**: `/market?match_id=Y&status=live`
   - ✅ Returns `"status": "LIVE"`
   - ✅ Includes `live_data` with score + minute
   - ✅ Includes `momentum` with home/away scores
   - ✅ Includes `model_markets` with live predictions

3. **Live match (wrong status param)**: `/market?match_id=Y&status=upcoming`
   - ✅ Still returns `"status": "LIVE"` (determined from data)
   - ✅ Still includes all live fields

4. **Live match (no status param)**: `/market?match_id=Y`
   - ✅ Defaults to "all" but still detects live state
   - ✅ Returns all live fields

5. **Finished match**: `/market?match_id=Z&status=live`
   - ✅ Returns `"status": "FINISHED"`
   - ✅ No live fields (match is over)

---

## 🎨 Frontend Impact

### Components Fixed:
1. **LiveScoreCard** - Now receives `live_data.current_score` + `status="LIVE"`
2. **MomentumIndicator** - Now receives `momentum.home` + `momentum.away`
3. **LiveMatchStats** - Now receives full `live_data.statistics` + `momentum.breakdown`
4. **LiveMarketAnalysis** - Now receives `model_markets.live_1x2`

### Before (Broken):
```jsx
// Frontend tries to render
<MomentumIndicator momentum={match.momentum} />
// match.momentum is undefined → Component shows error or nothing
```

### After (Fixed):
```jsx
<MomentumIndicator momentum={match.momentum} />
// match.momentum = { home: 65, away: 35, ... } → Works!
```

---

## 📊 Performance Impact

**Minimal** - New logic adds:
- 1 SQL query for status determination (fast, indexed on match_id)
- 1 momentum calculation (~50ms for window queries)
- 1 live market calculation (~30ms for blending logic)

**Total overhead**: ~80-100ms for live matches  
**Acceptable**: Yes, live matches update every 60 seconds anyway

---

## 🔒 Safety Notes

1. **Graceful degradation**: All new fields wrapped in try-except
2. **No breaking changes**: Existing fields remain unchanged
3. **Backward compatible**: Clients without new fields still work
4. **Error logging**: Failed momentum/markets logged but don't block response

---

*Last updated: 2025-11-15*  
*Priority: CRITICAL - Blocking frontend live match display*
