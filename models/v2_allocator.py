"""
V2 Model Allocation Logic
Determines whether to use V2 Select (premium) or V2 Full (free) based on confidence
"""
import numpy as np
from typing import Dict, Tuple, Optional
import logging

logger = logging.getLogger(__name__)

class V2ModelAllocator:
    """
    Allocates matches to V2 Select (premium) vs V2 Full (free) tiers
    
    V2 Select:
    - High confidence (conf >= 0.62)
    - Positive EV vs market
    - Premium tier (paywall)
    - ~17% coverage, ~76% hit rate
    
    V2 Full:
    - All matches
    - Free tier
    - 100% coverage, ~53% accuracy
    """
    
    def __init__(
        self,
        min_confidence: float = 0.62,
        min_ev: float = 0.0,
        max_league_ece: float = 0.08
    ):
        """
        Args:
            min_confidence: Minimum V2 confidence for select tier
            min_ev: Minimum EV vs market for select tier
            max_league_ece: Maximum allowed league calibration error
        """
        self.min_confidence = min_confidence
        self.min_ev = min_ev
        self.max_league_ece = max_league_ece
        
        # League ECE values from calibration analysis
        self.league_ece = {
            'Premier League': 0.0089,
            'La Liga': 0.0095,
            'Serie A': 0.0102,
            'Bundesliga': 0.0087,
            'Ligue 1': 0.0098,
            'Eredivisie': 0.0156,
            'Primeira Liga': 0.0142,
            'Jupiler League': 0.0189,
            'Super Lig': 0.0167,
            'Scottish Championship': 0.1315  # High ECE, exclude from select
        }
    
    def calculate_conf_v2(self, v2_probs: Dict[str, float]) -> float:
        """
        Calculate V2 confidence (max probability)
        
        Args:
            v2_probs: Dict with keys 'home', 'draw', 'away'
        
        Returns:
            Confidence (0-1)
        """
        return max(v2_probs['home'], v2_probs['draw'], v2_probs['away'])
    
    def calculate_ev(
        self, 
        v2_probs: Dict[str, float],
        market_probs: Dict[str, float]
    ) -> float:
        """
        Calculate expected value vs market
        Simple EV = max(v2_probs) - max(market_probs)
        
        Positive EV means model sees value
        """
        conf_v2 = max(v2_probs['home'], v2_probs['draw'], v2_probs['away'])
        conf_market = max(market_probs['home'], market_probs['draw'], market_probs['away'])
        return conf_v2 - conf_market
    
    def is_eligible_league(self, league_name: str) -> bool:
        """Check if league meets calibration criteria"""
        ece = self.league_ece.get(league_name, 0.05)  # Default to 0.05 for unknown leagues
        return ece <= self.max_league_ece
    
    def allocate_model(
        self,
        v2_probs: Dict[str, float],
        market_probs: Dict[str, float],
        league_name: str,
        user_is_premium: bool = False,
        free_previews_used: int = 0
    ) -> Tuple[str, bool, Dict[str, any]]:
        """
        Allocate match to V2 Select or V2 Full
        
        Args:
            v2_probs: V2 model probabilities
            market_probs: Current market probabilities
            league_name: League name for calibration check
            user_is_premium: Whether user has premium access
            free_previews_used: How many free previews user has used today
        
        Returns:
            (model_type, premium_lock, metadata)
            - model_type: 'v2_select' or 'v2_full'
            - premium_lock: True if should be locked behind paywall
            - metadata: Dict with conf_v2, ev, etc.
        """
        # Calculate confidence and EV
        conf_v2 = self.calculate_conf_v2(v2_probs)
        ev = self.calculate_ev(v2_probs, market_probs)
        eligible_league = self.is_eligible_league(league_name)
        
        # Determine if this qualifies for V2 Select
        is_v2_select = (
            conf_v2 >= self.min_confidence and
            ev > self.min_ev and
            eligible_league
        )
        
        # Determine premium lock
        if is_v2_select:
            model_type = 'v2_select'
            
            # Premium users always get access
            if user_is_premium:
                premium_lock = False
            # Free users get limited previews
            elif free_previews_used < 2:
                premium_lock = False  # Allow preview
            else:
                premium_lock = True  # Lock behind paywall
        else:
            model_type = 'v2_full'
            premium_lock = False  # Free tier always unlocked
        
        metadata = {
            'conf_v2': float(conf_v2),
            'ev_live': float(ev),
            'eligible_league': eligible_league,
            'league_ece': self.league_ece.get(league_name, 0.05)
        }
        
        logger.info(
            f"Model allocation: {model_type} (conf={conf_v2:.3f}, "
            f"ev={ev:+.3f}, lock={premium_lock})"
        )
        
        return model_type, premium_lock, metadata
    
    def get_predicted_pick(self, v2_probs: Dict[str, float]) -> str:
        """Get predicted outcome from V2 probabilities"""
        if v2_probs['home'] >= max(v2_probs['draw'], v2_probs['away']):
            return 'home'
        elif v2_probs['away'] >= max(v2_probs['home'], v2_probs['draw']):
            return 'away'
        else:
            return 'draw'


# Singleton instance
_allocator = None

def get_allocator() -> V2ModelAllocator:
    """Get singleton allocator instance"""
    global _allocator
    if _allocator is None:
        _allocator = V2ModelAllocator()
    return _allocator
