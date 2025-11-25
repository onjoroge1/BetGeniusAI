"""
Trending Scores Model
Pre-computed hot and trending match scores for caching
"""
from sqlalchemy import Column, Integer, Float, DateTime, Index, create_engine
from sqlalchemy.orm import declarative_base
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

Base = declarative_base()


class TrendingScore(Base):
    """Pre-computed trending/hot scores for matches"""
    __tablename__ = "trending_scores"
    
    id = Column(Integer, primary_key=True)
    match_id = Column(Integer, unique=True, nullable=False, index=True)
    hot_score = Column(Float, default=0.0)  # 0-100
    trending_score = Column(Float, default=0.0)  # 0-100
    hot_rank = Column(Integer)  # 1-20
    trending_rank = Column(Integer)  # 1-20
    momentum_current = Column(Float, default=0.0)
    momentum_velocity = Column(Float, default=0.0)  # points per minute
    clv_signal_count = Column(Integer, default=0)
    prediction_disagreement = Column(Float, default=0.0)  # abs(v1-v2)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        Index('idx_trending_hot', 'hot_score'),
        Index('idx_trending_trending', 'trending_score'),
        Index('idx_trending_match', 'match_id'),
    )
    
    def to_dict(self):
        """Convert to dictionary for JSON serialization"""
        return {
            "match_id": self.match_id,
            "hot_score": round(self.hot_score, 2) if self.hot_score else 0.0,
            "trending_score": round(self.trending_score, 2) if self.trending_score else 0.0,
            "hot_rank": self.hot_rank,
            "trending_rank": self.trending_rank,
            "momentum": {
                "current": round(self.momentum_current, 1) if self.momentum_current else 0.0,
                "velocity": round(self.momentum_velocity, 2) if self.momentum_velocity else 0.0,
            },
            "clv_signals": self.clv_signal_count or 0,
            "prediction_disagreement": round(self.prediction_disagreement, 3) if self.prediction_disagreement else 0.0,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


def compute_hot_score(
    momentum: float,
    clv_alerts: int,
    disagreement: float,
    max_disagreement: float = 0.5
) -> float:
    """
    Calculate hot score (matches with immediate action/interest)
    
    Formula: momentum (40%) + CLV (30%) + disagreement (20%) + other (10%)
    Range: 0-100
    
    Args:
        momentum: Current momentum (0-100)
        clv_alerts: Number of CLV alerts in last 5 min
        disagreement: Absolute difference between V1 and V2 probabilities (0-1)
        max_disagreement: Maximum disagreement for normalization (default 0.5)
    
    Returns:
        Hot score (0-100)
    """
    # Normalize components to 0-1 range
    normalized_momentum = min(momentum / 100, 1.0) if momentum else 0.0
    normalized_clv = min(clv_alerts / 5, 1.0)  # 5+ alerts = max score
    normalized_disagreement = min(disagreement / max_disagreement, 1.0)
    
    # Weighted calculation
    score = (
        (normalized_momentum * 0.40) +
        (normalized_clv * 0.30) +
        (normalized_disagreement * 0.20) +
        (0.1)  # Base 10% for any match with data
    ) * 100
    
    return round(min(max(score, 0.0), 100.0), 2)


def compute_trending_score(
    momentum_velocity: float,
    odds_shift: float = 0.0,
    confidence_change: float = 0.0,
    max_velocity: float = 5.0,
    max_odds_shift: float = 10.0,
    max_confidence_change: float = 0.2
) -> float:
    """
    Calculate trending score (matches with growing interest)
    
    Formula: momentum velocity (40%) + odds shift (30%) + confidence change (20%) + other (10%)
    Range: 0-100
    
    Args:
        momentum_velocity: Change in momentum per minute
        odds_shift: Percentage shift in odds
        confidence_change: Change in prediction confidence
        max_velocity: Maximum velocity for normalization (default 5 pts/min)
        max_odds_shift: Maximum odds shift % for normalization (default 10%)
        max_confidence_change: Maximum confidence change for normalization (default 0.2)
    
    Returns:
        Trending score (0-100)
    """
    # Normalize to 0-1 range
    normalized_velocity = min(abs(momentum_velocity) / max_velocity, 1.0) if momentum_velocity else 0.0
    normalized_shift = min(abs(odds_shift) / max_odds_shift, 1.0) if odds_shift else 0.0
    normalized_confidence = min(abs(confidence_change) / max_confidence_change, 1.0) if confidence_change else 0.0
    
    # Weighted calculation
    score = (
        (normalized_velocity * 0.40) +
        (normalized_shift * 0.30) +
        (normalized_confidence * 0.20) +
        (0.1)  # Base 10%
    ) * 100
    
    return round(min(max(score, 0.0), 100.0), 2)


def calculate_disagreement(v1_probs: dict, v2_probs: dict) -> float:
    """
    Calculate disagreement between V1 and V2 predictions
    
    Args:
        v1_probs: V1 probabilities {"home": float, "draw": float, "away": float}
        v2_probs: V2 probabilities {"home": float, "draw": float, "away": float}
    
    Returns:
        Max absolute difference across outcomes
    """
    if not v1_probs or not v2_probs:
        return 0.0
    
    diffs = []
    for outcome in ["home", "draw", "away"]:
        v1_prob = v1_probs.get(outcome, 0.33)
        v2_prob = v2_probs.get(outcome, 0.33)
        diffs.append(abs(v1_prob - v2_prob))
    
    return max(diffs)
