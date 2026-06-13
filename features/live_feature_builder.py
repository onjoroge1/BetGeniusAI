"""
Live (in-game) feature + label builder — Snapbet Live Edge, Phase 1.
See docs/LIVE_EDGE_PLAN.md.

Two pure cores (no I/O → fully unit-testable):
  - build_live_features(snapshots, minute, prematch=None): rolling-window +
    pressure features from a chronological list of live_match_stats snapshots,
    using ONLY snapshots at/<= `minute` (leak-safe).
  - label_from_goals(goal_minutes, snapshot_minute, score_at, final_score):
    target_more_goal / target_next_goal / target_result_holds.

Plus a thin DB layer that reads the PERSISTENT snapshot store (live_match_snapshots,
created by migrations/live_edge_snapshots.sql — live_match_stats itself is purged
after 4h by stale_cleanup, so it can't be the training store).
"""

import math
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Pressure score weights (docs/LIVE_EDGE_PLAN.md §5). Tunable.
PRESSURE_WEIGHTS = {
    "shots_10": 0.30, "sot_10": 0.25, "corners_10": 0.15,
    "da_10": 0.15, "poss_final": 0.10, "subs": 0.05,
}


def _at_or_before(snapshots: List[dict], minute: int) -> List[dict]:
    """Leak-safe filter: only snapshots at or before `minute`, chronological."""
    return sorted([s for s in snapshots if s.get("minute") is not None and s["minute"] <= minute],
                  key=lambda s: s["minute"])


def _delta_over_window(snaps: List[dict], minute: int, window: int, field: str) -> float:
    """
    Change in a cumulative stat (e.g. home_shots_total) over the last `window`
    minutes — current value minus the value at (minute - window).
    """
    if not snaps:
        return 0.0
    current = snaps[-1].get(field) or 0
    prior_cut = minute - window
    prior_snaps = [s for s in snaps if s["minute"] <= prior_cut]
    prior = (prior_snaps[-1].get(field) or 0) if prior_snaps else 0
    return float(max(0, current - prior))


def build_live_features(snapshots: List[dict], minute: int,
                        prematch: Optional[dict] = None) -> Dict[str, float]:
    """
    Build the feature row for a decision at `minute`. `snapshots` is the match's
    live_match_stats history (each dict has minute, home/away_score, shots,
    shots_on_target, corners, possession, red_cards...). `prematch` optionally
    carries pre-match anchor probs + favorite info.
    """
    snaps = _at_or_before(snapshots, minute)
    if not snaps:
        return {}
    cur = snaps[-1]
    hs, as_ = cur.get("home_score", 0) or 0, cur.get("away_score", 0) or 0

    f: Dict[str, float] = {
        # clock / score-state
        "minute": float(minute),
        "remaining_est": float(max(0, 94 - minute)),  # 90 + ~4 stoppage
        "home_score": float(hs), "away_score": float(as_),
        "goal_diff": float(hs - as_),
        "is_tied": 1.0 if hs == as_ else 0.0,
        "total_goals": float(hs + as_),
        # cumulative live
        "home_shots": float(cur.get("home_shots_total") or 0),
        "away_shots": float(cur.get("away_shots_total") or 0),
        "home_sot": float(cur.get("home_shots_on_target") or 0),
        "away_sot": float(cur.get("away_shots_on_target") or 0),
        "home_corners": float(cur.get("home_corners") or 0),
        "away_corners": float(cur.get("away_corners") or 0),
        "home_red": float(cur.get("home_red_cards") or 0),
        "away_red": float(cur.get("away_red_cards") or 0),
        "home_possession": float(cur.get("home_possession") or 50),
    }
    # momentum: deltas over last 10 minutes
    for side, field in (("home", "home_shots_total"), ("away", "away_shots_total")):
        f[f"{side}_shots_10"] = _delta_over_window(snaps, minute, 10, field)
    for side, field in (("home", "home_shots_on_target"), ("away", "away_shots_on_target")):
        f[f"{side}_sot_10"] = _delta_over_window(snaps, minute, 10, field)
    for side, field in (("home", "home_corners"), ("away", "away_corners")):
        f[f"{side}_corners_10"] = _delta_over_window(snaps, minute, 10, field)

    # pressure score per side (spec §5), normalized lightly to a 0–100-ish scale
    def pressure(side: str) -> float:
        poss = f["home_possession"] if side == "home" else (100 - f["home_possession"])
        return (PRESSURE_WEIGHTS["shots_10"] * f[f"{side}_shots_10"] * 10
                + PRESSURE_WEIGHTS["sot_10"] * f[f"{side}_sot_10"] * 15
                + PRESSURE_WEIGHTS["corners_10"] * f[f"{side}_corners_10"] * 8
                + PRESSURE_WEIGHTS["poss_final"] * (poss / 10.0))
    f["pressure_home"] = round(pressure("home"), 3)
    f["pressure_away"] = round(pressure("away"), 3)
    f["pressure_total"] = round(f["pressure_home"] + f["pressure_away"], 3)

    # pre-match anchor
    if prematch:
        f["prematch_home_prob"] = float(prematch.get("home", 0) or 0)
        f["prematch_away_prob"] = float(prematch.get("away", 0) or 0)
        fav = prematch.get("favorite")  # 'home'/'away'
        if fav:
            fav_goals = hs if fav == "home" else as_
            dog_goals = as_ if fav == "home" else hs
            f["favorite_trailing"] = 1.0 if fav_goals < dog_goals else 0.0
            f["favorite_leading"] = 1.0 if fav_goals > dog_goals else 0.0
    return f


def label_from_goals(goal_minutes: List[int], snapshot_minute: int,
                     score_at: tuple, final_score: tuple,
                     next_goal_team: Optional[str] = None) -> Dict:
    """
    Targets for a snapshot at `snapshot_minute`.
      goal_minutes : minutes of ALL goals in the match
      score_at     : (home, away) at the snapshot
      final_score  : (home, away) at FT
      next_goal_team: team of the first goal after snapshot_minute ('home'/'away'/None)
    """
    more = any(gm > snapshot_minute for gm in goal_minutes)
    h0, a0 = score_at
    hf, af = final_score
    state_now = "H" if h0 > a0 else ("A" if a0 > h0 else "D")
    state_ft = "H" if hf > af else ("A" if af > hf else "D")
    return {
        "target_more_goal": 1 if more else 0,
        "target_next_goal": next_goal_team if more else "none",
        "target_result_holds": 1 if state_now == state_ft else 0,
    }


def implied_more_goal_poisson(home_score: int, away_score: int, minute: int,
                              prematch_total_goals: float = 2.6) -> float:
    """
    Cheap model-free PRIOR for P(>=1 more goal) used by the rule-based scanner
    (Phase 2) before the trained model exists: scale league goal rate by the
    fraction of match remaining. p = 1 - exp(-lambda_remaining).
    """
    remaining_frac = max(0.0, (94 - minute) / 94.0)
    lam = prematch_total_goals * remaining_frac
    return round(1.0 - math.exp(-lam), 4)
