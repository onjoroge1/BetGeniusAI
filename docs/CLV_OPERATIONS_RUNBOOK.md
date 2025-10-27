# BetGenius AI - CLV System Operations Runbook
**Phase 2: Production Troubleshooting Guide**

---

## Quick Reference

| Alert | Severity | First Action | Runbook Section |
|-------|----------|--------------|-----------------|
| CLVNoAlertsButSnapshotsFlowing | 🔴 Page | Check logs for errors | [Flatline](#symptom-no-alerts-15m-snapshots-flowing) |
| ClosingOddsCaptureDegraded | 🟡 Ticket | Verify time sync | [Closing Capture](#symptom-closing-capture-85) |
| TBDFixtureBuildupNearKickoff | 🟡 Ticket | Run batch enrichment | [TBD Buildup](#symptom-high-tbd-24h) |
| CLVProducerSlowCycle | 🟡 Ticket | Check DB performance | [Slow Cycles](#symptom-clv-producer-slow-30s) |

---

## Symptom: No Alerts 15m, Snapshots Flowing

**Alert:** `CLVNoAlertsButSnapshotsFlowing`  
**Severity:** 🔴 Page  
**Impact:** Missing CLV opportunities - users not getting value alerts

### Diagnosis

1. **Check Prometheus metrics:**
   ```promql
   # Are snapshots flowing?
   sum(rate(odds_snapshot_age_seconds_count[10m])) > 0
   
   # Are alerts created?
   sum(rate(clv_alerts_created_total[15m]))
   ```

2. **Check producer logs:**
   ```bash
   grep "CLV Producer complete" /tmp/logs/*.log | tail -5
   ```
   
   Look for structured output:
   ```
   opps=27, alerts=0, tbd_<24h=21, fixtures=9, duration=11560ms
   Suppressions: LOW_CLV=15, STALE=8, LOW_BOOKS=4
   ```

3. **Run candidates SQL:**
   ```sql
   SELECT COUNT(*) as candidates
   FROM odds_snapshots os
   JOIN fixtures f USING(match_id)
   WHERE f.kickoff_at BETWEEN NOW() AND NOW() + INTERVAL '72 hours'
     AND os.ts_snapshot > NOW() - INTERVAL '2 hours'
     AND f.status = 'scheduled'
     AND f.home_team NOT ILIKE 'TBD%' 
     AND f.away_team NOT ILIKE 'TBD%';
   ```
   
   **Expected:** > 100 rows

### Root Causes

| Symptom in Logs | Root Cause | Fix |
|-----------------|------------|-----|
| `LOW_CLV=high` | Quality gates too strict | Review CLV thresholds by league tier |
| `STALE=high` | Staleness window too tight | Check `CLV_MIN_STALENESS_SEC` (default 600s) |
| `LOW_BOOKS=high` | Insufficient bookmaker coverage | Lower tier minimums or verify data collection |
| `tbd_<24h=high` | TBD backlog blocking analysis | Run enrichment (see [TBD section](#symptom-high-tbd-24h)) |
| `candidates=0` | No upcoming fixtures or odds | Verify fixtures exist, check odds collector |

### Quick Fixes

**If staleness too tight:**
```bash
# Temporarily widen staleness window
export CLV_MAX_STALENESS_SEC=10800  # 3 hours instead of 2
```

**If TBD backlog:**
```bash
curl -X POST http://localhost:8000/admin/enrich-tbd-batch?limit=50 \
  -H "Authorization: Bearer YOUR_API_KEY"
```

**If quality gates too strict:**
Review and adjust in `models/clv_club.py`:
```python
CLV_THRESHOLD_TIER1 = 50  # Lower from 80 bps
CLV_THRESHOLD_TIER2 = 40  # Lower from 60 bps
```

---

## Symptom: Closing Capture <85%

**Alert:** `ClosingOddsCaptureDegraded`  
**Severity:** 🟡 Ticket  
**Impact:** Cannot accurately measure realized CLV performance

### Diagnosis

1. **Check current capture rate:**
   ```sql
   SELECT 
       COUNT(DISTINCT f.match_id) as total_finished,
       COUNT(DISTINCT co.match_id) as with_closing,
       ROUND(COUNT(DISTINCT co.match_id) * 100.0 / NULLIF(COUNT(DISTINCT f.match_id), 0), 1) as capture_rate_pct
   FROM fixtures f
   LEFT JOIN closing_odds co USING(match_id)
   WHERE f.kickoff_at > NOW() - INTERVAL '24 hours'
     AND f.kickoff_at < NOW()
     AND f.status = 'finished';
   ```

2. **Check closing capture job logs:**
   ```bash
   grep "Closing capture" /tmp/logs/*.log | tail -20
   ```

3. **Verify time sync:**
   ```bash
   date -u  # Should match actual UTC time
   ```

### Root Causes

| Symptom | Root Cause | Fix |
|---------|------------|-----|
| Job not running | Scheduler disabled or crashed | Restart scheduler, verify `ENABLE_CLV_CLUB=true` |
| Window too narrow | 90s window misses late odds | Widen to 120s in `closing_capture.py` |
| Time drift | System clock out of sync | Sync NTP, restart services |
| Sparse odds collection | Not collecting near kickoff | Verify collector runs every 60s |

### Quick Fixes

**Widen capture window:**
Edit `models/closing_capture.py`:
```python
# Change from ±90s to ±120s
WHERE f.kickoff_at BETWEEN NOW() - INTERVAL '120 seconds' 
                       AND NOW() + INTERVAL '120 seconds'
```

**Manual capture for recent matches:**
```sql
-- Backfill closing odds for matches in last hour
INSERT INTO closing_odds (match_id, bookmaker_id, market, h_odds_dec, d_odds_dec, a_odds_dec, ts_closing)
SELECT DISTINCT ON (os.match_id, os.bookmaker_id, os.market)
    os.match_id, os.bookmaker_id, os.market,
    os.h_odds_dec, os.d_odds_dec, os.a_odds_dec,
    os.ts_snapshot
FROM odds_snapshots os
JOIN fixtures f USING(match_id)
WHERE f.kickoff_at > NOW() - INTERVAL '1 hour'
  AND f.kickoff_at < NOW()
  AND os.ts_snapshot > f.kickoff_at - INTERVAL '5 minutes'
ORDER BY os.match_id, os.bookmaker_id, os.market, os.ts_snapshot DESC
ON CONFLICT (match_id, bookmaker_id, market) DO NOTHING;
```

---

## Symptom: High TBD <24h

**Alert:** `TBDFixtureBuildupNearKickoff`  
**Severity:** 🟡 Ticket  
**Impact:** Reduced CLV coverage - TBD fixtures excluded from scanning

### Diagnosis

1. **Check TBD count:**
   ```sql
   SELECT COUNT(*) as tbd_count,
          MIN(kickoff_at) as earliest_ko
   FROM fixtures
   WHERE kickoff_at BETWEEN NOW() AND NOW() + INTERVAL '24 hours'
     AND (home_team ILIKE 'TBD%' OR away_team ILIKE 'TBD%');
   ```

2. **Check enrichment queue:**
   ```bash
   curl http://localhost:8000/admin/enrich-tbd-batch?limit=5 \
     -H "Authorization: Bearer YOUR_API_KEY"
   ```

3. **Verify API-Football health:**
   ```bash
   curl -X GET "https://v3.football.api-sports.io/status" \
     -H "x-apisports-key: YOUR_KEY"
   ```

### Root Causes

| Symptom | Root Cause | Fix |
|---------|------------|-----|
| API timeout | Provider degraded | Use single endpoint with retries |
| High failure rate | Data not available yet | Wait, or raise `CLV_TBD_ALLOW_BEFORE_HOURS` |
| Queue stalled | Circuit breaker tripped | Reset by running single enrichments |
| Wrong league | Non-covered league | Skip or add league to API-Football config |

### Quick Fixes

**Run batch enrichment:**
```bash
# Safe default: 50 fixtures
curl -X POST http://localhost:8000/admin/enrich-tbd-batch?limit=50 \
  -H "Authorization: Bearer YOUR_API_KEY"
```

**Fix individual fixture:**
```bash
curl -X POST "http://localhost:8000/admin/enrich-tbd-one?match_id=1444606" \
  -H "Authorization: Bearer YOUR_API_KEY"
```

**Temporarily allow TBD (if <12h from KO):**
```bash
# NOT RECOMMENDED - defeats T-12h fail-safe
# Only use if TBD enrichment is truly broken
export CLV_TBD_ALLOW_BEFORE_HOURS=6  # Allow until T-6h
```

---

## Symptom: CLV Producer Slow (>30s)

**Alert:** `CLVProducerSlowCycle`  
**Severity:** 🟡 Ticket  
**Impact:** Delayed CLV alerts - users get stale opportunities

### Diagnosis

1. **Check cycle timings in logs:**
   ```bash
   grep "duration=" /tmp/logs/*.log | tail -5
   ```
   
   Look for breakdown:
   ```
   Stage timings: gather=8200ms, analyze=2100ms
   ```

2. **Check database query performance:**
   ```sql
   EXPLAIN ANALYZE
   SELECT os.match_id, os.bookmaker_id, os.h_odds_dec, os.d_odds_dec, os.a_odds_dec
   FROM odds_snapshots os
   JOIN fixtures f USING(match_id)
   WHERE f.kickoff_at BETWEEN NOW() AND NOW() + INTERVAL '72 hours'
     AND os.ts_snapshot > NOW() - INTERVAL '2 hours'
   LIMIT 100;
   ```
   
   **Expected:** < 50ms execution time, index scans

3. **Check index usage:**
   ```sql
   SELECT schemaname, tablename, indexname, idx_scan
   FROM pg_stat_user_indexes
   WHERE tablename = 'odds_snapshots'
   ORDER BY idx_scan DESC;
   ```

### Root Causes

| Symptom | Root Cause | Fix |
|---------|------------|-----|
| `gather_ms` high | Missing index on ts_snapshot | Recreate index (see below) |
| `analyze_ms` high | Too many opportunities | Raise quality gates |
| Sequential scans | Indexes not being used | Run VACUUM ANALYZE, check query plans |
| High row count | Partition table needed | Implement monthly partitioning |

### Quick Fixes

**Recreate critical index:**
```sql
-- Drop and recreate if not being used
DROP INDEX IF EXISTS idx_odds_snapshots_ts;
CREATE INDEX idx_odds_snapshots_ts ON odds_snapshots(ts_snapshot DESC);

-- Force statistics update
VACUUM ANALYZE odds_snapshots;
```

**Reduce lookback window temporarily:**
```bash
# Edit CLV producer query to use 1h instead of 2h
# models/clv_alert_producer.py line ~200:
# WHERE os.ts_snapshot > NOW() - INTERVAL '1 hour'
```

---

## Symptom: High Suppression Rate (Alert Yield <5%)

**Alert:** `HighCLVSuppressionRate`  
**Severity:** ℹ️ Info  
**Impact:** Low alert volume - may be missing opportunities

### Diagnosis

1. **Check suppression breakdown:**
   ```bash
   grep "Suppressions:" /tmp/logs/*.log | tail -10
   ```

2. **Analyze CLV distribution:**
   ```sql
   SELECT 
       CASE 
           WHEN (payload->>'clv_bps')::float < 50 THEN '<50bps'
           WHEN (payload->>'clv_bps')::float < 100 THEN '50-100bps'
           WHEN (payload->>'clv_bps')::float < 200 THEN '100-200bps'
           ELSE '>200bps'
       END as clv_bucket,
       COUNT(*) as opportunities
   FROM clv_alerts
   WHERE created_at > NOW() - INTERVAL '24 hours'
   GROUP BY 1
   ORDER BY 1;
   ```

### Tuning Guide

**If mostly LOW_CLV suppressions:**
- Review thresholds in `models/clv_club.py`
- Consider league-specific calibration
- Validate consensus quality

**If mostly LOW_STABILITY suppressions:**
- Check if historical data is available
- Lower stability threshold from 0.8 to 0.6

**If mostly LOW_BOOKS suppressions:**
- Verify bookmaker coverage by league
- Adjust tier minimums if needed

---

## Emergency Commands

### Restart CLV System
```bash
# Restart workflow
systemctl restart betgenius-server  # or your process manager

# Verify health
curl http://localhost:8000/health
curl http://localhost:8000/metrics | grep clv_
```

### Clear Stale Alerts
```sql
-- Archive all expired alerts immediately
WITH archived AS (
    DELETE FROM clv_alerts 
    WHERE expires_at < NOW()
    RETURNING *
)
INSERT INTO clv_alerts_history 
SELECT * FROM archived;
```

### Reset Metrics
```bash
# Restart Prometheus to reset counters
systemctl restart prometheus

# Or clear specific metrics via API (if configured)
curl -X POST http://localhost:9090/api/v1/admin/tsdb/delete_series \
  -d 'match[]=clv_alerts_created_total'
```

---

## Monitoring Dashboards

### Grafana Quick Links
- **CLV Overview:** http://grafana/d/clv-overview
- **Alert Yield:** http://grafana/d/clv-yield
- **System Health:** http://grafana/d/clv-health

### Key Queries
```promql
# Alerts per hour (by league)
sum by (league) (increase(clv_alerts_created_total[1h]))

# Producer latency p95
histogram_quantile(0.95, sum(rate(clv_producer_duration_seconds_bucket[5m])) by (le))

# Closing capture rate
closing_capture_rate_pct

# TBD buildup
tbd_fixtures_unenriched
```

---

## On-Call Escalation

| Issue Severity | Response Time | Escalation Path |
|----------------|---------------|-----------------|
| 🔴 Page (flatline) | 15 minutes | Platform team → Engineering lead |
| 🟡 Ticket (degraded) | 2 hours | Platform team (business hours) |
| ℹ️ Info (tuning) | Next business day | Data science team |

**Contact:** platform-oncall@betgenius.ai

---

**Last Updated:** October 27, 2025  
**Maintained By:** Platform Team
