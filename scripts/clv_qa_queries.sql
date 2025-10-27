-- BetGenius AI - CLV System QA Queries
-- Phase 2: Quick diagnostic queries for common investigations
-- Run in psql or pgAdmin for instant system health insights

-- ============ ALERT VOLUME & YIELD ============

-- Alert yield by league (last 24h)
SELECT 
    league as league_id,
    COUNT(*) as alerts_24h,
    ROUND(AVG((clv_pct)), 2) as avg_clv_pct,
    ROUND(AVG(stability), 3) as avg_stability,
    MIN(created_at) as first_alert,
    MAX(created_at) as last_alert
FROM clv_alerts
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY league
ORDER BY alerts_24h DESC;

-- Alert distribution by outcome (last 24h)
SELECT 
    outcome,
    COUNT(*) as alert_count,
    ROUND(AVG(clv_pct), 2) as avg_clv_pct,
    COUNT(*) * 100.0 / SUM(COUNT(*)) OVER () as pct_of_total
FROM clv_alerts
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY outcome
ORDER BY alert_count DESC;

-- Hourly alert volume (last 24h)
SELECT 
    date_trunc('hour', created_at) as hour,
    COUNT(*) as alerts,
    COUNT(DISTINCT match_id) as matches,
    ROUND(AVG(clv_pct), 2) as avg_clv
FROM clv_alerts
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY date_trunc('hour', created_at)
ORDER BY hour DESC;

-- ============ DATA QUALITY ============

-- TBD fixtures by time window
SELECT 
    CASE 
        WHEN kickoff_at < NOW() THEN 'PAST (ERROR!)'
        WHEN kickoff_at BETWEEN NOW() AND NOW() + INTERVAL '12 hours' THEN '<12h (CRITICAL)'
        WHEN kickoff_at BETWEEN NOW() + INTERVAL '12 hours' AND NOW() + INTERVAL '24 hours' THEN '12-24h (WARNING)'
        WHEN kickoff_at BETWEEN NOW() + INTERVAL '24 hours' AND NOW() + INTERVAL '72 hours' THEN '24-72h (OK)'
        ELSE '>72h (OK)'
    END as time_window,
    COUNT(*) as fixture_count,
    STRING_AGG(DISTINCT league, ', ') as leagues
FROM fixtures
WHERE kickoff_at > NOW() - INTERVAL '1 hour'
  AND (home_team ILIKE 'TBD%' OR away_team ILIKE 'TBD%')
GROUP BY 
    CASE 
        WHEN kickoff_at < NOW() THEN 'PAST (ERROR!)'
        WHEN kickoff_at BETWEEN NOW() AND NOW() + INTERVAL '12 hours' THEN '<12h (CRITICAL)'
        WHEN kickoff_at BETWEEN NOW() + INTERVAL '12 hours' AND NOW() + INTERVAL '24 hours' THEN '12-24h (WARNING)'
        WHEN kickoff_at BETWEEN NOW() + INTERVAL '24 hours' AND NOW() + INTERVAL '72 hours' THEN '24-72h (OK)'
        ELSE '>72h (OK)'
    END
ORDER BY 1;

-- Snapshot freshness (odds age distribution)
SELECT 
    CASE 
        WHEN ts_snapshot > NOW() - INTERVAL '10 minutes' THEN '<10min (FRESH)'
        WHEN ts_snapshot > NOW() - INTERVAL '30 minutes' THEN '10-30min (OK)'
        WHEN ts_snapshot > NOW() - INTERVAL '1 hour' THEN '30-60min (AGING)'
        WHEN ts_snapshot > NOW() - INTERVAL '2 hours' THEN '1-2h (STALE)'
        ELSE '>2h (VERY STALE)'
    END as age_bucket,
    COUNT(DISTINCT match_id) as matches,
    COUNT(*) as snapshot_rows,
    COUNT(DISTINCT bookmaker_id) as bookmakers
FROM odds_snapshots
WHERE ts_snapshot > NOW() - INTERVAL '3 hours'
GROUP BY 
    CASE 
        WHEN ts_snapshot > NOW() - INTERVAL '10 minutes' THEN '<10min (FRESH)'
        WHEN ts_snapshot > NOW() - INTERVAL '30 minutes' THEN '10-30min (OK)'
        WHEN ts_snapshot > NOW() - INTERVAL '1 hour' THEN '30-60min (AGING)'
        WHEN ts_snapshot > NOW() - INTERVAL '2 hours' THEN '1-2h (STALE)'
        ELSE '>2h (VERY STALE)'
    END
ORDER BY 1;

-- ============ CLOSING ODDS PERFORMANCE ============

-- Closing capture rate (last 24h)
SELECT 
    COUNT(DISTINCT f.match_id) as total_finished,
    COUNT(DISTINCT co.match_id) as with_closing,
    ROUND(COUNT(DISTINCT co.match_id) * 100.0 / NULLIF(COUNT(DISTINCT f.match_id), 0), 1) as capture_rate_pct,
    COUNT(DISTINCT co.match_id) * 3 as closing_odds_rows_expected
FROM fixtures f
LEFT JOIN closing_odds co USING(match_id)
WHERE f.kickoff_at > NOW() - INTERVAL '24 hours'
  AND f.kickoff_at < NOW()
  AND f.status = 'finished';

-- Closing capture by league
SELECT 
    f.league,
    COUNT(DISTINCT f.match_id) as finished_matches,
    COUNT(DISTINCT co.match_id) as captured,
    ROUND(COUNT(DISTINCT co.match_id) * 100.0 / COUNT(DISTINCT f.match_id), 1) as capture_rate_pct
FROM fixtures f
LEFT JOIN closing_odds co USING(match_id)
WHERE f.kickoff_at > NOW() - INTERVAL '24 hours'
  AND f.kickoff_at < NOW()
  AND f.status = 'finished'
GROUP BY f.league
ORDER BY finished_matches DESC;

-- ============ SYSTEM HEALTH ============

-- Candidate fixtures for CLV scanning
SELECT 
    COUNT(DISTINCT f.match_id) as total_fixtures,
    COUNT(DISTINCT CASE WHEN os.match_id IS NOT NULL THEN f.match_id END) as with_odds,
    COUNT(DISTINCT CASE 
        WHEN os.match_id IS NOT NULL 
         AND os.ts_snapshot > NOW() - INTERVAL '2 hours'
        THEN f.match_id 
    END) as with_fresh_odds,
    COUNT(DISTINCT CASE 
        WHEN f.home_team ILIKE 'TBD%' OR f.away_team ILIKE 'TBD%' 
        THEN f.match_id 
    END) as tbd_fixtures
FROM fixtures f
LEFT JOIN odds_snapshots os USING(match_id)
WHERE f.kickoff_at BETWEEN NOW() AND NOW() + INTERVAL '72 hours'
  AND f.status = 'scheduled';

-- Bookmaker coverage by fixture
SELECT 
    COUNT(DISTINCT bookmaker_id) as bookmaker_count,
    COUNT(DISTINCT match_id) as fixture_count
FROM odds_snapshots
WHERE ts_snapshot > NOW() - INTERVAL '2 hours'
GROUP BY match_id
ORDER BY bookmaker_count DESC
LIMIT 10;

-- Alert deduplication check (should be 0 duplicates)
SELECT 
    match_id,
    outcome,
    window_tag,
    COUNT(*) as duplicate_count,
    STRING_AGG(alert_id::text, ', ') as alert_ids
FROM clv_alerts
WHERE created_at > NOW() - INTERVAL '1 hour'
GROUP BY match_id, outcome, window_tag
HAVING COUNT(*) > 1
ORDER BY duplicate_count DESC;

-- ============ PERFORMANCE METRICS ============

-- Table sizes (partitioning candidates)
SELECT 
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size,
    pg_size_pretty(pg_relation_size(schemaname||'.'||tablename)) AS table_size,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename) - pg_relation_size(schemaname||'.'||tablename)) AS indexes_size
FROM pg_tables
WHERE tablename IN ('odds_snapshots', 'fixtures', 'closing_odds', 'clv_alerts', 'clv_alerts_history')
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;

-- Index usage statistics
SELECT 
    schemaname,
    tablename,
    indexname,
    idx_scan as times_used,
    pg_size_pretty(pg_relation_size(indexrelid)) as index_size,
    ROUND(idx_scan::numeric / NULLIF(seq_scan + idx_scan, 0) * 100, 2) as index_usage_pct
FROM pg_stat_user_indexes
WHERE tablename IN ('odds_snapshots', 'fixtures', 'closing_odds', 'clv_alerts')
ORDER BY tablename, idx_scan DESC;

-- Slow queries (if pg_stat_statements enabled)
-- SELECT 
--     query,
--     calls,
--     ROUND(mean_exec_time::numeric, 2) as avg_time_ms,
--     ROUND(total_exec_time::numeric, 2) as total_time_ms
-- FROM pg_stat_statements
-- WHERE query LIKE '%clv%' OR query LIKE '%odds_snapshots%'
-- ORDER BY mean_exec_time DESC
-- LIMIT 10;

-- ============ DATA INTEGRITY ============

-- Orphaned odds snapshots (match_id not in fixtures)
SELECT COUNT(*) as orphaned_snapshots
FROM odds_snapshots os
WHERE NOT EXISTS (
    SELECT 1 FROM fixtures f WHERE f.match_id = os.match_id
);

-- Alerts without corresponding fixtures
SELECT COUNT(*) as orphaned_alerts
FROM clv_alerts ca
WHERE NOT EXISTS (
    SELECT 1 FROM fixtures f WHERE f.match_id = ca.match_id
);

-- ============ RECENT ACTIVITY ============

-- Last 10 alerts created
SELECT 
    created_at,
    match_id,
    league,
    outcome,
    ROUND(clv_pct, 2) as clv_pct,
    ROUND(stability, 3) as stability,
    best_book_id,
    books_used,
    expires_at
FROM clv_alerts
ORDER BY created_at DESC
LIMIT 10;

-- Upcoming fixtures with highest odds activity
SELECT 
    f.match_id,
    f.home_team,
    f.away_team,
    f.league,
    f.kickoff_at,
    COUNT(DISTINCT os.bookmaker_id) as bookmakers,
    COUNT(*) as snapshot_count,
    MAX(os.ts_snapshot) as latest_snapshot
FROM fixtures f
JOIN odds_snapshots os USING(match_id)
WHERE f.kickoff_at BETWEEN NOW() AND NOW() + INTERVAL '24 hours'
  AND f.status = 'scheduled'
  AND os.ts_snapshot > NOW() - INTERVAL '1 hour'
GROUP BY f.match_id, f.home_team, f.away_team, f.league, f.kickoff_at
ORDER BY snapshot_count DESC
LIMIT 10;

-- ============ EXPORT TEMPLATES ============

-- CSV export: Alerts for external analysis
-- \copy (SELECT created_at, match_id, league, outcome, clv_pct, stability, best_book_id, books_used FROM clv_alerts WHERE created_at > NOW() - INTERVAL '7 days' ORDER BY created_at DESC) TO '/tmp/clv_alerts_7d.csv' CSV HEADER;

-- CSV export: Closing capture rate by day
-- \copy (SELECT date_trunc('day', f.kickoff_at)::date as date, COUNT(DISTINCT f.match_id) as finished, COUNT(DISTINCT co.match_id) as captured, ROUND(COUNT(DISTINCT co.match_id) * 100.0 / COUNT(DISTINCT f.match_id), 1) as capture_rate FROM fixtures f LEFT JOIN closing_odds co USING(match_id) WHERE f.status = 'finished' AND f.kickoff_at > NOW() - INTERVAL '30 days' GROUP BY date_trunc('day', f.kickoff_at) ORDER BY date) TO '/tmp/closing_capture_30d.csv' CSV HEADER;
