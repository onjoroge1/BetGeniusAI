# BetGenius AI - Complete API Usage Guide

## Full URL Structure

When deployed, your complete URLs will be:
```
https://your-replit-app-name.replit.app/endpoint
```

For local development:
```
http://localhost:5000/endpoint
```

## Understanding League IDs

League IDs are standardized identifiers from the football API. Here's what each number means:

### Major European Leagues
- **39** = Premier League (England) - Arsenal, Chelsea, Liverpool, Man United, Man City
- **140** = La Liga (Spain) - Real Madrid, Barcelona, Atletico Madrid, Sevilla
- **78** = Bundesliga (Germany) - Bayern Munich, Borussia Dortmund, RB Leipzig
- **135** = Serie A (Italy) - Juventus, AC Milan, Inter Milan, Roma, Napoli
- **61** = Ligue 1 (France) - PSG, Marseille, Lyon, Monaco

### International Competitions
- **2** = UEFA Champions League - Top European club competition
- **3** = UEFA Europa League - Second-tier European competition

## Complete Workflow with Real URLs

### Step 1: Check Available Leagues
```bash
curl -H "Authorization: Bearer betgenius_secure_key_2024" \
  https://your-app-name.replit.app/leagues
```

**Response shows all leagues with their teams:**
```json
{
  "leagues": {
    "39": {
      "name": "Premier League",
      "country": "England",
      "teams": ["Arsenal", "Chelsea", "Liverpool", "Manchester United"]
    }
  }
}
```

### Step 2: Find Upcoming Matches
```bash
# Premier League matches
curl -H "Authorization: Bearer betgenius_secure_key_2024" \
  "https://your-app-name.replit.app/matches/upcoming?league_id=39&limit=10"

# La Liga matches  
curl -H "Authorization: Bearer betgenius_secure_key_2024" \
  "https://your-app-name.replit.app/matches/upcoming?league_id=140&limit=10"
```

**Response with actual match data:**
```json
{
  "matches": [
    {
      "match_id": 867946,
      "home_team": "Arsenal", 
      "away_team": "Manchester United",
      "date": "2024-12-15T15:00:00Z",
      "venue": "Emirates Stadium",
      "league": "Premier League",
      "prediction_ready": true
    }
  ],
  "usage_note": "Use match_id from any match to get predictions via POST /predict"
}
```

### Step 3: Search for Specific Teams
```bash
# Find Arsenal matches
curl -H "Authorization: Bearer betgenius_secure_key_2024" \
  "https://your-app-name.replit.app/matches/search?team=arsenal&league_id=39"

# Find Barcelona matches in La Liga
curl -H "Authorization: Bearer betgenius_secure_key_2024" \
  "https://your-app-name.replit.app/matches/search?team=barcelona&league_id=140"
```

### Step 4: Get Match Predictions
```bash
curl -X POST \
  -H "Authorization: Bearer betgenius_secure_key_2024" \
  -H "Content-Type: application/json" \
  -d '{
    "match_id": 867946,
    "include_analysis": true,
    "include_additional_markets": true
  }' \
  https://your-app-name.replit.app/predict
```

## Real Match Examples

The system processes authentic matches from current football seasons. Here are examples of what you'd see:

### Premier League (league_id=39)
- Arsenal vs Manchester United (match_id: 867946)
- Liverpool vs Chelsea (match_id: 868123)
- Manchester City vs Tottenham (match_id: 868456)

### La Liga (league_id=140)
- Real Madrid vs Barcelona (El Clasico)
- Atletico Madrid vs Sevilla
- Valencia vs Real Sociedad

### Champions League (league_id=2)
- Bayern Munich vs Paris Saint-Germain
- Manchester City vs Real Madrid
- Barcelona vs Arsenal

## How to Find Specific Matches

### Method 1: Browse by League
1. **Choose league:** Premier League = 39, La Liga = 140, etc.
2. **Get all matches:** `/matches/upcoming?league_id=39`
3. **Pick match_id** from the response
4. **Get prediction:** `/predict` with that match_id

### Method 2: Search by Team
1. **Search team:** `/matches/search?team=arsenal&league_id=39`
2. **Get filtered results** showing only Arsenal matches
3. **Use match_id** for prediction

### Method 3: Interactive Demo
Visit `/demo` in your browser for a point-and-click interface to:
- Browse leagues and teams
- Find upcoming matches
- Test predictions with sample data

## Authentication Headers

All prediction endpoints require authentication:
```bash
Authorization: Bearer betgenius_secure_key_2024
```

## Complete cURL Examples

### Get Premier League Matches
```bash
curl -H "Authorization: Bearer betgenius_secure_key_2024" \
  "https://your-app-name.replit.app/matches/upcoming?league_id=39&limit=5"
```

### Search for Manchester United Matches
```bash
curl -H "Authorization: Bearer betgenius_secure_key_2024" \
  "https://your-app-name.replit.app/matches/search?team=manchester&league_id=39"
```

### Get Match Prediction
```bash
curl -X POST \
  -H "Authorization: Bearer betgenius_secure_key_2024" \
  -H "Content-Type: application/json" \
  -d '{"match_id": 867946, "include_analysis": true}' \
  https://your-app-name.replit.app/predict
```

## Understanding the Data Flow

1. **RapidAPI Sports Data** → Real match schedules and team statistics
2. **Machine Learning Models** → Process team performance into predictions  
3. **OpenAI GPT-4o** → Generate human-readable explanations
4. **JSON Response** → Complete prediction with analysis and betting advice

The system never uses synthetic or mock data - every prediction is based on authentic football statistics from professional leagues and competitions.

## Response Time and Processing

- **Match search:** < 1 second
- **League browsing:** < 1 second  
- **Full prediction:** 7-10 seconds (includes real-time data collection + AI analysis)

The prediction time includes fetching live team statistics, running ML models, and generating AI explanations - all with authentic sports data.