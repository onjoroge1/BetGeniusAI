"""
Historical Odds → V3 Feature Adapter

Converts rows from `historical_odds` (raw multi-bookmaker odds, ALWAYS pre-match)
into V3-compatible feature vectors for training league specialists.

Bookmakers in table:
  b365 (Bet365), bw (BetWin), iw (Interwetten), lb (Ladbrokes),
  ps (Pinnacle), wh (William Hill), sj (Stan James), vc (VC Bet)
  + avg (market average), max (best price)

Features produced (20):
  Market core (11): prob_home/draw/away, book_dispersion_*, odds_volatility_*,
                    book_coverage, market_overround
  Closeness (4):    ha_prob_gap, favourite_strength, draw_vs_nondraw_ratio,
                    implied_competitiveness
  League draw (2):  league_draw_rate, league_draw_deviation
  Draw market (2):  draw_dispersion_ratio, draw_overround_share
  Derived (1):      none additional

Excluded (not derivable from historical_odds):
  - h2h_draw_rate, h2h_matches_used (no team_id linkage)
  - league_ece, league_tier_weight, league_historical_edge (cross-league features)
"""

import numpy as np
from typing import Dict, List, Tuple


# Mapping from historical_odds league codes to API-Football league IDs
HISTORICAL_LEAGUE_MAP = {
    'E0': 39,    # Premier League
    'SP1': 140,  # La Liga
    'I1': 135,   # Serie A
    'D1': 78,    # Bundesliga
    'F1': 61,    # Ligue 1
    'N1': 88,    # Eredivisie
    'P1': 94,    # Primeira Liga
    'T1': 203,   # Turkey Super Lig
    'B1': 144,   # Belgium Pro League
    'G1': 197,   # Greek Super League
    'SC0': 179,  # Scottish Premier
    'I2': 136,   # Serie B
    'E1': 40,    # Championship
    'SP2': 141,  # Segunda
    'D2': 79,    # 2. Bundesliga
    'F2': 62,    # Ligue 2
    'P2': 95,    # Primeira Liga 2
}

# 8 bookmakers tracked in historical_odds
BOOKMAKERS = ['b365', 'bw', 'iw', 'lb', 'ps', 'wh', 'sj', 'vc']

# Output feature names (20 features)
SPECIALIST_FEATURE_NAMES = [
    # V2 Core (11)
    'prob_home', 'prob_draw', 'prob_away',
    'book_dispersion_home', 'book_dispersion_draw', 'book_dispersion_away',
    'odds_volatility_home', 'odds_volatility_draw', 'odds_volatility_away',
    'book_coverage', 'market_overround',
    # Closeness (4)
    'ha_prob_gap', 'favourite_strength', 'draw_vs_nondraw_ratio', 'implied_competitiveness',
    # League draw context (2)
    'league_draw_rate', 'league_draw_deviation',
    # Draw market structure (2)
    'draw_dispersion_ratio', 'draw_overround_share',
    # Match context (1)
    'season_progress',  # placeholder for season position
]


def build_features_from_row(row: Dict, league_stats: Dict) -> Dict[str, float]:
    """
    Build V3-compatible features from a single historical_odds row.

    Args:
        row: dict with bookmaker odds columns (b365_h, ps_h, etc.) plus avg/max
        league_stats: precomputed dict with 'avg_draw_rate' for the row's league

    Returns:
        Dict of 20 feature values (np.nan for missing data)
    """
    features = {name: np.nan for name in SPECIALIST_FEATURE_NAMES}

    # ── Collect bookmaker probabilities ──
    home_odds_list, draw_odds_list, away_odds_list = [], [], []
    for bm in BOOKMAKERS:
        h = row.get(f'{bm}_h')
        d = row.get(f'{bm}_d')
        a = row.get(f'{bm}_a')
        if h and d and a and h > 1.0 and d > 1.0 and a > 1.0:
            home_odds_list.append(h)
            draw_odds_list.append(d)
            away_odds_list.append(a)

    n_books = len(home_odds_list)
    if n_books == 0:
        # Fallback to avg_h/d/a if no individual books
        avg_h = row.get('avg_h')
        avg_d = row.get('avg_d')
        avg_a = row.get('avg_a')
        if not (avg_h and avg_d and avg_a):
            return features  # nothing to work with
        # Synthesize 1-book scenario
        home_odds_list = [avg_h]
        draw_odds_list = [avg_d]
        away_odds_list = [avg_a]
        n_books = 1

    # ── Convert to implied probabilities (per-book, normalize per-book) ──
    home_probs, draw_probs, away_probs = [], [], []
    for h, d, a in zip(home_odds_list, draw_odds_list, away_odds_list):
        ih, id_, ia = 1.0/h, 1.0/d, 1.0/a
        total = ih + id_ + ia
        home_probs.append(ih / total)
        draw_probs.append(id_ / total)
        away_probs.append(ia / total)

    # ── V2 Core features ──
    features['prob_home'] = float(np.mean(home_probs))
    features['prob_draw'] = float(np.mean(draw_probs))
    features['prob_away'] = float(np.mean(away_probs))
    features['book_coverage'] = float(n_books)

    # Overround = avg gross implied (before normalization)
    avg_h = np.mean(home_odds_list)
    avg_d = np.mean(draw_odds_list)
    avg_a = np.mean(away_odds_list)
    overround = (1.0/avg_h + 1.0/avg_d + 1.0/avg_a) - 1.0
    features['market_overround'] = float(overround)

    # Dispersion = std of per-book implied probabilities
    if n_books >= 2:
        features['book_dispersion_home'] = float(np.std(home_probs))
        features['book_dispersion_draw'] = float(np.std(draw_probs))
        features['book_dispersion_away'] = float(np.std(away_probs))
    else:
        features['book_dispersion_home'] = 0.02  # typical small-market value
        features['book_dispersion_draw'] = 0.02
        features['book_dispersion_away'] = 0.02

    # Odds volatility = (max - min) / mean per outcome
    def _vol(odds_list):
        if len(odds_list) < 2:
            return 0.05  # typical small-market value
        return float((max(odds_list) - min(odds_list)) / np.mean(odds_list))
    features['odds_volatility_home'] = _vol(home_odds_list)
    features['odds_volatility_draw'] = _vol(draw_odds_list)
    features['odds_volatility_away'] = _vol(away_odds_list)

    # Use max_h/d/a for volatility if available (more accurate)
    max_h = row.get('max_h'); max_d = row.get('max_d'); max_a = row.get('max_a')
    if max_h and avg_h:
        features['odds_volatility_home'] = float((max_h - avg_h) / avg_h)
    if max_d and avg_d:
        features['odds_volatility_draw'] = float((max_d - avg_d) / avg_d)
    if max_a and avg_a:
        features['odds_volatility_away'] = float((max_a - avg_a) / avg_a)

    # ── Closeness features (4) ──
    ph, pd_, pa = features['prob_home'], features['prob_draw'], features['prob_away']
    features['ha_prob_gap'] = abs(ph - pa)
    features['favourite_strength'] = max(ph, pa)
    features['implied_competitiveness'] = 1.0 - abs(ph - pa)
    if pd_ < 0.99:
        features['draw_vs_nondraw_ratio'] = pd_ / (1.0 - pd_)
    else:
        features['draw_vs_nondraw_ratio'] = 99.0

    # ── League draw context (2) ──
    league_avg_draw = league_stats.get('avg_draw_rate', 0.25)
    features['league_draw_rate'] = float(league_avg_draw)
    features['league_draw_deviation'] = float(pd_ - league_avg_draw)

    # ── Draw market structure (2) ──
    avg_ha_disp = (features['book_dispersion_home'] + features['book_dispersion_away']) / 2.0
    if avg_ha_disp > 0.001:
        features['draw_dispersion_ratio'] = features['book_dispersion_draw'] / avg_ha_disp
    else:
        features['draw_dispersion_ratio'] = 1.0

    total_impl = (1.0 / avg_h) + (1.0 / avg_d) + (1.0 / avg_a)
    if total_impl > 1.0:
        excess = total_impl - 1.0
        fair_draw = (1.0 / avg_d) / total_impl
        raw_draw = 1.0 / avg_d
        if excess > 0.001:
            features['draw_overround_share'] = (raw_draw - fair_draw) / excess
        else:
            features['draw_overround_share'] = 1.0/3.0
    else:
        features['draw_overround_share'] = 1.0/3.0

    # ── Match context (1) ──
    # Season progress: estimate from match_date within season
    # Most leagues: Aug-May season; we approximate position 0..1
    md = row.get('match_date')
    if md:
        month = md.month if hasattr(md, 'month') else 1
        # Aug = 0, May = ~10/12. Approximate.
        if month >= 8:
            features['season_progress'] = (month - 8) / 10.0
        else:
            features['season_progress'] = (month + 4) / 10.0
    else:
        features['season_progress'] = 0.5

    return features


def compute_league_stats(rows: List[Dict]) -> Dict[str, float]:
    """Compute per-league aggregate stats needed for features."""
    if not rows:
        return {'avg_draw_rate': 0.25, 'n_matches': 0}

    draw_count = sum(1 for r in rows if r.get('result') == 'D')
    return {
        'avg_draw_rate': draw_count / len(rows),
        'n_matches': len(rows),
    }


def get_outcome_label(row: Dict) -> str:
    """Extract H/D/A label from row."""
    h = row.get('home_goals')
    a = row.get('away_goals')
    if h is None or a is None:
        return None
    if h > a:
        return 'H'
    elif h < a:
        return 'A'
    else:
        return 'D'
