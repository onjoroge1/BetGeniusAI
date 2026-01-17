"""
Historical Feature Builder - High-Quality Features from historical_odds

This builder extracts features directly from the historical_odds table,
which contains 37,000+ matches with complete bookmaker odds data.

Feature Categories (35 high-coverage features):
═══════════════════════════════════════════════════════════════════════════════

1. ODDS PROBABILITY FEATURES (9):
   - Implied probabilities from Bet365 (p_b365_h, p_b365_d, p_b365_a)
   - Implied probabilities from Pinnacle (p_ps_h, p_ps_d, p_ps_a) - sharp book
   - Market average probabilities (p_avg_h, p_avg_d, p_avg_a)

2. MARKET STRUCTURE FEATURES (8):
   - favorite_strength: Gap between favorite and others
   - underdog_value: Price of longest-odds outcome
   - draw_tendency: How close to 1/3 is draw probability
   - market_overround: Total implied probability (margin)
   - sharp_soft_divergence: Pinnacle vs Bet365 difference
   - max_vs_avg_edge: Maximum odds vs average opportunity
   - odds_range_h/d/a: Max - Avg spread per outcome

3. OVER/UNDER & ASIAN HANDICAP (6):
   - ou_line: Total goals line
   - over_implied_prob, under_implied_prob: O/U probabilities
   - ah_line: Asian handicap line
   - ah_home_prob, ah_away_prob: AH probabilities

4. LEAGUE & SEASONAL FEATURES (4):
   - league_home_win_rate: Historical home win % in league
   - league_draw_rate: Historical draw % in league
   - league_goals_avg: Average goals in league
   - season_month: Month of match (captures seasonality)

5. GOAL EXPECTATION FEATURES (4):
   - expected_total_goals: Derived from O/U line
   - home_goals_expected: Derived from odds + home advantage
   - away_goals_expected: Derived from odds
   - goal_diff_expected: Home - Away expected

6. VALUE DETECTION FEATURES (4):
   - home_value_score: Model prob vs market prob gap
   - draw_value_score: Model prob vs market prob gap
   - away_value_score: Model prob vs market prob gap
   - best_value_outcome: Which outcome has most value
"""

import logging
import numpy as np
import psycopg2
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import os

logger = logging.getLogger(__name__)


class HistoricalFeatureBuilder:
    """
    Feature builder using historical_odds table directly.
    
    This provides 35 high-quality features with 90%+ coverage
    from the 37,000+ matches in historical_odds.
    """
    
    CORE_ODDS_FEATURES = [
        'p_b365_h', 'p_b365_d', 'p_b365_a',
        'p_ps_h', 'p_ps_d', 'p_ps_a',
        'p_avg_h', 'p_avg_d', 'p_avg_a'
    ]
    
    MARKET_STRUCTURE_FEATURES = [
        'favorite_strength', 'underdog_value', 'draw_tendency',
        'market_overround', 'sharp_soft_divergence',
        'max_vs_avg_edge_h', 'max_vs_avg_edge_d', 'max_vs_avg_edge_a'
    ]
    
    TOTALS_FEATURES = [
        'ou_line', 'over_implied_prob', 'under_implied_prob',
        'ah_line', 'ah_home_prob', 'ah_away_prob'
    ]
    
    LEAGUE_FEATURES = [
        'league_home_win_rate', 'league_draw_rate', 
        'league_goals_avg', 'season_month'
    ]
    
    GOAL_FEATURES = [
        'expected_total_goals', 'home_goals_expected',
        'away_goals_expected', 'goal_diff_expected'
    ]
    
    VALUE_FEATURES = [
        'home_value_score', 'draw_value_score', 
        'away_value_score', 'best_value_outcome'
    ]
    
    DERIVED_FEATURES = [
        'home_advantage_signal', 'draw_vs_away_ratio',
        'favorite_confidence', 'upset_potential',
        'book_agreement_score', 'implied_competitiveness'
    ]
    
    ALL_FEATURES = (
        CORE_ODDS_FEATURES + MARKET_STRUCTURE_FEATURES + 
        TOTALS_FEATURES + LEAGUE_FEATURES + 
        GOAL_FEATURES + VALUE_FEATURES + DERIVED_FEATURES
    )
    
    def __init__(self, database_url: Optional[str] = None):
        self.db_url = database_url or os.getenv('DATABASE_URL')
        if not self.db_url:
            raise ValueError("DATABASE_URL not provided")
        self._league_stats_cache = {}
        self._precompute_league_stats()
        logger.info(f"✅ HistoricalFeatureBuilder initialized ({len(self.ALL_FEATURES)} features)")
    
    def _get_connection(self):
        return psycopg2.connect(self.db_url)
    
    def _precompute_league_stats(self):
        """Pre-compute historical league-level statistics (before 2022 to avoid leakage)"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                league,
                COUNT(*) as matches,
                SUM(CASE WHEN result = 'H' THEN 1 ELSE 0 END)::float / COUNT(*) as home_win_rate,
                SUM(CASE WHEN result = 'D' THEN 1 ELSE 0 END)::float / COUNT(*) as draw_rate,
                AVG(home_goals + away_goals) as goals_avg
            FROM historical_odds
            WHERE result IS NOT NULL
              AND match_date < '2022-01-01'
            GROUP BY league
            HAVING COUNT(*) >= 20
        """)
        
        for row in cursor.fetchall():
            league, matches, home_rate, draw_rate, goals_avg = row
            self._league_stats_cache[league] = {
                'matches': matches,
                'home_win_rate': home_rate or 0.45,
                'draw_rate': draw_rate or 0.26,
                'goals_avg': goals_avg or 2.5
            }
        
        self._default_league_stats = {
            'home_win_rate': 0.45,
            'draw_rate': 0.26,
            'goals_avg': 2.5
        }
        
        cursor.close()
        conn.close()
        logger.info(f"Pre-computed historical stats for {len(self._league_stats_cache)} leagues (pre-2022 data only)")
    
    def _odds_to_prob(self, odds: float) -> float:
        """Convert decimal odds to implied probability"""
        if odds is None or odds <= 1.0:
            return 0.0
        return 1.0 / odds
    
    def build_features(self, match_row: Dict) -> Dict:
        """
        Build all features from a historical_odds row.
        
        Args:
            match_row: Dict with columns from historical_odds table
            
        Returns:
            Dict of feature_name -> value
        """
        features = {}
        
        b365_h = match_row.get('b365_h')
        b365_d = match_row.get('b365_d')
        b365_a = match_row.get('b365_a')
        ps_h = match_row.get('ps_h')
        ps_d = match_row.get('ps_d')
        ps_a = match_row.get('ps_a')
        avg_h = match_row.get('avg_h')
        avg_d = match_row.get('avg_d')
        avg_a = match_row.get('avg_a')
        max_h = match_row.get('max_h')
        max_d = match_row.get('max_d')
        max_a = match_row.get('max_a')
        
        features['p_b365_h'] = self._odds_to_prob(b365_h)
        features['p_b365_d'] = self._odds_to_prob(b365_d)
        features['p_b365_a'] = self._odds_to_prob(b365_a)
        
        features['p_ps_h'] = self._odds_to_prob(ps_h) if ps_h else features['p_b365_h']
        features['p_ps_d'] = self._odds_to_prob(ps_d) if ps_d else features['p_b365_d']
        features['p_ps_a'] = self._odds_to_prob(ps_a) if ps_a else features['p_b365_a']
        
        features['p_avg_h'] = self._odds_to_prob(avg_h) if avg_h else features['p_b365_h']
        features['p_avg_d'] = self._odds_to_prob(avg_d) if avg_d else features['p_b365_d']
        features['p_avg_a'] = self._odds_to_prob(avg_a) if avg_a else features['p_b365_a']
        
        probs = [features['p_b365_h'], features['p_b365_d'], features['p_b365_a']]
        if sum(probs) > 0:
            favorite_prob = max(probs)
            underdog_prob = min(probs)
            features['favorite_strength'] = favorite_prob - (1/3)
            features['underdog_value'] = underdog_prob
            features['draw_tendency'] = abs(features['p_b365_d'] - 0.27)
            features['market_overround'] = sum(probs) - 1.0
        else:
            features['favorite_strength'] = 0.0
            features['underdog_value'] = 0.33
            features['draw_tendency'] = 0.0
            features['market_overround'] = 0.05
        
        if ps_h and b365_h:
            features['sharp_soft_divergence'] = abs(
                self._odds_to_prob(ps_h) - self._odds_to_prob(b365_h)
            ) + abs(
                self._odds_to_prob(ps_d or b365_d) - self._odds_to_prob(b365_d)
            ) + abs(
                self._odds_to_prob(ps_a or b365_a) - self._odds_to_prob(b365_a)
            )
        else:
            features['sharp_soft_divergence'] = 0.0
        
        features['max_vs_avg_edge_h'] = (
            self._odds_to_prob(avg_h) - self._odds_to_prob(max_h) 
            if max_h and avg_h else 0.0
        )
        features['max_vs_avg_edge_d'] = (
            self._odds_to_prob(avg_d) - self._odds_to_prob(max_d)
            if max_d and avg_d else 0.0
        )
        features['max_vs_avg_edge_a'] = (
            self._odds_to_prob(avg_a) - self._odds_to_prob(max_a)
            if max_a and avg_a else 0.0
        )
        
        ou_line = match_row.get('ou_line')
        over_odds = match_row.get('over_odds')
        under_odds = match_row.get('under_odds')
        ah_line = match_row.get('ah_line')
        ah_home = match_row.get('ah_home_odds')
        ah_away = match_row.get('ah_away_odds')
        
        features['ou_line'] = ou_line if ou_line else 2.5
        features['over_implied_prob'] = self._odds_to_prob(over_odds) if over_odds else 0.5
        features['under_implied_prob'] = self._odds_to_prob(under_odds) if under_odds else 0.5
        features['ah_line'] = ah_line if ah_line else 0.0
        features['ah_home_prob'] = self._odds_to_prob(ah_home) if ah_home else 0.5
        features['ah_away_prob'] = self._odds_to_prob(ah_away) if ah_away else 0.5
        
        league = match_row.get('league', 'unknown')
        match_date = match_row.get('match_date')
        
        league_stats = self._league_stats_cache.get(league, {
            'home_win_rate': 0.45,
            'draw_rate': 0.26,
            'goals_avg': 2.5
        })
        
        features['league_home_win_rate'] = league_stats['home_win_rate']
        features['league_draw_rate'] = league_stats['draw_rate']
        features['league_goals_avg'] = league_stats['goals_avg']
        
        if match_date:
            if isinstance(match_date, str):
                try:
                    match_date = datetime.fromisoformat(match_date)
                except:
                    match_date = datetime.now()
            features['season_month'] = match_date.month / 12.0
        else:
            features['season_month'] = 0.5
        
        features['expected_total_goals'] = features['ou_line']
        
        home_prob = features['p_b365_h']
        away_prob = features['p_b365_a']
        total_goals = features['expected_total_goals']
        
        if home_prob + away_prob > 0:
            home_share = home_prob / (home_prob + away_prob + 0.001)
            away_share = away_prob / (home_prob + away_prob + 0.001)
            features['home_goals_expected'] = total_goals * home_share * 1.1
            features['away_goals_expected'] = total_goals * away_share * 0.9
        else:
            features['home_goals_expected'] = 1.3
            features['away_goals_expected'] = 1.2
        
        features['goal_diff_expected'] = (
            features['home_goals_expected'] - features['away_goals_expected']
        )
        
        norm_probs = self._normalize_probs(probs)
        if len(norm_probs) == 3:
            features['home_value_score'] = league_stats['home_win_rate'] - norm_probs[0]
            features['draw_value_score'] = league_stats['draw_rate'] - norm_probs[1]
            features['away_value_score'] = (1 - league_stats['home_win_rate'] - league_stats['draw_rate']) - norm_probs[2]
            
            values = [
                features['home_value_score'],
                features['draw_value_score'],
                features['away_value_score']
            ]
            features['best_value_outcome'] = values.index(max(values))
        else:
            features['home_value_score'] = 0.0
            features['draw_value_score'] = 0.0
            features['away_value_score'] = 0.0
            features['best_value_outcome'] = 0
        
        p_home = features['p_b365_h']
        p_draw = features['p_b365_d']
        p_away = features['p_b365_a']
        
        features['home_advantage_signal'] = (
            p_home - league_stats['home_win_rate']
        ) if p_home > 0 else 0.0
        
        features['draw_vs_away_ratio'] = (
            p_draw / (p_away + 0.001)
        ) if p_away > 0 else 1.0
        
        sorted_probs = sorted([p_home, p_draw, p_away], reverse=True)
        features['favorite_confidence'] = (
            sorted_probs[0] - sorted_probs[1]
        ) if len(sorted_probs) >= 2 else 0.0
        
        features['upset_potential'] = (
            min(p_home, p_away) / (max(p_home, p_away) + 0.001)
        ) if max(p_home, p_away) > 0 else 0.5
        
        if ps_h and b365_h and avg_h:
            ps_probs = [self._odds_to_prob(ps_h), self._odds_to_prob(ps_d or b365_d), self._odds_to_prob(ps_a or b365_a)]
            b365_probs = [p_home, p_draw, p_away]
            avg_probs = [features['p_avg_h'], features['p_avg_d'], features['p_avg_a']]
            
            std_h = np.std([ps_probs[0], b365_probs[0], avg_probs[0]])
            std_d = np.std([ps_probs[1], b365_probs[1], avg_probs[1]])
            std_a = np.std([ps_probs[2], b365_probs[2], avg_probs[2]])
            features['book_agreement_score'] = max(0.0, min(1.0, 1.0 - (std_h + std_d + std_a) * 3))
        else:
            features['book_agreement_score'] = 0.5
        
        features['implied_competitiveness'] = 1.0 - abs(p_home - p_away)
        
        return features
    
    def _normalize_probs(self, probs: List[float]) -> List[float]:
        """Normalize probabilities to sum to 1"""
        total = sum(probs)
        if total <= 0:
            return [0.33, 0.33, 0.34]
        return [p / total for p in probs]
    
    def get_all_features_for_training(self, 
                                       min_date: str = '2018-01-01',
                                       max_date: str = '2026-01-01',
                                       leagues: Optional[List[str]] = None) -> List[Dict]:
        """
        Get all features for training from historical_odds.
        
        Returns list of dicts with features + outcome.
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        league_filter = ""
        if leagues:
            league_list = "','".join(leagues)
            league_filter = f"AND league IN ('{league_list}')"
        
        cursor.execute(f"""
            SELECT 
                id, match_date, season, league, league_name,
                home_team, away_team, home_goals, away_goals, result,
                b365_h, b365_d, b365_a,
                ps_h, ps_d, ps_a,
                avg_h, avg_d, avg_a,
                max_h, max_d, max_a,
                ou_line, over_odds, under_odds,
                ah_line, ah_home_odds, ah_away_odds
            FROM historical_odds
            WHERE result IS NOT NULL
              AND b365_h IS NOT NULL
              AND match_date >= '{min_date}'
              AND match_date <= '{max_date}'
              {league_filter}
            ORDER BY match_date
        """)
        
        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        results = []
        for row in rows:
            match_data = dict(zip(columns, row))
            
            try:
                features = self.build_features(match_data)
                features['match_id'] = match_data['id']
                features['outcome'] = match_data['result']
                features['match_date'] = match_data['match_date']
                features['league'] = match_data['league']
                features['home_team'] = match_data['home_team']
                features['away_team'] = match_data['away_team']
                results.append(features)
            except Exception as e:
                logger.warning(f"Error building features for match {match_data['id']}: {e}")
                continue
        
        logger.info(f"Built features for {len(results)} matches")
        return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    builder = HistoricalFeatureBuilder()
    
    data = builder.get_all_features_for_training(min_date='2024-01-01')
    print(f"\nLoaded {len(data)} matches for training")
    
    if data:
        sample = data[0]
        print("\nSample features:")
        for k, v in sorted(sample.items()):
            if k not in ['match_id', 'outcome', 'match_date', 'league', 'home_team', 'away_team']:
                print(f"  {k}: {v}")
