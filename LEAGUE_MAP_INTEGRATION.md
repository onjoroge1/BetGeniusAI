# League Map Integration - Enhanced Data Collection

## Implementation Summary

### Problem Solved:
Previously, the scheduler was hardcoded to collect from only 4 leagues:
```python
self.major_leagues = [39, 140, 78, 135]  # Hardcoded
```

### Solution Implemented:
Now uses the `league_map` table to dynamically determine which leagues to collect:

```python
def _get_configured_leagues(self) -> List[int]:
    """Get list of league IDs from league_map table"""
    cursor.execute("SELECT league_id FROM league_map ORDER BY league_id")
    league_ids = [row[0] for row in cursor.fetchall()]
    return league_ids
```

### Configured Leagues (from league_map):
- **39**: Premier League (EPL)
- **61**: Ligue 1 (France) 
- **78**: Bundesliga (Germany)
- **88**: Eredivisie (Netherlands)
- **135**: Serie A (Italy)
- **140**: La Liga (Spain)

### Benefits:
1. **Scalable**: Add new leagues by inserting into league_map table
2. **Centralized**: One source of truth for supported leagues
3. **Flexible**: No code changes needed to modify league coverage
4. **Comprehensive**: Now collecting from 6 leagues instead of 4

### Enhanced Collection Results:

```
📋 Found 6 configured leagues in league_map: [39, 61, 78, 88, 135, 140]
🔍 Checking upcoming matches for Premier League (ID: 39)
🔍 Checking upcoming matches for Ligue 1 (ID: 61)
🔍 Checking upcoming matches for Bundesliga (ID: 78)
🔍 Checking upcoming matches for Eredivisie (ID: 88)
🔍 Checking upcoming matches for Serie A (ID: 135)
🔍 Checking upcoming matches for La Liga (ID: 140)
```

### Dual Collection Enhancement:
- **Phase A**: Now collects completed matches from all 6 leagues → training_matches
- **Phase B**: Now collects upcoming odds from all 6 leagues → odds_snapshots

### Fallback Protection:
```python
if not configured_leagues:
    logger.warning("No leagues found in league_map table, using default leagues")
    configured_leagues = [39, 140, 78, 135]  # Fallback
```

This ensures the system continues working even if league_map is empty or unavailable.

## Current Collection Status:
- **Training matches**: Successfully collecting from all configured leagues
- **Odds snapshots**: Framework ready for all configured leagues
- **League coverage**: Expanded from 4 to 6 major European leagues
- **Data source**: Dynamic and configurable via league_map table