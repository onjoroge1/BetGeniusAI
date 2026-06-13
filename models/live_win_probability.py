"""
Live win-probability engine (Snapbet Live Edge, Layer 1).

Given the CURRENT score, the minute, and each team's full-match expected goals,
compute live P(home win / draw / away win) plus the advanced markets — the same
Poisson approach /predict uses for pre-match markets, but conditioned on the
goals that can still happen in the time remaining.

Principled, training-free, odds-free → ships today as "live match intelligence."
A *trained* live model replaces this prior once we've accumulated snapshots.

Method:
  remaining_frac = minutes_left / 90
  λ_home_rem = λ_home_full * remaining_frac * red_card_adjust
  (same for away). Distribution of ADDITIONAL goals each side ~ Poisson(λ_rem).
  Fold over the joint grid with the current score to get final-outcome probs and
  every goals-based market.
"""

import math
from typing import Dict, Optional

# A team down to 10 men scores less and concedes more (rough, well-documented).
RED_SCORING_MULT = 0.80
RED_CONCEDING_MULT = 1.25
DEFAULT_TOTAL_XG = 2.7          # league-ish full-match total when no anchor
MATCH_MINUTES = 92.0           # 90 + ~2 typical effective stoppage for remaining-time calc
_MAX_ADD = 8                   # additional goals per side considered (tail mass negligible)


def _pois_pmf(k: int, lam: float) -> float:
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def lambdas_from_anchor(prematch: Optional[dict], total_xg: float = DEFAULT_TOTAL_XG) -> tuple:
    """
    Split a full-match goal total into (home, away) expected goals using the
    pre-match win-prob anchor. Stronger side gets the larger share. With no
    anchor, assume a mild home tilt.
    """
    if not prematch:
        return 0.53 * total_xg, 0.47 * total_xg
    ph = float(prematch.get("home", 0) or 0)
    pa = float(prematch.get("away", 0) or 0)
    pd = max(0.0, 1.0 - ph - pa)
    # expected-points-ish share → goal share
    home_strength = ph + 0.5 * pd
    away_strength = pa + 0.5 * pd
    s = home_strength + away_strength
    if s <= 0:
        return 0.53 * total_xg, 0.47 * total_xg
    home_share = home_strength / s
    # compress toward 0.5 so a 70% favorite isn't given 70% of goals (goals are noisier)
    home_share = 0.5 + 0.6 * (home_share - 0.5)
    return round(total_xg * home_share, 3), round(total_xg * (1 - home_share), 3)


def live_win_probability(home_score: int, away_score: int, minute: int,
                         lambda_home_full: float = 1.45, lambda_away_full: float = 1.25,
                         red_home: int = 0, red_away: int = 0) -> Dict:
    """
    Live outcome probabilities + advanced markets from current state.
    Returns win_probability, markets, and the remaining-goal rates used.
    """
    minutes_left = max(0.0, MATCH_MINUTES - minute)
    rem_frac = minutes_left / 90.0

    lam_h = max(0.0, lambda_home_full * rem_frac)
    lam_a = max(0.0, lambda_away_full * rem_frac)
    # red-card adjustments (a red on home hurts home scoring, helps away)
    if red_home > 0:
        lam_h *= RED_SCORING_MULT; lam_a *= RED_CONCEDING_MULT
    if red_away > 0:
        lam_a *= RED_SCORING_MULT; lam_h *= RED_CONCEDING_MULT

    # Joint distribution over additional goals
    pmf_h = [_pois_pmf(i, lam_h) for i in range(_MAX_ADD + 1)]
    pmf_a = [_pois_pmf(j, lam_a) for j in range(_MAX_ADD + 1)]

    p_home = p_draw = p_away = 0.0
    p_btts = 0.0
    p_over25 = 0.0
    cur_total = home_score + away_score
    for i in range(_MAX_ADD + 1):
        for j in range(_MAX_ADD + 1):
            p = pmf_h[i] * pmf_a[j]
            if p <= 0:
                continue
            fh, fa = home_score + i, away_score + j
            if fh > fa:
                p_home += p
            elif fa > fh:
                p_away += p
            else:
                p_draw += p
            if fh >= 1 and fa >= 1:
                p_btts += p
            if fh + fa >= 3:
                p_over25 += p

    # normalize (tail truncation)
    z = p_home + p_draw + p_away
    if z > 0:
        p_home, p_draw, p_away = p_home / z, p_draw / z, p_away / z
    # round to 4dp but guarantee an exact sum of 1.0 (frontend relies on it):
    # absorb the rounding residual into the largest component.
    wp = {"home": round(p_home, 4), "draw": round(p_draw, 4), "away": round(p_away, 4)}
    resid = round(1.0 - sum(wp.values()), 4)
    wp[max(wp, key=wp.get)] = round(wp[max(wp, key=wp.get)] + resid, 4)
    p_home, p_draw, p_away = wp["home"], wp["draw"], wp["away"]

    # goals-remaining markets
    p_no_more = pmf_h[0] * pmf_a[0]
    p_over05_more = 1.0 - p_no_more
    # next goal split by instantaneous rate
    lam_sum = lam_h + lam_a
    if lam_sum > 0:
        ng_home = p_over05_more * (lam_h / lam_sum)
        ng_away = p_over05_more * (lam_a / lam_sum)
    else:
        ng_home = ng_away = 0.0

    return {
        "win_probability": {
            "home": round(p_home, 4),
            "draw": round(p_draw, 4),
            "away": round(p_away, 4),
        },
        "markets": {
            "over_0.5_more_goals": round(p_over05_more, 4),
            "over_2.5_total": round(p_over25, 4),
            "btts": round(p_btts, 4),
            "next_goal": {
                "home": round(ng_home, 4),
                "away": round(ng_away, 4),
                "none": round(p_no_more, 4),
            },
        },
        "remaining_goal_rate": {"home": round(lam_h, 3), "away": round(lam_a, 3)},
        "minutes_left_est": round(minutes_left, 1),
        "method": "live_poisson_prior",   # not a trained model yet
    }
