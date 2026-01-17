"""
V3 Ensemble Predictor - Binary Expert Stacked Model
Uses calibrated binary experts + stacked meta-model for predictions
"""

import os
import json
import pickle
import logging
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MODEL_DIR = Path("artifacts/models/v3_full")
BINARY_EXPERTS_DIR = Path("artifacts/models/binary_experts")

BASE_FEATURES = [
    'p_b365_h', 'p_b365_d', 'p_b365_a',
    'p_ps_h', 'p_ps_d', 'p_ps_a',
    'p_avg_h', 'p_avg_d', 'p_avg_a',
    'favorite_strength', 'underdog_value', 'draw_tendency',
    'market_overround', 'sharp_soft_divergence',
    'max_vs_avg_edge_h', 'max_vs_avg_edge_d', 'max_vs_avg_edge_a',
    'league_home_win_rate', 'league_draw_rate', 'league_goals_avg',
    'season_month',
    'expected_total_goals', 'home_goals_expected', 'away_goals_expected', 
    'goal_diff_expected',
    'home_value_score', 'draw_value_score', 'away_value_score',
    'home_advantage_signal', 'draw_vs_away_ratio', 'favorite_confidence',
    'upset_potential', 'book_agreement_score', 'implied_competitiveness'
]

REGIME_FEATURES = [
    'league_draw_regime', 'league_goals_regime',
    'regime_home_stability', 'regime_draw_volatility',
    'odds_skewness', 'favorite_dominance',
    'draw_compression', 'home_favorite_fragility',
    'sharp_draw_signal', 'sharp_away_signal',
    'early_season', 'late_season', 'winter_period', 'draw_season_bias'
]

EXPERT_FEATURES = [
    'expert_home_prob', 'expert_away_prob', 'expert_draw_prob',
    'expert_home_away_diff', 'expert_draw_confidence', 'expert_favorite_spread',
    'expert_norm_home', 'expert_norm_away', 'expert_norm_draw'
]


class V3EnsemblePredictor:
    """V3 Binary Expert Stacked Ensemble Predictor"""
    
    def __init__(self):
        self.model = None
        self.experts = {}
        self.metadata = None
        self._loaded = False
        self._load_models()
    
    def _load_models(self):
        """Load V3 model and binary experts"""
        try:
            model_path = MODEL_DIR / 'model.pkl'
            if model_path.exists():
                with open(model_path, 'rb') as f:
                    self.model = pickle.load(f)
                logger.info("Loaded V3 stacked model")
            
            for expert_type in ['home', 'away', 'draw']:
                model_path = MODEL_DIR / f'{expert_type}_expert.pkl'
                calibrator_path = MODEL_DIR / f'{expert_type}_calibrator.pkl'
                
                if not model_path.exists():
                    model_path = BINARY_EXPERTS_DIR / f'{expert_type}_expert.pkl'
                    calibrator_path = BINARY_EXPERTS_DIR / f'{expert_type}_calibrator.pkl'
                
                if model_path.exists() and calibrator_path.exists():
                    with open(model_path, 'rb') as f:
                        model = pickle.load(f)
                    with open(calibrator_path, 'rb') as f:
                        calibrator = pickle.load(f)
                    
                    self.experts[expert_type] = {
                        'model': model,
                        'calibrator': calibrator
                    }
            
            logger.info(f"Loaded {len(self.experts)} binary experts")
            
            metadata_path = MODEL_DIR / 'metadata.json'
            if metadata_path.exists():
                with open(metadata_path) as f:
                    self.metadata = json.load(f)
            
            self._loaded = bool(self.model) or len(self.experts) == 3
            
        except Exception as e:
            logger.error(f"Error loading V3 models: {e}")
            self._loaded = False
    
    def is_loaded(self) -> bool:
        return self._loaded
    
    def get_model_info(self) -> Dict:
        if self.metadata:
            return {
                'version': self.metadata.get('version', 'v3_ensemble'),
                'trained_at': self.metadata.get('trained_at'),
                'accuracy': self.metadata.get('metrics', {}).get('accuracy'),
                'logloss': self.metadata.get('metrics', {}).get('logloss'),
                'feature_count': len(self.metadata.get('features', {}).get('all', [])),
                'experts_loaded': len(self.experts)
            }
        return {'version': 'v3_ensemble', 'status': 'loaded' if self._loaded else 'not_loaded'}
    
    def _compute_expert_predictions(self, features: Dict) -> Dict[str, float]:
        """Get calibrated predictions from binary experts"""
        
        feature_values = []
        for col in BASE_FEATURES:
            val = features.get(col, 0.0)
            if val is None:
                val = 0.0
            feature_values.append(float(val))
        
        X = np.array([feature_values])
        
        expert_probs = {}
        for expert_type, expert in self.experts.items():
            raw_proba = expert['model'].predict(X)[0]
            calibrated_proba = expert['calibrator'].predict([raw_proba])[0]
            calibrated_proba = np.clip(calibrated_proba, 0.01, 0.99)
            expert_probs[expert_type] = float(calibrated_proba)
        
        return expert_probs
    
    def _compute_regime_features(self, features: Dict) -> Dict[str, float]:
        """Compute regime features from base features"""
        
        regime = {}
        
        p_home = features.get('p_b365_h', 0.33)
        p_draw = features.get('p_b365_d', 0.33)
        p_away = features.get('p_b365_a', 0.33)
        
        sorted_probs = sorted([p_home, p_draw, p_away], reverse=True)
        regime['odds_skewness'] = sorted_probs[0] - sorted_probs[2]
        regime['favorite_dominance'] = sorted_probs[0] / (sorted_probs[1] + 0.001)
        
        if 0.2 < p_draw < 0.4:
            draw_comp = abs(p_draw - 0.30) * -1 + 0.1
        else:
            draw_comp = abs(p_draw - 0.30) * -3
        regime['draw_compression'] = max(0, min(1, draw_comp + 0.5))
        
        regime['home_favorite_fragility'] = 0.0
        if p_home > 0.5:
            book_agree = features.get('book_agreement_score', 0.5)
            regime['home_favorite_fragility'] = (p_home - 0.5) * (1 - book_agree)
        
        ps_draw = features.get('p_ps_d', p_draw)
        ps_away = features.get('p_ps_a', p_away)
        avg_draw = features.get('p_avg_d', p_draw)
        avg_away = features.get('p_avg_a', p_away)
        
        regime['sharp_draw_signal'] = (ps_draw - avg_draw) * 3
        regime['sharp_away_signal'] = (ps_away - avg_away) * 3
        
        month = features.get('season_month', 6)
        regime['early_season'] = 1.0 if month in [8, 9] else 0.0
        regime['late_season'] = 1.0 if month in [4, 5] else 0.0
        regime['winter_period'] = 1.0 if month in [12, 1, 2] else 0.0
        
        regime['draw_season_bias'] = 0.0
        if month in [10, 11, 3]:
            regime['draw_season_bias'] = 0.05
        elif month in [12, 1, 2]:
            regime['draw_season_bias'] = 0.03
        
        regime['league_draw_regime'] = 0.0
        regime['league_goals_regime'] = 0.0
        regime['regime_home_stability'] = 0.5
        regime['regime_draw_volatility'] = 0.0
        
        return regime
    
    def predict(self, features: Dict) -> Dict:
        """
        Make V3 prediction using binary expert ensemble
        
        Returns:
            Dict with probabilities, prediction, confidence, and expert breakdown
        """
        if not self._loaded:
            return {
                'error': 'V3 model not loaded',
                'probabilities': {'home': 0.33, 'draw': 0.33, 'away': 0.33},
                'prediction': 'H',
                'confidence': 0.0
            }
        
        expert_probs = self._compute_expert_predictions(features)
        
        expert_home = expert_probs.get('home', 0.43)
        expert_away = expert_probs.get('away', 0.31)
        expert_draw = expert_probs.get('draw', 0.26)
        
        draw_boost = 1.10
        total = expert_home + expert_away + expert_draw * draw_boost
        
        normalized_home = expert_home / total
        normalized_away = expert_away / total
        normalized_draw = (expert_draw * draw_boost) / total
        
        if self.model:
            regime_features = self._compute_regime_features(features)
            
            stacked_features = {}
            for col in BASE_FEATURES:
                stacked_features[col] = features.get(col, 0.0)
            
            stacked_features['expert_home_prob'] = expert_home
            stacked_features['expert_away_prob'] = expert_away
            stacked_features['expert_draw_prob'] = expert_draw
            stacked_features['expert_home_away_diff'] = expert_home - expert_away
            stacked_features['expert_draw_confidence'] = expert_draw * features.get('implied_competitiveness', 0.5)
            stacked_features['expert_favorite_spread'] = abs(expert_home - expert_away)
            stacked_features['expert_norm_home'] = normalized_home
            stacked_features['expert_norm_away'] = normalized_away
            stacked_features['expert_norm_draw'] = normalized_draw
            
            stacked_features.update(regime_features)
            
            all_features = BASE_FEATURES + EXPERT_FEATURES + REGIME_FEATURES
            feature_values = []
            for col in all_features:
                val = stacked_features.get(col, 0.0)
                if val is None:
                    val = 0.0
                feature_values.append(float(val))
            
            X = np.array([feature_values])
            proba = self.model.predict(X)[0]
            
            final_home = float(proba[0])
            final_draw = float(proba[1])
            final_away = float(proba[2])
        else:
            final_home = normalized_home
            final_draw = normalized_draw
            final_away = normalized_away
        
        outcomes = {'H': final_home, 'D': final_draw, 'A': final_away}
        prediction = max(outcomes, key=outcomes.get)
        confidence = outcomes[prediction] - sorted(outcomes.values())[-2]
        
        return {
            'probabilities': {
                'home': round(final_home, 4),
                'draw': round(final_draw, 4),
                'away': round(final_away, 4)
            },
            'prediction': prediction,
            'confidence': round(confidence, 4),
            'expert_breakdown': {
                'home_expert': round(expert_home, 4),
                'away_expert': round(expert_away, 4),
                'draw_expert': round(expert_draw, 4)
            },
            'model_version': 'v3_ensemble'
        }
    
    def predict_batch(self, feature_list: List[Dict]) -> List[Dict]:
        """Make predictions for multiple matches"""
        return [self.predict(features) for features in feature_list]


_predictor_instance = None

def get_v3_ensemble_predictor() -> V3EnsemblePredictor:
    """Get singleton V3 ensemble predictor instance"""
    global _predictor_instance
    if _predictor_instance is None:
        _predictor_instance = V3EnsemblePredictor()
    return _predictor_instance
