"""
Hybrid Ensemble System - League specialists + Global ensemble for optimal performance
"""
import json
import numpy as np
from sqlalchemy import create_engine, text
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier, VotingClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, confusion_matrix
import os

class HybridEnsembleSystem:
    """Hybrid system combining league specialists with global ensemble"""
    
    def __init__(self):
        self.engine = create_engine(os.environ.get('DATABASE_URL'))
        self.league_specialists = {}
        self.league_scalers = {}
        self.global_ensemble = None
        self.global_scaler = None
        
        # League complexity classification
        self.simple_leagues = [140, 78, 135, 88, 61, 203, 179]  # Perfect specialist performance
        self.complex_leagues = [39, 143]  # Require hybrid approach
    
    def train_hybrid_system(self):
        """Train hybrid system with league specialists and global ensemble"""
        
        # Load all data
        with self.engine.connect() as conn:
            result = conn.execute(text('SELECT league_id, features, outcome FROM training_matches WHERE features IS NOT NULL'))
            all_data = []
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
                    
                    sample = {'league_id': league_id, 'features': features, 'outcome': outcome}
                    all_data.append(sample)
                    
                    if league_id not in league_data:
                        league_data[league_id] = []
                    league_data[league_id].append(sample)
                except:
                    continue
        
        print(f"Training hybrid system with {len(all_data)} matches")
        
        # Train league specialists for simple leagues
        specialist_results = {}
        for league_id in self.simple_leagues:
            if league_id in league_data and len(league_data[league_id]) >= 50:
                result = self._train_league_specialist(league_id, league_data[league_id])
                specialist_results[league_id] = result
        
        # Train global ensemble for complex leagues and fallback
        complex_data = []
        for sample in all_data:
            if sample['league_id'] in self.complex_leagues or sample['league_id'] not in self.league_specialists:
                complex_data.append(sample)
        
        global_result = self._train_global_ensemble(complex_data)
        
        return specialist_results, global_result
    
    def _train_league_specialist(self, league_id, data):
        """Train specialist for specific league"""
        league_names = {
            140: 'La Liga', 78: 'Bundesliga', 135: 'Serie A',
            88: 'Eredivisie', 61: 'Ligue 1', 203: 'Turkish Super Lig', 179: 'Greek Super League'
        }
        
        league_name = league_names.get(league_id, f'League {league_id}')
        
        # Create optimized features for this league
        X, y = [], []
        
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
                
                # League-specific optimization
                if league_id in [140, 78, 88]:  # High home advantage
                    home_boost = 1.15
                elif league_id in [61]:  # Competitive league
                    home_boost = 0.95
                else:
                    home_boost = 1.0
                
                # Simplified but effective features for specialists
                feature_vector = [
                    hgpg * home_boost,
                    agpg,
                    hwp * home_boost,
                    awp,
                    (hfp - afp) / 15.0,  # Form difference
                    sd * home_boost,
                    abs(hwp - awp) * home_boost,
                    hwp * hgpg * home_boost,  # Home power
                    awp * agpg  # Away power
                ]
                
                label = 2 if outcome == 'Home' else (1 if outcome == 'Draw' else 0)
                X.append(feature_vector)
                y.append(label)
            except:
                continue
        
        if len(X) < 30:
            return None
        
        X = np.array(X)
        y = np.array(y)
        
        # Train specialist
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.25, random_state=42)
        
        scaler = StandardScaler()
        X_train_scaled = scaler.fit_transform(X_train)
        X_test_scaled = scaler.transform(X_test)
        
        # Optimized specialist model
        specialist = RandomForestClassifier(
            n_estimators=300, max_depth=20, min_samples_split=3,
            class_weight='balanced', random_state=42, n_jobs=-1
        )
        
        specialist.fit(X_train_scaled, y_train)
        y_pred = specialist.predict(X_test_scaled)
        
        # Store models
        self.league_specialists[league_id] = specialist
        self.league_scalers[league_id] = scaler
        
        # Evaluate
        accuracy = accuracy_score(y_test, y_pred)
        cm = confusion_matrix(y_test, y_pred)
        
        away_acc = cm[0][0] / sum(cm[0]) if len(cm) > 0 and sum(cm[0]) > 0 else 0
        draw_acc = cm[1][1] / sum(cm[1]) if len(cm) > 1 and sum(cm[1]) > 0 else 0
        home_acc = cm[2][2] / sum(cm[2]) if len(cm) > 2 and sum(cm[2]) > 0 else 0
        
        result = {
            'league_name': league_name,
            'accuracy': accuracy,
            'home_accuracy': home_acc,
            'away_accuracy': away_acc,
            'draw_accuracy': draw_acc,
            'matches': len(X)
        }
        
        print(f"{league_name} specialist: {accuracy:.1%} overall, {home_acc:.1%} home")
        return result
    
    def _train_global_ensemble(self, data):
        """Train global ensemble for complex leagues"""
        
        # Create comprehensive features
        X, y = [], []
        
        for sample in data:
            try:
                sf = sample['features']
                outcome = sample['outcome']
                league_id = sample['league_id']
                
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
                
                # Enhanced features for complex prediction
                home_power = hwp * hgpg * (1 + max(0, sd))
                away_power = awp * agpg * (1 + max(0, -sd))
                tactical_balance = cb * tc * ts
                competitive_edge = mu * cb
                
                # League context features
                is_premier = float(league_id == 39)
                is_brazilian = float(league_id == 143)
                is_complex = float(league_id in self.complex_leagues)
                
                feature_vector = [
                    # Core performance
                    hgpg, agpg, hwp, awp, hfp/15.0, afp/15.0, sd,
                    
                    # Enhanced power metrics
                    home_power, away_power, home_power / (away_power + 0.01),
                    
                    # Tactical intelligence
                    tactical_balance, competitive_edge, cb, tc, mu, ts,
                    
                    # Balance indicators
                    abs(hwp - awp), (hwp + awp)/2, abs(hgpg - agpg),
                    
                    # Advanced interactions
                    hwp * tc, awp * ts, sd * cb, mu * ts,
                    
                    # Meta features
                    home_power - away_power, 1.0 - abs(sd),
                    tactical_balance * competitive_edge,
                    
                    # League context
                    is_premier, is_brazilian, is_complex
                ]
                
                label = 2 if outcome == 'Home' else (1 if outcome == 'Draw' else 0)
                X.append(feature_vector)
                y.append(label)
            except:
                continue
        
        X = np.array(X)
        y = np.array(y)
        
        print(f"Training global ensemble with {len(X)} complex matches")
        
        # Train global ensemble
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.15, random_state=42, stratify=y)
        
        self.global_scaler = StandardScaler()
        X_train_scaled = self.global_scaler.fit_transform(X_train)
        X_test_scaled = self.global_scaler.transform(X_test)
        
        # Advanced ensemble for complex cases
        self.global_ensemble = VotingClassifier(
            estimators=[
                ('rf1', RandomForestClassifier(
                    n_estimators=800, max_depth=35, min_samples_split=2,
                    class_weight='balanced', random_state=42, n_jobs=-1
                )),
                ('rf2', RandomForestClassifier(
                    n_estimators=600, max_depth=30, min_samples_split=3,
                    class_weight='balanced_subsample', random_state=43, n_jobs=-1
                )),
                ('gb', GradientBoostingClassifier(
                    n_estimators=400, max_depth=25, learning_rate=0.05,
                    subsample=0.9, random_state=42
                ))
            ],
            voting='soft', weights=[0.4, 0.35, 0.25]
        )
        
        self.global_ensemble.fit(X_train_scaled, y_train)
        y_pred = self.global_ensemble.predict(X_test_scaled)
        
        # Evaluate
        accuracy = accuracy_score(y_test, y_pred)
        cm = confusion_matrix(y_test, y_pred)
        
        away_acc = cm[0][0] / sum(cm[0]) if len(cm) > 0 and sum(cm[0]) > 0 else 0
        draw_acc = cm[1][1] / sum(cm[1]) if len(cm) > 1 and sum(cm[1]) > 0 else 0
        home_acc = cm[2][2] / sum(cm[2]) if len(cm) > 2 and sum(cm[2]) > 0 else 0
        
        result = {
            'accuracy': accuracy,
            'home_accuracy': home_acc,
            'away_accuracy': away_acc,
            'draw_accuracy': draw_acc,
            'matches': len(X)
        }
        
        print(f"Global ensemble: {accuracy:.1%} overall, {home_acc:.1%} home")
        return result
    
    def predict(self, match_features, league_id):
        """Predict using hybrid system"""
        
        # Use specialist if available and league is simple
        if league_id in self.league_specialists and league_id in self.simple_leagues:
            model = self.league_specialists[league_id]
            scaler = self.league_scalers[league_id]
            
            # Create specialist features (simplified)
            specialist_features = match_features[:9]  # Use first 9 features
            
            X_scaled = scaler.transform([specialist_features])
            prediction = model.predict(X_scaled)[0]
            probabilities = model.predict_proba(X_scaled)[0]
            
        else:
            # Use global ensemble for complex leagues
            model = self.global_ensemble
            scaler = self.global_scaler
            
            # Add league context to features
            enhanced_features = match_features + [
                float(league_id == 39),  # is_premier
                float(league_id == 143),  # is_brazilian
                float(league_id in self.complex_leagues)  # is_complex
            ]
            
            X_scaled = scaler.transform([enhanced_features])
            prediction = model.predict(X_scaled)[0]
            probabilities = model.predict_proba(X_scaled)[0]
        
        outcome_map = {0: 'Away', 1: 'Draw', 2: 'Home'}
        return outcome_map[prediction], probabilities
    
    def evaluate_system(self):
        """Evaluate complete hybrid system"""
        
        # Test on recent data
        with self.engine.connect() as conn:
            result = conn.execute(text('SELECT league_id, features, outcome FROM training_matches WHERE features IS NOT NULL ORDER BY match_date DESC LIMIT 300'))
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
        
        # Test predictions
        correct = 0
        home_correct = 0
        away_correct = 0
        draw_correct = 0
        
        home_total = 0
        away_total = 0
        draw_total = 0
        
        for sample in test_data:
            try:
                league_id = sample['league_id']
                features = sample['features']
                true_outcome = sample['outcome']
                
                # Create feature vector
                feature_vector = [
                    features.get('home_goals_per_game', 1.5),
                    features.get('away_goals_per_game', 1.3),
                    features.get('home_win_percentage', 0.44),
                    features.get('away_win_percentage', 0.32),
                    features.get('home_form_points', 8) / 15.0,
                    features.get('away_form_points', 6) / 15.0,
                    features.get('strength_difference', 0.15),
                    abs(features.get('home_win_percentage', 0.44) - features.get('away_win_percentage', 0.32)),
                    features.get('home_win_percentage', 0.44) * features.get('home_goals_per_game', 1.5),
                    features.get('away_win_percentage', 0.32) * features.get('away_goals_per_game', 1.3)
                ]
                
                # Extend for global ensemble
                while len(feature_vector) < 30:
                    feature_vector.append(0.0)
                
                predicted_outcome, probabilities = self.predict(feature_vector, league_id)
                
                if predicted_outcome == true_outcome:
                    correct += 1
                
                if true_outcome == 'Home':
                    home_total += 1
                    if predicted_outcome == 'Home':
                        home_correct += 1
                elif true_outcome == 'Away':
                    away_total += 1
                    if predicted_outcome == 'Away':
                        away_correct += 1
                else:
                    draw_total += 1
                    if predicted_outcome == 'Draw':
                        draw_correct += 1
                        
            except:
                continue
        
        total_tested = home_total + away_total + draw_total
        overall_accuracy = correct / total_tested if total_tested > 0 else 0
        
        home_accuracy = home_correct / home_total if home_total > 0 else 0
        away_accuracy = away_correct / away_total if away_total > 0 else 0
        draw_accuracy = draw_correct / draw_total if draw_total > 0 else 0
        
        return {
            'overall_accuracy': overall_accuracy,
            'home_accuracy': home_accuracy,
            'away_accuracy': away_accuracy,
            'draw_accuracy': draw_accuracy,
            'tested_samples': total_tested
        }

def main():
    """Execute hybrid ensemble system"""
    system = HybridEnsembleSystem()
    
    print("HYBRID ENSEMBLE SYSTEM")
    print("=" * 30)
    print("Combining league specialists with global ensemble")
    print()
    
    # Train system
    specialist_results, global_result = system.train_hybrid_system()
    
    print("\nSPECIALIST PERFORMANCE:")
    print("-" * 25)
    for league_id, result in specialist_results.items():
        if result:
            print(f"{result['league_name']}: {result['accuracy']:.1%} overall, {result['home_accuracy']:.1%} home")
    
    print(f"\nGLOBAL ENSEMBLE:")
    print(f"Complex leagues: {global_result['accuracy']:.1%} overall, {global_result['home_accuracy']:.1%} home")
    
    # Evaluate complete system
    evaluation = system.evaluate_system()
    
    print(f"\nHYBRID SYSTEM RESULTS:")
    print("-" * 24)
    print(f"Overall accuracy: {evaluation['overall_accuracy']:.1%}")
    print(f"Home predictions: {evaluation['home_accuracy']:.1%}")
    print(f"Away predictions: {evaluation['away_accuracy']:.1%}")
    print(f"Draw predictions: {evaluation['draw_accuracy']:.1%}")
    
    # Assessment
    target_achieved = evaluation['overall_accuracy'] >= 0.70
    home_recovered = evaluation['home_accuracy'] >= 0.85
    
    print(f"\nASSESSMENT:")
    if target_achieved:
        print("✓ 70% accuracy target achieved")
    else:
        gap = 0.70 - evaluation['overall_accuracy']
        print(f"Gap to 70%: {gap:.1%}")
    
    if home_recovered:
        print("✓ Home prediction accuracy recovered")
    
    status = "PRODUCTION READY" if target_achieved else "OPTIMIZATION PHASE"
    print(f"Status: {status}")
    
    return evaluation

if __name__ == "__main__":
    results = main()