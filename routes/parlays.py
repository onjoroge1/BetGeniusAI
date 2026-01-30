"""
Parlay API - AI-Curated Parlay Recommendations
Returns generated parlays with edge calculation and correlation adjustments
"""
from fastapi import APIRouter, Query, HTTPException, Request
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime
import logging
import redis
import json
import os
from sqlalchemy import create_engine, text

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/parlays", tags=["parlays"])
router_v2 = APIRouter(prefix="/api/v2/parlays", tags=["parlays-v2"])

try:
    db_url = os.getenv("DATABASE_URL")
    db_engine = create_engine(db_url, pool_pre_ping=True)
    logger.info("Parlay API: Database engine initialized")
except Exception as e:
    logger.error(f"Parlay API: Failed to initialize database: {e}")
    db_engine = None

try:
    redis_host = os.getenv("REDIS_HOST", "localhost")
    redis_port = int(os.getenv("REDIS_PORT", 6379))
    redis_client = redis.Redis(
        host=redis_host,
        port=redis_port,
        decode_responses=True,
        socket_connect_timeout=2
    )
    redis_client.ping()
    logger.info(f"Parlay API: Redis connected")
except Exception as e:
    logger.warning(f"Parlay API: Redis not available: {e}")
    redis_client = None


class ParlaySelection(BaseModel):
    match_id: int
    outcome: str  # 'H', 'D', 'A'


class CustomParlayRequest(BaseModel):
    selections: List[ParlaySelection]


@router.get("")
@router_v2.get("")
async def list_parlays(
    status: str = Query("active", description="Filter by status: active, settled, expired"),
    confidence_tier: Optional[str] = Query(None, description="Filter by tier: high, medium, low"),
    leg_count: Optional[int] = Query(None, description="Filter by number of legs"),
    limit: int = Query(20, ge=1, le=100)
) -> Dict[str, Any]:
    """
    List all generated parlays with optional filtering.
    
    Returns AI-curated parlays with edge calculations and confidence tiers.
    """
    if not db_engine:
        raise HTTPException(status_code=503, detail="Database not available")
    
    cache_key = f"parlays:list:{status}:{confidence_tier}:{leg_count}:{limit}"
    if redis_client:
        try:
            cached = redis_client.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception:
            pass
    
    try:
        with db_engine.connect() as conn:
            query = """
                SELECT 
                    parlay_id::text,
                    leg_count,
                    legs,
                    combined_prob,
                    correlation_penalty,
                    adjusted_prob,
                    implied_odds,
                    market_implied_prob,
                    edge_pct,
                    confidence_tier,
                    parlay_type,
                    league_group,
                    earliest_kickoff,
                    latest_kickoff,
                    kickoff_window,
                    status,
                    created_at
                FROM parlay_consensus
                WHERE status = :status
            """
            params = {'status': status, 'limit': limit}
            
            if confidence_tier:
                query += " AND confidence_tier = :tier"
                params['tier'] = confidence_tier
            
            if leg_count:
                query += " AND leg_count = :leg_count"
                params['leg_count'] = leg_count
            
            query += " ORDER BY edge_pct DESC, created_at DESC LIMIT :limit"
            
            result = conn.execute(text(query), params)
            
            parlays = []
            for row in result:
                parlays.append({
                    'parlay_id': row.parlay_id,
                    'leg_count': row.leg_count,
                    'legs': row.legs if isinstance(row.legs, list) else json.loads(row.legs) if row.legs else [],
                    'combined_prob': float(row.combined_prob) if row.combined_prob else 0,
                    'correlation_penalty': float(row.correlation_penalty) if row.correlation_penalty else 0,
                    'adjusted_prob': float(row.adjusted_prob) if row.adjusted_prob else 0,
                    'implied_odds': float(row.implied_odds) if row.implied_odds else 0,
                    'edge_pct': float(row.edge_pct) if row.edge_pct else 0,
                    'confidence_tier': row.confidence_tier,
                    'parlay_type': row.parlay_type,
                    'league_group': row.league_group,
                    'earliest_kickoff': row.earliest_kickoff.isoformat() if row.earliest_kickoff else None,
                    'latest_kickoff': row.latest_kickoff.isoformat() if row.latest_kickoff else None,
                    'kickoff_window': row.kickoff_window,
                    'status': row.status,
                    'created_at': row.created_at.isoformat() if row.created_at else None
                })
            
            response = {
                'count': len(parlays),
                'status_filter': status,
                'parlays': parlays
            }
            
            if redis_client:
                try:
                    redis_client.setex(cache_key, 300, json.dumps(response))
                except Exception:
                    pass
            
            return response
            
    except Exception as e:
        logger.error(f"Error listing parlays: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/recommended")
@router_v2.get("/recommended")
async def get_recommended_parlays(
    min_edge: float = Query(0.05, description="Minimum edge percentage"),
    max_parlays: int = Query(10, ge=1, le=20),
    confidence_tiers: str = Query("high,medium", description="Comma-separated tiers to include")
) -> Dict[str, Any]:
    """
    Get AI-curated recommended parlays meeting strict criteria.
    
    Returns only parlays with positive edge, high confidence, and low correlation.
    These are the "Smart Parlays" highlighted for users.
    """
    if not db_engine:
        raise HTTPException(status_code=503, detail="Database not available")
    
    cache_key = f"parlays:recommended:{min_edge}:{max_parlays}:{confidence_tiers}"
    if redis_client:
        try:
            cached = redis_client.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception:
            pass
    
    try:
        tiers = [t.strip() for t in confidence_tiers.split(",")]
        tier_placeholders = ",".join([f"'{t}'" for t in tiers])
        
        with db_engine.connect() as conn:
            query = f"""
                SELECT 
                    parlay_id::text,
                    leg_count,
                    legs,
                    combined_prob,
                    correlation_penalty,
                    adjusted_prob,
                    implied_odds,
                    edge_pct,
                    confidence_tier,
                    parlay_type,
                    league_group,
                    earliest_kickoff,
                    kickoff_window,
                    created_at
                FROM parlay_consensus
                WHERE status = 'active'
                AND edge_pct >= :min_edge
                AND confidence_tier IN ({tier_placeholders})
                AND earliest_kickoff > NOW()
                ORDER BY 
                    CASE confidence_tier WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
                    edge_pct DESC
                LIMIT :limit
            """
            
            result = conn.execute(text(query), {'min_edge': min_edge, 'limit': max_parlays})
            
            parlays = []
            for row in result:
                legs_data = row.legs if isinstance(row.legs, list) else json.loads(row.legs) if row.legs else []
                
                parlays.append({
                    'parlay_id': row.parlay_id,
                    'leg_count': row.leg_count,
                    'legs': legs_data,
                    'edge_pct': round(float(row.edge_pct) * 100, 1),
                    'edge_label': f"+{round(float(row.edge_pct) * 100, 1)}%" if row.edge_pct > 0 else f"{round(float(row.edge_pct) * 100, 1)}%",
                    'implied_odds': round(float(row.implied_odds), 2),
                    'adjusted_prob': round(float(row.adjusted_prob) * 100, 1),
                    'correlation_penalty': round(float(row.correlation_penalty) * 100, 1),
                    'confidence_tier': row.confidence_tier,
                    'parlay_type': row.parlay_type,
                    'league_group': row.league_group,
                    'earliest_kickoff': row.earliest_kickoff.isoformat() if row.earliest_kickoff else None,
                    'kickoff_window': row.kickoff_window
                })
            
            response = {
                'recommended_count': len(parlays),
                'criteria': {
                    'min_edge_pct': min_edge * 100,
                    'confidence_tiers': tiers
                },
                'parlays': parlays
            }
            
            if redis_client:
                try:
                    redis_client.setex(cache_key, 300, json.dumps(response))
                except Exception:
                    pass
            
            return response
            
    except Exception as e:
        logger.error(f"Error getting recommended parlays: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/build")
@router_v2.post("/build")
async def build_custom_parlay(request: CustomParlayRequest) -> Dict[str, Any]:
    """
    Build a custom parlay from user-selected matches.
    
    Accepts match selections and returns:
    - Combined odds calculation
    - Model probability estimate
    - Edge percentage (positive or negative)
    - Correlation warning if same-league matches
    """
    if len(request.selections) < 2:
        raise HTTPException(status_code=400, detail="Parlay requires at least 2 selections")
    
    if len(request.selections) > 10:
        raise HTTPException(status_code=400, detail="Maximum 10 legs per parlay")
    
    try:
        from models.parlay_builder import ParlayBuilder
        builder = ParlayBuilder()
        
        selections = [{'match_id': s.match_id, 'outcome': s.outcome} for s in request.selections]
        parlay = builder.build_custom_parlay(selections)
        
        if not parlay:
            raise HTTPException(status_code=400, detail="Could not build parlay - matches not found or odds unavailable")
        
        edge_pct = parlay.get('edge_pct', 0)
        if edge_pct >= 0.05:
            edge_indicator = 'positive'
        elif edge_pct >= 0:
            edge_indicator = 'neutral'
        else:
            edge_indicator = 'negative'
        
        correlation_penalty = parlay.get('correlation_penalty', 0)
        if correlation_penalty > 0.15:
            correlation_warning = "High correlation detected - consider diversifying across leagues"
        elif correlation_penalty > 0.05:
            correlation_warning = "Moderate correlation - some legs may affect each other"
        else:
            correlation_warning = None
        
        response = {
            'parlay': {
                'leg_count': parlay['leg_count'],
                'legs': parlay['legs'],
                'combined_odds': round(parlay['implied_odds'], 2),
                'combined_prob_pct': round(parlay['adjusted_prob'] * 100, 2),
                'edge_pct': round(edge_pct * 100, 2),
                'edge_indicator': edge_indicator,
                'correlation_penalty_pct': round(correlation_penalty * 100, 1),
                'correlation_warning': correlation_warning,
                'confidence_tier': parlay.get('confidence_tier', 'low')
            },
            'recommendation': _get_parlay_recommendation(edge_pct, correlation_penalty)
        }
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error building custom parlay: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
@router_v2.get("/status")
async def get_parlay_status() -> Dict[str, Any]:
    """
    Get parlay system status and statistics.
    """
    if not db_engine:
        return {'status': 'error', 'message': 'Database not available'}
    
    try:
        with db_engine.connect() as conn:
            result = conn.execute(text("""
                SELECT 
                    COUNT(*) FILTER (WHERE status = 'active') as active_count,
                    COUNT(*) FILTER (WHERE status = 'settled') as settled_count,
                    COUNT(*) FILTER (WHERE status = 'expired') as expired_count,
                    COUNT(*) FILTER (WHERE confidence_tier = 'high' AND status = 'active') as high_confidence_count,
                    AVG(edge_pct) FILTER (WHERE status = 'active') as avg_edge,
                    MAX(created_at) as last_generated
                FROM parlay_consensus
            """))
            
            row = result.fetchone()
            
            return {
                'status': 'ok',
                'stats': {
                    'active_parlays': row.active_count or 0,
                    'settled_parlays': row.settled_count or 0,
                    'expired_parlays': row.expired_count or 0,
                    'high_confidence_active': row.high_confidence_count or 0,
                    'avg_edge_pct': round(float(row.avg_edge or 0) * 100, 2),
                    'last_generated': row.last_generated.isoformat() if row.last_generated else None
                }
            }
            
    except Exception as e:
        logger.error(f"Error getting parlay status: {e}")
        return {'status': 'error', 'message': str(e)}


@router.get("/performance")
@router_v2.get("/performance")
async def get_parlay_performance() -> Dict[str, Any]:
    """
    Get parlay performance statistics and ROI tracking.
    
    Returns overall and per-tier performance metrics for settled parlays.
    """
    try:
        from jobs.settle_parlays import get_parlay_performance_summary
        return get_parlay_performance_summary()
    except ImportError:
        raise HTTPException(status_code=503, detail="Performance module not available")
    except Exception as e:
        logger.error(f"Error getting performance: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _get_parlay_recommendation(edge_pct: float, correlation_penalty: float) -> str:
    """Generate a recommendation based on edge and correlation"""
    if edge_pct >= 0.08 and correlation_penalty <= 0.15:
        return "Strong value detected - this parlay has high edge and low correlation"
    elif edge_pct >= 0.05:
        return "Moderate value detected - consider this parlay"
    elif edge_pct >= 0:
        return "Fair odds - no significant edge but acceptable value"
    else:
        return "Negative edge detected - the market may be overpricing this combination"


@router.get("/health")
@router_v2.get("/health")
async def get_parlay_health(
    since_date: Optional[str] = Query("2026-01-29", description="Start date for analysis (YYYY-MM-DD)")
) -> Dict[str, Any]:
    """
    Get parlay health dashboard with performance metrics across all parlay types.
    
    Returns summary statistics, P&L tracking, and recent parlay table.
    """
    if not db_engine:
        raise HTTPException(status_code=503, detail="Database not available")
    
    import re
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', since_date):
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    
    try:
        with db_engine.connect() as conn:
            summary_query = """
            WITH auto_parlays AS (
                SELECT 
                    'auto_parlay' as parlay_type,
                    COUNT(*) as total,
                    COUNT(CASE WHEN result = 'won' THEN 1 END) as wins,
                    COUNT(CASE WHEN result = 'lost' THEN 1 END) as losses,
                    COUNT(CASE WHEN status = 'pending' THEN 1 END) as pending,
                    ROUND(AVG(combined_odds)::numeric, 2) as avg_odds,
                    ROUND(AVG(edge_pct)::numeric, 2) as avg_edge,
                    ROUND(SUM(CASE WHEN result = 'won' THEN (combined_odds - 1) * 100 ELSE 0 END)::numeric, 2) as won_amount,
                    ROUND(SUM(CASE WHEN result = 'lost' THEN -100 ELSE 0 END)::numeric, 2) as lost_amount
                FROM parlay_precomputed
                WHERE created_at >= CAST(:since_date AS date)
            ),
            player_parlays_cte AS (
                SELECT 
                    'player_parlay' as parlay_type,
                    COUNT(*) as total,
                    COUNT(CASE WHEN result = 'won' THEN 1 END) as wins,
                    COUNT(CASE WHEN result = 'lost' THEN 1 END) as losses,
                    COUNT(CASE WHEN status = 'pending' THEN 1 END) as pending,
                    ROUND(AVG(combined_odds)::numeric, 2) as avg_odds,
                    ROUND(AVG(edge_pct)::numeric, 2) as avg_edge,
                    ROUND(SUM(CASE WHEN result = 'won' THEN (combined_odds - 1) * 100 ELSE 0 END)::numeric, 2) as won_amount,
                    ROUND(SUM(CASE WHEN result = 'lost' THEN -100 ELSE 0 END)::numeric, 2) as lost_amount
                FROM player_parlays
                WHERE created_at >= CAST(:since_date AS date)
            ),
            consensus_parlays AS (
                SELECT 
                    parlay_type,
                    COUNT(*) as total,
                    COUNT(CASE WHEN won = true THEN 1 END) as wins,
                    COUNT(CASE WHEN won = false THEN 1 END) as losses,
                    COUNT(CASE WHEN won IS NULL AND status = 'active' THEN 1 END) as pending,
                    ROUND(AVG(implied_odds)::numeric, 2) as avg_odds,
                    ROUND(AVG(edge_pct)::numeric, 2) as avg_edge,
                    ROUND(SUM(CASE WHEN won = true THEN (implied_odds - 1) * 100 ELSE 0 END)::numeric, 2) as won_amount,
                    ROUND(SUM(CASE WHEN won = false THEN -100 ELSE 0 END)::numeric, 2) as lost_amount
                FROM parlay_consensus
                WHERE created_at >= CAST(:since_date AS date)
                GROUP BY parlay_type
            )
            SELECT * FROM auto_parlays WHERE total > 0
            UNION ALL
            SELECT * FROM player_parlays_cte WHERE total > 0
            UNION ALL
            SELECT * FROM consensus_parlays WHERE total > 0
            ORDER BY parlay_type
            """
            
            result = conn.execute(text(summary_query), {"since_date": since_date})
            rows = result.fetchall()
            
            summary_table = []
            total_pnl = 0.0
            total_settled = 0
            total_wins = 0
            
            for row in rows:
                net_pnl = float(row.won_amount or 0) + float(row.lost_amount or 0)
                settled = int(row.wins or 0) + int(row.losses or 0)
                accuracy = round(100.0 * row.wins / settled, 1) if settled > 0 else None
                
                summary_table.append({
                    "parlay_type": row.parlay_type,
                    "total": row.total,
                    "wins": row.wins,
                    "losses": row.losses,
                    "pending": row.pending,
                    "accuracy_pct": accuracy,
                    "avg_odds": float(row.avg_odds) if row.avg_odds else None,
                    "avg_edge_pct": float(row.avg_edge) if row.avg_edge else None,
                    "won_amount": float(row.won_amount) if row.won_amount else 0,
                    "lost_amount": float(row.lost_amount) if row.lost_amount else 0,
                    "net_pnl": net_pnl
                })
                
                total_pnl += net_pnl
                total_settled += settled
                total_wins += row.wins or 0
            
            recent_query = """
            (
                SELECT 
                    'auto_parlay' as type,
                    id::text as parlay_id,
                    leg_count,
                    ROUND(combined_odds::numeric, 2) as odds,
                    ROUND(edge_pct::numeric, 2) as edge_pct,
                    confidence_tier,
                    status,
                    result,
                    created_at
                FROM parlay_precomputed
                WHERE created_at >= CAST(:since_date AS date)
                ORDER BY created_at DESC
                LIMIT 8
            )
            UNION ALL
            (
                SELECT 
                    'player_parlay' as type,
                    id::text as parlay_id,
                    leg_count,
                    ROUND(combined_odds::numeric, 2) as odds,
                    ROUND(edge_pct::numeric, 2) as edge_pct,
                    confidence_tier,
                    status,
                    result,
                    created_at
                FROM player_parlays
                WHERE created_at >= CAST(:since_date AS date)
                ORDER BY created_at DESC
                LIMIT 8
            )
            UNION ALL
            (
                SELECT 
                    parlay_type as type,
                    parlay_id::text as parlay_id,
                    leg_count,
                    ROUND(implied_odds::numeric, 2) as odds,
                    ROUND(edge_pct::numeric, 2) as edge_pct,
                    confidence_tier,
                    status,
                    CASE WHEN won = true THEN 'won' WHEN won = false THEN 'lost' ELSE NULL END as result,
                    created_at
                FROM parlay_consensus
                WHERE created_at >= CAST(:since_date AS date)
                ORDER BY created_at DESC
                LIMIT 8
            )
            ORDER BY created_at DESC
            LIMIT 24
            """
            
            result2 = conn.execute(text(recent_query), {"since_date": since_date})
            recent_rows = result2.fetchall()
            
            recent_parlays = []
            for row in recent_rows:
                recent_parlays.append({
                    "type": row.type,
                    "parlay_id": row.parlay_id,
                    "leg_count": row.leg_count,
                    "odds": float(row.odds) if row.odds else None,
                    "edge_pct": float(row.edge_pct) if row.edge_pct else None,
                    "confidence_tier": row.confidence_tier,
                    "status": row.status,
                    "result": row.result,
                    "created_at": row.created_at.isoformat() if row.created_at else None
                })
            
            overall_accuracy = round(100.0 * total_wins / total_settled, 1) if total_settled > 0 else None
            
            return {
                "status": "ok",
                "since_date": since_date,
                "overall_summary": {
                    "total_settled": total_settled,
                    "total_wins": total_wins,
                    "total_losses": total_settled - total_wins,
                    "accuracy_pct": overall_accuracy,
                    "net_pnl_100_per_bet": round(total_pnl, 2),
                    "roi_pct": round(100 * total_pnl / (total_settled * 100), 2) if total_settled > 0 else None
                },
                "by_type": summary_table,
                "recent_parlays": recent_parlays
            }
            
    except Exception as e:
        logger.error(f"Error getting parlay health: {e}")
        raise HTTPException(status_code=500, detail=str(e))
