"""
Optimized ML Training - Eliminate timeouts with batch processing
"""
import asyncio
import logging
from models.database import DatabaseManager
from models.ml_predictor import MLPredictor
import numpy as np
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, classification_report
import joblib
import json

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class OptimizedTrainer:
    """Fast ML training with batch processing to avoid timeouts"""
    
    def __init__(self):
        self.db_manager = DatabaseManager()
        self.models = {}
        self.scaler = StandardScaler()
        self.is_trained = False
        
    def train_models_fast(self):
        """Train models with optimized batch processing"""
        try:
            logger.info("Starting optimized ML training")
            
            # Load training data efficiently
            training_data = self.db_manager.load_training_data()
            if not training_data:
                logger.error("No training data available")
                return False
            
            logger.info(f"Loaded {len(training_data)} training samples")
            
            # Prepare features and labels efficiently
            X, y = self._prepare_training_data(training_data)
            
            if len(X) < 50:
                logger.warning(f"Limited training data: {len(X)} samples")
                return False
            
            # Split data
            X_train, X_test, y_train, y_test = train_test_split(
                X, y, test_size=0.2, random_state=42, stratify=y
            )
            
            # Scale features
            X_train_scaled = self.scaler.fit_transform(X_train)
            X_test_scaled = self.scaler.transform(X_test)
            
            # Train models with optimized parameters
            models_config = {
                'RandomForest': RandomForestClassifier(
                    n_estimators=50,  # Reduced for speed
                    max_depth=10,
                    random_state=42,
                    n_jobs=-1
                ),
                'GradientBoosting': GradientBoostingClassifier(
                    n_estimators=50,  # Reduced for speed
                    max_depth=6,
                    random_state=42
                ),
                'LogisticRegression': LogisticRegression(
                    random_state=42,
                    max_iter=500
                )
            }
            
            # Train each model
            for name, model in models_config.items():
                logger.info(f"Training {name}")
                model.fit(X_train_scaled, y_train)
                
                # Quick evaluation
                y_pred = model.predict(X_test_scaled)
                accuracy = accuracy_score(y_test, y_pred)
                
                self.models[name] = model
                logger.info(f"{name} accuracy: {accuracy:.1%}")
            
            # Save models
            self._save_models()
            self.is_trained = True
            
            logger.info("Optimized training completed successfully")
            return True
            
        except Exception as e:
            logger.error(f"Training failed: {e}")
            return False
    
    def _prepare_training_data(self, training_data):
        """Efficiently prepare training data"""
        features = []
        labels = []
        
        feature_names = [
            'home_goals_per_game', 'away_goals_per_game',
            'home_goals_against_per_game', 'away_goals_against_per_game',
            'home_win_percentage', 'away_win_percentage',
            'home_form_points', 'away_form_points',
            'goal_difference_home', 'goal_difference_away',
            'form_difference', 'strength_difference',
            'total_goals_tendency', 'h2h_home_wins',
            'h2h_away_wins', 'h2h_avg_goals',
            'home_key_injuries', 'away_key_injuries'
        ]
        
        for sample in training_data:
            try:
                sample_features = sample.get('features', {})
                outcome = sample.get('outcome')
                
                if not outcome:
                    continue
                
                # Extract feature vector
                feature_vector = []
                for feature_name in feature_names:
                    value = sample_features.get(feature_name, 0.0)
                    feature_vector.append(float(value))
                
                # Convert outcome to numeric label
                if outcome == 'Home':
                    label = 2
                elif outcome == 'Draw':
                    label = 1
                else:  # Away
                    label = 0
                
                features.append(feature_vector)
                labels.append(label)
                
            except Exception as e:
                logger.warning(f"Skipped invalid sample: {e}")
                continue
        
        return np.array(features), np.array(labels)
    
    def _save_models(self):
        """Save trained models to disk"""
        try:
            # Save individual models
            for name, model in self.models.items():
                filename = f"models/{name.lower()}_model.joblib"
                joblib.dump(model, filename)
            
            # Save scaler
            joblib.dump(self.scaler, "models/scaler.joblib")
            
            logger.info("Models saved successfully")
            
        except Exception as e:
            logger.error(f"Failed to save models: {e}")
    
    def test_prediction(self):
        """Test prediction with sample data"""
        if not self.is_trained:
            return None
        
        # Sample Premier League match features
        test_features = np.array([[
            1.8, 1.2, 1.0, 1.5, 0.6, 0.3,  # Goals and win percentages
            15, 6, 0.8, -0.3, 9.0, 0.35,    # Form and differences
            3.0, 5, 1, 2.9, 0, 2             # H2H and other factors
        ]])
        
        # Scale features
        test_features_scaled = self.scaler.transform(test_features)
        
        # Get predictions from all models
        predictions = {}
        for name, model in self.models.items():
            proba = model.predict_proba(test_features_scaled)[0]
            predictions[name] = {
                'away_win': proba[0],
                'draw': proba[1],
                'home_win': proba[2]
            }
        
        # Ensemble prediction
        avg_proba = {
            'away_win': np.mean([p['away_win'] for p in predictions.values()]),
            'draw': np.mean([p['draw'] for p in predictions.values()]),
            'home_win': np.mean([p['home_win'] for p in predictions.values()])
        }
        
        return {
            'ensemble': avg_proba,
            'individual_models': predictions
        }

def main():
    """Run optimized training"""
    trainer = OptimizedTrainer()
    
    # Train models
    success = trainer.train_models_fast()
    
    if success:
        print("✓ Training completed successfully")
        
        # Test prediction
        result = trainer.test_prediction()
        if result:
            print("\nTest Prediction Results:")
            ensemble = result['ensemble']
            print(f"Home Win: {ensemble['home_win']:.1%}")
            print(f"Draw: {ensemble['draw']:.1%}")
            print(f"Away Win: {ensemble['away_win']:.1%}")
            
            print("\nIndividual Model Results:")
            for model_name, probs in result['individual_models'].items():
                print(f"{model_name}: {probs['home_win']:.1%} home win")
    else:
        print("✗ Training failed")
    
    return success

if __name__ == "__main__":
    main()