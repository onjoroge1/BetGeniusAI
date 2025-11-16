# BetGenius AI - Sports Prediction Backend

## Overview
BetGenius AI is a sports prediction platform that delivers intelligent football match predictions using advanced machine learning and AI analysis. Its primary purpose is to offer market-relative performance, a superior user experience with confidence-calibrated predictions, and sophisticated risk management tools for sports betting in key African markets. Key capabilities include comprehensive data collection, robust ML models, AI-powered contextual analysis, strategic market intelligence, and a full live betting intelligence stack with real-time momentum scoring and WebSocket streaming.

## User Preferences
Preferred communication style: Simple, everyday language.
Production Model Decision: Use simple weighted consensus based on performance comparison showing 0.031549 LogLoss improvement over complex model.
Model Performance Analysis: Model rating 6.3/10 (B Grade) with 54.3% 3-way accuracy and 62.4% 2-way accuracy. Rating corrected after fixing Brier score normalization issue (0.191 vs incorrectly reported 0.573).
Improvement Priority: Focus on enhanced feature engineering and gradient boosting ensemble methods for immediate gains, with deep learning and reinforcement learning as longer-term research directions.
V2.1 Transformation Strategy: Approved relative ratio transformations (rest_advantage, congestion_ratio) with corrected parity formula achieving 27.01% uniqueness (down from 81.61%). Alternative binned features available (2.04% uniqueness) if needed.

## System Architecture

### Backend Framework
- **FastAPI**: Python web framework.
- **SQLAlchemy**: ORM for database interactions.
- **Pydantic**: For data validation.
- **AsyncIO**: For asynchronous operations.
- **Deployment Architecture**: Supports Autoscale (API-only) and Development/VM (full functionality with background scheduler) modes.

### Machine Learning Pipeline
- **Models**: Production V1 (weighted consensus) and V2 (LightGBM ensemble) models. V2.3 (2025-11-16) uses leak-free match_context_v2 table with 0% contamination.
- **Feature Engineering**: Reusable pipeline with 46 features for V2.3 (40 base + 2 context_transformed + 4 drift). All context features computed using ONLY past matches with strict T-1h cutoff.
- **Leak Elimination (2025-11-16)**: Replaced contaminated match_context table (100% post-match data) with match_context_v2 (0% contamination, validated). Automated pipeline ensures all context data uses as_of_time = match_date - 1 hour.
- **Training Data**: 1,370 matches (2020+) with 100% clean context coverage. Historical backfill completed via scripts/backfill_match_context_v2.py.
- **Calibration & Constraints**: Extensive testing for optimal model configuration including random-label sanity checks (<40% target).
- **Shadow Testing System**: Operational market-delta ridge regression for A/B testing and auto-promotion.
- **Auto-Retraining System**: Models retrain automatically based on match volume.
- **Match Context Builder**: Automated service runs every 5 minutes in scheduler, populates match_context_v2 for new matches with zero manual intervention.
- **Market System**: Poisson-based market expansion providing 50+ mathematically consistent markets.
- **Accuracy Tracking**: Automated backend monitoring for predictions, calculating metrics (Brier score, LogLoss, Hit-rate).
- **Live Betting Intelligence**: Includes a Momentum Engine (0-100 scoring based on weighted features) and a Live Market Engine for in-play predictions with time-aware blending and momentum boost.

### Data Collection
- **Canonical Fixtures Table**: Single source of truth for match metadata.
- **TBD Fixture Enrichment**: Automated service resolves "To Be Determined" placeholders.
- **Multi-Source Real-Time Odds**: Parallel collection from The Odds API and API-Football.
- **Fixture ID Resolver**: Advanced system for high linkage rates.
- **Historical Match Data**: Extensive historical data (40,769 matches from 1993-2025) with results, bookmaker odds, and in-game statistics.
- **CLV Monitoring**: Advanced system for detecting pricing inefficiencies, robust consensus calculation, real-time alerts, and closing line capture.
- **Observability**: Prometheus metrics, Grafana dashboards, and operations runbook.

### AI Analysis Layer
- **OpenAI GPT-4o Integration**: Provides comprehensive match analysis and contextual insights.

### Data Flow & Feature Engineering
- Automated processes for creating ML-ready features from raw data, utilizing horizon-aligned market snapshots.

### Database Layer
- **PostgreSQL**: Primary database with optimized production indexes.
- **Schema Bridge Views**: For streamlined analysis.
- **Outcome Standardization**: Unified H/D/A outcome codes.
- **Timezone Architecture**: All timestamp columns are timezone-aware UTC.
- **Match Status Architecture**: Database stores 'scheduled' and 'finished' statuses, with upcoming matches determined by time-based filtering.
- **Team Logo System**: Dimension table with logo_url and API Football team ID mapping, intelligent enrichment service.

### API Endpoints
- **Prediction API**: `/predict` (V1 consensus), `/predict-v2` (premium V2 SELECT), `/market` (market board with V1/V2, team logos, status filters: upcoming, live, finished). Recent fix (2025-11-15): Dynamic status determination, added momentum and model_markets fields for live matches, fixed live data conditional logic.
- **Betting Intelligence API**: `/betting-intelligence/{match_id}` (per-match CLV, edge, Kelly sizing), `/betting-intelligence` (curated opportunities). Features include edge calculation, CLV analysis, and Kelly Criterion optimal stake sizing.
- **WebSocket Streaming**: `/ws/live/{match_id}` for real-time match events and prediction updates.
- **Admin Endpoints**: For data management, match discovery, and training statistics.
- **Monitoring Endpoints**: For CLV health, shadow system metrics, and model evaluation.

### UI/UX Decisions
- Focus on superior user experience with confidence-calibrated predictions and uncertainty quantification.

## External Dependencies

### Sports Data
- **RapidAPI Football API**: For real-time and historical match information.
- **The Odds API**: For aggregated odds data.

### AI Services
- **OpenAI API**: Specifically GPT-4o for contextual analysis.

### Database
- **PostgreSQL**: Core relational database.