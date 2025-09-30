# BetGenius AI - Sports Prediction Backend

## Overview
BetGenius AI is a sports prediction platform providing intelligent football match predictions using machine learning and AI analysis. It targets African markets (Kenya, Uganda, Nigeria, South Africa, Tanzania) while training models on European league data. The project aims to provide market-relative performance, superior user experience with confidence-calibrated predictions, and advanced risk management for sports betting. Key capabilities include comprehensive data collection, robust ML models, AI-powered contextual analysis, and strategic market-anchored intelligence.

## User Preferences
Preferred communication style: Simple, everyday language.
Production Model Decision: Use simple weighted consensus based on performance comparison showing 0.031549 LogLoss improvement over complex model.
Model Performance Analysis: Model rating 6.3/10 (B Grade) with 54.3% 3-way accuracy and 62.4% 2-way accuracy. Rating corrected after fixing Brier score normalization issue (0.191 vs incorrectly reported 0.573).
Improvement Priority: Focus on enhanced feature engineering and gradient boosting ensemble methods for immediate gains, with deep learning and reinforcement learning as longer-term research directions.

## System Architecture

### Backend Framework
- **FastAPI**: Modern Python web framework.
- **SQLAlchemy**: Database ORM for PostgreSQL.
- **Pydantic**: Data validation and serialization.
- **AsyncIO**: Asynchronous operations.

### Machine Learning Pipeline
- **Production Model**: Simple Weighted Consensus using quality weights from 31-year bookmaker analysis.
- **Quality Weights**: Pinnacle (35%), Bet365 (25%), Betway (22%), William Hill (18%) based on historical LogLoss performance.
- **Performance**: 0.838 LogLoss with authentic data (vs 0.963 baseline), 0.167 Brier Score (vs 0.191 baseline), significant improvement across all metrics.
- **Model Rating**: 8.5/10 (A Grade - Very Good Model) with 63.6% 3-way accuracy using authentic bookmaker data (tested August 18, 2025).
- **Enhanced Architecture**: Dual-table population strategy implemented and tested (August 18, 2025) with market-efficient consensus, league_map integration, timing-optimized data collection across 6 major European leagues, manual testing capability, and cross-table synchronization ensuring both training_matches and odds_consensus tables are populated consistently.
- **Optimal Prediction Timing**: T-48h/T-24h windows for maximum market efficiency, with T-72h fallback data available.
- **Real Data Integration**: Enhanced data collector with injuries, team news, recent form, and head-to-head records from RapidAPI.
- **Auto-Retraining System**: Fixed and operational (August 31, 2025) - Models automatically retrain when 50+ matches collected weekly or 10+ matches per session. Training completed successfully with 5,348 matches, 23 numeric features, 3 algorithms (Random Forest, Gradient Boosting, Logistic Regression) in 15.8 seconds. All validation tests passed.
- **Manual Training Scripts**: `manual_retrain_models.py` for comprehensive retraining with detailed analysis, `trigger_auto_retrain.py` for simulating automatic retraining cycles.
- **Research Infrastructure**: Advanced features available for research; roadmap includes gradient boosting, deep learning (LSTM, attention networks), and reinforcement learning approaches.
- **Comprehensive Market System**: PRODUCTION-READY (September 21, 2025) - Enhanced Poisson-based market expansion providing 50+ mathematically consistent markets derived from single λₕ,λₐ parameter fitting. Optimized performance with single PoissonGrid computation and caching, delivering all markets in ~17s. Features three response formats (v1 legacy, v2 nested, flat key-value) with proper API schema validation. Markets include alternate totals, team totals, Asian handicap quarter-lines, double chance, winning margins, correct scores, BTTS, clean sheets, and win-to-nil variants.
- **Automated Accuracy Tracking**: PRODUCTION-READY (September 29, 2025) - Comprehensive 100% backend-driven accuracy monitoring system with automated metrics calculation. Auto-logs every prediction on /predict call (prediction_snapshots table), automatically fetches match results from RapidAPI via scheduler (every 6 hours at 03:00, 09:00, 15:00, 21:00 UTC), and computes Brier score, LogLoss, and Hit-rate metrics. Complete API suite for accuracy analysis: /metrics/match/{id} for individual match metrics, /metrics/summary for overall performance stats, /metrics/result for confidence band analysis. Script: calculate_metrics_results.py integrated into background scheduler for hands-free operation.

### Enhanced Data Collection System (August 2025)
- **Dual Collection Strategy**: Scheduler populates both training_matches (completed) and odds_snapshots (upcoming) tables.
- **League Coverage**: Dynamic league selection via league_map table (22 leagues expanded September 2025): Tier-1 European: EPL, La Liga, Serie A, Bundesliga, Ligue 1, Eredivisie; Tier-2 European: Championship, LaLiga2, Serie B, 2. Bundesliga, Ligue 2; UEFA Competitions: Champions League, Europa League, Conference League; Americas: Brasileirão, Liga MX, MLS, Liga Profesional Argentina; Other European: Primeira Liga, Scottish Premiership, Jupiler Pro League, Süper Lig.
- **Training Data**: 5,766+ matches in training_matches for ML model learning (5,195 original + 571 UEFA matches backfilled September 30, 2025) with synchronized odds_consensus table. UEFA backfill includes 269 Champions League, 256 Europa League, 46 Conference League matches from 2024/25 season.
- **Authentic Odds Collection**: LIVE and operational - collecting real bookmaker odds from The Odds API with 21+ bookmakers per match.
- **Database Integration**: 63+ authentic odds successfully stored with proper H/D/A outcome mapping and individual bookmaker tracking.
- **Timing Windows**: Operational at T-3h to T-168h windows for optimal prediction timing across all configured leagues.
- **Data Integrity**: All odds data sourced from authentic bookmakers (1xBet, Parions Sport, Unibet, etc.) with proper constraint validation.
- **CLV Monitoring**: Real-time Closing Line Value API with 4 endpoints for frontend integration, +2-7% CLV opportunities detected across 1,743 odds entries.
- **CLV Club Phase 1**: PRODUCTION-READY (September 30, 2025) - Advanced CLV detection system with professional-grade pricing inefficiency alerts. Features include: (1) De-juiced odds normalization removing bookmaker margins with identity check (pH+pD+pA≈1.0), (2) Trimmed mean consensus (10% tail removal) for robust market baseline, (3) Line stability metrics (≥70% threshold) ensuring reliable signals, (4) Desk group deduplication via YAML config preventing duplicate desk exposure, (5) Multi-tier gating (≥8 books for major leagues, ≥5 for minor, ≥2.0% CLV threshold), (6) Alert producer running every 60 seconds via scheduler, (7) TTL-based alerts with window tags (T-72to48, T-48to24, T-24to8, T-8to1, T-1to0), (8) Three REST APIs: /clv/club/opportunities (active alerts), /clv/club/alerts/history (paginated history), /clv/club/realized (Phase 2 stub). Database: bookmakers (with desk_group), clv_alerts (UUID primary keys with expiry), clv_realized (for future closing line capture). Hardening includes: unique constraints, indexes, TTL cleanup job (every 5 mins), reason codes for suppression (STALE, LOW_BOOKS, LOW_STABILITY, LOW_CLV, BAD_IDENTITY), stage timing instrumentation (gather_odds_ms, analyze_ms, total_ms). ALL SMOKE TESTS PASSED (September 30, 2025): Verified desk group deduplication, de-juice identity check, TTL cleanup, uniqueness constraint, API contract (15 fields), stability gate, and database indexes. System ready for canary deployment.
- **CLV Club Phase 2**: PRODUCTION-READY (September 30, 2025) - Closing line capture and realized CLV tracking system. Features include: (1) Closing sampler running every 60 seconds collecting composite odds samples near kickoff (T-6m to T+2m window), (2) Closing settler running every 60 seconds computing closing odds using LAST5_VWAP (volume-weighted or trimmed mean) with LAST_TICK fallback, (3) Automatic realized CLV computation comparing alert odds vs closing line, (4) clv_closing_feed table storing all samples with composite_odds_dec, books_used, and timestamps, (5) Enhanced clv_realized table with explicit closing_method, closing_samples, and closing_window_sec columns, (6) GET /clv/club/stats canary monitoring endpoint with league filter and time windows (1h, 6h, 24h, 7d) providing alerts_emitted, books_used_avg, stability_avg, clv_pct_avg, and top 10 opportunities. Both workers integrated into background scheduler with proper error handling and observability. System supports full audit trail from alert creation through closing line capture to realized CLV settlement.
- **CLV Daily Brief**: PRODUCTION-READY (September 30, 2025) - Backend-only daily aggregation and reporting system. Features include: (1) Automated daily rollup at 00:05 UTC aggregating previous UTC day's CLV Club performance per league, (2) clv_daily_stats table storing alerts_emitted, books_used_avg, stability_avg, clv_pct_avg, realized CLV metrics (avg, p50), closing method distribution (JSONB), top 10 opportunities (JSONB), and optional suppression mix, (3) clv_suppression_counters table for tracking alert suppression reasons (STALE, LOW_BOOKS, LOW_STABILITY, LOW_CLV, BAD_IDENTITY), (4) 90-day retention with automatic cleanup, (5) GET /clv/club/daily endpoint with date and league filtering for frontend integration, (6) Fast execution (sub-second rollup), (7) Idempotent upserts supporting re-runs. Configuration: ENABLE_CLV_DAILY_BRIEF (default: true), CLV_DAILY_RETAIN_DAYS (default: 90), CLV_DAILY_SCHEDULE_CRON (default: "5 0 * * *"). System provides comprehensive canary monitoring and value tracking for CLV Club operations.

### AI Analysis Layer
- **OpenAI GPT-4o Integration**: For comprehensive match analysis and contextual insights.
- **Dual-Layer Intelligence**: Combines ML predictions with AI contextual analysis.

### Data Flow & Feature Engineering
- Automated data collection, feature engineering from raw data to ML-ready features.
- Features include team performance metrics, recent form, head-to-head history, venue factors, and market-derived features (logits, entropy, dispersion).
- Market-aligned architecture utilizing horizon-aligned market snapshots (T-72h) from multiple bookmakers.

### Database Layer
- **PostgreSQL**: Primary database for training data, match results, odds snapshots, and market features.
- Organized by league for efficient retrieval.

### API Endpoints
- Prediction API, Admin Endpoints for data management, Match Discovery, and Training Statistics.

### UI/UX Decisions
- Focus on superior UX with confidence-calibrated predictions and uncertainty quantification.

## External Dependencies

### Sports Data
- **RapidAPI Football API**: Primary source for real-time and historical match information.
- **The Odds API**: Third-party aggregator providing odds data from multiple bookmakers (Bet365, Pinnacle, William Hill, etc.). Note: We use aggregated data, not direct bookmaker APIs.

### AI Services
- **OpenAI API**: Specifically GPT-4o for contextual analysis and explanations.

### Database
- **PostgreSQL**: Core relational database.