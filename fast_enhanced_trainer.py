"""
Fast Enhanced ML Training - Achieve 70%+ accuracy without timeouts
"""
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, classification_report
import joblib
import logging
from models.database import DatabaseManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class FastEnhancedTrainer:
    """Fast enhanced training targeting 70%+ accuracy"""
    
    def __init__(self):
        self.db_manager = DatabaseManager()
        self.models = {}
        self.scaler = StandardScaler()
        self.is_trained = False
        
    def train_fast_enhanced(self):
        """Fast training with enhanced features"""
        try:
            logger.info("Fast enhanced training for 70%+ accuracy")
            
            # Load data
            training_data = self.db_manager.load_training_data()
            logger.info(f"Training with {len(training_data)} samples")
            
            # Enhanced feature engineering
            X, y = self._create_enhanced_features(training_data)
            
            # Split data
            X_train, X_test, y_train, y_test = train_test_split(
                X, y, test_size=0.2, random_state=42, stratify=y
            )
            
            # Scale features
            X_train_scaled = self.scaler.fit_transform(X_train)
            X_test_scaled = self.scaler.transform(X_test)
            
            # Train optimized models
            models_config = {
                'RandomForest': RandomForestClassifier(
                    n_estimators=150, max_depth=15, min_samples_split=5,
                    random_state=42, n_jobs=-1
                ),
                'GradientBoosting': GradientBoostingClassifier(
                    n_estimators=100, max_depth=8, learning_rate=0.15,
                    random_state=42
                ),
                'LogisticRegression': LogisticRegression(
                    C=10.0, random_state=42, max_iter=1000
                )
            }
            
            # Train and evaluate each model
            accuracies = {}
            for name, model in models_config.items():
                model.fit(X_train_scaled, y_train)
                y_pred = model.predict(X_test_scaled)
                accuracy = accuracy_score(y_test, y_pred)
                accuracies[name] = accuracy
                self.models[name] = model
                logger.info(f"{name}: {accuracy:.1%} accuracy")
            
            # Create ensemble prediction
            ensemble_predictions = []
            for model in self.models.values():
                pred = model.predict(X_test_scaled)
                ensemble_predictions.append(pred)
            
            # Majority vote ensemble
            ensemble_pred = np.array(ensemble_predictions).T
            final_pred = [np.bincount(row).argmax() for row in ensemble_pred]
            ensemble_accuracy = accuracy_score(y_test, final_pred)
            
            logger.info(f"Ensemble accuracy: {ensemble_accuracy:.1%}")
            
            # Detailed report
            logger.info("Classification Report:")
            report = classification_report(y_test, final_pred, 
                                         target_names=['Away', 'Draw', 'Home'],
                                         output_dict=True)
            
            for outcome, metrics in report.items():
                if outcome in ['Away', 'Draw', 'Home']:
                    logger.info(f"{outcome}: {metrics['precision']:.1%} precision, {metrics['recall']:.1%} recall")
            
            # Save models
            self._save_models()
            self.is_trained = True
            
            return ensemble_accuracy
            
        except Exception as e:
            logger.error(f"Fast enhanced training failed: {e}")
            return False
    
    def _create_enhanced_features(self, training_data):
        """Create enhanced features for better accuracy"""
        features = []
        labels = []
        
        for sample in training_data:
            try:
                sample_features = sample.get('features', {})
                outcome = sample.get('outcome')
                
                if not outcome:
                    continue
                
                # Extract base features
                hgpg = sample_features.get('home_goals_per_game', 1.5)
                agpg = sample_features.get('away_goals_per_game', 1.3)
                hgapg = sample_features.get('home_goals_against_per_game', 1.2)
                agapg = sample_features.get('away_goals_against_per_game', 1.4)
                hwp = sample_features.get('home_win_percentage', 0.5)
                awp = sample_features.get('away_win_percentage', 0.3)
                hfp = sample_features.get('home_form_points', 8)
                afp = sample_features.get('away_form_points', 6)
                
                # Enhanced feature vector (22 features)
                feature_vector = [
                    # Original features
                    hgpg, agpg, hgapg, agapg, hwp, awp, hfp, afp,
                    
                    # Derived features for better prediction
                    hgpg - agpg,  # Attack advantage
                    agapg - hgapg,  # Defense advantage
                    hwp - awp,  # Win rate difference
                    (hfp - afp) / 15,  # Form difference normalized
                    
                    # Attack vs Defense matchups
                    hgpg / agapg if agapg > 0 else 1.5,  # Home attack vs away defense
                    agpg / hgapg if hgapg > 0 else 1.2,  # Away attack vs home defense
                    
                    # Strength indicators
                    hgpg * hwp,  # Home offensive strength
                    agpg * awp,  # Away offensive strength
                    (2 - hgapg) * hwp,  # Home defensive strength
                    (2 - agapg) * awp,  # Away defensive strength
                    
                    # Form momentum
                    hfp / 15,  # Home form normalized
                    afp / 15,  # Away form normalized
                    
                    # Balance indicators
                    abs(hwp - awp),  # Competitive balance
                    0.15  # Home advantage constant
                ]
                
                # Convert outcome to label
                if outcome == 'Home':
                    label = 2
                elif outcome == 'Draw':
                    label = 1
                else:  # Away
                    label = 0
                
                features.append(feature_vector)
                labels.append(label)
                
            except Exception:
                continue
        
        return np.array(features), np.array(labels)
    
    def _save_models(self):
        """Save trained models"""
        try:
            for name, model in self.models.items():
                filename = f'models/enhanced_{name.lower()}.joblib'
                joblib.dump(model, filename)
            
            joblib.dump(self.scaler, 'models/enhanced_scaler.joblib')
            logger.info("Enhanced models saved")
            
        except Exception as e:
            logger.error(f"Save failed: {e}")

def main():
    trainer = FastEnhancedTrainer()
    accuracy = trainer.train_fast_enhanced()
    
    if accuracy:
        print(f"\nFast Enhanced Training Results:")
        print(f"Ensemble Accuracy: {accuracy:.1%}")
        print(f"Target 70% achieved: {accuracy >= 0.70}")
        return accuracy
    else:
        print("Training failed")
        return 0

if __name__ == "__main__":
    main()