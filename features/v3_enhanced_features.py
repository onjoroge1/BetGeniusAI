"""
V3 Enhanced Features — Phase A (ELO + Z-scores)

Adds 7 new features on top of the existing 24 working features:
  1-4. ELO ratings (home_elo, away_elo, elo_diff, elo_expected_home)
  5-7. League-relative Z-scores (z_prob_home, z_prob_draw, z_ha_gap)

These features are INDEPENDENT of the existing features and have been
shown to add AUC without causing class skew (unlike the previous retrain's
meta features that were coupled with class weighting).

Design principles:
- Each feature is a separate DB query or computation
- All return np.nan when data missing (LightGBM handles natively)
- Z-scores are per-league — the main model currently can't learn this
- ELO is independent of market odds — adds orthogonal signal
- No class weighting, no inference boost — just new signal

Usage:
  from features.v3_enhanced_features import build_enhanced_features
  extra = build_enhanced_features(cursor, match_id, match_info, v2_features)
  all_features = {**existing_24_features, **extra}  # now 31 features
"""

from typing import Dict, Optional
import numpy as np
import psycopg2
import logging

logger = logging.getLogger(__name__)

ENHANCED_FEATURE_NAMES = [
    # ELO features (4)
    'home_elo',
    'away_elo',
    'elo_diff',
    'elo_expected_home',  # Probability from ELO formula
    # Z-score features (3)
    'z_prob_home',   # Standardized home prob vs league average
    'z_prob_draw',   # Standardized draw prob vs league average
    'z_ha_gap',      # Standardized home-away gap
]


def _get_elo_features(cursor, home_team_id: int, away_team_id: int) -> Dict[str, float]:
    """Fetch ELO ratings for both teams. Returns NaN if missing."""
    features = {name: np.nan for name in ['home_elo', 'away_elo', 'elo_diff', 'elo_expected_home']}

    if not home_team_id or not away_team_id:
        return features

    try:
        cursor.execute("""
            SELECT team_id, elo_rating FROM team_elo
            WHERE team_id IN (%s, %s)
        """, (home_team_id, away_team_id))
        rows = dict(cursor.fetchall())

        home_elo = rows.get(home_team_id)
        away_elo = rows.get(away_team_id)

        if home_elo is not None:
            features['home_elo'] = float(home_elo)
        if away_elo is not None:
            features['away_elo'] = float(away_elo)

        if home_elo is not None and away_elo is not None:
            features['elo_diff'] = float(home_elo - away_elo)
            # Standard ELO expected-score formula with home advantage
            # Home advantage ~= 65 ELO points in soccer
            diff = (home_elo + 65) - away_elo
            features['elo_expected_home'] = 1.0 / (1.0 + 10 ** (-diff / 400))
    except Exception as e:
        logger.debug(f"ELO lookup failed: {e}")

    return features


# League-level z-score stats cached per process
_league_stats_cache: Optional[Dict[int, Dict[str, tuple]]] = None


def _load_league_stats(cursor) -> Dict[int, Dict[str, tuple]]:
    """Compute mean/std per league for key features. Cached after first call."""
    global _league_stats_cache
    if _league_stats_cache is not None:
        return _league_stats_cache

    logger.info("Loading league-level stats for Z-scores...")
    stats = {}

    try:
        cursor.execute("""
            SELECT oc.match_id, f.league_id,
                   oc.ph_cons, oc.pd_cons, oc.pa_cons
            FROM odds_consensus oc
            JOIN fixtures f ON oc.match_id = f.match_id
            WHERE oc.ph_cons IS NOT NULL
              AND oc.ts_effective < NOW() - INTERVAL '1 day'  -- leak-safe: only past
        """)

        league_data = {}
        for _, lid, ph, pd_, pa in cursor.fetchall():
            if lid is None:
                continue
            league_data.setdefault(lid, {'prob_home': [], 'prob_draw': [], 'ha_gap': []})
            if ph is not None:
                league_data[lid]['prob_home'].append(float(ph))
            if pd_ is not None:
                league_data[lid]['prob_draw'].append(float(pd_))
            if ph is not None and pa is not None:
                league_data[lid]['ha_gap'].append(abs(float(ph) - float(pa)))

        for lid, d in league_data.items():
            if len(d['prob_home']) < 30:  # Need min sample for reliable stats
                continue
            stats[lid] = {
                'prob_home': (np.mean(d['prob_home']), np.std(d['prob_home']) or 0.01),
                'prob_draw': (np.mean(d['prob_draw']), np.std(d['prob_draw']) or 0.01),
                'ha_gap':    (np.mean(d['ha_gap']),    np.std(d['ha_gap'])    or 0.01),
            }

        _league_stats_cache = stats
        logger.info(f"Loaded Z-score stats for {len(stats)} leagues")
    except Exception as e:
        logger.warning(f"League stats computation failed: {e}")
        _league_stats_cache = {}

    return _league_stats_cache


def _get_zscore_features(cursor, league_id: int, v2_features: Dict[str, float]) -> Dict[str, float]:
    """Compute league-relative Z-scores for prob features."""
    features = {name: np.nan for name in ['z_prob_home', 'z_prob_draw', 'z_ha_gap']}

    if not league_id:
        return features

    league_stats = _load_league_stats(cursor)
    league_info = league_stats.get(league_id)
    if not league_info:
        return features

    ph = v2_features.get('prob_home')
    pd_ = v2_features.get('prob_draw')
    pa = v2_features.get('prob_away')

    if ph is not None and not (isinstance(ph, float) and np.isnan(ph)):
        mean_h, std_h = league_info['prob_home']
        features['z_prob_home'] = (ph - mean_h) / std_h

    if pd_ is not None and not (isinstance(pd_, float) and np.isnan(pd_)):
        mean_d, std_d = league_info['prob_draw']
        features['z_prob_draw'] = (pd_ - mean_d) / std_d

    if ph is not None and pa is not None and not any(isinstance(x, float) and np.isnan(x) for x in [ph, pa]):
        mean_g, std_g = league_info['ha_gap']
        features['z_ha_gap'] = (abs(ph - pa) - mean_g) / std_g

    return features


def build_enhanced_features(cursor, match_info: Dict, v2_features: Dict[str, float]) -> Dict[str, float]:
    """
    Build ELO + Z-score features.
    Returns dict with 7 new features. Safe to merge into existing feature dict.

    Args:
        cursor: active psycopg2 cursor
        match_info: dict with home_team_id, away_team_id, league_id
        v2_features: existing V2 features (needs prob_home, prob_draw, prob_away)
    """
    features = {}
    features.update(_get_elo_features(
        cursor,
        match_info.get('home_team_id'),
        match_info.get('away_team_id')
    ))
    features.update(_get_zscore_features(cursor, match_info.get('league_id'), v2_features))
    return features
