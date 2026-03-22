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

    # ── Prediction Confidence Thresholds ──
    V2_MIN_CONFIDENCE: float = 0.62
    CONFIDENCE_MEDIUM: float = 0.65
    CONFIDENCE_HIGH: float = 0.72
    EDGE_GATE_MIN: float = 0.03
    DIVERGENCE_THRESHOLD: float = 0.15

    # ── Time Windows (seconds) ──
    RECENT_MATCH_WINDOW_SEC: int = 14400       # 4 hours
    FRESH_STATS_WINDOW_SEC: int = 600          # 10 minutes
    VERY_FRESH_STATS_WINDOW_SEC: int = 300     # 5 minutes
    DASHBOARD_LOOKBACK_SEC: int = 86400        # 24 hours

    # ── Parlay Correlation Penalties ──
    PARLAY_CORR_SAME_LEAGUE: float = 0.10
    PARLAY_CORR_SAME_COUNTRY: float = 0.05
    PARLAY_CORR_SAME_TIME: float = 0.03
    PARLAY_CORR_FAVORITES: float = 0.05
    PARLAY_MAX_CORRELATION: float = 0.40
    PARLAY_EDGE_HIGH_MIN: float = 0.04
    PARLAY_EDGE_HIGH_MAX_CORR: float = 0.15
    PARLAY_EDGE_MEDIUM_MIN: float = 0.02
    PARLAY_EDGE_MEDIUM_MAX_CORR: float = 0.25
    PARLAY_EDGE_LOW_MIN: float = 0.01
    PARLAY_EDGE_LOW_MAX_CORR: float = 0.40
    PARLAY_FAVORITES_ODDS_THRESHOLD: float = 1.50
    PARLAY_LEG_MIN_PROB: float = 0.20
    PARLAY_LEG_MIN_EDGE: float = -0.05

    # ── Kelly Criterion ──
    KELLY_MAX_FRACTION: float = 0.05
    KELLY_MAX_LIVE: float = 0.03
    KELLY_RECOMMENDED_MAX_PCT: float = 3.0

    # ── Totals Predictor ──
    TOTALS_MAX_GOALS: int = 10
    CORRECT_SCORE_MAX: int = 5

    # ── Collection Delays (seconds) ──
    COLLECTION_DELAY_LONG: float = 2.0
    COLLECTION_DELAY_MEDIUM: float = 0.5
    COLLECTION_DELAY_SHORT: float = 0.3

    # ── Data Freshness Boundaries (seconds) ──
    FRESHNESS_FRESH_SEC: int = 600             # < 10 min = fresh
    FRESHNESS_STALE_SEC: int = 3600            # < 60 min = stale, else very_stale

    # ── Edge Classification Thresholds ──
    EDGE_STRONG: float = 0.10
    EDGE_MEDIUM: float = 0.05
    EDGE_LOW: float = 0.03

    # CLV Club Settings
    ENABLE_CLV_CLUB: bool = os.getenv("ENABLE_CLV_CLUB", "true").lower() == "true"
    CLV_MIN_BOOKS_DEFAULT: int = int(os.getenv("CLV_MIN_BOOKS_DEFAULT", "8"))
    CLV_MIN_BOOKS_MINOR: int = int(os.getenv("CLV_MIN_BOOKS_MINOR", "3"))  # Relaxed from 5 to 3 for testing
    CLV_MIN_STABILITY: float = float(os.getenv("CLV_MIN_STABILITY", "0.60"))  # Relaxed from 0.70 to 0.60
    CLV_MIN_CLV_PCT_BASIC: float = float(os.getenv("CLV_MIN_CLV_PCT_BASIC", "0.4"))  # Relaxed from 2.0% to 0.4% (40 bps)
    CLV_MIN_CLV_PCT_PRO: float = float(os.getenv("CLV_MIN_CLV_PCT_PRO", "0.6"))  # Relaxed from 3.0% to 0.6%
    CLV_STALENESS_SEC: int = int(os.getenv("CLV_STALENESS_SEC", "3600"))  # 60 minutes to match discrete collection windows
    CLV_TRIM_FRACTION: float = float(os.getenv("CLV_TRIM_FRACTION", "0.10"))
    CLV_CLOSING_METHOD: str = os.getenv("CLV_CLOSING_METHOD", "LAST5_VWAP")
    CLV_CLOSING_WINDOW_SEC: int = int(os.getenv("CLV_CLOSING_WINDOW_SEC", "300"))
    CLV_ALERT_TTL_SEC: int = int(os.getenv("CLV_ALERT_TTL_SEC", "900"))
    CLV_ALERT_TTL_NEAR_KO_SEC: int = int(os.getenv("CLV_ALERT_TTL_NEAR_KO_SEC", "300"))
    
    # CLV Phase 1 Hardening: Adaptive Staleness
    CLV_MIN_STALENESS_SEC: int = int(os.getenv("CLV_MIN_STALENESS_SEC", "600"))  # 10 min floor
    CLV_MAX_STALENESS_SEC: int = int(os.getenv("CLV_MAX_STALENESS_SEC", "7200"))  # 2 hour ceiling
    
    # CLV Phase 1 Hardening: TBD Filtering
    CLV_TBD_ALLOW_BEFORE_HOURS: int = int(os.getenv("CLV_TBD_ALLOW_BEFORE_HOURS", "36"))  # Allow TBD only >36h before KO
    
    # CLV Phase 1 Hardening: Alert Deduplication
    CLV_ALERT_COOLDOWN_MIN: int = int(os.getenv("CLV_ALERT_COOLDOWN_MIN", "20"))  # 20 min cooldown for duplicates
    
    # CLV Daily Brief Settings
    ENABLE_CLV_DAILY_BRIEF: bool = os.getenv("ENABLE_CLV_DAILY_BRIEF", "true").lower() == "true"
    CLV_DAILY_RETAIN_DAYS: int = int(os.getenv("CLV_DAILY_RETAIN_DAYS", "90"))
    CLV_DAILY_SCHEDULE_CRON: str = os.getenv("CLV_DAILY_SCHEDULE_CRON", "5 0 * * *")
    
    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    
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
