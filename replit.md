# BetGenius AI - Sports Prediction Backend

## Overview
BetGenius AI is a sports prediction platform that provides intelligent football match predictions using advanced machine learning and AI analysis. Its primary goal is to offer market-relative performance, a superior user experience with confidence-calibrated predictions, and sophisticated risk management tools for sports betting, particularly in key African markets. The platform includes comprehensive data collection, robust ML models, AI-powered contextual analysis, strategic market intelligence, and a full live betting intelligence stack. Future ambitions include expansion to multi-sports (NBA, NHL, MLB), advanced sharp book intelligence, and AI-curated parlay recommendations.

## User Preferences
Preferred communication style: Simple, everyday language.
Production Model Decision: Use simple weighted consensus based on performance comparison showing 0.031549 LogLoss improvement over complex model.
Improvement Priority: Focus on enhanced feature engineering and gradient boosting ensemble methods for immediate gains, with deep learning and reinforcement learning as longer-term research directions.

## System Architecture

### Backend Framework
The backend is built with FastAPI, utilizing SQLAlchemy for ORM, Pydantic for data validation, and AsyncIO for asynchronous operations. Redis is used for session caching.

### Machine Learning Pipeline
The platform employs a multi-model approach for predictions, including:
- **V3 Binary Expert Ensemble**: The primary production model with high accuracy and low LogLoss, using a stacked ensemble of calibrated binary classifiers and regime features with strict temporal validation.
- **V0 Form-Only Predictor**: An ELO-based fallback for matches without odds data.
- **V1 Weighted Consensus**: A consensus model used in the prediction cascade.
- **Prediction Cascade**: Utilizes V3 Sharp → V1 Consensus → V0 Form → None for comprehensive match coverage.
- **Feature Engineering**: Automated pipeline generating features from categories like Odds, Drift, ELO, Form, H2H, and Sharp Book data.
- **Multi-Sport V3 Models**: Dedicated LightGBM models for NBA and NHL predictions.
- **Auto-Retraining System**: Models automatically retrain based on new data volume, staleness, or accuracy drift.
- **Parlay System**: AI-curated parlay recommendations with correlation-adjusted probabilities, edge detection, and confidence tiers, utilizing LightGBM and Poisson-based totals predictor.
- **Player Performance Prediction (V2-Player)**: LightGBM models predict goal involvement and goals based on various player and match features.

### Data Collection
A Canonical Fixtures Table serves as the single source of truth. Data collection includes:
- **Fixture Seeding System**: Auto-discovers upcoming matches.
- **Multi-Source Real-Time Odds**: Parallel collection from multiple providers.
- **Fixture ID Resolver**: Advanced system for cross-source data linkage.
- **Historical Match Data**: Extensive dataset including results, odds, and in-game statistics.
- **Multi-Sport Data Collector**: Gathers NBA, NHL, NFL, and NCAA Basketball (NCAAB) data. NCAAB added March 2026 — collects fixtures, odds (h2h/spreads/totals from 12 US bookmakers), and completed game results; backfill script at `scripts/backfill_ncaab.py`. A prediction model will be trained after a full season of data (November 2026+).
- **Sharp Book Data**: Pinnacle and other sharp bookmaker odds for V3 features.
- **International Match Collector**: System for major international tournaments.
- **Multi-Sport Player Statistics**: Unified tables with 48 metrics for Soccer, NBA, and NHL.

### Database Layer
PostgreSQL is the primary database, featuring optimized production indexes and schema bridge views. Key aspects include outcome standardization, timezone-aware UTC timestamps, and dedicated tables for various data types, including a unified prediction log.

### API Endpoints
The system exposes several APIs:
- **Prediction API**: `/predict`, `/predict-v2`, `/predict-v3`, `/market` for various prediction models.
- **Multisport Prediction API**: `POST /predict-multisport` (NBA/NHL full prediction with markets, context, AI analysis), `GET /predict-multisport/available?sport=` (list predictable fixtures).
- **Betting Intelligence API**: `/betting-intelligence/{match_id}` for per-match CLV, edge, and Kelly sizing, and `/betting-intelligence` for curated opportunities.
- **WebSocket Streaming**: `/ws/live/{match_id}` for real-time updates.
- **Trending API**: `/api/v1/trending/hot`, `/api/v1/trending/trending`, `/api/v1/trending/status`.
- **Parlay API**: `/api/v1/parlays` and related endpoints for recommended parlays.
- **Player Stats API**: `/api/v1/players/top-scorers/{sport}`, `/api/v1/players/search/{sport}`, `/api/v1/players/stats/{sport}/{season}`, `/api/v1/players/summary`.

### UI/UX Decisions
The platform prioritizes a superior user experience through confidence-calibrated predictions and uncertainty quantification.

## External Dependencies

### Sports Data
- **RapidAPI Football API**: For real-time and historical football match information.
- **The Odds API**: For aggregated odds data across various sports.
- **API-Sports**: For multi-sport data and team information.

### AI Services
- **OpenAI API**: Utilizes GPT-4o for contextual analysis and insights generation.

### Cache & Session
- **Redis**: Used for high-speed session caching and temporary data storage.

### Database
- **PostgreSQL**: The core relational database for persistent storage.