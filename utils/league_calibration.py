"""
Per-league confidence calibration multipliers.

Derived from the 67-match post-cutoff backtest (April 22-26, 2026).
Multipliers adjust V3 confidence based on observed accuracy per league.
A multiplier of 1.10 means "trust this league's V3 prediction 10% more."

Applied AFTER prediction, BEFORE returning to /predict response.
Specialist override (when specialist disagrees with main) bypasses this multiplier
and uses the specialist's own confidence directly.
"""

# League ID → confidence multiplier
# Based on post-cutoff accuracy: higher acc = higher multiplier
LEAGUE_CONFIDENCE_MULTIPLIERS = {
    94:  1.10,   # Primeira Liga (87.5% accuracy in backtest, n=8)
    39:  1.05,   # Premier League (75.0%, n=8)
    78:  1.05,   # Bundesliga (66.7%, n=9)
    140: 1.00,   # La Liga (53.3%, n=15)
    61:  0.95,   # Ligue 1 (50.0%, n=10)
    88:  0.90,   # Eredivisie (44.4%, n=9)
    135: 0.85,   # Serie A (37.5%, n=8) — main weak; specialist exists
    2:   1.00,   # Champions League — neutral (no specific signal)
    3:   1.00,   # Europa League
}

# Defaults
DEFAULT_MULTIPLIER = 1.00
MIN_CONFIDENCE = 0.05
MAX_CONFIDENCE = 0.95


def apply_league_calibration(confidence: float, league_id: int) -> tuple:
    """
    Apply league-specific confidence multiplier.

    Args:
        confidence: raw model confidence in [0, 1]
        league_id: league ID

    Returns:
        (calibrated_confidence, multiplier_applied)
    """
    multiplier = LEAGUE_CONFIDENCE_MULTIPLIERS.get(league_id, DEFAULT_MULTIPLIER)
    calibrated = confidence * multiplier
    calibrated = max(MIN_CONFIDENCE, min(MAX_CONFIDENCE, calibrated))
    return calibrated, multiplier


def compute_should_surface(prediction: str, confidence: float, probs: dict) -> tuple:
    """
    Determine if a prediction should be surfaced on the frontend.

    Backtest evidence (67-match post-cutoff sample):
    - Away picks <40% conf: 36% accuracy (suppress)
    - Coin-flip matches (max prob <40%): 38% accuracy (suppress)
    - High-conf picks (50%+): 83% accuracy (surface)

    Args:
        prediction: 'home', 'draw', or 'away'
        confidence: max probability
        probs: dict with 'home', 'draw', 'away' probabilities

    Returns:
        (should_surface: bool, reason: str)
    """
    max_prob = max(probs.values())

    # Coin-flip: no meaningful pick
    if max_prob < 0.40:
        return False, "coin_flip"

    # Away picks below 40% conf are unreliable
    if prediction == 'away' and confidence < 0.40:
        return False, "away_low_conf"

    # Draw picks below 30% are noise
    if prediction == 'draw' and confidence < 0.30:
        return False, "draw_low_conf"

    return True, "ok"
