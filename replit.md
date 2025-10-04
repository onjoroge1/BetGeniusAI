# BetGenius AI - Sports Prediction Backend

## Overview
BetGenius AI is a sports prediction platform focused on delivering intelligent football match predictions through advanced machine learning and AI analysis. Targeting key African markets, the project aims to provide market-relative performance, a superior user experience with confidence-calibrated predictions, and sophisticated risk management tools for sports betting. Its core capabilities include comprehensive data collection, robust ML models, AI-powered contextual analysis, and strategic market intelligence.

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

### Machine Learning Pipeline
- **Production Model**: Simple Weighted Consensus using quality weights derived from 31-year bookmaker analysis (Pinnacle, Bet365, Betway, William Hill). Achieves 0.838 LogLoss and 0.167 Brier Score with 63.6% 3-way accuracy.
- **Enhanced Architecture**: Dual-table population with market-efficient consensus, timing-optimized data collection (T-48h/T-24h windows), and cross-table synchronization.
- **Real Data Integration**: Data collector incorporates injuries, team news, recent form, and head-to-head records.
- **Auto-Retraining System**: Models automatically retrain based on match volume, with manual training scripts available.
- **Comprehensive Market System**: Production-ready Poisson-based market expansion providing 50+ mathematically consistent markets derived from single λ parameters, with optimized performance and API schema validation.
- **Automated Accuracy Tracking**: Backend-driven monitoring system for predictions, automatically fetching results and computing metrics (Brier score, LogLoss, Hit-rate). Includes API suite for analysis and a unified SQL view (`odds_accuracy_evaluation`) for streamlined evaluation and CLV analysis.
- **Real Accuracy Testing**: Utilizes the `odds_accuracy_evaluation` view for true metric calculation and CLV when closing odds are available.

### Data Collection
- **Dual Collection Strategy**: Scheduler populates both training (`training_matches`) and upcoming (`odds_snapshots`) tables.
- **Multi-Source Real-Time Odds**: Parallel collection from The Odds API and API-Football for upcoming matches, ensuring consistency.
- **Fixture ID Resolver**: A robust 3-step system to resolve fixture IDs between different data sources, ensuring independent multi-source collection.
- **League Coverage**: Dynamic selection across 35 leagues, including major European, UEFA, English lower, Asian, South American, and Nordic/Alpine leagues.
- **Training Data**: Over 9,846 matches in `training_matches` for ML model learning, with synchronized `odds_consensus` table.
- **Authentic Odds Collection**: Live collection of real bookmaker odds from The Odds API (21+ bookmakers) stored with proper mapping and tracking.
- **CLV Monitoring (CLV Club Phase 1 & 2)**: Advanced system for detecting pricing inefficiencies, normalizing de-juiced odds, robust consensus calculation, line stability metrics, desk group deduplication, multi-tier gating, and real-time alerts. Includes closing line capture and realized CLV tracking with various sampling and settlement methods.
- **CLV Daily Brief**: Automated daily aggregation and reporting of CLV Club performance per league, tracking metrics and suppression reasons.

### AI Analysis Layer
- **OpenAI GPT-4o Integration**: Provides comprehensive match analysis and contextual insights, combining ML predictions with AI contextual analysis.

### Data Flow & Feature Engineering
- Automated processes for data collection and feature engineering, creating ML-ready features from raw data.
- Features include team performance, form, head-to-head, venue factors, and market-derived features (logits, entropy, dispersion).
- Market-aligned architecture utilizing horizon-aligned market snapshots from multiple bookmakers.

### Database Layer
- **PostgreSQL**: Primary database for all project data (training, match results, odds, market features).

### API Endpoints
- Prediction API, Admin Endpoints for data management, Match Discovery, and Training Statistics.

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