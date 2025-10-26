"""
Response schemas for /market endpoint
UI-ready format with odds, predictions, and premium locks
"""
from pydantic import BaseModel, Field
from typing import Dict, List, Optional
from datetime import datetime

class TeamInfo(BaseModel):
    """Team information with logo"""
    id: int
    name: str
    logo: Optional[str] = None

class LeagueInfo(BaseModel):
    """League information with flag"""
    id: int
    name: str
    flag: Optional[str] = None

class BookOdds(BaseModel):
    """Odds from a single bookmaker"""
    home: float
    draw: float
    away: float

class OddsData(BaseModel):
    """Comprehensive odds information"""
    books: Dict[str, BookOdds] = Field(..., description="Odds by bookmaker (Bet365, Unibet, Pinnacle)")
    novig_current: Dict[str, float] = Field(..., description="Current no-vig probabilities")
    novig_open: Optional[Dict[str, float]] = None
    novig_close: Optional[Dict[str, float]] = None

class ModelPredictions(BaseModel):
    """Model prediction probabilities"""
    v1_probs: Optional[Dict[str, float]] = Field(None, description="V1 consensus (if available)")
    v2_probs: Dict[str, float] = Field(..., description="V2 LightGBM probabilities")
    conf_v2: float = Field(..., description="V2 confidence (max probability)")
    delta: Optional[float] = Field(None, description="Disagreement between V2 and market")
    ev_live: Optional[float] = Field(None, description="Expected value vs current market")
    clv_run: Optional[float] = Field(None, description="Running CLV (current vs close)")

class PredictionInfo(BaseModel):
    """Prediction display information"""
    type: str = Field(..., description="'v2_select' or 'v2_full'")
    pick: str = Field(..., description="Predicted outcome: 'home', 'draw', or 'away'")
    confidence_pct: int = Field(..., description="Confidence percentage (0-100)")
    badge: Optional[str] = Field(None, description="UI badge: 'LIVE', 'PREMIUM', etc.")
    premium_lock: bool = Field(..., description="Whether this is a premium prediction")
    cta_url: Optional[str] = Field(None, description="Call-to-action URL for premium")

class LiveScore(BaseModel):
    """Live match score"""
    home: int
    away: int

class MarketMatch(BaseModel):
    """Single match in /market response"""
    match_id: str
    status: str = Field(..., description="'UPCOMING' or 'LIVE'")
    clock: Optional[str] = Field(None, description="Match clock (live only)")
    score: Optional[LiveScore] = Field(None, description="Current score (live only)")
    kickoff_at: str = Field(..., description="ISO 8601 kickoff time")
    league: LeagueInfo
    home: TeamInfo
    away: TeamInfo
    odds: OddsData
    model: ModelPredictions
    prediction: PredictionInfo

class MarketResponse(BaseModel):
    """Response for /market endpoint"""
    matches: List[MarketMatch]
    total_count: int
    filters_applied: Dict[str, any] = Field(default_factory=dict)
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())

class V2SelectConfig(BaseModel):
    """Configuration for V2 select logic"""
    min_confidence: float = 0.62  # Minimum confidence threshold
    min_ev: float = 0.0  # Minimum EV vs market
    max_league_ece: float = 0.08  # Maximum league calibration error
    free_preview_quota: int = 2  # Free previews per day
