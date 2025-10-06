#!/bin/bash
# Quick Closing Odds Status Check

echo "📊 CLOSING ODDS QUICK STATUS"
echo "========================================"

echo ""
echo "Schema & Indexes:"
psql $DATABASE_URL -c "SELECT indexname FROM pg_indexes WHERE tablename IN ('clv_closing_feed', 'closing_odds') ORDER BY indexname;" 2>/dev/null

echo ""
echo "Data Counts:"
psql $DATABASE_URL -c "SELECT 'clv_closing_feed' as table_name, COUNT(*) as rows FROM clv_closing_feed UNION ALL SELECT 'closing_odds', COUNT(*) FROM closing_odds;" 2>/dev/null

echo ""
echo "Upcoming Matches:"
psql $DATABASE_URL -c "SELECT COUNT(DISTINCT match_id) as upcoming FROM odds_snapshots WHERE match_date > NOW();" 2>/dev/null

echo ""
echo "Status:"
FEED=$(psql $DATABASE_URL -t -c "SELECT COUNT(*) FROM clv_closing_feed;" 2>/dev/null | xargs)
ODDS=$(psql $DATABASE_URL -t -c "SELECT COUNT(*) FROM closing_odds;" 2>/dev/null | xargs)

if [ "$ODDS" -gt 0 ]; then
    echo "  ✅ Closing odds populated: ${ODDS} matches"
elif [ "$FEED" -gt 0 ]; then
    echo "  ⏳ Closing feed has ${FEED} samples - run: python populate_closing_odds.py"
else
    echo "  ⏸️  Waiting for matches near kickoff (T-6m to T+2m window)"
fi
