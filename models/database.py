"""
BetGenius AI Backend - Database Models and Operations
PostgreSQL database for persistent training data storage
"""

import os
import json
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Text, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
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

class DatabaseManager:
    """Database operations for training data"""
    
    def __init__(self):
        self.database_url = os.environ.get('DATABASE_URL')
        if not self.database_url:
            raise ValueError("DATABASE_URL environment variable is required")
        
        self.engine = create_engine(self.database_url)
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
        """Save multiple training matches in batch"""
        saved_count = 0
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
                saved_count += 1
            
            session.commit()
            logger.info(f"Saved {saved_count} training matches to database")
            
        except Exception as e:
            logger.error(f"Error saving training matches batch: {e}")
            session.rollback()
            saved_count = 0
        finally:
            session.close()
        
        return saved_count
    
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