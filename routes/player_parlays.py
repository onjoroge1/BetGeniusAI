"""
Player Parlay API Routes
Provides endpoints for automated player scorer parlays
"""

from fastapi import APIRouter, Query, HTTPException
from typing import Optional, Dict, List
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/player-parlays", tags=["Player Parlays"])

_generator = None

def get_generator():
    global _generator
    if _generator is None:
        from models.player_parlay_generator import PlayerParlayGenerator
        _generator = PlayerParlayGenerator()
    return _generator


@router.get("/best")
async def get_best_player_parlays(
    limit: int = Query(default=10, ge=1, le=50),
    min_edge: float = Query(default=-30, description="Minimum edge percentage"),
    leg_count: Optional[int] = Query(default=None, ge=2, le=5, description="Filter by leg count")
) -> Dict:
    """
    Get best player scorer parlays for upcoming games.
    
    Returns pre-computed parlays with 2/3/4/5 legs combining
    anytime scorer predictions across multiple matches.
    """
    try:
        generator = get_generator()
        parlays = generator.get_best_parlays(
            limit=limit,
            min_edge=min_edge,
            leg_count=leg_count
        )
        
        formatted_parlays = []
        for p in parlays:
            formatted_parlays.append({
                'parlay_id': p['parlay_hash'],
                'leg_count': p['leg_count'],
                'combined_odds': float(p['combined_odds']),
                'win_probability': float(p['raw_prob_pct']),
                'edge_pct': float(p['edge_pct']),
                'confidence': p['confidence_tier'],
                'payout_100': float(p['payout_100']),
                'legs': [
                    {
                        'player': leg['player_name'],
                        'team': leg['team_name'],
                        'match': f"{leg['home_team']} vs {leg['away_team']}",
                        'league': leg['league_name'],
                        'scorer_prob': float(leg['model_prob']),
                        'odds': float(leg['decimal_odds']),
                        'edge_pct': float(leg['edge_pct'])
                    }
                    for leg in p.get('legs', [])
                ]
            })
        
        return {
            'count': len(formatted_parlays),
            'filters': {
                'min_edge': min_edge,
                'leg_count': leg_count
            },
            'default_bet': 100.0,
            'parlays': formatted_parlays
        }
        
    except Exception as e:
        logger.error(f"Error getting player parlays: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/by-legs/{leg_count}")
async def get_player_parlays_by_legs(
    leg_count: int,
    limit: int = Query(default=10, ge=1, le=50),
    min_edge: float = Query(default=-30)
) -> Dict:
    """Get player parlays filtered by leg count (2, 3, 4, or 5)."""
    if leg_count < 2 or leg_count > 5:
        raise HTTPException(status_code=400, detail="Leg count must be 2-5")
    
    try:
        generator = get_generator()
        parlays = generator.get_best_parlays(
            limit=limit,
            min_edge=min_edge,
            leg_count=leg_count
        )
        
        formatted = []
        for p in parlays:
            formatted.append({
                'parlay_id': p['parlay_hash'],
                'leg_count': p['leg_count'],
                'combined_odds': float(p['combined_odds']),
                'win_probability': float(p['raw_prob_pct']),
                'edge_pct': float(p['edge_pct']),
                'confidence': p['confidence_tier'],
                'payout_100': float(p['payout_100']),
                'legs': [
                    {
                        'player': leg['player_name'],
                        'team': leg['team_name'],
                        'match': f"{leg['home_team']} vs {leg['away_team']}",
                        'scorer_prob': float(leg['model_prob']),
                        'odds': float(leg['decimal_odds']),
                        'edge_pct': float(leg['edge_pct'])
                    }
                    for leg in p.get('legs', [])
                ]
            })
        
        return {
            'leg_count': leg_count,
            'count': len(formatted),
            'default_bet': 100.0,
            'parlays': formatted
        }
        
    except Exception as e:
        logger.error(f"Error getting player parlays by legs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/generate")
async def generate_player_parlays(
    hours_ahead: int = Query(default=72, ge=24, le=168)
) -> Dict:
    """
    Manually trigger player parlay generation for upcoming fixtures.
    
    This is normally run automatically by the scheduler every 10 minutes.
    """
    try:
        generator = get_generator()
        result = generator.generate_all_player_parlays(hours_ahead=hours_ahead)
        
        return {
            'status': 'success',
            'generation_result': result
        }
        
    except Exception as e:
        logger.error(f"Error generating player parlays: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
async def get_player_parlay_status() -> Dict:
    """Get status of player parlay system including counts by leg type."""
    try:
        from sqlalchemy import create_engine, text
        import os
        
        engine = create_engine(os.environ.get('DATABASE_URL'))
        
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT 
                    leg_count,
                    confidence_tier,
                    COUNT(*) as count,
                    AVG(edge_pct) as avg_edge,
                    MIN(expires_at) as earliest_expiry,
                    MAX(expires_at) as latest_expiry
                FROM player_parlays
                WHERE expires_at > NOW() AND status = 'pending'
                GROUP BY leg_count, confidence_tier
                ORDER BY leg_count, confidence_tier
            """))
            
            breakdown = [dict(row._mapping) for row in result.fetchall()]
            
            total_result = conn.execute(text("""
                SELECT COUNT(*) as total FROM player_parlays 
                WHERE expires_at > NOW() AND status = 'pending'
            """))
            total = total_result.fetchone()[0]
        
        return {
            'status': 'active',
            'total_active_parlays': total,
            'breakdown': breakdown
        }
        
    except Exception as e:
        logger.error(f"Error getting player parlay status: {e}")
        return {
            'status': 'error',
            'error': str(e),
            'total_active_parlays': 0
        }
