-- BetGenius AI - Partition Maintenance Functions
-- Phase 2: Automated partition creation and retention cleanup

-- Function: Create next month's partition
CREATE OR REPLACE FUNCTION create_next_partition()
RETURNS void AS $$
DECLARE
    next_month date := date_trunc('month', NOW() + INTERVAL '1 month');
    partition_name text;
    start_date text;
    end_date text;
BEGIN
    -- Generate partition name (e.g., odds_snapshots_2026_02)
    partition_name := 'odds_snapshots_' || to_char(next_month, 'YYYY_MM');
    
    -- Check if partition already exists
    IF NOT EXISTS (
        SELECT 1 FROM pg_tables 
        WHERE tablename = partition_name
    ) THEN
        start_date := to_char(next_month, 'YYYY-MM-DD');
        end_date := to_char(next_month + INTERVAL '1 month', 'YYYY-MM-DD');
        
        EXECUTE format(
            'CREATE TABLE %I PARTITION OF odds_snapshots FOR VALUES FROM (%L) TO (%L)',
            partition_name,
            start_date,
            end_date
        );
        
        RAISE NOTICE 'Created partition: % for range [%, %)', partition_name, start_date, end_date;
    ELSE
        RAISE NOTICE 'Partition % already exists', partition_name;
    END IF;
END;
$$ LANGUAGE plpgsql;

-- Function: Drop partitions older than 90 days (retention policy)
CREATE OR REPLACE FUNCTION drop_old_partitions(retention_days integer DEFAULT 90)
RETURNS void AS $$
DECLARE
    cutoff_date date := NOW() - (retention_days || ' days')::interval;
    partition_record record;
    dropped_count integer := 0;
BEGIN
    -- Find and drop old partitions
    FOR partition_record IN
        SELECT tablename
        FROM pg_tables
        WHERE tablename LIKE 'odds_snapshots_20%'
          AND tablename < 'odds_snapshots_' || to_char(cutoff_date, 'YYYY_MM')
    LOOP
        EXECUTE 'DROP TABLE IF EXISTS ' || partition_record.tablename;
        RAISE NOTICE 'Dropped old partition: %', partition_record.tablename;
        dropped_count := dropped_count + 1;
    END LOOP;
    
    IF dropped_count = 0 THEN
        RAISE NOTICE 'No partitions older than % days found', retention_days;
    ELSE
        RAISE NOTICE 'Dropped % old partition(s)', dropped_count;
    END IF;
END;
$$ LANGUAGE plpgsql;

-- Monthly cron job (run on 1st of each month)
-- Uncomment to enable automated partition management via pg_cron:

-- SELECT cron.schedule(
--     'partition_maintenance',
--     '0 2 1 * *',  -- 2 AM on 1st of every month
--     $$
--     SELECT create_next_partition();
--     SELECT drop_old_partitions(90);
--     $$
-- );

-- Manual execution examples:

-- Create next month's partition now:
-- SELECT create_next_partition();

-- Drop partitions older than 90 days:
-- SELECT drop_old_partitions(90);

-- Drop partitions older than 60 days (more aggressive):
-- SELECT drop_old_partitions(60);

-- List all partitions with sizes:
SELECT 
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size,
    (SELECT COUNT(*) FROM (SELECT 1 FROM ONLY quote_ident(tablename) LIMIT 1) x) as has_rows
FROM pg_tables
WHERE tablename LIKE 'odds_snapshots_20%'
ORDER BY tablename DESC;
