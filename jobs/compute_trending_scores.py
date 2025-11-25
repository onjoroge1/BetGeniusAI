"""
Compute Trending Scores Job
Pre-computes hot and trending scores every 5 minutes
Results cached in Redis for fast serving
"""
import asyncio
import logging
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import redis

logger = logging.getLogger(__name__)


async def compute_trending_scores_job():
    """
    Compute trending and hot scores every 5 minutes
    
    Process:
    1. Load live data (momentum, CLV, predictions)
    2. Calculate hot_score and trending_score for each match
    3. Rank top 20 for each category
    4. Cache in Redis with 5-minute TTL
    5. Update metadata
    """
    try:
        # Import here to avoid circular dependencies
        from sqlalchemy import create_engine, text
        import pandas as pd
        from models.trending_score import (
            TrendingScore, compute_hot_score, compute_trending_score, calculate_disagreement
        )
        
        logger.info("🔨 Starting trending scores computation...")
        start_time = datetime.utcnow()
        
        # Initialize database connection
        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            logger.error("❌ DATABASE_URL not set")
            return False
        
        engine = create_engine(db_url)
        
        # ===== STEP 1: Load live data =====
        logger.info("📊 Loading live data...")
        
        # Get current live momentum
        with engine.connect() as conn:
            momentum_query = text("""
                SELECT 
                    m.match_id,
                    (COALESCE(m.momentum_home, 50) + COALESCE(m.momentum_away, 50)) / 2.0 as momentum_current,
                    f.league_id,
                    f.kickoff_at
                FROM live_momentum m
                JOIN fixtures f ON m.match_id = f.match_id
                WHERE f.kickoff_at > NOW() - INTERVAL '24 hours'
                ORDER BY momentum_current DESC
            """)
            momentum_df = pd.read_sql(momentum_query, conn)
            logger.info(f"✅ Loaded {len(momentum_df)} matches with momentum data")
        
        if len(momentum_df) == 0:
            logger.warning("⚠️ No matches with momentum data - skipping computation")
            return False
        
        # Get CLV alerts (last 5 minutes)
        with engine.connect() as conn:
            clv_query = text("""
                SELECT 
                    match_id,
                    COUNT(*) as clv_count
                FROM clv_alerts
                WHERE created_at > NOW() - INTERVAL '5 minutes'
                GROUP BY match_id
            """)
            clv_df = pd.read_sql(clv_query, conn)
            logger.info(f"✅ Loaded CLV data for {len(clv_df)} matches")
        
        # Get predictions (V1: consensus predictions)
        with engine.connect() as conn:
            pred_query = text("""
                SELECT 
                    match_id,
                    consensus_h as v1_home,
                    consensus_d as v1_draw,
                    consensus_a as v1_away
                FROM consensus_predictions
                WHERE time_bucket = '24h'
                ORDER BY created_at DESC
            """)
            pred_df = pd.read_sql(pred_query, conn)
            logger.info(f"✅ Loaded predictions for {len(pred_df)} matches")
        
        # Get momentum velocity (change over last 5 minutes)
        with engine.connect() as conn:
            velocity_query = text("""
                SELECT 
                    m1.match_id,
                    CASE 
                        WHEN m2.match_id IS NOT NULL THEN
                            ((COALESCE(m1.momentum_home, 50) + COALESCE(m1.momentum_away, 50)) / 2.0 - 
                             (COALESCE(m2.momentum_home, 50) + COALESCE(m2.momentum_away, 50)) / 2.0) / 
                            NULLIF(EXTRACT(EPOCH FROM (m1.updated_at - m2.updated_at)) / 60, 0)
                        ELSE 0.0
                    END as velocity
                FROM live_momentum m1
                LEFT JOIN live_momentum m2 ON m1.match_id = m2.match_id 
                    AND m2.updated_at >= m1.updated_at - INTERVAL '5 minutes'
                    AND m2.updated_at < m1.updated_at
                WHERE m1.updated_at > NOW() - INTERVAL '24 hours'
            """)
            velocity_df = pd.read_sql(velocity_query, conn)
            logger.info(f"✅ Loaded velocity data for {len(velocity_df)} matches")
        
        # ===== STEP 2: Merge all data =====
        logger.info("🔗 Merging data...")
        
        # Merge all dataframes
        data = momentum_df.copy()
        data = data.merge(clv_df[["match_id", "clv_count"]], on="match_id", how="left")
        data = data.merge(pred_df[["match_id", "v1_home", "v1_draw", "v1_away"]], on="match_id", how="left")
        data = data.merge(velocity_df[["match_id", "velocity"]], on="match_id", how="left")
        
        # Fill NaN values
        data["clv_count"] = data["clv_count"].fillna(0).astype(int)
        data["velocity"] = data["velocity"].fillna(0.0)
        data["v1_home"] = data["v1_home"].fillna(0.33)
        data["v1_draw"] = data["v1_draw"].fillna(0.33)
        data["v1_away"] = data["v1_away"].fillna(0.33)
        
        logger.info(f"✅ Merged data for {len(data)} matches")
        
        # ===== STEP 3: Calculate scores =====
        logger.info("📈 Calculating scores...")
        
        scores_to_save = []
        
        for _, row in data.iterrows():
            match_id = int(row["match_id"])
            momentum = float(row["momentum_current"])
            clv_count = int(row["clv_count"])
            velocity = float(row["velocity"])
            
            # For now, set disagreement to 0 (V2 predictions not immediately available)
            disagreement = 0.0
            
            # Calculate scores
            hot_score = compute_hot_score(
                momentum=momentum,
                clv_alerts=clv_count,
                disagreement=disagreement
            )
            
            trending_score = compute_trending_score(
                momentum_velocity=velocity,
                odds_shift=0.0,
                confidence_change=0.0
            )
            
            # Create score object
            score = TrendingScore(
                match_id=match_id,
                hot_score=hot_score,
                trending_score=trending_score,
                momentum_current=momentum,
                momentum_velocity=velocity,
                clv_signal_count=clv_count,
                prediction_disagreement=disagreement,
                updated_at=datetime.utcnow()
            )
            
            scores_to_save.append(score)
        
        logger.info(f"✅ Calculated scores for {len(scores_to_save)} matches")
        
        # ===== STEP 4: Rank and save to database =====
        logger.info("💾 Saving scores to database...")
        
        from sqlalchemy.orm import Session
        
        # Sort for ranking
        scores_by_hot = sorted(scores_to_save, key=lambda x: x.hot_score, reverse=True)
        scores_by_trending = sorted(scores_to_save, key=lambda x: x.trending_score, reverse=True)
        
        # Assign ranks
        for i, score in enumerate(scores_by_hot):
            score.hot_rank = i + 1
        
        for i, score in enumerate(scores_by_trending):
            score.trending_rank = i + 1
        
        # Save to database and serialize WHILE in session
        top_hot = []
        top_trending = []
        with Session(engine) as session:
            # Delete old scores
            session.query(TrendingScore).delete()
            session.commit()
            
            # Bulk save
            session.add_all(scores_to_save)
            session.commit()
            logger.info(f"✅ Saved {len(scores_to_save)} scores to database")
            
            # Convert to dicts WHILE still in session (BEFORE session closes)
            top_hot = [s.to_dict() for s in scores_by_hot[:20]]
            top_trending = [s.to_dict() for s in scores_by_trending[:20]]
        
        # ===== STEP 5: Cache results =====
        logger.info("⚡ Caching results in Redis...")
        
        try:
            redis_host = os.getenv("REDIS_HOST", "localhost")
            redis_port = int(os.getenv("REDIS_PORT", 6379))
            redis_client = redis.Redis(
                host=redis_host,
                port=redis_port,
                decode_responses=True,
                socket_connect_timeout=2
            )
            
            # Cache with 5-minute TTL
            redis_client.setex("trending:hot:None:20", 300, json.dumps(top_hot))
            redis_client.setex("trending:trending:5m:None:20", 300, json.dumps(top_trending))
            
            # Cache metadata
            meta = {
                "updated_at": datetime.utcnow().isoformat(),
                "hot_count": len(top_hot),
                "trending_count": len(top_trending),
                "total_matches": len(scores_to_save)
            }
            redis_client.setex("trending:meta", 300, json.dumps(meta))
            
            logger.info(f"✅ Cached {len(top_hot)} hot matches and {len(top_trending)} trending matches")
        
        except Exception as e:
            logger.warning(f"⚠️ Redis caching failed: {e} - scores available in database")
        
        # ===== COMPLETE =====
        elapsed = (datetime.utcnow() - start_time).total_seconds()
        logger.info(f"✅ Trending scores computation completed in {elapsed:.2f}s")
        logger.info(f"   📊 {len(scores_to_save)} matches processed")
        
        # Get top scores from dicts (avoid detached session issues)
        if top_hot:
            logger.info(f"   🔥 Top hot score: {top_hot[0].get('hot_score', 0):.1f}")
        if top_trending:
            logger.info(f"   📈 Top trending score: {top_trending[0].get('trending_score', 0):.1f}")
        
        return True
    
    except Exception as e:
        logger.error(f"❌ Trending scores computation failed: {e}", exc_info=True)
        return False
