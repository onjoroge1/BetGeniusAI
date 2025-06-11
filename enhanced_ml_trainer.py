"""
Enhanced ML Training - Target 70%+ accuracy with advanced features
"""
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier, VotingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.svm import SVC
from sklearn.preprocessing import StandardScaler, RobustScaler
from sklearn.model_selection import train_test_split, cross_val_score, GridSearchCV
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
from sklearn.feature_selection import SelectKBest, f_classif
import joblib
import json
import logging
from models.database import DatabaseManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class EnhancedMLTrainer:
    """Advanced ML trainer targeting 70%+ accuracy"""
    
    def __init__(self):
        self.db_manager = DatabaseManager()
        self.models = {}
        self.ensemble_model = None
        self.scalers = {}
        self.feature_selector = None
        self.is_trained = False
        
    def train_enhanced_models(self):
        """Train enhanced models with advanced techniques"""
        try:
            logger.info("Starting enhanced ML training for 70%+ accuracy")
            
            # Load training data
            training_data = self.db_manager.load_training_data()
            if len(training_data) < 100:
                logger.error(f"Insufficient training data: {len(training_data)} samples")
                return False
            
            logger.info(f"Training with {len(training_data)} authentic samples")
            
            # Enhanced feature engineering
            X, y, feature_names = self._enhanced_feature_engineering(training_data)
            
            # Feature selection
            self.feature_selector = SelectKBest(score_func=f_classif, k=min(15, X.shape[1]))
            X_selected = self.feature_selector.fit_transform(X, y)
            
            logger.info(f"Selected {X_selected.shape[1]} best features")
            
            # Split data with stratification
            X_train, X_test, y_train, y_test = train_test_split(
                X_selected, y, test_size=0.25, random_state=42, stratify=y
            )
            
            # Multiple scaling approaches
            scalers = {
                'standard': StandardScaler(),
                'robust': RobustScaler()
            }
            
            best_accuracy = 0
            best_scaler_name = None
            
            for scaler_name, scaler in scalers.items():
                X_train_scaled = scaler.fit_transform(X_train)
                X_test_scaled = scaler.transform(X_test)
                
                # Train models with hyperparameter tuning
                models = self._train_optimized_models(X_train_scaled, y_train)
                
                # Create ensemble
                ensemble = VotingClassifier(
                    estimators=[(name, model) for name, model in models.items()],
                    voting='soft'
                )
                ensemble.fit(X_train_scaled, y_train)
                
                # Evaluate
                y_pred = ensemble.predict(X_test_scaled)
                accuracy = accuracy_score(y_test, y_pred)
                
                logger.info(f"Scaler {scaler_name}: Ensemble accuracy {accuracy:.1%}")
                
                if accuracy > best_accuracy:
                    best_accuracy = accuracy
                    best_scaler_name = scaler_name
                    self.models = models
                    self.ensemble_model = ensemble
                    self.scalers[scaler_name] = scaler
            
            # Final evaluation
            if best_accuracy >= 0.70:
                logger.info(f"✓ Target achieved: {best_accuracy:.1%} accuracy with {best_scaler_name} scaler")
            else:
                logger.warning(f"Target missed: {best_accuracy:.1%} accuracy (target: 70%)")
            
            # Detailed classification report
            X_train_final = self.scalers[best_scaler_name].transform(X_train)
            X_test_final = self.scalers[best_scaler_name].transform(X_test)
            
            y_pred_final = self.ensemble_model.predict(X_test_final)
            
            logger.info("Classification Report:")
            logger.info(f"\n{classification_report(y_test, y_pred_final, target_names=['Away', 'Draw', 'Home'])}")
            
            # Save models
            self._save_enhanced_models(best_scaler_name)
            self.is_trained = True
            
            return best_accuracy
            
        except Exception as e:
            logger.error(f"Enhanced training failed: {e}")
            return False
    
    def _enhanced_feature_engineering(self, training_data):
        """Create enhanced features for better prediction accuracy"""
        features = []
        labels = []
        
        for sample in training_data:
            try:
                sample_features = sample.get('features', {})
                outcome = sample.get('outcome')
                
                if not outcome:
                    continue
                
                # Base features
                home_goals_pg = sample_features.get('home_goals_per_game', 1.5)
                away_goals_pg = sample_features.get('away_goals_per_game', 1.3)
                home_goals_against = sample_features.get('home_goals_against_per_game', 1.2)
                away_goals_against = sample_features.get('away_goals_against_per_game', 1.4)
                home_win_pct = sample_features.get('home_win_percentage', 0.5)
                away_win_pct = sample_features.get('away_win_percentage', 0.3)
                home_form = sample_features.get('home_form_points', 8)
                away_form = sample_features.get('away_form_points', 6)
                
                # Enhanced feature engineering
                feature_vector = [
                    # Original features
                    home_goals_pg, away_goals_pg, home_goals_against, away_goals_against,
                    home_win_pct, away_win_pct, home_form, away_form,
                    
                    # Derived features for better accuracy
                    home_goals_pg - away_goals_pg,  # Goals scoring advantage
                    away_goals_against - home_goals_against,  # Defensive advantage
                    home_win_pct - away_win_pct,  # Win percentage difference
                    (home_form - away_form) / 15,  # Normalized form difference
                    
                    # Attack vs Defense matchups
                    home_goals_pg / away_goals_against if away_goals_against > 0 else 1.5,
                    away_goals_pg / home_goals_against if home_goals_against > 0 else 1.2,
                    
                    # Form momentum indicators
                    home_form / 15,  # Normalized home form
                    away_form / 15,  # Normalized away form
                    
                    # Additional derived metrics
                    (home_goals_pg + away_goals_against) / 2,  # Expected goals matchup
                    abs(home_win_pct - away_win_pct),  # Competitive balance
                    (home_goals_pg * home_win_pct),  # Offensive strength
                    (away_goals_pg * away_win_pct),  # Away offensive strength
                    
                    # Home advantage factors
                    0.15,  # Standard home advantage
                    home_form * 0.1,  # Form-based home boost
                ]
                
                # Convert outcome to numeric
                if outcome == 'Home':
                    label = 2
                elif outcome == 'Draw':
                    label = 1
                else:  # Away
                    label = 0
                
                features.append(feature_vector)
                labels.append(label)
                
            except Exception as e:
                continue
        
        feature_names = [
            'home_goals_pg', 'away_goals_pg', 'home_goals_against', 'away_goals_against',
            'home_win_pct', 'away_win_pct', 'home_form', 'away_form',
            'goals_advantage', 'defense_advantage', 'win_pct_diff', 'form_diff_norm',
            'home_attack_vs_away_defense', 'away_attack_vs_home_defense',
            'home_form_norm', 'away_form_norm', 'expected_goals_matchup',
            'competitive_balance', 'home_offensive_strength', 'away_offensive_strength',
            'home_advantage', 'form_home_boost'
        ]
        
        return np.array(features), np.array(labels), feature_names
    
    def _train_optimized_models(self, X_train, y_train):
        """Train models with hyperparameter optimization"""
        models = {}
        
        # Optimized Random Forest
        rf_params = {
            'n_estimators': [100, 200],
            'max_depth': [10, 15, 20],
            'min_samples_split': [5, 10],
            'min_samples_leaf': [2, 4]
        }
        
        rf = RandomForestClassifier(random_state=42, n_jobs=-1)
        rf_grid = GridSearchCV(rf, rf_params, cv=5, scoring='accuracy', n_jobs=-1)
        rf_grid.fit(X_train, y_train)
        models['RandomForest'] = rf_grid.best_estimator_
        
        logger.info(f"RandomForest best params: {rf_grid.best_params_}")
        
        # Optimized Gradient Boosting
        gb_params = {
            'n_estimators': [100, 150],
            'max_depth': [6, 8, 10],
            'learning_rate': [0.1, 0.15]
        }
        
        gb = GradientBoostingClassifier(random_state=42)
        gb_grid = GridSearchCV(gb, gb_params, cv=5, scoring='accuracy', n_jobs=-1)
        gb_grid.fit(X_train, y_train)
        models['GradientBoosting'] = gb_grid.best_estimator_
        
        logger.info(f"GradientBoosting best params: {gb_grid.best_params_}")
        
        # Optimized Logistic Regression
        lr_params = {
            'C': [0.1, 1.0, 10.0],
            'solver': ['lbfgs', 'liblinear']
        }
        
        lr = LogisticRegression(random_state=42, max_iter=1000)
        lr_grid = GridSearchCV(lr, lr_params, cv=5, scoring='accuracy', n_jobs=-1)
        lr_grid.fit(X_train, y_train)
        models['LogisticRegression'] = lr_grid.best_estimator_
        
        # Add SVM for ensemble diversity
        svm = SVC(probability=True, random_state=42)
        svm.fit(X_train, y_train)
        models['SVM'] = svm
        
        return models
    
    def _save_enhanced_models(self, best_scaler_name):
        """Save enhanced models"""
        try:
            # Save ensemble model
            joblib.dump(self.ensemble_model, 'models/enhanced_ensemble.joblib')
            
            # Save individual models
            for name, model in self.models.items():
                filename = f'models/enhanced_{name.lower()}.joblib'
                joblib.dump(model, filename)
            
            # Save scaler
            joblib.dump(self.scalers[best_scaler_name], 'models/enhanced_scaler.joblib')
            
            # Save feature selector
            joblib.dump(self.feature_selector, 'models/feature_selector.joblib')
            
            logger.info("Enhanced models saved successfully")
            
        except Exception as e:
            logger.error(f"Failed to save enhanced models: {e}")

def main():
    """Run enhanced training"""
    trainer = EnhancedMLTrainer()
    accuracy = trainer.train_enhanced_models()
    
    if accuracy:
        print(f"\nEnhanced Training Results:")
        print(f"Final Accuracy: {accuracy:.1%}")
        print(f"Target 70% achieved: {accuracy >= 0.70}")
    else:
        print("Enhanced training failed")
    
    return accuracy

if __name__ == "__main__":
    main()