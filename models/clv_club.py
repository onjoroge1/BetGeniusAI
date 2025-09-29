"""
CLV Club - Professional Closing Line Value Detection
Implements robust consensus, de-juicing, stability metrics, and alert gating
"""

import os
import math
import statistics
import yaml
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
import logging

from utils.config import settings

logger = logging.getLogger(__name__)

@dataclass
class BookOdds:
    """Single bookmaker's 3-way odds"""
    book_id: int
    odds_h: float
    odds_d: float
    odds_a: float
    timestamp: datetime
    desk_group: str

@dataclass
class CLVOpportunityCandidate:
    """CLV opportunity before gating"""
    match_id: int
    league: str
    outcome: str  # 'H', 'D', 'A'
    best_book_id: int
    best_odds_dec: float
    market_odds_dec: float
    clv_pct: float
    stability: float
    books_used: int
    window_tag: str
    kickoff_time: datetime

class CLVClubEngine:
    """Core CLV Club computation engine"""
    
    def __init__(self):
        self.config = settings
        self.desk_group_overrides = self._load_desk_groups()
    
    def _load_desk_groups(self) -> Dict[int, str]:
        """Load desk group overrides from config/desk_groups.yaml"""
        try:
            desk_groups_file = 'config/desk_groups.yaml'
            if os.path.exists(desk_groups_file):
                with open(desk_groups_file, 'r') as f:
                    data = yaml.safe_load(f) or {}
                    return data.get('desk_groups', {})
        except Exception as e:
            logger.warning(f"Could not load desk_groups.yaml: {e}")
        
        # Default: each book is its own desk group
        return {}
    
    def get_desk_group(self, book_id: int) -> str:
        """Get desk group for bookmaker (for independence filtering)"""
        # Check override file first
        if book_id in self.desk_group_overrides:
            return self.desk_group_overrides[book_id]
        
        # Default: each book is independent
        return f"book_{book_id}"
    
    def dejuice_three_way(self, odds_h: float, odds_d: float, odds_a: float) -> Tuple[float, float, float]:
        """
        Remove overround from 3-way odds using proportional renormalization
        
        Args:
            odds_h, odds_d, odds_a: Decimal odds for Home, Draw, Away
            
        Returns:
            (pH, pD, pA): De-juiced probabilities that sum to 1.0
        """
        # Convert to implied probabilities
        p_h = 1.0 / max(1e-12, odds_h)
        p_d = 1.0 / max(1e-12, odds_d)
        p_a = 1.0 / max(1e-12, odds_a)
        
        # Remove overround by proportional renormalization
        total = max(1e-12, p_h + p_d + p_a)
        
        return p_h / total, p_d / total, p_a / total
    
    def robust_consensus(self, probs: List[float], trim_fraction: float = None) -> Optional[float]:
        """
        Compute robust consensus using trimmed mean
        
        Args:
            probs: List of probabilities from different books
            trim_fraction: Fraction to trim from each tail (default: CLV_TRIM_FRACTION)
            
        Returns:
            Trimmed mean, or None if insufficient data
        """
        if not probs:
            return None
        
        if len(probs) < 3:
            # Not enough for trimming, use simple mean
            return sum(probs) / len(probs)
        
        if trim_fraction is None:
            trim_fraction = self.config.CLV_TRIM_FRACTION
        
        # Sort and trim
        sorted_probs = sorted(probs)
        n = len(sorted_probs)
        trim_count = int(n * trim_fraction)
        
        # Trim from both ends
        if trim_count > 0:
            trimmed = sorted_probs[trim_count:-trim_count]
        else:
            trimmed = sorted_probs
        
        if not trimmed:
            trimmed = sorted_probs
        
        return sum(trimmed) / len(trimmed)
    
    def composite_from_books(self, books_probs: List[Dict[str, float]]) -> Dict[str, float]:
        """
        Build composite market odds from de-juiced book probabilities
        
        Args:
            books_probs: List of dicts with keys 'H', 'D', 'A' (de-juiced probs)
            
        Returns:
            {'H': pH, 'D': pD, 'A': pA} normalized composite
        """
        if not books_probs:
            return {'H': 0.0, 'D': 0.0, 'A': 0.0}
        
        # Gather probabilities by outcome
        h_probs = [b['H'] for b in books_probs]
        d_probs = [b['D'] for b in books_probs]
        a_probs = [b['A'] for b in books_probs]
        
        # Apply robust consensus to each outcome
        h = self.robust_consensus(h_probs)
        d = self.robust_consensus(d_probs)
        a = self.robust_consensus(a_probs)
        
        if h is None or d is None or a is None:
            return {'H': 0.0, 'D': 0.0, 'A': 0.0}
        
        # Renormalize to ensure sum = 1.0
        total = max(1e-12, h + d + a)
        
        return {
            'H': h / total,
            'D': d / total,
            'A': a / total
        }
    
    def calculate_stability(self, recent_probs: List[float]) -> float:
        """
        Calculate line stability metric (0..1) based on recent probability variance
        
        Args:
            recent_probs: List of composite probabilities over time for same outcome
            
        Returns:
            Stability score (0=unstable, 1=perfectly stable)
        """
        if len(recent_probs) < 3:
            # Insufficient history, assume stable
            return 1.0
        
        try:
            std = statistics.pstdev(recent_probs)
            
            # Exponential decay: ~3pp std → ~0.7 stability
            k = 60.0
            stability = math.exp(-k * std)
            
            return max(0.0, min(1.0, stability))
        except Exception as e:
            logger.warning(f"Stability calculation error: {e}")
            return 1.0
    
    def filter_stale_quotes(self, book_odds: List[BookOdds], current_time: datetime) -> List[BookOdds]:
        """
        Filter out stale bookmaker quotes
        
        Args:
            book_odds: List of BookOdds objects
            current_time: Reference time
            
        Returns:
            Filtered list with only fresh quotes
        """
        staleness_threshold = timedelta(seconds=self.config.CLV_STALENESS_SEC)
        
        fresh_quotes = []
        for odds in book_odds:
            age = current_time - odds.timestamp
            if age <= staleness_threshold:
                fresh_quotes.append(odds)
        
        return fresh_quotes
    
    def filter_independent_books(self, book_odds: List[BookOdds]) -> List[BookOdds]:
        """
        Keep only one quote per desk group (independence filtering)
        
        Args:
            book_odds: List of BookOdds objects
            
        Returns:
            Filtered list with one book per desk group (most recent)
        """
        # Group by desk_group
        desk_groups: Dict[str, BookOdds] = {}
        
        for odds in book_odds:
            desk = self.get_desk_group(odds.book_id)
            
            # Keep the most recent quote from each desk group
            if desk not in desk_groups or odds.timestamp > desk_groups[desk].timestamp:
                desk_groups[desk] = odds
        
        return list(desk_groups.values())
    
    def window_tag(self, kickoff_time: datetime, current_time: datetime) -> str:
        """
        Generate window tag based on time to kickoff
        
        Args:
            kickoff_time: Match kickoff time
            current_time: Current time
            
        Returns:
            Window tag like 'T-72to48', 'T-48to24', etc.
        """
        hours_to_kickoff = (kickoff_time - current_time).total_seconds() / 3600.0
        
        if 48 <= hours_to_kickoff <= 72:
            return "T-72to48"
        elif 24 <= hours_to_kickoff < 48:
            return "T-48to24"
        elif 8 <= hours_to_kickoff < 24:
            return "T-24to8"
        elif 1 <= hours_to_kickoff < 8:
            return "T-8to1"
        else:
            return "T-1to0"
    
    def calculate_clv_pct(self, best_odds: float, market_odds: float) -> float:
        """
        Calculate CLV percentage edge
        
        Args:
            best_odds: Best available decimal odds
            market_odds: De-juiced composite decimal odds
            
        Returns:
            CLV percentage: ((best - market) / market) * 100
        """
        return 100.0 * (best_odds - market_odds) / market_odds
    
    def calculate_alert_ttl(self, kickoff_time: datetime, current_time: datetime) -> int:
        """
        Calculate alert TTL in seconds based on proximity to kickoff
        
        Args:
            kickoff_time: Match kickoff time
            current_time: Current time
            
        Returns:
            TTL in seconds
        """
        seconds_to_kickoff = (kickoff_time - current_time).total_seconds()
        
        # Within 15 minutes of kickoff: shorter TTL
        if seconds_to_kickoff <= 900:  # 15 minutes
            return self.config.CLV_ALERT_TTL_NEAR_KO_SEC
        else:
            return self.config.CLV_ALERT_TTL_SEC
    
    def analyze_match_clv(
        self,
        match_id: int,
        league: str,
        kickoff_time: datetime,
        book_odds_list: List[BookOdds],
        historical_probs: Dict[str, List[float]] = None
    ) -> List[CLVOpportunityCandidate]:
        """
        Analyze CLV opportunities for a single match
        
        Args:
            match_id: Match ID
            league: League name
            kickoff_time: Kickoff datetime
            book_odds_list: List of BookOdds from various bookmakers
            historical_probs: Optional dict of recent probabilities per outcome for stability
            
        Returns:
            List of CLV opportunity candidates (before gating)
        """
        current_time = datetime.now(timezone.utc)
        
        # Step 1: Filter stale quotes
        fresh_odds = self.filter_stale_quotes(book_odds_list, current_time)
        
        if not fresh_odds:
            logger.debug(f"Match {match_id}: No fresh quotes")
            return []
        
        # Step 2: Filter for independence (one per desk group)
        independent_odds = self.filter_independent_books(fresh_odds)
        
        if len(independent_odds) < self.config.CLV_MIN_BOOKS_MINOR:
            logger.debug(f"Match {match_id}: Insufficient independent books ({len(independent_odds)})")
            return []
        
        # Step 3: De-juice all books
        dejuiced_books = []
        for odds in independent_odds:
            pH, pD, pA = self.dejuice_three_way(odds.odds_h, odds.odds_d, odds.odds_a)
            dejuiced_books.append({
                'book_id': odds.book_id,
                'H': pH,
                'D': pD,
                'A': pA,
                'odds_h': odds.odds_h,
                'odds_d': odds.odds_d,
                'odds_a': odds.odds_a
            })
        
        # Step 4: Compute composite market odds
        composite_probs = self.composite_from_books(dejuiced_books)
        
        # Step 5: Analyze each outcome for CLV opportunities
        opportunities = []
        
        for outcome in ['H', 'D', 'A']:
            outcome_key = outcome.lower()
            
            # Get composite probability and convert to odds
            composite_prob = composite_probs[outcome]
            if composite_prob <= 0:
                continue
            
            market_odds_dec = 1.0 / composite_prob
            
            # Find best available odds for this outcome
            best_odds_dec = 0.0
            best_book_id = None
            
            for book in dejuiced_books:
                if outcome == 'H':
                    book_odds = book['odds_h']
                elif outcome == 'D':
                    book_odds = book['odds_d']
                else:  # 'A'
                    book_odds = book['odds_a']
                
                if book_odds > best_odds_dec:
                    best_odds_dec = book_odds
                    best_book_id = book['book_id']
            
            if best_book_id is None:
                continue
            
            # Calculate CLV
            clv_pct = self.calculate_clv_pct(best_odds_dec, market_odds_dec)
            
            # Calculate stability
            if historical_probs and outcome in historical_probs:
                stability = self.calculate_stability(historical_probs[outcome])
            else:
                stability = 1.0  # Assume stable if no history
            
            # Window tag
            window = self.window_tag(kickoff_time, current_time)
            
            # Create opportunity candidate
            opportunity = CLVOpportunityCandidate(
                match_id=match_id,
                league=league,
                outcome=outcome,
                best_book_id=best_book_id,
                best_odds_dec=best_odds_dec,
                market_odds_dec=market_odds_dec,
                clv_pct=clv_pct,
                stability=stability,
                books_used=len(independent_odds),
                window_tag=window,
                kickoff_time=kickoff_time
            )
            
            opportunities.append(opportunity)
        
        return opportunities
    
    def should_emit_alert(self, opportunity: CLVOpportunityCandidate, is_major_league: bool = True) -> Tuple[bool, str]:
        """
        Gate CLV opportunity to determine if alert should be emitted
        
        Args:
            opportunity: CLVOpportunityCandidate to evaluate
            is_major_league: Whether this is a major league (affects min books threshold)
            
        Returns:
            (should_emit, reason): Boolean and human-readable reason
        """
        # Gate 1: Minimum books
        min_books = self.config.CLV_MIN_BOOKS_DEFAULT if is_major_league else self.config.CLV_MIN_BOOKS_MINOR
        
        if opportunity.books_used < min_books:
            return False, f"Insufficient books ({opportunity.books_used} < {min_books})"
        
        # Gate 2: Line stability
        if opportunity.stability < self.config.CLV_MIN_STABILITY:
            return False, f"Low stability ({opportunity.stability:.3f} < {self.config.CLV_MIN_STABILITY})"
        
        # Gate 3: CLV threshold
        if opportunity.clv_pct < self.config.CLV_MIN_CLV_PCT_BASIC:
            return False, f"CLV below threshold ({opportunity.clv_pct:.2f}% < {self.config.CLV_MIN_CLV_PCT_BASIC}%)"
        
        return True, "All gates passed"


# Utility functions
def implied_from_decimal(odds: float) -> float:
    """Convert decimal odds to implied probability"""
    return 1.0 / max(1e-12, odds)

def composite_odds_from_probs(p: float) -> float:
    """Convert probability to decimal odds"""
    return 1.0 / max(1e-12, p)

def clv_pct(best_odds_dec: float, composite_odds_dec: float) -> float:
    """Calculate CLV percentage"""
    return 100.0 * (best_odds_dec - composite_odds_dec) / composite_odds_dec
