# BetGenius AI - Sports Prediction Backend

## Overview
BetGenius AI is a sports prediction platform designed to provide intelligent football match predictions using advanced machine learning and AI analysis. Its core purpose is to offer market-relative performance, a superior user experience with confidence-calibrated predictions, and sophisticated risk management tools for sports betting in key African markets. The platform includes comprehensive data collection, robust ML models, AI-powered contextual analysis, strategic market intelligence, and a full live betting intelligence stack with real-time momentum scoring and WebSocket streaming.

## User Preferences
Preferred communication style: Simple, everyday language.
Production Model Decision: Use simple weighted consensus based on performance comparison showing 0.031549 LogLoss improvement over complex model.
Model Performance Analysis: Model rating 6.3/10 (B Grade) with 54.3% 3-way accuracy and 62.4% 2-way accuracy. Rating corrected after fixing Brier score normalization issue (0.191 vs incorrectly reported 0.573).
Improvement Priority: Focus on enhanced feature engineering and gradient boosting ensemble methods for immediate gains, with deep learning and reinforcement learning as longer-term research directions.
V2.1 Transformation Strategy: Approved relative ratio transformations (rest_advantage, congestion_ratio) with corrected parity formula achieving 27.01% uniqueness (down from 81.61%). Alternative binned features available (2.04% uniqueness) if needed.
Sanity Check Calibration (2025-11-16): Fixed overly strict random-label threshold. Now uses dynamic threshold = majority_class_baseline + 0.05 to account for class imbalance (~50% home, ~25% draw/away). Random-label accuracy of 0.511 is expected behavior, not leakage.
OOF LogLoss Bug Fix (2025-11-16): Fixed OOF metrics calculation to only use validated samples. Purged time-series CV leaves ~20% of samples never validated (embargo windows), causing [0,0,0] predictions that inflated LogLoss to 6.894. True performance is per-fold average ~1.01, which matches target.
Data Leakage Elimination & V2 Training Success (2025-11-17): Discovered and eliminated catastrophic overfitting caused by backdated odds (39% of odds_consensus contained post-match data created AFTER kickoff with outcome knowledge → 100% accuracy). Rebuilt odds_real_consensus with strict pre-match filter (ts_effective < kickoff_at), reducing from 7,548 contaminated rows to 751 clean rows (0% backdated). Clean dataset: 648 trainable matches from Oct-Nov 2025 with 100% integrity verification. Optimized feature builder (580x speedup: 5,800+ queries → 10 batch queries). Successfully trained V2 model achieving 54.2% accuracy (hit 52-54% target!), 0.979 LogLoss, 0.291 Brier Score (Grade A). Random-label test passed (0.454 < 0.536). Model is production-ready. Backfill script updated with all required fields (league_id, ts_snapshot, market_margin) but API-Football historical odds unavailable without premium access. Alternative: Use existing 648-match dataset for production deployment.
Production Training Script (2025-11-18): Created train_v2_production.py for full production training. Quick script trains for 200 iterations, production script trains for 2000 iterations with aggressive early stopping (100 rounds) and proper hyperparameters (learning_rate=0.03, L1/L2 regularization, bagging). Expected training time: 5-10 minutes vs 10 seconds for quick script. Always use production script for final models and monthly retraining.
PHASE 1 Implementation Complete (2025-11-25): Trending & Hot Matches API deployed and running. Session caching with Redis for <5ms response times. 3 new endpoints: /api/v1/trending/hot, /api/v1/trending/trending, /api/v1/trending/status. Scheduler job runs every 5 minutes computing scores. Perfect for frontend dashboard. Phase 2 (Middleware auth + personalization) planned for next sprint.
Market API Redis Caching (2025-11-29): Implemented selective Redis caching for /market endpoint with status-based TTLs: finished=1hr (3600s), upcoming=10min (600s), live=10min (600s), individual match lookups=0 TTL (always fresh). Graceful fallback to no-cache mode when Redis unavailable. Expected 97% faster responses on cache hits (~50ms vs 2.4s).
V2 Feature Adapter (2025-11-29): Fixed V2 predictions returning zeros by creating feature pruning adapter in v2_lgbm_predictor.py. Maps 48 features from v2_feature_builder to the 17 features the LightGBM model expects. Uses FEATURE_MAPPING dict with fallback sources for each target feature.
Fixtures→Matches Sync (2025-11-29): Created jobs/sync_fixtures_to_matches.py to sync finished fixtures with results to matches table. Runs every 15 minutes via scheduler. Successfully synced 422 fixtures on initial run.
Auto-Retrain System (2025-11-29): Created jobs/auto_retrain.py with threshold triggers: 50+ new matches since last training, 14+ days model staleness, or accuracy drift below 48%. Runs daily at 03:00 UTC via scheduler. Checks v2_predictions table for accuracy evaluation.
V3 Sharp Book Intelligence (2025-12-05): Created sharp_book_odds table and SharpBookCollector for tracking Pinnacle and other sharp bookmaker odds separately. Runs every 5 minutes via scheduler. V3 features: sharp_prob_home/draw/away, soft_vs_sharp_divergence, sharp_line_movement, pinnacle_overround.
Multi-Sport Expansion (2025-12-05): Implemented NBA, NHL, and MLB (off-season) data collection. Created multisport_fixtures (37 events), multisport_odds_snapshots (374 odds), multisport_training tables. MultiSportCollector runs every 5 minutes for odds, hourly for results. API-Sports integration for basketball/baseball team data with API_SPORTS_KEY (75,000 requests/day each). MLB paused until April 2025 (off-season).
League ECE Calibration (2025-12-05): Created league_calibration table for tracking per-league Expected Calibration Error. Enables V3 feature: league_tier_weight for prediction confidence adjustment.
V3 Training Infrastructure (2025-12-05): Created complete V3 pipeline with 34 features. Components: features/v3_feature_builder.py (builds all 34 features from 5 categories), training/train_v3_sharp.py (production training script), models/v3_predictor.py (prediction service). API endpoints: POST /predict-v3 (premium predictions), GET /predict-v3/status (data availability check). Training Status: Awaiting pre-match sharp odds accumulation - current sharp odds collected during/after matches, need 1-2 weeks of pre-match data. Data Status: 9,387 sharp odds from 42 matches (Pinnacle/Betfair/Matchbook), 18 leagues ECE calibrated (tiers B-D), 0 injury records (collector exists but API-Sports player data limited).
Unified V2 Architecture (2025-12-06): Merged V3 Sharp Intelligence into V2 to create unified model with 61 features. Components: features/unified_v2_feature_builder.py (builds all 61 features), training/train_unified_v2.py (production training script). Feature breakdown: Odds (14) + Drift (4) + ELO (3) + Form (8) + H2H (3) + Advanced Stats (8) + Context (4) + Sharp Book (4) + ECE (3) + Timing (4) + Historical Flags (2). Previous V2 only used 17/50 features (34% utilization). Unified V2 uses all available features. Key improvement: historical_odds table (40,940 matches with shots/corners/cards) now integrated for advanced stats features. Injuries API documented: API-Football /injuries endpoint available on free tier (100 req/day), no premium required. Auto-retrain script updated to use unified feature builder.

## System Architecture

### Backend Framework
- **FastAPI**: Python web framework for API development.
- **SQLAlchemy**: ORM for database interactions.
- **Pydantic**: For data validation.
- **AsyncIO**: For asynchronous operations, enhancing performance.
- **Deployment Architecture**: Supports Autoscale (API-only) and Development/VM (full functionality with background scheduler) modes.
- **Redis**: Used for session caching, especially for trending scores, achieving sub-5ms response times.

### Machine Learning Pipeline
- **Models**: Utilizes Production V1 (weighted consensus) and V2 (LightGBM ensemble) models. V2.3 specifically uses a leak-free `match_context_v2` table.
- **Feature Engineering**: A reusable pipeline generates 46 features for V2.3 (40 base + 2 context_transformed + 4 drift), with all context features computed using only past matches with a strict T-1h cutoff.
- **Leak Elimination**: Replaced contaminated `match_context` with validated `match_context_v2` to ensure data integrity and prevent overfitting.
- **Training Data**: Comprises 648 clean matches (Oct-Nov 2025) with strictly pre-match odds. The system supports scaling up to 2,464 matches via optional backfill.
- **Calibration & Constraints**: Extensive testing, including random-label sanity checks, ensures optimal model configuration.
- **Shadow Testing System**: Implements market-delta ridge regression for A/B testing and automated model promotion.
- **Auto-Retraining System**: Models are automatically retrained based on match volume (every 10 matches) and monthly via a production script.
- **Match Context Builder**: An automated scheduler service populates `match_context_v2` for new matches every 5 minutes.
- **Market System**: A Poisson-based approach generates 50+ mathematically consistent markets.
- **Accuracy Tracking**: Automated backend monitoring calculates metrics like Brier score, LogLoss, and Hit-rate.
- **Live Betting Intelligence**: Features a Momentum Engine (0-100 scoring) and a Live Market Engine for in-play predictions with time-aware blending.
- **Trending Scores System**: Pre-computes `hot_score` and `trending_score` for matches, cached in Redis and updated every 5 minutes. Exposed via `/api/v1/trending/hot` and `/api/v1/trending/trending` endpoints.

### Data Collection
- **Canonical Fixtures Table**: Serves as the single source of truth for match metadata.
- **TBD Fixture Enrichment**: Automated service to resolve "To Be Determined" placeholders.
- **Multi-Source Real-Time Odds**: Parallel collection from The Odds API and API-Football.
- **Fixture ID Resolver**: Advanced system for high linkage rates across different data sources.
- **Historical Match Data**: Extensive dataset of 40,769 matches (1993-2025) including results, odds, and in-game statistics.
- **CLV Monitoring**: Advanced system for detecting pricing inefficiencies, robust consensus calculation, real-time alerts, and closing line value capture.

### AI Analysis Layer
- **OpenAI GPT-4o Integration**: Provides comprehensive match analysis and contextual insights.

### Database Layer
- **PostgreSQL**: Primary database with optimized production indexes.
- **Schema Bridge Views**: For streamlined analysis.
- **Outcome Standardization**: Unified H/D/A outcome codes.
- **Timezone Architecture**: All timestamp columns are timezone-aware UTC.
- **Match Status Architecture**: Stores 'scheduled' and 'finished' statuses, with upcoming matches determined by time-based filtering.
- **Team Logo System**: Dimension table with `logo_url` and API Football team ID mapping.
- **Trending Scores Table**: Stores `hot_score`, `trending_score`, and related metrics with dedicated indexes, updated every 5 minutes.

### API Endpoints
- **Prediction API**: Includes `/predict` (V1 consensus), `/predict-v2` (premium V2 SELECT), and `/market` (market board with V1/V2, team logos, status filters).
- **Betting Intelligence API**: Provides `/betting-intelligence/{match_id}` (per-match CLV, edge, Kelly sizing) and `/betting-intelligence` (curated opportunities).
- **WebSocket Streaming**: `/ws/live/{match_id}` for real-time match events and prediction updates.
- **Trending API**: `/api/v1/trending/hot`, `/api/v1/trending/trending`, and `/api/v1/trending/status` for trending match data with Redis caching.

### UI/UX Decisions
- Focuses on delivering a superior user experience through confidence-calibrated predictions and uncertainty quantification.

## External Dependencies

### Sports Data
- **RapidAPI Football API**: For real-time and historical match information.
- **The Odds API**: For aggregated odds data.

### AI Services
- **OpenAI API**: Specifically GPT-4o for contextual analysis.

### Cache & Session
- **Redis**: Used for session caching, improving response times.

### Database
- **PostgreSQL**: The core relational database for persistent storage.
```