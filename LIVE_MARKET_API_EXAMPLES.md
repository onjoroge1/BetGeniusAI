# Live Market API - cURL Examples

## Authentication
All requests require a Bearer token in the Authorization header:
```bash
Authorization: Bearer betgenius_secure_key_2024
```

## Base URL
- **Development**: `http://localhost:8000`
- **Production**: `https://<your-replit-domain>.replit.dev`

---

## **1. Get All Live Matches (Default)**
Returns all currently live matches with full Phase 2 data (momentum, model markets).

### cURL Command (Local):
```bash
curl -H "Authorization: Bearer betgenius_secure_key_2024" \
  "http://localhost:8000/market?status=live"
```

### cURL Command (Production):
```bash
curl -H "Authorization: Bearer betgenius_secure_key_2024" \
  "https://101cf33a-9447-48b3-b3a8-432574c5b0a5-00-3sctvig41es8z.kirk.replit.dev/market?status=live"
```

---

## **2. Get Live Matches (Limited Results)**
Limit the number of matches returned.

### cURL Command:
```bash
curl -H "Authorization: Bearer betgenius_secure_key_2024" \
  "http://localhost:8000/market?status=live&limit=5"
```

---

## **3. Get Live Matches for Specific League**
Filter by league_id.

### cURL Command:
```bash
curl -H "Authorization: Bearer betgenius_secure_key_2024" \
  "http://localhost:8000/market?status=live&league_id=39&limit=10"
```

Common League IDs:
- `39`: Premier League
- `140`: La Liga
- `78`: Bundesliga
- `135`: Serie A
- `61`: Ligue 1

---

## **4. Get Specific Live Match by ID**
Retrieve a single match's complete data.

### cURL Command:
```bash
curl -H "Authorization: Bearer betgenius_secure_key_2024" \
  "http://localhost:8000/market?status=live&match_id=1374266"
```

---

## **5. Get Live Matches WITHOUT V2 Predictions**
Faster response by skipping V2 model predictions.

### cURL Command:
```bash
curl -H "Authorization: Bearer betgenius_secure_key_2024" \
  "http://localhost:8000/market?status=live&include_v2=false"
```

---

## **6. Get Upcoming Matches**
For pre-match predictions (not live yet).

### cURL Command:
```bash
curl -H "Authorization: Bearer betgenius_secure_key_2024" \
  "http://localhost:8000/market?status=upcoming&limit=20"
```

---

## **Response Format**

### Live Match Response Structure:
```json
{
  "matches": [
    {
      "match_id": 1374266,
      "status": "LIVE",
      "kickoff_at": "2025-11-01T23:00:00+00:00",
      "league": {
        "id": 128,
        "name": "Liga Profesional Argentina"
      },
      "home": {
        "name": "Independiente",
        "team_id": 309,
        "logo_url": "https://media.api-sports.io/football/teams/453.png"
      },
      "away": {
        "name": "Atletico Tucuman",
        "team_id": 42,
        "logo_url": "https://media.api-sports.io/football/teams/455.png"
      },
      "odds": {
        "books": {
          "bet365": {
            "home": 1.85,
            "draw": 3.44,
            "away": 4.54
          }
        },
        "consensus": {
          "home": 0.512,
          "draw": 0.273,
          "away": 0.215
        }
      },
      "predictions": {
        "v1": {
          "probs": {
            "home": 0.49,
            "draw": 0.28,
            "away": 0.23
          },
          "pick": "home",
          "confidence": 0.49
        },
        "v2": {
          "probs": {
            "home": 0.52,
            "draw": 0.27,
            "away": 0.21
          },
          "pick": "home",
          "confidence": 0.52
        }
      },
      "momentum": {
        "home": 51.0,
        "away": 49.0,
        "driver_summary": {
          "shots_on_target": "home",
          "possession": "home",
          "red_card": null
        },
        "minute": 15
      },
      "model_markets": {
        "updated_at": "2025-11-01T23:15:00",
        "win_draw_win": {
          "home": 0.49,
          "draw": 0.28,
          "away": 0.23
        },
        "over_under": {
          "line": 2.5,
          "over": 0.69,
          "under": 0.31
        },
        "next_goal": {
          "home": 0.53,
          "away": 0.31,
          "none": 0.16
        }
      }
    }
  ],
  "total_count": 1,
  "timestamp": "2025-11-01T23:15:30.123456"
}
```

---

## **Phase 2 Live Features**

### **1. Momentum Scores** (`momentum` object)
- Real-time 0-100 scoring for each team
- Shows which team has the momentum advantage
- `driver_summary` explains what's driving momentum:
  - `shots_on_target`: Which team has more dangerous attacks
  - `possession`: Which team controls the ball
  - `red_card`: Red card modifiers if applicable

### **2. Live Model Markets** (`model_markets` object)
- **Win/Draw/Win**: Updated probabilities based on current match state
- **Over/Under 2.5**: Live probability of total goals
- **Next Goal**: Probability of who scores next (home/away/none)

### **3. Live Match Data** (when available)
- Current score and match minute
- Recent events (goals, cards, substitutions)
- Real-time statistics (shots, possession, etc.)

---

## **Error Responses**

### Missing Authorization:
```json
{
  "detail": "Authorization header required"
}
```

### Invalid API Key:
```json
{
  "detail": "Invalid API key"
}
```

### Invalid Status Parameter:
```json
{
  "detail": "Status must be 'upcoming' or 'live'"
}
```

---

## **Testing with Python**

```python
import requests

API_KEY = "betgenius_secure_key_2024"
BASE_URL = "http://localhost:8000"

headers = {
    "Authorization": f"Bearer {API_KEY}"
}

# Get live matches
response = requests.get(
    f"{BASE_URL}/market",
    params={"status": "live", "limit": 5},
    headers=headers
)

data = response.json()
print(f"Found {data['total_count']} live matches")

for match in data['matches']:
    print(f"\n{match['home']['name']} vs {match['away']['name']}")
    
    if 'momentum' in match:
        mom = match['momentum']
        print(f"  Momentum: {mom['home']}-{mom['away']} (min {mom['minute']})")
    
    if 'model_markets' in match:
        wdw = match['model_markets']['win_draw_win']
        print(f"  Win Prob: H:{wdw['home']:.2f} D:{wdw['draw']:.2f} A:{wdw['away']:.2f}")
```

---

## **Notes**

1. **Live Status Window**: Matches are considered "live" if:
   - Kickoff was within the last 2 hours
   - Status is still "scheduled" (not marked finished)

2. **Phase 2 Data Availability**:
   - `momentum`: Updated every 60 seconds during live matches
   - `model_markets`: Generated every 60 seconds for matches with consensus predictions
   - Data may be missing if match just started or APIs are unavailable

3. **Rate Limiting**: Standard API rate limits apply (check with admin)

4. **Team Logos**: Automatically populated from API-Football when available
