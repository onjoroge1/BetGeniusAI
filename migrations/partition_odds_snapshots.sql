-- BetGenius AI - Odds Snapshots Table Partitioning
-- Phase 2: Monthly partitioning for query performance and retention management
-- Run this once to convert existing table to partitioned structure

-- WARNING: This requires downtime to run. Schedule during low-traffic period.
-- Estimated time: ~2-5 minutes depending on data volume

BEGIN;

-- Step 1: Rename existing table to _old
ALTER TABLE IF EXISTS odds_snapshots RENAME TO odds_snapshots_old;

-- Step 2: Create partitioned parent table
CREATE TABLE odds_snapshots (
    snapshot_id serial,
    match_id integer NOT NULL,
    bookmaker_id varchar(50) NOT NULL,
    market varchar(20) NOT NULL,
    h_odds_dec numeric(6,3),
    d_odds_dec numeric(6,3),
    a_odds_dec numeric(6,3),
    ts_snapshot timestamptz NOT NULL,
    created_at timestamptz DEFAULT NOW()
) PARTITION BY RANGE (ts_snapshot);

-- Step 3: Create partitions for current + next 3 months
-- October 2025
CREATE TABLE odds_snapshots_2025_10
    PARTITION OF odds_snapshots
    FOR VALUES FROM ('2025-10-01') TO ('2025-11-01');

-- November 2025
CREATE TABLE odds_snapshots_2025_11
    PARTITION OF odds_snapshots
    FOR VALUES FROM ('2025-11-01') TO ('2025-12-01');

-- December 2025
CREATE TABLE odds_snapshots_2025_12
    PARTITION OF odds_snapshots
    FOR VALUES FROM ('2025-12-01') TO ('2026-01-01');

-- January 2026
CREATE TABLE odds_snapshots_2026_01
    PARTITION OF odds_snapshots
    FOR VALUES FROM ('2026-01-01') TO ('2026-02-01');

-- Step 4: Recreate indexes on parent table (applied to all partitions)
CREATE INDEX idx_odds_snapshots_ts ON odds_snapshots(ts_snapshot DESC);
CREATE INDEX idx_odds_snapshots_match ON odds_snapshots(match_id);
CREATE INDEX idx_odds_snapshots_match_ts ON odds_snapshots(match_id, ts_snapshot DESC);

-- Step 5: Migrate data from old table
INSERT INTO odds_snapshots
SELECT * FROM odds_snapshots_old
WHERE ts_snapshot >= '2025-10-01';  -- Only keep recent data

-- Step 6: Drop old table (CAREFUL!)
-- Uncomment after verifying data migration
-- DROP TABLE odds_snapshots_old;

COMMIT;

-- Verify migration
SELECT 
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size
FROM pg_tables
WHERE tablename LIKE 'odds_snapshots%'
ORDER BY tablename;

-- Sample query to test partitioning
SELECT COUNT(*), MIN(ts_snapshot), MAX(ts_snapshot)
FROM odds_snapshots;
