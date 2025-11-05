# Betting Intelligence API - Test Commands

## Overview
Complete test suite for BetGenius AI's betting intelligence endpoints with robust odds parsing and per-match intelligence.

## Environment
```bash
export API_KEY="betgenius_secure_key_2024"
export BASE_URL="http://localhost:8000"
```

## Test 1: Market Board with Betting Intelligence (Upcoming Matches)

```bash
# Get upcoming matches with embedded betting intelligence
curl -s -H "Authorization: Bearer betgenius_secure_key_2024" \
  "http://localhost:8000/market?status=upcoming&limit=5&v2_include=true" | \
  python3 -c "
import sys, json
data = json.load(sys.stdin)
print(f'📊 UPCOMING MATCHES: {data.get(\"total_count\", 0)} found\n')

for m in data.get('matches', [])[:3]:
    print(f'✅ {m[\"home\"][\"name\"]} vs {m[\"away\"][\"name\"]}')
    print(f'   League: {m[\"league\"][\"name\"]}')
    print(f'   Kickoff: {m[\"kickoff_time\"]}')
    
    if 'betting_intelligence' in m and m['betting_intelligence']:
        bi = m['betting_intelligence']
        best = bi.get('best_bet', {})
        clv = bi.get('clv', {})
        kelly = bi.get('kelly_sizing', {})
        
        print(f'   📊 BETTING INTELLIGENCE:')
        print(f'      Pick: {best.get(\"pick\", \"N/A\").upper()}')
        print(f'      Edge: {best.get(\"edge\", 0)*100:.1f}%')
        print(f'      Recommendation: {best.get(\"recommendation\", \"N/A\")}')
        print(f'      CLV: H={clv.get(\"home\", 0)*100:+.1f}% D={clv.get(\"draw\", 0)*100:+.1f}% A={clv.get(\"away\", 0)*100:+.1f}%')
        if kelly:
            print(f'      Kelly: {kelly.get(\"recommended_stake_pct\", 0):.1f}% of bankroll')
    else:
        print(f'   ⚠️  No betting intelligence')
    print()
"
```

## Test 2: Curated Betting Opportunities (High Edge)

```bash
# Get high-edge opportunities (5%+)
curl -s -H "Authorization: Bearer betgenius_secure_key_2024" \
  "http://localhost:8000/betting-intelligence?min_edge=0.05&limit=10&sort_by=edge" | \
  python3 -c "
import sys, json
data = json.load(sys.stdin)
count = data.get('total_count', 0)
print(f'🎯 HIGH-EDGE OPPORTUNITIES: {count} found\n')

for opp in data.get('opportunities', [])[:5]:
    bi = opp['betting_intelligence']
    best = bi['best_bet']
    kelly = bi.get('kelly_sizing', {})
    
    print(f'✅ {opp[\"home_team\"]} vs {opp[\"away_team\"]}')
    print(f'   League: {opp[\"league\"][\"name\"]}')
    print(f'   Kickoff: {opp[\"kickoff_at\"]}')
    print(f'   Model: {opp[\"model_used\"].upper()}')
    print(f'   📊 Best Bet: {best[\"pick\"].upper()} @ {best[\"edge\"]*100:.1f}% edge')
    print(f'   ⭐ {best[\"recommendation\"]}')
    if kelly:
        print(f'   💰 Kelly: {kelly.get(\"recommended_stake_pct\", 0):.1f}% of bankroll')
    print()
"
```

## Test 3: Moderate Edge Opportunities (3%+)

```bash
# Get moderate-edge opportunities
curl -s -H "Authorization: Bearer betgenius_secure_key_2024" \
  "http://localhost:8000/betting-intelligence?min_edge=0.03&limit=20&sort_by=edge" | \
  python3 -c "
import sys, json
data = json.load(sys.stdin)
print(f'📈 MODERATE-EDGE OPPORTUNITIES: {data.get(\"total_count\", 0)} found')
print(f'Min Edge Threshold: {data.get(\"filters\", {}).get(\"min_edge\", 0)*100:.0f}%\n')

for opp in data.get('opportunities', [])[:5]:
    bi = opp['betting_intelligence']
    best = bi['best_bet']
    print(f'{opp[\"home_team\"]} vs {opp[\"away_team\"]} | {best[\"pick\"].upper()} @ {best[\"edge\"]*100:.1f}% | {best[\"recommendation\"]}')
"
```

## Test 4: Per-Match Betting Intelligence

```bash
# Get betting intelligence for a specific match
# Replace 1451083 with an actual match_id from your database
curl -s -H "Authorization: Bearer betgenius_secure_key_2024" \
  "http://localhost:8000/betting-intelligence/1451083?bankroll=1000&kelly_frac=0.5" | \
  python3 -c "
import sys, json
data = json.load(sys.stdin)

print(f'🎯 MATCH BETTING INTELLIGENCE')
print(f'Match ID: {data.get(\"match_id\")}')
print(f'{data.get(\"home\", {}).get(\"name\")} vs {data.get(\"away\", {}).get(\"name\")}')
print(f'League: {data.get(\"league\", {}).get(\"name\")}')
print(f'Kickoff: {data.get(\"kickoff_time\")}')
print(f'Model Used: {data.get(\"model_used\", \"N/A\").upper()}\n')

bi = data.get('betting_intelligence', {})
if bi:
    best = bi.get('best_bet', {})
    clv = bi.get('clv', {})
    kelly = bi.get('kelly_sizing', {})
    
    print(f'📊 BEST BET:')
    print(f'   Pick: {best.get(\"pick\", \"N/A\").upper()}')
    print(f'   Edge: {best.get(\"edge\", 0)*100:.2f}%')
    print(f'   Recommendation: {best.get(\"recommendation\", \"N/A\")}\n')
    
    print(f'💰 CLV BREAKDOWN:')
    print(f'   Home: {clv.get(\"home\", 0)*100:+.2f}%')
    print(f'   Draw: {clv.get(\"draw\", 0)*100:+.2f}%')
    print(f'   Away: {clv.get(\"away\", 0)*100:+.2f}%\n')
    
    if kelly:
        print(f'🎲 KELLY SIZING:')
        print(f'   Full Kelly: {kelly.get(\"full_kelly\", 0)*100:.2f}%')
        print(f'   Fractional Kelly (0.5x): {kelly.get(\"fractional_kelly\", 0)*100:.2f}%')
        print(f'   Recommended Stake: {kelly.get(\"recommended_stake_pct\", 0):.2f}% of bankroll')
        print(f'   Max Stake (cap): {kelly.get(\"max_stake_pct\", 0):.2f}%')
    
    odds = data.get('best_odds', {})
    if odds:
        print(f'\n📖 BEST ODDS ({odds.get(\"bookmaker\", \"N/A\")}):')
        prices = odds.get('prices', {})
        print(f'   Home: {prices.get(\"home\", 0):.2f}')
        print(f'   Draw: {prices.get(\"draw\", 0):.2f}')
        print(f'   Away: {prices.get(\"away\", 0):.2f}')
else:
    print('⚠️ No betting intelligence available')
"
```

## Test 5: Live Match Betting Intelligence

```bash
# Get live matches with in-play betting intelligence
curl -s -H "Authorization: Bearer betgenius_secure_key_2024" \
  "http://localhost:8000/market?status=live&limit=5" | \
  python3 -c "
import sys, json
data = json.load(sys.stdin)
print(f'🔴 LIVE MATCHES: {data.get(\"total_count\", 0)} found\n')

for m in data.get('matches', [])[:5]:
    print(f'⚡ {m[\"home\"][\"name\"]} vs {m[\"away\"][\"name\"]}')
    
    if 'live_data' in m and m['live_data']:
        ld = m['live_data']
        print(f'   Score: {ld.get(\"score\", {}).get(\"home\", 0)}-{ld.get(\"score\", {}).get(\"away\", 0)}')
        print(f'   Minute: {ld.get(\"minute\", \"N/A\")}')
    
    if 'betting_intelligence' in m and m['betting_intelligence']:
        bi = m['betting_intelligence']
        best = bi.get('best_bet', {})
        print(f'   📊 Live Edge: {best.get(\"pick\", \"N/A\").upper()} @ {best.get(\"edge\", 0)*100:.1f}%')
        print(f'   {best.get(\"recommendation\", \"N/A\")}')
    print()
"
```

## Test 6: Filtered by League

```bash
# Get Premier League (39) betting opportunities
curl -s -H "Authorization: Bearer betgenius_secure_key_2024" \
  "http://localhost:8000/betting-intelligence?league_ids=39&min_edge=0.02&limit=10" | \
  python3 -c "
import sys, json
data = json.load(sys.stdin)
print(f'⚽ PREMIER LEAGUE OPPORTUNITIES: {data.get(\"total_count\", 0)} found\n')

for opp in data.get('opportunities', [])[:5]:
    bi = opp['betting_intelligence']
    best = bi['best_bet']
    print(f'{opp[\"home_team\"]} vs {opp[\"away_team\"]} | {best[\"pick\"].upper()} @ {best[\"edge\"]*100:.1f}%')
"
```

## Test 7: Low Edge Threshold (Conservative)

```bash
# Get all opportunities with even minimal edge (1%+)
curl -s -H "Authorization: Bearer betgenius_secure_key_2024" \
  "http://localhost:8000/betting-intelligence?min_edge=0.01&limit=30&sort_by=edge" | \
  python3 -c "
import sys, json
data = json.load(sys.stdin)
print(f'📊 ALL POSITIVE EDGE OPPORTUNITIES: {data.get(\"total_count\", 0)} found\n')

# Group by recommendation
recommendations = {}
for opp in data.get('opportunities', []):
    rec = opp['betting_intelligence']['best_bet']['recommendation']
    recommendations[rec] = recommendations.get(rec, 0) + 1

print('Breakdown by Recommendation:')
for rec, count in sorted(recommendations.items(), key=lambda x: x[1], reverse=True):
    print(f'  {rec}: {count}')
"
```

## Test 8: Market Board Single Match

```bash
# Get market data for a specific match with betting intelligence
curl -s -H "Authorization: Bearer betgenius_secure_key_2024" \
  "http://localhost:8000/market?match_id=1451083&status=upcoming" | \
  python3 -c "
import sys, json
data = json.load(sys.stdin)

if data.get('matches'):
    m = data['matches'][0]
    print(f'Match: {m[\"home\"][\"name\"]} vs {m[\"away\"][\"name\"]}')
    print(f'League: {m[\"league\"][\"name\"]}')
    
    # V1 Prediction
    v1 = m.get('v1_prediction', {})
    if v1:
        v1p = v1.get('probabilities', {})
        print(f'\nV1 Model:')
        print(f'  H={v1p.get(\"home\", 0)*100:.1f}% D={v1p.get(\"draw\", 0)*100:.1f}% A={v1p.get(\"away\", 0)*100:.1f}%')
        print(f'  Pick: {v1.get(\"recommended_bet\", \"N/A\").upper()}')
    
    # V2 Prediction
    v2 = m.get('v2_prediction', {})
    if v2:
        v2p = v2.get('probabilities', {})
        print(f'\nV2 Model:')
        print(f'  H={v2p.get(\"home\", 0)*100:.1f}% D={v2p.get(\"draw\", 0)*100:.1f}% A={v2p.get(\"away\", 0)*100:.1f}%')
        print(f'  Pick: {v2.get(\"recommended_bet\", \"N/A\").upper()}')
        print(f'  Confidence: {v2.get(\"confidence\", 0)*100:.1f}%')
    
    # Betting Intelligence
    bi = m.get('betting_intelligence', {})
    if bi:
        best = bi.get('best_bet', {})
        print(f'\nBetting Intelligence:')
        print(f'  Pick: {best.get(\"pick\", \"N/A\").upper()}')
        print(f'  Edge: {best.get(\"edge\", 0)*100:.1f}%')
        print(f'  {best.get(\"recommendation\", \"N/A\")}')
"
```

## Test 9: Check Endpoint Health

```bash
# Simple health check to see if betting intelligence is working
curl -s -H "Authorization: Bearer betgenius_secure_key_2024" \
  "http://localhost:8000/betting-intelligence?min_edge=0.01&limit=1" | \
  python3 -c "
import sys, json
data = json.load(sys.stdin)

if 'opportunities' in data:
    count = data.get('total_count', 0)
    if count > 0:
        print('✅ Betting Intelligence API is WORKING')
        print(f'   Found {count} opportunities')
        
        opp = data['opportunities'][0]
        bi = opp['betting_intelligence']
        print(f'   Sample: {opp[\"home_team\"]} vs {opp[\"away_team\"]}')
        print(f'   Edge: {bi[\"best_bet\"][\"edge\"]*100:.1f}%')
    else:
        print('⚠️  Betting Intelligence API working but no opportunities found')
        print('   Try lowering min_edge or checking if matches have predictions')
else:
    print('❌ Betting Intelligence API error')
    print(json.dumps(data, indent=2))
"
```

## Test 10: V2 Model Only (Premium)

```bash
# Get opportunities using only V2 premium model
curl -s -H "Authorization: Bearer betgenius_secure_key_2024" \
  "http://localhost:8000/betting-intelligence?model=v2&min_edge=0.03&limit=10" | \
  python3 -c "
import sys, json
data = json.load(sys.stdin)
print(f'⭐ V2 PREMIUM OPPORTUNITIES: {data.get(\"total_count\", 0)} found\n')

for opp in data.get('opportunities', [])[:5]:
    bi = opp['betting_intelligence']
    best = bi['best_bet']
    print(f'{opp[\"home_team\"]} vs {opp[\"away_team\"]}')
    print(f'  {best[\"pick\"].upper()} @ {best[\"edge\"]*100:.1f}% | {best[\"recommendation\"]}')
"
```

## Quick Test Script

Save this as `test_betting_intel.sh`:

```bash
#!/bin/bash

API_KEY="betgenius_secure_key_2024"
BASE_URL="http://localhost:8000"

echo "🧪 Testing BetGenius AI Betting Intelligence"
echo "============================================"
echo ""

# Test 1: Health check
echo "1️⃣ Health Check..."
curl -s -H "Authorization: Bearer $API_KEY" \
  "$BASE_URL/betting-intelligence?min_edge=0.01&limit=1" | \
  python3 -c "import sys,json; d=json.load(sys.stdin); print(f'✅ Found {d.get(\"total_count\",0)} opportunities' if d.get('opportunities') else '❌ API Error')"
echo ""

# Test 2: Market board
echo "2️⃣ Market Board with Betting Intelligence..."
curl -s -H "Authorization: Bearer $API_KEY" \
  "$BASE_URL/market?status=upcoming&limit=3" | \
  python3 -c "import sys,json; d=json.load(sys.stdin); print(f'✅ {d.get(\"total_count\",0)} matches loaded')"
echo ""

# Test 3: Curated opportunities
echo "3️⃣ High-Edge Opportunities (5%+)..."
curl -s -H "Authorization: Bearer $API_KEY" \
  "$BASE_URL/betting-intelligence?min_edge=0.05&limit=5" | \
  python3 -c "import sys,json; d=json.load(sys.stdin); print(f'✅ {d.get(\"total_count\",0)} high-edge bets found')"
echo ""

echo "✅ All tests completed!"
```

Run with: `chmod +x test_betting_intel.sh && ./test_betting_intel.sh`

## Expected Response Format

### Betting Intelligence Object
```json
{
  "clv": {
    "home": 0.052,
    "draw": -0.015,
    "away": -0.031
  },
  "best_bet": {
    "pick": "home",
    "edge": 0.052,
    "recommendation": "STRONG BET",
    "confidence": "high"
  },
  "kelly_sizing": {
    "full_kelly": 0.034,
    "fractional_kelly": 0.017,
    "recommended_stake_pct": 1.7,
    "max_stake_pct": 3.0
  }
}
```

## Troubleshooting

### No betting intelligence field
- Match has no predictions yet
- Odds data not available
- Match too far in future (>7 days)

### Empty opportunities list
- No matches meet min_edge threshold
- Try lowering min_edge to 0.01
- Check different leagues

### Calculation errors in logs
- Check logs: `grep "Betting intelligence" /tmp/logs/*.log`
- Verify odds data format is correct
- Ensure model predictions exist
