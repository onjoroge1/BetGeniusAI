# CLV (Closing Line Value) Betting Strategy Guide

## What is CLV?

**Closing Line Value (CLV)** is the difference between the odds you get when placing a bet and the closing odds (final odds before the match starts). Positive CLV indicates you got better odds than the market's final assessment, suggesting long-term profitability.

**Formula**: `CLV = (Your Odds - Closing Line Odds) / Closing Line Odds × 100`

## CLV API Endpoints

### 1. Dashboard Overview
```
GET /clv/dashboard
Authorization: Bearer betgenius_secure_key_2024
```

**Purpose**: Get comprehensive CLV monitoring overview
- Active matches with CLV opportunities
- Market movement summary
- Top performing bookmakers
- System status indicators

### 2. Live CLV Alerts
```
GET /clv/alerts?league_ids=39,140&min_clv=2.0
Authorization: Bearer betgenius_secure_key_2024
```

**Purpose**: Real-time alerts for positive CLV opportunities
- Filter by specific leagues
- Automatic opportunity detection
- Updates every 30 seconds recommended

### 3. Filtered Opportunities
```
GET /clv/opportunities?min_clv=3.0&confidence=High&league_ids=39,140
Authorization: Bearer betgenius_secure_key_2024
```

**Purpose**: Advanced filtering for specific CLV criteria
- Minimum CLV threshold (default: 2.0%)
- Confidence levels: High, Medium, Low
- League-specific filtering
- Custom opportunity discovery

### 4. Match-Specific Analysis
```
GET /clv/match/{match_id}
Authorization: Bearer betgenius_secure_key_2024
```

**Purpose**: Detailed CLV analysis for individual matches
- Comprehensive outcome analysis (H/D/A)
- Bookmaker comparison
- Timing recommendations
- Overall match assessment

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