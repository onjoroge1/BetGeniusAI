#!/bin/bash
# Comprehensive Closing Odds System Test & Status Check

API_KEY="betgenius_secure_key_2024"
BASE_URL="http://localhost:8000"

echo "🔍 CLOSING ODDS SYSTEM STATUS CHECK"
echo "===================================================================="
echo ""

# 1. Schema Checks
echo "1️⃣  SCHEMA VALIDATION"
echo "--------------------------------------------------------------------"
echo "✓ clv_closing_feed table:"
psql $DATABASE_URL -c "\d clv_closing_feed" 2>/dev/null | grep -E "Column|Indexes" | head -10

echo ""
echo "✓ closing_odds table:"
psql $DATABASE_URL -c "\d closing_odds" 2>/dev/null | grep -E "Column|Indexes" | head -10

echo ""
echo "✓ Index check:"
psql $DATABASE_URL -c "
  SELECT indexname, indexdef 
  FROM pg_indexes 
  WHERE tablename IN ('clv_closing_feed', 'closing_odds')
  ORDER BY tablename, indexname;
" 2>/dev/null

# 2. Data Counts
echo ""
echo "2️⃣  DATA COUNTS"
echo "--------------------------------------------------------------------"
psql $DATABASE_URL -c "
  SELECT 
    'clv_closing_feed' as table_name,
    COUNT(*) as row_count,
    COUNT(DISTINCT match_id) as unique_matches
  FROM clv_closing_feed
  UNION ALL
  SELECT 
    'closing_odds',
    COUNT(*),
    COUNT(DISTINCT match_id)
  FROM closing_odds;
" 2>/dev/null

# 3. Freshness Check (Last 24h)
echo ""
echo "3️⃣  FRESHNESS CHECK (Last 24 hours)"
echo "--------------------------------------------------------------------"
psql $DATABASE_URL -c "
  SELECT 
    COUNT(*) as recent_samples,
    MIN(ts) as oldest_sample,
    MAX(ts) as newest_sample
  FROM clv_closing_feed
  WHERE ts > NOW() - INTERVAL '24 hours';
" 2>/dev/null

# 4. Sample Data (if available)
echo ""
echo "4️⃣  SAMPLE DATA"
echo "--------------------------------------------------------------------"
echo "Recent closing feed samples:"
psql $DATABASE_URL -c "
  SELECT match_id, outcome, composite_odds_dec, books_used, ts 
  FROM clv_closing_feed 
  ORDER BY ts DESC 
  LIMIT 5;
" 2>/dev/null

echo ""
echo "Closing odds (if populated):"
psql $DATABASE_URL -c "
  SELECT match_id, h_close_odds, d_close_odds, a_close_odds, 
         method_used, avg_books_closing 
  FROM closing_odds 
  LIMIT 5;
" 2>/dev/null

# 5. Upcoming Matches
echo ""
echo "5️⃣  UPCOMING MATCHES (Next 24h)"
echo "--------------------------------------------------------------------"
psql $DATABASE_URL -c "
  SELECT COUNT(DISTINCT match_id) as upcoming_matches,
         MIN(match_date) as next_match,
         MAX(match_date) as last_match
  FROM odds_snapshots 
  WHERE match_date > NOW() 
    AND match_date < NOW() + INTERVAL '24 hours';
" 2>/dev/null

# 6. API Test - Enhanced Metrics
echo ""
echo "6️⃣  API TEST - Enhanced Metrics Endpoint"
echo "--------------------------------------------------------------------"
RESPONSE=$(curl -s "${BASE_URL}/metrics/evaluation?window=all" \
  -H "Authorization: Bearer ${API_KEY}")

echo "$RESPONSE" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    
    print(f\"✓ Metrics retrieved successfully\")
    print(f\"  • Total matches evaluated: {data.get('total_matches', 0)}\")
    print(f\"  • Brier Score: {data.get('brier_score', 0):.4f}\")
    print(f\"  • LogLoss: {data.get('log_loss', 0):.4f}\")
    print(f\"  • Hit Rate: {data.get('hit_rate', 0)*100:.2f}%\")
    
    clv = data.get('clv_analysis', {})
    if 'status' in clv:
        print(f\"  • CLV Status: {clv['status']}\")
        print(f\"  • CLV Message: {clv.get('message', 'N/A')}\")
    else:
        print(f\"  • CLV Matches: {clv.get('matches_with_closing_odds', 0)}\")
        print(f\"  • Avg CLV Edge: {clv.get('avg_clv_edge', 0):.4f}\")
        print(f\"  • Positive CLV Rate: {clv.get('positive_clv_rate', 0)*100:.1f}%\")
except Exception as e:
    print(f\"❌ Error parsing response: {e}\")
    print(sys.stdin.read())
"

# 7. System Health Summary
echo ""
echo "7️⃣  SYSTEM HEALTH SUMMARY"
echo "--------------------------------------------------------------------"

# Check if sampler is active (look for recent samples)
RECENT_SAMPLES=$(psql $DATABASE_URL -t -c "
  SELECT COUNT(*) FROM clv_closing_feed 
  WHERE ts > NOW() - INTERVAL '10 minutes';
" 2>/dev/null | xargs)

if [ "$RECENT_SAMPLES" -gt 0 ]; then
    echo "✅ CLV Closing Sampler: ACTIVE (${RECENT_SAMPLES} samples in last 10min)"
else
    echo "⏸️  CLV Closing Sampler: IDLE (waiting for matches near kickoff)"
fi

# Check if closing odds are populated
CLOSING_COUNT=$(psql $DATABASE_URL -t -c "SELECT COUNT(*) FROM closing_odds;" 2>/dev/null | xargs)
if [ "$CLOSING_COUNT" -gt 0 ]; then
    echo "✅ Closing Odds: POPULATED (${CLOSING_COUNT} matches)"
else
    echo "⏳ Closing Odds: WAITING FOR DATA"
fi

# Check upcoming matches
UPCOMING=$(psql $DATABASE_URL -t -c "
  SELECT COUNT(DISTINCT match_id) FROM odds_snapshots 
  WHERE match_date > NOW();
" 2>/dev/null | xargs)

if [ "$UPCOMING" -gt 0 ]; then
    echo "✅ Upcoming Matches: ${UPCOMING} matches scheduled"
else
    echo "⚠️  Upcoming Matches: NONE (need collection)"
fi

echo ""
echo "===================================================================="
echo "📋 NEXT STEPS:"
echo ""

if [ "$CLOSING_COUNT" -eq 0 ] && [ "$RECENT_SAMPLES" -gt 0 ]; then
    echo "  • Run aggregation: python populate_closing_odds.py"
elif [ "$UPCOMING" -gt 0 ]; then
    echo "  • Wait for matches to approach kickoff (T-6m to T+2m)"
    echo "  • Closing sampler will collect automatically"
    echo "  • Then run: python populate_closing_odds.py"
else
    echo "  • Trigger collection: python trigger_manual_collection.py"
    echo "  • Wait for upcoming matches"
fi

echo ""
echo "===================================================================="
