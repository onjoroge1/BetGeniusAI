#!/bin/bash
# Closing Odds Quick Reference Commands

API_KEY="betgenius_secure_key_2024"
BASE_URL="http://localhost:8000"

echo "📊 CLOSING ODDS & CLV - QUICK COMMANDS"
echo "========================================"

echo ""
echo "1️⃣  Check Current Status"
echo "----------------------------------------"

echo "Closing feed samples:"
psql $DATABASE_URL -c "SELECT COUNT(*) FROM clv_closing_feed;"

echo "Closing odds (aggregated):"
psql $DATABASE_URL -c "SELECT COUNT(*) FROM closing_odds;"

echo "Upcoming matches:"
psql $DATABASE_URL -c "SELECT COUNT(*) FROM odds_snapshots WHERE match_date > NOW();"

echo ""
echo "2️⃣  Populate Closing Odds"
echo "----------------------------------------"
echo "Run when clv_closing_feed has data:"
echo "  python populate_closing_odds.py"

echo ""
echo "3️⃣  Test Enhanced Metrics with CLV"
echo "----------------------------------------"
curl -s "${BASE_URL}/metrics/evaluation?window=all" \
  -H "Authorization: Bearer ${API_KEY}" | python -m json.tool

echo ""
echo "4️⃣  View Closing Odds Data (if available)"
echo "----------------------------------------"
psql $DATABASE_URL -c "
  SELECT match_id, 
         h_close_odds, d_close_odds, a_close_odds,
         method_used, avg_books_closing
  FROM closing_odds 
  LIMIT 5;
"

echo ""
echo "✅ All commands complete!"
