# API-Football Injuries API - Access Documentation

## Overview

The API-Football Injuries endpoint provides player injury and suspension data that can enhance prediction accuracy by 1-2% through injury impact features.

---

## API Access Requirements

### FREE Plan (Current)
- **Requests:** 100/day per API
- **Endpoints:** ALL endpoints included (including Injuries)
- **Credit Card:** NOT required
- **Limitations:** Recent seasons only

### Paid Plans (If Needed)

| Plan | Requests/Day | Price/Month | Best For |
|------|-------------|-------------|----------|
| Free | 100 | $0 | Testing & development |
| Basic | 7,500 | ~$10 | Small-scale production |
| Pro | 300,000 | ~$50 | Full production |
| Enterprise | 1,500,000 | ~$100+ | High-frequency collection |

---

## Current Configuration

You already have `API_SPORTS_KEY` configured in your environment secrets, which provides access to:
- API-Football (soccer)
- API-Basketball (NBA/basketball)
- API-Baseball (MLB)
- API-Hockey (NHL)

**Current Allocation:** 75,000 requests/day each for basketball and baseball APIs.

---

## Injuries Endpoint

### Endpoint
```
GET https://v3.football.api-sports.io/injuries
```

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `fixture` | int | Optional | Fixture ID |
| `league` | int | Optional | League ID |
| `team` | int | Optional | Team ID |
| `player` | int | Optional | Player ID |
| `date` | string | Optional | YYYY-MM-DD |
| `season` | int | Optional | Season year (e.g., 2024) |

### Example Request
```bash
curl -X GET "https://v3.football.api-sports.io/injuries?fixture=1234567" \
  -H "x-rapidapi-host: v3.football.api-sports.io" \
  -H "x-apisports-key: YOUR_API_SPORTS_KEY"
```

### Response Structure
```json
{
  "response": [
    {
      "player": {
        "id": 276,
        "name": "Neymar",
        "photo": "https://..."
      },
      "team": {
        "id": 85,
        "name": "Paris Saint Germain"
      },
      "fixture": {
        "id": 1234567,
        "date": "2024-12-06T20:00:00+00:00"
      },
      "league": {
        "id": 61,
        "name": "Ligue 1"
      },
      "reason": "Knee Injury",
      "type": "Missing Fixture"
    }
  ]
}
```

---

## Integration with BetGenius

### Current Status

| Component | Status |
|-----------|--------|
| `player_injuries` table | EXISTS (0 records) |
| `team_injury_summary` table | EXISTS |
| V3 Injury Features (6) | Implemented in `v3_feature_builder.py` |
| Injury Collector Job | Scheduled every 6 hours |

### Injury Features (6)
1. `home_injury_impact` - Impact score for home team injuries
2. `away_injury_impact` - Impact score for away team injuries
3. `home_key_players_out` - Count of key players injured (home)
4. `away_key_players_out` - Count of key players injured (away)
5. `injury_advantage` - Net injury impact advantage
6. `total_squad_impact` - Combined squad availability impact

### Why No Data Yet?

The injury collector exists but returns 0 records because:

1. **API Call Needs Implementation:** The `models/sharp_book_collector.py` schedules injury collection but the actual API call to fetch player-level data may not be fully implemented.

2. **Player Data Dependency:** To calculate injury impact, you need:
   - Player market value/importance ratings
   - Position weighting (GK, DEF, MID, FWD)
   - Recent playing time data

---

## Recommended Implementation

### Step 1: Enable Injury Collection

Update the injury collector to fetch from API-Football:

```python
async def collect_injuries_for_match(match_id: int, fixture_id: int):
    """Fetch injuries for a specific fixture from API-Football"""
    
    url = f"https://v3.football.api-sports.io/injuries"
    params = {"fixture": fixture_id}
    headers = {"x-apisports-key": os.getenv("API_SPORTS_KEY")}
    
    response = requests.get(url, params=params, headers=headers)
    data = response.json()
    
    for injury in data.get('response', []):
        # Store in player_injuries table
        cursor.execute("""
            INSERT INTO player_injuries (
                match_id, player_id, player_name, team_id,
                injury_type, reason, status
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            match_id,
            injury['player']['id'],
            injury['player']['name'],
            injury['team']['id'],
            injury['type'],
            injury['reason'],
            'injured'
        ))
```

### Step 2: Calculate Impact Scores

Use player importance weighting:
- Goalkeeper: 1.5x impact
- Key midfielder/forward: 2.0x impact
- Rotation player: 0.5x impact

### Step 3: Populate team_injury_summary

Aggregate player injuries into team-level summaries for the feature builder.

---

## API Rate Management

### Current Daily Budget
- Free: 100 requests/day (testing)
- With paid plan: 7,500-300,000 requests/day

### Recommended Collection Strategy

| Match Type | Collection Frequency | Requests/Match |
|------------|---------------------|----------------|
| Upcoming (T-24h) | Once per match | 1 |
| Upcoming (T-6h) | Refresh | 1 |
| Pre-kickoff (T-1h) | Final check | 1 |

**Estimate:** ~200 matches/week × 3 checks = 600 requests/week = ~100/day

This fits within the FREE tier for development/testing.

---

## Summary

| Item | Status | Action |
|------|--------|--------|
| API Access | ✅ Have `API_SPORTS_KEY` | Use existing key |
| Injuries Endpoint | ✅ Available on all plans | Included in free tier |
| Player Injuries Table | ✅ Schema exists | Populate with API data |
| Feature Builder | ✅ V3 has injury features | Will work once data flows |
| Cost | $0 for testing | Upgrade if >100 req/day needed |

**No premium API is required for basic injury features.** The existing `API_SPORTS_KEY` provides access to the Injuries endpoint on all plans including free.
