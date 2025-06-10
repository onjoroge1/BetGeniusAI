"""
BetGenius AI Backend - Machine Learning Prediction Engine
Ensemble ML models for football match outcome prediction
"""

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import cross_val_score
import joblib
import json
import os
import logging
from typing import Dict, List, Tuple, Any

from utils.config import settings

logger = logging.getLogger(__name__)

# Lazy import to avoid initialization issues
def get_database_manager():
    try:
        from models.database import DatabaseManager
        return DatabaseManager()
    except Exception as e:
        logger.warning(f"Database not available: {e}")
        return None

class MLPredictor:
    """Ensemble ML prediction engine for football matches"""
    
    def __init__(self):
        self.models = {}
        self.scaler = StandardScaler()
        self.feature_names = [
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
        self.is_trained = False
        self._initialize_models()
        # Defer training to avoid blocking server startup
        # Training will happen on first prediction request or manual trigger
    
    def _initialize_models(self):
        """Initialize the ensemble of ML models"""
        self.models = {
            'random_forest': RandomForestClassifier(
                n_estimators=100, 
                max_depth=10, 
                random_state=42,
                class_weight='balanced'
            ),
            'gradient_boosting': GradientBoostingClassifier(
                n_estimators=100,
                learning_rate=0.1,
                max_depth=6,
                random_state=42
            ),
            'logistic_regression': LogisticRegression(
                class_weight='balanced',
                random_state=42,
                max_iter=1000
            )
        }
    
    def _train_models(self):
        """Train models using sample data"""
        try:
            # Load sample training data
            training_data = self._load_training_data()
            if not training_data:
                logger.warning("No training data available, using default model parameters")
                self.is_trained = False
                return
            
            # Extract features properly handling both dict and JSON string formats
            features_list = []
            feature_keys = None
            
            for sample in training_data:
                features = sample['features']
                if isinstance(features, str):
                    features = json.loads(features)
                
                # Establish consistent feature ordering
                if feature_keys is None:
                    feature_keys = sorted(features.keys())
                
                # Extract features in consistent order
                feature_values = [features.get(key, 0.0) for key in feature_keys]
                features_list.append(feature_values)
            
            X = np.array(features_list, dtype=np.float32)
            
            # Convert string outcomes to numeric (database format: 'Home', 'Draw', 'Away')
            outcome_map = {'Home': 0, 'Draw': 1, 'Away': 2}
            y_list = []
            for sample in training_data:
                outcome = sample.get('outcome', 'Home')
                if isinstance(outcome, str):
                    y_list.append(outcome_map.get(outcome, 0))
                else:
                    y_list.append(outcome)
            y = np.array(y_list)
            
            # Update feature names to match authentic data
            if feature_keys:
                self.feature_names = feature_keys
                logger.info(f"Using authentic data features: {len(self.feature_names)} features from database")
            
            if X.shape[1] < 5:
                logger.warning(f"Insufficient features for training: {X.shape[1]}")
                self.is_trained = False
                return
            
            # Scale features
            X_scaled = self.scaler.fit_transform(X)
            
            # Train each model
            for name, model in self.models.items():
                try:
                    model.fit(X_scaled, y)
                    
                    # Validate with cross-validation (adjust cv based on data size)
                    cv_folds = min(5, len(np.unique(y)), len(X) // 2)
                    if cv_folds >= 2:
                        cv_scores = cross_val_score(model, X_scaled, y, cv=cv_folds, scoring='accuracy')
                        logger.info(f"{name} - CV Accuracy: {cv_scores.mean():.3f} (+/- {cv_scores.std() * 2:.3f})")
                    else:
                        logger.info(f"{name} - Trained successfully (insufficient data for CV)")
                    
                except Exception as e:
                    logger.error(f"Failed to train {name}: {e}")
            
            self.is_trained = True
            logger.info("ML models trained successfully")
            
        except Exception as e:
            logger.error(f"Failed to train models: {e}")
            self.is_trained = False
    
    def _load_training_data(self) -> List[Dict]:
        """Load training data from PostgreSQL database or files"""
        try:
            # Try database first
            db_manager = get_database_manager()
            if db_manager:
                db_data = db_manager.load_training_data()
                if db_data:
                    logger.info(f"Loaded {len(db_data)} authentic samples from database")
                    return db_data
            
            # Fallback to file-based data
            data_file = "data/training_data.json"
            if os.path.exists(data_file):
                with open(data_file, 'r') as f:
                    data = json.load(f)
                logger.info(f"Loaded {len(data)} authentic training samples from file")
                return data
            
            # Last resort: sample data
            sample_file = "data/sample_data.json"
            if os.path.exists(sample_file):
                with open(sample_file, 'r') as f:
                    data = json.load(f)
                logger.warning(f"Using sample data: {len(data)} samples. Collect real data for better accuracy.")
                return data
            
            logger.error("No training data available. Use /admin/collect-training-data endpoint.")
            return []
            
        except Exception as e:
            logger.error(f"Failed to load training data: {e}")
            return []
    
    def predict_match_outcome(self, features: Dict[str, float]) -> Dict[str, Any]:
        """
        Predict match outcome using ensemble of ML models
        Returns probabilities and recommendations
        """
        try:
            # Train models if not already trained
            if not self.is_trained:
                logger.info("Training models on first prediction request...")
                self._train_models()
            
            # Prepare feature vector
            feature_vector = self._prepare_features(features)
            
            if not self.is_trained:
                # Fallback to heuristic prediction if training failed
                return self._heuristic_prediction(features)
            
            # Get predictions from all models
            predictions = {}
            probabilities = {}
            
            X_scaled = self.scaler.transform([feature_vector])
            
            for name, model in self.models.items():
                try:
                    # Get class probabilities
                    proba = model.predict_proba(X_scaled)[0]
                    
                    # Map to outcome classes (0=away_win, 1=draw, 2=home_win)
                    probabilities[name] = {
                        'away_win': proba[0],
                        'draw': proba[1], 
                        'home_win': proba[2]
                    }
                    
                except Exception as e:
                    logger.error(f"Prediction failed for {name}: {e}")
                    # Fallback probabilities
                    probabilities[name] = {
                        'away_win': 0.25,
                        'draw': 0.25,
                        'home_win': 0.50
                    }
            
            # Ensemble prediction using weighted average
            ensemble_proba = self._ensemble_prediction(probabilities)
            
            # Calculate confidence score
            confidence_score = self._calculate_confidence(probabilities, features)
            
            # Determine recommended bet
            recommended_bet = self._get_recommended_bet(ensemble_proba, confidence_score)
            
            return {
                'home_win_probability': round(ensemble_proba['home_win'], 3),
                'draw_probability': round(ensemble_proba['draw'], 3), 
                'away_win_probability': round(ensemble_proba['away_win'], 3),
                'confidence_score': round(confidence_score, 3),
                'recommended_bet': recommended_bet,
                'model_predictions': probabilities
            }
            
        except Exception as e:
            logger.error(f"Prediction failed: {e}")
            return self._fallback_prediction(features)
    
    def predict_additional_markets(self, features: Dict[str, float]) -> Dict[str, Any]:
        """Predict additional betting markets"""
        try:
            # Over/Under 2.5 goals prediction
            total_goals_expected = features.get('total_goals_tendency', 2.5)
            over_2_5_prob = min(0.95, max(0.05, (total_goals_expected - 1.5) / 3.0))
            
            # Both teams to score prediction
            home_goals_avg = features.get('home_goals_per_game', 1.5)
            away_goals_avg = features.get('away_goals_per_game', 1.0)
            both_score_prob = min(0.95, max(0.05, (home_goals_avg + away_goals_avg) / 4.0))
            
            # Asian Handicap prediction (simplified)
            strength_diff = features.get('strength_difference', 0.0)
            handicap_home_prob = 0.5 + (strength_diff * 0.3)
            handicap_home_prob = min(0.95, max(0.05, handicap_home_prob))
            
            return {
                'total_goals': {
                    'over_2_5': round(over_2_5_prob, 3),
                    'under_2_5': round(1 - over_2_5_prob, 3)
                },
                'both_teams_score': {
                    'yes': round(both_score_prob, 3),
                    'no': round(1 - both_score_prob, 3)
                },
                'asian_handicap': {
                    'home_handicap': round(handicap_home_prob, 3),
                    'away_handicap': round(1 - handicap_home_prob, 3)
                }
            }
            
        except Exception as e:
            logger.error(f"Additional markets prediction failed: {e}")
            return {
                'total_goals': {'over_2_5': 0.55, 'under_2_5': 0.45},
                'both_teams_score': {'yes': 0.60, 'no': 0.40},
                'asian_handicap': {'home_handicap': 0.52, 'away_handicap': 0.48}
            }
    
    def _prepare_features(self, features: Dict[str, float]) -> List[float]:
        """Prepare feature vector for ML models"""
        feature_vector = []
        for feature_name in self.feature_names:
            value = features.get(feature_name, 0.0)
            # Handle potential string values
            try:
                feature_vector.append(float(value))
            except (ValueError, TypeError):
                feature_vector.append(0.0)
        
        return feature_vector
    
    def _ensemble_prediction(self, probabilities: Dict[str, Dict]) -> Dict[str, float]:
        """Combine predictions from multiple models using weighted average"""
        weights = settings.ENSEMBLE_WEIGHTS
        
        ensemble_proba = {'home_win': 0.0, 'draw': 0.0, 'away_win': 0.0}
        total_weight = 0.0
        
        for model_name, proba in probabilities.items():
            weight = weights.get(model_name, 0.33)  # Default equal weight
            
            for outcome in ensemble_proba:
                ensemble_proba[outcome] += proba[outcome] * weight
            
            total_weight += weight
        
        # Normalize
        if total_weight > 0:
            for outcome in ensemble_proba:
                ensemble_proba[outcome] /= total_weight
        
        # Ensure probabilities sum to 1
        total_prob = sum(ensemble_proba.values())
        if total_prob > 0:
            for outcome in ensemble_proba:
                ensemble_proba[outcome] /= total_prob
        
        return ensemble_proba
    
    def _calculate_confidence(self, probabilities: Dict, features: Dict) -> float:
        """Calculate prediction confidence based on model agreement and data quality"""
        try:
            # Model agreement (how much models agree)
            outcome_std = []
            for outcome in ['home_win', 'draw', 'away_win']:
                values = [proba[outcome] for proba in probabilities.values()]
                outcome_std.append(np.std(values))
            
            model_agreement = 1.0 - np.mean(outcome_std)
            
            # Data quality (how complete the features are)
            non_zero_features = sum(1 for v in features.values() if v != 0.0)
            data_quality = non_zero_features / len(self.feature_names)
            
            # Combined confidence
            confidence = (model_agreement * 0.7 + data_quality * 0.3)
            
            return min(0.99, max(0.30, float(confidence)))
            
        except Exception as e:
            logger.error(f"Confidence calculation failed: {e}")
            return 0.75
    
    def _get_recommended_bet(self, probabilities: Dict, confidence: float) -> str:
        """Determine recommended bet based on probabilities and confidence"""
        try:
            # Only recommend if confidence is above threshold
            if confidence < settings.MODEL_CONFIDENCE_THRESHOLD:
                return "Low confidence - consider avoiding"
            
            # Find highest probability outcome
            max_outcome = max(probabilities.keys(), key=lambda k: probabilities[k])
            max_prob = probabilities[max_outcome]
            
            # Convert to readable format
            outcome_map = {
                'home_win': 'Home Team Win',
                'away_win': 'Away Team Win', 
                'draw': 'Draw'
            }
            
            # Only recommend if probability is significantly higher than others
            if max_prob > 0.55:
                return outcome_map[max_outcome]
            else:
                return "No clear favorite - consider draw or avoid"
                
        except Exception as e:
            logger.error(f"Bet recommendation failed: {e}")
            return "Analysis inconclusive"
    
    def _heuristic_prediction(self, features: Dict) -> Dict[str, Any]:
        """Fallback heuristic prediction when ML models aren't available"""
        try:
            # Simple heuristic based on key features
            home_strength = (features.get('home_win_percentage', 0.5) + 
                           features.get('home_form_points', 10) / 15.0 +
                           features.get('goal_difference_home', 0.0) / 2.0) / 3.0
            
            away_strength = (features.get('away_win_percentage', 0.4) +
                           features.get('away_form_points', 8) / 15.0 +
                           features.get('goal_difference_away', 0.0) / 2.0) / 3.0
            
            # Adjust for home advantage
            home_strength += 0.1
            
            # Calculate probabilities
            total_strength = home_strength + away_strength + 0.3  # draw factor
            
            home_win_prob = min(0.80, max(0.15, home_strength / total_strength))
            away_win_prob = min(0.80, max(0.15, away_strength / total_strength))
            draw_prob = max(0.15, 1.0 - home_win_prob - away_win_prob)
            
            # Normalize
            total = home_win_prob + away_win_prob + draw_prob
            home_win_prob /= total
            away_win_prob /= total
            draw_prob /= total
            
            return {
                'home_win_probability': round(home_win_prob, 3),
                'draw_probability': round(draw_prob, 3),
                'away_win_probability': round(away_win_prob, 3),
                'confidence_score': 0.65,  # Medium confidence for heuristic
                'recommended_bet': 'Home Team Win' if home_win_prob > 0.5 else 'Away Team Win' if away_win_prob > 0.4 else 'Draw'
            }
            
        except Exception as e:
            logger.error(f"Heuristic prediction failed: {e}")
            return self._fallback_prediction(features)
    
    def _fallback_prediction(self, features: Dict) -> Dict[str, Any]:
        """Ultimate fallback with default probabilities"""
        return {
            'home_win_probability': 0.45,
            'draw_probability': 0.30,
            'away_win_probability': 0.25,
            'confidence_score': 0.50,
            'recommended_bet': 'Home Team Win (Default)'
        }
