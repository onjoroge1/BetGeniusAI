# CLV (Closing Line Value) Betting Strategy Guide

## What is CLV?

**Closing Line Value (CLV)** is the difference between the odds you get when placing a bet and the closing odds (final odds before the match starts). Positive CLV indicates you got better odds than the market's final assessment, suggesting long-term profitability.

**Formula**: `CLV = (Your Odds - Closing Line Odds) / Closing Line Odds × 100`

## CLV API Endpoints & Calculation Methods

### Average Odds Calculation Method

**Formula**: `AVG(odds_decimal)` - Simple arithmetic mean of all odds from a bookmaker

**Example for Bookmaker 160**:
- Total odds collected: 66 individual odds
- Sum of all odds: 238.85
- Average calculation: 238.85 ÷ 66 = 3.6189393939...
- **Purpose**: Identifies bookmakers offering consistently higher or lower odds

**Sample odds range**: [1.33, 1.44, 1.45, ..., 7.8, 11.5] across all match outcomes (H/D/A)

### CLV Calculation Method

**Formula**: `CLV% = (Best_Odds - Market_Average) / Market_Average × 100`

**Example**:
- Best odds found: 11.5 (Bookmaker 160)
- Market average: 9.672 (average across all bookmakers)
- CLV = (11.5 - 9.672) / 9.672 × 100 = +18.9% CLV

### 1. Dashboard Overview
```
GET /clv/dashboard
Authorization: Bearer betgenius_secure_key_2024
```

**Purpose**: Get comprehensive CLV monitoring overview

**Response Structure**:
```json
{
  "summary": {
    "active_matches": 22,           // Matches with recent odds data
    "positive_clv_opportunities": 20, // CLV opportunities above threshold
    "significant_movements_6h": 0,   // Major odds changes (>5%)
    "bookmakers_tracked": 10         // Active bookmakers providing odds
  },
  "live_alerts": [...],             // Top 10 current CLV opportunities
  "top_bookmakers": [               // Bookmakers ranked by average odds
    {
      "book_id": "160",             // Internal bookmaker ID
      "odds_count": 66,             // Total odds provided
      "avg_odds": 3.6189,           // Average of all odds from this bookmaker
      "matches": 22,                // Matches covered by this bookmaker
      "is_premium": false           // Premium bookmaker status
    }
  ]
}
```

### 2. Live CLV Alerts
```
GET /clv/alerts?league_ids=39,140&min_clv=2.0
Authorization: Bearer betgenius_secure_key_2024
```

**Purpose**: Real-time alerts for positive CLV opportunities

**Parameters**:
- `league_ids` (optional): Filter by specific leagues (e.g., 39=Premier League, 140=La Liga)
- `min_clv` (optional): Minimum CLV percentage threshold (default: 2.0)

**Response Structure**:
```json
{
  "status": "success",
  "alerts": [
    {
      "match_id": 1377877,                    // Unique match identifier
      "outcome": "A",                         // H=Home Win, D=Draw, A=Away Win
      "best_odds": 11.5,                      // Highest odds found
      "best_bookmaker": 160,                  // Bookmaker offering best odds
      "market_odds": 9.672,                   // Average market odds
      "clv_percentage": 18.899917287014052,   // CLV percentage
      "confidence_level": "Medium",           // High/Medium/Low confidence
      "time_to_kickoff_hours": 16.41,         // Hours until match starts
      "recommendation": "CONSIDER - Positive CLV but close to kickoff",
      "created_at": "2025-08-31T02:15:20.353691"
    }
  ],
  "count": 20,                               // Total alerts found
  "timestamp": "2025-08-31T03:04:28.029292"  // API response timestamp
}
```

### 3. Filtered Opportunities
```
GET /clv/opportunities?min_clv=3.0&confidence=High&league_ids=39,140
Authorization: Bearer betgenius_secure_key_2024
```

**Purpose**: Advanced filtering for specific CLV criteria

**Parameters**:
- `min_clv` (optional): Minimum CLV percentage (default: 2.0)
- `confidence` (optional): Filter by confidence level (High/Medium/Low)
- `league_ids` (optional): Comma-separated league IDs

**Response Structure**: Same as `/clv/alerts` but with applied filters
```json
{
  "status": "success",
  "opportunities": [...],           // Same structure as alerts
  "filters": {                      // Applied filter summary
    "min_clv": 3.0,
    "confidence": "High",
    "league_ids": [39, 140]
  },
  "count": 5                        // Opportunities matching filters
}
```

### 4. Match-Specific Analysis
```
GET /clv/match/{match_id}
Authorization: Bearer betgenius_secure_key_2024
```

**Purpose**: Detailed CLV analysis for individual matches

**Response Structure**:
```json
{
  "match_id": 1377877,
  "home_team": "Manchester United",
  "away_team": "Liverpool", 
  "league_id": 39,
  "opportunities": [
    {
      "outcome": "A",                    // H/D/A outcome
      "best_odds": 11.5,
      "best_bookmaker": 160,
      "market_odds": 9.672,
      "clv_percentage": 18.9,
      "confidence_level": "Medium",
      "recommendation": "CONSIDER",
      "bookmaker_spread": 2.1            // Difference between highest/lowest odds
    }
  ],
  "market_summary": {
    "total_bookmakers": 20,              // Bookmakers offering odds
    "outcome_coverage": {                // Coverage by outcome
      "H": 20, "D": 20, "A": 20
    },
    "market_efficiency": 0.85            // Market efficiency score (0-1)
  },
  "timing_analysis": {
    "optimal_bet_time": "T-24h",         // Recommended betting window
    "time_to_kickoff": "16h 25m",
    "market_maturity": "High"            // Market development stage
  },
  "overall_recommendation": "MONITOR - Strong Away CLV opportunity"
}
```

## CLV Response Field Definitions

### Core Fields
- **match_id**: Unique identifier for the football match
- **outcome**: Betting outcome (H=Home Win, D=Draw, A=Away Win)
- **best_odds**: Highest decimal odds found across all bookmakers
- **best_bookmaker**: Bookmaker ID offering the highest odds
- **market_odds**: Average decimal odds across all tracked bookmakers
- **clv_percentage**: Calculated CLV as a percentage ((best_odds - market_odds) / market_odds × 100)

### Assessment Fields
- **confidence_level**: 
  - "High": Premium bookmaker + large sample size + significant CLV
  - "Medium": Good bookmaker coverage + moderate CLV
  - "Low": Limited sample or minimal CLV
- **recommendation**: 
  - "STRONG BET": CLV >5%, High confidence
  - "CONSIDER": CLV 3-5%, Medium+ confidence
  - "AVOID": CLV <3% or Low confidence
- **time_to_kickoff_hours**: Hours remaining until match kickoff

### Market Analysis Fields
- **bookmaker_spread**: Difference between highest and lowest odds (indicates market efficiency)
- **market_efficiency**: Score from 0-1 (higher = more efficient market, lower CLV opportunities)
- **total_bookmakers**: Number of bookmakers providing odds for this outcome

### Premium Bookmaker Classifications
- **Sharp Bookmakers**: [937, 468, 176, 215] - Professional/Pinnacle-style books
- **Premium Bookmakers**: [148, 894, 710, 6, 748] - High-quality mainstream books
- **is_premium**: Boolean indicating if bookmaker is classified as premium

## When to Bet (Positive CLV Strategy)

### 🟢 STRONG BET - Immediate Action Required
**CLV Range**: +5% or higher
**Confidence**: High
**Action**: Place bet immediately
**Example**: Best odds 2.50 vs market consensus 2.38 (+5.0% CLV)

**Why Bet**:
- Significant market inefficiency detected
- High probability of long-term profit
- Strong statistical edge over bookmakers

### 🟡 GOOD BET - Strong Consideration
**CLV Range**: +3% to +5%
**Confidence**: High or Medium
**Action**: Place bet with appropriate stake sizing
**Example**: Best odds 2.30 vs market consensus 2.23 (+3.1% CLV)

**Why Bet**:
- Clear value opportunity
- Positive expected value
- Market offering better odds than true probability

### 🔵 MODERATE BET - Selective Betting
**CLV Range**: +2% to +3%
**Confidence**: High only
**Action**: Consider bet with reduced stake
**Example**: Best odds 2.20 vs market consensus 2.16 (+1.9% CLV)

**Additional Criteria**:
- Must have High confidence rating
- Prefer early timing (T-72h to T-48h)
- Strong bookmaker (Pinnacle, Bet365, etc.)

## When to Monitor (Neutral CLV)

### 🔵 WATCH - Potential Opportunity
**CLV Range**: 0% to +2%
**Action**: Monitor for improvement, do not bet yet
**Strategy**: 
- Set alerts for movement above +2%
- Check again in 2-4 hours
- Look for line shopping opportunities

## When to Avoid Betting (Negative CLV)

### ❌ AVOID - No Betting Action
**CLV Range**: Any negative value
**Confidence**: Any level
**Action**: Do not bet under any circumstances
**Example**: Best available 2.10 vs market consensus 2.25 (-6.7% CLV)

**Why Avoid**:
- Market working against you
- Negative expected value
- Long-term losing proposition
- Better opportunities available elsewhere

### ❌ RED FLAGS - Never Bet Situations
1. **Consistently negative CLV** across all outcomes
2. **Late betting** (within 2 hours of kickoff) with negative CLV
3. **Low-confidence negative CLV** (worst possible combination)
4. **Bookmaker limitations** affecting your access to best odds

## CLV-Based Betting Decision Matrix

| CLV Range | Confidence | Timing | Action | Stake Size |
|-----------|------------|---------|---------|------------|
| +5% or more | High | Any | STRONG BET | Full stake |
| +3% to +5% | High/Medium | Early (T-48h+) | GOOD BET | 75% stake |
| +3% to +5% | High/Medium | Late (T-24h) | CONSIDER | 50% stake |
| +2% to +3% | High | Early (T-48h+) | MODERATE BET | 50% stake |
| +2% to +3% | Medium/Low | Any | MONITOR | No bet |
| 0% to +2% | Any | Any | MONITOR | No bet |
| Negative | Any | Any | AVOID | No bet |

## Timing Strategy for Maximum CLV

### Optimal Betting Windows

**T-72h to T-48h (Early Line)**:
- Highest CLV opportunities
- Market inefficiencies most common
- Best odds before sharp money arrives
- **Recommendation**: Primary betting window

**T-48h to T-24h (Value Window)**:
- Good CLV opportunities remain
- Some market tightening occurs
- Still profitable for +3% CLV opportunities
- **Recommendation**: Secondary betting window

**T-24h to T-4h (Late Window)**:
- Limited CLV opportunities
- Market becomes more efficient
- Only bet on +5% CLV with High confidence
- **Recommendation**: Selective betting only

**T-4h to Kickoff (Closing Window)**:
- Minimal CLV opportunities
- Avoid unless exceptional circumstances
- Market most efficient
- **Recommendation**: Generally avoid

## Risk Management with CLV

### Bankroll Allocation by CLV
- **+5% CLV**: Up to 3% of bankroll
- **+3-5% CLV**: Up to 2% of bankroll  
- **+2-3% CLV**: Up to 1% of bankroll
- **Below +2%**: No bet

### Portfolio Diversification
- Maximum 5 bets per day
- No more than 3 bets on same league
- Spread across different match outcomes
- Avoid correlated bets (same match multiple outcomes)

### Stop-Loss Protocols
- Daily loss limit: 5% of bankroll
- Weekly review of CLV performance
- Monthly bankroll adjustment based on results
- Quarterly strategy reassessment

## Practical Implementation Guide

### Step 1: Set Up Monitoring
```javascript
// Poll CLV alerts every 30 seconds
setInterval(async () => {
    const alerts = await fetch('/clv/alerts?min_clv=2.0');
    processAlerts(alerts);
}, 30000);
```

### Step 2: Alert Configuration
- **High Priority**: CLV +5% or higher
- **Medium Priority**: CLV +3% to +5%
- **Low Priority**: CLV +2% to +3%
- **SMS Alerts**: Only for High Priority with High Confidence

### Step 3: Decision Process
1. **Receive Alert**: CLV opportunity detected
2. **Verify Confidence**: Check confidence level and bookmaker
3. **Check Timing**: Ensure adequate time to kickoff
4. **Confirm Stake**: Use CLV-based stake sizing
5. **Execute Bet**: Place bet immediately if criteria met
6. **Track Performance**: Log bet for CLV analysis

## Common CLV Mistakes to Avoid

### ❌ Betting Without CLV Analysis
- Never bet based on "gut feeling"
- Always check CLV before placing any bet
- Ignore tips without CLV verification

### ❌ Chasing Negative CLV
- Don't bet because you "like" a team
- Avoid emotional betting on favorite teams
- Never justify negative CLV bets

### ❌ Poor Timing Management
- Don't wait too long to act on high CLV
- Avoid betting in closing hours without exceptional CLV
- Don't place bets during market volatility

### ❌ Inadequate Stake Sizing
- Don't bet same amount regardless of CLV
- Avoid over-betting on single opportunities
- Don't under-bet on exceptional CLV opportunities

## Expected Results with CLV Strategy

### Short-term (1 month)
- **Target**: +2-3% average CLV per bet
- **Expected ROI**: 5-8% improvement over random betting
- **Learning curve**: Understanding market patterns

### Medium-term (3 months)
- **Target**: +3-4% average CLV per bet
- **Expected ROI**: 10-15% improvement
- **Skill development**: Advanced pattern recognition

### Long-term (6+ months)
- **Target**: +4-5% average CLV per bet
- **Expected ROI**: 15-25% improvement
- **Mastery level**: Systematic profit generation

## CLV Success Metrics

### Track These KPIs
- **Average CLV per bet**: Target +3% minimum
- **CLV hit rate**: Percentage of positive CLV bets
- **ROI by CLV range**: Performance analysis by CLV level
- **Timing efficiency**: Early vs late bet performance

### Monthly Review Questions
1. What was my average CLV this month?
2. Which leagues provided best CLV opportunities?
3. What timing windows were most profitable?
4. How did my confidence filtering perform?
5. Are there patterns in my losing bets?

## Conclusion

CLV-based betting is a systematic approach to long-term profitability. The key principles are:

1. **Only bet positive CLV** (+2% minimum)
2. **Higher CLV = larger stakes** (within risk limits)
3. **Early timing preferred** (T-72h to T-48h optimal)
4. **Confidence matters** (High confidence + High CLV = best opportunities)
5. **Avoid negative CLV** under all circumstances

Success with CLV requires discipline, patience, and systematic execution. The CLV API endpoints provide the data foundation - your discipline and decision-making determine the results.