# BetGenius AI - Sports Prediction Backend

## Overview
BetGenius AI is a sports prediction platform providing intelligent football match predictions using advanced machine learning and AI analysis. Its core purpose is to deliver market-relative performance, a superior user experience with confidence-calibrated predictions, and sophisticated risk management tools for sports betting in key African markets. The platform features comprehensive data collection, robust ML models, AI-powered contextual analysis, strategic market intelligence, and a full live betting intelligence stack with real-time momentum scoring and WebSocket streaming. Future ambitions include multi-sport expansion (NBA, NHL, MLB) and advanced sharp book intelligence, as well as AI-curated parlay recommendations with correlation adjustments and edge calculations.

## User Preferences
Preferred communication style: Simple, everyday language.
Production Model Decision: Use simple weighted consensus based on performance comparison showing 0.031549 LogLoss improvement over complex model.
Improvement Priority: Focus on enhanced feature engineering and gradient boosting ensemble methods for immediate gains, with deep learning and reinforcement learning as longer-term research directions.

## System Architecture

### Backend Framework
- **FastAPI**: Python web framework for API development.
- **SQLAlchemy**: ORM for database interactions.
- **Pydantic**: For data validation.
- **AsyncIO**: For asynchronous operations.
- **Deployment Architecture**: Supports Autoscale (API-only) and Development/VM (full functionality with background scheduler) modes.
- **Redis**: Used for session caching.

### Machine Learning Pipeline
- **Models**: Production V1 (weighted consensus), V2 (LightGBM ensemble), unified V2 with 61 features, V2-NBA (basketball), V2-NHL (hockey), **V3 Binary Expert Ensemble** (52.80% accuracy, 0.9788 LogLoss).
- **V3 Architecture (Jan 2026)**: Binary expert stacked ensemble with 3 calibrated binary classifiers (Home/Away/Draw) + stacked meta-model + 14 regime features. **Leak-free training** using out-of-fold predictions with time-based splits (50%/30%/20%).
  - Home Expert: Predicts H vs (D+A)
  - Away Expert: Predicts A vs (H+D)
  - Draw Expert: Predicts D vs (H+A) with class weighting
  - Stacked Meta-Model: Uses expert probabilities as features (57 total features)
  - **V3 Results: 52.80% accuracy, 0.9788 LogLoss** (+2.46% acc vs V2)
- **V3 Temporal Validation (Jan 2026)**: Strict temporal cutoff (train ≤ Jul 2024, test Aug 2024 → Nov 2025).
  - True out-of-sample: 4,021 matches completely untouched during training
  - **V3 Temporal: 52.60% accuracy, 0.9817 LogLoss** (matches Pinnacle probability quality)
  - Bootstrap P(V3 better than Pinnacle): 5.1% - CI includes zero
  - **Verdict: MATCHES PINNACLE** - recreates sharp-book quality with transparent model
- **Feature Engineering**: Automated pipeline generating features from various categories (Odds, Drift, ELO, Form, H2H, Advanced Stats, Context, Sharp Book, ECE, Timing, Historical Flags).
- **Regime Features (V3)**: League draw regime, goals regime, home stability, draw volatility, odds skewness, favorite dominance, draw compression, sharp signals.
- **Multi-Sport Models**: V2-Basketball (92.9% accuracy, 30 features) and V2-Hockey (75.0% accuracy, 30 features) for NBA/NHL predictions.
- **Leak Elimination**: Strict pre-match odds filtering + league stats computed from pre-2022 data only.
- **Auto-Retraining System**: Models retrain automatically based on new match volume, staleness, or accuracy drift.
- **Match Context Builder**: Automated scheduler service populates match context data.
- **Market System**: Poisson-based approach for generating mathematically consistent markets.
- **Live Betting Intelligence**: Momentum Engine and Live Market Engine for in-play predictions.
- **Trending Scores System**: Pre-computes and caches `hot_score` and `trending_score`.
- **Parlay System**: AI-curated parlay recommendations with correlation-adjusted probability calculations, edge detection, and confidence tiers. Uses V2 LightGBM model for match result predictions and Poisson-based totals predictor with market margin adjustments.
- **Quality Parlay Generator (V2 Jan 2026)**: High-quality parlay construction with proper constraints:
  - **Leg Quality Score (LQS)**: EV-based ranking with longshot/probability penalties
  - **Single outcome per match**: Only best EV outcome selected (no H/D/A contradictions)
  - **Probability-based confidence**: Trust (>=18% parlay prob), Value (12-18%)
  - **Exposure caps**: Max 2 parlays per match across feed
  - **Narrative-coherent SGPs**: Home+Over, Draw+Under templates only
  - **Parlay Types**: Trust (high-quality, 2 legs, ~20-30% win prob), Value (good quality, 12-18% prob), SGP (same-game, coherent templates)

### Data Collection
- **Canonical Fixtures Table**: Single source of truth for match metadata.
- **Fixture Seeding System**: Auto-discovers upcoming matches from API-Football using `seed_upcoming_fixtures()`. Runs every 4 hours plus emergency triggers when <10 upcoming fixtures detected. Excludes team_id columns (nullable) to avoid FK constraint violations.
- **Multi-Source Real-Time Odds**: Parallel collection from The Odds API and API-Football.
- **Fixture ID Resolver**: Advanced system for cross-source data linkage.
- **Historical Match Data**: Extensive dataset of matches with results, odds, and in-game statistics.
- **CLV Monitoring**: Advanced system for detecting pricing inefficiencies.
- **Multi-Sport Data**: NBA, NHL, NFL data collection for fixtures, odds, results, and training.
- **Multi-Sport Data Collector (Jan 2026)**: `models/multisport_data_collector.py` uses The Odds API /scores endpoint.
  - Collects match results for NBA, NHL, NFL every 2 hours via scheduler
  - Syncs completed games with odds to multisport_training table
  - Training data: NBA (76 samples), NHL (100 samples), Euroleague (14 samples) as of Jan 2026
  - New tables: `multisport_match_results`, `multisport_schedule`, `multisport_team_stats`, `multisport_injuries`
- **Sharp Book Data**: Collection of Pinnacle and other sharp bookmaker odds for V3 features.
- **International Match Collector**: World Cup and tournament data collection system for WC 2026 preparation.

### World Cup 2026 Preparation
- **International Leagues**: FIFA World Cup (ID 1), UEFA Euro (ID 4), AFCON (ID 6), Copa America (ID 9), WC Qualifiers (IDs 29-34).
- **Collected Data**: 3,791 international matches across all tournaments with 230 penalty shootouts tracked.
- **National Team Logos**: 150+ countries mapped with correct API-Football national team IDs covering CAF, UEFA, CONMEBOL, CONCACAF, AFC, and OFC confederations.
- **Tournament Coverage** (as of Dec 2025):
  - WC Qualifiers UEFA: 728 matches (latest: Nov 2025)
  - WC Qualifiers AFC: 681 matches (latest: Nov 2025)
  - WC Qualifiers CAF: 540 matches (latest: Nov 2025)
  - UEFA Euro: 477 matches (2008-2024)
  - Africa Cup of Nations: 366 matches (2015-2024)
  - WC Qualifiers CONCACAF: 330 matches (latest: Nov 2025)
  - WC Qualifiers CONMEBOL: 269 matches (latest: Sep 2025)
  - FIFA World Cup: 256 matches (2010-2022)
  - Copa America: 144 matches (2015-2024)
- **API Season Mapping**: UEFA uses "2024", others use "2026" for WC 2026 qualifiers.
- **New Tables**: `international_matches`, `national_team_squads`, `player_international_stats`, `national_team_elo`, `tournament_features`, `penalty_shootout_history`.
- **Tournament Stage Classification**: Automatic classification of group, r16, qf, sf, final stages.
- **Penalty Shootout Tracking**: Psychology features for knockout stage predictions.
- **Automated Collection**: Daily scheduler at 04:00 UTC collects new WC qualifier matches.
- **Logo Fix Script**: `scripts/fix_international_team_logos.py` with 180 API-verified country-to-team-ID mappings (Dec 2025). Fixed major mapping errors where countries like Tunisia showed wrong flags (was showing Kenya's flag due to ID confusion).

### AI Analysis Layer
- **OpenAI GPT-4o Integration**: For comprehensive match analysis and contextual insights.

### Multi-Sport Player Statistics
- **Unified Tables**: `players_unified`, `player_season_stats`, `player_game_stats` for all sports.
- **Stat Definitions**: 48 metrics across Soccer (14), NBA (18), NHL (16) with JSONB storage.
- **Extensible Design**: Add new sports via `sports` and `stat_definitions` tables without schema changes.
- **Collector Module**: `models/multisport_player_collector.py` handles Soccer, NBA, NHL player data.
- **Automated Collection**: Daily scheduler at 05:00 UTC collects player stats from ALL leagues in league_map (51 soccer leagues) plus NBA and NHL.
- **Game-by-Game Stats**: Per-match player stats via `/fixtures/players` endpoint with 20 metrics per game (goals, assists, shots, passes, tackles, etc.).

### Player Performance Prediction (V2-Player)
- **Feature Builder**: `features/player_v2_feature_builder.py` with ~45 features across 6 categories.
- **Feature Categories**: Form (10), Season (8), Opponent (8), Match (8), Profile (6), Market (5).
- **Training Script**: `training/train_player_v2.py` trains goal involvement (binary) and goals (regression) models.
- **Model Architecture**: LightGBM with TimeSeriesSplit CV, leak-safe implementation.
- **Target Metrics**: Goal involvement AUC 0.65-0.70, Goals RMSE < 0.8.
- **API Endpoints**: `/api/v1/predict-player/` (POST), `/api/v1/predict-player/top-picks` (GET), `/api/v1/predict-player/model-status` (GET).

### Database Layer
- **PostgreSQL**: Primary database with optimized production indexes.
- **Schema Bridge Views**: For streamlined analysis.
- **Outcome Standardization**: Unified H/D/A outcome codes.
- **Timezone Architecture**: All timestamp columns are timezone-aware UTC.
- **Team Logo System**: Dimension table with `logo_url` and API Football team ID mapping.
- **Trending Scores Table**: Stores `hot_score`, `trending_score`, and related metrics with dedicated indexes.
- **Parlay Tables**: `parlay_consensus`, `parlay_legs`, `parlay_performance` for tracking parlay data.
- **Sharp Book Odds Table**: `sharp_book_odds` for tracking sharp bookmaker data.
- **League Calibration Table**: `league_calibration` for tracking per-league Expected Calibration Error.
- **Historical Features Table**: Stores pre-computed H2H, form, and advanced stats from historical data.
- **International Match Tables**: 6 new tables for World Cup 2026 preparation (international_matches, national_team_squads, player_international_stats, national_team_elo, tournament_features, penalty_shootout_history).

### API Endpoints
- **Prediction API**: `/predict` (V1 consensus with model transparency - includes V1/V2 models array and final_decision), `/predict-v2` (premium V2 SELECT), `/predict-v3` (premium V3), `/market` (market board).
- **Betting Intelligence API**: `/betting-intelligence/{match_id}` (per-match CLV, edge, Kelly sizing), `/betting-intelligence` (curated opportunities).
- **WebSocket Streaming**: `/ws/live/{match_id}` for real-time updates.
- **Trending API**: `/api/v1/trending/hot`, `/api/v1/trending/trending`, `/api/v1/trending/status`.
- **Parlay API**: `/api/v1/parlays`, `/api/v1/parlays/recommended`, `/api/v1/parlays/build`, `/api/v1/parlays/status`, `/api/v1/parlays/performance`.
- **Player Stats API**: `/api/v1/players/top-scorers/{sport}`, `/api/v1/players/search/{sport}`, `/api/v1/players/stats/{sport}/{season}`, `/api/v1/players/summary`.

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