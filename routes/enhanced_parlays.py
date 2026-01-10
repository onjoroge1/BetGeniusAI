"""
BetGenius AI - Enhanced Parlay API Routes
Supports match results, totals, and player props with cross-market correlation
"""

import os
import json
import logging
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from datetime import datetime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/parlays-enhanced", tags=["parlays-enhanced"])
router_v2 = APIRouter(prefix="/api/v2/parlays-enhanced", tags=["parlays-enhanced-v2"])


class EnhancedLegSelection(BaseModel):
    leg_type: str  # 'match_result', 'totals', 'player_prop'
    match_id: int
    market: str  # 'H', 'D', 'A', 'over_2.5', 'under_2.5', 'anytime_scorer', etc.
    player_id: Optional[int] = None  # Required for player_prop


class EnhancedParlayRequest(BaseModel):
    selections: List[EnhancedLegSelection]


@router.post("/build")
@router_v2.post("/build")
async def build_enhanced_parlay(request: EnhancedParlayRequest) -> Dict[str, Any]:
    """
    Build an enhanced parlay with multiple market types.
    
    Supports:
    - match_result: Home/Draw/Away (H, D, A)
    - totals: Over/Under goals (over_2.5, under_2.5, over_1.5, etc.)
    - player_prop: Player markets (anytime_scorer, 2_plus_goals, to_assist)
    
    Returns edge calculation with cross-market correlation adjustments.
    """
    if len(request.selections) < 2:
        raise HTTPException(status_code=400, detail="Parlay requires at least 2 selections")
    
    if len(request.selections) > 10:
        raise HTTPException(status_code=400, detail="Maximum 10 legs per parlay")
    
    try:
        from models.enhanced_parlay_builder import EnhancedParlayBuilder
        builder = EnhancedParlayBuilder()
        
        selections = [
            {
                'leg_type': s.leg_type,
                'match_id': s.match_id,
                'market': s.market,
                'player_id': s.player_id
            }
            for s in request.selections
        ]
        
        result = builder.build_custom_parlay(selections)
        
        if 'error' in result:
            raise HTTPException(status_code=400, detail=result['error'])
        
        return result
        
    except Exception as e:
        logger.error(f"Error building enhanced parlay: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/smart")
@router_v2.get("/smart")
async def get_smart_parlays(
    max_parlays: int = Query(10, ge=1, le=20),
    min_edge: float = Query(0.05, ge=0, le=0.50),
    leg_count: Optional[int] = Query(None, ge=2, le=5)
) -> Dict[str, Any]:
    """
    Get AI-curated smart parlays with positive edge.
    
    Combines match results, totals, and player props for optimal diversification.
    """
    try:
        from models.enhanced_parlay_builder import EnhancedParlayBuilder
        builder = EnhancedParlayBuilder()
        
        parlays = builder.generate_smart_parlays(
            max_parlays=max_parlays,
            min_edge=min_edge
        )
        
        if leg_count:
            parlays = [p for p in parlays if p['leg_count'] == leg_count]
        
        return {
            'count': len(parlays),
            'criteria': {
                'min_edge_pct': min_edge * 100,
                'max_parlays': max_parlays,
                'leg_count_filter': leg_count
            },
            'parlays': parlays
        }
        
    except Exception as e:
        logger.error(f"Error generating smart parlays: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/markets/{match_id}")
@router_v2.get("/markets/{match_id}")
async def get_available_markets(match_id: int) -> Dict[str, Any]:
    """
    Get all available markets for a match (match result, totals, player props).
    
    Use this to see what legs can be added to a parlay for a specific match.
    """
    try:
        from models.totals_predictor import TotalsPredictor
        from models.player_props_service import PlayerPropsService
        from models.enhanced_parlay_builder import EnhancedParlayBuilder
        
        builder = EnhancedParlayBuilder()
        totals = TotalsPredictor()
        player_props = PlayerPropsService()
        
        match_info = builder._get_match_info(match_id)
        if not match_info:
            raise HTTPException(status_code=404, detail="Match not found")
        
        markets = {
            'match_info': {
                'match_id': match_id,
                'home_team': match_info['home_team'],
                'away_team': match_info['away_team'],
                'league': match_info['league_name'],
                'kickoff_at': match_info['kickoff_at'].isoformat() if match_info['kickoff_at'] else None
            },
            'match_result': {
                'H': {
                    'name': f"{match_info['home_team']} Win",
                    'model_prob': round(match_info['model_prob']['H'], 3),
                    'market_prob': round(match_info['market_prob']['H'], 3),
                    'decimal_odds': round(match_info['odds']['H'], 2),
                    'edge_pct': round((match_info['model_prob']['H'] - match_info['market_prob']['H']) / match_info['market_prob']['H'] * 100, 1) if match_info['market_prob']['H'] > 0 else 0
                },
                'D': {
                    'name': 'Draw',
                    'model_prob': round(match_info['model_prob']['D'], 3),
                    'market_prob': round(match_info['market_prob']['D'], 3),
                    'decimal_odds': round(match_info['odds']['D'], 2),
                    'edge_pct': round((match_info['model_prob']['D'] - match_info['market_prob']['D']) / match_info['market_prob']['D'] * 100, 1) if match_info['market_prob']['D'] > 0 else 0
                },
                'A': {
                    'name': f"{match_info['away_team']} Win",
                    'model_prob': round(match_info['model_prob']['A'], 3),
                    'market_prob': round(match_info['market_prob']['A'], 3),
                    'decimal_odds': round(match_info['odds']['A'], 2),
                    'edge_pct': round((match_info['model_prob']['A'] - match_info['market_prob']['A']) / match_info['market_prob']['A'] * 100, 1) if match_info['market_prob']['A'] > 0 else 0
                }
            }
        }
        
        totals_pred = totals.predict_match(match_id)
        if totals_pred and totals_pred.get('status') == 'available':
            markets['totals'] = {
                'expected_goals': totals_pred['expected_goals'],
                'over_under': totals_pred['over_under'],
                'btts': totals_pred['btts']
            }
        else:
            markets['totals'] = {'status': 'unavailable'}
        
        top_scorers = player_props.get_top_scorer_picks(match_ids=[match_id], limit=5)
        if top_scorers:
            markets['player_props'] = {
                'top_scorers': top_scorers
            }
        else:
            markets['player_props'] = {'status': 'no_players_available'}
        
        return markets
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting markets for match {match_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/totals/{match_id}")
@router_v2.get("/totals/{match_id}")
async def get_totals_prediction(match_id: int) -> Dict[str, Any]:
    """
    Get totals (over/under) prediction for a specific match.
    
    Returns Poisson-based goal probabilities for all common lines.
    """
    try:
        from models.totals_predictor import TotalsPredictor
        
        predictor = TotalsPredictor()
        result = predictor.predict_match(match_id)
        
        if not result:
            raise HTTPException(status_code=404, detail="Match not found")
        
        if result.get('status') != 'available':
            raise HTTPException(status_code=400, detail=result.get('error', 'Prediction unavailable'))
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting totals for match {match_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/player-props/{player_id}")
@router_v2.get("/player-props/{player_id}")
async def get_player_props(
    player_id: int,
    match_id: Optional[int] = Query(None)
) -> Dict[str, Any]:
    """
    Get player prop predictions for a specific player.
    
    Returns anytime scorer probability, 2+ goals, and assist predictions.
    """
    try:
        from models.player_props_service import PlayerPropsService
        
        service = PlayerPropsService()
        
        scorer_pred = service.predict_anytime_scorer(player_id, match_id)
        goals_pred = service.predict_goals_scored(player_id, match_id)
        
        if 'error' in scorer_pred:
            raise HTTPException(status_code=404, detail=scorer_pred['error'])
        
        return {
            'player_id': player_id,
            'player_name': scorer_pred['player_name'],
            'position': scorer_pred['position'],
            'markets': {
                'anytime_scorer': {
                    'probability': scorer_pred['probability'],
                    'confidence': scorer_pred['confidence']
                },
                'goals': goals_pred['probabilities'],
                'expected_goals': goals_pred['expected_goals']
            },
            'form': scorer_pred['form']
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting player props for {player_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/top-scorer-picks")
@router_v2.get("/top-scorer-picks")
async def get_top_scorer_picks(
    limit: int = Query(10, ge=1, le=50)
) -> Dict[str, Any]:
    """
    Get top scorer picks across upcoming matches.
    
    Returns players most likely to score based on form and position.
    """
    try:
        from models.player_props_service import PlayerPropsService
        
        service = PlayerPropsService()
        picks = service.get_top_scorer_picks(limit=limit)
        
        return {
            'count': len(picks),
            'picks': picks
        }
        
    except Exception as e:
        logger.error(f"Error getting top scorer picks: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/correlation-matrix")
@router_v2.get("/correlation-matrix")
async def get_correlation_matrix() -> Dict[str, Any]:
    """
    Get the cross-market correlation matrix used for parlay adjustments.
    
    Shows how different bet types within the same match are correlated.
    """
    from models.enhanced_parlay_builder import CROSS_MARKET_CORRELATIONS, SAME_LEAGUE_PENALTY, SAME_TIME_PENALTY
    
    formatted = {}
    for key, value in CROSS_MARKET_CORRELATIONS.items():
        type1, market1, type2, market2 = key
        readable_key = f"{type1}:{market1} + {type2}:{market2}"
        formatted[readable_key] = {
            'correlation': value,
            'penalty_applied': round(abs(value) * 0.3, 3)
        }
    
    return {
        'cross_market_correlations': formatted,
        'structural_penalties': {
            'same_league': SAME_LEAGUE_PENALTY,
            'same_time_slot': SAME_TIME_PENALTY,
            'favorites_combo': 0.05
        },
        'max_total_penalty': 0.50,
        'explanation': 'Positive correlations between legs from the same match reduce true win probability. The parlay builder applies a penalty proportional to correlation strength.'
    }
