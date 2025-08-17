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
- **Performance**: 0.963475 LogLoss, outperforming complex models by 0.031549 LogLoss.
- **Model Rating**: 6.3/10 (B Grade - Good Model) with 54.3% 3-way accuracy and 62.4% 2-way accuracy.
- **Enhanced Architecture**: Dual-table population strategy implemented (August 17, 2025) with market-efficient consensus and timing-optimized data collection.
- **Optimal Prediction Timing**: T-48h/T-24h windows for maximum market efficiency, with T-72h fallback data available.
- **Real Data Integration**: Enhanced data collector with injuries, team news, recent form, and head-to-head records from RapidAPI.
- **Research Infrastructure**: Advanced features available for research; roadmap includes gradient boosting, deep learning (LSTM, attention networks), and reinforcement learning approaches.

### Enhanced Data Collection System (August 2025)
- **Dual Collection Strategy**: Scheduler populates both training_matches (completed) and odds_snapshots (upcoming) tables.
- **Training Data**: 5,151 matches in training_matches for ML model learning.
- **Odds Snapshots**: Framework ready for T-48h/T-24h collection at optimal timing windows.
- **Fallback Architecture**: odds_snapshots → odds_consensus (1,000 T-72h records) → consensus_predictions chain.

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