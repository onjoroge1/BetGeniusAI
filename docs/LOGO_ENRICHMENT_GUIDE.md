# Team Logo Enrichment Guide

## ✅ Correct Command (Verified Working!)

```bash
curl -X POST "http://localhost:8000/admin/enrich-team-logos?limit=200" \
  -H "Authorization: Bearer betgenius_secure_key_2024"
```

### Response Example:
```json
{
  "status": "success",
  "enrichment": {
    "teams_processed": 200,
    "teams_enriched": 150,
    "teams_failed": 50,
    "api_calls": 200
  },
  "linking": {
    "fixtures_linked": 1200,
    "home_linked": 600,
    "away_linked": 600
  },
  "message": "Enriched 150/200 teams, linked 1200 fixtures"
}
```

---

## How It Works

### 1. **Fetches teams** without logos from the `teams` table
   - Filters for `logo_url IS NULL AND api_football_team_id IS NULL`
   - Processes up to `limit` teams per request

### 2. **Enrichment Service** (3-pass fuzzy matching)
   - **Pass 1**: Exact name match within same league
   - **Pass 2**: Normalized name match (handles "1. FC Bayern" → "Bayern")
   - **Pass 3**: Normalized name match across all leagues

### 3. **Logo download** from API-Football
   - Fetches team metadata including logo URL
   - Stores `logo_url` and `api_football_team_id` in database

### 4. **Auto-linking** to fixtures
   - Links teams to existing fixtures via `home_team_id` and `away_team_id`
   - Updates all past and future fixtures automatically

---

## Important Notes

### ⏱️ **Rate Limiting**
- Service has **1-second delay** between API calls (to respect API-Football limits)
- 200 teams = **~200+ seconds** (3.5 minutes minimum)
- **Timeouts are expected** - this is normal behavior!

### 🔄 **Background Service**
The TeamEnrichmentService runs **continuously in the background** via the scheduler:
- Automatically enriches teams as they appear in fixtures
- No manual intervention needed for new teams
- Check progress with: `GET /admin/teams/stats`

### 📊 **Current Status**
```
Total teams: 577
Teams with logos: 173 (30.0%)
Teams without logos: 404 (70.0%)
```

---

## Recommended Workflow

### For bulk enrichment (initial setup):
```bash
# Process 200 teams at a time
curl -X POST "http://localhost:8000/admin/enrich-team-logos?limit=200" \
  -H "Authorization: Bearer betgenius_secure_key_2024"

# Wait 4-5 minutes for completion
# Then repeat for next batch
```

### For monitoring progress:
```bash
# Check enrichment stats
curl -H "Authorization: Bearer betgenius_secure_key_2024" \
  "http://localhost:8000/admin/teams/stats"
```

---

## Troubleshooting

### ❌ Timeout errors
**Normal!** The endpoint takes 3+ minutes for 200 teams. The enrichment continues server-side even if your HTTP request times out.

### ❌ Low match rate
Some teams may not match if:
- Team name differs significantly between data sources
- Team doesn't exist in API-Football database
- League mapping is incorrect

### ✅ Verify success
Check the database directly:
```sql
SELECT COUNT(*) as enriched 
FROM teams 
WHERE logo_url IS NOT NULL;
```

---

## Pro Tips

1. **Start small**: Test with `limit=10` first to verify it works
2. **Be patient**: Large batches (200+) take 5+ minutes
3. **Check logs**: Background service logs show enrichment progress
4. **Let it run**: The background scheduler handles ongoing enrichment automatically
