# BetGenius AI - Grafana Dashboard Queries
**Starter panel queries for CLV monitoring dashboards**

---

## Panel 1: CLV Alerts Created (Last Hour)
**Type:** Stat Panel  
**Query:**
```promql
sum(increase(clv_alerts_created_total[1h]))
```

**Breakdown by League (Table Panel):**
```promql
sum by (league) (increase(clv_alerts_created_total[1h]))
```

**Breakdown by Outcome (Bar Chart):**
```promql
sum by (outcome) (increase(clv_alerts_created_total[24h]))
```

**Settings:**
- Visualization: Stat / Table / Bar
- Unit: Short
- Thresholds: Green > 5, Yellow 1-5, Red < 1

---

## Panel 2: Closing Odds Capture Rate
**Type:** Gauge  
**Query:**
```promql
closing_capture_rate_pct
```

**Settings:**
- Visualization: Gauge
- Unit: Percent (0-100)
- Min: 0, Max: 100
- Thresholds: Red < 80, Yellow 80-90, Green > 90
- Display: "% of fixtures with closing odds captured (last 24h)"

---

## Panel 3: Odds Snapshot Age (p50, p95, p99)
**Type:** Time Series  
**Query (p95):**
```promql
histogram_quantile(0.95, sum(rate(odds_snapshot_age_seconds_bucket[15m])) by (le))
```

**Query (p50):**
```promql
histogram_quantile(0.50, sum(rate(odds_snapshot_age_seconds_bucket[15m])) by (le))
```

**Query (p99):**
```promql
histogram_quantile(0.99, sum(rate(odds_snapshot_age_seconds_bucket[15m])) by (le))
```

**Settings:**
- Visualization: Time series
- Unit: Seconds (s)
- Legend: "p50", "p95", "p99"
- Target line: 3600s (1 hour - warning), 7200s (2 hours - critical)

---

## Panel 4: TBD Fixtures (Unenriched, Inside 24h)
**Type:** Single Stat  
**Query:**
```promql
tbd_fixtures_unenriched
```

**Settings:**
- Visualization: Stat
- Unit: Short
- Thresholds: Green < 5, Yellow 5-10, Red > 10
- Display: "TBD fixtures approaching kickoff"

---

## Panel 5: CLV Producer Cycle Duration
**Type:** Time Series  
**Query (p95):**
```promql
histogram_quantile(0.95, sum(rate(clv_producer_duration_seconds_bucket[5m])) by (le))
```

**Query (avg):**
```promql
rate(clv_producer_duration_seconds_sum[5m]) / rate(clv_producer_duration_seconds_count[5m])
```

**Settings:**
- Visualization: Time series
- Unit: Seconds (s)
- Legend: "p95 latency", "avg latency"
- Target line: 20s (warning), 30s (critical)

---

## Panel 6: Alert Yield Rate (Alerts per Opportunity)
**Type:** Time Series  
**Query:**
```promql
sum(rate(clv_alerts_created_total[5m])) / sum(rate(clv_opportunities_scanned_total[5m]))
```

**Settings:**
- Visualization: Time series
- Unit: Percent (0.0-1.0)
- Display: "% of opportunities that became alerts"
- Typical range: 5-20% (depends on quality gates)

---

## Panel 7: Alerts by League (Heatmap)
**Type:** Heatmap  
**Query:**
```promql
sum by (league) (increase(clv_alerts_created_total[1h]))
```

**Settings:**
- Visualization: Heatmap
- Color scheme: Green (high activity) to Red (low activity)
- Time buckets: 1 hour
- Shows alert distribution across leagues over time

---

## Panel 8: Snapshot Collection Health
**Type:** Time Series  
**Query (snapshots per minute):**
```promql
sum(rate(odds_snapshot_age_seconds_count[1m])) * 60
```

**Settings:**
- Visualization: Time series
- Unit: Short
- Display: "Odds snapshots collected per minute"
- Expected: ~300-400/min during active hours

---

## Full Dashboard JSON Import

Create a new Grafana dashboard and import this JSON structure:

```json
{
  "dashboard": {
    "title": "BetGenius AI - CLV Monitoring",
    "tags": ["clv", "betting", "alerts"],
    "timezone": "utc",
    "panels": [
      {
        "id": 1,
        "title": "CLV Alerts Created (Last Hour)",
        "type": "stat",
        "targets": [{"expr": "sum(increase(clv_alerts_created_total[1h]))"}],
        "gridPos": {"h": 8, "w": 6, "x": 0, "y": 0}
      },
      {
        "id": 2,
        "title": "Closing Capture Rate",
        "type": "gauge",
        "targets": [{"expr": "closing_capture_rate_pct"}],
        "gridPos": {"h": 8, "w": 6, "x": 6, "y": 0}
      },
      {
        "id": 3,
        "title": "Snapshot Age Percentiles",
        "type": "timeseries",
        "targets": [
          {"expr": "histogram_quantile(0.95, sum(rate(odds_snapshot_age_seconds_bucket[15m])) by (le))", "legendFormat": "p95"},
          {"expr": "histogram_quantile(0.50, sum(rate(odds_snapshot_age_seconds_bucket[15m])) by (le))", "legendFormat": "p50"}
        ],
        "gridPos": {"h": 8, "w": 12, "x": 12, "y": 0}
      },
      {
        "id": 4,
        "title": "TBD Fixtures (<24h)",
        "type": "stat",
        "targets": [{"expr": "tbd_fixtures_unenriched"}],
        "gridPos": {"h": 8, "w": 6, "x": 0, "y": 8}
      },
      {
        "id": 5,
        "title": "Producer Cycle Duration",
        "type": "timeseries",
        "targets": [
          {"expr": "histogram_quantile(0.95, sum(rate(clv_producer_duration_seconds_bucket[5m])) by (le))", "legendFormat": "p95"}
        ],
        "gridPos": {"h": 8, "w": 18, "x": 6, "y": 8}
      }
    ]
  }
}
```

---

## Quick Diagnostics

### Check if metrics are flowing:
```bash
curl http://localhost:8000/metrics | grep clv_
```

### View metrics in Prometheus:
Navigate to: `http://prometheus:9090/graph`  
Query: `clv_alerts_created_total`

### Import to Grafana:
1. Add Prometheus data source
2. Import dashboard JSON above
3. Set refresh interval: 30s
4. Save dashboard

---

**These 8 panels give you 90% observability** with minimal setup. Add more panels as needed for deeper analysis!
