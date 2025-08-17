# BetGenius AI - Dual-Table Population Strategy

## 🎯 Recommendation: YES - Implement Dual-Table Population

### Current Problem:
- **Scheduler**: Only populates `training_matches` (completed matches)
- **Model**: Tries to use `odds_snapshots` (empty) + `consensus_predictions` (10 records)
- **Available**: `odds_consensus` (1,000 T-72h records, unused)
- **Result**: Limited prediction accuracy due to insufficient odds timing data

### Recommended Solution: Enhanced Scheduler Architecture

## Phase 1: Immediate Enhancement (Recommended)

### Modify Scheduler to Collect Both:
1. **Phase A**: Completed matches → `training_matches` (KEEP CURRENT)
2. **Phase B**: Live upcoming matches → `odds_snapshots` (ADD NEW)

### Implementation Strategy:

#### Daily Collection Cycle (2 AM UTC):
```python
async def daily_collection_cycle(self):
    """Dual collection: completed + upcoming matches"""
    # Phase 1: Completed matches (current)
    completed_results = await self.collect_completed_matches()
    
    # Phase 2: Upcoming matches with odds (NEW)
    odds_results = await self.collect_upcoming_odds_snapshots()
    
    return {
        "completed_matches": completed_results,
        "odds_snapshots": odds_results,
        "total_new_data": completed_results + odds_results
    }
```

#### New Odds Collection Logic:
```python
async def collect_upcoming_odds_snapshots(self):
    """Collect T-48h/T-24h odds for upcoming matches"""
    upcoming_matches = await self.get_upcoming_matches(days_ahead=7)
    
    for match in upcoming_matches:
        hours_to_kickoff = self.calculate_hours_to_kickoff(match)
        
        # Collect at optimal timing windows
        if hours_to_kickoff in [72, 48, 24, 12, 6, 3, 1]:
            odds_data = await self.fetch_live_odds(match)
            await self.save_odds_snapshot(match, odds_data, hours_to_kickoff)
```

## Phase 2: Database Schema Enhancement

### Enhance `odds_snapshots` Table:
```sql
-- Ensure optimal structure for T-48h/T-24h data
ALTER TABLE odds_snapshots ADD COLUMN IF NOT EXISTS horizon_hours INTEGER;
ALTER TABLE odds_snapshots ADD COLUMN IF NOT EXISTS collection_timestamp TIMESTAMP;
ALTER TABLE odds_snapshots ADD COLUMN IF NOT EXISTS data_quality_score FLOAT;
```

### Indexing for Performance:
```sql
CREATE INDEX IF NOT EXISTS idx_odds_snapshots_timing 
ON odds_snapshots(match_id, horizon_hours, ts_snapshot);

CREATE INDEX IF NOT EXISTS idx_odds_snapshots_kickoff 
ON odds_snapshots(secs_to_kickoff, created_at);
```

## Phase 3: Model Integration Enhancement

### Update Model to Use Both Sources:
```python
def get_consensus_prediction(self, match_id: int, time_bucket: str = None):
    # Priority 1: Use odds_snapshots for T-48h/T-24h if available
    odds_data = self.get_odds_snapshots(match_id, time_bucket)
    
    if odds_data and len(odds_data) > 0:
        return self.process_odds_snapshots(odds_data)
    
    # Priority 2: Fall back to odds_consensus T-72h data
    consensus_data = self.get_odds_consensus(match_id, horizon_hours=72)
    
    if consensus_data:
        return self.process_consensus_data(consensus_data)
    
    # Priority 3: Legacy consensus_predictions (current fallback)
    return self.get_legacy_consensus(match_id, time_bucket)
```

## Expected Benefits:

### Accuracy Improvements:
- **Better Timing**: T-48h/T-24h snapshots vs current T-72h or limited data
- **Market Efficiency**: Capture optimal prediction windows
- **Data Richness**: More bookmaker sources and timing intervals

### Performance Metrics Expected:
- **Current**: Limited by 10-record `consensus_predictions`
- **With T-72h**: Can utilize 1,000-record `odds_consensus` 
- **With T-48h/T-24h**: Optimal timing windows + full market coverage

### Risk Mitigation:
- **Data Redundancy**: Multiple tables with different timing horizons
- **Graceful Fallback**: T-48h → T-72h → legacy consensus chain
- **Quality Assurance**: Data validation at each collection point

## Implementation Timeline:

### Week 1: Basic Enhancement
- Modify scheduler to collect upcoming matches
- Add T-48h/T-24h odds collection logic
- Test dual collection cycle

### Week 2: Integration
- Update model to use odds_snapshots preferentially
- Implement fallback chain (T-48h → T-72h → legacy)
- Performance testing and calibration

### Week 3: Optimization
- Fine-tune collection timing windows
- Add data quality validation
- Monitor prediction accuracy improvements

## Resource Requirements:

### API Calls:
- **Current**: ~4 leagues × daily completed matches
- **Enhanced**: +4 leagues × upcoming matches × 7 timing windows
- **Rate Limiting**: 2-second delays between calls (existing)

### Storage:
- **odds_snapshots growth**: ~100-200 records/day during active season
- **Disk usage**: Minimal increase (structured data)
- **Database performance**: Indexed queries, no impact expected

### Compute:
- **Collection overhead**: +30-60 seconds per daily cycle
- **Prediction speed**: Improved (more direct data access)
- **Background load**: Minimal impact on live API

## Bottom Line Recommendation:

**Implement dual-table population immediately** for:
1. **Better prediction accuracy** through optimal timing windows
2. **Data robustness** with multiple fallback sources  
3. **Market efficiency capture** at T-48h/T-24h intervals
4. **Minimal risk** with graceful fallback architecture

The enhanced scheduler will provide the missing T-48h/T-24h data while maintaining all current functionality for training data collection.