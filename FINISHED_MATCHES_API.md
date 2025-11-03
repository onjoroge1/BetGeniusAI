# Finished Matches API Guide

## Overview
Query completed matches with final scores, results, and compare against model predictions.

## Endpoint
```
GET /market?status=finished
```

## Query Parameters
- `status` (required): Set to `"finished"`
- `match_id` (optional): Query specific match
- `league_id` (optional): Filter by league
- `limit` (optional): Number of results (default: 100)
- `include_v2` (optional): Include V2 model predictions (default: true)

## Example Requests

### 1. Get Specific Finished Match
```bash
curl -H "Authorization: Bearer betgenius_secure_key_2024" \
  "http://localhost:8000/market?status=finished&match_id=1482409"
```

**Response:**
```json
{
  "matches": [
    {
      "match_id": "1482409",
      "home": {
        "name": "Austin",
        "team_id": 44,
        "logo_url": "https://..."
      },
      "away": {
        "name": "Los Angeles FC",
        "team_id": 373,
        "logo_url": "https://..."
      },
      "league": {
        "id": 253,
        "name": "Major League Soccer"
      },
      "kickoff_at": "2025-11-03T01:45:00+00:00",
      "final_result": {
        "score": {
          "home": 1,
          "away": 4
        },
        "outcome": "A",
        "outcome_text": "Away Win"
      },
      "odds": {
        "books": [...],
        "novig_current": {
          "home": 0.342,
          "draw": 0.274,
          "away": 0.384
        }
      },
      "models": {
        "v1_consensus": {
          "probs": {
            "home": 0.342,
            "draw": 0.274,
            "away": 0.384
          },
          "pick": "away",
          "confidence": 0.533
        },
        "v2_lightgbm": {
          "probs": {...},
          "pick": "away",
          "confidence": 0.545
        }
      }
    }
  ],
  "total_count": 1
}
```

### 2. List Recent Finished Matches
```bash
curl -H "Authorization: Bearer betgenius_secure_key_2024" \
  "http://localhost:8000/market?status=finished&limit=10"
```

### 3. Filter by League
```bash
curl -H "Authorization: Bearer betgenius_secure_key_2024" \
  "http://localhost:8000/market?status=finished&league_id=39&limit=20"
```

## Use Cases

### 1. Model Performance Analysis
Compare model predictions against actual results:
```python
import requests

response = requests.get(
    "http://localhost:8000/market",
    params={"status": "finished", "limit": 100},
    headers={"Authorization": "Bearer betgenius_secure_key_2024"}
)

data = response.json()
correct = 0
total = len(data["matches"])

for match in data["matches"]:
    if "final_result" in match and "models" in match:
        actual = match["final_result"]["outcome"]
        predicted = match["models"]["v1_consensus"]["pick"]
        
        # Map prediction to outcome code
        prediction_map = {"home": "H", "draw": "D", "away": "A"}
        if prediction_map.get(predicted) == actual:
            correct += 1

accuracy = (correct / total * 100) if total > 0 else 0
print(f"Model Accuracy: {accuracy:.1f}% ({correct}/{total})")
```

### 2. Retrieve Match Stats for Analysis
```python
match_id = "1482409"
response = requests.get(
    f"http://localhost:8000/market",
    params={"status": "finished", "match_id": match_id},
    headers={"Authorization": "Bearer betgenius_secure_key_2024"}
)

match = response.json()["matches"][0]
print(f"{match['home']['name']} vs {match['away']['name']}")
print(f"Final Score: {match['final_result']['score']['home']}-{match['final_result']['score']['away']}")
print(f"Result: {match['final_result']['outcome_text']}")
```

### 3. Closing Line Value (CLV) Analysis
```python
for match in data["matches"]:
    result = match.get("final_result", {})
    odds = match.get("odds", {}).get("novig_current", {})
    v1 = match.get("models", {}).get("v1_consensus", {})
    
    if result and odds and v1:
        pick = v1["pick"]
        model_prob = v1["probs"][pick]
        market_prob = odds[pick]
        
        # Positive CLV = model found value
        clv = model_prob - market_prob
        
        actual = result["outcome"]
        won = (pick == "home" and actual == "H") or \
              (pick == "draw" and actual == "D") or \
              (pick == "away" and actual == "A")
        
        print(f"Match {match['match_id']}: CLV={clv:+.3f}, Won={won}")
```

## Response Fields

### Final Result Object
```json
{
  "final_result": {
    "score": {
      "home": 1,    // Final home score
      "away": 4     // Final away score
    },
    "outcome": "A",           // H/D/A
    "outcome_text": "Away Win"  // Human-readable
  }
}
```

### Outcome Codes
- `H` = Home Win
- `D` = Draw
- `A` = Away Win

## Notes

1. **Cleanup Policy**: Live match stats are deleted after 4 hours, so finished matches won't have `live_data` or `momentum` fields.

2. **Historical Data**: Finished matches retain:
   - Final scores from `match_results` table
   - Pre-match odds from `odds_snapshots`
   - Model predictions from `consensus_predictions`

3. **Performance**: Fast path optimization for single match queries (<100ms)

4. **Data Availability**: Only matches with results in `match_results` table will have `final_result` field.

## Error Handling

### Match Not Found
```json
{
  "matches": [],
  "total_count": 0,
  "message": "No matches found"
}
```

### Invalid Status
```json
{
  "detail": "Status must be 'upcoming', 'live', or 'finished'"
}
```

## Integration with Other Endpoints

### Compare with Live Data
1. Track match during live play: `GET /market?status=live&match_id=X`
2. Review final result: `GET /market?status=finished&match_id=X`

### WebSocket → Finished Match
After WebSocket connection closes (match ends):
```javascript
ws.onclose = () => {
  // Fetch final result
  fetch(`/market?status=finished&match_id=${matchId}`)
    .then(res => res.json())
    .then(data => {
      const result = data.matches[0].final_result;
      console.log(`Final: ${result.score.home}-${result.score.away}`);
    });
};
```
