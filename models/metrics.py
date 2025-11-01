"""
Phase 1 & Phase 2 System Metrics
Prometheus metrics for CLV monitoring and live betting intelligence
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

# ==== PHASE 2: LIVE BETTING INTELLIGENCE METRICS ====

# Momentum calculation runs
momentum_calculations_total = Counter(
    "momentum_calculations_total",
    "Total momentum calculations attempted",
    ["status"]
)

# Momentum calculation processing time
momentum_calculation_duration = Histogram(
    "momentum_calculation_duration_seconds",
    "Duration of momentum calculation",
    buckets=[0.1, 0.25, 0.5, 1.0, 2.0, 5.0]
)

# Current momentum differential (home - away)
momentum_differential = Gauge(
    "momentum_differential",
    "Current momentum differential by match",
    ["match_id"]
)

# Live market generation runs
live_market_generations_total = Counter(
    "live_market_generations_total",
    "Total live market generation attempts",
    ["status"]
)

# Live market generation processing time
live_market_generation_duration = Histogram(
    "live_market_generation_duration_seconds",
    "Duration of live market generation",
    buckets=[0.1, 0.25, 0.5, 1.0, 2.0, 5.0]
)

# WebSocket active connections
websocket_connections = Gauge(
    "websocket_connections_active",
    "Number of active WebSocket connections"
)

# WebSocket messages sent
websocket_messages_sent = Counter(
    "websocket_messages_sent_total",
    "Total WebSocket messages broadcast",
    ["match_id", "message_type"]
)

# Fixture ID resolution success rate
fixture_resolution_attempts = Counter(
    "fixture_resolution_attempts_total",
    "Fixture ID resolution attempts",
    ["status", "method"]
)
