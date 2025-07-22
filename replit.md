# BetGenius AI - Sports Prediction Backend

## Overview

BetGenius AI is a comprehensive sports prediction platform that combines machine learning models with AI-powered analysis to provide intelligent football match predictions. The system focuses on African markets (Kenya, Uganda, Nigeria, South Africa, Tanzania) while leveraging European league data for training robust models.

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### Backend Framework
- **FastAPI**: Modern Python web framework for API development
- **SQLAlchemy**: Database ORM for PostgreSQL integration
- **Pydantic**: Data validation and serialization
- **AsyncIO**: Asynchronous operations for improved performance

### Machine Learning Pipeline
- **Clean Ensemble Model**: Random Forest + Logistic Regression with legitimate features only
- **Data Leakage Prevention**: No match outcome features used in training
- **Pre-Match Features Only**: league_tier, competitiveness, regional_strength, home_advantage, expected_goals
- **Rigorous Validation**: Stratified CV with 30% holdout test set (27.3% honest accuracy)

### AI Analysis Layer
- **OpenAI GPT-4o Integration**: Comprehensive match analysis
- **Dual-Layer Intelligence**: ML predictions + AI contextual analysis
- **Real-Time Context**: Live injury reports, team news, tactical insights

## Key Components

### Data Collection System
- **RapidAPI Football Integration**: Real-time sports data collection
- **Multi-League Coverage**: Premier League, La Liga, Bundesliga, Serie A, Ligue 1
- **Training Data Collector**: Automated collection of historical match data
- **African League Collector**: Specialized collection for target markets

### Machine Learning Models
- **Unified Model**: Single robust ensemble model (current production approach)
- **Multi-Context Models**: Specialized models for home-dominant, competitive, and away-strong scenarios
- **Feature Engineering**: 10 optimized features from real sports data
- **Overfitting Prevention**: Proper validation strategies and conservative parameters

### Database Layer
- **PostgreSQL**: Primary database for storing training data and match results
- **Training Matches Table**: Stores processed match data with features and outcomes
- **Automated Collection History**: Tracks data collection activities
- **League-Specific Storage**: Organized by league for efficient retrieval

### API Endpoints
- **Prediction API**: Core prediction endpoints with authentication
- **Admin Endpoints**: Training data management and model retraining
- **Match Discovery**: Search and filter upcoming matches
- **Training Statistics**: Monitor model performance and data quality

## Data Flow

1. **Data Collection**: Automated collection from RapidAPI Football API
2. **Feature Engineering**: Transform raw match data into ML-ready features
3. **Model Training**: Train ensemble models with cross-validation
4. **Prediction Generation**: Process match requests through ML pipeline
5. **AI Enhancement**: Enrich predictions with contextual analysis
6. **Response Delivery**: Return comprehensive prediction with explanations

### Feature Engineering Pipeline
- **Team Performance Metrics**: Win percentages, goals per game
- **Recent Form Analysis**: Points from last 5 matches
- **Head-to-Head History**: Historical matchup performance
- **Venue Factors**: Home/away performance differentials
- **League Context**: Competitiveness and market-specific factors

## External Dependencies

### Sports Data
- **RapidAPI Football API**: Primary data source for match information
- **Authentication**: API key-based authentication system
- **Rate Limiting**: Implemented to respect API limits
- **Data Validation**: Comprehensive validation of incoming data

### AI Services
- **OpenAI API**: GPT-4o for contextual analysis and explanations
- **Async Processing**: Non-blocking AI analysis requests
- **Error Handling**: Graceful degradation when AI services unavailable

### Database
- **PostgreSQL**: Production database with proper indexing
- **Connection Pooling**: Efficient database connection management
- **Migration Support**: Database schema versioning

## Deployment Strategy

### Production Environment
- **Replit Deployment**: Configured for Replit hosting platform
- **Environment Variables**: Secure configuration management
- **CORS Configuration**: Properly configured for frontend integration
- **Logging**: Comprehensive logging for monitoring and debugging

### Scalability Considerations
- **Async Architecture**: Non-blocking operations for better throughput
- **Database Optimization**: Efficient queries and proper indexing
- **Model Caching**: Pre-trained models loaded at startup
- **API Rate Limiting**: Protection against abuse

### Monitoring and Maintenance
- **Training Statistics**: Monitor model performance over time
- **Collection History**: Track data collection activities
- **Error Logging**: Comprehensive error tracking and reporting
- **Health Checks**: API health monitoring endpoints

### Security
- **API Key Authentication**: Secure endpoint access
- **Input Validation**: Comprehensive request validation
- **SQL Injection Prevention**: Parameterized queries
- **Environment Security**: Secure handling of sensitive configuration

## Development Notes

The system has undergone critical validation revealing fundamental issues with data leakage:

### Data Leakage Discovery (Critical)
- Previous 65%-100% accuracies were due to data leakage using match outcome features
- Features like home_goals, away_goals, and goal_difference predict outcomes perfectly but are useless for real prediction
- Phase 1A enhanced features (23 tactical features) added complexity without genuine predictive value
- Clean validation with only pre-match features shows 27.3% accuracy (near random 33.3%)

### Clean Model Implementation (Current)
- Built legitimate prediction model using only pre-match available features
- Features: league_tier, league_competitiveness, regional_strength, home_advantage_factor, expected_goals_avg, match_importance
- Rigorous validation prevents overfitting: CV ≈ Test accuracy
- Production model saved with no data leakage: models/clean_production_model.joblib

### Current Status (Honest Assessment)
The system now has a clean foundation with 27.3% accuracy using legitimate pre-match features. This represents the true baseline without data leakage. While below the 74% target, it provides an honest starting point for improvement through additional pre-match features and Phase 1B data expansion. The focus has shifted from complex feature engineering to building genuine predictive capability.