-- V2 Sanity Monitoring Queries
-- Run these daily to verify V2 is making realistic predictions

-- =============================================================================
-- MONITOR 1: Average Top Probability (should be < 0.80)
-- =============================================================================
-- Checks if V2 is being overconfident
-- Target: avg_top_prob < 0.80 (realistic sports betting confidence)

SELECT 
    ROUND(AVG(GREATEST(p_home, p_draw, p_away))::numeric, 4) AS avg_top_prob,
    COUNT(*) AS n_predictions,
    CASE 
        WHEN AVG(GREATEST(p_home, p_draw, p_away)) < 0.80 THEN '✅ Reasonable'
        WHEN AVG(GREATEST(p_home, p_draw, p_away)) < 0.85 THEN '⚠️ Slightly high'
        ELSE '❌ Too confident'
    END AS status
FROM model_inference_logs
WHERE model_version = 'v2' 
    AND scored_at > NOW() - INTERVAL '1 day';

-- =============================================================================
-- MONITOR 2: L1 Divergence from Market (should be 0.10-0.30)
-- =============================================================================
-- Checks if V2 is making meaningful adjustments from market
-- Target: mean_L1_diff between 0.10 and 0.30

SELECT 
    ROUND(AVG(
        ABS(mil.p_home - mf.prob_home) +
        ABS(mil.p_draw - mf.prob_draw) +
        ABS(mil.p_away - mf.prob_away)
    )::numeric, 4) AS mean_L1_diff,
    COUNT(*) AS n_predictions,
    CASE 
        WHEN AVG(
            ABS(mil.p_home - mf.prob_home) +
            ABS(mil.p_draw - mf.prob_draw) +
            ABS(mil.p_away - mf.prob_away)
        ) < 0.10 THEN '⚠️ Too conservative'
        WHEN AVG(
            ABS(mil.p_home - mf.prob_home) +
            ABS(mil.p_draw - mf.prob_draw) +
            ABS(mil.p_away - mf.prob_away)
        ) > 0.30 THEN '⚠️ Too aggressive'
        ELSE '✅ In target range'
    END AS status
FROM model_inference_logs mil
JOIN match_features mf ON mil.match_id = mf.match_id
WHERE mil.model_version = 'v2'
    AND mil.scored_at > NOW() - INTERVAL '1 day';

-- =============================================================================
-- MONITOR 3: Guardrail Activation Rate
-- =============================================================================
-- Checks how often KL/max-prob guardrails are triggered
-- Target: <30% of predictions (shows model respects market most of the time)

SELECT 
    COUNT(*) FILTER (WHERE reason_code LIKE '%KL_CAPPED%') AS kl_capped_count,
    COUNT(*) FILTER (WHERE reason_code LIKE '%MAX_PROB_CAPPED%') AS max_prob_capped_count,
    COUNT(*) FILTER (WHERE reason_code LIKE '%DELTA_CLIPPED%') AS delta_clipped_count,
    COUNT(*) AS total_predictions,
    ROUND(100.0 * COUNT(*) FILTER (WHERE reason_code LIKE '%KL_CAPPED%') / COUNT(*), 2) AS kl_cap_pct,
    ROUND(100.0 * COUNT(*) FILTER (WHERE reason_code LIKE '%MAX_PROB_CAPPED%') / COUNT(*), 2) AS max_prob_pct,
    ROUND(100.0 * COUNT(*) FILTER (WHERE reason_code LIKE '%DELTA_CLIPPED%') / COUNT(*), 2) AS delta_clip_pct
FROM model_inference_logs
WHERE model_version = 'v2'
    AND scored_at > NOW() - INTERVAL '1 day';

-- =============================================================================
-- MONITOR 4: V2 vs Market Performance (when results available)
-- =============================================================================
-- Compares V2 LogLoss vs Market baseline LogLoss
-- Target: V2 LogLoss < Market LogLoss (model adds value)

WITH market_ll AS (
    SELECT 
        AVG(-LN(CASE 
            WHEN tm.outcome = 'H' THEN mf.prob_home
            WHEN tm.outcome = 'D' THEN mf.prob_draw
            WHEN tm.outcome = 'A' THEN mf.prob_away
        END + 1e-9)) AS market_logloss
    FROM match_features mf
    JOIN training_matches tm ON mf.match_id = tm.match_id
    WHERE mf.kickoff_timestamp > NOW() - INTERVAL '7 days'
        AND tm.outcome IS NOT NULL
),
v2_ll AS (
    SELECT 
        AVG(-LN(CASE 
            WHEN tm.outcome = 'H' THEN mil.p_home
            WHEN tm.outcome = 'D' THEN mil.p_draw
            WHEN tm.outcome = 'A' THEN mil.p_away
        END + 1e-9)) AS v2_logloss,
        COUNT(*) AS n_evaluated
    FROM model_inference_logs mil
    JOIN training_matches tm ON mil.match_id = tm.match_id
    WHERE mil.model_version = 'v2'
        AND mil.scored_at > NOW() - INTERVAL '7 days'
        AND tm.outcome IS NOT NULL
)
SELECT 
    ROUND(m.market_logloss::numeric, 4) AS market_logloss,
    ROUND(v.v2_logloss::numeric, 4) AS v2_logloss,
    ROUND((v.v2_logloss - m.market_logloss)::numeric, 4) AS delta_logloss,
    v.n_evaluated,
    CASE 
        WHEN v.v2_logloss < m.market_logloss THEN '✅ V2 better'
        WHEN v.v2_logloss < m.market_logloss + 0.05 THEN '⚠️ Marginal'
        ELSE '❌ V2 worse'
    END AS status
FROM market_ll m, v2_ll v;

-- =============================================================================
-- MONITOR 5: Weekly V2 Health Summary
-- =============================================================================
-- Comprehensive weekly health check

SELECT 
    DATE_TRUNC('day', scored_at) AS prediction_date,
    COUNT(*) AS n_predictions,
    ROUND(AVG(GREATEST(p_home, p_draw, p_away))::numeric, 3) AS avg_confidence,
    COUNT(*) FILTER (WHERE reason_code LIKE '%KL_CAPPED%') AS kl_caps,
    COUNT(*) FILTER (WHERE reason_code LIKE '%MAX_PROB_CAPPED%') AS max_prob_caps,
    ROUND(AVG(p_home)::numeric, 3) AS avg_p_home,
    ROUND(AVG(p_draw)::numeric, 3) AS avg_p_draw,
    ROUND(AVG(p_away)::numeric, 3) AS avg_p_away
FROM model_inference_logs
WHERE model_version = 'v2'
    AND scored_at > NOW() - INTERVAL '7 days'
GROUP BY DATE_TRUNC('day', scored_at)
ORDER BY prediction_date DESC;

-- =============================================================================
-- QUICK DAILY CHECK (ONE QUERY)
-- =============================================================================
-- Run this every morning for quick V2 health snapshot

SELECT 
    'V2_HEALTH_CHECK' AS check_name,
    NOW() AS checked_at,
    COUNT(*) AS predictions_24h,
    ROUND(AVG(GREATEST(p_home, p_draw, p_away))::numeric, 3) AS avg_confidence,
    CASE 
        WHEN AVG(GREATEST(p_home, p_draw, p_away)) < 0.80 THEN '✅'
        ELSE '⚠️'
    END AS confidence_ok,
    COUNT(*) FILTER (WHERE reason_code LIKE '%KL_CAPPED%' OR reason_code LIKE '%MAX_PROB_CAPPED%') AS guardrails_triggered,
    ROUND(100.0 * COUNT(*) FILTER (WHERE reason_code LIKE '%KL_CAPPED%' OR reason_code LIKE '%MAX_PROB_CAPPED%') / COUNT(*), 1) AS guardrail_pct
FROM model_inference_logs
WHERE model_version = 'v2'
    AND scored_at > NOW() - INTERVAL '1 day';
