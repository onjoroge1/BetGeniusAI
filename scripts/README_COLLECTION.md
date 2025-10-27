# Manual Data Collection Scripts

## Quick Start

### Collect Last Week's Data
```bash
# Collect last 7 days from all Tier 1 leagues (Premier League, La Liga, Serie A, etc.)
python scripts/collect_last_week.py

# Collect last 14 days
python scripts/collect_last_week.py --days 14

# Collect from specific leagues only (Premier League + La Liga)
python scripts/collect_last_week.py --leagues 39,140

# Collect last month
python scripts/collect_last_week.py --days 30
```

## What It Does

The script:
1. ✅ Fetches finished matches from the past N days
2. ✅ Retrieves odds data for each match
3. ✅ Extracts H/D/A consensus odds
4. ✅ Inserts into `historical_odds` table
5. ✅ Automatically skips duplicates
6. ✅ Shows detailed progress and summary

## Default Tier 1 Leagues

The script collects from these leagues by default:
- 39: Premier League (England)
- 140: La Liga (Spain)
- 135: Serie A (Italy)
- 78: Bundesliga (Germany)
- 61: Ligue 1 (France)
- 94: Primeira Liga (Portugal)
- 203: Super Lig (Turkey)
- 88: Eredivisie (Netherlands)

## Example Output

```
============================================================
📥 MANUAL DATA COLLECTION - LAST WEEK
============================================================

📅 Date Range: 2025-10-20 to 2025-10-27 (7 days)
🎯 Leagues: 8 leagues
🗄️  Database: postgresql://...
🔑 API Key: sk_test_...

📊 Processing League ID: 39
   Date range: 2025-10-20 to 2025-10-27
   Found 10 finished matches

   🏟️  Arsenal vs Chelsea
      Fixture ID: 1234567, Date: 2025-10-26T15:00:00+00:00
      📊 Odds: H=1.95, D=3.60, A=4.20
   ✅ Inserted: Arsenal vs Chelsea (H)

   🏟️  Liverpool vs Manchester United
      Fixture ID: 1234568, Date: 2025-10-27T17:30:00+00:00
      📊 Odds: H=1.70, D=3.90, A=5.50
   ✅ Inserted: Liverpool vs Manchester United (H)

...

============================================================
📊 COLLECTION SUMMARY
============================================================
Leagues processed:     8
Matches found:         87
Matches with odds:     82
Matches inserted:      78
Matches skipped:       9
Errors:                0
============================================================

✅ SUCCESS: Added 78 new matches to historical_odds
💡 Next step: Run model retraining with updated dataset
```

## Requirements

Environment variables must be set:
- `DATABASE_URL` - PostgreSQL connection string
- `RAPIDAPI_KEY` - API-Football RapidAPI key

These are automatically available in your Replit environment.

## After Collection

Once you've added new data:

1. **Check dataset size:**
```bash
psql $DATABASE_URL -c "SELECT COUNT(*) FROM historical_odds;"
```

2. **Retrain models:**
```bash
curl -X POST http://localhost:8000/admin/retrain-models \
  -H "X-API-Key: YOUR_API_KEY"
```

3. **Monitor new model performance:**
```bash
curl http://localhost:8000/metrics/evaluation \
  -H "X-API-Key: YOUR_API_KEY"
```

## Tips

### Collect Specific Date Range
Edit the script to use custom dates:
```python
date_from = "2025-10-01"
date_to = "2025-10-31"
```

### Rate Limiting
The script includes automatic delays between API calls to respect rate limits. For large collections (30+ days), expect 5-10 minutes per league.

### Error Handling
If API calls fail:
- Check your RAPIDAPI_KEY is valid
- Verify you have API credits remaining
- Check internet connectivity
- Try reducing the date range (--days 3)

## Troubleshooting

**"No finished matches found"**
- Normal for leagues not currently in season
- Try different date range
- Verify league ID is correct

**"No odds data available"**
- Some matches may not have odds recorded
- Old matches (>6 months) may have limited odds data
- Try more recent date ranges

**"Already in database"**
- Script automatically skips duplicates
- This is expected on re-runs
- No action needed

**API rate limit errors**
- Reduce --days parameter
- Run script in smaller batches
- Add delays between league collections
