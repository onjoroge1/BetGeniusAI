"""
BetGenius AI Backend - Configuration Management
Handles environment variables and application settings
"""

import os
from pydantic_settings import BaseSettings
from typing import Dict, Any

class Settings(BaseSettings):
    """Application settings with environment variable support"""
    
    # API Keys
    RAPIDAPI_KEY: str = os.getenv("RAPIDAPI_KEY", "demo_key")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "demo_key") 
    BETGENIUS_API_KEY: str = os.getenv("BETGENIUS_API_KEY", "betgenius_secure_key_2024")
    
    # External API URLs
    RAPIDAPI_FOOTBALL_URL: str = "https://api-football-v1.p.rapidapi.com/v3"
    ODDS_API_URL: str = "https://api.the-odds-api.com/v4"
    
    # ML Model Settings
    MODEL_CONFIDENCE_THRESHOLD: float = 0.7
    ENSEMBLE_WEIGHTS: Dict[str, float] = {
        "team_performance": 0.35,
        "recent_form": 0.25,
        "head_to_head": 0.20,
        "home_advantage": 0.15,
        "context_factors": 0.05
    }
    
    # OpenAI Settings
    OPENAI_MODEL: str = "gpt-4o"  # Latest model as of May 13, 2024
    OPENAI_TEMPERATURE: float = 0.3
    OPENAI_MAX_TOKENS: int = 1000
    
    # Application Settings
    LOG_LEVEL: str = "INFO"
    CACHE_TTL: int = 300  # 5 minutes
    MAX_REQUESTS_PER_MINUTE: int = 60
    
    # Data Processing
    FEATURE_SCALING: bool = True
    OUTLIER_DETECTION: bool = True
    MIN_HISTORICAL_MATCHES: int = 5
    
    class Config:
        env_file = ".env"
        case_sensitive = True

# Global settings instance
settings = Settings()

# Validation functions
def validate_api_keys():
    """Validate that required API keys are present"""
    required_keys = ["RAPIDAPI_KEY", "OPENAI_API_KEY", "BETGENIUS_API_KEY"]
    missing_keys = []
    
    for key in required_keys:
        value = getattr(settings, key)
        if not value or value.startswith("demo_"):
            missing_keys.append(key)
    
    if missing_keys:
        print(f"Warning: Missing or demo API keys: {missing_keys}")
        print("Application will use fallback values but may have limited functionality")
    
    return len(missing_keys) == 0

def get_rapidapi_headers():
    """Get headers for RapidAPI requests"""
    return {
        "X-RapidAPI-Key": settings.RAPIDAPI_KEY,
        "X-RapidAPI-Host": "api-football-v1.p.rapidapi.com",
        "Content-Type": "application/json"
    }

def get_openai_config():
    """Get OpenAI configuration"""
    return {
        "api_key": settings.OPENAI_API_KEY,
        "model": settings.OPENAI_MODEL,
        "temperature": settings.OPENAI_TEMPERATURE,
        "max_tokens": settings.OPENAI_MAX_TOKENS
    }

# Initialize validation on import
validate_api_keys()
