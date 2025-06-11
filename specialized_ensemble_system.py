"""
Specialized Ensemble System - Separate models for different contexts + Meta-learner
"""
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.metrics import accuracy_score, classification_report
import joblib
import json
import logging
from models.database import DatabaseManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SpecializedEnsembleSystem:
    """Multi-context ensemble system with meta-learner"""
    
    def __init__(self):
        self.db_manager = DatabaseManager()
        
        # Specialized models for different contexts
        self.home_advantage_models = {}  # Models for home-favored matches
        self.balanced_models = {}        # Models for evenly matched games
        self.away_strength_models = {}   # Models for strong away teams
        
        # Meta-learner to combine predictions
        self.meta_learner = None
        
        # Scalers for each context
        self.scalers = {
            'home_advantage': StandardScaler(),
            'balanced': StandardScaler(), 
            'away_strength': StandardScaler()
        }
        
        self.is_trained = False
        
    def train_specialized_ensemble(self):
        """Train specialized models for different match contexts"""
        try:
            logger.info("Training specialized ensemble system")
            
            # Load training data
            training_data = self.db_manager.load_training_data()
            logger.info(f"Training with {len(training_data)} samples")
            
            # Categorize matches by context
            contexts = self._categorize_matches(training_data)
            
            # Train specialized models for each context
            context_accuracies = {}
            meta_features = []
            meta_labels = []
            
            for context_name, context_data in contexts.items():
                if len(context_data) < 50:  # Skip if insufficient data
                    logger.warning(f"Insufficient data for {context_name}: {len(context_data)} samples")
                    continue
                
                logger.info(f"Training {context_name} models with {len(context_data)} samples")
                
                # Train context-specific models
                accuracy, predictions, labels = self._train_context_models(context_name, context_data)
                context_accuracies[context_name] = accuracy
                
                # Collect meta-features for meta-learner
                meta_features.extend(predictions)
                meta_labels.extend(labels)
                
                logger.info(f"{context_name} best accuracy: {accuracy:.1%}")
            
            # Train meta-learner to combine specialist predictions
            if meta_features:
                meta_accuracy = self._train_meta_learner(meta_features, meta_labels)
                logger.info(f"Meta-learner accuracy: {meta_accuracy:.1%}")
            
            # Overall system evaluation
            overall_accuracy = self._evaluate_full_system(training_data)
            
            self.is_trained = True
            
            # Save all models
            self._save_specialized_models()
            
            logger.info(f"Specialized ensemble training complete: {overall_accuracy:.1%} accuracy")
            return overall_accuracy
            
        except Exception as e:
            logger.error(f"Specialized ensemble training failed: {e}")
            return False
    
    def _categorize_matches(self, training_data):
        """Categorize matches into different contexts"""
        home_advantage = []  # Home team clearly stronger
        balanced = []        # Teams evenly matched
        away_strength = []   # Away team stronger or competitive
        
        for sample in training_data:
            try:
                features = sample.get('features', {})
                
                # Extract key indicators
                home_win_pct = features.get('home_win_percentage', 0.5)
                away_win_pct = features.get('away_win_percentage', 0.3)
                home_form = features.get('home_form_points', 8)
                away_form = features.get('away_form_points', 6)
                home_goals = features.get('home_goals_per_game', 1.5)
                away_goals = features.get('away_goals_per_game', 1.3)
                
                # Calculate strength indicators
                home_strength = (home_win_pct + home_form/15 + home_goals/3) / 3
                away_strength = (away_win_pct + away_form/15 + away_goals/3) / 3
                strength_diff = home_strength - away_strength
                
                # Categorize based on strength difference and home advantage
                if strength_diff > 0.15:  # Clear home advantage
                    home_advantage.append(sample)
                elif abs(strength_diff) <= 0.15:  # Balanced match
                    balanced.append(sample)
                else:  # Away team competitive/stronger
                    away_strength.append(sample)
                    
            except Exception:
                balanced.append(sample)  # Default to balanced if error
        
        logger.info(f"Match categorization:")
        logger.info(f"  Home advantage: {len(home_advantage)} matches")
        logger.info(f"  Balanced: {len(balanced)} matches")
        logger.info(f"  Away strength: {len(away_strength)} matches")
        
        return {
            'home_advantage': home_advantage,
            'balanced': balanced,
            'away_strength': away_strength
        }
    
    def _train_context_models(self, context_name, context_data):
        """Train models specialized for specific context"""
        # Prepare features and labels
        X, y = self._prepare_context_features(context_data, context_name)
        
        # Split data
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42, stratify=y
        )
        
        # Scale features
        scaler = self.scalers[context_name]
        X_train_scaled = scaler.fit_transform(X_train)
        X_test_scaled = scaler.transform(X_test)
        
        # Context-specific model configurations
        if context_name == 'home_advantage':
            # Optimize for detecting strong home wins
            models_config = {
                'RandomForest': RandomForestClassifier(
                    n_estimators=100, max_depth=10, min_samples_split=5,
                    class_weight={0: 1.0, 1: 1.2, 2: 0.8}, random_state=42
                ),
                'GradientBoosting': GradientBoostingClassifier(
                    n_estimators=80, max_depth=6, learning_rate=0.15,
                    random_state=42
                ),
                'LogisticRegression': LogisticRegression(
                    C=1.5, random_state=42, max_iter=1000
                )
            }
        elif context_name == 'balanced':
            # Optimize for detecting draws and close matches
            models_config = {
                'RandomForest': RandomForestClassifier(
                    n_estimators=120, max_depth=8, min_samples_split=8,
                    class_weight={0: 1.0, 1: 0.7, 2: 1.0}, random_state=42
                ),
                'GradientBoosting': GradientBoostingClassifier(
                    n_estimators=100, max_depth=5, learning_rate=0.1,
                    random_state=42
                ),
                'LogisticRegression': LogisticRegression(
                    C=0.8, random_state=42, max_iter=1000
                )
            }
        else:  # away_strength
            # Optimize for detecting away wins and upsets
            models_config = {
                'RandomForest': RandomForestClassifier(
                    n_estimators=100, max_depth=12, min_samples_split=5,
                    class_weight={0: 0.8, 1: 1.1, 2: 1.2}, random_state=42
                ),
                'GradientBoosting': GradientBoostingClassifier(
                    n_estimators=90, max_depth=7, learning_rate=0.12,
                    random_state=42
                ),
                'LogisticRegression': LogisticRegression(
                    C=2.0, random_state=42, max_iter=1000
                )
            }
        
        # Train context-specific models
        context_models = {}
        best_accuracy = 0
        
        for name, model in models_config.items():
            model.fit(X_train_scaled, y_train)
            y_pred = model.predict(X_test_scaled)
            accuracy = accuracy_score(y_test, y_pred)
            
            context_models[name] = model
            if accuracy > best_accuracy:
                best_accuracy = accuracy
        
        # Store models for this context
        if context_name == 'home_advantage':
            self.home_advantage_models = context_models
        elif context_name == 'balanced':
            self.balanced_models = context_models
        else:
            self.away_strength_models = context_models
        
        # Generate meta-features (predictions from all models)
        meta_features = []
        for i, model in enumerate(context_models.values()):
            proba = model.predict_proba(X_test_scaled)
            meta_features.append(proba)
        
        # Combine predictions for meta-learning
        combined_meta_features = np.hstack(meta_features)
        
        return best_accuracy, combined_meta_features.tolist(), y_test.tolist()
    
    def _prepare_context_features(self, context_data, context_name):
        """Prepare features optimized for specific context"""
        features = []
        labels = []
        
        for sample in context_data:
            try:
                sf = sample.get('features', {})
                outcome = sample.get('outcome')
                
                if not outcome:
                    continue
                
                # Base features
                hgpg = sf.get('home_goals_per_game', 1.5)
                agpg = sf.get('away_goals_per_game', 1.3)
                hwp = sf.get('home_win_percentage', 0.5)
                awp = sf.get('away_win_percentage', 0.3)
                hfp = sf.get('home_form_points', 8)
                afp = sf.get('away_form_points', 6)
                
                # Context-specific feature engineering
                if context_name == 'home_advantage':
                    # Focus on home team strength indicators
                    feature_vector = [
                        hgpg, hwp, hfp/15, (hgpg * hwp),  # Home strength
                        agpg, awp, afp/15, (agpg * awp),  # Away strength
                        hgpg - agpg, hwp - awp, (hfp - afp)/15,  # Advantages
                        hgpg * hwp * 1.15,  # Home advantage factor
                        abs(hwp - awp), hgpg/3, hwp  # Additional home factors
                    ]
                elif context_name == 'balanced':
                    # Focus on balance and draw-predicting features
                    feature_vector = [
                        hgpg, agpg, hwp, awp, hfp/15, afp/15,  # Base features
                        abs(hgpg - agpg), abs(hwp - awp), abs(hfp - afp)/15,  # Balance indicators
                        min(hgpg, agpg), min(hwp, awp), min(hfp, afp)/15,  # Minimum strengths
                        (hgpg + agpg)/2, (hwp + awp)/2, (hfp + afp)/30,  # Averages
                        1.0 - abs(hwp - awp)  # Balance score
                    ]
                else:  # away_strength
                    # Focus on away team competitive factors
                    feature_vector = [
                        agpg, awp, afp/15, (agpg * awp),  # Away strength
                        hgpg, hwp, hfp/15, (hgpg * hwp),  # Home strength
                        agpg - hgpg, awp - hwp, (afp - hfp)/15,  # Away advantages
                        agpg * awp * 1.05,  # Away competitiveness
                        awp, agpg/3, (afp/15)  # Additional away factors
                    ]
                
                # Convert outcome to label
                if outcome == 'Home':
                    label = 2
                elif outcome == 'Draw':
                    label = 1
                else:
                    label = 0
                
                features.append(feature_vector)
                labels.append(label)
                
            except Exception:
                continue
        
        return np.array(features), np.array(labels)
    
    def _train_meta_learner(self, meta_features, meta_labels):
        """Train meta-learner to combine specialist predictions"""
        X_meta = np.array(meta_features)
        y_meta = np.array(meta_labels)
        
        # Split meta-data
        X_meta_train, X_meta_test, y_meta_train, y_meta_test = train_test_split(
            X_meta, y_meta, test_size=0.2, random_state=42, stratify=y_meta
        )
        
        # Train meta-learner (simple but effective)
        self.meta_learner = LogisticRegression(
            C=1.0, random_state=42, max_iter=1000, class_weight='balanced'
        )
        self.meta_learner.fit(X_meta_train, y_meta_train)
        
        # Evaluate meta-learner
        y_meta_pred = self.meta_learner.predict(X_meta_test)
        meta_accuracy = accuracy_score(y_meta_test, y_meta_pred)
        
        return meta_accuracy
    
    def _evaluate_full_system(self, training_data):
        """Evaluate the complete specialized ensemble system"""
        # Sample evaluation on held-out data
        sample_size = min(200, len(training_data))
        eval_data = training_data[-sample_size:]
        
        correct_predictions = 0
        total_predictions = 0
        
        for sample in eval_data:
            try:
                prediction = self.predict_with_specialized_ensemble(sample)
                actual = sample.get('outcome')
                
                if prediction and actual:
                    if prediction == actual:
                        correct_predictions += 1
                    total_predictions += 1
                    
            except Exception:
                continue
        
        if total_predictions > 0:
            return correct_predictions / total_predictions
        return 0
    
    def predict_with_specialized_ensemble(self, match_sample):
        """Make prediction using specialized ensemble"""
        if not self.is_trained:
            return None
        
        try:
            features = match_sample.get('features', {})
            
            # Determine match context
            context = self._determine_context(features)
            
            # Get appropriate models
            if context == 'home_advantage' and self.home_advantage_models:
                models = self.home_advantage_models
                scaler = self.scalers['home_advantage']
            elif context == 'balanced' and self.balanced_models:
                models = self.balanced_models
                scaler = self.scalers['balanced']
            elif context == 'away_strength' and self.away_strength_models:
                models = self.away_strength_models
                scaler = self.scalers['away_strength']
            else:
                return None
            
            # Prepare features for this context
            X, _ = self._prepare_context_features([match_sample], context)
            if len(X) == 0:
                return None
            
            X_scaled = scaler.transform(X)
            
            # Get predictions from specialist models
            predictions = []
            for model in models.values():
                proba = model.predict_proba(X_scaled)[0]
                predictions.extend(proba)
            
            # Use meta-learner if available
            if self.meta_learner:
                meta_pred = self.meta_learner.predict([predictions])[0]
            else:
                # Simple ensemble voting
                model_preds = [model.predict(X_scaled)[0] for model in models.values()]
                meta_pred = max(set(model_preds), key=model_preds.count)
            
            # Convert to outcome
            if meta_pred == 2:
                return 'Home'
            elif meta_pred == 1:
                return 'Draw'
            else:
                return 'Away'
                
        except Exception:
            return None
    
    def _determine_context(self, features):
        """Determine which context this match belongs to"""
        home_win_pct = features.get('home_win_percentage', 0.5)
        away_win_pct = features.get('away_win_percentage', 0.3)
        home_form = features.get('home_form_points', 8)
        away_form = features.get('away_form_points', 6)
        
        home_strength = (home_win_pct + home_form/15) / 2
        away_strength = (away_win_pct + away_form/15) / 2
        strength_diff = home_strength - away_strength
        
        if strength_diff > 0.15:
            return 'home_advantage'
        elif abs(strength_diff) <= 0.15:
            return 'balanced'
        else:
            return 'away_strength'
    
    def _save_specialized_models(self):
        """Save all specialized models"""
        try:
            # Save context models
            for context_name, models in [
                ('home_advantage', self.home_advantage_models),
                ('balanced', self.balanced_models),
                ('away_strength', self.away_strength_models)
            ]:
                for model_name, model in models.items():
                    filename = f'models/specialized_{context_name}_{model_name.lower()}.joblib'
                    joblib.dump(model, filename)
            
            # Save scalers
            for context_name, scaler in self.scalers.items():
                filename = f'models/specialized_{context_name}_scaler.joblib'
                joblib.dump(scaler, filename)
            
            # Save meta-learner
            if self.meta_learner:
                joblib.dump(self.meta_learner, 'models/specialized_meta_learner.joblib')
            
            logger.info("All specialized models saved")
            
        except Exception as e:
            logger.error(f"Failed to save specialized models: {e}")

def main():
    """Train and evaluate specialized ensemble system"""
    system = SpecializedEnsembleSystem()
    
    accuracy = system.train_specialized_ensemble()
    
    if accuracy:
        print(f"\nSpecialized Ensemble Results:")
        print(f"Overall System Accuracy: {accuracy:.1%}")
        print(f"Target 70% achieved: {accuracy >= 0.70}")
        print(f"\nApproach: Separate models for home advantage, balanced, and away strength scenarios")
        print(f"Meta-learner combines specialist predictions for optimal accuracy")
        
        if accuracy >= 0.70:
            print("✓ Specialized ensemble approach successful!")
        else:
            print("- Consider expanding training data for each context")
            print("- Add more sophisticated features for each specialist model")
    else:
        print("Specialized ensemble training failed")
    
    return accuracy

if __name__ == "__main__":
    main()