# BetGenius AI - Sports Prediction Backend

## Overview
BetGenius AI is a sports prediction platform that provides intelligent football match predictions using advanced machine learning and AI analysis. The project aims to deliver market-relative performance, a superior user experience with confidence-calibrated predictions, and sophisticated risk management tools for sports betting in key African markets. Its core capabilities include comprehensive data collection, robust ML models, AI-powered contextual analysis, and strategic market intelligence.

## User Preferences
Preferred communication style: Simple, everyday language.
Production Model Decision: Use simple weighted consensus based on performance comparison showing 0.031549 LogLoss improvement over complex model.
Model Performance Analysis: Model rating 6.3/10 (B Grade) with 54.3% 3-way accuracy and 62.4% 2-way accuracy. Rating corrected after fixing Brier score normalization issue (0.191 vs incorrectly reported 0.573).
Improvement Priority: Focus on enhanced feature engineering and gradient boosting ensemble methods for immediate gains, with deep learning and reinforcement learning as longer-term research directions.
**Historical Feature Pipeline**: Reusable feature extraction system extracting 65 features (24 form, 10 venue, 7 H2H, 8 temporal, 16 advanced stats) from 32 years of match data. Provides 100% feature coverage for LightGBM training.
**Training Dataset Expansion (Oct 2025)**: **MASSIVE EXPANSION COMPLETE** - Historical database expanded from 25,174 to **40,769 matches** (+61.9%, +15,595 matches). Trainable dataset grew from 21,406 to **36,942 matches** (+72.6%, +15,536 matches). Added 5 new leagues: Belgium (Jupiler League: 2,014), Turkey (Super Lig: 2,476), Portugal (Primeira Liga: 2,142), Netherlands (Eredivisie: 2,068), Greece (197). Major leagues now have extensive coverage: Serie A (5,343 matches, 22 seasons), La Liga (5,320, 19 seasons), Premier League (5,402, 18 seasons), Bundesliga (4,172, 19 seasons), Ligue 1 (3,699, 14 seasons). Date range: 1993-2025.
**EV/CLV Evaluation Framework (Oct 2025)**: Production-ready evaluation pipeline built with hit@coverage analysis, EV decile tables, and per-league ECE calibration. Baseline tested on 36,942 matches showing perfect monotonicity (confidence → accuracy) and excellent calibration (ECE 0.0095). Framework enables data-driven promotion decisions with 5 criteria gate: Δ LogLoss ≤ -0.02, positive EV rate, hit@coverage dominance at 60-65%, ECE < 0.08, and 55-60% 3-way accuracy target.

## System Architecture

### Backend Framework
- **FastAPI**: Modern Python web framework for API development.
- **SQLAlchemy**: ORM for database interactions.
- **Pydantic**: For data validation.
- **AsyncIO**: For asynchronous operations.
- **Deployment Architecture**: Supports both Autoscale (API-only) and Development/VM (full functionality with background scheduler) modes, with automatic environment detection and conditional startup logic.

### Machine Learning Pipeline
- **Metrics Hygiene**: Implemented defensive probability normalization, pre-kickoff filtering, and ECE + reliability curves for robust model evaluation. V2 model shows improved Brier and LogLoss compared to V1.
- **Calibration & Constraints**: Extensive testing of temperature scaling and blend/KL/Δτ sweeps determined that the V2 training configuration is already optimal for current features.
- **Historical Feature Engineering Pipeline**: Operational extraction system built on 14,527 matches (1993-2024) from `historical_odds` table. Extracts 65 features per match: team form (last 5), venue performance (last 10), head-to-head (last 5), temporal features, and advanced stats (shooting, discipline). Pipeline is reusable across all leagues.
- **LightGBM Development**: Validated pipeline with fixed label encoding (H=0, D=1, A=2). **Enriched Model (Oct 2025):** Trained on 36,942 matches (1993-2025) using 62 features (12 market + 50 historical). Full OOF evaluation: 52.7% 3-way accuracy, 75.9% hit rate @ 62% confidence threshold (17.3% coverage), 80.6% top decile accuracy. Model ensemble (5-fold CV) deployed as V2 LightGBM predictor service.
- **Production Model (V1)**: Utilizes a simple weighted consensus based on bookmaker analysis (54.3% historical accuracy).
- **V2 LightGBM Production Deployment (Oct 2025)**: V2 SELECT endpoint launched with strict quality gate (conf >= 0.62, EV > 0). Three-tier product strategy: Free `/market` (both V1+V2), Free `/predict` (V1 + optional AI), Premium `/predict-v2` (V2 SELECT + always-on AI analysis). All endpoints require API key authentication. MVP uses market-only features pending historical feature integration.
- **V2 Shadow Testing System**: An operational market-delta ridge regression model running in shadow mode (A/B testing) alongside V1. It predicts deltas from the market in logit space, with guardrails like KL divergence and probability caps. Features auto-promotion criteria for V2 to become primary.
- **Enhanced Architecture**: Dual-table population, timing-optimized data collection, and cross-table synchronization.
- **Auto-Retraining System**: Models retrain automatically based on match volume.
- **Comprehensive Market System**: Poisson-based market expansion providing 50+ mathematically consistent markets.
- **Automated Accuracy Tracking**: Backend monitoring system for predictions, calculating metrics (Brier score, LogLoss, Hit-rate) and supporting CLV analysis.

### Data Collection
- **Canonical Fixtures Table**: Single source of truth for match metadata, preventing data inconsistencies.
- **TBD Fixture Enrichment**: Automated service resolves "To Be Determined" placeholders from The Odds API using API-Football data.
- **Dual Collection Strategy**: Scheduler populates training and upcoming odds tables.
- **Multi-Source Real-Time Odds**: Parallel collection from The Odds API and API-Football.
- **Fixture ID Resolver**: Robust system for resolving fixture IDs across different data sources.
- **League Coverage**: Dynamic selection across 35 leagues.
- **Training Data**: Over 9,846 matches for ML model training, synchronized with odds consensus.
- **Historical Match Data**: **40,769 matches** (1993-2025) across 14 leagues with results, bookmaker odds (Bet365, Pinnacle, William Hill, etc.), and in-game statistics (shots, corners, cards). Powers historical feature engineering pipeline and LightGBM training via CSV import from football-data.co.uk. Deduplication system ensures clean imports. **36,942 trainable matches** with complete odds data (2000+).
- **Authentic Odds Collection**: Live collection from 21+ bookmakers via The Odds API.
- **CLV Monitoring**: Advanced system for detecting pricing inefficiencies, robust consensus calculation, and real-time alerts. Includes closing line capture and realized CLV tracking.
- **CLV Daily Brief**: Automated daily aggregation and reporting of CLV performance.
- **Data Integrity**: Achieved through fixture backfilling, automatic enrichment, and timezone handling.

### AI Analysis Layer
- **OpenAI GPT-4o Integration**: Provides comprehensive match analysis and contextual insights.

### Data Flow & Feature Engineering
- Automated processes create ML-ready features from raw data, including team performance, form, head-to-head, venue factors, and market-derived features. Utilizes horizon-aligned market snapshots.

### Database Layer
- **PostgreSQL**: Primary database for all project data.
- **Production Indexes**: Optimized indexes for critical tables.
- **Schema Bridge Views**: `closing_odds_long` and `clv_matches_view` for streamlined analysis.
- **Outcome Standardization**: Unified H/D/A outcome codes for consistent data handling.
- **Timezone Architecture**: All timestamp columns use timezone-aware UTC.
- **CLV Alert Archival**: Expired alerts are archived instead of deleted to preserve historical data.
- **Match Status Architecture**: Database only stores 2 status values (`'scheduled'`, `'finished'`). "Upcoming" matches determined by time-based filtering (`kickoff_at > NOW() AND status = 'scheduled'`). This approach is more reliable than status flags and requires no maintenance.

### API Endpoints
- **Prediction API**: Main endpoints for match predictions.
  - `/predict` - V1 consensus predictions with optional AI analysis
  - `/predict-v2` - **NEW (Oct 2025)** V2 SELECT endpoint (premium, high-confidence only: conf >= 0.62, EV > 0). Uses V2 LightGBM model (52.7% overall, 75.9% @ 62% threshold). Requires API key authentication.
  - `/market` - **NEW (Oct 2025)** Market board showing both V1 + V2 predictions side-by-side (free tier, authenticated). Designed for real-time odds comparison with premium upgrade CTA. **Architecture:** Reads pre-computed V1 from `consensus_predictions` (updated every 60s by scheduler), fetches latest odds from `odds_snapshots`, generates V2 on-demand. Uses time-based filtering (`kickoff_at > NOW()`) instead of status flags for "upcoming" matches. Response time: ~500ms for 10 matches.
- **Admin Endpoints**: For data management, match discovery, and training statistics.
- **V2 Shadow System Endpoints**: `/predict/which-primary`, `/metrics/ab`, `/metrics/clv-summary`.
- **Calibration & Optimization Endpoints**: `/metrics/evaluation`, `/metrics/temperature-scaling`.
- **CLV Monitoring Endpoints**: For alerts, daily briefs, and closing line analysis.
- **CLV Health Endpoint**: `/_health/clv` for real-time system health monitoring.
- **Fixture Enrichment Endpoint**: `/admin/enrich-tbd-fixtures` for manual TBD resolution.

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