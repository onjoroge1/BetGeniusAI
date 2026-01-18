"""
Automated Parlay API Routes
Endpoints for viewing pre-computed parlays, filtering by edge/legs, and performance tracking
Now uses QualityParlayGenerator (V2) for improved parlay construction
"""

from fastapi import APIRouter, Query, HTTPException
from typing import Optional
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/auto-parlays", tags=["Automated Parlays"])

generator = None
quality_generator = None

def get_generator():
    global generator
    if generator is None:
        from models.automated_parlay_generator import AutomatedParlayGenerator
        generator = AutomatedParlayGenerator()
    return generator

def get_quality_generator():
    global quality_generator
    if quality_generator is None:
        from models.quality_parlay_generator import QualityParlayGenerator
        quality_generator = QualityParlayGenerator()
    return quality_generator


def _format_quality_parlays_for_frontend(raw_parlays: list) -> list:
    """Convert QualityParlayGenerator output to frontend-compatible format"""
    import hashlib
    from datetime import datetime
    
    formatted = []
    for p in raw_parlays:
        confidence_map = {'trust': 'high', 'value': 'medium', 'sgp': 'medium'}
        
        formatted_legs = []
        leg_ids = []
        for leg in p.get('legs', []):
            match_id = leg.get('match_id')
            market = leg.get('market_name', '')
            leg_ids.append(f"{match_id}_{market}")
            
            formatted_legs.append({
                'match_id': match_id,
                'home_team': leg.get('home_team'),
                'away_team': leg.get('away_team'),
                'market': market,
                'market_type': leg.get('market_type', 'match_result'),
                'outcome': market,
                'odds': leg.get('decimal_odds'),
                'model_prob': round(leg.get('model_prob', 0) * 100, 1),
                'implied_prob': round(leg.get('implied_prob', 0) * 100, 1),
                'edge_pct': round((leg.get('model_prob', 0) - leg.get('implied_prob', 0)) * 100, 1),
                'kickoff_at': leg.get('kickoff_at'),
                'home_logo': leg.get('home_logo'),
                'away_logo': leg.get('away_logo'),
                'leg_quality_score': round(leg.get('lqs', 0), 3)
            })
        
        parlay_type = p.get('parlay_type', 'value')
        hash_input = f"{'-'.join(sorted(leg_ids))}_{parlay_type}"
        parlay_hash = hashlib.md5(hash_input.encode()).hexdigest()[:16]
        parlay_id = f"qp_{parlay_hash}"
        
        formatted.append({
            'id': parlay_id,
            'parlay_hash': parlay_hash,
            'leg_count': p.get('leg_count', 2),
            'combined_odds': round(p.get('combined_odds', 0), 2),
            'adjusted_prob_pct': round(p.get('raw_prob_pct', 0), 2),
            'edge_pct': round(p.get('edge_pct', 0), 2),
            'confidence_tier': confidence_map.get(parlay_type, 'medium'),
            'confidence': p.get('confidence_tier', 'medium'),
            'payout_100': round(p.get('combined_odds', 0) * 100, 2),
            'correlation_penalty_pct': 0,
            'leg_types': ['match_result'] * p.get('leg_count', 2),
            'status': 'pending',
            'result': None,
            'parlay_type': parlay_type,
            'legs': formatted_legs
        })
    
    return formatted


@router.get("/best")
async def get_best_parlays(
    leg_count: Optional[int] = Query(None, description="Filter by number of legs (2, 3, 4, 5)"),
    confidence: Optional[str] = Query(None, description="Filter by confidence tier (high, medium, low)"),
    min_edge: float = Query(0, description="Minimum edge percentage"),
    limit: int = Query(20, le=50, description="Max parlays to return"),
    use_quality: bool = Query(True, description="Use Quality Parlay Generator V2 (recommended)")
):
    """Get best parlays - now uses QualityParlayGenerator V2 by default"""
    try:
        if use_quality:
            qgen = get_quality_generator()
            raw_parlays = qgen.get_best_parlays(limit=limit)
            
            if confidence:
                confidence_map = {'high': 'trust', 'medium': 'value', 'low': 'value'}
                target_type = confidence_map.get(confidence, confidence)
                raw_parlays = [p for p in raw_parlays if p.get('parlay_type') == target_type]
            
            if leg_count:
                raw_parlays = [p for p in raw_parlays if p.get('leg_count') == leg_count]
            
            if min_edge > 0:
                raw_parlays = [p for p in raw_parlays if p.get('edge_pct', 0) >= min_edge]
            
            parlays = _format_quality_parlays_for_frontend(raw_parlays)
        else:
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
            "parlays": parlays,
            "generator": "quality_v2" if use_quality else "legacy"
        }
    except Exception as e:
        logger.error(f"Failed to get best parlays: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/by-legs/{leg_count}")
async def get_parlays_by_leg_count(
    leg_count: int,
    min_edge: float = Query(0, description="Minimum edge percentage"),
    limit: int = Query(20, le=50),
    use_quality: bool = Query(True, description="Use Quality Parlay Generator V2")
):
    """Get parlays filtered by leg count bucket"""
    if leg_count < 2 or leg_count > 10:
        raise HTTPException(status_code=400, detail="Leg count must be between 2 and 10")
    
    try:
        if use_quality:
            qgen = get_quality_generator()
            raw_parlays = qgen.get_best_parlays(limit=limit * 2)
            raw_parlays = [p for p in raw_parlays if p.get('leg_count') == leg_count]
            if min_edge > 0:
                raw_parlays = [p for p in raw_parlays if p.get('edge_pct', 0) >= min_edge]
            parlays = _format_quality_parlays_for_frontend(raw_parlays[:limit])
        else:
            gen = get_generator()
            parlays = gen.get_best_parlays(leg_count=leg_count, min_edge=min_edge, limit=limit)
        
        return {
            "leg_count": leg_count,
            "count": len(parlays),
            "default_bet": 100.0,
            "parlays": parlays,
            "generator": "quality_v2" if use_quality else "legacy"
        }
    except Exception as e:
        logger.error(f"Failed to get parlays by leg count: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/high-confidence")
async def get_high_confidence_parlays(
    min_edge: float = Query(5.0, description="Minimum edge percentage"),
    limit: int = Query(20, le=50),
    use_quality: bool = Query(True, description="Use Quality Parlay Generator V2")
):
    """Get high-confidence parlays with positive edge - now uses QualityParlayGenerator"""
    try:
        if use_quality:
            qgen = get_quality_generator()
            raw_parlays = qgen.generate_trust_parlays(max_parlays=limit)
            if min_edge > 0:
                raw_parlays = [p for p in raw_parlays if p.get('edge_pct', 0) >= min_edge]
            parlays = _format_quality_parlays_for_frontend(raw_parlays)
        else:
            gen = get_generator()
            parlays = gen.get_best_parlays(confidence="high", min_edge=min_edge, limit=limit)
        
        return {
            "confidence": "high",
            "min_edge": min_edge,
            "count": len(parlays),
            "default_bet": 100.0,
            "parlays": parlays,
            "generator": "quality_v2" if use_quality else "legacy"
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
