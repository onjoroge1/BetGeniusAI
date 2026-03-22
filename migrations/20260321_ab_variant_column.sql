-- Add ab_variant column to prediction_log for A/B testing tracking
-- Safe to run multiple times (IF NOT EXISTS)

ALTER TABLE prediction_log ADD COLUMN IF NOT EXISTS ab_variant VARCHAR(32);

-- Index for efficient A/B results queries
CREATE INDEX IF NOT EXISTS idx_prediction_log_ab_variant
    ON prediction_log (ab_variant)
    WHERE ab_variant IS NOT NULL;

COMMENT ON COLUMN prediction_log.ab_variant IS 'A/B experiment variant this prediction was allocated to';
