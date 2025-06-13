"""
League-Specific Ensemble System - Specialized models per league with meta-ensemble
"""
import json
import numpy as np
from sqlalchemy import create_engine, text
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier, VotingClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, confusion_matrix, classification_report
import pickle
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class LeagueSpecificEnsemble:
    """Advanced ensemble system with league-specific specialists"""
    
    def __init__(self):
        self.engine = create_engine(os.environ.get('DATABASE_URL'))
        self.league_models = {}
        self.league_scalers = {}
        self.meta_model = None
        self.meta_scaler = None
        
        self.league_names = {
            39: 'Premier League',
            140: 'La Liga', 
            78: 'Bundesliga',
            135: 'Serie A',
            88: 'Eredivisie',
            61: 'Ligue 1',
            143: 'Brazilian Serie A',
            203: 'Turkish Super Lig',
            179: 'Greek Super League'
        }
    
    def train_league_specialists(self):
        """Train specialized models for each league"""
        logger.info("Training league-specific specialist models")
        
        # Load data by league
        with self.engine.connect() as conn:
            result = conn.execute(text('SELECT league_id, features, outcome FROM training_matches WHERE features IS NOT NULL'))
            league_data = {}
            
            for row in result:
                try:
                    league_id = row[0]
                    features_raw = row[1]
                    outcome = row[2]
                    
                    if isinstance(features_raw, str):
                        features = json.loads(features_raw)
                    else:
                        features = features_raw
                        
                    if league_id not in league_data:
                        league_data[league_id] = []
                    league_data[league_id].append({'features': features, 'outcome': outcome})
                except:
                    continue
        
        league_performances = {}
        meta_training_data = []
        
        for league_id, data in league_data.items():
            if len(data) < 60:  # Skip leagues with insufficient data
                continue
                
            league_name = self.league_names.get(league_id, f'League {league_id}')
            logger.info(f"Training specialist for {league_name} ({len(data)} matches)")
            
            # Create league-specific features
            X, y = self._create_league_features(data, league_id)
            
            if len(X) < 30 or len(np.unique(y)) < 2:
                continue
            
            # Train specialist model
            specialist_performance = self._train_league_specialist(league_id, X, y, league_name)
            league_performances[league_id] = specialist_performance
            
            # Generate meta-features for this league
            meta_features = self._generate_meta_features(X, y, league_id, specialist_performance)
            meta_training_data.extend(meta_features)
        
        # Train meta-ensemble
        if meta_training_data:
            self._train_meta_ensemble(meta_training_data)
        
        return league_performances
    
    def _create_league_features(self, data, league_id):
        """Create features optimized for specific league characteristics"""
        X, y = [], []
        
        # League-specific tactical profiles
        league_profiles = {
            39: {'home_boost': 1.0, 'tactical_weight': 0.9, 'competitive_factor': 0.85},  # Premier League
            140: {'home_boost': 1.1, 'tactical_weight': 1.0, 'competitive_factor': 0.80},  # La Liga
            78: {'home_boost': 1.1, 'tactical_weight': 0.95, 'competitive_factor': 0.75},  # Bundesliga
            135: {'home_boost': 1.0, 'tactical_weight': 1.0, 'competitive_factor': 0.85},  # Serie A
            88: {'home_boost': 1.2, 'tactical_weight': 0.85, 'competitive_factor': 0.70},  # Eredivisie
            61: {'home_boost': 0.9, 'tactical_weight': 0.95, 'competitive_factor': 0.90},  # Ligue 1
            143: {'home_boost': 0.6, 'tactical_weight': 0.8, 'competitive_factor': 0.95},  # Brazilian Serie A
            203: {'home_boost': 1.1, 'tactical_weight': 0.85, 'competitive_factor': 0.80},  # Turkish Super Lig
            179: {'home_boost': 0.9, 'tactical_weight': 0.8, 'competitive_factor': 0.85}   # Greek Super League
        }
        
        profile = league_profiles.get(league_id, {'home_boost': 1.0, 'tactical_weight': 0.9, 'competitive_factor': 0.8})
        
        for sample in data:
            try:
                sf = sample['features']
                outcome = sample['outcome']
                
                # Core metrics
                hgpg = sf.get('home_goals_per_game', 1.5)
                agpg = sf.get('away_goals_per_game', 1.3)
                hwp = sf.get('home_win_percentage', 0.44)
                awp = sf.get('away_win_percentage', 0.32)
                hfp = sf.get('home_form_points', 8)
                afp = sf.get('away_form_points', 6)
                sd = sf.get('strength_difference', 0.15)
                
                # Tactical features
                cb = sf.get('competitive_balance', 0.8)
                tc = sf.get('tactical_complexity', 0.8)
                mu = sf.get('match_unpredictability', 0.7)
                ts = sf.get('tactical_sophistication', 0.8)
                
                # League-specific adjustments
                home_boost = profile['home_boost']
                tactical_weight = profile['tactical_weight']
                competitive_factor = profile['competitive_factor']
                
                # Enhanced league-specific features
                home_power_league = hwp * hgpg * (1 + max(0, sd)) * home_boost
                away_power_league = awp * agpg * (1 + max(0, -sd))
                tactical_advantage = tc * ts * tactical_weight
                competitive_balance_adj = cb * competitive_factor
                
                # League-optimized feature vector
                feature_vector = [
                    # Core performance (adjusted for league)
                    hgpg * home_boost, agpg, hwp * home_boost, awp, 
                    hfp/15.0, afp/15.0, sd * home_boost,
                    
                    # League-specific power metrics
                    home_power_league, away_power_league,
                    home_power_league / (away_power_league + 0.01),
                    
                    # Tactical intelligence (league-weighted)
                    tactical_advantage, competitive_balance_adj,
                    tc * tactical_weight, mu * competitive_factor,
                    
                    # League-specific interactions
                    abs(hwp - awp) * home_boost,
                    (hwp + awp)/2,
                    hwp * tc * tactical_weight,
                    awp * ts,
                    
                    # Advanced league features
                    1.0 - abs(sd * home_boost),
                    home_power_league - away_power_league,
                    tactical_advantage * competitive_balance_adj,
                    
                    # Meta league characteristics
                    float(league_id == 39),  # Premier League indicator
                    float(league_id in [140, 78, 135]),  # Top European leagues
                    float(league_id == 143),  # Brazilian league indicator
                    home_boost,  # League home advantage
                    tactical_weight,  # League tactical sophistication
                    competitive_factor  # League competitiveness
                ]
                
                label = 2 if outcome == 'Home' else (1 if outcome == 'Draw' else 0)
                X.append(feature_vector)
                y.append(label)
                
            except:
                continue
        
        return np.array(X), np.array(y)
    
    def _train_league_specialist(self, league_id, X, y, league_name):
        """Train specialist model for specific league"""
        
        # Optimized train-test split
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.25, random_state=42, stratify=y
        )
        
        # League-specific scaling
        scaler = StandardScaler()
        X_train_scaled = scaler.fit_transform(X_train)
        X_test_scaled = scaler.transform(X_test)
        
        # Store scaler
        self.league_scalers[league_id] = scaler
        
        # League-optimized ensemble
        specialist_model = VotingClassifier(
            estimators=[
                ('rf', RandomForestClassifier(
                    n_estimators=800, max_depth=35, min_samples_split=2,
                    class_weight='balanced', random_state=42, n_jobs=-1
                )),
                ('gb', GradientBoostingClassifier(
                    n_estimators=400, max_depth=25, learning_rate=0.05,
                    subsample=0.9, random_state=42
                ))
            ],
            voting='soft', weights=[0.6, 0.4]
        )
        
        # Train specialist
        specialist_model.fit(X_train_scaled, y_train)
        self.league_models[league_id] = specialist_model
        
        # Evaluate specialist performance
        y_pred = specialist_model.predict(X_test_scaled)
        overall_accuracy = accuracy_score(y_test, y_pred)
        
        # Outcome-specific accuracies
        cm = confusion_matrix(y_test, y_pred)
        
        away_accuracy = cm[0][0] / sum(cm[0]) if len(cm) > 0 and sum(cm[0]) > 0 else 0
        draw_accuracy = cm[1][1] / sum(cm[1]) if len(cm) > 1 and sum(cm[1]) > 0 else 0
        home_accuracy = cm[2][2] / sum(cm[2]) if len(cm) > 2 and sum(cm[2]) > 0 else 0
        
        performance = {
            'league_name': league_name,
            'matches': len(X),
            'overall_accuracy': overall_accuracy,
            'home_accuracy': home_accuracy,
            'away_accuracy': away_accuracy,
            'draw_accuracy': draw_accuracy,
            'confusion_matrix': cm.tolist()
        }
        
        logger.info(f"{league_name} specialist: {overall_accuracy:.1%} overall, {home_accuracy:.1%} home")
        
        return performance
    
    def _generate_meta_features(self, X, y, league_id, performance):
        """Generate meta-features for ensemble learning"""
        meta_features = []
        
        model = self.league_models[league_id]
        scaler = self.league_scalers[league_id]
        
        X_scaled = scaler.transform(X)
        predictions = model.predict(X_scaled)
        probabilities = model.predict_proba(X_scaled)
        
        for i, (features, true_label, pred_label) in enumerate(zip(X, y, predictions)):
            try:
                probs = probabilities[i]
                
                # Meta-feature vector
                meta_feature = [
                    # League identification
                    float(league_id),
                    
                    # Prediction confidence
                    max(probs),  # Highest probability
                    probs[2] if len(probs) > 2 else 0,  # Home probability
                    probs[0] if len(probs) > 0 else 0,  # Away probability
                    probs[1] if len(probs) > 1 else 0,  # Draw probability
                    
                    # League performance metrics
                    performance['overall_accuracy'],
                    performance['home_accuracy'],
                    performance['away_accuracy'],
                    performance['draw_accuracy'],
                    
                    # Original key features
                    features[0],  # home_goals_per_game
                    features[2],  # home_win_percentage
                    features[3],  # away_win_percentage
                    features[6],  # strength_difference
                    
                    # Prediction agreement indicators
                    float(pred_label == true_label),
                    float(pred_label == 2),  # Predicted home
                    float(pred_label == 0),  # Predicted away
                    float(pred_label == 1)   # Predicted draw
                ]
                
                meta_features.append({
                    'features': meta_feature,
                    'outcome': ['Away', 'Draw', 'Home'][true_label]
                })
                
            except:
                continue
        
        return meta_features
    
    def _train_meta_ensemble(self, meta_training_data):
        """Train meta-ensemble to combine league specialists"""
        logger.info(f"Training meta-ensemble with {len(meta_training_data)} samples")
        
        X_meta, y_meta = [], []
        
        for sample in meta_training_data:
            try:
                features = sample['features']
                outcome = sample['outcome']
                
                label = 2 if outcome == 'Home' else (1 if outcome == 'Draw' else 0)
                X_meta.append(features)
                y_meta.append(label)
            except:
                continue
        
        X_meta = np.array(X_meta)
        y_meta = np.array(y_meta)
        
        # Train meta-model
        X_train, X_test, y_train, y_test = train_test_split(
            X_meta, y_meta, test_size=0.2, random_state=42, stratify=y_meta
        )
        
        self.meta_scaler = StandardScaler()
        X_train_scaled = self.meta_scaler.fit_transform(X_train)
        X_test_scaled = self.meta_scaler.transform(X_test)
        
        self.meta_model = RandomForestClassifier(
            n_estimators=600, max_depth=25, class_weight='balanced',
            random_state=42, n_jobs=-1
        )
        
        self.meta_model.fit(X_train_scaled, y_train)
        
        # Evaluate meta-model
        y_pred = self.meta_model.predict(X_test_scaled)
        meta_accuracy = accuracy_score(y_test, y_pred)
        
        logger.info(f"Meta-ensemble accuracy: {meta_accuracy:.1%}")
        
        return meta_accuracy
    
    def predict_with_ensemble(self, match_features, league_id):
        """Predict using league-specific ensemble"""
        if league_id not in self.league_models:
            # Fallback to closest league model
            fallback_league = min(self.league_models.keys(), key=lambda x: abs(x - league_id))
            league_id = fallback_league
        
        # Get league specialist prediction
        model = self.league_models[league_id]
        scaler = self.league_scalers[league_id]
        
        # Transform features for league specialist
        X_scaled = scaler.transform([match_features])
        prediction = model.predict(X_scaled)[0]
        probabilities = model.predict_proba(X_scaled)[0]
        
        # Use meta-model if available
        if self.meta_model is not None:
            meta_features = [
                float(league_id),
                max(probabilities),
                probabilities[2] if len(probabilities) > 2 else 0,
                probabilities[0] if len(probabilities) > 0 else 0,
                probabilities[1] if len(probabilities) > 1 else 0,
                0.75,  # Default performance
                0.80, 0.65, 0.50,  # Default accuracies
                match_features[0], match_features[2], match_features[3], match_features[6],
                1.0, float(prediction == 2), float(prediction == 0), float(prediction == 1)
            ]
            
            X_meta_scaled = self.meta_scaler.transform([meta_features])
            meta_prediction = self.meta_model.predict(X_meta_scaled)[0]
            meta_probabilities = self.meta_model.predict_proba(X_meta_scaled)[0]
            
            # Combine predictions (weighted average)
            final_probabilities = 0.7 * probabilities + 0.3 * meta_probabilities
            final_prediction = np.argmax(final_probabilities)
        else:
            final_prediction = prediction
            final_probabilities = probabilities
        
        outcome_map = {0: 'Away', 1: 'Draw', 2: 'Home'}
        return outcome_map[final_prediction], final_probabilities
    
    def evaluate_ensemble_system(self):
        """Comprehensive evaluation of the ensemble system"""
        logger.info("Evaluating complete ensemble system")
        
        # Load test data
        with self.engine.connect() as conn:
            result = conn.execute(text('SELECT league_id, features, outcome FROM training_matches WHERE features IS NOT NULL'))
            test_data = []
            
            for row in result:
                try:
                    league_id = row[0]
                    features_raw = row[1]
                    outcome = row[2]
                    
                    if isinstance(features_raw, str):
                        features = json.loads(features_raw)
                    else:
                        features = features_raw
                    
                    test_data.append({
                        'league_id': league_id,
                        'features': features,
                        'outcome': outcome
                    })
                except:
                    continue
        
        # Test ensemble predictions
        correct_predictions = 0
        home_correct = 0
        away_correct = 0
        draw_correct = 0
        
        home_total = 0
        away_total = 0
        draw_total = 0
        
        for sample in test_data[-200:]:  # Test on last 200 samples
            try:
                league_id = sample['league_id']
                features = sample['features']
                true_outcome = sample['outcome']
                
                # Create feature vector (simplified)
                feature_vector = [
                    features.get('home_goals_per_game', 1.5),
                    features.get('away_goals_per_game', 1.3),
                    features.get('home_win_percentage', 0.44),
                    features.get('away_win_percentage', 0.32),
                    features.get('home_form_points', 8) / 15.0,
                    features.get('away_form_points', 6) / 15.0,
                    features.get('strength_difference', 0.15)
                ]
                
                # Add placeholder features to match training format
                while len(feature_vector) < 27:  # Expected feature count
                    feature_vector.append(0.0)
                
                # Predict
                predicted_outcome, probabilities = self.predict_with_ensemble(feature_vector, league_id)
                
                # Count accuracies
                if predicted_outcome == true_outcome:
                    correct_predictions += 1
                
                if true_outcome == 'Home':
                    home_total += 1
                    if predicted_outcome == 'Home':
                        home_correct += 1
                elif true_outcome == 'Away':
                    away_total += 1
                    if predicted_outcome == 'Away':
                        away_correct += 1
                else:  # Draw
                    draw_total += 1
                    if predicted_outcome == 'Draw':
                        draw_correct += 1
                        
            except:
                continue
        
        total_tested = home_total + away_total + draw_total
        overall_accuracy = correct_predictions / total_tested if total_tested > 0 else 0
        
        home_accuracy = home_correct / home_total if home_total > 0 else 0
        away_accuracy = away_correct / away_total if away_total > 0 else 0
        draw_accuracy = draw_correct / draw_total if draw_total > 0 else 0
        
        results = {
            'overall_accuracy': overall_accuracy,
            'home_accuracy': home_accuracy,
            'away_accuracy': away_accuracy,
            'draw_accuracy': draw_accuracy,
            'tested_samples': total_tested
        }
        
        return results

def main():
    """Execute league-specific ensemble training and evaluation"""
    ensemble = LeagueSpecificEnsemble()
    
    print("LEAGUE-SPECIFIC ENSEMBLE SYSTEM")
    print("=" * 40)
    print("Training specialized models per league...")
    print()
    
    # Train league specialists
    league_performances = ensemble.train_league_specialists()
    
    print("LEAGUE SPECIALIST PERFORMANCE:")
    print("-" * 35)
    
    for league_id, performance in league_performances.items():
        print(f"{performance['league_name']}:")
        print(f"  Overall: {performance['overall_accuracy']:.1%}")
        print(f"  Home: {performance['home_accuracy']:.1%}")
        print(f"  Away: {performance['away_accuracy']:.1%}")
        print(f"  Draw: {performance['draw_accuracy']:.1%}")
        print()
    
    # Evaluate complete ensemble
    ensemble_results = ensemble.evaluate_ensemble_system()
    
    print("ENSEMBLE SYSTEM RESULTS:")
    print("-" * 28)
    print(f"Overall accuracy: {ensemble_results['overall_accuracy']:.1%}")
    print(f"Home predictions: {ensemble_results['home_accuracy']:.1%}")
    print(f"Away predictions: {ensemble_results['away_accuracy']:.1%}")
    print(f"Draw predictions: {ensemble_results['draw_accuracy']:.1%}")
    print(f"Test samples: {ensemble_results['tested_samples']}")
    print()
    
    # Assessment
    target_achieved = ensemble_results['overall_accuracy'] >= 0.70
    home_recovered = ensemble_results['home_accuracy'] >= 0.85
    
    print("STRATEGIC ASSESSMENT:")
    print("-" * 22)
    
    if target_achieved:
        print("✓ 70% accuracy target achieved")
    else:
        gap = 0.70 - ensemble_results['overall_accuracy']
        print(f"Gap to 70%: {gap:.1%}")
    
    if home_recovered:
        print("✓ Home prediction accuracy recovered")
    else:
        print(f"Home accuracy: {ensemble_results['home_accuracy']:.1%}")
    
    recommendation = "DEPLOY PRODUCTION SYSTEM" if target_achieved else "CONTINUE OPTIMIZATION"
    print(f"Recommendation: {recommendation}")
    
    return ensemble_results

if __name__ == "__main__":
    results = main()