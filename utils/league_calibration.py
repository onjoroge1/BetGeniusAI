"""
Per-league confidence calibration multipliers.

Originally derived from the 67-match post-cutoff backtest (April 22-26, 2026).
Updated 2026-05-10 by council review against 90-day live data (986 settled predictions):

  League              Old mult  New mult  Reason
  Primeira Liga (94)  1.10      0.80      39% live accuracy (n=41) — was set from n=8 noise
  Premier League (39) 1.05      1.00      50% live (n=56) — not enough signal to boost
  Bundesliga (78)     1.05      1.05      52.5% live (n=40) — marginal, keep modest boost
  La Liga (140)       1.00      1.00      50% live (n=58) — coin flip, neutral
  Ligue 1 (61)        0.95      0.95      no change — sparse data
  Eredivisie (88)     0.90      0.90      no change — sparse data
  Serie A (135)       0.85      0.75      40% live (n=70) — specialist now overrides main;
                                           low multiplier suppresses residual surfacing
  Eliteserien (103)   (none)    1.15      67.9% live (n=28) — strong signal, trust more
  Champions League    1.00      1.00      no change
  Europa League       1.00      1.00      no change

Note: Primeira Liga multiplier drop from 1.10→0.80 is the most material change.
The original 1.10 was based on n=8 backtest (±17pp std error) that contradicts
41-match live reality (39% accuracy). 0.80 means only raw_conf ≥0.625 will clear
the ≥50% gate, drastically reducing surfaced Primeira Liga picks.
"""

# League ID → confidence multiplier
LEAGUE_CONFIDENCE_MULTIPLIERS = {
    94:  0.80,   # Primeira Liga — 39% live (n=41); was 1.10 from noisy n=8 backtest
    39:  1.00,   # Premier League — 50% live (n=56); remove false boost
    78:  1.05,   # Bundesliga — 52.5% live (n=40); modest boost retained
    140: 1.00,   # La Liga — 50% live (n=58); coin flip, neutral
    61:  0.95,   # Ligue 1 — sparse live data, conservative
    88:  0.90,   # Eredivisie — sparse live data, conservative
    135: 0.75,   # Serie A — 40% live (n=70); specialist overrides main, suppress residual
    103: 1.15,   # Eliteserien — 67.9% live (n=28); strong V3 signal, surface more
    2:   1.00,   # Champions League — neutral
    3:   1.00,   # Europa League — neutral
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
