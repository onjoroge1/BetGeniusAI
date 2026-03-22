"""
Betting Intelligence: CLV, Edge, and Kelly Criterion Calculations

Provides utility functions for:
- Computing Closing Line Value (CLV) / Edge
- Kelly Criterion bet sizing
- Expected Value (EV) calculations
- Market probability normalization
"""

from typing import Dict, Optional, Tuple
from utils.config import settings


def normalize_from_decimal_odds(odds: Dict[str, float]) -> Dict[str, float]:
    """
    Convert decimal odds to normalized probabilities (remove overround/vig)
    
    Args:
        odds: Dict with 'home', 'draw', 'away' decimal odds
        
    Returns:
        Dict with normalized probabilities that sum to 1.0
        
    Example:
        >>> normalize_from_decimal_odds({"home": 1.90, "draw": 3.60, "away": 5.10})
        {'home': 0.476, 'draw': 0.251, 'away': 0.177}
    """
    raw_probs = {outcome: 1.0 / odd for outcome, odd in odds.items()}
    total = sum(raw_probs.values())
    
    # Normalize to sum to 1.0 (remove overround)
    return {outcome: prob / total for outcome, prob in raw_probs.items()}


def calculate_expected_value(
    model_prob: float,
    decimal_odds: float
) -> float:
    """
    Calculate Expected Value (EV) of a bet
    
    Formula: EV = p_win * (odds - 1) - p_lose
    
    Args:
        model_prob: Your model's probability of winning (0-1)
        decimal_odds: Bookmaker's decimal odds
        
    Returns:
        Expected value as decimal (e.g., 0.05 = 5% expected return)
    """
    payout_multiplier = decimal_odds - 1.0
    p_lose = 1.0 - model_prob
    
    ev = (model_prob * payout_multiplier) - p_lose
    return ev


def kelly_fraction(
    model_prob: float,
    decimal_odds: float,
    fraction: float = 0.5,
    max_kelly: float = None
) -> float:
    """
    Calculate Kelly Criterion bet sizing
    
    Formula: f* = (b*p - q) / b
    where:
        b = odds - 1 (payout multiplier)
        p = probability of winning
        q = 1 - p (probability of losing)
    
    Args:
        model_prob: Your model's win probability (0-1)
        decimal_odds: Bookmaker's decimal odds
        fraction: Kelly fraction to use (0.5 = half Kelly, safer)
        max_kelly: Maximum bet size as fraction of bankroll (default 5%)
        
    Returns:
        Recommended bet size as fraction of bankroll (0-1)
        
    Example:
        >>> kelly_fraction(0.55, 2.0, fraction=0.5)
        0.025  # Bet 2.5% of bankroll
    """
    if max_kelly is None:
        max_kelly = settings.KELLY_MAX_FRACTION

    b = decimal_odds - 1.0
    q = 1.0 - model_prob

    # Calculate full Kelly
    if b <= 0:
        return 0.0
    
    f_star = (b * model_prob - q) / b
    
    # Only bet if positive edge
    if f_star <= 0:
        return 0.0
    
    # Apply fraction and cap
    fractional_kelly = f_star * fraction
    return min(fractional_kelly, max_kelly)


def compute_betting_intelligence(
    model_probs: Dict[str, float],
    market_probs: Optional[Dict[str, float]] = None,
    decimal_odds: Optional[Dict[str, float]] = None,
    bankroll: Optional[float] = None,
    kelly_frac: float = 0.5,
    max_kelly: float = None
) -> Dict:
    """
    Compute complete betting intelligence for a match
    
    Args:
        model_probs: Your model's probabilities {'home': 0.54, 'draw': 0.28, 'away': 0.18}
        market_probs: Market probabilities (normalized, no vig). If None, computed from decimal_odds
        decimal_odds: Decimal odds {'home': 1.90, 'draw': 3.60, 'away': 5.10}
        bankroll: User's bankroll for stake calculation
        kelly_frac: Kelly fraction (0.5 = half Kelly)
        max_kelly: Maximum bet as % of bankroll (default 5%)
        
    Returns:
        Dict with CLV, edge, best bet, and optional Kelly sizing
    """
    if max_kelly is None:
        max_kelly = settings.KELLY_MAX_FRACTION

    if market_probs is None and decimal_odds is None:
        raise ValueError("Must provide either market_probs or decimal_odds")

    # Normalize market odds if needed
    if market_probs is None:
        market_probs = normalize_from_decimal_odds(decimal_odds)

    # Calculate edge (CLV) for each outcome
    outcomes = ['home', 'draw', 'away']
    clv = {
        outcome: round(model_probs[outcome] - market_probs[outcome], 4)
        for outcome in outcomes
    }

    # Find best bet
    best_pick = max(outcomes, key=lambda k: clv[k])
    edge = clv[best_pick]

    # Determine confidence level and recommendation
    if edge >= settings.EDGE_STRONG:
        confidence = "high"
        recommendation = "STRONG BET"
    elif edge >= settings.EDGE_MEDIUM:
        confidence = "medium"
        recommendation = "VALUE BET"
    elif edge >= settings.EDGE_LOW:
        confidence = "low"
        recommendation = "LEAN"
    else:
        confidence = "none"
        recommendation = "PASS"
    
    result = {
        "clv": clv,
        "best_bet": {
            "pick": best_pick,
            "edge": round(edge, 4),
            "confidence": confidence,
            "recommendation": recommendation,
            "implied_value": f"Market underpricing by {abs(int(edge * 100))}%" if edge > 0 else "No edge detected"
        }
    }
    
    # Add Kelly sizing if bankroll provided
    if decimal_odds and bankroll and edge > 0:
        # Calculate full Kelly first
        b = decimal_odds[best_pick] - 1.0
        q = 1.0 - model_probs[best_pick]
        
        if b > 0:
            full_kelly_value = (b * model_probs[best_pick] - q) / b
            full_kelly_value = max(0, full_kelly_value)  # Only positive
        else:
            full_kelly_value = 0
        
        # Calculate fractional Kelly with caps
        stake_fraction = kelly_fraction(
            model_probs[best_pick],
            decimal_odds[best_pick],
            kelly_frac,
            max_kelly
        )
        
        # Convert to percentage (multiply by 100)
        full_kelly_pct = full_kelly_value * 100
        fractional_kelly_pct = stake_fraction * 100
        max_stake_pct = max_kelly * 100  # 5% → 5.0
        
        # Cap at 3% for recommended (more conservative than max_kelly)
        recommended_stake_pct = min(fractional_kelly_pct, settings.KELLY_RECOMMENDED_MAX_PCT)
        
        result["kelly_sizing"] = {
            "full_kelly": round(full_kelly_value, 4),  # As decimal (0.08 = 8%)
            "fractional_kelly": round(stake_fraction, 4),  # As decimal (0.04 = 4%)
            "recommended_stake_pct": round(recommended_stake_pct, 2),  # As percentage (2.5)
            "max_stake_pct": round(max_stake_pct, 2)  # As percentage (5.0)
        }
        
        # Add EV calculation
        ev = calculate_expected_value(model_probs[best_pick], decimal_odds[best_pick])
        result["kelly_sizing"]["expected_value"] = round(ev, 4)
    
    return result


def compute_live_intelligence(
    model_probs_live: Dict[str, float],
    market_probs_live: Dict[str, float],
    market_probs_closing: Optional[Dict[str, float]] = None,
    decimal_odds_live: Optional[Dict[str, float]] = None,
    bankroll: Optional[float] = None,
    kelly_frac: float = 0.5
) -> Dict:
    """
    Compute betting intelligence for live/in-play matches
    
    Includes:
    - Current live edge
    - CLV vs closing line (how much line has moved)
    
    Args:
        model_probs_live: Your live model's probabilities
        market_probs_live: Current live market probabilities
        market_probs_closing: Pre-match closing probabilities (for CLV tracking)
        decimal_odds_live: Current live decimal odds
        bankroll: User's bankroll
        kelly_frac: Kelly fraction
        
    Returns:
        Dict with live edge, CLV vs closing, and recommendations
    """
    outcomes = ['home', 'draw', 'away']
    
    # Current live edge
    edge_live = {
        outcome: round(model_probs_live[outcome] - market_probs_live[outcome], 4)
        for outcome in outcomes
    }
    
    best_pick = max(outcomes, key=lambda k: edge_live[k])
    edge = edge_live[best_pick]
    
    # CLV vs closing (if available)
    clv_vs_closing = None
    if market_probs_closing:
        clv_vs_closing = {
            outcome: round(market_probs_live[outcome] - market_probs_closing[outcome], 4)
            for outcome in outcomes
        }
    
    # Recommendation logic (live thresholds are tighter than pre-match)
    live_strong = settings.EDGE_STRONG - 0.02  # 0.08
    live_lean = settings.EDGE_MEDIUM - 0.01    # 0.04
    if edge >= live_strong:
        recommendation = "STRONG LIVE BET"
        confidence = "high"
    elif edge >= live_lean:
        recommendation = "LEAN"
        confidence = "medium"
    else:
        recommendation = "PASS"
        confidence = "low"

    result = {
        "edge_live": edge_live,
        "best_bet_live": {
            "pick": best_pick,
            "edge": round(edge, 4),
            "recommendation": recommendation,
            "confidence": confidence,
            "note": "Live in-play edge - smaller than pre-match but actionable" if edge > 0.02 else "Limited edge in current state"
        }
    }

    if clv_vs_closing:
        result["clv_vs_closing"] = clv_vs_closing
        closing_move = clv_vs_closing[best_pick]
        result["best_bet_live"]["closing_line_move"] = round(closing_move, 4)
        result["best_bet_live"]["beating_closing"] = closing_move > 0.02

    # Kelly sizing for live bets (if provided)
    if decimal_odds_live and bankroll and edge > 0:
        stake_fraction = kelly_fraction(
            model_probs_live[best_pick],
            decimal_odds_live[best_pick],
            kelly_frac,
            max_kelly=settings.KELLY_MAX_LIVE
        )

        result["kelly_sizing"] = {
            "fractional_kelly": round(stake_fraction, 4),
            "bankroll_stake": round(bankroll * stake_fraction, 2),
            "confidence_level": confidence,
            "note": f"Live bet sizing more conservative ({settings.KELLY_MAX_LIVE * 100:.0f}% cap)"
        }

    return result


def get_confidence_tier(edge: float) -> str:
    """Map edge value to confidence tier"""
    if edge >= settings.EDGE_STRONG:
        return "high"
    elif edge >= settings.EDGE_MEDIUM:
        return "medium"
    elif edge >= settings.EDGE_LOW:
        return "low"
    else:
        return "none"


def get_recommendation(edge: float, is_live: bool = False) -> str:
    """Get betting recommendation based on edge"""
    if is_live:
        live_strong = settings.EDGE_STRONG - 0.02
        live_lean = settings.EDGE_MEDIUM - 0.01
        if edge >= live_strong:
            return "STRONG LIVE BET"
        elif edge >= live_lean:
            return "LEAN"
        else:
            return "PASS"
    else:
        if edge >= settings.EDGE_STRONG:
            return "STRONG BET"
        elif edge >= settings.EDGE_MEDIUM:
            return "VALUE BET"
        elif edge >= settings.EDGE_LOW:
            return "LEAN"
        else:
            return "PASS"
