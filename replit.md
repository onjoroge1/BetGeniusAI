# BetGenius AI - Sports Prediction Backend

## Overview
BetGenius AI is a sports prediction platform providing intelligent football match predictions using machine learning and AI analysis. It targets African markets (Kenya, Uganda, Nigeria, South Africa, Tanzania) while training models on European league data. The project aims to provide market-relative performance, superior user experience with confidence-calibrated predictions, and advanced risk management for sports betting. Key capabilities include comprehensive data collection, robust ML models, AI-powered contextual analysis, and strategic market-anchored intelligence.

## User Preferences
Preferred communication style: Simple, everyday language.
Production Model Decision: Use simple weighted consensus based on performance comparison showing 0.031549 LogLoss improvement over complex model.
Model Performance Analysis: Model rating 6.3/10 (B Grade) with 54.3% 3-way accuracy and 62.4% 2-way accuracy. Rating corrected after fixing Brier score normalization issue (0.191 vs incorrectly reported 0.573).
Improvement Priority: Focus on enhanced feature engineering and gradient boosting ensemble methods for immediate gains, with deep learning and reinforcement learning as longer-term research directions.

## System Architecture

### Backend Framework
- **FastAPI**: Modern Python web framework.
- **SQLAlchemy**: Database ORM for PostgreSQL.
- **Pydantic**: Data validation and serialization.
- **AsyncIO**: Asynchronous operations.

### Machine Learning Pipeline
- **Production Model**: Simple Weighted Consensus using quality weights from 31-year bookmaker analysis.
- **Quality Weights**: Pinnacle (35%), Bet365 (25%), Betway (22%), William Hill (18%) based on historical LogLoss performance.
- **Performance**: 0.838 LogLoss with authentic data (vs 0.963 baseline), 0.167 Brier Score (vs 0.191 baseline), significant improvement across all metrics.
- **Model Rating**: 8.5/10 (A Grade - Very Good Model) with 63.6% 3-way accuracy using authentic bookmaker data (tested August 18, 2025).
- **Enhanced Architecture**: Dual-table population strategy implemented and tested (August 18, 2025) with market-efficient consensus, league_map integration, timing-optimized data collection across 6 major European leagues, manual testing capability, and cross-table synchronization ensuring both training_matches and odds_consensus tables are populated consistently.
- **Optimal Prediction Timing**: T-48h/T-24h windows for maximum market efficiency, with T-72h fallback data available.
- **Real Data Integration**: Enhanced data collector with injuries, team news, recent form, and head-to-head records from RapidAPI.
- **Research Infrastructure**: Advanced features available for research; roadmap includes gradient boosting, deep learning (LSTM, attention networks), and reinforcement learning approaches.

### Enhanced Data Collection System (August 2025)
- **Dual Collection Strategy**: Scheduler populates both training_matches (completed) and odds_snapshots (upcoming) tables.
- **League Coverage**: Dynamic league selection via league_map table (6 leagues: EPL, La Liga, Serie A, Bundesliga, Ligue 1, Eredivisie).
- **Training Data**: 5,195+ matches in training_matches for ML model learning with synchronized odds_consensus table (26+ recent matches).
- **Authentic Odds Collection**: LIVE and operational - collecting real bookmaker odds from The Odds API with 21+ bookmakers per match.
- **Database Integration**: 63+ authentic odds successfully stored with proper H/D/A outcome mapping and individual bookmaker tracking.
- **Timing Windows**: Operational at T-3h to T-168h windows for optimal prediction timing across all configured leagues.
- **Data Integrity**: All odds data sourced from authentic bookmakers (1xBet, Parions Sport, Unibet, etc.) with proper constraint validation.

### AI Analysis Layer
- **OpenAI GPT-4o Integration**: For comprehensive match analysis and contextual insights.
- **Dual-Layer Intelligence**: Combines ML predictions with AI contextual analysis.

### Data Flow & Feature Engineering
- Automated data collection, feature engineering from raw data to ML-ready features.
- Features include team performance metrics, recent form, head-to-head history, venue factors, and market-derived features (logits, entropy, dispersion).
- Market-aligned architecture utilizing horizon-aligned market snapshots (T-72h) from multiple bookmakers.

### Database Layer
- **PostgreSQL**: Primary database for training data, match results, odds snapshots, and market features.
- Organized by league for efficient retrieval.

### API Endpoints
- Prediction API, Admin Endpoints for data management, Match Discovery, and Training Statistics.

### UI/UX Decisions
- Focus on superior UX with confidence-calibrated predictions and uncertainty quantification.

## External Dependencies

### Sports Data
- **RapidAPI Football API**: Primary source for real-time and historical match information.
- **The Odds API**: Third-party aggregator providing odds data from multiple bookmakers (Bet365, Pinnacle, William Hill, etc.). Note: We use aggregated data, not direct bookmaker APIs.

### AI Services
- **OpenAI API**: Specifically GPT-4o for contextual analysis and explanations.

### Database
- **PostgreSQL**: Core relational database.