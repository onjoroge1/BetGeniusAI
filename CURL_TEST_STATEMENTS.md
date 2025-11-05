# BetGenius AI - Complete cURL Test Guide

## 🔑 Authentication
All endpoints require API key authentication:
```bash
export API_KEY="betgenius_secure_key_2024"
export BASE_URL="http://localhost:8000"
```

## 📊 1. Per-Match Betting Intelligence

### Basic Request
```bash
curl -s -H "Authorization: Bearer $API_KEY" \
  "$BASE_URL/betting-intelligence/1451083" | jq '.'
```

### With Custom Bankroll
```bash
curl -s -H "Authorization: Bearer $API_KEY" \
  "$BASE_URL/betting-intelligence/1451083?bankroll=10000" | jq '.'
```

### With Kelly Fraction (Quarter-Kelly for Conservative)
```bash
curl -s -H "Authorization: Bearer $API_KEY" \
  "$BASE_URL/betting-intelligence/1451083?bankroll=5000&kelly_frac=0.25" | jq '.'
```

### Using V2 Premium Model
```bash
curl -s -H "Authorization: Bearer $API_KEY" \
  "$BASE_URL/betting-intelligence/1451083?model=v2&bankroll=1000" | jq '.'
```

### Full Parameters
```bash
curl -s -H "Authorization: Bearer $API_KEY" \
  "$BASE_URL/betting-intelligence/1451083?model=best&bankroll=10000&kelly_frac=0.5" | jq '.'
```

### Pretty Print Best Bet Info
```bash
curl -s -H "Authorization: Bearer $API_KEY" \
  "$BASE_URL/betting-intelligence/1451083?bankroll=1000" | \
  jq '{
    match: (.home.name + " vs " + .away.name),
    league: .league.name,
    kickoff: .kickoff_time,
    best_bet: .betting_intelligence.best_bet,
    kelly: .betting_intelligence.kelly_sizing
  }'
```

## 🎯 2. Curated Betting Opportunities

### High-Edge Opportunities (5%+ Edge)
```bash
curl -s -H "Authorization: Bearer $API_KEY" \
  "$BASE_URL/betting-intelligence?min_edge=0.05&limit=10" | jq '.'
```

### Moderate Edge (3%+) - More Opportunities
```bash
curl -s -H "Authorization: Bearer $API_KEY" \
  "$BASE_URL/betting-intelligence?min_edge=0.03&limit=20" | jq '.'
```

### Low Edge Threshold (1%+) - Maximum Opportunities
```bash
curl -s -H "Authorization: Bearer $API_KEY" \
  "$BASE_URL/betting-intelligence?min_edge=0.01&limit=50" | jq '.'
```

### Sort by Edge (Highest First)
```bash
curl -s -H "Authorization: Bearer $API_KEY" \
  "$BASE_URL/betting-intelligence?min_edge=0.02&sort_by=edge&limit=15" | jq '.'
```

### Sort by Kickoff Time (Soonest First)
```bash
curl -s -H "Authorization: Bearer $API_KEY" \
  "$BASE_URL/betting-intelligence?min_edge=0.02&sort_by=kickoff&limit=10" | jq '.'
```

### Sort by Confidence (Highest First)
```bash
curl -s -H "Authorization: Bearer $API_KEY" \
  "$BASE_URL/betting-intelligence?min_edge=0.02&sort_by=confidence&limit=10" | jq '.'
```

### Filter by League (Premier League = 39)
```bash
curl -s -H "Authorization: Bearer $API_KEY" \
  "$BASE_URL/betting-intelligence?league_ids=39&min_edge=0.02&limit=10" | jq '.'
```

### Filter by Multiple Leagues (Premier League + La Liga)
```bash
curl -s -H "Authorization: Bearer $API_KEY" \
  "$BASE_URL/betting-intelligence?league_ids=39,140&min_edge=0.02&limit=20" | jq '.'
```

### V2 Premium Model Only
```bash
curl -s -H "Authorization: Bearer $API_KEY" \
  "$BASE_URL/betting-intelligence?model=v2&min_edge=0.03&limit=10" | jq '.'
```

### Live Betting Opportunities Only
```bash
curl -s -H "Authorization: Bearer $API_KEY" \
  "$BASE_URL/betting-intelligence?status=live&min_edge=0.03&limit=10" | jq '.'
```

### Upcoming Matches Only
```bash
curl -s -H "Authorization: Bearer $API_KEY" \
  "$BASE_URL/betting-intelligence?status=upcoming&min_edge=0.02&limit=20" | jq '.'
```

### With Custom Bankroll for Kelly Sizing
```bash
curl -s -H "Authorization: Bearer $API_KEY" \
  "$BASE_URL/betting-intelligence?min_edge=0.03&bankroll=5000&limit=15" | jq '.'
```

### Pagination (Page 2, 10 per page)
```bash
curl -s -H "Authorization: Bearer $API_KEY" \
  "$BASE_URL/betting-intelligence?min_edge=0.02&limit=10&offset=10" | jq '.'
```

### Extract Just the Top Opportunities
```bash
curl -s -H "Authorization: Bearer $API_KEY" \
  "$BASE_URL/betting-intelligence?min_edge=0.03&limit=5" | \
  jq '.opportunities[] | {
    match: (.home_team + " vs " + .away_team),
    league: .league_name,
    pick: .betting_intelligence.best_bet.pick,
    edge: (.betting_intelligence.best_bet.edge * 100),
    stake_pct: .betting_intelligence.kelly_sizing.recommended_stake_pct
  }'
```

## 📋 3. Market Board Integration

### Upcoming Matches with Betting Intelligence
```bash
curl -s -H "Authorization: Bearer $API_KEY" \
  "$BASE_URL/market?status=upcoming&limit=10" | jq '.'
```

### Live Matches with In-Play Intelligence
```bash
curl -s -H "Authorization: Bearer $API_KEY" \
  "$BASE_URL/market?status=live&limit=5" | jq '.'
```

### Finished Matches with Results
```bash
curl -s -H "Authorization: Bearer $API_KEY" \
  "$BASE_URL/market?status=finished&limit=10" | jq '.'
```

### Market Board with V2 Predictions
```bash
curl -s -H "Authorization: Bearer $API_KEY" \
  "$BASE_URL/market?status=upcoming&v2_include=true&limit=10" | jq '.'
```

### Filter by League
```bash
curl -s -H "Authorization: Bearer $API_KEY" \
  "$BASE_URL/market?status=upcoming&league_id=39&limit=20" | jq '.'
```

### Extract Matches with Value Bets
```bash
curl -s -H "Authorization: Bearer $API_KEY" \
  "$BASE_URL/market?status=upcoming&limit=20" | \
  jq '.matches[] | select(.betting_intelligence.best_bet.recommendation == "VALUE BET") | {
    match: (.home.name + " vs " + .away.name),
    pick: .betting_intelligence.best_bet.pick,
    edge: (.betting_intelligence.best_bet.edge * 100)
  }'
```

## 🧪 4. Quick Test Suite

### Test 1: Health Check
```bash
echo "=== Health Check ===" && \
curl -s -H "Authorization: Bearer $API_KEY" \
  "$BASE_URL/health" | jq '.'
```

### Test 2: Per-Match Intelligence
```bash
echo -e "\n=== Per-Match Intelligence ===" && \
curl -s -H "Authorization: Bearer $API_KEY" \
  "$BASE_URL/betting-intelligence/1451083?bankroll=1000" | \
  jq '{
    match: (.home.name + " vs " + .away.name),
    pick: .betting_intelligence.best_bet.pick,
    edge: (.betting_intelligence.best_bet.edge * 100),
    recommendation: .betting_intelligence.best_bet.recommendation,
    stake_pct: .betting_intelligence.kelly_sizing.recommended_stake_pct
  }'
```

### Test 3: Find Opportunities
```bash
echo -e "\n=== Top Opportunities ===" && \
curl -s -H "Authorization: Bearer $API_KEY" \
  "$BASE_URL/betting-intelligence?min_edge=0.01&limit=5" | \
  jq '{
    count: .total_count,
    opportunities: .opportunities[0:3] | map({
      match: (.home_team + " vs " + .away_team),
      edge: (.betting_intelligence.best_bet.edge * 100)
    })
  }'
```

### Test 4: Market Board
```bash
echo -e "\n=== Market Board ===" && \
curl -s -H "Authorization: Bearer $API_KEY" \
  "$BASE_URL/market?status=upcoming&limit=3" | \
  jq '{
    count: .total_count,
    matches: .matches[0:3] | map({
      match: (.home.name + " vs " + .away.name),
      kickoff: .kickoff_time,
      has_intel: (.betting_intelligence != null)
    })
  }'
```

### Run All Tests
```bash
#!/bin/bash
API_KEY="betgenius_secure_key_2024"
BASE_URL="http://localhost:8000"

echo "🧪 BetGenius AI - Test Suite"
echo "=============================="

echo -e "\n✅ Test 1: Health"
curl -s -H "Authorization: Bearer $API_KEY" "$BASE_URL/health" | jq -r '.status'

echo -e "\n✅ Test 2: Per-Match Intel"
curl -s -H "Authorization: Bearer $API_KEY" \
  "$BASE_URL/betting-intelligence/1451083" | \
  jq -r '"Pick: " + .betting_intelligence.best_bet.pick + " @ " + (.betting_intelligence.best_bet.edge * 100 | tostring) + "% edge"'

echo -e "\n✅ Test 3: Opportunities Count"
curl -s -H "Authorization: Bearer $API_KEY" \
  "$BASE_URL/betting-intelligence?min_edge=0.01" | \
  jq -r '"Found: " + (.total_count | tostring) + " opportunities"'

echo -e "\n✅ Test 4: Market Board Count"
curl -s -H "Authorization: Bearer $API_KEY" \
  "$BASE_URL/market?status=upcoming" | \
  jq -r '"Matches: " + (.total_count | tostring)'

echo -e "\n✅ All tests complete!"
```

## 🔍 5. Advanced Queries

### Find Strong Bets Only (≥5% Edge)
```bash
curl -s -H "Authorization: Bearer $API_KEY" \
  "$BASE_URL/betting-intelligence?min_edge=0.05" | \
  jq '.opportunities[] | select(.betting_intelligence.best_bet.recommendation == "STRONG BET")'
```

### Find Home Bets Only
```bash
curl -s -H "Authorization: Bearer $API_KEY" \
  "$BASE_URL/betting-intelligence?min_edge=0.02" | \
  jq '.opportunities[] | select(.betting_intelligence.best_bet.pick == "home")'
```

### Find Away Underdogs with Value
```bash
curl -s -H "Authorization: Bearer $API_KEY" \
  "$BASE_URL/betting-intelligence?min_edge=0.03" | \
  jq '.opportunities[] | select(.betting_intelligence.best_bet.pick == "away" and .betting_intelligence.best_bet.edge > 0.04)'
```

### Export to CSV
```bash
curl -s -H "Authorization: Bearer $API_KEY" \
  "$BASE_URL/betting-intelligence?min_edge=0.02&limit=50" | \
  jq -r '.opportunities[] | [
    .home_team,
    .away_team,
    .league_name,
    .kickoff_time,
    .betting_intelligence.best_bet.pick,
    (.betting_intelligence.best_bet.edge * 100),
    .betting_intelligence.best_bet.recommendation,
    .betting_intelligence.kelly_sizing.recommended_stake_pct
  ] | @csv' > betting_opportunities.csv

echo "Exported to betting_opportunities.csv"
```

### Generate Bet Slip
```bash
curl -s -H "Authorization: Bearer $API_KEY" \
  "$BASE_URL/betting-intelligence?min_edge=0.04&bankroll=1000&limit=10" | \
  jq '.opportunities[] | {
    match: (.home_team + " vs " + .away_team),
    pick: .betting_intelligence.best_bet.pick,
    edge: (.betting_intelligence.best_bet.edge * 100 | floor),
    stake: (.betting_intelligence.kelly_sizing.recommended_stake_pct * 10 | floor),
    recommendation: .betting_intelligence.best_bet.recommendation
  }'
```

## 📊 6. Performance Testing

### Measure Response Time
```bash
time curl -s -H "Authorization: Bearer $API_KEY" \
  "$BASE_URL/betting-intelligence/1451083" > /dev/null
```

### Benchmark Multiple Requests
```bash
for i in {1..10}; do
  echo "Request $i:"
  time curl -s -H "Authorization: Bearer $API_KEY" \
    "$BASE_URL/betting-intelligence?min_edge=0.02&limit=20" > /dev/null
done
```

### Parallel Requests Test
```bash
for match_id in 1451083 1451084 1451085; do
  curl -s -H "Authorization: Bearer $API_KEY" \
    "$BASE_URL/betting-intelligence/$match_id" &
done
wait
echo "All requests complete"
```

## 🚨 7. Error Handling Tests

### Test Invalid Match ID
```bash
curl -s -H "Authorization: Bearer $API_KEY" \
  "$BASE_URL/betting-intelligence/999999999" | jq '.'
```

### Test Missing API Key
```bash
curl -s "$BASE_URL/betting-intelligence/1451083" | jq '.'
```

### Test Invalid Model
```bash
curl -s -H "Authorization: Bearer $API_KEY" \
  "$BASE_URL/betting-intelligence/1451083?model=invalid" | jq '.'
```

### Test Invalid Parameters
```bash
curl -s -H "Authorization: Bearer $API_KEY" \
  "$BASE_URL/betting-intelligence/1451083?bankroll=-1000&kelly_frac=5.0" | jq '.'
```

## 📱 8. Mobile/Web App Simulation

### Fetch Today's Opportunities for Mobile App
```bash
curl -s -H "Authorization: Bearer $API_KEY" \
  "$BASE_URL/betting-intelligence?min_edge=0.03&sort_by=edge&limit=20" | \
  jq '{
    updated_at: now,
    total_count: .total_count,
    top_picks: .opportunities[0:5] | map({
      id: .match_id,
      home: .home_team,
      away: .away_team,
      league: .league_name,
      kickoff: .kickoff_time,
      pick: .betting_intelligence.best_bet.pick,
      edge_pct: (.betting_intelligence.best_bet.edge * 100 | floor),
      stake_pct: (.betting_intelligence.kelly_sizing.recommended_stake_pct | floor),
      confidence: .betting_intelligence.best_bet.confidence
    })
  }'
```

### Live Dashboard Refresh (Every 60 seconds)
```bash
while true; do
  clear
  echo "🎯 BetGenius AI - Live Dashboard"
  echo "=================================="
  echo ""
  
  curl -s -H "Authorization: Bearer $API_KEY" \
    "$BASE_URL/betting-intelligence?status=live&min_edge=0.02&limit=5" | \
    jq -r '.opportunities[] | 
      "⚽ " + .home_team + " vs " + .away_team + " | " +
      .betting_intelligence.best_bet.pick + " @ " +
      (.betting_intelligence.best_bet.edge * 100 | tostring | split(".")[0]) + "% | " +
      .betting_intelligence.best_bet.recommendation'
  
  echo ""
  echo "Updated: $(date)"
  sleep 60
done
```

## 🎓 9. Learning Examples

### Simple: Get One Match
```bash
curl -H "Authorization: Bearer betgenius_secure_key_2024" \
  "http://localhost:8000/betting-intelligence/1451083"
```

### Medium: Find Top 5 Value Bets
```bash
curl -H "Authorization: Bearer betgenius_secure_key_2024" \
  "http://localhost:8000/betting-intelligence?min_edge=0.03&limit=5" | \
  jq '.opportunities[].betting_intelligence.best_bet'
```

### Advanced: Build Betting Portfolio
```bash
curl -H "Authorization: Bearer betgenius_secure_key_2024" \
  "http://localhost:8000/betting-intelligence?min_edge=0.04&bankroll=10000&limit=10" | \
  jq '{
    bankroll: 10000,
    total_opportunities: .total_count,
    portfolio: [.opportunities[] | {
      match: (.home_team + " vs " + .away_team),
      pick: .betting_intelligence.best_bet.pick,
      edge: .betting_intelligence.best_bet.edge,
      stake_amount: (.betting_intelligence.kelly_sizing.recommended_stake_pct * 100 | floor)
    }],
    total_staked: ([.opportunities[].betting_intelligence.kelly_sizing.recommended_stake_pct * 100] | add | floor)
  }'
```

---

## 💡 Pro Tips

1. **Use `jq` for pretty output**: All examples use `jq '.'` for formatting
2. **Save responses**: Add `| jq '.' > output.json` to save results
3. **Chain commands**: Use `&&` to run multiple tests sequentially
4. **Background requests**: Add `&` at the end for parallel execution
5. **Watch mode**: Use `watch -n 30` to refresh every 30 seconds
6. **Logging**: Add `-v` flag to curl for verbose output (debugging)

## 🔗 Quick Reference

| Endpoint | Purpose | Key Parameters |
|----------|---------|----------------|
| `/betting-intelligence/{id}` | Per-match intel | `model`, `bankroll`, `kelly_frac` |
| `/betting-intelligence` | Curated opportunities | `min_edge`, `league_ids`, `status`, `sort_by` |
| `/market` | Market board | `status`, `limit`, `league_id` |

---

**Tip**: Save this as `test.sh`, make it executable (`chmod +x test.sh`), and run all tests with `./test.sh`
