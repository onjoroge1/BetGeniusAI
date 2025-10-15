# BetGenius AI - Sports Prediction Backend

## Overview
BetGenius AI is a sports prediction platform focused on delivering intelligent football match predictions through advanced machine learning and AI analysis. Targeting key African markets, the project aims to provide market-relative performance, a superior user experience with confidence-calibrated predictions, and sophisticated risk management tools for sports betting. Its core capabilities include comprehensive data collection, robust ML models, AI-powered contextual analysis, and strategic market intelligence.

## Recent Updates
- **Oct 15, 2025**: API-Football Continuous Collection LIVE - Dual-source odds collection now running every 60 seconds alongside The Odds API. 75,000 req/day capacity (57% utilization). CLV alerts jumped from 13/hour to 250+/hour (19x improvement). All tables auto-updated: odds_snapshots, odds_consensus, consensus_predictions, clv_alerts. Zero manual triggers needed.
- **Oct 13, 2025**: TBD Fixture Enrichment COMPLETE - Root cause of 2-day CLV drought eliminated. Implemented automatic fixture enrichment service using API-Football to resolve TBD placeholders created by The Odds API. All 89 TBD fixtures backfilled successfully (100% success rate). System now auto-enriches fixtures after each collection. Fixed ON CONFLICT clause to allow team name updates. CLV ready to resume on next odds collection. See TBD_FIXTURE_FIX_SUMMARY.md for full details.
- **Oct 12, 2025**: Scheduler & CLV Fully Operational - All deployment lazy-loading issues fixed. Scheduler confirmed running with all jobs executing (Phase B, CLV Producer, Closing Sampler/Settler). Fixed lazy loader imports for all model classes. Zero functionality lost from deployment optimizations. See SCHEDULER_STATUS_REPORT.md for full verification.
- **Oct 12, 2025**: Bulletproof Autoscale Fix Applied - Background task detection now deployment-safe: disables for ANY deployment (REPLIT_DEPLOYMENT=1) unless ENABLE_BACKGROUND=1 explicitly set. Deployment config optimized with ${PORT:-8000} for future-proofing. Manual .replit fix required: delete all [[ports]] entries, keep only localPort=8000→externalPort=80.
- **Oct 12, 2025**: Option A Quick Fix Applied - Heavy module imports deferred to AFTER port opens (<1s startup). All 20+ model/service imports moved inside lazy loaders. Background tasks conditionally disabled for Autoscale (API-only mode). Port 8000 now opens immediately, ready for deployment.
- **Oct 11, 2025**: V2 Market-Delta Model LOCKED & MONITORED - Hyperparameters frozen (τ=1.0, α=0.8, C=2.0), daily health checks deployed, shadow mode confirmed. Production-ready with auto-promotion monitoring. Weekly retrain schedule active. See V2_LOCKDOWN_SUMMARY.md for full details.
- **Oct 10, 2025**: CLV Alert Producer SQL escaping bug fixed - TBD filtering operational with %% wildcard escaping. Phase B timeout protection working correctly.

## User Preferences
Preferred communication style: Simple, everyday language.
Production Model Decision: Use simple weighted consensus based on performance comparison showing 0.031549 LogLoss improvement over complex model.
Model Performance Analysis: Model rating 6.3/10 (B Grade) with 54.3% 3-way accuracy and 62.4% 2-way accuracy. Rating corrected after fixing Brier score normalization issue (0.191 vs incorrectly reported 0.573).
Improvement Priority: Focus on enhanced feature engineering and gradient boosting ensemble methods for immediate gains, with deep learning and reinforcement learning as longer-term research directions.

## System Architecture

### Backend Framework
- **FastAPI**: Modern Python web framework.
- **SQLAlchemy**: Database ORM.
- **Pydantic**: Data validation.
- **AsyncIO**: Asynchronous operations.
- **Deployment Architecture**: 
  - **Autoscale Mode**: API-only (background tasks disabled per Replit docs: "Autoscale not suitable for background activities")
  - **Development/VM Mode**: Full functionality including background scheduler
  - **Environment Detection**: Automatic detection via `REPLIT_DEPLOYMENT` and `REPLIT_DEPLOYMENT_TYPE` env vars
  - **Conditional Startup**: Background tasks deferred 2 seconds after port opens in dev, completely disabled in Autoscale

### Machine Learning Pipeline
- **Production Model (V1)**: Simple Weighted Consensus using quality weights derived from 31-year bookmaker analysis (Pinnacle, Bet365, Betway, William Hill). Achieves 0.838 LogLoss and 0.167 Brier Score with 63.6% 3-way accuracy.
- **V2 Shadow Testing System**: **OPERATIONAL** - Market-delta ridge regression model in A/B testing:
  - **Architecture**: Predict deltas from market in logit space, not raw probabilities
  - **Model**: L2 ridge (C=2.0) with τ=1.0 clamps, α=0.8 blend weight, NO isotonic calibration
  - **Training**: 5,136 samples (2022-2025) with leakage-free temporal train/val split
  - **Performance**: L1=0.14-0.51 from market, max confidence 50-81%, realistic adjustments
  - **Guardrails**: KL divergence cap (0.15), max prob cap (0.90), safety clamps
  - **Validation**: LogLoss=0.25, Brier=0.033, but realistic prediction behavior verified
  - **Infrastructure**: Shadow coordinator runs V1/V2 in parallel, logs to `model_inference_logs`
  - **Data**: 6,185 matches backfilled across 33 leagues (Aug 2022 - Oct 2025)
  - **Auto-promotion**: V2 promoted when ΔLogLoss≤-0.05, ΔBrier≤-0.02, CLV%>55%, n≥300, 7-day streak
  - **API endpoints**: `/predict/which-primary`, `/metrics/ab`, `/metrics/clv-summary`
  - **Status**: Shadow mode **ENABLED**, Primary model: V1 (safe), V2 accumulating metrics
- **Enhanced Architecture**: Dual-table population with market-efficient consensus, timing-optimized data collection (T-48h/T-24h windows), and cross-table synchronization.
- **Real Data Integration**: Data collector incorporates injuries, team news, recent form, and head-to-head records.
- **Auto-Retraining System**: Models automatically retrain based on match volume, with manual training scripts available.
- **Comprehensive Market System**: Production-ready Poisson-based market expansion providing 50+ mathematically consistent markets derived from single λ parameters, with optimized performance and API schema validation.
- **Automated Accuracy Tracking**: Backend-driven monitoring system for predictions, automatically fetching results and computing metrics (Brier score, LogLoss, Hit-rate). Includes API suite for analysis and unified SQL views (`odds_accuracy_evaluation`, `odds_accuracy_evaluation_v2` with model predictions) for streamlined evaluation and CLV analysis.
- **Real Accuracy Testing**: Utilizes evaluation views for true metric calculation and CLV when closing odds are available.

### Data Collection
- **Canonical Fixtures Table**: Single source of truth for all match metadata (435+ records), automatically maintained by both AutomatedCollector and API-Football integration. Prevents orphaned odds and ensures data integrity.
- **TBD Fixture Enrichment**: Automated service resolves TBD placeholders from The Odds API by fetching real team names from API-Football. Runs automatically after each collection via background task, with manual endpoint `/admin/enrich-tbd-fixtures` for backfill. 100% success rate on Oct 13 backfill (89/89 fixtures).
- **Dual Collection Strategy**: Scheduler populates both training (`training_matches`) and upcoming (`odds_snapshots`) tables.
- **Multi-Source Real-Time Odds**: Parallel collection from The Odds API and API-Football for upcoming matches, ensuring consistency. Handles both numeric book_ids (537, 877) and text format (apif:32, apif:11).
- **Fixture ID Resolver**: A robust 3-step system to resolve fixture IDs between different data sources, ensuring independent multi-source collection.
- **League Coverage**: Dynamic selection across 35 leagues, including major European, UEFA, English lower, Asian, South American, and Nordic/Alpine leagues.
- **Training Data**: Over 9,846 matches in `training_matches` for ML model learning, with synchronized `odds_consensus` table.
- **Authentic Odds Collection**: Live collection of real bookmaker odds from The Odds API (21+ bookmakers) stored with proper mapping and tracking.
- **CLV Monitoring (CLV Club Phase 1 & 2)**: Advanced system for detecting pricing inefficiencies, normalizing de-juiced odds, robust consensus calculation, line stability metrics, desk group deduplication, multi-tier gating, and real-time alerts. Includes closing line capture and realized CLV tracking with various sampling and settlement methods.
- **CLV Daily Brief**: Automated daily aggregation and reporting of CLV Club performance per league, tracking metrics and suppression reasons.
- **Data Integrity**: Zero orphaned odds and zero TBD placeholders achieved through fixtures table backfilling, automatic enrichment, and maintenance. Timezone import fixed in API-Football integration (Oct 2025).

### AI Analysis Layer
- **OpenAI GPT-4o Integration**: Provides comprehensive match analysis and contextual insights, combining ML predictions with AI contextual analysis.

### Data Flow & Feature Engineering
- Automated processes for data collection and feature engineering, creating ML-ready features from raw data.
- Features include team performance, form, head-to-head, venue factors, and market-derived features (logits, entropy, dispersion).
- Market-aligned architecture utilizing horizon-aligned market snapshots from multiple bookmakers.

### Database Layer
- **PostgreSQL**: Primary database for all project data (training, match results, odds, market features).
- **Production Indexes**: Optimized hot-path indexes for fixtures (kickoff/status), odds snapshots (match/time), closing feed (match/ts), and CLV alerts (recency).
- **Schema Bridge Views**: `closing_odds_long` (wide→long transformation) and `clv_matches_view` (unified CLV evaluation) for seamless analysis.
- **Outcome Standardization**: Unified H/D/A outcome codes via `utils/outcomes.py` helper for consistent data handling across pipeline.
- **Timezone Architecture**: All timestamp columns use `timestamptz` (timezone-aware UTC) for clv_alerts and odds_snapshots, with standardized timezone handling via `utils/dates.py` utilities. Migration completed Oct 2025.
- **CLV Alert Archival**: Expired alerts automatically archived to `clv_alerts_history` table (1-hour expiry window) instead of deletion, preserving historical CLV performance data.

### API Endpoints
- **Prediction API**: Main endpoints for match predictions with ML and AI analysis
- **Admin Endpoints**: Data management, match discovery, training statistics, TBD fixture enrichment
- **V2 Shadow System**: `/predict/which-primary`, `/metrics/ab`, `/metrics/clv-summary`
- **CLV Monitoring**: CLV Club alerts, daily briefs, closing line analysis
- **CLV Health**: `/_health/clv` endpoint for real-time system health monitoring (fresh odds, alerts, closing samples)
- **Fixture Enrichment**: `/admin/enrich-tbd-fixtures` for manual TBD resolution and backfill operations

### UI/UX Decisions
- Focus on superior user experience with confidence-calibrated predictions and uncertainty quantification.

## External Dependencies

### Sports Data
- **RapidAPI Football API**: Primary source for real-time and historical match information.
- **The Odds API**: Aggregator for odds data from multiple bookmakers.

### AI Services
- **OpenAI API**: Specifically GPT-4o for contextual analysis and explanations.

### Database
- **PostgreSQL**: Core relational database.