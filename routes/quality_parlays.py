"""
Quality Parlay API Routes
High-quality parlay endpoints with Trust/Value/SGP tiers
"""

from fastapi import APIRouter, Query, HTTPException
from typing import Optional, Dict, List
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/quality-parlays", tags=["Quality Parlays"])

_generator = None


def get_generator():
    global _generator
    if _generator is None:
        from models.quality_parlay_generator import QualityParlayGenerator
        _generator = QualityParlayGenerator()
    return _generator


@router.get("/best")
async def get_best_quality_parlays(
    limit: int = Query(default=10, ge=1, le=50),
    parlay_type: Optional[str] = Query(default=None, description="Filter: trust, value, sgp"),
    min_edge: float = Query(default=-100, description="Minimum edge percentage")
) -> Dict:
    """
    Get best quality parlays with proper constraints.
    
    Parlay Types:
    - trust: Each leg >= 55% prob, parlay >= 18% prob, different matches
    - value: Each leg >= 50% prob, parlay >= 12% prob, different matches
    - sgp: Same-game parlays with narrative-coherent templates
    """
    try:
        generator = get_generator()
        parlays = generator.get_best_parlays(
            parlay_type=parlay_type,
            limit=limit,
            min_edge=min_edge
        )
        
        formatted = []
        for p in parlays:
            formatted.append({
                'parlay_id': p['parlay_hash'],
                'parlay_type': p['parlay_type'],
                'leg_count': p['leg_count'],
                'combined_odds': p['combined_odds'],
                'win_probability': p['raw_prob_pct'],
                'edge_pct': p['edge_pct'],
                'confidence': p['confidence_tier'],
                'payout_100': p['payout_100'],
                'avg_quality_score': p['avg_lqs'],
                'same_match': p['same_match_flag'],
                'legs': [
                    {
                        'leg_type': leg['leg_type'],
                        'market': leg['market_code'],
                        'market_name': leg['market_name'],
                        'teams': f"{leg['home_team']} vs {leg['away_team']}",
                        'league': leg['league_name'],
                        'model_prob': leg['model_prob'],
                        'odds': leg['decimal_odds'],
                        'edge_pct': leg['edge_pct'],
                        'quality_score': leg.get('lqs', 0)
                    }
                    for leg in p.get('legs', [])
                ]
            })
        
        return {
            'count': len(formatted),
            'filters': {
                'parlay_type': parlay_type,
                'min_edge': min_edge
            },
            'default_bet': 100.0,
            'parlays': formatted
        }
        
    except Exception as e:
        logger.error(f"Error getting quality parlays: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/trust")
async def get_trust_parlays(
    limit: int = Query(default=10, ge=1, le=20)
) -> Dict:
    """
    Get Trust Parlays - highest quality, different matches.
    Each leg >= 55% probability, parlay >= 18% probability.
    """
    try:
        generator = get_generator()
        parlays = generator.generate_trust_parlays(max_parlays=limit)
        
        return {
            'parlay_type': 'trust',
            'description': 'High-quality parlays with strong conviction on each leg',
            'thresholds': {
                'min_leg_probability': '55%',
                'min_parlay_probability': '18%',
                'max_odds': 6.0
            },
            'count': len(parlays),
            'parlays': [_format_parlay(p) for p in parlays]
        }
        
    except Exception as e:
        logger.error(f"Error getting trust parlays: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/value")
async def get_value_parlays(
    limit: int = Query(default=10, ge=1, le=20)
) -> Dict:
    """
    Get Value Parlays - good quality with slightly higher odds.
    Each leg >= 50% probability, parlay 12-18% probability.
    """
    try:
        generator = get_generator()
        parlays = generator.generate_value_parlays(max_parlays=limit)
        
        return {
            'parlay_type': 'value',
            'description': 'Balanced parlays with good value and reasonable probability',
            'thresholds': {
                'min_leg_probability': '50%',
                'min_parlay_probability': '12%',
                'max_odds': 10.0
            },
            'count': len(parlays),
            'parlays': [_format_parlay(p) for p in parlays]
        }
        
    except Exception as e:
        logger.error(f"Error getting value parlays: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sgp")
async def get_sgp_parlays(
    limit: int = Query(default=5, ge=1, le=10)
) -> Dict:
    """
    Get Same-Game Parlays - coherent templates within single matches.
    Uses narrative-aligned combinations (Home + Over, Draw + Under, etc.)
    """
    try:
        generator = get_generator()
        parlays = generator.generate_sgp_parlays(max_parlays=limit)
        
        return {
            'parlay_type': 'sgp',
            'description': 'Same-game parlays with logically coherent leg combinations',
            'templates': [
                'Home/Away dominance + Over 1.5/2.5',
                'Draw + Under 2.5/3.5'
            ],
            'count': len(parlays),
            'parlays': [_format_parlay(p) for p in parlays]
        }
        
    except Exception as e:
        logger.error(f"Error getting SGP parlays: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
async def get_quality_parlay_status() -> Dict:
    """Get quality parlay generator status"""
    try:
        generator = get_generator()
        return generator.get_status()
    except Exception as e:
        logger.error(f"Error getting status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/leg-pool")
async def get_leg_pool(
    limit: int = Query(default=20, ge=1, le=50)
) -> Dict:
    """
    Get the ranked leg pool (best single bets across the slate).
    Useful for seeing which matches have the highest quality legs.
    """
    try:
        generator = get_generator()
        legs = generator.build_ranked_leg_pool()[:limit]
        
        return {
            'count': len(legs),
            'description': 'Single legs ranked by Leg Quality Score (LQS)',
            'legs': [
                {
                    'match': f"{leg['home_team']} vs {leg['away_team']}",
                    'league': leg['league_name'],
                    'market': leg['market_code'],
                    'market_name': leg['market_name'],
                    'model_prob': leg['model_prob'],
                    'book_prob': leg['book_prob'],
                    'odds': leg['decimal_odds'],
                    'edge_pct': leg['edge_pct'],
                    'quality_score': leg['lqs']
                }
                for leg in legs
            ]
        }
        
    except Exception as e:
        logger.error(f"Error getting leg pool: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _format_parlay(p: Dict) -> Dict:
    """Format parlay for API response"""
    return {
        'parlay_id': p['parlay_hash'],
        'parlay_type': p['parlay_type'],
        'leg_count': p['leg_count'],
        'combined_odds': p['combined_odds'],
        'win_probability': p['raw_prob_pct'],
        'edge_pct': p['edge_pct'],
        'confidence': p['confidence_tier'],
        'payout_100': p['payout_100'],
        'avg_quality_score': p['avg_lqs'],
        'same_match': p['same_match_flag'],
        'legs': [
            {
                'leg_type': leg['leg_type'],
                'market': leg['market_code'],
                'market_name': leg['market_name'],
                'teams': f"{leg['home_team']} vs {leg['away_team']}",
                'league': leg['league_name'],
                'model_prob': leg['model_prob'],
                'odds': leg['decimal_odds'],
                'edge_pct': leg['edge_pct'],
                'quality_score': leg.get('lqs', 0)
            }
            for leg in p.get('legs', [])
        ]
    }
