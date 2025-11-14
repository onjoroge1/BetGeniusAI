# BetGenius AI - Sports Prediction Backend

## Overview
BetGenius AI is a sports prediction platform that provides intelligent football match predictions using advanced machine learning and AI analysis. The project aims to deliver market-relative performance, a superior user experience with confidence-calibrated predictions, and sophisticated risk management tools for sports betting in key African markets. Its core capabilities include comprehensive data collection, robust ML models, AI-powered contextual analysis, and strategic market intelligence, including a full live betting intelligence stack with real-time momentum scoring and WebSocket streaming.

## User Preferences
Preferred communication style: Simple, everyday language.
Production Model Decision: Use simple weighted consensus based on performance comparison showing 0.031549 LogLoss improvement over complex model.
Model Performance Analysis: Model rating 6.3/10 (B Grade) with 54.3% 3-way accuracy and 62.4% 2-way accuracy. Rating corrected after fixing Brier score normalization issue (0.191 vs incorrectly reported 0.573).
Improvement Priority: Focus on enhanced feature engineering and gradient boosting ensemble methods for immediate gains, with deep learning and reinforcement learning as longer-term research directions.

## Recent Work (Nov 2025)
- **STEP A OPTIMIZATION LOOP READY (Nov 14)**: Created comprehensive optimization script (training/step_a_optimizations.py) implementing all 5 optimization tasks: (1) ✅ Random-label sanity check (global permutation, reuse across folds, target: acc≈0.33, logloss≈1.10), (2) ✅ Hyperparameter grid search (num_leaves, min_data_in_leaf, feature_fraction, lambda_l1/l2), (3) ✅ Class balancing for draws (1.25-1.35× weight), (4) ✅ Meta-features (league_tier, favorite_strength), (5) ✅ Per-league evaluation tables. Path to 53%: drift +0.7pp → hyperparams +1.5pp → class balance +0.8pp → meta-features +0.5pp = **53.0% target**. Ready to execute full optimization loop. Documentation: STEP_A_READY.md.
- **DRIFT FEATURES IMPLEMENTATION COMPLETE (Nov 13)**: Successfully unlocked drift features using existing multi-horizon odds data. Infrastructure: (1) ✅ Created odds_early_snapshot materialized view (1,177 matches, 24h+ pre-kickoff consensus), (2) ✅ Implemented _build_drift_features() in V2FeatureBuilder with 4 new features (prob_drift_home/draw/away, drift_magnitude), (3) ✅ Removed duplicate placeholder drift from odds features, (4) ✅ Fixed feature count documentation (was incorrectly 46 Phase 1, actually 42). **Final feature set: 50 features** (42 Phase 1 + 4 Phase 2 context + 4 Phase 2.5 drift). Expected impact: +0.5-1.0pp accuracy gain. Path to 53% validated by architect. Ready for retraining. Documentation: V2_DRIFT_FEATURES_IMPLEMENTATION.md, V2_OPTIMIZATION_SUMMARY.md.
- **TBD FIXTURES SAFEGUARD COMPLETE (Nov 11)**: Implemented two-phase solution for "TBD" placeholder team pollution: (1) ✅ Defensive filter in `/market` endpoint excludes all TBD fixtures from API responses, (2) ✅ TbdFixtureResolver service (runs every 5 minutes) polls The Odds API to update placeholders with real team names, (3) ✅ Soft delete/archive strategy preserves referential integrity, (4) ✅ League-level API caching (20 call limit per cycle) prevents rate limit exhaustion, (5) ✅ Enhanced error handling with retry logic, exponential backoff, and observable metrics. Architect-approved PASS verdict.
- **PHASE 2 IMPROVEMENTS (Nov 9)**: Comprehensive infrastructure for 53-55% target: (1) ✅ Fixed sanity checks with global permutation + row-permutation test, (2) ✅ Created odds_real_latest (185 matches) and odds_real_opening (1,554 matches) views for drift features, (3) ⚠️ Discovered API-Football lacks historical pre-match odds (backfill not viable - tested 20 matches, all returned no data), (4) ✅ Created fold 4 investigation + market baseline validation scripts. Training at 49.5% accuracy. **REVISED STRATEGY**: Focus on drift features + small-data optimization (hyperparameters, class weights, calibration) instead of data expansion. Expected: 52-54% in 4-6 weeks. Documentation: PHASE2_TRAINING_ANALYSIS.md, ENSEMBLE_ROADMAP.md, IMPLEMENTATION_NOV9.md.
- **FIRST V2 TRAINING COMPLETE (Nov 8)**: Achieved 49.5% accuracy on 1,236 clean matches with 100% feature extraction success. Results: 49.5% accuracy (target: 53-55%, gap: -3.5pp to -5.5pp), 1.0125 LogLoss, 0.2558 Brier. Fold 4 anomaly detected (56.8% vs 49.5% avg). Fixed training pipeline: (1) INNER JOIN to odds_real_consensus, (2) Feature builder using real odds, (3) Probability normalization. Ready for improvements. Documentation: TRAINING_FIX_NOV8.md.
- **READY: Clean Data Migration Complete (Nov 8)**: Successfully migrated from fake odds_consensus to authentic odds_snapshots data. Created odds_real_consensus materialized view (1,513 matches, 67 avg bookmakers, 100% pre-kickoff). Cleaned and refilled match_context table (1,236 matches with realistic rest days & congestion). Updated backfill_match_context.py to only process matches with real odds. Fixed sanity checks to use TimeSeriesSplit. Comprehensive documentation: TRAINING_FAILURE_ANALYSIS.md, CRITICAL_ODDS_DATA_CORRUPTION.md, HYBRID_BACKFILL_STRATEGY.md.
- **Leakage Prevention Complete**: Implemented time-based CV with 7-day embargo, pre-kickoff odds enforcement, sanity checks (random shuffle ~33%, market baseline 48-52%). Fixed 90.4% leakage issue (was post-kickoff odds + poor CV). Realistic Phase 2 target: 53-55% (NOT 90%!).
- **Phase 2 Data Collection Complete (Architect-Approved)**: Successfully backfilled 8,809 matches with 100% Phase 2 context coverage (rest days, schedule congestion). Expanded V2FeatureBuilder from 46→50 features. DatabaseContextComputer working with realistic values (rest: 1.4/4.4 days, congestion: 10-11 matches/7d).
- **Phase 2 Foundation (Architect-Approved)**: Applied schema extensions (5 new tables: players, referees, match_weather, match_context, data_lineage). Created fetcher interfaces with FetchResult contract and gap discovery SQL. Fixed backfill agent KeyError bug (kickoff_at alias mismatch).
- **Training Infrastructure**: Consolidated manage_training.py with libgomp auto-config, 6-hour timeout (was 2h), real-time progress streaming, dropped match tracking.
- **Phase 1 Validation Script**: Comprehensive acceptance testing with betting-centric metrics (LogLoss, Brier Score, ECE, Expected Value, CLV, Kelly ROI, Sharpe Ratio). Validates feature parity, accuracy, calibration, profitability, and latency.
- **Betting Intelligence System**: Complete implementation with per-match and curated endpoints.
- **Robust Odds Parser**: Fixed odds extraction bugs handling stringified JSON and nested structures.

## System Architecture

### Backend Framework
- **FastAPI**: Modern Python web framework for API development.
- **SQLAlchemy**: ORM for database interactions.
- **Pydantic**: For data validation.
- **AsyncIO**: For asynchronous operations.
- **Deployment Architecture**: Supports both Autoscale (API-only) and Development/VM (full functionality with background scheduler) modes.

### Machine Learning Pipeline
- **Models**: Production V1 (weighted consensus) and V2 (LightGBM ensemble) models.
- **Feature Engineering**: Reusable pipeline extracting 50 features for V2 (42 Phase 1 base + 4 Phase 2 context + 4 Phase 2.5 drift), ensuring 100% feature coverage for LightGBM training. Drift features capture smart money movement from early (T-24h+) to latest (T-0h) odds.
- **Training Data**: 1,177 matches with full 50-feature coverage (82% of odds-bearing matches), expandable to 1,428 with context-only features.
- **Calibration & Constraints**: Extensive testing for optimal model configuration.
- **Shadow Testing System**: Operational market-delta ridge regression model for A/B testing and auto-promotion.
- **Auto-Retraining System**: Models retrain automatically based on match volume.
- **Market System**: Poisson-based market expansion providing 50+ mathematically consistent markets.
- **Accuracy Tracking**: Automated backend monitoring for predictions, calculating metrics (Brier score, LogLoss, Hit-rate) and supporting CLV analysis.
- **Live Betting Intelligence**:
    - **Momentum Engine**: 0-100 scoring based on weighted features (shots, attacks, xG, odds, possession) with red card modifiers.
    - **Live Market Engine**: In-play predictions (1X2 live, O/U 2.5, Next Goal) with time-aware blending and momentum boost.

### Data Collection
- **Canonical Fixtures Table**: Single source of truth for match metadata.
- **TBD Fixture Enrichment**: Automated service resolves "To Be Determined" placeholders with 100% team_id linkage.
- **Multi-Source Real-Time Odds**: Parallel collection from The Odds API and API-Football.
- **Fixture ID Resolver**: Advanced system achieving 95%+ linkage rate using multi-pass lookup and normalization.
- **Historical Match Data**: 40,769 matches (1993-2025) with results, bookmaker odds, and in-game statistics.
- **CLV Monitoring**: Advanced system for detecting pricing inefficiencies, robust consensus calculation, real-time alerts, and closing line capture.
- **Observability**: Full Prometheus metrics, Grafana dashboards, and comprehensive operations runbook for CLV and live betting systems.

### AI Analysis Layer
- **OpenAI GPT-4o Integration**: Provides comprehensive match analysis and contextual insights.

### Data Flow & Feature Engineering
- Automated processes create ML-ready features from raw data, utilizing horizon-aligned market snapshots.

### Database Layer
- **PostgreSQL**: Primary database.
- **Production Indexes**: Optimized for critical tables.
- **Schema Bridge Views**: For streamlined analysis.
- **Outcome Standardization**: Unified H/D/A outcome codes.
- **Timezone Architecture**: All timestamp columns are timezone-aware UTC.
- **Match Status Architecture**: Database stores only 'scheduled' and 'finished' statuses, with upcoming matches determined by time-based filtering.
- **Team Logo System**: Teams dimension table with logo_url, api_football_team_id mapping, and intelligent enrichment service.

### API Endpoints
- **Prediction API**:
    - `/predict`: V1 consensus predictions with optional AI analysis.
    - `/predict-v2`: Premium V2 SELECT endpoint (high-confidence only).
    - `/market`: Market board showing both V1 and V2 predictions side-by-side (free tier). Includes team logos and supports three status filters:
        - `status=upcoming`: Future scheduled matches with embedded betting intelligence (CLV, edge, Kelly sizing)
        - `status=live`: In-progress matches with fresh data (updated within 10 minutes) and in-play betting intelligence
        - `status=finished`: Completed matches with final scores and results
    - `/teams`: Frontend-friendly API for fetching teams with logos, supporting filtering and search.
- **Betting Intelligence API**:
    - `/betting-intelligence/{match_id}`: Per-match betting intelligence with CLV, edge, Kelly sizing. Supports model selection (v1/v2/best), custom bankroll, and Kelly fraction parameters.
    - `/betting-intelligence`: Curated betting opportunities combining model predictions with CLV calculations and Kelly Criterion bet sizing. Filters by edge threshold, model preference, league, and status.
    - **Features**: Edge calculation, Closing Line Value (CLV) analysis, Kelly Criterion optimal stake sizing, fractional Kelly recommendations, risk-adjusted bet sizing with 3% bankroll cap.
    - **Robust Odds Parser**: `utils/odds_extract.py` handles stringified JSON, nested objects, and multiple bookmaker data formats.
- **WebSocket Streaming**: `/ws/live/{match_id}` for real-time match event and prediction updates.
- **Admin Endpoints**: For data management, match discovery, and training statistics.
- **Monitoring Endpoints**: For CLV health, shadow system metrics, and model evaluation.

### UI/UX Decisions
- Focus on superior user experience with confidence-calibrated predictions and uncertainty quantification.

## External Dependencies

### Sports Data
- **RapidAPI Football API**: For real-time and historical match information.
- **The Odds API**: For aggregated odds data from multiple bookmakers.

### AI Services
- **OpenAI API**: Specifically GPT-4o for contextual analysis.

### Database
- **PostgreSQL**: Core relational database.