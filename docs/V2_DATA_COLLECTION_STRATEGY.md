# V2 Data Collection Strategy
**Goal:** Continuous model improvement through systematic data expansion

## Collection Priorities

### Tier 1 Leagues (Daily Collection)
**Target:** Leagues feeding your selective V2 bets
- Premier League (39)
- La Liga (140)
- Serie A (135)
- Bundesliga (78)
- Ligue 1 (61)
- Primeira Liga (94)
- Super Lig (203)
- Eredivisie (88)

**Why:** These leagues have:
- Highest market liquidity (12+ bookmakers)
- Best closing line accuracy
- Most reliable historical features
- Maximum user engagement

### Tier 2 Leagues (Weekly Collection)
- Championship, Serie B, La Liga 2, Bundesliga 2
- Major cup competitions (FA Cup, Copa del Rey, etc.)

**Why:** Cup matches show market divergence from league patterns

---

## Collection Schedule

### **Daily Automated (24h Lag)**
```
Trigger: Every day at 3 AM UTC
Target: Completed fixtures from previous day
Process:
  1. Fetch finished matches (status='finished')
  2. Validate closing odds present (>6 bookmakers for Tier 1)
  3. Verify settlement (actual_outcome not null)
  4. Dedupe by (match_id, bookmaker, market)
  5. Ingest to historical_odds table
```

**Why 24h lag?** Closing odds need time to stabilize, settlements to finalize.

### **Weekly Health Check**
```
Trigger: Sunday 2 AM UTC
Metrics:
  - Collection coverage by league (target: >95%)
  - Missing closing odds count
  - Settlement completion rate
  - Feature completeness ratio
```

### **Quarterly Retraining**
```
Trigger: Every 2,500-3,000 new matches OR quarter-end
Process:
  1. Snapshot current dataset (parquet export)
  2. Run LightGBM 5-fold CV sweep
  3. Validate on holdout set (last 30 days)
  4. Gate promotion: ECE < 0.08, Δ LogLoss ≤ -0.02
  5. Deploy if gates pass
```

---

## Automation Approach

### **Recommended: 90% Automated, 10% Manual**

#### Automated Daily Collector
```python
# Add to scheduler (utils/scheduler.py)
async def daily_training_collection():
    """
    Collect yesterday's completed matches for training
    Runs daily at 3 AM UTC
    """
    yesterday = datetime.now() - timedelta(days=1)
    
    tier1_leagues = [39, 140, 135, 78, 61, 94, 203, 88]
    
    for league_id in tier1_leagues:
        # Fetch finished matches from yesterday
        await collect_finished_matches(
            league_id=league_id,
            date_from=yesterday.strftime('%Y-%m-%d'),
            date_to=yesterday.strftime('%Y-%m-%d'),
            min_bookmakers=6  # Quality gate
        )
```

#### Manual Backfill Triggers
- Automated coverage drops below 95%
- New league activation
- Historical gap discovery (missing seasons)

---

## Data Quality Gates

### **Pre-Ingestion Validation**
```sql
-- Only accept matches with:
-- 1. Complete consensus odds (all 3 outcomes)
-- 2. Verified settlement (actual_outcome)
-- 3. Minimum bookmaker coverage
-- 4. No duplicate entries

INSERT INTO historical_odds (...)
SELECT ...
FROM staging_matches sm
WHERE sm.h_odds_consensus IS NOT NULL
  AND sm.d_odds_consensus IS NOT NULL
  AND sm.a_odds_consensus IS NOT NULL
  AND sm.actual_outcome IN ('H', 'D', 'A')
  AND sm.bookmaker_count >= 6
  AND NOT EXISTS (
      SELECT 1 FROM historical_odds ho
      WHERE ho.match_id = sm.match_id
  );
```

### **Post-Ingestion Monitoring**
```sql
-- Weekly health dashboard
SELECT 
    league_name,
    COUNT(*) as matches_collected,
    AVG(bookmaker_count) as avg_books,
    SUM(CASE WHEN actual_outcome IS NULL THEN 1 ELSE 0 END) as unsettled,
    MIN(match_date) as earliest,
    MAX(match_date) as latest
FROM historical_odds
WHERE ingested_at > NOW() - INTERVAL '7 days'
GROUP BY league_name;
```

---

## Storage & Retention

### **Hot Data (PostgreSQL)**
- Last 2 seasons of matches (fast feature extraction)
- Complete odds history + settlements
- Indexed by (league_id, match_date, team_id)

### **Warm Data (Parquet + Object Storage)**
- Seasons 3+ archived as parquet files
- Partitioned by season/month
- Monthly snapshots for rollback
- 2-year retention (cost: $0.02/GB/month)

### **Feature Matrices (Cached)**
```
Format: Parquet files
Structure: /features/{league_id}/{season}/{month}.parquet
Columns: match_id, 62 features, labels (H/D/A)
Retention: Rolling 3 years
Update: Monthly batch refresh
```

---

## Retraining Triggers

### **Volume-Based (Primary)**
```
IF new_labeled_matches >= 2,500:
    THEN trigger_retraining()
```

**Calculation:**
- 10 leagues × 38 matches/week × 4 weeks = ~1,520 matches/month
- Trigger hits every ~1.6 months naturally

### **Calendar-Based (Fallback)**
```
IF end_of_quarter AND new_labeled_matches >= 1,000:
    THEN trigger_retraining()
```

### **Emergency (Manual)**
- Model performance degradation (weekly ECE check)
- New leagues added to focus list
- Major bookmaker coverage changes

---

## Implementation Checklist

### Phase 1: Automated Daily Collection
- [ ] Add `daily_training_collection()` job to scheduler
- [ ] Set cron: `0 3 * * *` (3 AM UTC daily)
- [ ] Configure tier 1 league list
- [ ] Add bookmaker count validation (min 6)
- [ ] Test with 1-week backfill

### Phase 2: Weekly Health Monitoring
- [ ] Create `weekly_collection_health()` job
- [ ] Add Grafana panel for coverage metrics
- [ ] Set alert: coverage <95% for 2 consecutive weeks
- [ ] Document manual backfill procedure

### Phase 3: Quarterly Retraining Automation
- [ ] Add match count tracker (Prometheus metric)
- [ ] Create `trigger_v2_retraining()` function
- [ ] Implement promotion gate checks
- [ ] Add rollback mechanism (snapshot restore)

### Phase 4: Storage Optimization
- [ ] Migrate seasons 3+ to parquet
- [ ] Set up monthly partition cleanup
- [ ] Configure object storage bucket
- [ ] Test feature matrix caching

---

## Expected Growth

### **Current State**
- Training dataset: 36,942 matches
- Coverage: 14 leagues, 1993-2025
- Update frequency: Manual

### **After 6 Months (Automated)**
- Training dataset: ~46,000 matches (+25%)
- Coverage: Same 14 leagues, continuous
- Update frequency: Daily automatic
- Retraining: 3 cycles completed

### **After 12 Months**
- Training dataset: ~55,000 matches (+50%)
- New leagues: 2-3 additions
- Model version: V2.3 or V2.4
- Accuracy target: 72-74% selective

---

## Cost Estimates

### **API Calls (The Odds API + API-Football)**
- Daily: ~200 finished matches × 2 APIs = 400 calls/day
- Monthly: ~12,000 calls
- Cost: ~$60/month (at $0.005/call)

### **Storage (PostgreSQL + Object Storage)**
- Hot data (Postgres): ~5 GB (free tier)
- Warm data (Parquet): ~2 GB × $0.02 = $0.04/month
- Total: ~$0.04/month

### **Compute (Retraining)**
- Quarterly LightGBM sweep: ~2 hours @ $0.10/hour
- Annual: 4 × $0.20 = $0.80/year

**Total Monthly Cost: ~$60** (mostly API calls)

---

## Success Metrics

### **Data Quality**
- Collection coverage: >95% of scheduled fixtures
- Closing odds availability: >90% of collected matches
- Settlement completion: 100% within 48h
- Deduplication rate: 0% (zero duplicates)

### **Model Performance**
- Selective accuracy (conf>=0.62): 70% → 72%+ in 6 months
- ECE (calibration): <0.08 consistently
- 3-way overall accuracy: 52.7% → 54%+
- EV rate: Positive across all deciles

### **Operational Health**
- Automated collection uptime: >99%
- Manual intervention: <5% of total matches
- Retraining frequency: Every 6-8 weeks
- Promotion success rate: >75% of candidates

---

## Quick Reference

### Commands
```bash
# Manual backfill (1 league, 1 season)
curl -X POST "http://localhost:8000/admin/collect-training-data?league_id=39&season=2025" \
  -H "X-API-Key: YOUR_KEY"

# Trigger retraining
curl -X POST "http://localhost:8000/admin/retrain-models" \
  -H "X-API-Key: YOUR_KEY"

# Check collection health
psql $DATABASE_URL -c "
  SELECT league_name, COUNT(*), MAX(match_date)
  FROM historical_odds
  WHERE ingested_at > NOW() - INTERVAL '7 days'
  GROUP BY league_name;
"
```

### Monitoring Queries
See `scripts/clv_qa_queries.sql` for full diagnostic suite.

---

**Bottom Line:** Automate daily collection from tier 1 leagues with 24h lag, run weekly health checks, trigger quarterly retraining after 2,500+ new matches. This keeps V2 improving while staying production-safe.
