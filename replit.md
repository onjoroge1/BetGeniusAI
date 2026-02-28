# BetGenius AI - Sports Prediction Backend

## Overview
BetGenius AI is a sports prediction platform that provides intelligent football match predictions using advanced machine learning and AI analysis. Its primary goal is to offer market-relative performance, a superior user experience with confidence-calibrated predictions, and sophisticated risk management tools for sports betting, particularly in key African markets. The platform includes comprehensive data collection, robust ML models, AI-powered contextual analysis, strategic market intelligence, and a full live betting intelligence stack. Future ambitions include expansion to multi-sports (NBA, NHL, MLB), advanced sharp book intelligence, and AI-curated parlay recommendations.

## User Preferences
Preferred communication style: Simple, everyday language.
Production Model Decision: Use simple weighted consensus based on performance comparison showing 0.031549 LogLoss improvement over complex model.
Improvement Priority: Focus on enhanced feature engineering and gradient boosting ensemble methods for immediate gains, with deep learning and reinforcement learning as longer-term research directions.

## System Architecture

### Backend Framework
The backend is built with FastAPI for API development, utilizing SQLAlchemy for ORM, Pydantic for data validation, and AsyncIO for asynchronous operations. The deployment supports both Autoscale (API-only) and Development/VM (full functionality with background scheduler) modes. Redis is used for session caching.

### Machine Learning Pipeline
The platform employs a multi-model approach for predictions, including:
- **V3 Binary Expert Ensemble**: The primary production model with 52.80% accuracy and 0.9788 LogLoss, using a stacked ensemble of calibrated binary classifiers and regime features. It features strict temporal validation, matching Pinnacle's probability quality.
- **V0 Form-Only Predictor**: An ELO-based fallback for matches without odds data, offering leak-free predictions using 11 features and daily ELO updates.
- **V1 Weighted Consensus**: A consensus model used in the prediction cascade.
- **Prediction Cascade**: Utilizes V3 Sharp → V1 Consensus → V0 Form → None for comprehensive match coverage.
- **Feature Engineering**: Automated pipeline generating features from categories like Odds, Drift, ELO, Form, H2H, and Sharp Book data.
- **Multi-Sport Models**: Dedicated LightGBM models for NBA and NHL predictions (V2-Basketball, V2-Hockey).
- **Auto-Retraining System**: Models automatically retrain based on new data volume, staleness, or accuracy drift.
- **Parlay System**: AI-curated parlay recommendations with correlation-adjusted probabilities, edge detection, and confidence tiers, utilizing the V2 LightGBM model and Poisson-based totals predictor. Features include Leg Quality Score, single outcome per match constraint, probability-based confidence, and exposure caps.
- **Player Performance Prediction (V2-Player)**: LightGBM models predict goal involvement and goals, using approximately 45 features across various categories (Form, Season, Opponent, Match, Profile, Market).

### Data Collection
A Canonical Fixtures Table serves as the single source of truth. Data collection includes:
- **Fixture Seeding System**: Auto-discovers upcoming matches from API-Football.
- **Multi-Source Real-Time Odds**: Parallel collection from The Odds API and API-Football.
- **Fixture ID Resolver**: Advanced system for cross-source data linkage.
- **Historical Match Data**: Extensive dataset including results, odds, and in-game statistics.
- **Multi-Sport Data Collector**: Gathers NBA, NHL, NFL data for fixtures, odds, and results.
- **Sharp Book Data**: Pinnacle and other sharp bookmaker odds for V3 features.
- **International Match Collector**: System for FIFA World Cup and other major international tournaments, including penalty shootout tracking and national team logo mapping.
- **Multi-Sport Player Statistics**: Unified tables (`players_unified`, `player_season_stats`, `player_game_stats`) with 48 metrics for Soccer, NBA, and NHL, collected daily.

### Database Layer
PostgreSQL is the primary database, featuring optimized production indexes and schema bridge views. Key aspects include:
- **Outcome Standardization**: Unified H/D/A outcome codes.
- **Timezone Architecture**: All timestamp columns are timezone-aware UTC.
- **Dedicated Tables**: For trending scores, parlay data, sharp book odds, league calibration, historical features, and international match data.
- **Unified Prediction Log**: Tracks all model predictions (V0, V1, V3) with model version, cascade level, probabilities, confidence, and actual results for accuracy tracking.

### API Endpoints
The system exposes several APIs:
- **Prediction API**: `/predict`, `/predict-v2`, `/predict-v3`, `/market` for various prediction models and market board access.
- **Betting Intelligence API**: `/betting-intelligence/{match_id}` for per-match CLV, edge, and Kelly sizing, and `/betting-intelligence` for curated opportunities.
- **WebSocket Streaming**: `/ws/live/{match_id}` for real-time updates.
- **Trending API**: `/api/v1/trending/hot`, `/api/v1/trending/trending`, `/api/v1/trending/status`.
- **Parlay API**: `/api/v1/parlays` and related endpoints for recommended parlays, building, status, and performance tracking.
- **Player Stats API**: `/api/v1/players/top-scorers/{sport}`, `/api/v1/players/search/{sport}`, `/api/v1/players/stats/{sport}/{season}`, `/api/v1/players/summary`.

### UI/UX Decisions
The platform prioritizes a superior user experience through confidence-calibrated predictions and uncertainty quantification.

## External Dependencies

### Sports Data
- **RapidAPI Football API**: For real-time and historical football match information and injuries.
- **The Odds API**: For aggregated odds data across various sports.
- **API-Sports**: For multi-sport data (NBA, NHL, MLB) and team information.

### AI Services
- **OpenAI API**: Utilizes GPT-4o for contextual analysis and insights generation.

### Cache & Session
- **Redis**: Used for high-speed session caching and temporary data storage.

### Database
- **PostgreSQL**: The core relational database for persistent storage.

## Recent Changes (2026-02-28)
- **Auto Parlay System Fixes**:
  - **Leg result tracking fixed**: `settle_parlays()` now writes `result='won'/'lost'` to each individual `parlay_precomputed_legs` row. Previously, all 340 settled leg results were NULL.
  - **Backfill completed**: `jobs/backfill_parlay_leg_results.py` populated result for all 340 historically settled legs.
  - **2-leg only enforcement**: `TARGET_LEG_COUNT=2` is now the only supported format. Edge filter widened slightly (MIN 3% → was 4%, MAX 25% → was 15%, MIN_PARLAY_PROB 0.10 → was 0.20) to sustain generation volume now that higher-quality leg combinations are the only option.
  - **Unit tests added**: `tests/test_auto_parlay_system.py` with 39 passing tests covering: leg result logic (`TestCheckLegResult`, 17 tests), parlay math (`TestBuildParlay`, 6 tests), generation flow (`TestGenerationFlow`, 6 tests), settlement + leg tracking (`TestSettlement`, 5 tests including regression test for the NULL-result bug), performance stats (`TestPerformanceStats`, 5 tests), and live integration smoke tests (`TestLiveIntegration`, 5 tests skipped in CI).

## Recent Changes (2026-02-23)
- **Soccer Scorer Odds System**: New odds-informed player betting system using real bookmaker odds from The Odds API.
  - `models/soccer_scorer_odds.py`: SoccerScorerOddsCollector collects anytime goalscorer odds for EPL, La Liga, Serie A, Bundesliga, Ligue 1, MLS. SoccerScorerEdgeDetector computes model prob vs implied prob edge and EV.
  - Player parlay generator now enriches legs with real bookmaker odds, filters out negative EV legs when market data exists, and boosts sampling weight for market-odds legs by 1.5x.
  - New API endpoints: `/api/v1/player-parlays/singles/best` (best single bets by EV), `/api/v1/player-parlays/singles/by-match/{match_id}` (per-match scorer analysis), `/api/v1/player-parlays/odds-coverage` (collection statistics).
  - Automated scheduler runs soccer scorer odds collection every 4 hours.
  - Database tables: `soccer_scorer_odds`, `player_name_aliases` for name matching cache.
  - Edge formula: `model_prob - implied_prob`, EV formula: `model_prob * (odds - 1) - (1 - model_prob)`.

## Changes (2026-02-22)
- **Market Endpoint Performance**: Lite mode now responds in ~1.1s for 50 matches (was ~28s). Full mode ~7.9s for 50 matches.
  - Removed per-match prediction logging from request path (50 individual DB connections eliminated).
  - Batch live_match_stats check replaces 50 per-match queries in full mode.
  - V2 LightGBM predictions disabled by default in market board (can be enabled via `include_v2=true`).
- **V0 Batch Predictions**: predict_batch() method reduces 5 sequential DB queries per match to 2 batch queries for all matches.
- **DB Connection Pooling**: pool_pre_ping, pool_size=3, max_overflow=2, pool_recycle=300 added to V0FormPredictor and TeamELOManager.

## Changes (2026-02-18)
- **Fixed DB Connection Starvation**: Root cause was `ALTER TABLE fixtures ADD COLUMN IF NOT EXISTS archived` running every 5 minutes via TBD Fixture Resolver, taking an ACCESS EXCLUSIVE lock on the fixtures table and blocking all reads. Fixed by checking column existence first (information_schema) and caching the result with a class-level flag.
- **Scheduler Staggering**: Split 10+ concurrent 60-second scheduler tasks into 3 groups (A: odds collection, B: CLV/settlement, C: resolver/live data) that alternate every loop iteration, preventing DB connection stampede.
- **V0 Predictor Pre-loading**: V0 Form Predictor now loads eagerly at startup instead of lazily on first request, preventing event loop blocking.
- **Connection Timeouts**: Added `connect_timeout=10` to all scheduler database connections for fail-fast behavior.