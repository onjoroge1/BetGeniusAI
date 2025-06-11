"""
Multi-Context ML System - Separate models for different game scenarios + Meta-learner
"""
import numpy as np
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, classification_report
import joblib
import json
import logging
from models.database import DatabaseManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class MultiContextMLSystem:
    """Multi-context ML system with specialized models and meta-learner"""
    
    def __init__(self):
        self.db_manager = DatabaseManager()
        
        # Specialized models for different contexts
        self.context_models = {
            'home_favored': {},    # Clear home advantage scenarios
            'competitive': {},     # Evenly matched teams
            'away_strong': {}      # Strong away teams
        }
        
        # Meta-learner to combine predictions
        self.meta_model = None
        self.meta_scaler = StandardScaler()
        
        # Context scalers
        self.context_scalers = {
            'home_favored': StandardScaler(),
            'competitive': StandardScaler(),
            'away_strong': StandardScaler()
        }
        
        self.is_trained = False
        
    def train_multi_context_system(self):
        """Train the complete multi-context system"""
        try:
            logger.info("Training multi-context ML system")
            
            # Load training data
            training_data = self.db_manager.load_training_data()
            logger.info(f"Training with {len(training_data)} samples")
            
            # Split data into contexts
            context_data = self._split_by_context(training_data)
            
            # Train specialized models for each context
            meta_features_list = []
            meta_labels_list = []
            
            for context_name, data in context_data.items():
                if len(data) < 30:  # Need minimum samples
                    logger.warning(f"Insufficient data for {context_name}: {len(data)} samples")
                    continue
                
                logger.info(f"Training {context_name} models with {len(data)} samples")
                
                # Train context-specific models
                context_accuracy, meta_features, meta_labels = self._train_context_specialists(
                    context_name, data
                )
                
                # Collect meta-learning data
                if meta_features is not None:
                    meta_features_list.extend(meta_features)
                    meta_labels_list.extend(meta_labels)
                
                logger.info(f"{context_name} best accuracy: {context_accuracy:.1%}")
            
            # Train meta-learner
            if meta_features_list:
                meta_accuracy = self._train_meta_model(meta_features_list, meta_labels_list)
                logger.info(f"Meta-model accuracy: {meta_accuracy:.1%}")
            
            # Evaluate complete system
            system_accuracy = self._evaluate_system(training_data)
            
            self.is_trained = True
            self._save_all_models()
            
            logger.info(f"Multi-context system accuracy: {system_accuracy:.1%}")
            return system_accuracy
            
        except Exception as e:
            logger.error(f"Multi-context training failed: {e}")
            return 0
    
    def _split_by_context(self, training_data):
        """Split matches into different contexts based on team strengths"""
        home_favored = []
        competitive = []
        away_strong = []
        
        for sample in training_data:
            try:
                features = sample.get('features', {})
                
                # Calculate strength indicators
                home_strength = self._calculate_team_strength(features, 'home')
                away_strength = self._calculate_team_strength(features, 'away')
                
                strength_diff = home_strength - away_strength
                
                # Categorize based on strength difference
                if strength_diff > 0.2:  # Clear home advantage
                    home_favored.append(sample)
                elif strength_diff < -0.1:  # Away team stronger
                    away_strong.append(sample)
                else:  # Competitive match
                    competitive.append(sample)
                    
            except Exception:
                competitive.append(sample)  # Default category
        
        logger.info(f"Context distribution:")
        logger.info(f"  Home favored: {len(home_favored)} matches")
        logger.info(f"  Competitive: {len(competitive)} matches") 
        logger.info(f"  Away strong: {len(away_strong)} matches")
        
        return {
            'home_favored': home_favored,
            'competitive': competitive,
            'away_strong': away_strong
        }
    
    def _calculate_team_strength(self, features, team_type):
        """Calculate normalized team strength"""
        if team_type == 'home':
            goals_pg = features.get('home_goals_per_game', 1.5)
            win_pct = features.get('home_win_percentage', 0.5)
            form = features.get('home_form_points', 8)
        else:
            goals_pg = features.get('away_goals_per_game', 1.3)
            win_pct = features.get('away_win_percentage', 0.3)
            form = features.get('away_form_points', 6)
        
        # Normalize and combine strength indicators
        goals_norm = min(goals_pg / 3.0, 1.0)
        win_norm = min(win_pct, 1.0)
        form_norm = min(form / 15.0, 1.0)
        
        return (goals_norm + win_norm + form_norm) / 3
    
    def _train_context_specialists(self, context_name, context_data):
        """Train specialized models for specific context"""
        # Prepare features and labels
        X, y = self._prepare_context_features(context_data, context_name)
        
        if len(X) < 20:
            return 0, None, None
        
        # Split data
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.25, random_state=42, stratify=y
        )
        
        # Scale features
        scaler = self.context_scalers[context_name]
        X_train_scaled = scaler.fit_transform(X_train)
        X_test_scaled = scaler.transform(X_test)
        
        # Context-optimized models
        if context_name == 'home_favored':
            # Optimize for home win detection
            models = {
                'rf': RandomForestClassifier(
                    n_estimators=80, max_depth=8, min_samples_split=3,
                    class_weight={0: 1.2, 1: 1.0, 2: 0.7}, random_state=42
                ),
                'gb': GradientBoostingClassifier(
                    n_estimators=60, max_depth=6, learning_rate=0.15,
                    random_state=42
                ),
                'lr': LogisticRegression(C=1.0, random_state=42, max_iter=1000)
            }
        elif context_name == 'competitive':
            # Optimize for balanced prediction including draws
            models = {
                'rf': RandomForestClassifier(
                    n_estimators=100, max_depth=10, min_samples_split=5,
                    class_weight='balanced', random_state=42
                ),
                'gb': GradientBoostingClassifier(
                    n_estimators=80, max_depth=5, learning_rate=0.1,
                    random_state=42
                ),
                'lr': LogisticRegression(C=0.5, class_weight='balanced', random_state=42, max_iter=1000)
            }
        else:  # away_strong
            # Optimize for away win detection
            models = {
                'rf': RandomForestClassifier(
                    n_estimators=80, max_depth=12, min_samples_split=3,
                    class_weight={0: 0.7, 1: 1.0, 2: 1.3}, random_state=42
                ),
                'gb': GradientBoostingClassifier(
                    n_estimators=70, max_depth=7, learning_rate=0.12,
                    random_state=42
                ),
                'lr': LogisticRegression(C=2.0, random_state=42, max_iter=1000)
            }
        
        # Train models
        best_accuracy = 0
        trained_models = {}
        
        for name, model in models.items():
            model.fit(X_train_scaled, y_train)
            y_pred = model.predict(X_test_scaled)
            accuracy = accuracy_score(y_test, y_pred)
            
            trained_models[name] = model
            if accuracy > best_accuracy:
                best_accuracy = accuracy
        
        # Store trained models
        self.context_models[context_name] = trained_models
        
        # Generate meta-features for meta-learning
        meta_features = []
        for model in trained_models.values():
            probabilities = model.predict_proba(X_test_scaled)
            for prob_vector in probabilities:
                meta_features.append(list(prob_vector))
        
        # Flatten meta-features properly
        meta_feature_vectors = []
        for i in range(len(X_test_scaled)):
            vector = []
            for model in trained_models.values():
                proba = model.predict_proba(X_test_scaled[i:i+1])[0]
                vector.extend(proba)
            meta_feature_vectors.append(vector)
        
        return best_accuracy, meta_feature_vectors, y_test.tolist()
    
    def _prepare_context_features(self, context_data, context_name):
        """Prepare optimized features for each context"""
        features = []
        labels = []
        
        for sample in context_data:
            try:
                sf = sample.get('features', {})
                outcome = sample.get('outcome')
                
                if not outcome:
                    continue
                
                # Extract base features
                hgpg = sf.get('home_goals_per_game', 1.5)
                agpg = sf.get('away_goals_per_game', 1.3)
                hwp = sf.get('home_win_percentage', 0.5)
                awp = sf.get('away_win_percentage', 0.3)
                hfp = sf.get('home_form_points', 8)
                afp = sf.get('away_form_points', 6)
                
                # Context-specific feature engineering
                if context_name == 'home_favored':
                    # Emphasize home team strengths
                    feature_vector = [
                        hgpg, hwp, hfp/15.0,           # Home strengths
                        agpg, awp, afp/15.0,           # Away strengths
                        hgpg - agpg, hwp - awp,        # Home advantages
                        hgpg * hwp, (hfp/15.0) * hwp,  # Combined home strength
                        0.15  # Home advantage factor
                    ]
                elif context_name == 'competitive':
                    # Emphasize balance and draw factors
                    feature_vector = [
                        hgpg, agpg, hwp, awp, hfp/15.0, afp/15.0,  # Base features
                        abs(hgpg - agpg), abs(hwp - awp),          # Balance indicators
                        min(hwp, awp), (hgpg + agpg)/2,            # Competitive factors
                        1.0 - abs(hwp - awp)  # Balance score
                    ]
                else:  # away_strong
                    # Emphasize away team competitive factors
                    feature_vector = [
                        agpg, awp, afp/15.0,           # Away strengths
                        hgpg, hwp, hfp/15.0,           # Home strengths
                        agpg - hgpg, awp - hwp,        # Away advantages
                        agpg * awp, (afp/15.0) * awp,  # Combined away strength
                        -0.05  # Reduced home advantage
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
    
    def _train_meta_model(self, meta_features, meta_labels):
        """Train meta-model to combine specialist predictions"""
        X_meta = np.array(meta_features)
        y_meta = np.array(meta_labels)
        
        # Split meta data
        X_meta_train, X_meta_test, y_meta_train, y_meta_test = train_test_split(
            X_meta, y_meta, test_size=0.2, random_state=42, stratify=y_meta
        )
        
        # Scale meta features
        X_meta_train_scaled = self.meta_scaler.fit_transform(X_meta_train)
        X_meta_test_scaled = self.meta_scaler.transform(X_meta_test)
        
        # Train meta-model
        self.meta_model = LogisticRegression(
            C=1.0, class_weight='balanced', random_state=42, max_iter=1000
        )
        self.meta_model.fit(X_meta_train_scaled, y_meta_train)
        
        # Evaluate
        y_meta_pred = self.meta_model.predict(X_meta_test_scaled)
        meta_accuracy = accuracy_score(y_meta_test, y_meta_pred)
        
        return meta_accuracy
    
    def _evaluate_system(self, training_data):
        """Evaluate the complete multi-context system"""
        sample_data = training_data[-100:]  # Use last 100 samples for evaluation
        correct = 0
        total = 0
        
        for sample in sample_data:
            try:
                predicted = self.predict_with_context(sample)
                actual = sample.get('outcome')
                
                if predicted and actual:
                    if predicted == actual:
                        correct += 1
                    total += 1
                    
            except Exception:
                continue
        
        return correct / total if total > 0 else 0
    
    def predict_with_context(self, match_sample):
        """Make prediction using context-specific models and meta-learner"""
        if not self.is_trained:
            return None
        
        try:
            features = match_sample.get('features', {})
            
            # Determine context
            home_strength = self._calculate_team_strength(features, 'home')
            away_strength = self._calculate_team_strength(features, 'away')
            strength_diff = home_strength - away_strength
            
            if strength_diff > 0.2:
                context = 'home_favored'
            elif strength_diff < -0.1:
                context = 'away_strong'
            else:
                context = 'competitive'
            
            # Get context models
            models = self.context_models.get(context, {})
            if not models:
                return None
            
            # Prepare features
            X, _ = self._prepare_context_features([match_sample], context)
            if len(X) == 0:
                return None
            
            # Scale features
            scaler = self.context_scalers[context]
            X_scaled = scaler.transform(X)
            
            # Get predictions from specialist models
            meta_features = []
            for model in models.values():
                proba = model.predict_proba(X_scaled)[0]
                meta_features.extend(proba)
            
            # Use meta-model if available
            if self.meta_model and len(meta_features) > 0:
                meta_features_scaled = self.meta_scaler.transform([meta_features])
                prediction = self.meta_model.predict(meta_features_scaled)[0]
            else:
                # Fallback to ensemble voting
                predictions = [model.predict(X_scaled)[0] for model in models.values()]
                prediction = max(set(predictions), key=predictions.count)
            
            # Convert to outcome
            if prediction == 2:
                return 'Home'
            elif prediction == 1:
                return 'Draw'
            else:
                return 'Away'
                
        except Exception:
            return None
    
    def _save_all_models(self):
        """Save all trained models"""
        try:
            # Save context models
            for context_name, models in self.context_models.items():
                for model_name, model in models.items():
                    filename = f'models/context_{context_name}_{model_name}.joblib'
                    joblib.dump(model, filename)
            
            # Save scalers
            for context_name, scaler in self.context_scalers.items():
                filename = f'models/context_{context_name}_scaler.joblib'
                joblib.dump(scaler, filename)
            
            # Save meta-model and scaler
            if self.meta_model:
                joblib.dump(self.meta_model, 'models/context_meta_model.joblib')
                joblib.dump(self.meta_scaler, 'models/context_meta_scaler.joblib')
            
            logger.info("Multi-context models saved")
            
        except Exception as e:
            logger.error(f"Failed to save models: {e}")

def main():
    """Train and evaluate multi-context ML system"""
    system = MultiContextMLSystem()
    
    accuracy = system.train_multi_context_system()
    
    print(f"\nMulti-Context ML System Results:")
    print(f"System Accuracy: {accuracy:.1%}")
    print(f"Target 70% achieved: {accuracy >= 0.70}")
    print(f"\nApproach: Specialized models for different match contexts + Meta-learner")
    
    if accuracy >= 0.70:
        print("Multi-context approach successful!")
    else:
        print("Recommendations:")
        print("- Expand dataset with more diverse leagues")
        print("- Add player-level and tactical features")
        print("- Include historical head-to-head data")
    
    return accuracy

if __name__ == "__main__":
    main()