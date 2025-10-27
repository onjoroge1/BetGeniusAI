-- Phase 1: CLV System Hardening
-- Date: 2025-10-27
-- Purpose: Critical indexes, alert deduplication, performance optimization

-- 1) Critical indexes for performance
CREATE INDEX IF NOT EXISTS idx_odds_snapshots_match_ts
  ON odds_snapshots(match_id, ts_snapshot DESC);

CREATE INDEX IF NOT EXISTS idx_odds_snapshots_ts
  ON odds_snapshots(ts_snapshot DESC);

CREATE INDEX IF NOT EXISTS idx_fixtures_kickoff
  ON fixtures(kickoff_at);

-- 2) Market/book index for faster odds aggregation
CREATE INDEX IF NOT EXISTS idx_odds_snapshots_mkt_book_ts
  ON odds_snapshots(match_id, market, book_id, ts_snapshot DESC);

-- 3) Alert de-duplication: prevent duplicate alerts within cooldown window
-- Note: clv_alerts table uses alert_id (varchar UUID) as primary key
-- Add unique constraint on (match_id, outcome, window_tag) to prevent duplicates
DO $$
BEGIN
  -- First, add window_tag column if it doesn't exist
  IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_name = 'clv_alerts'
      AND column_name = 'window_tag'
  ) THEN
    ALTER TABLE clv_alerts ADD COLUMN window_tag VARCHAR(32);
  END IF;

  -- Create unique index for deduplication
  IF NOT EXISTS (
    SELECT 1
    FROM pg_indexes
    WHERE schemaname = 'public'
      AND indexname = 'ux_clv_alerts_key_window'
  ) THEN
    CREATE UNIQUE INDEX ux_clv_alerts_key_window
      ON clv_alerts(match_id, outcome, window_tag)
      WHERE window_tag IS NOT NULL;
  END IF;
END $$;

-- 4) Index on clv_alerts for TTL cleanup queries
CREATE INDEX IF NOT EXISTS idx_clv_alerts_created_at
  ON clv_alerts(created_at);

CREATE INDEX IF NOT EXISTS idx_clv_alerts_match_kickoff
  ON clv_alerts(match_id, kickoff_at);

-- Migration complete
SELECT 'Phase 1 CLV Hardening Migration Complete' AS status;
