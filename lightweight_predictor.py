"""
Lightweight ML Predictor - No timeouts, fast predictions
"""
import numpy as np
import joblib
import json
import os
from typing import Dict, Any

class LightweightPredictor:
    """Fast ML predictor using pre-trained models"""
    
    def __init__(self):
        self.models = {}
        self.scaler = None
        self.is_loaded = False
        self._load_models()
    
    def _load_models(self):
        """Load pre-trained models if available"""
        try:
            model_files = {
                'RandomForest': 'models/randomforest_model.joblib',
                'GradientBoosting': 'models/gradientboosting_model.joblib', 
                'LogisticRegression': 'models/logisticregression_model.joblib'
            }
            
            scaler_file = 'models/scaler.joblib'
            
            # Load models
            for name, file_path in model_files.items():
                if os.path.exists(file_path):
                    self.models[name] = joblib.load(file_path)
            
            # Load scaler
            if os.path.exists(scaler_file):
                self.scaler = joblib.load(scaler_file)
            
            self.is_loaded = len(self.models) > 0 and self.scaler is not None
            
            if self.is_loaded:
                print(f"Loaded {len(self.models)} pre-trained models")
            
        except Exception as e:
            print(f"Model loading failed: {e}")
            self.is_loaded = False
    
    def quick_predict(self, features: Dict[str, float]) -> Dict[str, Any]:
        """Generate prediction quickly without timeouts"""
        
        if not self.is_loaded:
            return self._heuristic_prediction(features)
        
        try:
            # Prepare feature vector
            feature_vector = self._prepare_features(features)
            
            # Scale features
            X_scaled = self.scaler.transform([feature_vector])
            
            # Get predictions from all models
            predictions = {}
            for name, model in self.models.items():
                try:
                    proba = model.predict_proba(X_scaled)[0]
                    predictions[name] = {
                        'away_win': proba[0],
                        'draw': proba[1],
                        'home_win': proba[2]
                    }
                except:
                    # Fallback if model fails
                    predictions[name] = {
                        'away_win': 0.25,
                        'draw': 0.25,
                        'home_win': 0.50
                    }
            
            # Ensemble prediction
            avg_proba = {
                'away_win': np.mean([p['away_win'] for p in predictions.values()]),
                'draw': np.mean([p['draw'] for p in predictions.values()]),
                'home_win': np.mean([p['home_win'] for p in predictions.values()])
            }
            
            # Calculate confidence
            max_prob = max(avg_proba.values())
            confidence = min(max_prob * 1.2, 1.0)
            
            # Recommended bet
            best_outcome = max(avg_proba, key=avg_proba.get)
            if best_outcome == 'home_win':
                recommended_bet = "Home Win"
            elif best_outcome == 'away_win':
                recommended_bet = "Away Win"
            else:
                recommended_bet = "Draw"
            
            return {
                'home_win_probability': round(avg_proba['home_win'], 3),
                'draw_probability': round(avg_proba['draw'], 3),
                'away_win_probability': round(avg_proba['away_win'], 3),
                'confidence_score': round(confidence, 3),
                'recommended_bet': recommended_bet,
                'model_predictions': predictions
            }
            
        except Exception as e:
            print(f"Prediction failed: {e}")
            return self._heuristic_prediction(features)
    
    def _prepare_features(self, features: Dict[str, float]) -> list:
        """Prepare feature vector from input features"""
        feature_names = [
            'home_goals_per_game', 'away_goals_per_game',
            'home_goals_against_per_game', 'away_goals_against_per_game',
            'home_win_percentage', 'away_win_percentage',
            'home_form_points', 'away_form_points',
            'home_goals_last_5', 'away_goals_last_5',
            'h2h_home_wins', 'h2h_away_wins', 'h2h_avg_goals',
            'home_key_injuries', 'away_key_injuries',
            'goal_difference_home', 'goal_difference_away',
            'form_difference', 'strength_difference', 'total_goals_tendency',
            'home_player_performance', 'away_player_performance',
            'player_performance_diff', 'key_player_advantage'
        ]
        
        feature_vector = []
        for name in feature_names:
            value = features.get(name, 0.0)
            feature_vector.append(float(value))
        
        return feature_vector
    
    def _heuristic_prediction(self, features: Dict[str, float]) -> Dict[str, Any]:
        """Heuristic prediction when models unavailable"""
        
        # Calculate home advantage
        home_strength = (
            features.get('home_win_percentage', 0.5) +
            features.get('home_form_points', 5) / 15 +
            features.get('goal_difference_home', 0) / 2
        ) / 3
        
        away_strength = (
            features.get('away_win_percentage', 0.3) +
            features.get('away_form_points', 5) / 15 +
            abs(features.get('goal_difference_away', 0)) / 2
        ) / 3
        
        # Home advantage factor
        home_advantage = 0.15
        
        # Calculate probabilities
        home_prob = min(0.85, max(0.15, home_strength + home_advantage))
        away_prob = min(0.70, max(0.10, away_strength))
        draw_prob = max(0.15, 1.0 - home_prob - away_prob)
        
        # Normalize
        total = home_prob + draw_prob + away_prob
        home_prob /= total
        draw_prob /= total
        away_prob /= total
        
        confidence = abs(home_prob - away_prob)
        
        best_outcome = max([
            ('home_win', home_prob),
            ('draw', draw_prob),
            ('away_win', away_prob)
        ], key=lambda x: x[1])
        
        if best_outcome[0] == 'home_win':
            recommended_bet = "Home Win"
        elif best_outcome[0] == 'away_win':
            recommended_bet = "Away Win"
        else:
            recommended_bet = "Draw"
        
        return {
            'home_win_probability': round(home_prob, 3),
            'draw_probability': round(draw_prob, 3),
            'away_win_probability': round(away_prob, 3),
            'confidence_score': round(confidence, 3),
            'recommended_bet': recommended_bet,
            'model_predictions': {'heuristic': {
                'home_win': home_prob,
                'draw': draw_prob,
                'away_win': away_prob
            }}
        }

def test_lightweight_predictor():
    """Test the lightweight predictor"""
    predictor = LightweightPredictor()
    
    # Test features
    test_features = {
        'home_goals_per_game': 1.8,
        'away_goals_per_game': 1.1,
        'home_goals_against_per_game': 0.9,
        'away_goals_against_per_game': 1.4,
        'home_win_percentage': 0.65,
        'away_win_percentage': 0.25,
        'home_form_points': 16,
        'away_form_points': 5,
        'home_goals_last_5': 10,
        'away_goals_last_5': 3,
        'h2h_home_wins': 6,
        'h2h_away_wins': 1,
        'h2h_avg_goals': 3.1,
        'home_key_injuries': 0,
        'away_key_injuries': 2,
        'goal_difference_home': 0.9,
        'goal_difference_away': -0.3,
        'form_difference': 11.0,
        'strength_difference': 0.4,
        'total_goals_tendency': 2.9,
        'home_player_performance': 0.82,
        'away_player_performance': 0.48,
        'player_performance_diff': 0.34,
        'key_player_advantage': 1.5
    }
    
    prediction = predictor.quick_predict(test_features)
    
    print("Lightweight Prediction Results:")
    print(f"Home Win: {prediction['home_win_probability']:.1%}")
    print(f"Draw: {prediction['draw_probability']:.1%}")
    print(f"Away Win: {prediction['away_win_probability']:.1%}")
    print(f"Confidence: {prediction['confidence_score']:.1%}")
    print(f"Recommended: {prediction['recommended_bet']}")
    
    return prediction

if __name__ == "__main__":
    test_lightweight_predictor()