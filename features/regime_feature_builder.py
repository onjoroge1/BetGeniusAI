"""
Regime and Temporal Feature Builder - Phase 3
Adds market shape, temporal drift, and league regime features
"""

import os
import logging
from typing import Dict, List, Optional
from datetime import datetime

import numpy as np
import pandas as pd
import psycopg2

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class RegimeFeatureBuilder:
    """Builds temporal and regime features for V3 model"""
    
    def __init__(self):
        self.db_url = os.environ.get('DATABASE_URL')
        self._league_regime_cache = {}
        self._precompute_league_regimes()
    
    def _get_connection(self):
        return psycopg2.connect(self.db_url)
    
    def _precompute_league_regimes(self):
        """Compute league-specific regime characteristics from historical data"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                league,
                EXTRACT(YEAR FROM match_date) as year,
                COUNT(*) as matches,
                SUM(CASE WHEN result = 'H' THEN 1 ELSE 0 END)::float / NULLIF(COUNT(*), 0) as home_rate,
                SUM(CASE WHEN result = 'D' THEN 1 ELSE 0 END)::float / NULLIF(COUNT(*), 0) as draw_rate,
                AVG(home_goals + away_goals) as goals_avg,
                STDDEV(home_goals + away_goals) as goals_std
            FROM historical_odds
            WHERE result IS NOT NULL AND match_date < '2022-01-01'
            GROUP BY league, EXTRACT(YEAR FROM match_date)
            HAVING COUNT(*) >= 20
        """)
        
        for row in cursor.fetchall():
            league, year, matches, home_rate, draw_rate, goals_avg, goals_std = row
            if league not in self._league_regime_cache:
                self._league_regime_cache[league] = []
            
            self._league_regime_cache[league].append({
                'year': int(year),
                'matches': matches,
                'home_rate': home_rate or 0.45,
                'draw_rate': draw_rate or 0.26,
                'goals_avg': goals_avg or 2.5,
                'goals_std': goals_std or 1.2
            })
        
        cursor.close()
        conn.close()
        logger.info(f"Pre-computed regime data for {len(self._league_regime_cache)} leagues")
    
    def compute_regime_features(self, features: Dict) -> Dict:
        """Add regime-based features to existing feature dictionary"""
        
        league = features.get('league', '')
        
        features['league_draw_regime'] = 0.0
        features['league_goals_regime'] = 0.0
        features['regime_home_stability'] = 0.5
        features['regime_draw_volatility'] = 0.0
        
        if league in self._league_regime_cache:
            regime_data = self._league_regime_cache[league]
            if len(regime_data) >= 2:
                home_rates = [float(r['home_rate']) for r in regime_data]
                draw_rates = [float(r['draw_rate']) for r in regime_data]
                goals_avgs = [float(r['goals_avg']) for r in regime_data]
                
                avg_draw = np.mean(draw_rates)
                std_draw = np.std(draw_rates)
                
                features['league_draw_regime'] = float(avg_draw - 0.26)
                features['league_goals_regime'] = float(np.mean(goals_avgs) - 2.5)
                features['regime_home_stability'] = float(max(0, 1 - np.std(home_rates) * 5))
                features['regime_draw_volatility'] = float(std_draw * 5)
        
        return features
    
    def compute_market_shape_features(self, features: Dict) -> Dict:
        """Compute market shape features from odds"""
        
        p_home = features.get('p_b365_h', 0.33)
        p_draw = features.get('p_b365_d', 0.33)
        p_away = features.get('p_b365_a', 0.33)
        
        ps_home = features.get('p_ps_h', p_home)
        ps_draw = features.get('p_ps_d', p_draw)
        ps_away = features.get('p_ps_a', p_away)
        
        avg_home = features.get('p_avg_h', p_home)
        avg_draw = features.get('p_avg_d', p_draw)
        avg_away = features.get('p_avg_a', p_away)
        
        sorted_probs = sorted([p_home, p_draw, p_away], reverse=True)
        features['odds_skewness'] = sorted_probs[0] - sorted_probs[2]
        features['favorite_dominance'] = sorted_probs[0] / (sorted_probs[1] + 0.001)
        
        if p_draw > 0.2 and p_draw < 0.4:
            draw_compression = abs(p_draw - 0.30) * -1 + 0.1
        else:
            draw_compression = abs(p_draw - 0.30) * -3
        features['draw_compression'] = max(0, min(1, draw_compression + 0.5))
        
        features['home_favorite_fragility'] = 0.0
        if p_home > 0.5:
            features['home_favorite_fragility'] = (p_home - 0.5) * (1 - features.get('book_agreement_score', 0.5))
        
        sharp_soft_h = ps_home - avg_home
        sharp_soft_d = ps_draw - avg_draw  
        sharp_soft_a = ps_away - avg_away
        
        features['sharp_draw_signal'] = sharp_soft_d * 3
        features['sharp_away_signal'] = sharp_soft_a * 3
        
        return features
    
    def compute_timing_features(self, features: Dict) -> Dict:
        """Compute timing-based features"""
        
        month = features.get('season_month', 6)
        
        features['early_season'] = 1.0 if month in [8, 9] else 0.0
        features['late_season'] = 1.0 if month in [4, 5] else 0.0
        features['winter_period'] = 1.0 if month in [12, 1, 2] else 0.0
        
        features['draw_season_bias'] = 0.0
        if month in [10, 11, 3]:
            features['draw_season_bias'] = 0.05
        elif month in [12, 1, 2]:
            features['draw_season_bias'] = 0.03
        
        return features
    
    def add_all_regime_features(self, features: Dict) -> Dict:
        """Add all Phase 3 regime/temporal features"""
        
        features = self.compute_regime_features(features)
        features = self.compute_market_shape_features(features)
        features = self.compute_timing_features(features)
        
        return features
    
    def get_feature_names(self) -> List[str]:
        """Get list of all regime feature names"""
        return [
            'league_draw_regime',
            'league_goals_regime', 
            'regime_home_stability',
            'regime_draw_volatility',
            'odds_skewness',
            'favorite_dominance',
            'draw_compression',
            'home_favorite_fragility',
            'sharp_draw_signal',
            'sharp_away_signal',
            'early_season',
            'late_season',
            'winter_period',
            'draw_season_bias'
        ]
