# Betting Intelligence API

## Overview
BetGenius AI's Betting Intelligence system combines ML-based match predictions with closing line value (CLV) calculations and Kelly Criterion bet sizing to provide actionable betting opportunities. The system identifies matches where our models have an edge over bookmaker odds and recommends optimal bet sizing based on confidence and bankroll management.

## Key Concepts

### Closing Line Value (CLV)
CLV measures the difference between our model's predicted probabilities and bookmaker closing odds. Positive CLV indicates our model sees value that the market doesn't, representing a potential betting edge.

**Formula**: `CLV = (Model Probability) - (1 / Decimal Odds)`

**Example**:
- Model predicts Home Win: 45%
- Closing odds for Home Win: 2.10
- Implied probability: 1/2.10 = 47.6%
- CLV = 0.45 - 0.476 = -0.026 (-2.6%)

### Kelly Criterion
The Kelly Criterion calculates the optimal fraction of your bankroll to bet based on the edge and odds. It maximizes long-term growth while managing risk.

**Formula**: `Kelly% = (bp - q) / b`
- b = decimal odds - 1
- p = model probability
- q = 1 - p

**Example**:
- Edge: 5%, Odds: 2.50
- Kelly = (1.5 × 0.35 - 0.65) / 1.5 = 2.5%
- For $1000 bankroll: Recommended bet = $25

### Edge Calculation
Edge represents expected value - how much profit you expect per dollar bet over the long run.

**Formula**: `Edge = (Model Probability × Decimal Odds) - 1`

**Example**:
- Model: 40%, Odds: 2.75
- Edge = (0.40 × 2.75) - 1 = 0.10 (10%)

## API Endpoints

### 1. Market Board with Betting Intelligence
`GET /market?status={status}&v2_include=true`

Returns match predictions with embedded betting intelligence for each match.

#### Status Filters
- `status=upcoming` - Future matches with pre-match edge
- `status=live` - In-play matches with real-time edge vs closing lines
- `status=finished` - Completed matches (no betting intelligence)

#### Request Examples

```bash
# Upcoming matches with betting intelligence
curl -H "Authorization: Bearer betgenius_secure_key_2024" \
  "https://your-domain.com/market?status=upcoming&limit=10&v2_include=true"

# Live matches with in-play opportunities
curl -H "Authorization: Bearer betgenius_secure_key_2024" \
  "https://your-domain.com/market?status=live&limit=5"

# Filter by league
curl -H "Authorization: Bearer betgenius_secure_key_2024" \
  "https://your-domain.com/market?status=upcoming&league_id=39&limit=20"
```

#### Response Structure

```json
{
  "matches": [
    {
      "match_id": 1451083,
      "home": {"team_id": 123, "name": "Chelsea", "logo_url": "..."},
      "away": {"team_id": 456, "name": "Arsenal", "logo_url": "..."},
      "league": {"league_id": 39, "name": "Premier League", "logo_url": "..."},
      "kickoff_time": "2025-11-09T15:00:00Z",
      "v1_prediction": {
        "probabilities": {"home": 0.45, "draw": 0.28, "away": 0.27},
        "recommended_bet": "home"
      },
      "v2_prediction": {
        "probabilities": {"home": 0.48, "draw": 0.26, "away": 0.26},
        "recommended_bet": "home",
        "confidence": 0.72
      },
      "betting_intelligence": {
        "clv": {
          "home": 0.052,
          "draw": -0.015,
          "away": -0.031
        },
        "best_bet": {
          "pick": "home",
          "edge": 0.052,
          "recommendation": "STRONG BET"
        },
        "kelly_sizing": {
          "full_kelly": 0.034,
          "fractional_kelly": 0.017,
          "recommended_stake_pct": 1.7,
          "max_stake_pct": 3.0
        }
      },
      "books": [
        {
          "bookmaker": "bet365",
          "prices": {"home": 2.10, "draw": 3.40, "away": 3.60},
          "timestamp": "2025-11-09T14:30:00Z"
        }
      ]
    }
  ],
  "total_count": 39,
  "pagination": {"limit": 10, "offset": 0}
}
```

### 2. Curated Betting Opportunities
`GET /betting-intelligence`

Returns only matches with significant betting edge, filtered and sorted for quick decision-making.

#### Query Parameters
- `min_edge` - Minimum edge threshold (default: 0.02 = 2%)
- `model` - Model preference: `v1`, `v2`, or `best` (default)
- `status` - Match status: `upcoming` or `live` (default: upcoming)
- `league_id` - Filter by specific league
- `sort` - Sort by: `edge` (default), `kelly`, or `clv`
- `limit` - Max results (default: 20)

#### Request Examples

```bash
# High-edge opportunities (5%+)
curl -H "Authorization: Bearer betgenius_secure_key_2024" \
  "https://your-domain.com/betting-intelligence?min_edge=0.05&limit=5"

# Live betting opportunities
curl -H "Authorization: Bearer betgenius_secure_key_2024" \
  "https://your-domain.com/betting-intelligence?status=live&min_edge=0.03"

# V2 premium model only, sorted by Kelly
curl -H "Authorization: Bearer betgenius_secure_key_2024" \
  "https://your-domain.com/betting-intelligence?model=v2&sort=kelly&limit=10"

# Specific league with low edge threshold
curl -H "Authorization: Bearer betgenius_secure_key_2024" \
  "https://your-domain.com/betting-intelligence?league_id=39&min_edge=0.01"
```

#### Response Structure

```json
{
  "opportunities": [
    {
      "match_id": 1451083,
      "home_team": "Chelsea",
      "away_team": "Arsenal",
      "league": "Premier League",
      "kickoff_time": "2025-11-09T15:00:00Z",
      "model_used": "v2",
      "betting_intelligence": {
        "clv": {"home": 0.068, "draw": -0.012, "away": -0.045},
        "best_bet": {
          "pick": "home",
          "edge": 0.068,
          "recommendation": "STRONG BET"
        },
        "kelly_sizing": {
          "full_kelly": 0.045,
          "fractional_kelly": 0.022,
          "recommended_stake_pct": 2.2,
          "max_stake_pct": 3.0
        }
      },
      "best_odds": {
        "home": 2.10,
        "draw": 3.40,
        "away": 3.60,
        "bookmaker": "bet365"
      }
    }
  ],
  "total_count": 7,
  "filters": {
    "min_edge": 0.05,
    "model": "best",
    "status": "upcoming"
  }
}
```

## Response Fields Explained

### betting_intelligence Object

| Field | Type | Description |
|-------|------|-------------|
| `clv.home` | float | CLV for home win (-1.0 to 1.0) |
| `clv.draw` | float | CLV for draw |
| `clv.away` | float | CLV for away win |
| `best_bet.pick` | string | "home", "draw", or "away" |
| `best_bet.edge` | float | Expected value per dollar (0.0 to 1.0+) |
| `best_bet.recommendation` | string | "STRONG BET", "VALUE BET", or "PASS" |
| `kelly_sizing.full_kelly` | float | Full Kelly percentage (0.0 to 1.0) |
| `kelly_sizing.fractional_kelly` | float | Half Kelly (recommended, 0.0 to 0.5) |
| `kelly_sizing.recommended_stake_pct` | float | Percentage of bankroll (0.0 to 100.0) |
| `kelly_sizing.max_stake_pct` | float | Maximum allowed stake (3.0%) |

### Recommendation Thresholds

| Recommendation | Edge Threshold | Kelly% Threshold |
|----------------|----------------|------------------|
| STRONG BET | ≥ 5% | ≥ 2% |
| VALUE BET | ≥ 2% | ≥ 0.5% |
| PASS | < 2% | < 0.5% |

## Usage Examples

### Example 1: Finding Today's Best Bets

```python
import requests

API_KEY = "betgenius_secure_key_2024"
BASE_URL = "https://your-domain.com"

# Get high-value opportunities
response = requests.get(
    f"{BASE_URL}/betting-intelligence",
    headers={"Authorization": f"Bearer {API_KEY}"},
    params={"min_edge": 0.04, "limit": 10, "sort": "edge"}
)

opportunities = response.json()["opportunities"]

for opp in opportunities:
    bi = opp["betting_intelligence"]
    best = bi["best_bet"]
    kelly = bi["kelly_sizing"]
    
    print(f"{opp['home_team']} vs {opp['away_team']}")
    print(f"  Pick: {best['pick'].upper()} @ {best['edge']*100:.1f}% edge")
    print(f"  Stake: {kelly['recommended_stake_pct']:.1f}% of bankroll")
    print(f"  {best['recommendation']}")
    print()
```

### Example 2: Live Betting Monitor

```python
# Monitor live matches for in-play opportunities
response = requests.get(
    f"{BASE_URL}/betting-intelligence",
    headers={"Authorization": f"Bearer {API_KEY}"},
    params={"status": "live", "min_edge": 0.03}
)

for opp in response.json()["opportunities"]:
    bi = opp["betting_intelligence"]
    print(f"🔴 LIVE: {opp['home_team']} vs {opp['away_team']}")
    print(f"   Edge: {bi['best_bet']['edge']*100:.1f}% on {bi['best_bet']['pick']}")
```

### Example 3: Kelly Criterion Bankroll Management

```python
BANKROLL = 1000  # $1000 starting bankroll

response = requests.get(
    f"{BASE_URL}/betting-intelligence",
    headers={"Authorization": f"Bearer {API_KEY}"},
    params={"min_edge": 0.02}
)

for opp in response.json()["opportunities"]:
    kelly = opp["betting_intelligence"]["kelly_sizing"]
    stake_amount = BANKROLL * (kelly["recommended_stake_pct"] / 100)
    
    print(f"{opp['home_team']} vs {opp['away_team']}")
    print(f"  Recommended bet: ${stake_amount:.2f}")
    print(f"  ({kelly['recommended_stake_pct']:.1f}% of ${BANKROLL})")
```

## Best Practices

### 1. Edge Thresholds
- **Conservative**: min_edge=0.05 (5%+) - Only highest confidence bets
- **Moderate**: min_edge=0.03 (3%+) - Balanced approach
- **Aggressive**: min_edge=0.02 (2%+) - More opportunities, higher variance

### 2. Kelly Sizing
- Always use **fractional Kelly** (half Kelly recommended)
- Never exceed the `max_stake_pct` (3% hard cap)
- Reduce stakes during losing streaks
- The system automatically caps Kelly at 3% for bankroll protection

### 3. Model Selection
- **V2 Model**: Higher accuracy, fewer matches (SELECT tier)
- **V1 Model**: Broader coverage, consistent performance
- **Best (Auto)**: System chooses V2 when qualified, V1 otherwise

### 4. CLV Interpretation
- **Positive CLV (>0)**: Model sees value vs market
- **High CLV (>5%)**: Significant disagreement - verify match context
- **Negative CLV (<0)**: Market disagrees - consider avoiding

### 5. Live Betting
- CLV calculated vs **closing** odds (not current live odds)
- Edge considers momentum and match state
- Higher variance - use lower stakes

## Technical Notes

### Data Freshness
- Odds updated every 60 seconds
- Predictions refreshed when new odds available
- Live data updated every 60 seconds during matches

### Calculation Methods
- **CLV**: Model probability - Implied probability
- **Edge**: (Model prob × Decimal odds) - 1
- **Kelly**: (bp - q) / b, capped at 3%
- **Fractional Kelly**: 0.5 × Full Kelly (recommended)

### Missing Data Handling
- If no odds available: betting_intelligence = null
- If no model prediction: betting_intelligence = null
- If CLV < 0 for all outcomes: best_bet may still suggest a pick with smallest loss

### Rate Limits
- 100 requests per minute per API key
- Use pagination for large result sets

## Error Handling

### Common Errors

**No betting intelligence field**:
- Match has no predictions yet
- Odds data not available
- Match too far in future (>7 days)

**Empty opportunities list**:
- No matches meet min_edge threshold
- Try lowering min_edge or checking different leagues

**Calculation failed**:
- Odds data incomplete or invalid
- Model probabilities don't sum to 1.0
- System logs warning, match excluded from results

## Support

For issues or questions:
- Check logs for "Betting intelligence calc failed" warnings
- Verify odds data available for target matches
- Confirm model predictions exist for the match
- Review CLV values for reasonableness (-100% to +100%)

## Changelog

**v1.0.0** - November 2025
- Initial release
- CLV calculation for all 1X2 markets
- Kelly Criterion bet sizing with fractional Kelly default
- Curated opportunities endpoint with filtering
- Support for upcoming and live match betting intelligence
