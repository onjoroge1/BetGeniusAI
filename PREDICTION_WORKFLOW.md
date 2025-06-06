# BetGenius AI - Complete Prediction Workflow Guide

## Overview

BetGenius AI provides intelligent football match predictions by combining real-time sports data, machine learning models, and AI explanations. This guide demonstrates the complete workflow for getting predictions for specific games.

## Authentication

All prediction endpoints require API key authentication:
```bash
Authorization: Bearer betgenius_secure_key_2024
```

## Step-by-Step Workflow

### Step 1: Find Available Matches

#### Option A: Get Upcoming Matches by League
```bash
curl -X GET "http://localhost:5000/matches/upcoming?league_id=39&limit=10" \
  -H "Authorization: Bearer betgenius_secure_key_2024"
```

**League IDs:**
- 39: Premier League (England)
- 140: La Liga (Spain)
- 78: Bundesliga (Germany)
- 135: Serie A (Italy)
- 61: Ligue 1 (France)
- 2: UEFA Champions League
- 3: UEFA Europa League

#### Option B: Search for Specific Team
```bash
curl -X GET "http://localhost:5000/matches/search?team=manchester&league_id=39" \
  -H "Authorization: Bearer betgenius_secure_key_2024"
```

**Response Format:**
```json
{
  "matches": [
    {
      "match_id": 867946,
      "home_team": "Manchester United",
      "away_team": "Arsenal",
      "date": "2024-12-15T15:00:00Z",
      "venue": "Old Trafford",
      "league": "Premier League",
      "prediction_ready": true
    }
  ],
  "total": 1,
  "usage_note": "Use match_id from any match to get predictions via POST /predict"
}
```

### Step 2: Get Match Prediction

Use the `match_id` from Step 1 to get comprehensive predictions:

```bash
curl -X POST "http://localhost:5000/predict" \
  -H "Authorization: Bearer betgenius_secure_key_2024" \
  -H "Content-Type: application/json" \
  -d '{
    "match_id": 867946,
    "include_analysis": true,
    "include_additional_markets": true
  }'
```

**Complete Response Example:**
```json
{
  "match_info": {
    "match_id": 867946,
    "home_team": "Manchester United",
    "away_team": "Arsenal",
    "venue": "Old Trafford",
    "date": "2024-12-15T15:00:00Z",
    "league": "Premier League"
  },
  "predictions": {
    "home_win": 0.423,
    "draw": 0.267,
    "away_win": 0.310,
    "confidence": 0.784,
    "recommended_bet": "Home Team Win"
  },
  "analysis": {
    "explanation": "Manchester United are slight favorites at home despite Arsenal's strong away form. United's home advantage and recent improvements in defense give them the edge in this closely contested match.",
    "confidence_factors": [
      "Manchester United home advantage (64% win rate at Old Trafford)",
      "Recent defensive improvements (1.2 goals conceded per game last 5)",
      "Arsenal's away form shows vulnerability (only 45% away win rate)"
    ],
    "betting_recommendations": {
      "best_value": "Manchester United Win",
      "safest_bet": "Both Teams to Score",
      "avoid": "Draw bet due to both teams' attacking potential"
    },
    "risk_assessment": "Medium risk based on 78.4% model confidence",
    "value_analysis": "Manchester United offers good value at current odds given their home form",
    "key_stats": [
      "Home goals per game: 1.9",
      "Away goals per game: 1.7", 
      "Model confidence: 78%"
    ]
  },
  "additional_markets": {
    "total_goals": {
      "over_2_5": 0.643,
      "under_2_5": 0.357
    },
    "both_teams_score": {
      "yes": 0.712,
      "no": 0.288
    },
    "asian_handicap": {
      "home_handicap": 0.567,
      "away_handicap": 0.433
    }
  },
  "processing_time": 8.234,
  "timestamp": "2024-12-15T14:30:15.123456"
}
```

## Understanding the Prediction Output

### Match Predictions
- **home_win/draw/away_win**: Probability of each outcome (0-1 scale)
- **confidence**: How certain the model is (0.3-0.99 scale)
- **recommended_bet**: Suggested betting action based on probabilities and confidence

### AI Analysis
- **explanation**: Plain-language reasoning for the prediction
- **confidence_factors**: Key statistics supporting the prediction
- **betting_recommendations**: Specific betting advice
- **risk_assessment**: Risk level evaluation
- **value_analysis**: Betting value assessment

### Additional Markets
- **total_goals**: Over/Under 2.5 goals probabilities
- **both_teams_score**: Probability both teams will score
- **asian_handicap**: Handicap betting probabilities

## Real-Time Data Integration

Each prediction uses authentic, current data:

### Team Statistics
- Season-long performance metrics
- Home/away specific statistics
- Goal scoring and defensive records
- Win/loss percentages

### Recent Form
- Last 5-10 match results
- Recent goal scoring patterns
- Momentum indicators
- Performance trends

### Head-to-Head History
- Historical meetings between teams
- Past results and goal patterns
- Venue-specific performance
- Recent encounters emphasis

### Context Factors
- Current injury reports
- Player availability
- Venue information
- Match importance

## Confidence Levels Guide

### High Confidence (80%+)
- Strong statistical support
- Clear favorite identified
- Models in agreement
- Complete data available

**Action:** Confident betting recommended

### Medium Confidence (60-80%)
- Moderate statistical support
- Some uncertainty in outcome
- Partial model agreement
- Good data quality

**Action:** Cautious betting with smaller stakes

### Low Confidence (Below 60%)
- Limited statistical support
- High uncertainty
- Model disagreement
- Incomplete data

**Action:** Avoid betting or wait for more information

## Error Handling

### Common Issues

**401 Unauthorized**
```json
{"detail": "Invalid API key"}
```
*Solution: Check API key in Authorization header*

**404 Not Found**
```json
{"detail": "Match 123456 not found or no data available"}
```
*Solution: Verify match_id from upcoming matches endpoint*

**500 Internal Server Error**
```json
{"detail": "Internal server error: prediction processing failed"}
```
*Solution: Check match_id validity or try again later*

## Best Practices

### For Developers
1. Always check upcoming matches first to get valid match_ids
2. Handle API responses with proper error checking
3. Implement rate limiting to respect API quotas
4. Cache responses appropriately for better performance

### For Bettors
1. Only bet on matches with 70%+ confidence
2. Compare AI recommendations with multiple bookmakers
3. Consider both main prediction and additional markets
4. Use analysis explanations to understand reasoning
5. Set betting limits and stick to them

## Integration Examples

### Python Integration
```python
import requests

def get_match_prediction(match_id, api_key):
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json'
    }
    
    payload = {
        'match_id': match_id,
        'include_analysis': True,
        'include_additional_markets': True
    }
    
    response = requests.post(
        'http://localhost:5000/predict',
        headers=headers,
        json=payload
    )
    
    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"Prediction failed: {response.status_code}")

# Usage
prediction = get_match_prediction(867946, "betgenius_secure_key_2024")
print(f"Recommended bet: {prediction['predictions']['recommended_bet']}")
print(f"Confidence: {prediction['predictions']['confidence']:.1%}")
```

### JavaScript Integration
```javascript
async function getMatchPrediction(matchId, apiKey) {
    const response = await fetch('http://localhost:5000/predict', {
        method: 'POST',
        headers: {
            'Authorization': `Bearer ${apiKey}`,
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            match_id: matchId,
            include_analysis: true,
            include_additional_markets: true
        })
    });
    
    if (!response.ok) {
        throw new Error(`Prediction failed: ${response.status}`);
    }
    
    return await response.json();
}

// Usage
getMatchPrediction(867946, "betgenius_secure_key_2024")
    .then(prediction => {
        console.log('Recommended bet:', prediction.predictions.recommended_bet);
        console.log('Confidence:', Math.round(prediction.predictions.confidence * 100) + '%');
    })
    .catch(error => console.error('Error:', error));
```

## Support

For technical issues or questions about the prediction system:
- Check API documentation at `/docs`
- Test functionality at `/demo`
- Verify system health at `/health`

The BetGenius AI system processes authentic sports data to provide transparent, intelligent betting insights powered by machine learning and AI explanations.