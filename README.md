# BetGenius AI - Sports Prediction Backend

Africa's first AI-powered sports prediction platform that combines unified machine learning with comprehensive AI analysis to provide transparent, data-driven football betting insights.

## System Architecture

### Unified Machine Learning Model

**Production Approach:**
- **Unified Ensemble Model**: Combines Random Forest and Logistic Regression with conservative parameters
- **Realistic Accuracy**: 71.5% validated performance (addresses previous overfitting issues)
- **Robust Training**: 1,893+ matches across multiple European leagues with proper cross-validation
- **African Market Ready**: Specialized features for target markets (Kenya, Uganda, Nigeria, South Africa, Tanzania)

**Enhanced Feature Engineering:**
The system uses 10 optimized features from real sports data:

```python
# Core Team Metrics
- home_win_percentage: Historical win rate at home venue
- away_win_percentage: Historical win rate away from home
- home_form_normalized: Recent form points (normalized 0-1)
- away_form_normalized: Away team recent form (normalized 0-1)

# Derived Intelligence Features
- win_probability_difference: Absolute difference in team win rates
- form_balance: Balance between home and away team form
- combined_strength: Overall match quality indicator
- league_competitiveness: League-specific competitiveness factor
- league_home_advantage: League-specific home advantage factor
- african_market_flag: Market context indicator (0=European, 1=African)
```

### Comprehensive Analysis System

**Dual-Layer Intelligence:**
1. **ML Layer**: Unified model provides statistical foundation with 71.5% validated accuracy
2. **AI Layer**: OpenAI GPT-4o aggregates ML predictions + real-time context for holistic verdict

**Real-Time Data Integration:**
- Live injury reports and team news from RapidAPI
- Recent form analysis and tactical insights
- Head-to-head historical patterns
- Venue factors and external context
- Market sentiment and betting intelligence

**Training Dataset:**
- **Size**: 1,893+ authentic matches across 10 leagues
- **Coverage**: Premier League, La Liga, Bundesliga, Serie A, Ligue 1, Eredivisie
- **Validation**: Proper cross-validation with train/validation/test splits
- **Overfitting Prevention**: Conservative model parameters and thorough validation

**Performance Metrics:**
- **Unified Model**: 71.5% ± 1.2% realistic accuracy (cross-validated)
- **Overfitting Gap**: -0.1% (excellent generalization)
- **Data Quality**: 1,893 authentic matches (no synthetic data)
- **Market Context**: Specialized features for African and European markets

### AI Aggregation Process

**Step 1: ML Foundation**
- Generate base statistical prediction using unified model
- Extract confidence metrics and probability distributions

**Step 2: Context Aggregation**
- Collect real-time injury reports for both teams
- Analyze recent form trends and tactical setups
- Gather head-to-head historical context
- Assess venue factors and external influences

**Step 3: OpenAI Synthesis**
- Send comprehensive data package to GPT-4o
- Request holistic analysis weighing all factors
- Generate betting intelligence and risk assessment
- Provide detailed reasoning for final verdict

**Step 4: Structured Response**
- Return standardized JSON with ML + AI insights
- Include confidence breakdowns and reasoning
- Provide betting recommendations and risk analysis

## API Usage

### Authentication

All prediction endpoints require API key authentication:

```bash
Authorization: Bearer betgenius_secure_key_2024
```

### Getting Predictions for Specific Games

#### 1. Get Comprehensive Match Predictions

```bash
curl -X POST "http://localhost:8000/predict" \
  -H "Authorization: Bearer betgenius_secure_key_2024" \
  -H "Content-Type: application/json" \
  -d '{
    "match_id": 867946,
    "include_analysis": true,
    "include_additional_markets": true
  }'
```

**Comprehensive Analysis Response:**
```json
{
  "match_info": {
    "match_id": 867946,
    "home_team": "Arsenal",
    "away_team": "Manchester United",
    "venue": "Emirates Stadium",
    "date": "2024-12-15T15:00:00Z",
    "league": "Premier League",
    "match_importance": "regular_season"
  },
  "comprehensive_analysis": {
    "ml_prediction": {
      "home_win": 0.652,
      "draw": 0.248,
      "away_win": 0.100,
      "confidence": 0.847,
      "model_type": "unified_production"
    },
    "ai_verdict": {
      "recommended_outcome": "Home Win",
      "confidence_level": "High",
      "probability_assessment": {
        "home": 0.68,
        "draw": 0.22,
        "away": 0.10
      }
    },
    "detailed_reasoning": {
      "ml_model_weight": "60% - Strong statistical foundation",
      "injury_impact": "15% - Key away player injuries favor home team",
      "form_analysis": "15% - Arsenal's superior recent form",
      "tactical_factors": "5% - Home tactical setup advantage",
      "historical_context": "5% - Strong home record vs United"
    },
    "betting_intelligence": {
      "primary_bet": "Arsenal Win @ 1.65 - Strong value based on analysis",
      "value_bets": [
        "Arsenal -1 Handicap @ 2.10",
        "Over 2.5 Goals @ 1.85",
        "Both Teams Score Yes @ 1.75"
      ],
      "avoid_bets": [
        "Draw @ 3.50 - Low probability given team form",
        "United Win @ 5.00 - Injuries and away form make this risky"
      ],
      "market_analysis": {
        "best_value_market": "Asian Handicap",
        "overpriced_outcomes": ["Draw", "Away Win"],
        "underpriced_outcomes": ["Home Win", "Over Goals"]
      }
    },
    "risk_analysis": {
      "overall_risk": "Low",
      "key_risks": [
        "Arsenal complacency against struggling United",
        "United's potential counter-attacking threat"
      ],
      "upset_potential": "Low - United's away form makes upset unlikely",
      "volatility_factors": [
        "Derby match unpredictability",
        "United's inconsistent performances"
      ]
    },
    "confidence_breakdown": "High confidence (85%) based on converging factors: ML model shows 84.7% confidence, injury reports favor Arsenal, recent form strongly supports home win, tactical matchup advantages clear, and historical data confirms pattern."
  },
  "additional_markets": {
    "total_goals": {
      "over_2_5": 0.734,
      "under_2_5": 0.266,
      "over_3_5": 0.445,
      "under_3_5": 0.555
    },
    "both_teams_score": {
      "yes": 0.678,
      "no": 0.322
    },
    "asian_handicap": {
      "home_handicap": 0.713,
      "away_handicap": 0.287
    },
    "correct_score_top3": [
      {"score": "2-1", "probability": 0.156},
      {"score": "2-0", "probability": 0.134},
      {"score": "3-1", "probability": 0.089}
    ]
  },
  "analysis_metadata": {
    "analysis_type": "comprehensive_ml_plus_ai",
    "data_sources": [
      "unified_ml_model",
      "injury_reports",
      "team_news",
      "tactical_analysis",
      "historical_h2h",
      "recent_form_stats",
      "venue_factors"
    ],
    "analysis_timestamp": "2024-12-15T14:30:15.123456Z",
    "ml_model_accuracy": "71.5%",
    "ai_model": "gpt-4o",
    "processing_time": 8.245
  }
}
```

#### 2. Find Upcoming Matches

```bash
curl -X GET "http://localhost:8000/matches/upcoming?league_id=39&limit=10" \
  -H "Authorization: Bearer betgenius_secure_key_2024"
```

**League IDs:**
- 39: Premier League
- 140: La Liga
- 78: Bundesliga
- 135: Serie A
- 61: Ligue 1
- 2: Champions League

#### 3. Get Specific Match by Teams

To find a specific match, first get upcoming matches, then use the match_id:

```bash
# Step 1: Get upcoming matches
curl -X GET "http://localhost:8000/matches/upcoming?league_id=39" \
  -H "Authorization: Bearer betgenius_secure_key_2024"

# Step 2: Use match_id from response for comprehensive prediction
curl -X POST "http://localhost:8000/predict" \
  -H "Authorization: Bearer betgenius_secure_key_2024" \
  -H "Content-Type: application/json" \
  -d '{"match_id": FOUND_MATCH_ID, "include_analysis": true}'
```

### Prediction Parameters

**Required:**
- `match_id`: Integer - Unique match identifier from football API

**Optional:**
- `include_analysis`: Boolean (default: true) - Include comprehensive AI analysis
- `include_additional_markets`: Boolean (default: true) - Include over/under, BTTS, etc.

### Response Types

**Comprehensive Analysis Mode** (`include_analysis: true`):
- Returns full ML + AI aggregated analysis
- Includes injury reports, tactical insights, and betting intelligence
- Processing time: 6-12 seconds
- Recommended for informed betting decisions

**Basic ML Mode** (`include_analysis: false`):
- Returns ML predictions only
- Processing time: 1-3 seconds
- Suitable for quick statistical overview

### Key Features

#### 1. Dual-Layer Intelligence
- **Statistical Foundation**: 71.5% accurate unified ML model
- **Context Awareness**: Real-time injury reports, team news, tactical analysis
- **AI Synthesis**: OpenAI GPT-4o provides holistic verdict weighing all factors

#### 2. Betting Intelligence
- **Value Detection**: Identifies overpriced and underpriced betting markets
- **Risk Assessment**: Comprehensive risk analysis with key factors
- **Market Analysis**: Recommendations across multiple betting markets
- **Confidence Explanation**: Detailed reasoning for confidence levels

#### 3. African Market Focus
- **Target Markets**: Kenya, Uganda, Nigeria, South Africa, Tanzania
- **League Awareness**: Specialized handling for African vs European leagues
- **Market Context**: Adapts analysis style for regional betting preferences

### Error Handling

**Response Codes:**
- `200 OK`: Successful prediction with comprehensive analysis
- `401 Unauthorized`: Invalid or missing API key
- `404 Not Found`: Match ID not found or no data available
- `500 Internal Server Error`: Prediction processing failed
- `503 Service Unavailable`: External data sources temporarily unavailable

**Fallback Behavior:**
- If comprehensive analysis fails, returns basic ML prediction
- If injury data unavailable, continues with available information
- If OpenAI unavailable, provides statistical analysis only

## Development

### Setup
```bash
# Install dependencies
uv add fastapi uvicorn aiohttp pandas numpy scikit-learn python-jose requests pydantic-settings

# Set environment variables
RAPIDAPI_KEY=your_rapidapi_key
OPENAI_API_KEY=your_openai_key
BETGENIUS_API_KEY=your_secure_api_key

# Run server
python main.py
```

### Testing
```bash
# Health check
curl http://localhost:8000/health

# Interactive demo
curl http://localhost:8000/demo

# Test comprehensive prediction
curl -X POST "http://localhost:8000/predict" \
  -H "Authorization: Bearer betgenius_secure_key_2024" \
  -H "Content-Type: application/json" \
  -d '{"match_id": 867946, "include_analysis": true}'
```

## Production Deployment

The application runs on port 8000 and is production-ready for deployment to cloud platforms. Key production features:

**Architecture:**
- **Port**: 8000 (configured for Replit deployment)
- **Security**: API key authentication for all prediction endpoints
- **Performance**: Unified ML model with 6-12 second comprehensive analysis
- **Reliability**: Fallback systems for external API failures
- **Scalability**: Asynchronous request handling with FastAPI

**Environment Variables Required:**
```bash
RAPIDAPI_KEY=your_rapidapi_football_key
OPENAI_API_KEY=your_openai_api_key
BETGENIUS_API_KEY=betgenius_secure_key_2024
DATABASE_URL=postgresql://connection_string
```

**Deployment Features:**
- Comprehensive logging and error tracking
- Health check endpoints for monitoring
- Rate limiting and request validation
- Graceful degradation when external services unavailable
- Real-time data integration with fallback mechanisms

## API Integration Examples

### Frontend Integration
```javascript
// Comprehensive prediction request
const response = await fetch('https://your-domain.replit.app/predict', {
  method: 'POST',
  headers: {
    'Authorization': 'Bearer betgenius_secure_key_2024',
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    match_id: 867946,
    include_analysis: true,
    include_additional_markets: true
  })
});

const prediction = await response.json();

// Access comprehensive analysis
const mlPrediction = prediction.comprehensive_analysis.ml_prediction;
const aiVerdict = prediction.comprehensive_analysis.ai_verdict;
const bettingIntelligence = prediction.comprehensive_analysis.betting_intelligence;
```

### Mobile App Integration
```swift
// iOS Swift example
struct PredictionRequest: Codable {
    let match_id: Int
    let include_analysis: Bool
    let include_additional_markets: Bool
}

struct ComprehensiveAnalysis: Codable {
    let ml_prediction: MLPrediction
    let ai_verdict: AIVerdict
    let betting_intelligence: BettingIntelligence
    let risk_analysis: RiskAnalysis
}
```

## Performance Characteristics

**Response Times:**
- Basic ML prediction: 1-3 seconds
- Comprehensive analysis: 6-12 seconds
- Match discovery: 0.5-2 seconds

**Accuracy Metrics:**
- ML Model: 71.5% ± 1.2% (validated)
- Overfitting gap: -0.1% (excellent generalization)
- Training dataset: 1,893 authentic matches
- Cross-validation: 5-fold with temporal splits

**Data Sources:**
- RapidAPI Football: Live match data, team statistics, injury reports
- OpenAI GPT-4o: Contextual analysis and betting intelligence
- Historical database: Multi-league match results and patterns