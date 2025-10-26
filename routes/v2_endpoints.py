"""
V2 API Endpoints
/predict-v2: V2 SELECT predictions with OpenAI analysis
/market: Real-time odds board with both V1 + V2 predictions
"""
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from typing import Optional, List, Dict
from datetime import datetime
import logging

from models.v2_lgbm_predictor import get_v2_lgbm_predictor
from models.v2_allocator import get_allocator
from models.market_schemas import MarketResponse, MarketMatch
from models.response_schemas import PredictionRequest

logger = logging.getLogger(__name__)

router = APIRouter()

# ============================================================================
# /predict-v2: V2 SELECT Endpoint (Premium)
# ============================================================================

@router.post("/predict-v2")
async def predict_v2_select(request: PredictionRequest):
    """
    V2 SELECT prediction endpoint (Premium)
    
    Only works for matches that qualify for V2 SELECT:
    - conf_v2 >= 0.62
    - ev_live > 0  
    - league_ece <= 0.05
    
    Returns 403 if match doesn't qualify
    """
    from main import (
        get_enhanced_data_collector,
        get_consensus_prediction_from_db,
        build_on_demand_consensus,
        get_enhanced_ai_analyzer,
        normalize_hda
    )
    
    start_time = datetime.now()
    
    try:
        logger.info(f"🎯 V2 SELECT REQUEST | match_id={request.match_id}")
        
        # Step 1: Get match data (same as /predict)
        match_data = get_enhanced_data_collector().collect_comprehensive_match_data(request.match_id)
        
        if not match_data:
            raise HTTPException(404, f"Match {request.match_id} not found")
        
        # Step 2: Get market consensus (for EV calculation)
        market_consensus = await get_consensus_prediction_from_db(request.match_id)
        if not market_consensus:
            market_consensus = await build_on_demand_consensus(request.match_id)
        
        if not market_consensus or market_consensus.get('confidence', 0) == 0:
            raise HTTPException(422, "No market data available for this match")
        
        market_probs = {
            'home': market_consensus.get('probabilities', {}).get('home', 0.33),
            'draw': market_consensus.get('probabilities', {}).get('draw', 0.33),
            'away': market_consensus.get('probabilities', {}).get('away', 0.33)
        }
        
        # Step 3: Generate V2 prediction
        logger.info("Generating V2 LightGBM prediction...")
        v2_predictor = get_v2_lgbm_predictor()
        v2_result = v2_predictor.predict(market_probs)
        
        if not v2_result:
            raise HTTPException(500, "V2 prediction failed")
        
        # Step 4: Check V2 SELECT eligibility
        allocator = get_allocator()
        league_name = match_data['match_details']['league']['name']
        
        model_type, premium_lock, metadata = allocator.allocate_model(
            v2_probs=v2_result['probabilities'],
            market_probs=market_probs,
            league_name=league_name,
            user_is_premium=True  # Assume premium if calling this endpoint
        )
        
        if model_type != 'v2_select':
            # Not eligible for V2 SELECT
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "Not eligible for V2 Select",
                    "reason": "Match doesn't meet high-confidence criteria",
                    "conf_v2": metadata['conf_v2'],
                    "ev_live": metadata.get('ev_live', 0),
                    "threshold": {"min_conf": 0.62, "min_ev": 0.0},
                    "suggestion": "Try /predict for standard predictions or check /market"
                }
            )
        
        logger.info(f"✅ V2 SELECT QUALIFIED: conf={metadata['conf_v2']:.3f}, ev={metadata.get('ev_live', 0):+.3f}")
        
        # Step 5: Enhanced AI analysis (same as /predict)
        ai_analysis = None
        if request.include_analysis:
            logger.info("Generating AI analysis for V2 prediction...")
            try:
                analyzer = get_enhanced_ai_analyzer()
                ai_result = analyzer.analyze_match_comprehensive(match_data, v2_result)
                
                if 'error' not in ai_result:
                    ai_analysis = {
                        "explanation": ai_result.get('final_verdict', ''),
                        "confidence_factors": ai_result.get('key_factors', []),
                        "betting_recommendations": ai_result.get('betting_recommendations', {}),
                        "risk_assessment": ai_result.get('betting_recommendations', {}).get('risk_level', 'Medium'),
                        "team_analysis": ai_result.get('team_analysis', {}),
                        "ai_summary": analyzer.generate_match_summary(ai_result, v2_result)
                    }
            except Exception as e:
                logger.error(f"AI analysis error: {e}")
                ai_analysis = None
        
        # Step 6: Build response (same format as /predict)
        processing_time = (datetime.now() - start_time).total_seconds()
        
        probs = v2_result.get('probabilities', {})
        h_norm, d_norm, a_norm = normalize_hda(
            probs.get('home', 0.0),
            probs.get('draw', 0.0),
            probs.get('away', 0.0)
        )
        
        predictions = {
            "home_win": round(h_norm, 3),
            "draw": round(d_norm, 3),
            "away_win": round(a_norm, 3),
            "confidence": v2_result.get('confidence', 0),
            "recommended_bet": v2_result.get('prediction', 'No Prediction'),
            "ev_live": metadata.get('ev_live', 0)
        }
        
        response = {
            "match_info": {
                "match_id": request.match_id,
                "home_team": match_data['match_details']['teams']['home']['name'],
                "away_team": match_data['match_details']['teams']['away']['name'],
                "venue": match_data['match_details']['fixture']['venue']['name'],
                "date": match_data['match_details']['fixture']['date'],
                "league": league_name
            },
            "predictions": predictions,
            "model_info": {
                "type": "v2_lightgbm_select",
                "version": "1.0.0",
                "performance": "75.9% hit rate @ 17.3% coverage",
                "confidence_threshold": 0.62,
                "ev_threshold": 0.0
            },
            "comprehensive_analysis": ai_analysis if ai_analysis else {},
            "processing_time": round(processing_time, 3),
            "timestamp": datetime.now().isoformat()
        }
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"V2 SELECT prediction error: {e}", exc_info=True)
        raise HTTPException(500, f"Prediction failed: {str(e)}")


# ============================================================================
# /market: Odds Board with V1 + V2 (Free Tier)
# ============================================================================

@router.get("/market")
async def get_market_data(
    status: str = Query("upcoming", regex="^(upcoming|live)$"),
    league: Optional[int] = None,
    limit: int = Query(100, ge=1, le=500)
):
    """
    Market endpoint: Real-time odds board with both V1 + V2 predictions
    
    Shows:
    - Latest odds from multiple bookmakers
    - V1 consensus (market baseline)
    - V2 LightGBM (ML model)
    - Premium badge when V2 SELECT qualifies
    
    Free tier gets both models, premium gets AI analysis via /predict-v2
    """
    from main import get_consensus_prediction_from_db, build_on_demand_consensus
    import psycopg2
    import os
    
    try:
        # TODO: Implement full /market endpoint
        # For now, return a basic structure
        
        logger.info(f"📊 MARKET REQUEST | status={status}, league={league}, limit={limit}")
        
        # Placeholder response
        return {
            "matches": [],
            "total_count": 0,
            "status": "coming_soon",
            "message": "Market endpoint under construction. Use /predict for now.",
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Market endpoint error: {e}", exc_info=True)
        raise HTTPException(500, f"Market data unavailable: {str(e)}")
