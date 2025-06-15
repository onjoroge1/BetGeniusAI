"""
Response Schemas for Comprehensive AI Analysis
Defines the exact JSON structure returned to frontend applications
"""
from pydantic import BaseModel, Field
from typing import Dict, List, Optional, Any
from datetime import datetime

class MLPrediction(BaseModel):
    """ML model prediction component"""
    home_win: float = Field(..., ge=0, le=1, description="Home team win probability")
    draw: float = Field(..., ge=0, le=1, description="Draw probability") 
    away_win: float = Field(..., ge=0, le=1, description="Away team win probability")
    confidence: float = Field(..., ge=0, le=1, description="ML model confidence")
    model_type: str = Field(default="unified_production", description="Type of ML model used")

class AIVerdict(BaseModel):
    """AI final verdict component"""
    recommended_outcome: str = Field(..., description="Home Win/Draw/Away Win")
    confidence_level: str = Field(..., description="High/Medium/Low")
    probability_assessment: Dict[str, float] = Field(..., description="AI-adjusted probabilities")

class DetailedReasoning(BaseModel):
    """Detailed reasoning breakdown"""
    ml_model_weight: str = Field(..., description="Percentage of decision based on ML")
    injury_impact: str = Field(..., description="How injuries affect the prediction")
    form_analysis: str = Field(..., description="Recent form impact on decision")
    tactical_factors: str = Field(..., description="Tactical matchup analysis")
    historical_context: str = Field(..., description="H2H and venue impact")

class BettingIntelligence(BaseModel):
    """Betting recommendations and value analysis"""
    primary_bet: str = Field(..., description="Main recommendation with reasoning")
    value_bets: List[str] = Field(default=[], description="Alternative betting opportunities")
    avoid_bets: List[str] = Field(default=[], description="Bets to avoid with reasons")
    market_analysis: Optional[Dict[str, Any]] = Field(default=None, description="Market odds analysis")

class RiskAnalysis(BaseModel):
    """Comprehensive risk assessment"""
    overall_risk: str = Field(..., description="High/Medium/Low")
    key_risks: List[str] = Field(default=[], description="Main factors that could affect outcome")
    upset_potential: str = Field(..., description="Likelihood of unexpected result")
    volatility_factors: Optional[List[str]] = Field(default=[], description="Factors adding uncertainty")

class AnalysisMetadata(BaseModel):
    """Analysis metadata and sourcing information"""
    analysis_type: str = Field(default="comprehensive_ml_plus_ai")
    data_sources: List[str] = Field(default=[])
    analysis_timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    ml_model_accuracy: str = Field(default="71.5%")
    ai_model: str = Field(default="gpt-4o")
    processing_time: Optional[float] = Field(default=None, description="Total processing time in seconds")

class ComprehensiveAnalysisResponse(BaseModel):
    """Main comprehensive analysis response structure"""
    ml_prediction: MLPrediction
    ai_verdict: AIVerdict
    detailed_reasoning: DetailedReasoning
    betting_intelligence: BettingIntelligence
    risk_analysis: RiskAnalysis
    confidence_breakdown: str = Field(..., description="Detailed confidence explanation")

class MatchContext(BaseModel):
    """Match context information"""
    match_id: int
    home_team: str
    away_team: str
    venue: str
    league: str
    date: str
    match_importance: Optional[str] = Field(default="regular_season")

class FinalPredictionResponse(BaseModel):
    """Complete response structure for frontend"""
    match_info: MatchContext
    comprehensive_analysis: ComprehensiveAnalysisResponse
    analysis_metadata: AnalysisMetadata
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }

# Additional market-specific responses
class AdditionalMarkets(BaseModel):
    """Additional betting markets"""
    total_goals: Dict[str, float] = Field(default={})
    both_teams_score: Dict[str, float] = Field(default={})
    asian_handicap: Dict[str, float] = Field(default={})
    correct_score_top3: Optional[List[Dict[str, Any]]] = Field(default=[])
    
class EnhancedPredictionResponse(BaseModel):
    """Enhanced response including additional markets"""
    match_info: MatchContext
    comprehensive_analysis: ComprehensiveAnalysisResponse
    additional_markets: Optional[AdditionalMarkets] = None
    analysis_metadata: AnalysisMetadata
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())

# Static JSON Templates for Frontend Integration
FRONTEND_RESPONSE_TEMPLATE = {
    "match_info": {
        "match_id": 867946,
        "home_team": "Arsenal",
        "away_team": "Manchester United", 
        "venue": "Emirates Stadium",
        "league": "Premier League",
        "date": "2024-12-15T15:00:00Z",
        "match_importance": "regular_season"
    },
    "comprehensive_analysis": {
        "ml_prediction": {
            "home_win": 0.652,
            "draw": 0.248, 
            "away_win": 0.100,
            "confidence": 0.847,
            "model_type": "unified_production"
        },
        "ai_verdict": {
            "recommended_outcome": "Home Win",
            "confidence_level": "High",
            "probability_assessment": {
                "home": 0.68,
                "draw": 0.22,
                "away": 0.10
            }
        },
        "detailed_reasoning": {
            "ml_model_weight": "60% - Strong statistical foundation",
            "injury_impact": "15% - Key away player injuries favor home team",
            "form_analysis": "15% - Arsenal's superior recent form",
            "tactical_factors": "5% - Home tactical setup advantage",
            "historical_context": "5% - Strong home record vs United"
        },
        "betting_intelligence": {
            "primary_bet": "Arsenal Win @ 1.65 - Strong value based on analysis",
            "value_bets": [
                "Arsenal -1 Handicap @ 2.10",
                "Over 2.5 Goals @ 1.85",
                "Both Teams Score Yes @ 1.75"
            ],
            "avoid_bets": [
                "Draw @ 3.50 - Low probability given team form",
                "United Win @ 5.00 - Injuries and away form make this risky"
            ],
            "market_analysis": {
                "best_value_market": "Asian Handicap",
                "overpriced_outcomes": ["Draw", "Away Win"],
                "underpriced_outcomes": ["Home Win", "Over Goals"]
            }
        },
        "risk_analysis": {
            "overall_risk": "Low",
            "key_risks": [
                "Arsenal complacency against struggling United",
                "United's potential counter-attacking threat",
                "Key player injury during match"
            ],
            "upset_potential": "Low - United's away form makes upset unlikely",
            "volatility_factors": [
                "Derby match unpredictability",
                "United's inconsistent performances"
            ]
        },
        "confidence_breakdown": "High confidence (85%) based on converging factors: ML model shows 84.7% confidence, injury reports favor Arsenal, recent form strongly supports home win, tactical matchup advantages clear, and historical data confirms pattern. Only minor risk from match volatility."
    },
    "additional_markets": {
        "total_goals": {
            "over_2_5": 0.734,
            "under_2_5": 0.266,
            "over_3_5": 0.445,
            "under_3_5": 0.555
        },
        "both_teams_score": {
            "yes": 0.678,
            "no": 0.322
        },
        "asian_handicap": {
            "home_handicap": 0.713,
            "away_handicap": 0.287
        },
        "correct_score_top3": [
            {"score": "2-1", "probability": 0.156},
            {"score": "2-0", "probability": 0.134},
            {"score": "3-1", "probability": 0.089}
        ]
    },
    "analysis_metadata": {
        "analysis_type": "comprehensive_ml_plus_ai",
        "data_sources": [
            "unified_ml_model",
            "injury_reports", 
            "team_news",
            "tactical_analysis",
            "historical_h2h",
            "recent_form_stats",
            "venue_factors"
        ],
        "analysis_timestamp": "2024-12-15T14:30:15.123456Z",
        "ml_model_accuracy": "71.5%",
        "ai_model": "gpt-4o",
        "processing_time": 8.245
    }
}

# Error Response Template
ERROR_RESPONSE_TEMPLATE = {
    "error": {
        "code": "ANALYSIS_FAILED",
        "message": "Comprehensive analysis could not be completed",
        "details": "Specific error details here",
        "fallback_available": True
    },
    "fallback_analysis": {
        "ml_prediction": "Basic ML prediction only",
        "confidence": "Reduced due to incomplete data",
        "recommendation": "Proceed with caution - limited analysis"
    },
    "analysis_metadata": {
        "analysis_type": "fallback_ml_only",
        "data_sources": ["ml_model_only"],
        "analysis_timestamp": "timestamp_here",
        "issues": ["injury_data_unavailable", "news_api_timeout"]
    }
}