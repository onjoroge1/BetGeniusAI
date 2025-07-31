# BetGenius AI - Sports Prediction Backend

## Overview
BetGenius AI is a sports prediction platform providing intelligent football match predictions using machine learning and AI analysis. It targets African markets (Kenya, Uganda, Nigeria, South Africa, Tanzania) while training models on European league data. The project aims to provide market-relative performance, superior user experience with confidence-calibrated predictions, and advanced risk management for sports betting. Key capabilities include comprehensive data collection, robust ML models, AI-powered contextual analysis, and strategic market-anchored intelligence.

## User Preferences
Preferred communication style: Simple, everyday language.

## System Architecture

### Backend Framework
- **FastAPI**: Modern Python web framework.
- **SQLAlchemy**: Database ORM for PostgreSQL.
- **Pydantic**: Data validation and serialization.
- **AsyncIO**: Asynchronous operations.

### Machine Learning Pipeline
- **Clean Ensemble Model**: Random Forest + Logistic Regression with pre-match features only (e.g., league_tier, competitiveness, regional_strength, home_advantage, expected_goals).
- **Rigorous Validation**: Stratified Cross-Validation with 30% holdout to prevent data leakage.
- **Market-Anchored Probability Calibration**: Per-league isotonic adjustment for odds-based predictions.
- **Residual-on-Market Model**: Random Forest combining market logits with structural features to improve upon market baselines.
- **Weighted Consensus**: Utilizes quality weights for bookmakers (e.g., Pinnacle, Bet365, Betway, William Hill) for robust market consensus.
- **Instance-Wise Book Mixing**: Softmax gating network for per-match bookmaker weighting based on contextual features.
- **Movement Features Framework**: Analyzes multi-timepoint odds movement (e.g., Opening→T-168→T-120→T-72) to capture market timing signals.

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
- **The Odds API**: Integrated for historical and real-time odds snapshots from multiple bookmakers.

### AI Services
- **OpenAI API**: Specifically GPT-4o for contextual analysis and explanations.

### Database
- **PostgreSQL**: Core relational database.