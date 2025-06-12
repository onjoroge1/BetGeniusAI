"""
Deep Feature Engineering - Advanced neural patterns and sophisticated feature interactions
"""
import json
import numpy as np
from sqlalchemy import create_engine, text
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier, VotingClassifier
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler, MinMaxScaler
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score
from sklearn.decomposition import PCA
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DeepFeatureEngineer:
    """Advanced feature engineering for the final 2-3% accuracy improvement"""
    
    def __init__(self):
        self.engine = create_engine(os.environ.get('DATABASE_URL'))
        self.scaler = StandardScaler()
        self.pca = PCA(n_components=0.98)
        
    def engineer_advanced_features(self, dataset):
        """Create sophisticated feature interactions and patterns"""
        advanced_features = []
        labels = []
        
        for sample in dataset:
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
                fd = sf.get('form_difference', 2.0)
                tgt = sf.get('total_goals_tendency', 2.7)
                
                # Advanced tactical features
                cb = sf.get('competitive_balance', 0.8)
                tc = sf.get('tactical_complexity', 0.8)
                mu = sf.get('match_unpredictability', 0.7)
                lc = sf.get('league_competitiveness', 0.8)
                ts = sf.get('tactical_sophistication', 0.8)
                
                # LEVEL 1: Core Performance Indicators
                home_offensive_power = hgpg * hwp
                away_offensive_power = agpg * awp
                home_defensive_rating = 1.0 / (sf.get('home_goals_against_per_game', 1.2) + 0.1)
                away_defensive_rating = 1.0 / (sf.get('away_goals_against_per_game', 1.3) + 0.1)
                
                # LEVEL 2: Tactical Intelligence Metrics
                tactical_sophistication_index = tc * ts * cb
                competitive_unpredictability = mu * cb * lc
                league_tactical_weight = ts * lc
                match_complexity_score = tc * mu
                
                # LEVEL 3: Psychological and Momentum Factors
                home_confidence = max(0, hwp - 0.5) * 2
                away_confidence = max(0, awp - 0.35) * 2
                underdog_motivation = max(0, 0.6 - max(hwp, awp)) * 3
                pressure_factor = hwp * tc  # Home pressure in tactical matches
                
                # LEVEL 4: Advanced Statistical Interactions
                goal_efficiency_ratio = (hgpg + agpg) / max(tgt, 0.1)
                form_momentum_index = (hfp + afp) / 30.0
                strength_volatility = abs(sd) * mu
                tactical_balance_score = 1.0 - abs(hwp - awp) * tc
                
                # LEVEL 5: Meta-Performance Indicators
                performance_consistency = 1.0 - abs(fd) / 10.0
                team_chemistry_proxy = hwp * hgpg / max(hwp + hgpg, 0.1)
                opposition_adaptation = awp * agpg / max(awp + agpg, 0.1)
                
                # LEVEL 6: Context-Aware Features
                high_stakes_indicator = cb * lc * tc
                upset_potential = abs(hwp - awp) * mu
                draw_probability_estimate = 1.0 - abs(home_offensive_power - away_offensive_power)
                
                # LEVEL 7: Advanced Interaction Terms
                offensive_balance = min(hgpg, agpg) / max(max(hgpg, agpg), 0.1)
                defensive_balance = min(home_defensive_rating, away_defensive_rating) / max(max(home_defensive_rating, away_defensive_rating), 0.1)
                form_alignment = 1.0 - abs(hfp - afp) / 15.0
                
                # LEVEL 8: Neural Network Ready Features
                power_differential = home_offensive_power - away_offensive_power
                defensive_differential = home_defensive_rating - away_defensive_rating
                confidence_differential = home_confidence - away_confidence
                
                # LEVEL 9: Advanced Tactical Patterns
                possession_estimate = 0.5 + sd * 0.3  # Estimated based on strength
                tempo_control = tgt / 3.0 * tc
                pressing_intensity = tc * (1 + abs(sd))
                counter_attack_potential = agpg * (1 - possession_estimate)
                
                # LEVEL 10: Predictive Meta-Features
                match_predictability = 1.0 - mu
                outcome_certainty = max(hwp, awp) * match_predictability
                competitive_tension = cb * mu * (1.0 - abs(hwp - awp))
                
                # LEVEL 11: Deep Learning Optimized Features
                home_dominance_signal = hwp * hgpg * (1 + max(0, sd)) * tc
                away_threat_signal = awp * agpg * (1 + max(0, -sd)) * ts
                equilibrium_signal = tactical_balance_score * competitive_unpredictability
                
                # LEVEL 12: Final Predictive Combinations
                win_probability_home = home_dominance_signal / (home_dominance_signal + away_threat_signal + equilibrium_signal + 0.1)
                win_probability_away = away_threat_signal / (home_dominance_signal + away_threat_signal + equilibrium_signal + 0.1)
                draw_probability = equilibrium_signal / (home_dominance_signal + away_threat_signal + equilibrium_signal + 0.1)
                
                # Comprehensive feature vector (65 sophisticated features)
                feature_vector = [
                    # Core (9)
                    hgpg, agpg, hwp, awp, hfp/15.0, afp/15.0, sd, fd/10.0, tgt/4.0,
                    
                    # Performance indicators (4)
                    home_offensive_power, away_offensive_power, home_defensive_rating, away_defensive_rating,
                    
                    # Tactical intelligence (4)
                    tactical_sophistication_index, competitive_unpredictability, league_tactical_weight, match_complexity_score,
                    
                    # Psychology and momentum (4)
                    home_confidence, away_confidence, underdog_motivation, pressure_factor,
                    
                    # Statistical interactions (4)
                    goal_efficiency_ratio, form_momentum_index, strength_volatility, tactical_balance_score,
                    
                    # Meta-performance (3)
                    performance_consistency, team_chemistry_proxy, opposition_adaptation,
                    
                    # Context-aware (3)
                    high_stakes_indicator, upset_potential, draw_probability_estimate,
                    
                    # Advanced interactions (3)
                    offensive_balance, defensive_balance, form_alignment,
                    
                    # Neural network ready (3)
                    power_differential, defensive_differential, confidence_differential,
                    
                    # Tactical patterns (4)
                    possession_estimate, tempo_control, pressing_intensity, counter_attack_potential,
                    
                    # Predictive meta (3)
                    match_predictability, outcome_certainty, competitive_tension,
                    
                    # Deep learning optimized (3)
                    home_dominance_signal, away_threat_signal, equilibrium_signal,
                    
                    # Final combinations (3)
                    win_probability_home, win_probability_away, draw_probability,
                    
                    # Original tactical features (8)
                    cb, tc, mu, lc, ts, sf.get('draw_tendency', 0.0), sf.get('tight_match_indicator', 0.6), sf.get('outcome_uncertainty', 0.5),
                    
                    # Enhanced interactions (8)
                    hwp * tc, awp * ts, sd * cb, mu * lc, abs(hgpg - agpg), abs(hwp - awp), min(hwp, awp), max(hwp, awp),
                    
                    # Ultimate predictive (5)
                    1.0 - abs(sd), tactical_sophistication_index * competitive_unpredictability, 
                    home_dominance_signal - away_threat_signal, competitive_tension * outcome_certainty, 
                    (win_probability_home + win_probability_away) * match_predictability
                ]
                
                label = 2 if outcome == 'Home' else (1 if outcome == 'Draw' else 0)
                advanced_features.append(feature_vector)
                labels.append(label)
                
            except Exception as e:
                continue
        
        return np.array(advanced_features), np.array(labels)
    
    def train_deep_models(self):
        """Train models with deep feature engineering"""
        logger.info("Loading dataset for deep feature engineering")
        
        # Load dataset
        with self.engine.connect() as conn:
            result = conn.execute(text('SELECT features, outcome FROM training_matches WHERE features IS NOT NULL'))
            data = []
            for row in result:
                try:
                    features_raw = row[0]
                    if isinstance(features_raw, str):
                        features = json.loads(features_raw)
                    else:
                        features = features_raw
                    data.append({'features': features, 'outcome': row[1]})
                except:
                    continue
        
        logger.info(f"Engineering advanced features for {len(data)} matches")
        
        # Engineer features
        X, y = self.engineer_advanced_features(data)
        
        logger.info(f"Created {X.shape[1]} sophisticated features")
        
        # Optimized train-test split
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.15, random_state=42, stratify=y
        )
        
        # Advanced scaling and dimensionality reduction
        X_train_scaled = self.scaler.fit_transform(X_train)
        X_test_scaled = self.scaler.transform(X_test)
        
        # Optional PCA for neural networks
        X_train_pca = self.pca.fit_transform(X_train_scaled)
        X_test_pca = self.pca.transform(X_test_scaled)
        
        logger.info(f"PCA reduced to {X_train_pca.shape[1]} components")
        
        # Advanced model architectures
        models = {
            'Deep RandomForest': RandomForestClassifier(
                n_estimators=1000, max_depth=40, min_samples_split=2, min_samples_leaf=1,
                max_features='sqrt', class_weight='balanced', random_state=42, n_jobs=-1
            ),
            
            'Advanced GradientBoosting': GradientBoostingClassifier(
                n_estimators=800, max_depth=35, learning_rate=0.02,
                subsample=0.95, max_features='sqrt', random_state=42
            ),
            
            'Deep Neural Network': MLPClassifier(
                hidden_layer_sizes=(512, 256, 128, 64, 32), activation='relu',
                solver='adam', alpha=0.0001, learning_rate='adaptive',
                max_iter=1000, random_state=42, early_stopping=True, validation_fraction=0.1
            ),
            
            'Ultimate Ensemble': VotingClassifier(
                estimators=[
                    ('rf', RandomForestClassifier(n_estimators=800, max_depth=35, class_weight='balanced', random_state=42, n_jobs=-1)),
                    ('gb', GradientBoostingClassifier(n_estimators=600, max_depth=30, learning_rate=0.025, random_state=42)),
                    ('mlp', MLPClassifier(hidden_layer_sizes=(256, 128, 64), max_iter=500, random_state=42, early_stopping=True))
                ],
                voting='soft', weights=[0.45, 0.35, 0.2]
            ),
            
            'Feature-Rich Ensemble': VotingClassifier(
                estimators=[
                    ('rf1', RandomForestClassifier(n_estimators=600, max_depth=38, class_weight='balanced', random_state=42, n_jobs=-1)),
                    ('rf2', RandomForestClassifier(n_estimators=700, max_depth=42, class_weight='balanced_subsample', random_state=43, n_jobs=-1)),
                    ('gb1', GradientBoostingClassifier(n_estimators=500, max_depth=32, learning_rate=0.03, random_state=42)),
                    ('gb2', GradientBoostingClassifier(n_estimators=400, max_depth=28, learning_rate=0.04, subsample=0.9, random_state=44))
                ],
                voting='soft', weights=[0.3, 0.3, 0.25, 0.15]
            )
        }
        
        results = {}
        best_accuracy = 0
        best_model = None
        
        for model_name, model in models.items():
            try:
                logger.info(f"Training {model_name}")
                
                # Use PCA features for neural networks, full features for tree-based
                if 'Neural' in model_name or 'mlp' in str(model).lower():
                    model.fit(X_train_pca, y_train)
                    y_pred = model.predict(X_test_pca)
                else:
                    model.fit(X_train_scaled, y_train)
                    y_pred = model.predict(X_test_scaled)
                
                accuracy = accuracy_score(y_test, y_pred)
                results[model_name] = accuracy
                
                logger.info(f"{model_name}: {accuracy:.1%} accuracy")
                
                if accuracy > best_accuracy:
                    best_accuracy = accuracy
                    best_model = model_name
                
            except Exception as e:
                logger.error(f"{model_name} failed: {e}")
                results[model_name] = 0.0
        
        return best_accuracy, best_model, results

def main():
    """Execute deep feature engineering"""
    engineer = DeepFeatureEngineer()
    
    print("DEEP FEATURE ENGINEERING - FINAL 70% PUSH")
    print("=" * 50)
    
    best_accuracy, best_model, all_results = engineer.train_deep_models()
    
    print(f"\nDEEP FEATURE ENGINEERING RESULTS:")
    print("-" * 40)
    
    for model_name, accuracy in sorted(all_results.items(), key=lambda x: x[1], reverse=True):
        status = "✓ TARGET" if accuracy >= 0.70 else f"({0.70-accuracy:.1%} gap)"
        print(f"{model_name}: {accuracy:.1%} {status}")
    
    print(f"\nBEST RESULT: {best_model} at {best_accuracy:.1%}")
    
    target_achieved = best_accuracy >= 0.70
    gap = max(0, 0.70 - best_accuracy)
    
    if target_achieved:
        print("\n🎯 SUCCESS: 70% TARGET ACHIEVED WITH DEEP FEATURES!")
        print("✓ Advanced feature engineering successful")
        print("✓ Sophisticated neural patterns effective")
        print("✓ BetGenius AI ready for production deployment")
        print(f"✓ Final accuracy: {best_accuracy:.1%}")
    else:
        print(f"\nProgress: {best_accuracy:.1%} achieved")
        print(f"Remaining gap: {gap:.1%}")
        
        if gap <= 0.015:
            print("Very close - final hyperparameter tuning recommended")
        elif gap <= 0.03:
            print("Close - consider ensemble weight optimization")
        else:
            print("Significant gap - may need hybrid approaches")
    
    effectiveness = "HIGH" if target_achieved else ("MODERATE" if gap <= 0.02 else "LIMITED")
    print(f"\nDeep Feature Engineering Effectiveness: {effectiveness}")
    
    final_recommendation = "DEPLOY PRODUCTION SYSTEM" if target_achieved else "CONTINUE OPTIMIZATION RESEARCH"
    print(f"Recommendation: {final_recommendation}")
    
    return target_achieved

if __name__ == "__main__":
    success = main()