# BetGenius AI - Sports Prediction Backend

## Overview
BetGenius AI is a sports prediction platform that provides intelligent football match predictions using advanced machine learning and AI analysis. Its primary purpose is to deliver market-relative performance, a superior user experience with confidence-calibrated predictions, and sophisticated risk management tools for sports betting in key African markets. The platform features comprehensive data collection, robust ML models, AI-powered contextual analysis, strategic market intelligence, and a full live betting intelligence stack with real-time momentum scoring and WebSocket streaming. The project aims to incorporate multi-sport expansion (NBA, NHL, MLB) and advanced sharp book intelligence for V3. A key ambition is to offer AI-curated parlay recommendations with correlation adjustments and edge calculations.

## User Preferences
Preferred communication style: Simple, everyday language.
Production Model Decision: Use simple weighted consensus based on performance comparison showing 0.031549 LogLoss improvement over complex model.
Improvement Priority: Focus on enhanced feature engineering and gradient boosting ensemble methods for immediate gains, with deep learning and reinforcement learning as longer-term research directions.
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
Historical Features Backfill (2025-12-07): Created system to populate H2H, form, and advanced stats from historical_odds table (22,335+ matches since 2020). Components: league_code_mapping table (21 leagues mapped E0→39, SP1→140, etc.), team_name_mapping table (138 teams across 5 major leagues), historical_features table (401 matches with 87.6% coverage), scripts/backfill_historical_features.py (backfill script). Feature builder now uses historical_features as primary source with fallback to training_matches. Form features normalized to per-match averages (points/n_matches * 3) for consistency with legacy implementation. Coverage: 97.8% H2H, 100% form, 100% advanced stats. To expand: add more team mappings and run backfill script for additional leagues.
Unified V2 Training Results (2025-12-10): Trained unified V2 model with 50 features, achieving 50.2% accuracy (up from 47.7%), 1.0173 LogLoss, 0.2027 Brier Score. Top features: rest_days (275), shots_avg (253), h2h_wins (242), corners_avg (218). Sharp book features excluded due to 0.6% coverage - need 2-4 weeks more data collection to reach 50%+ coverage for +2-5% accuracy boost.
Parlay Betting System (2025-12-10): Full parlay system implemented with AI-curated recommendations. Components: models/parlay_builder.py (correlation-adjusted probability calculator), routes/parlays.py (5 API endpoints), jobs/settle_parlays.py (performance tracking). Database: parlay_consensus, parlay_legs, parlay_performance tables. Features: same-day parlays, league-based parlays, correlation penalties (10-15% for same-league), edge calculation (model vs market), confidence tiers (high/medium/low). Scheduler jobs run every 5 minutes (generation) and 15 minutes (settlement). API endpoints: /api/v1/parlays, /api/v1/parlays/recommended, /api/v1/parlays/build, /api/v1/parlays/status, /api/v1/parlays/performance.

## System Architecture

### Backend Framework
- **FastAPI**: Python web framework for API development.
- **SQLAlchemy**: ORM for database interactions.
- **Pydantic**: For data validation.
- **AsyncIO**: For asynchronous operations.
- **Deployment Architecture**: Supports Autoscale (API-only) and Development/VM (full functionality with background scheduler) modes.
- **Redis**: Used for session caching.

### Machine Learning Pipeline
- **Models**: Production V1 (weighted consensus), V2 (LightGBM ensemble), and a unified V2 model integrating V3 Sharp Intelligence with 61 features.
- **Feature Engineering**: Automated pipeline generating features from various categories (Odds, Drift, ELO, Form, H2H, Advanced Stats, Context, Sharp Book, ECE, Timing, Historical Flags). V2.3 uses 46 leak-free features.
- **Leak Elimination**: Strict pre-match odds filtering and use of `match_context_v2` to prevent data contamination.
- **Training Data**: Comprises 648 clean matches (Oct-Nov 2025) with strictly pre-match odds; scalable with backfill.
- **Calibration & Constraints**: Includes random-label sanity checks and extensive testing.
- **Shadow Testing System**: Market-delta ridge regression for A/B testing and automated model promotion.
- **Auto-Retraining System**: Models retrain automatically based on new match volume (50+ new matches), staleness (14+ days), or accuracy drift (below 48%).
- **Match Context Builder**: Automated scheduler service populates `match_context_v2` every 5 minutes.
- **Market System**: Poisson-based approach for generating mathematically consistent markets.
- **Accuracy Tracking**: Automated backend monitoring for Brier score, LogLoss, and Hit-rate.
- **Live Betting Intelligence**: Momentum Engine (0-100 scoring) and Live Market Engine for in-play predictions.
- **Trending Scores System**: Pre-computes and caches `hot_score` and `trending_score` in Redis, updated every 5 minutes.
- **Parlay System**: AI-curated parlay recommendations with correlation-adjusted probability calculations, edge detection, and confidence tiers.

### Data Collection
- **Canonical Fixtures Table**: Single source of truth for match metadata.
- **Multi-Source Real-Time Odds**: Parallel collection from The Odds API and API-Football.
- **Fixture ID Resolver**: Advanced system for cross-source data linkage.
- **Historical Match Data**: Extensive dataset of 40,769 matches (1993-2025) with results, odds, and in-game statistics.
- **CLV Monitoring**: Advanced system for detecting pricing inefficiencies.
- **Multi-Sport Data**: NBA, NHL, MLB data collection for fixtures, odds, and training.
- **Sharp Book Data**: Collection of Pinnacle and other sharp bookmaker odds for V3 features.

### AI Analysis Layer
- **OpenAI GPT-4o Integration**: For comprehensive match analysis and contextual insights.

### Database Layer
- **PostgreSQL**: Primary database with optimized production indexes.
- **Schema Bridge Views**: For streamlined analysis.
- **Outcome Standardization**: Unified H/D/A outcome codes.
- **Timezone Architecture**: All timestamp columns are timezone-aware UTC.
- **Match Status Architecture**: Stores 'scheduled' and 'finished' statuses.
- **Team Logo System**: Dimension table with `logo_url` and API Football team ID mapping.
- **Trending Scores Table**: Stores `hot_score`, `trending_score`, and related metrics with dedicated indexes.
- **Parlay Tables**: `parlay_consensus`, `parlay_legs`, `parlay_performance` for tracking parlay data.
- **Sharp Book Odds Table**: `sharp_book_odds` for tracking sharp bookmaker data.
- **League Calibration Table**: `league_calibration` for tracking per-league Expected Calibration Error.
- **Historical Features Table**: Stores pre-computed H2H, form, and advanced stats from historical data.

### API Endpoints
- **Prediction API**: `/predict` (V1 consensus), `/predict-v2` (premium V2 SELECT), `/predict-v3` (premium V3), `/market` (market board).
- **Betting Intelligence API**: `/betting-intelligence/{match_id}` (per-match CLV, edge, Kelly sizing), `/betting-intelligence` (curated opportunities).
- **WebSocket Streaming**: `/ws/live/{match_id}` for real-time updates.
- **Trending API**: `/api/v1/trending/hot`, `/api/v1/trending/trending`, `/api/v1/trending/status`.
- **Parlay API**: `/api/v1/parlays`, `/api/v1/parlays/recommended`, `/api/v1/parlays/build`, `/api/v1/parlays/status`, `/api/v1/parlays/performance`.

### UI/UX Decisions
- Focuses on delivering a superior user experience through confidence-calibrated predictions and uncertainty quantification.

## External Dependencies

### Sports Data
- **RapidAPI Football API**: For real-time and historical football match information, including injuries.
- **The Odds API**: For aggregated odds data across various sports.
- **API-Sports**: For multi-sport data (NBA, NHL, MLB) and team information.

### AI Services
- **OpenAI API**: Specifically GPT-4o for contextual analysis and insights generation.

### Cache & Session
- **Redis**: Used for high-speed session caching and temporary data storage.

### Database
- **PostgreSQL**: The core relational database for persistent storage and complex queries.