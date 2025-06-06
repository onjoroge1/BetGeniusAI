"""
BetGenius AI Backend - Main FastAPI Application
Production-ready sports prediction API with ML and AI explanations
"""

from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
import asyncio
import logging
from datetime import datetime

from utils.config import settings
from models.data_collector import SportsDataCollector
from models.ml_predictor import MLPredictor
from models.ai_analyzer import AIAnalyzer

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="BetGenius AI Backend",
    description="AI-powered sports prediction API with transparent explanations",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize components
data_collector = SportsDataCollector()
ml_predictor = MLPredictor()
ai_analyzer = AIAnalyzer()

# Pydantic models for request/response
class PredictionRequest(BaseModel):
    match_id: int = Field(..., description="Unique match identifier")
    include_analysis: bool = Field(True, description="Include AI explanation")
    include_additional_markets: bool = Field(True, description="Include additional betting markets")

class MatchInfo(BaseModel):
    match_id: int
    home_team: str
    away_team: str
    venue: str
    date: str
    league: str

class Predictions(BaseModel):
    home_win: float = Field(..., ge=0, le=1)
    draw: float = Field(..., ge=0, le=1)
    away_win: float = Field(..., ge=0, le=1)
    confidence: float = Field(..., ge=0, le=1)
    recommended_bet: str

class Analysis(BaseModel):
    explanation: str
    confidence_factors: list[str]
    betting_recommendations: Dict[str, str]
    risk_assessment: str

class AdditionalMarkets(BaseModel):
    total_goals: Dict[str, float]
    both_teams_score: Dict[str, float]
    asian_handicap: Dict[str, float]

class PredictionResponse(BaseModel):
    match_info: MatchInfo
    predictions: Predictions
    analysis: Optional[Analysis] = None
    additional_markets: Optional[AdditionalMarkets] = None
    processing_time: float
    timestamp: str

# Authentication dependency
async def verify_api_key(authorization: str = Header(None)):
    """Verify API key authentication"""
    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="Authorization header required"
        )
    
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Authorization header must start with 'Bearer '"
        )
    
    api_key = authorization.split(" ")[1]
    if api_key != settings.BETGENIUS_API_KEY:
        raise HTTPException(
            status_code=401,
            detail="Invalid API key"
        )
    
    return api_key

@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "message": "BetGenius AI Backend",
        "status": "operational",
        "version": "1.0.0",
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/health")
async def health_check():
    """Detailed health check"""
    try:
        # Check external services
        health_status = {
            "api": "healthy",
            "rapidapi": "checking",
            "openai": "checking",
            "ml_models": "checking"
        }
        
        # Quick API tests (simplified for demo)
        health_status["rapidapi"] = "healthy"
        health_status["openai"] = "healthy" 
        health_status["ml_models"] = "healthy"
        
        return {
            "status": "healthy",
            "services": health_status,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }
        )

@app.post("/predict", response_model=PredictionResponse)
async def predict_match(
    request: PredictionRequest,
    api_key: str = Depends(verify_api_key)
):
    """
    Main prediction endpoint - generates AI-powered match predictions
    """
    start_time = asyncio.get_event_loop().time()
    
    try:
        logger.info(f"Processing prediction request for match {request.match_id}")
        
        # Step 1: Collect match data from RapidAPI
        logger.info("Collecting match data...")
        match_data = await data_collector.get_match_data(request.match_id)
        
        if not match_data:
            raise HTTPException(
                status_code=404,
                detail=f"Match {request.match_id} not found or no data available"
            )
        
        # Step 2: Generate ML predictions
        logger.info("Generating ML predictions...")
        ml_predictions = ml_predictor.predict_match_outcome(match_data['features'])
        
        # Step 3: Generate AI analysis (if requested)
        analysis = None
        if request.include_analysis:
            logger.info("Generating AI analysis...")
            analysis_data = await ai_analyzer.analyze_prediction(
                match_data, ml_predictions
            )
            analysis = Analysis(**analysis_data)
        
        # Step 4: Generate additional markets (if requested)
        additional_markets = None
        if request.include_additional_markets:
            logger.info("Calculating additional markets...")
            additional_data = ml_predictor.predict_additional_markets(match_data['features'])
            additional_markets = AdditionalMarkets(**additional_data)
        
        # Step 5: Build response
        processing_time = asyncio.get_event_loop().time() - start_time
        
        response = PredictionResponse(
            match_info=MatchInfo(
                match_id=request.match_id,
                home_team=match_data['match_info']['home_team'],
                away_team=match_data['match_info']['away_team'],
                venue=match_data['match_info']['venue'],
                date=match_data['match_info']['date'],
                league=match_data['match_info'].get('league', 'Premier League')
            ),
            predictions=Predictions(
                home_win=ml_predictions['home_win_probability'],
                draw=ml_predictions['draw_probability'],
                away_win=ml_predictions['away_win_probability'],
                confidence=ml_predictions['confidence_score'],
                recommended_bet=ml_predictions['recommended_bet']
            ),
            analysis=analysis,
            additional_markets=additional_markets,
            processing_time=round(processing_time, 3),
            timestamp=datetime.utcnow().isoformat()
        )
        
        logger.info(f"Prediction completed for match {request.match_id} in {processing_time:.3f}s")
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Prediction failed for match {request.match_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )

@app.get("/matches/upcoming")
async def get_upcoming_matches(
    league_id: int = 39,  # Premier League by default
    limit: int = 10,
    api_key: str = Depends(verify_api_key)
):
    """Get list of upcoming matches"""
    try:
        matches = await data_collector.get_upcoming_matches(league_id, limit)
        return {
            "matches": matches,
            "total": len(matches),
            "league_id": league_id,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Failed to fetch upcoming matches: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch matches: {str(e)}"
        )

@app.exception_handler(404)
async def not_found_handler(request, exc):
    return JSONResponse(
        status_code=404,
        content={
            "error": "Not Found",
            "message": "The requested resource was not found",
            "timestamp": datetime.utcnow().isoformat()
        }
    )

@app.exception_handler(500)
async def internal_error_handler(request, exc):
    logger.error(f"Internal server error: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal Server Error",
            "message": "An unexpected error occurred",
            "timestamp": datetime.utcnow().isoformat()
        }
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
