"""
BetGenius AI Backend - Database Models and Operations
PostgreSQL database for persistent training data storage
"""

import os
import json
import uuid
import math
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Text, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB, UUID
import logging

logger = logging.getLogger(__name__)

Base = declarative_base()

class TrainingMatch(Base):
    """Database model for training match data"""
    __tablename__ = 'training_matches'
    
    id = Column(Integer, primary_key=True)
    match_id = Column(Integer, unique=True, nullable=False)
    league_id = Column(Integer, nullable=False)
    season = Column(Integer, nullable=False)
    
    # Match information
    home_team = Column(String(100), nullable=False)
    away_team = Column(String(100), nullable=False)
    home_team_id = Column(Integer)
    away_team_id = Column(Integer)
    match_date = Column(DateTime)
    venue = Column(String(200))
    
    # Match outcome (target variable)
    outcome = Column(String(10), nullable=False)  # 'Home', 'Draw', 'Away'
    home_goals = Column(Integer)
    away_goals = Column(Integer)
    
    # ML Features (stored as JSON for flexibility)
    features = Column(JSONB, nullable=False)
    
    # Metadata
    collected_at = Column(DateTime, default=datetime.now(timezone.utc))
    is_processed = Column(Boolean, default=True)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for ML training"""
        return {
            'match_id': self.match_id,
            'league_id': self.league_id,
            'season': self.season,
            'home_team': self.home_team,
            'away_team': self.away_team,
            'outcome': self.outcome,
            'features': self.features,
            'home_goals': self.home_goals,
            'away_goals': self.away_goals
        }

class PredictionSnapshot(Base):
    """Auto-logged prediction snapshots for accuracy tracking"""
    __tablename__ = 'prediction_snapshots'
    
    snapshot_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    match_id = Column(Integer, nullable=False, index=True)
    served_at = Column(DateTime, nullable=False, default=datetime.now(timezone.utc))
    kickoff_at = Column(DateTime, nullable=True)
    league = Column(String(50), nullable=True)
    model_version = Column(String(20), nullable=False, default="1.0.0")
    
    # Prediction probabilities
    probs_h = Column(Float, nullable=False)
    probs_d = Column(Float, nullable=False)  
    probs_a = Column(Float, nullable=False)
    confidence = Column(Float, nullable=False)
    tone = Column(String(20), nullable=False)  # "avoid", "lean", "confident"
    recommended = Column(String(100), nullable=False)
    
    # Performance metadata
    latency_ms = Column(Integer, nullable=True)
    overround_used = Column(Float, nullable=True)
    input_hash = Column(String(64), nullable=True)
    source = Column(String(50), nullable=False, default="api.predict.v2")
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'snapshot_id': str(self.snapshot_id),
            'match_id': self.match_id,
            'served_at': self.served_at.isoformat(),
            'kickoff_at': self.kickoff_at.isoformat() if self.kickoff_at is not None else None,
            'league': self.league,
            'model_version': self.model_version,
            'probs': {'H': self.probs_h, 'D': self.probs_d, 'A': self.probs_a},
            'confidence': self.confidence,
            'tone': self.tone,
            'recommended': self.recommended,
            'latency_ms': self.latency_ms
        }

class MatchResult(Base):
    """Final match results for accuracy computation"""
    __tablename__ = 'match_results'
    
    match_id = Column(Integer, primary_key=True)
    home_goals = Column(Integer, nullable=False)
    away_goals = Column(Integer, nullable=False)
    outcome = Column(String(1), nullable=False)  # 'H', 'D', 'A'
    finalized_at = Column(DateTime, nullable=False, default=datetime.now(timezone.utc))
    league = Column(String(50), nullable=True)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'match_id': self.match_id,
            'home_goals': self.home_goals,
            'away_goals': self.away_goals,
            'outcome': self.outcome,
            'finalized_at': self.finalized_at.isoformat()
        }

class MetricsPerMatch(Base):
    """Computed accuracy metrics per match"""
    __tablename__ = 'metrics_per_match'
    
    match_id = Column(Integer, primary_key=True)
    snapshot_id_eval = Column(UUID(as_uuid=True), nullable=False)
    brier = Column(Float, nullable=False)
    logloss = Column(Float, nullable=False)
    hit = Column(Integer, nullable=False)  # 0 or 1
    computed_at = Column(DateTime, nullable=False, default=datetime.now(timezone.utc))
    
    # Optional enhanced metrics
    league = Column(String(50), nullable=True)
    confidence_band = Column(String(20), nullable=True)  # "[0,0.15)", "[0.15,0.30)", "[0.30,1]"
    clv = Column(Float, nullable=True)  # Closing Line Value if available
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'match_id': self.match_id,
            'snapshot_id_eval': str(self.snapshot_id_eval),
            'brier': self.brier,
            'logloss': self.logloss,
            'hit': self.hit,
            'computed_at': self.computed_at.isoformat(),
            'league': self.league,
            'confidence_band': self.confidence_band,
            'clv': self.clv
        }

class Bookmaker(Base):
    """Bookmaker metadata with desk group for independence filtering"""
    __tablename__ = 'bookmakers'
    
    bookmaker_id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    desk_group = Column(String(100), nullable=False)  # For deduplication
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now(timezone.utc))
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'bookmaker_id': self.bookmaker_id,
            'name': self.name,
            'desk_group': self.desk_group,
            'is_active': self.is_active
        }

class CLVAlert(Base):
    """Live CLV opportunities with expiration"""
    __tablename__ = 'clv_alerts'
    
    alert_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    match_id = Column(Integer, nullable=False, index=True)
    league = Column(String(50), nullable=False)
    outcome = Column(String(1), nullable=False)  # 'H', 'D', 'A'
    best_book_id = Column(Integer, nullable=False)
    best_odds_dec = Column(Float, nullable=False)
    market_odds_dec = Column(Float, nullable=False)  # De-juiced composite
    clv_pct = Column(Float, nullable=False)  # ((best - composite) / composite)*100
    stability = Column(Float, nullable=False)  # 0..1
    books_used = Column(Integer, nullable=False)
    window_tag = Column(String(20), nullable=False)  # T-72to48, T-48to24, etc.
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.now(timezone.utc), index=True)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'alert_id': str(self.alert_id),
            'match_id': self.match_id,
            'league': self.league,
            'outcome': self.outcome,
            'best_odds': self.best_odds_dec,
            'best_book_id': self.best_book_id,
            'market_composite_odds': self.market_odds_dec,
            'clv_pct': self.clv_pct,
            'stability': self.stability,
            'books_used': self.books_used,
            'window': self.window_tag,
            'composite_method': 'trim_10_dejuiced',  # 10% trim + de-juicing
            'closing_method': 'LAST5_VWAP',  # Phase 2 - not yet active
            'expires_at': self.expires_at.isoformat(),
            'created_at': self.created_at.isoformat()
        }

class CLVClosingFeed(Base):
    """Raw closing samples near kickoff for audit and closing line computation"""
    __tablename__ = 'clv_closing_feed'
    
    match_id = Column(Integer, primary_key=True, nullable=False)
    ts = Column(DateTime, primary_key=True, nullable=False)
    outcome = Column(String(1), primary_key=True, nullable=False)  # 'H', 'D', 'A'
    composite_odds_dec = Column(Float, nullable=False)
    volume = Column(Float, nullable=True)  # NULL if unknown
    books_used = Column(Integer, nullable=False)  # Independent desk groups
    desk_groups = Column(Integer, nullable=False)  # Same as books_used
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'match_id': self.match_id,
            'ts': self.ts.isoformat(),
            'outcome': self.outcome,
            'composite_odds_dec': self.composite_odds_dec,
            'volume': self.volume,
            'books_used': self.books_used,
            'desk_groups': self.desk_groups
        }

class CLVRealized(Base):
    """Settled CLV alerts vs closing line and result"""
    __tablename__ = 'clv_realized'
    
    alert_id = Column(UUID(as_uuid=True), primary_key=True)
    closing_odds_dec = Column(Float, nullable=False)
    realized_clv_pct = Column(Float, nullable=False)
    settled_at = Column(DateTime, nullable=False, default=datetime.now(timezone.utc))
    match_outcome = Column(String(1), nullable=False)  # 'H', 'D', 'A'
    win = Column(Boolean, nullable=False)
    closing_quality = Column(JSONB, nullable=True)  # {samples, window_sec, method_used}
    
    # Phase 2: Explicit closing fields for better queryability
    closing_method = Column(String(20), nullable=True)  # "LAST5_VWAP" | "LAST_TICK"
    closing_samples = Column(Integer, nullable=True)  # Number of samples used
    closing_window_sec = Column(Integer, nullable=True)  # Typically 300
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'alert_id': str(self.alert_id),
            'closing_odds_dec': self.closing_odds_dec,
            'realized_clv_pct': self.realized_clv_pct,
            'settled_at': self.settled_at.isoformat(),
            'match_outcome': self.match_outcome,
            'win': self.win,
            'closing_quality': self.closing_quality,
            'closing_method': self.closing_method,
            'closing_samples': self.closing_samples,
            'closing_window_sec': self.closing_window_sec
        }

class DatabaseManager:
    """Database operations for training data"""
    
    def __init__(self):
        self.database_url = os.environ.get('DATABASE_URL')
        if not self.database_url:
            raise ValueError("DATABASE_URL environment variable is required")
        
        # Add connection pooling and SSL error handling
        self.engine = create_engine(
            self.database_url,
            pool_pre_ping=True,
            pool_recycle=300,
            connect_args={"sslmode": "prefer"}
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        
        # Create tables if they don't exist
        Base.metadata.create_all(bind=self.engine)
        logger.info("Database tables initialized")
    
    def save_training_match(self, match_data: Dict[str, Any]) -> bool:
        """Save single training match to database"""
        session = None
        try:
            session = self.SessionLocal()
            
            # Check if match already exists
            existing = session.query(TrainingMatch).filter_by(
                match_id=match_data['match_id']
            ).first()
            
            if existing:
                logger.debug(f"Match {match_data['match_id']} already exists, skipping")
                session.close()
                return False
            
            # Create new training match
            training_match = TrainingMatch(
                match_id=match_data['match_id'],
                league_id=match_data.get('league_id', 0),
                season=match_data.get('season', 2023),
                home_team=match_data['home_team'],
                away_team=match_data['away_team'],
                home_team_id=match_data.get('home_team_id'),
                away_team_id=match_data.get('away_team_id'),
                match_date=match_data.get('match_date'),
                venue=match_data.get('venue'),
                outcome=match_data['outcome'],
                home_goals=match_data.get('home_goals'),
                away_goals=match_data.get('away_goals'),
                features=match_data['features']
            )
            
            session.add(training_match)
            session.commit()
            session.close()
            
            logger.debug(f"Saved training match {match_data['match_id']}")
            return True
            
        except Exception as e:
            logger.error(f"Error saving training match {match_data.get('match_id', 'unknown')}: {e}")
            if session:
                session.rollback()
                session.close()
            return False
    
    def save_training_matches_batch(self, matches: List[Dict[str, Any]]) -> int:
        """Save multiple training matches in batch with dual-table population"""
        saved_count = 0
        new_matches = []
        session = self.SessionLocal()
        
        try:
            for match_data in matches:
                # Check if match already exists
                existing = session.query(TrainingMatch).filter_by(
                    match_id=match_data['match_id']
                ).first()
                
                if existing:
                    continue
                
                # Create new training match
                training_match = TrainingMatch(
                    match_id=match_data['match_id'],
                    league_id=match_data.get('league_id', 0),
                    season=match_data.get('season', 2023),
                    home_team=match_data['home_team'],
                    away_team=match_data['away_team'],
                    home_team_id=match_data.get('home_team_id'),
                    away_team_id=match_data.get('away_team_id'),
                    match_date=match_data.get('match_date'),
                    venue=match_data.get('venue'),
                    outcome=match_data['outcome'],
                    home_goals=match_data.get('home_goals'),
                    away_goals=match_data.get('away_goals'),
                    features=match_data['features']
                )
                
                session.add(training_match)
                new_matches.append(match_data)
                saved_count += 1
            
            session.commit()
            logger.info(f"Saved {saved_count} training matches to database")
            
        except Exception as e:
            logger.error(f"Error saving training matches batch: {e}")
            session.rollback()
            saved_count = 0
        finally:
            session.close()
        
        # DUAL-TABLE POPULATION: Also save to odds_consensus
        if new_matches and saved_count > 0:
            consensus_saved = self.save_odds_consensus_batch(new_matches)
            logger.info(f"DUAL-TABLE: Also saved {consensus_saved} matches to odds_consensus")
        
        return saved_count
    
    def save_odds_consensus_batch(self, matches: List[Dict[str, Any]]) -> int:
        """Save completed matches to odds_consensus table for cross-table consistency"""
        saved_count = 0
        
        try:
            # Use raw SQL connection for odds_consensus table (not SQLAlchemy ORM)
            import psycopg2
            conn = psycopg2.connect(self.database_url)
            cursor = conn.cursor()
            
            for match_data in matches:
                match_id = match_data['match_id']
                
                # Check if match already exists in odds_consensus
                cursor.execute("SELECT 1 FROM odds_consensus WHERE match_id = %s LIMIT 1", (match_id,))
                existing = cursor.fetchone()
                
                if existing:
                    continue  # Skip if already exists
                
                # Create T-72h consensus entry for completed match
                # Use simple consensus from match outcome for historical data
                if match_data['outcome'] == 'Home':
                    ph_cons, pd_cons, pa_cons = 0.65, 0.25, 0.10
                elif match_data['outcome'] == 'Away': 
                    ph_cons, pd_cons, pa_cons = 0.10, 0.25, 0.65
                else:  # Draw
                    ph_cons, pd_cons, pa_cons = 0.30, 0.40, 0.30
                
                # Insert into odds_consensus table
                insert_sql = """
                    INSERT INTO odds_consensus 
                    (match_id, horizon_hours, ts_effective, ph_cons, pd_cons, pa_cons,
                     disph, dispd, dispa, n_books, market_margin_avg, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """
                
                values = (
                    match_id,
                    72,  # T-72h horizon for completed matches
                    match_data.get('match_date', datetime.now(timezone.utc)),
                    float(ph_cons), float(pd_cons), float(pa_cons),
                    0.05, 0.05, 0.05,  # Low dispersion for historical
                    4,  # Assume 4 bookmakers
                    0.05,  # 5% margin
                    datetime.now(timezone.utc)
                )
                
                cursor.execute(insert_sql, values)
                saved_count += 1
            
            conn.commit()
            cursor.close()
            conn.close()
            
            logger.info(f"Saved {saved_count} matches to odds_consensus table")
            
        except Exception as e:
            logger.error(f"Error saving odds consensus batch: {e}")
            if 'conn' in locals():
                conn.rollback()
                cursor.close()
                conn.close()
            saved_count = 0
        
        return saved_count
    
    def refresh_odds_consensus_from_snapshots(self, lookback_minutes: int = 10) -> int:
        """
        Refresh odds_consensus table from recent odds_snapshots for upcoming matches
        This ensures predictions and CLV alerts have fresh consensus data
        
        Args:
            lookback_minutes: How far back to look for fresh odds (default: 10min)
            
        Returns:
            Number of consensus rows refreshed
        """
        refreshed_count = 0
        
        try:
            import psycopg2
            import time
            
            # Retry logic for transient connection failures (IPv6 issues)
            max_retries = 3
            retry_delay = 2
            conn = None
            
            for attempt in range(max_retries):
                try:
                    conn = psycopg2.connect(self.database_url, connect_timeout=10)
                    break  # Connection successful
                except psycopg2.OperationalError as e:
                    if attempt < max_retries - 1:
                        logger.warning(f"🔄 [CONSENSUS REFRESH] Connection attempt {attempt + 1} failed, retrying in {retry_delay}s...")
                        time.sleep(retry_delay)
                        retry_delay *= 2  # Exponential backoff
                    else:
                        raise  # Re-raise on final attempt
            
            if conn is None:
                logger.error("❌ [CONSENSUS REFRESH] Could not establish database connection")
                return 0
            cursor = conn.cursor()
            
            # Find upcoming matches with recent odds
            # Aggregate bookmaker odds using median (robust to outliers)
            refresh_sql = """
                WITH upcoming_matches AS (
                    SELECT DISTINCT os.match_id
                    FROM odds_snapshots os
                    JOIN fixtures f ON os.match_id = f.match_id
                    WHERE os.ts_snapshot > NOW() - INTERVAL '%s minutes'
                      AND f.kickoff_at > NOW()
                      AND f.kickoff_at < NOW() + INTERVAL '168 hours'
                      AND f.status IN ('NS', 'scheduled')
                ),
                aggregated_odds AS (
                    SELECT 
                        os.match_id,
                        -- Use PERCENTILE_CONT for median (more robust than AVG)
                        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY 
                            CASE WHEN os.outcome = 'H' THEN os.implied_prob END
                        ) FILTER (WHERE os.outcome = 'H') as ph_cons,
                        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY 
                            CASE WHEN os.outcome = 'D' THEN os.implied_prob END
                        ) FILTER (WHERE os.outcome = 'D') as pd_cons,
                        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY 
                            CASE WHEN os.outcome = 'A' THEN os.implied_prob END
                        ) FILTER (WHERE os.outcome = 'A') as pa_cons,
                        -- Calculate dispersion (STDDEV) for market quality
                        STDDEV(CASE WHEN os.outcome = 'H' THEN os.implied_prob END) 
                            FILTER (WHERE os.outcome = 'H') as disph,
                        STDDEV(CASE WHEN os.outcome = 'D' THEN os.implied_prob END) 
                            FILTER (WHERE os.outcome = 'D') as dispd,
                        STDDEV(CASE WHEN os.outcome = 'A' THEN os.implied_prob END) 
                            FILTER (WHERE os.outcome = 'A') as dispa,
                        COUNT(DISTINCT os.book_id) as n_books,
                        AVG(os.market_margin) as market_margin_avg,
                        MAX(f.kickoff_at) as kickoff_at
                    FROM odds_snapshots os
                    JOIN fixtures f ON os.match_id = f.match_id
                    WHERE os.match_id IN (SELECT match_id FROM upcoming_matches)
                      AND os.ts_snapshot > NOW() - INTERVAL '%s minutes'
                      AND os.outcome IN ('H', 'D', 'A')
                    GROUP BY os.match_id
                    HAVING COUNT(DISTINCT CASE WHEN os.outcome IN ('H','D','A') THEN os.book_id END) >= 2
                )
                INSERT INTO odds_consensus 
                (match_id, horizon_hours, ts_effective, ph_cons, pd_cons, pa_cons,
                 disph, dispd, dispa, n_books, market_margin_avg, created_at)
                SELECT 
                    match_id,
                    EXTRACT(EPOCH FROM (kickoff_at - NOW())) / 3600 as horizon_hours,
                    NOW() as ts_effective,
                    ph_cons,
                    pd_cons,
                    pa_cons,
                    COALESCE(disph, 0.02) as disph,
                    COALESCE(dispd, 0.015) as dispd,
                    COALESCE(dispa, 0.02) as dispa,
                    n_books,
                    COALESCE(market_margin_avg, 0.065) as market_margin_avg,
                    NOW() as created_at
                FROM aggregated_odds
                WHERE ph_cons IS NOT NULL 
                  AND pd_cons IS NOT NULL 
                  AND pa_cons IS NOT NULL
                ON CONFLICT (match_id) 
                DO UPDATE SET
                    horizon_hours = EXCLUDED.horizon_hours,
                    ts_effective = EXCLUDED.ts_effective,
                    ph_cons = EXCLUDED.ph_cons,
                    pd_cons = EXCLUDED.pd_cons,
                    pa_cons = EXCLUDED.pa_cons,
                    disph = EXCLUDED.disph,
                    dispd = EXCLUDED.dispd,
                    dispa = EXCLUDED.dispa,
                    n_books = EXCLUDED.n_books,
                    market_margin_avg = EXCLUDED.market_margin_avg,
                    created_at = EXCLUDED.created_at
            """
            
            cursor.execute(refresh_sql % (lookback_minutes, lookback_minutes))
            refreshed_count = cursor.rowcount
            
            conn.commit()
            cursor.close()
            conn.close()
            
            if refreshed_count > 0:
                logger.info(f"🔄 [CONSENSUS REFRESH] Updated {refreshed_count} odds_consensus rows from snapshots")
            else:
                logger.debug(f"🔄 [CONSENSUS REFRESH] No consensus updates needed (lookback: {lookback_minutes}min)")
            
        except Exception as e:
            logger.error(f"❌ [CONSENSUS REFRESH] Error refreshing consensus: {e}")
            if 'conn' in locals():
                conn.rollback()
                cursor.close()
                conn.close()
            refreshed_count = 0
        
        return refreshed_count
    
    def load_training_data(self, league_ids: Optional[List[int]] = None, 
                          seasons: Optional[List[int]] = None) -> List[Dict[str, Any]]:
        """Load training data from database"""
        try:
            session = self.SessionLocal()
            
            query = session.query(TrainingMatch)
            
            if league_ids:
                query = query.filter(TrainingMatch.league_id.in_(league_ids))
            
            if seasons:
                query = query.filter(TrainingMatch.season.in_(seasons))
            
            matches = query.all()
            
            training_data = [match.to_dict() for match in matches]
            session.close()
            
            logger.info(f"Loaded {len(training_data)} training matches from database")
            return training_data
            
        except Exception as e:
            logger.error(f"Error loading training data: {e}")
            return []
    
    def get_training_stats(self) -> Dict[str, Any]:
        """Get comprehensive training data statistics"""
        try:
            session = self.SessionLocal()
            
            total_matches = session.query(TrainingMatch).count()
            
            # League distribution
            league_stats = session.query(
                TrainingMatch.league_id,
                TrainingMatch.league_id.label('league'),
            ).distinct().all()
            
            # Outcome distribution
            outcome_stats = {}
            for outcome in ['Home', 'Draw', 'Away']:
                count = session.query(TrainingMatch).filter_by(outcome=outcome).count()
                outcome_stats[outcome] = count
            
            # Season distribution
            season_stats = {}
            seasons = session.query(TrainingMatch.season).distinct().all()
            for season_tuple in seasons:
                season = season_tuple[0]
                count = session.query(TrainingMatch).filter_by(season=season).count()
                season_stats[str(season)] = count
            
            session.close()
            
            # Map league IDs to names
            league_names = {
                39: "Premier League",
                140: "La Liga", 
                78: "Bundesliga",
                135: "Serie A"
            }
            
            leagues = [league_names.get(ls.league_id, f"League {ls.league_id}") for ls in league_stats]
            
            return {
                "total_samples": total_matches,
                "leagues": leagues,
                "outcomes": outcome_stats,
                "seasons": season_stats,
                "last_updated": datetime.now(timezone.utc).isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error getting training stats: {e}")
            return {
                "total_samples": 0,
                "leagues": [],
                "outcomes": {},
                "seasons": {},
                "error": str(e)
            }
    
    def clear_training_data(self, league_id: Optional[int] = None) -> int:
        """Clear training data (for testing/maintenance)"""
        try:
            session = self.SessionLocal()
            
            if league_id:
                deleted = session.query(TrainingMatch).filter_by(league_id=league_id).delete()
            else:
                deleted = session.query(TrainingMatch).delete()
            
            session.commit()
            session.close()
            
            logger.info(f"Cleared {deleted} training matches from database")
            return deleted
            
        except Exception as e:
            logger.error(f"Error clearing training data: {e}")
            return 0
    
    def get_recent_matches(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get most recently collected matches"""
        try:
            session = self.SessionLocal()
            
            matches = session.query(TrainingMatch).order_by(
                TrainingMatch.collected_at.desc()
            ).limit(limit).all()
            
            recent_data = [match.to_dict() for match in matches]
            session.close()
            
            return recent_data
            
        except Exception as e:
            logger.error(f"Error getting recent matches: {e}")
            return []
    
    # ===== ACCURACY TRACKING METHODS =====
    
    def log_prediction_snapshot(self, prediction_data: Dict[str, Any]) -> str:
        """Auto-log prediction snapshot for accuracy tracking (100% backend-driven)"""
        try:
            session = self.SessionLocal()
            
            snapshot = PredictionSnapshot(
                match_id=prediction_data['match_id'],
                served_at=datetime.now(timezone.utc),
                kickoff_at=prediction_data.get('kickoff_at'),
                league=prediction_data.get('league'),
                model_version=prediction_data.get('model_version', '1.0.0'),
                probs_h=prediction_data['probs_h'],
                probs_d=prediction_data['probs_d'], 
                probs_a=prediction_data['probs_a'],
                confidence=prediction_data['confidence'],
                tone=prediction_data['tone'],
                recommended=prediction_data['recommended'],
                latency_ms=prediction_data.get('latency_ms'),
                overround_used=prediction_data.get('overround_used'),
                input_hash=prediction_data.get('input_hash'),
                source=prediction_data.get('source', 'api.predict.v2')
            )
            
            session.add(snapshot)
            session.commit()
            snapshot_id = str(snapshot.snapshot_id)
            session.close()
            
            logger.debug(f"📊 Logged prediction snapshot {snapshot_id} for match {prediction_data['match_id']}")
            return snapshot_id
            
        except Exception as e:
            logger.error(f"Error logging prediction snapshot: {e}")
            if 'session' in locals():
                session.rollback()
                session.close()
            return ""
    
    def save_match_result(self, result_data: Dict[str, Any]) -> bool:
        """Save final match result for accuracy computation"""
        try:
            session = self.SessionLocal()
            
            # Check if result already exists
            existing = session.query(MatchResult).filter_by(match_id=result_data['match_id']).first()
            if existing:
                logger.debug(f"Match result {result_data['match_id']} already exists")
                session.close()
                return False
            
            # Determine outcome from goals
            home_goals = result_data['home_goals']
            away_goals = result_data['away_goals']
            if home_goals > away_goals:
                outcome = 'H'
            elif away_goals > home_goals:
                outcome = 'A'
            else:
                outcome = 'D'
            
            result = MatchResult(
                match_id=result_data['match_id'],
                home_goals=home_goals,
                away_goals=away_goals,
                outcome=outcome,
                finalized_at=result_data.get('finalized_at', datetime.now(timezone.utc)),
                league=result_data.get('league')
            )
            
            session.add(result)
            session.commit()
            session.close()
            
            logger.info(f"📊 Saved match result {result_data['match_id']}: {outcome} ({home_goals}-{away_goals})")
            return True
            
        except Exception as e:
            logger.error(f"Error saving match result: {e}")
            if 'session' in locals():
                session.rollback()
                session.close()
            return False
    
    def compute_accuracy_metrics(self, force_recompute: bool = False) -> int:
        """Compute accuracy metrics for matches with results (joining snapshots ↔ results)"""
        computed_count = 0
        
        try:
            session = self.SessionLocal()
            
            # Find matches with results but no computed metrics (or force recompute)
            if force_recompute:
                # Get all match results
                results_query = session.query(MatchResult)
            else:
                # Only compute for matches without existing metrics
                results_query = session.query(MatchResult).filter(
                    ~MatchResult.match_id.in_(
                        session.query(MetricsPerMatch.match_id)
                    )
                )
            
            results = results_query.all()
            
            for result in results:
                match_id = result.match_id
                
                # Find the evaluation snapshot (latest before finalization)
                snapshot = session.query(PredictionSnapshot).filter(
                    PredictionSnapshot.match_id == match_id,
                    PredictionSnapshot.served_at <= result.finalized_at
                ).order_by(PredictionSnapshot.served_at.desc()).first()
                
                if not snapshot:
                    logger.warning(f"No prediction snapshot found for match {match_id}")
                    continue
                
                # Compute accuracy metrics
                # Multi-class Brier: ((pH-yH)^2 + (pD-yD)^2 + (pA-yA)^2) / 3
                yH = 1.0 if result.outcome == 'H' else 0.0
                yD = 1.0 if result.outcome == 'D' else 0.0
                yA = 1.0 if result.outcome == 'A' else 0.0
                
                brier = ((snapshot.probs_h - yH)**2 + (snapshot.probs_d - yD)**2 + (snapshot.probs_a - yA)**2) / 3.0
                
                # LogLoss: -ln(p_true)
                p_true = snapshot.probs_h if result.outcome == 'H' else (
                    snapshot.probs_d if result.outcome == 'D' else snapshot.probs_a
                )
                logloss = -1.0 * math.log(max(p_true, 1e-15))  # Avoid log(0)
                
                # Hit rate: argmax(probs) == outcome
                predicted_outcome = 'H' if snapshot.probs_h == max(snapshot.probs_h, snapshot.probs_d, snapshot.probs_a) else (
                    'D' if snapshot.probs_d == max(snapshot.probs_h, snapshot.probs_d, snapshot.probs_a) else 'A'
                )
                hit = 1 if predicted_outcome == result.outcome else 0
                
                # Confidence band
                confidence_band = (
                    "[0,0.15)" if snapshot.confidence < 0.15 else
                    "[0.15,0.30)" if snapshot.confidence < 0.30 else
                    "[0.30,1]"
                )
                
                # Delete existing metrics if force recompute
                if force_recompute:
                    session.query(MetricsPerMatch).filter_by(match_id=match_id).delete()
                
                # Save computed metrics
                metrics = MetricsPerMatch(
                    match_id=match_id,
                    snapshot_id_eval=snapshot.snapshot_id,
                    brier=brier,
                    logloss=logloss,
                    hit=hit,
                    computed_at=datetime.now(timezone.utc),
                    league=result.league,
                    confidence_band=confidence_band
                )
                
                session.add(metrics)
                computed_count += 1
            
            session.commit()
            session.close()
            
            logger.info(f"📊 Computed accuracy metrics for {computed_count} matches")
            return computed_count
            
        except Exception as e:
            logger.error(f"Error computing accuracy metrics: {e}")
            if 'session' in locals():
                session.rollback()
                session.close()
            return 0