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
- **Models**: Production V1 (weighted consensus), V2 (LightGBM ensemble), unified V2 with 61 features, V2-NBA (basketball), V2-NHL (hockey).
- **Feature Engineering**: Automated pipeline generating features from various categories (Odds, Drift, ELO, Form, H2H, Advanced Stats, Context, Sharp Book, ECE, Timing, Historical Flags).
- **Multi-Sport Models**: V2-Basketball (92.9% accuracy, 30 features) and V2-Hockey (75.0% accuracy, 30 features) for NBA/NHL predictions.
- **Leak Elimination**: Strict pre-match odds filtering.
- **Auto-Retraining System**: Models retrain automatically based on new match volume, staleness, or accuracy drift.
- **Match Context Builder**: Automated scheduler service populates match context data.
- **Market System**: Poisson-based approach for generating mathematically consistent markets.
- **Live Betting Intelligence**: Momentum Engine and Live Market Engine for in-play predictions.
- **Trending Scores System**: Pre-computes and caches `hot_score` and `trending_score`.
- **Parlay System**: AI-curated parlay recommendations with correlation-adjusted probability calculations, edge detection, and confidence tiers.

### Data Collection
- **Canonical Fixtures Table**: Single source of truth for match metadata.
- **Multi-Source Real-Time Odds**: Parallel collection from The Odds API and API-Football.
- **Fixture ID Resolver**: Advanced system for cross-source data linkage.
- **Historical Match Data**: Extensive dataset of matches with results, odds, and in-game statistics.
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
- **Team Logo System**: Dimension table with `logo_url` and API Football team ID mapping.
- **Trending Scores Table**: Stores `hot_score`, `trending_score`, and related metrics with dedicated indexes.
- **Parlay Tables**: `parlay_consensus`, `parlay_legs`, `parlay_performance` for tracking parlay data.
- **Sharp Book Odds Table**: `sharp_book_odds` for tracking sharp bookmaker data.
- **League Calibration Table**: `league_calibration` for tracking per-league Expected Calibration Error.
- **Historical Features Table**: Stores pre-computed H2H, form, and advanced stats from historical data.

### API Endpoints
- **Prediction API**: `/predict` (V1 consensus with model transparency - includes V1/V2 models array and final_decision), `/predict-v2` (premium V2 SELECT), `/predict-v3` (premium V3), `/market` (market board).
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