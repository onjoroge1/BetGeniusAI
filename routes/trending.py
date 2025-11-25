"""
Trending & Hot Matches API
Returns pre-computed trending and hot matches from cache (or database fallback)
"""
from fastapi import APIRouter, Query, HTTPException, Request
from typing import Optional, List, Dict, Any
from datetime import datetime
import logging
import redis
import json
import os
from sqlalchemy import create_engine, text, desc
from sqlalchemy.orm import Session
from models.trending_score import TrendingScore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/trending", tags=["trending"])

# Initialize database connection
try:
    db_url = os.getenv("DATABASE_URL")
    db_engine = create_engine(db_url)
    logger.info("✅ Database engine initialized")
except Exception as e:
    logger.error(f"❌ Failed to initialize database: {e}")
    db_engine = None

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
    logger.warning(f"⚠️ Redis not available: {e} - will use database fallback")
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


async def get_hot_matches_from_db(league_id: Optional[int] = None, limit: int = 20) -> List[Dict[str, Any]]:
    """Query hot matches from database (fallback when Redis unavailable)"""
    if not db_engine:
        logger.warning("Database engine not available")
        return []
    
    try:
        with Session(db_engine) as session:
            query = session.query(TrendingScore).order_by(desc(TrendingScore.hot_score))
            
            if league_id:
                # Filter by league - need to join with fixtures
                from models.fixtures import Fixture
                query = query.join(Fixture, TrendingScore.match_id == Fixture.fixture_id).filter(
                    Fixture.league_id == league_id
                )
            
            scores = query.limit(limit).all()
            
            # Serialize to dict
            matches = []
            for score in scores:
                matches.append({
                    "match_id": score.match_id,
                    "hot_score": float(score.hot_score),
                    "trending_score": float(score.trending_score),
                    "hot_rank": score.hot_rank,
                    "trending_rank": score.trending_rank,
                    "momentum_current": float(score.momentum_current) if score.momentum_current else 0.0,
                    "momentum_velocity": float(score.momentum_velocity) if score.momentum_velocity else 0.0,
                    "clv_signal_count": score.clv_signal_count or 0,
                    "prediction_disagreement": float(score.prediction_disagreement) if score.prediction_disagreement else 0.0
                })
            
            logger.info(f"✅ Loaded {len(matches)} hot matches from database")
            return matches
    except Exception as e:
        logger.error(f"Error querying hot matches from DB: {e}")
        return []


async def get_trending_matches_from_db(timeframe: str = "5m", league_id: Optional[int] = None, limit: int = 20) -> List[Dict[str, Any]]:
    """Query trending matches from database (fallback when Redis unavailable)"""
    if not db_engine:
        logger.warning("Database engine not available")
        return []
    
    try:
        with Session(db_engine) as session:
            query = session.query(TrendingScore).order_by(desc(TrendingScore.trending_score))
            
            if league_id:
                # Filter by league - need to join with fixtures
                from models.fixtures import Fixture
                query = query.join(Fixture, TrendingScore.match_id == Fixture.fixture_id).filter(
                    Fixture.league_id == league_id
                )
            
            scores = query.limit(limit).all()
            
            # Serialize to dict
            matches = []
            for score in scores:
                matches.append({
                    "match_id": score.match_id,
                    "hot_score": float(score.hot_score),
                    "trending_score": float(score.trending_score),
                    "hot_rank": score.hot_rank,
                    "trending_rank": score.trending_rank,
                    "momentum_current": float(score.momentum_current) if score.momentum_current else 0.0,
                    "momentum_velocity": float(score.momentum_velocity) if score.momentum_velocity else 0.0,
                    "clv_signal_count": score.clv_signal_count or 0,
                    "prediction_disagreement": float(score.prediction_disagreement) if score.prediction_disagreement else 0.0,
                    "timeframe": timeframe
                })
            
            logger.info(f"✅ Loaded {len(matches)} trending matches from database")
            return matches
    except Exception as e:
        logger.error(f"Error querying trending matches from DB: {e}")
        return []


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
        
        # Cache miss - try database fallback
        logger.warning(f"⚠️ Cache miss for hot matches - querying database")
        db_matches = await get_hot_matches_from_db(league_id=league_id, limit=limit)
        
        return {
            "matches": db_matches,
            "meta": {
                "cache_hit": False,
                "count": len(db_matches),
                "status": "database_fallback" if db_matches else "no_data",
                "note": "Data served from database (cache unavailable)" if db_matches else "No trending scores available yet",
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
        
        # Cache miss - try database fallback
        logger.warning(f"⚠️ Cache miss for trending matches - querying database")
        db_matches = await get_trending_matches_from_db(timeframe=timeframe, league_id=league_id, limit=limit)
        
        return {
            "matches": db_matches,
            "meta": {
                "cache_hit": False,
                "timeframe": timeframe,
                "count": len(db_matches),
                "status": "database_fallback" if db_matches else "no_data",
                "note": "Data served from database (cache unavailable)" if db_matches else "No trending scores available yet",
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
        # Check database status
        db_hot_matches = []
        db_trending_matches = []
        
        if db_engine:
            try:
                db_hot_matches = await get_hot_matches_from_db(limit=20)
                db_trending_matches = await get_trending_matches_from_db(limit=20)
            except Exception as e:
                logger.warning(f"⚠️ Could not query database: {e}")
        
        # Check Redis status
        if not redis_client:
            return {
                "status": "degraded",
                "source": "database_only",
                "hot_matches_available": len(db_hot_matches),
                "trending_matches_available": len(db_trending_matches),
                "cache_health": "offline",
                "message": "Redis cache offline, serving from database",
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
            "source": "redis_cache",
            "hot_matches_cached": len(hot_cache) if hot_cache else 0,
            "trending_matches_cached": len(trending_cache) if trending_cache else 0,
            "hot_matches_db_available": len(db_hot_matches),
            "trending_matches_db_available": len(db_trending_matches),
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
