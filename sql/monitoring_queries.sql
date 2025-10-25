-- ============================================================================
-- LIGHTGBM MONITORING QUERIES
-- ============================================================================

-- QUERY 1: Global Performance (Last 14 Days)
-- Use this for daily monitoring dashboard
SELECT
  COUNT(*) AS n_predictions,
  AVG((predicted_outcome = actual_outcome)::int) AS hit_rate,
  AVG(confidence) AS avg_confidence,
  COUNT(*) FILTER (WHERE confidence >= 0.62) AS high_conf_count,
  AVG((predicted_outcome = actual_outcome)::int) FILTER (WHERE confidence >= 0.62) AS high_conf_hit_rate
FROM model_inference_logs
WHERE kickoff_ts >= CURRENT_DATE - INTERVAL '14 days'
  AND kickoff_ts <= NOW()
  AND actual_outcome IS NOT NULL;

-- QUERY 2: Hit@Coverage Tracking (Last 30 Days)
-- Monitor key thresholds
WITH coverage_buckets AS (
  SELECT
    CASE
      WHEN confidence >= 0.70 THEN '70%+'
      WHEN confidence >= 0.62 THEN '62-70%'
      WHEN confidence >= 0.60 THEN '60-62%'
      WHEN confidence >= 0.56 THEN '56-60%'
      ELSE 'Below 56%'
    END AS bucket,
    (predicted_outcome = actual_outcome)::int AS hit
  FROM model_inference_logs
  WHERE kickoff_ts >= CURRENT_DATE - INTERVAL '30 days'
    AND actual_outcome IS NOT NULL
)
SELECT
  bucket,
  COUNT(*) AS n,
  AVG(hit) AS hit_rate,
  COUNT(*)::float / (SELECT COUNT(*) FROM coverage_buckets) AS coverage_pct
FROM coverage_buckets
GROUP BY bucket
ORDER BY bucket DESC;

-- QUERY 3: Per-League Performance
-- Alert on leagues with ECE > 0.12 or hit rate < 50%
SELECT
  league,
  COUNT(*) AS n,
  AVG((predicted_outcome = actual_outcome)::int) AS hit_rate,
  AVG(confidence) AS avg_confidence,
  STDDEV(confidence) AS conf_std
FROM model_inference_logs mil
JOIN fixtures f ON mil.fixture_id = f.id
WHERE mil.kickoff_ts >= CURRENT_DATE - INTERVAL '30 days'
  AND mil.actual_outcome IS NOT NULL
GROUP BY league
HAVING COUNT(*) >= 20
ORDER BY hit_rate ASC;

-- QUERY 4: Daily Trend (Rolling 7-Day)
-- Detect degradation early
SELECT
  DATE(kickoff_ts) AS date,
  COUNT(*) AS n,
  AVG((predicted_outcome = actual_outcome)::int) AS hit_rate,
  AVG(confidence) AS avg_confidence,
  COUNT(*) FILTER (WHERE confidence >= 0.62) AS high_conf_n,
  AVG((predicted_outcome = actual_outcome)::int) FILTER (WHERE confidence >= 0.62) AS high_conf_hit
FROM model_inference_logs
WHERE kickoff_ts >= CURRENT_DATE - INTERVAL '7 days'
  AND actual_outcome IS NOT NULL
GROUP BY DATE(kickoff_ts)
ORDER BY date DESC;

-- QUERY 5: Model Comparison (V2 Ridge vs LightGBM)
-- If shadow testing is active
SELECT
  model_version,
  COUNT(*) AS n,
  AVG((predicted_outcome = actual_outcome)::int) AS hit_rate,
  AVG(confidence) AS avg_confidence
FROM model_inference_logs
WHERE kickoff_ts >= CURRENT_DATE - INTERVAL '14 days'
  AND actual_outcome IS NOT NULL
GROUP BY model_version
ORDER BY model_version;

-- QUERY 6: Retraining Alert
-- Check if sample growth warrants retraining
SELECT
  COUNT(*) FILTER (WHERE created_at >= CURRENT_DATE - INTERVAL '30 days') AS last_30d_matches,
  COUNT(*) FILTER (WHERE created_at >= CURRENT_DATE - INTERVAL '60 days'
                    AND created_at < CURRENT_DATE - INTERVAL '30 days') AS prev_30d_matches,
  (COUNT(*) FILTER (WHERE created_at >= CURRENT_DATE - INTERVAL '30 days')::float /
   NULLIF(COUNT(*) FILTER (WHERE created_at >= CURRENT_DATE - INTERVAL '60 days'
                             AND created_at < CURRENT_DATE - INTERVAL '30 days'), 0) - 1) AS growth_rate
FROM historical_odds
WHERE result IS NOT NULL;

-- Alert: If growth_rate > 0.10 (10%+), consider retraining

-- QUERY 7: Calibration Check
-- Estimate ECE from production data
WITH binned AS (
  SELECT
    WIDTH_BUCKET(confidence, 0, 1, 10) AS bin,
    confidence,
    (predicted_outcome = actual_outcome)::int AS correct
  FROM model_inference_logs
  WHERE kickoff_ts >= CURRENT_DATE - INTERVAL '30 days'
    AND actual_outcome IS NOT NULL
)
SELECT
  bin,
  COUNT(*) AS n,
  AVG(confidence) AS avg_conf,
  AVG(correct) AS accuracy,
  ABS(AVG(confidence) - AVG(correct)) AS calibration_error
FROM binned
GROUP BY bin
ORDER BY bin;

-- Alert: If any bin has calibration_error > 0.08, consider temperature scaling
