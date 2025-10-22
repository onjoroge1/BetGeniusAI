"""
Metrics utilities for normalization and validation.
"""
from typing import Tuple


def normalize_triplet(p_home: float, p_draw: float, p_away: float) -> Tuple[float, float, float]:
    """
    Normalize probability triplet to sum to 1.0.
    
    Args:
        p_home: Home win probability
        p_draw: Draw probability
        p_away: Away win probability
    
    Returns:
        Tuple of normalized probabilities (p_home, p_draw, p_away)
    
    Examples:
        >>> normalize_triplet(0.5234, 0.3634, 0.3338)
        (0.4287, 0.2978, 0.2735)
        
        >>> normalize_triplet(0.4, 0.3, 0.3)
        (0.4, 0.3, 0.3)
    """
    total = max(1e-9, p_home + p_draw + p_away)
    return (
        p_home / total,
        p_draw / total,
        p_away / total
    )


def validate_probabilities(p_home: float, p_draw: float, p_away: float, tolerance: float = 0.01) -> bool:
    """
    Validate that probabilities are valid (non-negative, sum to ~1.0).
    
    Args:
        p_home: Home win probability
        p_draw: Draw probability
        p_away: Away win probability
        tolerance: Acceptable deviation from 1.0
    
    Returns:
        True if probabilities are valid, False otherwise
    """
    if p_home < 0 or p_draw < 0 or p_away < 0:
        return False
    
    total = p_home + p_draw + p_away
    return abs(total - 1.0) <= tolerance


def clamp_probability(p: float, min_val: float = 0.001, max_val: float = 0.999) -> float:
    """
    Clamp probability to valid range to avoid log(0) errors.
    
    Args:
        p: Probability value
        min_val: Minimum allowed value
        max_val: Maximum allowed value
    
    Returns:
        Clamped probability
    """
    return max(min_val, min(max_val, p))
