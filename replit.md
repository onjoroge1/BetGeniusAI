# BetGenius AI - Sports Prediction Backend

## Overview
BetGenius AI is a sports prediction platform that provides intelligent football match predictions using advanced machine learning and AI analysis. The project aims to deliver market-relative performance, a superior user experience with confidence-calibrated predictions, and sophisticated risk management tools for sports betting in key African markets. Its core capabilities include comprehensive data collection, robust ML models, AI-powered contextual analysis, and strategic market intelligence.

## User Preferences
Preferred communication style: Simple, everyday language.
Production Model Decision: Use simple weighted consensus based on performance comparison showing 0.031549 LogLoss improvement over complex model.
Model Performance Analysis: Model rating 6.3/10 (B Grade) with 54.3% 3-way accuracy and 62.4% 2-way accuracy. Rating corrected after fixing Brier score normalization issue (0.191 vs incorrectly reported 0.573).
Improvement Priority: Focus on enhanced feature engineering and gradient boosting ensemble methods for immediate gains, with deep learning and reinforcement learning as longer-term research directions.

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
- **Feature Enrichment & LightGBM**: Infrastructure is built for `market_features`, `elo_ratings`, and `team_features`. Aims to transition to LightGBM with more extensive, multi-league data (target: ≥1,000 labeled matches) for significant performance gains.
- **Production Model (V1)**: Utilizes a simple weighted consensus based on bookmaker analysis.
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

### API Endpoints
- **Prediction API**: Main endpoints for match predictions.
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