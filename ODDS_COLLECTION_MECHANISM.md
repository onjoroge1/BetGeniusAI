# BetGenius AI - Odds Collection Mechanism

## Current T-24h Odds Collection Strategy

Based on code analysis, we use a **hybrid approach** with both automated and on-demand collection:

## 1. Automated Daily Collection ⏰

**Scheduler**: Runs at **2:00 AM UTC daily**
```python
# From utils/scheduler.py
self.collection_time = time(hour=2, minute=0)  # 2 AM UTC daily
```

**Process**:
- Automatically collects matches from the last 3 days
- Processes Premier League, La Liga, Bundesliga, Serie A
- Stores odds data in PostgreSQL database
- Runs daily whether API calls are made or not

**Purpose**: 
- Build historical odds database
- Ensure we have T-24h+ data for completed matches
- Maintain comprehensive dataset for model training

## 2. Real-Time Collection (API-Triggered) 🔄

**Triggered by**: User API calls to `/predict` endpoint

**Process Flow**:
```python
# From main.py - prediction endpoint
match_data = enhanced_data_collector.collect_comprehensive_match_data(request.match_id)
```

**What Happens**:
1. User requests prediction for specific match
2. System immediately fetches current odds from The Odds API
3. Collects fresh injury data, team news, recent form
4. Generates prediction using latest available data
5. Returns prediction with real-time context

## Current Implementation Analysis

### Time Bucket Strategy
```python
# From consensus_builder.py
time_buckets = {
    'open': {'min_hours': 168, 'max_hours': None},  # 7 days+
    '48h': {'min_hours': 36, 'max_hours': 60},      # T-48h
    '24h': {'min_hours': 18, 'max_hours': 30},      # T-24h ← Current default
    '12h': {'min_hours': 6, 'max_hours': 18},
    '6h': {'min_hours': 3, 'max_hours': 9}
}
```

### Odds Processing Method
1. **Historical Odds**: Stored from daily automated collection
2. **Current Odds**: Fetched on-demand during prediction requests  
3. **Consensus Building**: Multiple bookmaker odds processed via The Odds API
4. **Vig Removal**: Bookmaker margins removed for true probabilities

## Key Findings

### What We Do Well:
✅ **Real-time collection** during prediction requests  
✅ **Historical data building** via automated daily collection  
✅ **Multiple bookmaker consensus** for accuracy  
✅ **Fresh data guarantee** - always current when user requests prediction

### What Could Be Optimized:
⚠️ **T-24h vs T-72h**: Using T-24h but should optimize for T-72h  
⚠️ **Proactive T-72h collection**: Could pre-collect odds at optimal timing  
⚠️ **Timing-aware predictions**: Should adjust confidence based on collection timing

## Recommendation: Enhanced Timing Strategy

### Current Reality:
```
User Request → Real-time collection → Immediate prediction
```

### Optimal Strategy:
```
T-72h: Automated optimal odds collection
T-24h: Current automated daily collection  
T-0h: Real-time collection for immediate requests
```

## Implementation Plan

### Phase 1: T-72h Automated Collection
```python
# Add to scheduler.py
optimal_collection_times = [
    time(hour=2, minute=0),   # T-72h for matches in 3 days
    time(hour=8, minute=0),   # T-48h for matches in 2 days  
    time(hour=14, minute=0),  # T-24h for matches tomorrow
]
```

### Phase 2: Timing-Aware Predictions
```python
def get_prediction_with_timing_context(match_id, hours_to_kickoff):
    if hours_to_kickoff >= 72:
        # Use stored T-72h optimal odds
        return get_optimal_prediction(match_id)
    else:
        # Real-time collection with timing adjustment
        return get_realtime_prediction(match_id, timing_adjustment=True)
```

### Phase 3: Proactive Value Identification
```python
# Daily T-72h analysis
def identify_t72h_value_bets():
    """
    At T-72h, identify value bets for upcoming matches
    Store predictions when market efficiency is optimal
    """
    upcoming_matches = get_matches_in_72_hours()
    for match in upcoming_matches:
        optimal_prediction = generate_t72h_prediction(match.id)
        store_optimal_prediction(match.id, optimal_prediction)
```

## Current API Behavior Summary

**When you call our prediction API:**
1. ✅ **Immediate odds fetch** from The Odds API
2. ✅ **Real-time injury data** from RapidAPI  
3. ✅ **Current team form** and recent matches
4. ✅ **Fresh consensus calculation** from multiple bookmakers
5. ✅ **Live AI analysis** using all current data

**Background automated collection:**
1. ✅ **Daily 2 AM UTC** collection for historical database
2. ✅ **Last 3 days** of completed matches processed
3. ✅ **Automatic model retraining** when sufficient new data
4. ✅ **Comprehensive feature extraction** for all matches

## Bottom Line

**Current Approach**: Hybrid - automated background + real-time on-demand  
**Timing**: T-24h focus, but should optimize for T-72h  
**Quality**: Real data, no mock/synthetic odds  
**Performance**: Fresh data guaranteed for every prediction request

Your question highlights a key optimization opportunity: we should proactively collect T-72h odds for maximum prediction accuracy, while maintaining real-time capability for immediate user requests.