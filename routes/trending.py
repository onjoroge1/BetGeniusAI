"""
Trending & Hot Matches API
Returns pre-computed trending and hot matches from cache
"""
from fastapi import APIRouter, Query, HTTPException, Request
from typing import Optional, List, Dict, Any
from datetime import datetime
import logging
import redis
import json
import os

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/trending", tags=["trending"])

# Initialize Redis client
try:
    redis_host = os.getenv("REDIS_HOST", "localhost")
    redis_port = int(os.getenv("REDIS_PORT", 6379))
    redis_client = redis.Redis(
        host=redis_host,
        port=redis_port,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_keepalive=True,
        health_check_interval=10
    )
    redis_client.ping()
    logger.info(f"✅ Redis connected: {redis_host}:{redis_port}")
except Exception as e:
    logger.warning(f"⚠️ Redis not available: {e} - endpoints will compute on-demand")
    redis_client = None


async def get_cached_data(key: str, default: List[Dict] = None) -> Optional[Any]:
    """Get data from Redis cache"""
    if not redis_client:
        return default or []
    
    try:
        cached = redis_client.get(key)
        if cached:
            return json.loads(cached)
    except Exception as e:
        logger.warning(f"Redis get error: {e}")
    
    return default or []


async def set_cached_data(key: str, data: Any, ttl: int = 300) -> bool:
    """Set data in Redis cache with TTL"""
    if not redis_client:
        return False
    
    try:
        redis_client.setex(key, ttl, json.dumps(data))
        return True
    except Exception as e:
        logger.warning(f"Redis set error: {e}")
        return False


# ============================================================================
# GET /api/v1/trending/hot
# ============================================================================

@router.get("/hot", response_model=Dict[str, Any])
async def get_hot_matches(
    league_id: Optional[int] = Query(None, description="Filter by league ID"),
    min_confidence: float = Query(0.0, ge=0, le=1, description="Minimum prediction confidence"),
    limit: int = Query(20, ge=1, le=100, description="Number of matches to return")
):
    """
    Get top hot matches (high momentum + value opportunities)
    
    Hot matches are those with:
    - High momentum (real-time engagement)
    - CLV alerts (value opportunities)
    - Prediction disagreement (model edge)
    
    Scores cached for 5 minutes, served <5ms
    
    Example:
        GET /api/v1/trending/hot?league_id=39&limit=10
    """
    try:
        # Build cache key
        cache_key = f"trending:hot:{league_id}:{limit}"
        
        # Try cache first
        logger.debug(f"🔍 Checking cache for hot matches: {cache_key}")
        cached_result = await get_cached_data(cache_key)
        
        if cached_result:
            logger.info(f"✅ Cache hit for hot matches")
            return {
                "matches": cached_result,
                "meta": {
                    "cache_hit": True,
                    "count": len(cached_result),
                    "cache_ttl_seconds": 300,
                    "timestamp": datetime.utcnow().isoformat()
                }
            }
        
        # Cache miss - return empty for now (should be populated by scheduler)
        # In production, this is rarely hit as scheduler keeps cache fresh
        logger.warning(f"⚠️ Cache miss for hot matches - scheduler may not have run yet")
        
        return {
            "matches": [],
            "meta": {
                "cache_hit": False,
                "count": 0,
                "status": "cache_miss",
                "note": "Trending scores are pre-computed every 5 minutes. Check back in a moment.",
                "timestamp": datetime.utcnow().isoformat()
            }
        }
    
    except Exception as e:
        logger.error(f"Error in /hot endpoint: {e}", exc_info=True)
        raise HTTPException(500, f"Failed to fetch hot matches: {str(e)}")


# ============================================================================
# GET /api/v1/trending/trending
# ============================================================================

@router.get("/trending", response_model=Dict[str, Any])
async def get_trending_matches(
    timeframe: str = Query("5m", regex="^(5m|15m|1h)$", description="Timeframe for trend detection"),
    league_id: Optional[int] = Query(None, description="Filter by league ID"),
    min_momentum_velocity: float = Query(0.0, description="Minimum momentum change per minute"),
    limit: int = Query(20, ge=1, le=100, description="Number of matches to return")
):
    """
    Get top trending matches (growing interest/momentum acceleration)
    
    Trending matches are those with:
    - Momentum acceleration (momentum growing rapidly)
    - Odds movement (bookmakers adjusting)
    - Confidence change (models becoming more certain)
    
    Scores cached for 5 minutes, served <5ms
    
    Example:
        GET /api/v1/trending/trending?timeframe=5m&limit=10
    """
    try:
        # Build cache key
        cache_key = f"trending:trending:{timeframe}:{league_id}:{limit}"
        
        # Try cache first
        logger.debug(f"🔍 Checking cache for trending matches: {cache_key}")
        cached_result = await get_cached_data(cache_key)
        
        if cached_result:
            logger.info(f"✅ Cache hit for trending matches")
            return {
                "matches": cached_result,
                "meta": {
                    "cache_hit": True,
                    "timeframe": timeframe,
                    "count": len(cached_result),
                    "cache_ttl_seconds": 300,
                    "timestamp": datetime.utcnow().isoformat()
                }
            }
        
        # Cache miss
        logger.warning(f"⚠️ Cache miss for trending matches")
        
        return {
            "matches": [],
            "meta": {
                "cache_hit": False,
                "timeframe": timeframe,
                "count": 0,
                "status": "cache_miss",
                "note": "Trending scores are pre-computed every 5 minutes.",
                "timestamp": datetime.utcnow().isoformat()
            }
        }
    
    except Exception as e:
        logger.error(f"Error in /trending endpoint: {e}", exc_info=True)
        raise HTTPException(500, f"Failed to fetch trending matches: {str(e)}")


# ============================================================================
# GET /api/v1/trending/status
# ============================================================================

@router.get("/status", response_model=Dict[str, Any])
async def get_trending_status():
    """
    Get status of trending scores cache
    
    Useful for debugging cache health and last update times
    """
    try:
        if not redis_client:
            return {
                "status": "redis_unavailable",
                "hot_matches": 0,
                "trending_matches": 0,
                "cache_health": "degraded",
                "timestamp": datetime.utcnow().isoformat()
            }
        
        # Check cache status
        hot_cache = await get_cached_data("trending:hot:None:20")
        trending_cache = await get_cached_data("trending:trending:5m:None:20")
        
        try:
            meta = redis_client.get("trending:meta")
            meta_data = json.loads(meta) if meta else {}
        except:
            meta_data = {}
        
        return {
            "status": "healthy",
            "hot_matches_cached": len(hot_cache) if hot_cache else 0,
            "trending_matches_cached": len(trending_cache) if trending_cache else 0,
            "cache_ttl_seconds": 300,
            "last_update": meta_data.get("updated_at", "unknown"),
            "cache_health": "healthy" if (hot_cache or trending_cache) else "empty",
            "timestamp": datetime.utcnow().isoformat()
        }
    
    except Exception as e:
        logger.error(f"Error in /status endpoint: {e}")
        return {
            "status": "error",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }
