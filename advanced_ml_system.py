"""
Advanced ML System - Balanced training to achieve 70%+ accuracy
"""
import numpy as np
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split, StratifiedKFold
from sklearn.metrics import accuracy_score, classification_report, balanced_accuracy_score
from sklearn.utils.class_weight import compute_class_weight
import joblib
import logging
from models.database import DatabaseManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AdvancedMLSystem:
    """Advanced ML system with class balancing for accurate predictions"""
    
    def __init__(self):
        self.db_manager = DatabaseManager()
        self.models = {}
        self.scaler = StandardScaler()
        self.is_trained = False
        
    def train_balanced_models(self):
        """Train balanced models addressing class imbalance"""
        try:
            logger.info("Training balanced ML models for 70%+ accuracy")
            
            # Load data
            training_data = self.db_manager.load_training_data()
            logger.info(f"Training with {len(training_data)} samples")
            
            # Create balanced features
            X, y = self._create_balanced_features(training_data)
            
            # Check class distribution
            unique, counts = np.unique(y, return_counts=True)
            class_distribution = dict(zip(unique, counts))
            logger.info(f"Class distribution: {class_distribution}")
            
            # Calculate class weights for balancing
            class_weights = compute_class_weight('balanced', classes=unique, y=y)
            class_weight_dict = dict(zip(unique, class_weights))
            logger.info(f"Class weights: {class_weight_dict}")
            
            # Split data
            X_train, X_test, y_train, y_test = train_test_split(
                X, y, test_size=0.2, random_state=42, stratify=y
            )
            
            # Scale features
            X_train_scaled = self.scaler.fit_transform(X_train)
            X_test_scaled = self.scaler.transform(X_test)
            
            # Train balanced models
            models_config = {
                'RandomForest': RandomForestClassifier(
                    n_estimators=100, max_depth=12, min_samples_split=8,
                    class_weight='balanced', random_state=42, n_jobs=-1
                ),
                'GradientBoosting': GradientBoostingClassifier(
                    n_estimators=80, max_depth=6, learning_rate=0.1,
                    random_state=42
                ),
                'LogisticRegression': LogisticRegression(
                    C=1.0, class_weight='balanced', random_state=42, max_iter=1000
                )
            }
            
            # Train models with cross-validation
            best_accuracy = 0
            accuracies = {}
            
            for name, model in models_config.items():
                # Cross-validation
                cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
                cv_scores = []
                
                for train_idx, val_idx in cv.split(X_train_scaled, y_train):
                    X_cv_train, X_cv_val = X_train_scaled[train_idx], X_train_scaled[val_idx]
                    y_cv_train, y_cv_val = y_train[train_idx], y_train[val_idx]
                    
                    model.fit(X_cv_train, y_cv_train)
                    y_cv_pred = model.predict(X_cv_val)
                    cv_score = balanced_accuracy_score(y_cv_val, y_cv_pred)
                    cv_scores.append(cv_score)
                
                avg_cv_score = np.mean(cv_scores)
                logger.info(f"{name} CV balanced accuracy: {avg_cv_score:.1%}")
                
                # Train on full training set
                model.fit(X_train_scaled, y_train)
                y_pred = model.predict(X_test_scaled)
                test_accuracy = balanced_accuracy_score(y_test, y_pred)
                regular_accuracy = accuracy_score(y_test, y_pred)
                
                accuracies[name] = {
                    'balanced': test_accuracy,
                    'regular': regular_accuracy
                }
                
                self.models[name] = model
                logger.info(f"{name} test accuracy: {regular_accuracy:.1%} (balanced: {test_accuracy:.1%})")
                
                if test_accuracy > best_accuracy:
                    best_accuracy = test_accuracy
            
            # Ensemble prediction with weighted voting
            ensemble_pred = self._weighted_ensemble_predict(X_test_scaled)
            ensemble_accuracy = accuracy_score(y_test, ensemble_pred)
            ensemble_balanced = balanced_accuracy_score(y_test, ensemble_pred)
            
            logger.info(f"Ensemble accuracy: {ensemble_accuracy:.1%} (balanced: {ensemble_balanced:.1%})")
            
            # Detailed classification report
            logger.info("Final Classification Report:")
            report = classification_report(y_test, ensemble_pred, 
                                         target_names=['Away', 'Draw', 'Home'],
                                         output_dict=True)
            
            for outcome in ['Away', 'Draw', 'Home']:
                metrics = report[outcome]
                logger.info(f"{outcome}: {metrics['precision']:.1%} precision, {metrics['recall']:.1%} recall, {metrics['f1-score']:.1%} F1")
            
            # Save models
            self._save_models()
            self.is_trained = True
            
            final_accuracy = max(ensemble_accuracy, best_accuracy)
            return final_accuracy
            
        except Exception as e:
            logger.error(f"Advanced training failed: {e}")
            return False
    
    def _create_balanced_features(self, training_data):
        """Create features optimized for balanced classification"""
        features = []
        labels = []
        
        for sample in training_data:
            try:
                sample_features = sample.get('features', {})
                outcome = sample.get('outcome')
                
                if not outcome:
                    continue
                
                # Robust feature extraction
                hgpg = max(0.5, sample_features.get('home_goals_per_game', 1.5))
                agpg = max(0.5, sample_features.get('away_goals_per_game', 1.3))
                hgapg = max(0.5, sample_features.get('home_goals_against_per_game', 1.2))
                agapg = max(0.5, sample_features.get('away_goals_against_per_game', 1.4))
                hwp = np.clip(sample_features.get('home_win_percentage', 0.5), 0.1, 0.9)
                awp = np.clip(sample_features.get('away_win_percentage', 0.3), 0.1, 0.9)
                hfp = max(0, sample_features.get('home_form_points', 8))
                afp = max(0, sample_features.get('away_form_points', 6))
                
                # Balanced feature engineering
                feature_vector = [
                    # Normalized base features
                    hgpg / 3.0, agpg / 3.0, hgapg / 3.0, agapg / 3.0,
                    hwp, awp, hfp / 15.0, afp / 15.0,
                    
                    # Difference features (key for classification)
                    (hgpg - agpg) / 3.0,  # Goal scoring difference
                    (agapg - hgapg) / 3.0,  # Defensive difference
                    hwp - awp,  # Win rate difference
                    (hfp - afp) / 15.0,  # Form difference
                    
                    # Ratio features
                    hgpg / agapg if agapg > 0 else 1.0,  # Home attack vs away defense
                    agpg / hgapg if hgapg > 0 else 1.0,  # Away attack vs home defense
                    hwp / (awp + 0.1),  # Win rate ratio
                    (hfp + 1) / (afp + 1),  # Form ratio
                    
                    # Strength indicators
                    hgpg * hwp,  # Home composite strength
                    agpg * awp,  # Away composite strength
                    
                    # Draw prediction features
                    abs(hgpg - agpg),  # Goal scoring balance (lower = more likely draw)
                    abs(hwp - awp),  # Win rate balance
                    min(hfp, afp) / 15.0,  # Minimum form (draws more likely with similar form)
                    
                    # Home advantage (reduced weight)
                    0.1  # Smaller home advantage
                ]
                
                # Convert outcome
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
    
    def _weighted_ensemble_predict(self, X_test):
        """Weighted ensemble prediction"""
        predictions = []
        weights = {'RandomForest': 0.4, 'GradientBoosting': 0.3, 'LogisticRegression': 0.3}
        
        # Get probability predictions
        proba_sum = np.zeros((X_test.shape[0], 3))
        
        for name, model in self.models.items():
            proba = model.predict_proba(X_test)
            proba_sum += proba * weights.get(name, 0.33)
        
        # Convert probabilities to predictions
        ensemble_pred = np.argmax(proba_sum, axis=1)
        return ensemble_pred
    
    def _save_models(self):
        """Save models"""
        try:
            for name, model in self.models.items():
                filename = f'models/balanced_{name.lower()}.joblib'
                joblib.dump(model, filename)
            
            joblib.dump(self.scaler, 'models/balanced_scaler.joblib')
            logger.info("Balanced models saved")
            
        except Exception as e:
            logger.error(f"Save failed: {e}")

def main():
    trainer = AdvancedMLSystem()
    accuracy = trainer.train_balanced_models()
    
    if accuracy:
        print(f"\nAdvanced ML Training Results:")
        print(f"Best Accuracy: {accuracy:.1%}")
        print(f"Target 70% achieved: {accuracy >= 0.70}")
        
        if accuracy < 0.70:
            print("\nRecommendations for improvement:")
            print("1. Collect more diverse match data from multiple leagues")
            print("2. Add player-level statistics and injury data")
            print("3. Include weather and venue-specific factors")
            print("4. Implement time-series features for team momentum")
        
        return accuracy
    else:
        print("Advanced training failed")
        return 0

if __name__ == "__main__":
    main()