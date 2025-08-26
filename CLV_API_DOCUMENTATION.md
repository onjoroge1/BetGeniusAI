# CLV API Documentation

## Overview

The CLV (Closing Line Value) API provides real-time monitoring and analysis of betting opportunities based on authentic bookmaker odds. CLV fluctuates constantly as market conditions change, and positive CLV indicates when users should consider placing bets.

## Key Concepts

### CLV Fluctuation Pattern
CLV is **dynamic** and changes constantly:
- **Positive CLV (+2% to +7%)**: BET - Market offering better odds than consensus
- **Negative CLV (-2% to -5%)**: AVOID - Market offering worse odds than consensus  
- **Neutral CLV (-1% to +1%)**: MONITOR - Wait for better opportunities

### When to Bet Based on CLV
- **+3% or higher**: Strong betting opportunity (especially with High confidence)
- **+2% to +3%**: Good betting opportunity (check confidence level)
- **0% to +2%**: Monitor for improvement
- **Negative CLV**: Avoid betting

## API Endpoints

### 1. Match-Specific CLV Analysis
```
GET /clv/match/{match_id}
```
**Description**: Get comprehensive CLV analysis for a specific match

**Response Example**:
```json
{
  "match_id": 1378978,
  "home_team": "Leeds United",
  "away_team": "Everton", 
  "league_id": 39,
  "opportunities": [
    {
      "match_id": 1378978,
      "outcome": "H",
      "best_odds": 2.36,
      "best_bookmaker": 937,
      "market_odds": 2.30,
      "clv_percentage": 2.61,
      "confidence_level": "High",
      "time_to_kickoff_hours": 2.8,
      "recommendation": "BET - Good CLV with early timing",
      "created_at": "2025-08-26T14:30:00"
    }
  ],
  "overall_recommendation": "CONSIDER - 1 positive CLV opportunities available"
}
```

### 2. Live CLV Alerts
```
GET /clv/alerts?league_ids=39,140&min_clv=2.0
```
**Description**: Get live CLV alerts for active matches

**Parameters**:
- `league_ids` (optional): Comma-separated league IDs (e.g., "39,140,78")
- Returns alerts for all leagues if not specified

**Response Example**:
```json
{
  "status": "success",
  "alerts": [
    {
      "match_id": 1378978,
      "outcome": "H",
      "best_odds": 2.36,
      "best_bookmaker": 937,
      "market_odds": 2.25,
      "clv_percentage": 4.89,
      "confidence_level": "High",
      "recommendation": "STRONG BET - High CLV with high confidence"
    }
  ],
  "count": 1,
  "timestamp": "2025-08-26T14:30:00"
}
```

### 3. CLV Dashboard
```
GET /clv/dashboard
```
**Description**: Get comprehensive dashboard data for CLV monitoring

**Response Example**:
```json
{
  "summary": {
    "active_matches": 23,
    "positive_clv_opportunities": 8,
    "significant_movements_6h": 12,
    "bookmakers_tracked": 88
  },
  "live_alerts": [...],
  "top_bookmakers": [
    {
      "book_id": 148,
      "avg_odds": 13.367,
      "odds_count": 69,
      "matches": 23,
      "is_premium": true
    }
  ],
  "last_updated": "2025-08-26T14:30:00"
}
```

### 4. Filtered CLV Opportunities
```
GET /clv/opportunities?min_clv=3.0&confidence=High&league_ids=39,140
```
**Description**: Get CLV opportunities with specific filtering criteria

**Parameters**:
- `min_clv`: Minimum CLV percentage (default: 2.0)
- `confidence`: Filter by confidence level ("High", "Medium", "Low")
- `league_ids`: Comma-separated league IDs

## Frontend Integration Guide

### Real-Time CLV Monitoring
```javascript
// Poll for live alerts every 30 seconds
async function monitorCLV() {
    try {
        const response = await fetch('/clv/alerts', {
            headers: {
                'Authorization': 'Bearer betgenius_secure_key_2024'
            }
        });
        
        const data = await response.json();
        
        // Process alerts
        data.alerts.forEach(alert => {
            if (alert.clv_percentage >= 3.0 && alert.confidence_level === 'High') {
                showBettingAlert(alert);
            }
        });
        
    } catch (error) {
        console.error('CLV monitoring error:', error);
    }
}

// Start monitoring
setInterval(monitorCLV, 30000);
```

### CLV Opportunity Display
```javascript
function displayCLVOpportunity(opportunity) {
    const clvClass = opportunity.clv_percentage >= 3 ? 'clv-high' : 'clv-medium';
    
    return `
        <div class="clv-opportunity ${clvClass}">
            <h4>${opportunity.match_id} - ${opportunity.outcome}</h4>
            <div class="clv-details">
                <span class="clv-value">+${opportunity.clv_percentage.toFixed(2)}% CLV</span>
                <span class="confidence">${opportunity.confidence_level} Confidence</span>
                <span class="recommendation">${opportunity.recommendation}</span>
            </div>
            <div class="odds-comparison">
                Best: ${opportunity.best_odds} vs Market: ${opportunity.market_odds}
            </div>
            <button onclick="placeBet(${opportunity.match_id}, '${opportunity.outcome}')">
                Place Bet
            </button>
        </div>
    `;
}
```

### Match-Specific CLV Analysis
```javascript
async function getMatchCLV(matchId) {
    const response = await fetch(`/clv/match/${matchId}`, {
        headers: {
            'Authorization': 'Bearer betgenius_secure_key_2024'
        }
    });
    
    const analysis = await response.json();
    
    // Display CLV analysis for each outcome
    analysis.opportunities.forEach(opp => {
        displayCLVAnalysis(opp);
    });
    
    // Show overall recommendation
    showOverallRecommendation(analysis.overall_recommendation);
}
```

## CLV Decision Matrix

| CLV Range | Confidence | Action | Example |
|-----------|------------|---------|---------|
| +5% or higher | High | STRONG BET | Best odds 2.50 vs market 2.38 |
| +3% to +5% | High/Medium | BET | Best odds 2.30 vs market 2.23 |
| +2% to +3% | High | BET | Best odds 2.20 vs market 2.16 |
| +2% to +3% | Medium | CONSIDER | Best odds 2.15 vs market 2.11 |
| 0% to +2% | Any | MONITOR | Wait for better opportunities |
| Negative | Any | AVOID | Market is inefficient against you |

## Authentication

All CLV endpoints require authentication:
```
Authorization: Bearer betgenius_secure_key_2024
```

## Rate Limits

- CLV alerts: Every 30 seconds recommended
- Match analysis: As needed
- Dashboard: Every 2-5 minutes

## Error Handling

```javascript
try {
    const response = await fetch('/clv/alerts');
    if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }
    const data = await response.json();
} catch (error) {
    console.error('CLV API Error:', error);
    // Handle error appropriately
}
```

## Best Practices

1. **Real-time monitoring**: Poll alerts every 30-60 seconds
2. **Quick execution**: Act on high CLV opportunities immediately
3. **Confidence filtering**: Prioritize High confidence opportunities
4. **League focus**: Monitor specific leagues for better efficiency
5. **Historical tracking**: Log CLV performance for analysis

## CLV Strategy Implementation

### Early Line Strategy
- Monitor matches T-72h to T-48h for best CLV opportunities
- Focus on premium bookmakers (148, 894, 710)
- Set alerts for CLV >+3%

### Real-time Arbitrage
- Compare odds across multiple bookmakers in real-time
- Execute quickly when significant CLV appears
- Track closing line performance

### Risk Management
- Limit exposure on extremely high CLV (>+7%) opportunities
- Diversify across multiple matches and outcomes
- Monitor for potential bookmaker limits