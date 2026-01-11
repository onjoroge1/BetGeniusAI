"""
Automated Parlay API Routes
Endpoints for viewing pre-computed parlays, filtering by edge/legs, and performance tracking
"""

from fastapi import APIRouter, Query, HTTPException
from typing import Optional
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/auto-parlays", tags=["Automated Parlays"])

generator = None

def get_generator():
    global generator
    if generator is None:
        from models.automated_parlay_generator import AutomatedParlayGenerator
        generator = AutomatedParlayGenerator()
    return generator


@router.get("/best")
async def get_best_parlays(
    leg_count: Optional[int] = Query(None, description="Filter by number of legs (2, 3, 4, 5)"),
    confidence: Optional[str] = Query(None, description="Filter by confidence tier (high, medium, low)"),
    min_edge: float = Query(0, description="Minimum edge percentage"),
    limit: int = Query(20, le=50, description="Max parlays to return")
):
    """Get best pre-computed parlays sorted by edge"""
    try:
        gen = get_generator()
        parlays = gen.get_best_parlays(
            leg_count=leg_count,
            confidence=confidence,
            min_edge=min_edge,
            limit=limit
        )
        
        return {
            "count": len(parlays),
            "filters": {
                "leg_count": leg_count,
                "confidence": confidence,
                "min_edge": min_edge
            },
            "default_bet": 100.0,
            "parlays": parlays
        }
    except Exception as e:
        logger.error(f"Failed to get best parlays: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/by-legs/{leg_count}")
async def get_parlays_by_leg_count(
    leg_count: int,
    min_edge: float = Query(0, description="Minimum edge percentage"),
    limit: int = Query(20, le=50)
):
    """Get parlays filtered by leg count bucket"""
    if leg_count < 2 or leg_count > 10:
        raise HTTPException(status_code=400, detail="Leg count must be between 2 and 10")
    
    try:
        gen = get_generator()
        parlays = gen.get_best_parlays(leg_count=leg_count, min_edge=min_edge, limit=limit)
        
        return {
            "leg_count": leg_count,
            "count": len(parlays),
            "default_bet": 100.0,
            "parlays": parlays
        }
    except Exception as e:
        logger.error(f"Failed to get parlays by leg count: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/high-confidence")
async def get_high_confidence_parlays(
    min_edge: float = Query(5.0, description="Minimum edge percentage"),
    limit: int = Query(20, le=50)
):
    """Get high-confidence parlays with positive edge"""
    try:
        gen = get_generator()
        parlays = gen.get_best_parlays(confidence="high", min_edge=min_edge, limit=limit)
        
        return {
            "confidence": "high",
            "min_edge": min_edge,
            "count": len(parlays),
            "default_bet": 100.0,
            "parlays": parlays
        }
    except Exception as e:
        logger.error(f"Failed to get high confidence parlays: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/performance")
async def get_parlay_performance():
    """Get parlay performance statistics by leg count and confidence tier"""
    try:
        gen = get_generator()
        stats = gen.get_performance_stats()
        
        return {
            "description": "Parlay performance tracking (based on $100 bets)",
            "stats": stats
        }
    except Exception as e:
        logger.error(f"Failed to get performance stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/generate/{match_id}")
async def generate_parlays_for_match(match_id: int):
    """Manually trigger parlay generation for a specific match"""
    try:
        gen = get_generator()
        result = gen.generate_parlays_for_match(match_id)
        
        if 'error' in result:
            raise HTTPException(status_code=400, detail=result['error'])
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to generate parlays for match {match_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/generate-all")
async def generate_all_parlays(hours_ahead: int = Query(48, le=72)):
    """Manually trigger parlay generation for all upcoming matches"""
    try:
        gen = get_generator()
        result = gen.generate_all_upcoming_parlays(hours_ahead=hours_ahead)
        
        return result
    except Exception as e:
        logger.error(f"Failed to generate all parlays: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/settle")
async def settle_parlays():
    """Manually trigger parlay settlement for completed matches"""
    try:
        gen = get_generator()
        result = gen.settle_parlays()
        
        return {
            "message": "Parlay settlement complete",
            "results": result
        }
    except Exception as e:
        logger.error(f"Failed to settle parlays: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/calculator")
async def calculate_payout(
    odds: float = Query(..., description="Combined decimal odds"),
    stake: float = Query(100.0, description="Bet amount in dollars")
):
    """Calculate potential payout from odds and stake"""
    if odds <= 1:
        raise HTTPException(status_code=400, detail="Odds must be greater than 1")
    if stake <= 0:
        raise HTTPException(status_code=400, detail="Stake must be positive")
    
    payout = stake * odds
    profit = payout - stake
    implied_prob = 1 / odds * 100
    
    return {
        "stake": stake,
        "odds": odds,
        "potential_payout": round(payout, 2),
        "potential_profit": round(profit, 2),
        "implied_probability_pct": round(implied_prob, 2)
    }
