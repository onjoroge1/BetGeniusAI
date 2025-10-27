"""
CLV System Metrics
Minimal Prometheus metrics for Phase 2 observability
"""

from prometheus_client import Counter, Gauge, Histogram

# Alert creation tracking
clv_alerts_created = Counter(
    "clv_alerts_created_total", 
    "CLV alerts created", 
    ["league", "outcome"]
)

# Odds snapshot age (on winning alert)
odds_snapshot_age = Histogram(
    "odds_snapshot_age_seconds", 
    "Age of snapshots on winning alert",
    buckets=[60, 300, 600, 1200, 1800, 3600, 7200]  # 1m, 5m, 10m, 20m, 30m, 1h, 2h
)

# TBD fixtures approaching kickoff
tbd_fixtures_unenriched = Gauge(
    "tbd_fixtures_unenriched", 
    "Count of fixtures with TBD inside 24h"
)

# Closing line capture rate
closing_capture_rate = Gauge(
    "closing_capture_rate_pct", 
    "Share of fixtures where closing was captured in last 24h"
)

# CLV opportunities scanned
clv_opportunities_scanned = Counter(
    "clv_opportunities_scanned_total",
    "Total opportunities analyzed",
    ["suppression_reason"]
)

# Producer cycle duration
clv_producer_duration = Histogram(
    "clv_producer_duration_seconds",
    "Duration of CLV producer cycle",
    buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 30.0]
)
