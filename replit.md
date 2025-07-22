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
- **Unified Ensemble Model**: Combines Random Forest and Logistic Regression
- **Conservative Parameters**: Prevents overfitting with 71.5% validated accuracy
- **Multi-Context Training**: Specialized models for different match scenarios
- **Cross-Validation**: Proper train/validation/test splits for reliable performance

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

The system has evolved through multiple phases to optimize accuracy and real-world performance:

### Phase 1A Enhancement (Complete)
- Enhanced all 1,893 matches with tactical intelligence features
- Added regional awareness and training weight optimization
- Implemented 9 distinct tactical styles with intensity factors
- Successfully integrated enhanced features: training_weight, tactical_style_encoding, regional_intensity

### Phase 1B Training Progress (Current)
- Validated Phase 1A enhancements with rigorous testing
- Conservative training approach prevents overfitting (65.1% realistic accuracy vs 99.4% overfitted)
- Core feature selection focuses on: tactical_style_encoding, regional_intensity, training_weight, competitiveness_indicator
- Production-ready model saved with ensemble weights optimized for stability

### Current Status
The system uses enhanced features from Phase 1A with conservative training parameters. While external data collection is limited due to API constraints, the enhanced feature engineering provides a solid foundation. The current approach prioritizes reliability and real-world performance over theoretical complexity, with ongoing work to expand the dataset strategically when APIs permit.