"""
European League Betting Optimizer - Focus on leagues African bettors actually use
Priority: Premier League, La Liga, Champions League, Bundesliga, Serie A
"""
import json
import numpy as np
from sqlalchemy import create_engine, text
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier, VotingClassifier
from sklearn.preprocessing import StandardScaler, MinMaxScaler
from sklearn.model_selection import train_test_split, GridSearchCV
from sklearn.metrics import accuracy_score, confusion_matrix, classification_report
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class EuropeanBettingOptimizer:
    """Optimize European leagues for African betting market"""
    
    def __init__(self):
        self.engine = create_engine(os.environ.get('DATABASE_URL'))
        
        # African betting market priorities based on actual betting volume
        self.betting_priorities = {
            39: {
                'name': 'Premier League',
                'betting_volume': 'Very High',
                'priority': 1,
                'target_accuracy': 0.75,
                'market_importance': 'Critical'
            },
            140: {
                'name': 'La Liga', 
                'betting_volume': 'High',
                'priority': 2,
                'target_accuracy': 0.72,
                'market_importance': 'Very Important'
            },
            78: {
                'name': 'Bundesliga',
                'betting_volume': 'Medium-High',
                'priority': 3,
                'target_accuracy': 0.70,
                'market_importance': 'Important'
            },
            135: {
                'name': 'Serie A',
                'betting_volume': 'Medium',
                'priority': 4,
                'target_accuracy': 0.68,
                'market_importance': 'Important'
            },
            61: {
                'name': 'Ligue 1',
                'betting_volume': 'Low-Medium',
                'priority': 5,
                'target_accuracy': 0.65,
                'market_importance': 'Secondary'
            }
        }
        
        self.optimized_models = {}
        self.model_scalers = {}
    
    def optimize_betting_accuracy(self):
        """Optimize accuracy for European leagues African bettors use"""
        
        logger.info("Optimizing European leagues for African betting market")
        
        # Load European league data
        european_data = self._load_european_data()
        
        optimization_results = {}
        
        # Optimize each league in priority order
        for league_id in sorted(self.betting_priorities.keys(), key=lambda x: self.betting_priorities[x]['priority']):
            if league_id not in european_data:
                continue
                
            league_info = self.betting_priorities[league_id]
            data = european_data[league_id]
            
            logger.info(f"Optimizing {league_info['name']} (Priority {league_info['priority']})")
            
            result = self._optimize_league_model(league_id, data, league_info)
            optimization_results[league_id] = result
            
            logger.info(f"{league_info['name']}: {result['accuracy']:.1%} accuracy achieved")
        
        return optimization_results
    
    def _load_european_data(self):
        """Load data for European leagues"""
        
        with self.engine.connect() as conn:
            result = conn.execute(text("""
                SELECT league_id, features, outcome, home_team, away_team 
                FROM training_matches 
                WHERE features IS NOT NULL 
                AND league_id IN (39, 140, 78, 135, 61)
            """))
            
            european_data = {}
            
            for row in result:
                try:
                    league_id = row[0]
                    features_raw = row[1]
                    outcome = row[2]
                    home_team = row[3]
                    away_team = row[4]
                    
                    if isinstance(features_raw, str):
                        features = json.loads(features_raw)
                    else:
                        features = features_raw
                    
                    if league_id not in european_data:
                        european_data[league_id] = []
                    
                    european_data[league_id].append({
                        'features': features,
                        'outcome': outcome,
                        'home_team': home_team,
                        'away_team': away_team
                    })
                except:
                    continue
        
        return european_data
    
    def _optimize_league_model(self, league_id, data, league_info):
        """Optimize model for specific league"""
        
        # Create betting-focused features
        X, y = self._create_betting_features(data, league_id)
        
        if len(X) < 50:
            return {'accuracy': 0.0, 'status': 'insufficient_data'}
        
        # Advanced train-test split
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.15, random_state=42, stratify=y
        )
        
        # Test multiple optimization strategies
        strategies = self._get_optimization_strategies(league_id)
        
        best_accuracy = 0
        best_model = None
        best_scaler = None
        best_strategy = None
        
        for strategy_name, strategy in strategies.items():
            try:
                accuracy, model, scaler = self._test_strategy(
                    X_train, X_test, y_train, y_test, strategy
                )
                
                if accuracy > best_accuracy:
                    best_accuracy = accuracy
                    best_model = model
                    best_scaler = scaler
                    best_strategy = strategy_name
                    
            except Exception as e:
                logger.warning(f"Strategy {strategy_name} failed: {e}")
                continue
        
        # Store best model
        if best_model:
            self.optimized_models[league_id] = best_model
            self.model_scalers[league_id] = best_scaler
        
        # Detailed evaluation
        if best_model and best_scaler:
            detailed_results = self._detailed_evaluation(
                X_test, y_test, best_model, best_scaler
            )
        else:
            detailed_results = {}
        
        return {
            'league_name': league_info['name'],
            'accuracy': best_accuracy,
            'target_accuracy': league_info['target_accuracy'],
            'target_met': best_accuracy >= league_info['target_accuracy'],
            'best_strategy': best_strategy,
            'matches': len(X),
            'market_importance': league_info['market_importance'],
            'betting_volume': league_info['betting_volume'],
            **detailed_results
        }
    
    def _create_betting_features(self, data, league_id):
        """Create features optimized for betting accuracy"""
        
        X, y = [], []
        
        # League-specific tactical adjustments based on betting patterns
        league_adjustments = {
            39: {'home_boost': 1.0, 'tactical_weight': 1.0, 'volatility': 1.2},  # Premier League - unpredictable
            140: {'home_boost': 1.15, 'tactical_weight': 1.1, 'volatility': 0.9},  # La Liga - tactical, home advantage
            78: {'home_boost': 1.1, 'tactical_weight': 0.95, 'volatility': 0.85},  # Bundesliga - consistent
            135: {'home_boost': 1.05, 'tactical_weight': 1.05, 'volatility': 0.95},  # Serie A - tactical
            61: {'home_boost': 0.95, 'tactical_weight': 0.9, 'volatility': 1.1}   # Ligue 1 - competitive
        }
        
        adjustments = league_adjustments.get(league_id, {
            'home_boost': 1.0, 'tactical_weight': 1.0, 'volatility': 1.0
        })
        
        for sample in data:
            try:
                sf = sample['features']
                outcome = sample['outcome']
                
                # Core performance metrics
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
                
                # Apply league-specific adjustments
                home_boost = adjustments['home_boost']
                tactical_weight = adjustments['tactical_weight']
                volatility = adjustments['volatility']
                
                # Enhanced betting features
                home_power_betting = hwp * hgpg * (1 + max(0, sd)) * home_boost
                away_power_betting = awp * agpg * (1 + max(0, -sd))
                tactical_advantage = tc * ts * tactical_weight
                competitive_edge = cb * mu * volatility
                
                # Form momentum (critical for betting)
                form_momentum = (hfp - afp) / 15.0
                recent_form_weight = max(0.5, min(1.5, 1.0 + form_momentum))
                
                # Betting-specific predictive features
                win_probability_differential = abs(hwp - awp) * home_boost
                goal_expectation = (hgpg + agpg) / 2.7  # Normalized to average
                defensive_stability = 1.0 / max(0.1, abs(hgpg - 1.5) + abs(agpg - 1.3))
                
                # Advanced interactions for betting accuracy
                home_dominance_signal = home_power_betting * tactical_advantage * recent_form_weight
                away_threat_signal = away_power_betting * competitive_edge
                equilibrium_signal = (1.0 - win_probability_differential) * cb * volatility
                
                # Meta-betting features
                upset_potential = max(0, 0.4 - max(hwp, awp)) * 2.5  # Underdog potential
                certainty_index = max(hwp, awp) * (1.0 - mu)
                
                # Comprehensive betting feature vector
                feature_vector = [
                    # Core metrics (adjusted)
                    hgpg * home_boost, agpg, hwp * home_boost, awp,
                    hfp/15.0, afp/15.0, sd * home_boost,
                    
                    # Power calculations
                    home_power_betting, away_power_betting,
                    home_power_betting / (away_power_betting + 0.01),
                    
                    # Tactical intelligence
                    tactical_advantage, competitive_edge,
                    tc * tactical_weight, mu * volatility,
                    
                    # Form and momentum
                    form_momentum, recent_form_weight,
                    abs(hfp - afp) / 15.0,
                    
                    # Betting-specific
                    win_probability_differential, goal_expectation,
                    defensive_stability, upset_potential, certainty_index,
                    
                    # Predictive signals
                    home_dominance_signal, away_threat_signal, equilibrium_signal,
                    
                    # Advanced interactions
                    hwp * tc * tactical_weight, awp * mu * volatility,
                    sd * cb * home_boost, tactical_advantage * competitive_edge,
                    
                    # Meta features
                    1.0 - abs(sd * home_boost),
                    home_dominance_signal - away_threat_signal,
                    (home_dominance_signal + away_threat_signal) * certainty_index,
                    equilibrium_signal * upset_potential
                ]
                
                label = 2 if outcome == 'Home' else (1 if outcome == 'Draw' else 0)
                X.append(feature_vector)
                y.append(label)
                
            except:
                continue
        
        return np.array(X), np.array(y)
    
    def _get_optimization_strategies(self, league_id):
        """Get optimization strategies tailored for each league"""
        
        base_strategies = {
            'conservative_ensemble': {
                'models': [
                    ('rf1', RandomForestClassifier(n_estimators=600, max_depth=25, class_weight='balanced', random_state=42)),
                    ('rf2', RandomForestClassifier(n_estimators=400, max_depth=20, class_weight='balanced_subsample', random_state=43))
                ],
                'weights': [0.6, 0.4],
                'scaler': StandardScaler()
            },
            
            'aggressive_ensemble': {
                'models': [
                    ('rf', RandomForestClassifier(n_estimators=800, max_depth=35, class_weight='balanced', random_state=42)),
                    ('gb', GradientBoostingClassifier(n_estimators=400, max_depth=25, learning_rate=0.05, random_state=42))
                ],
                'weights': [0.65, 0.35],
                'scaler': StandardScaler()
            },
            
            'balanced_approach': {
                'models': [
                    ('rf1', RandomForestClassifier(n_estimators=500, max_depth=30, class_weight='balanced', random_state=42)),
                    ('rf2', RandomForestClassifier(n_estimators=300, max_depth=25, class_weight='balanced_subsample', random_state=43)),
                    ('gb', GradientBoostingClassifier(n_estimators=200, max_depth=20, learning_rate=0.08, random_state=42))
                ],
                'weights': [0.4, 0.35, 0.25],
                'scaler': StandardScaler()
            }
        }
        
        # League-specific strategy adjustments
        if league_id == 39:  # Premier League - needs sophisticated approach
            base_strategies['premier_special'] = {
                'models': [
                    ('rf1', RandomForestClassifier(n_estimators=1000, max_depth=40, min_samples_split=2, class_weight='balanced', random_state=42)),
                    ('rf2', RandomForestClassifier(n_estimators=800, max_depth=35, min_samples_split=3, class_weight='balanced_subsample', random_state=43)),
                    ('gb1', GradientBoostingClassifier(n_estimators=600, max_depth=30, learning_rate=0.03, subsample=0.9, random_state=42)),
                    ('gb2', GradientBoostingClassifier(n_estimators=400, max_depth=25, learning_rate=0.05, subsample=0.95, random_state=44))
                ],
                'weights': [0.3, 0.3, 0.25, 0.15],
                'scaler': StandardScaler()
            }
        
        return base_strategies
    
    def _test_strategy(self, X_train, X_test, y_train, y_test, strategy):
        """Test optimization strategy"""
        
        # Scale features
        scaler = strategy['scaler']
        X_train_scaled = scaler.fit_transform(X_train)
        X_test_scaled = scaler.transform(X_test)
        
        # Create ensemble
        ensemble = VotingClassifier(
            estimators=strategy['models'],
            voting='soft',
            weights=strategy['weights']
        )
        
        # Train model
        ensemble.fit(X_train_scaled, y_train)
        
        # Evaluate
        y_pred = ensemble.predict(X_test_scaled)
        accuracy = accuracy_score(y_test, y_pred)
        
        return accuracy, ensemble, scaler
    
    def _detailed_evaluation(self, X_test, y_test, model, scaler):
        """Detailed evaluation for betting market assessment"""
        
        X_test_scaled = scaler.transform(X_test)
        y_pred = model.predict(X_test_scaled)
        
        # Confusion matrix analysis
        cm = confusion_matrix(y_test, y_pred)
        
        # Calculate outcome-specific accuracies
        away_acc = cm[0][0] / sum(cm[0]) if len(cm) > 0 and sum(cm[0]) > 0 else 0
        draw_acc = cm[1][1] / sum(cm[1]) if len(cm) > 1 and sum(cm[1]) > 0 else 0
        home_acc = cm[2][2] / sum(cm[2]) if len(cm) > 2 and sum(cm[2]) > 0 else 0
        
        return {
            'home_accuracy': home_acc,
            'away_accuracy': away_acc, 
            'draw_accuracy': draw_acc,
            'betting_readiness': {
                'home_bets': 'Ready' if home_acc >= 0.70 else 'Needs Work',
                'away_bets': 'Ready' if away_acc >= 0.65 else 'Needs Work',
                'draw_bets': 'Ready' if draw_acc >= 0.50 else 'Needs Work'
            }
        }
    
    def assess_launch_readiness(self, optimization_results):
        """Assess readiness for African betting market launch"""
        
        # Priority weighting for African betting market
        priority_weights = {1: 0.4, 2: 0.3, 3: 0.15, 4: 0.1, 5: 0.05}
        
        weighted_accuracy = 0
        total_weight = 0
        ready_leagues = []
        
        for league_id, result in optimization_results.items():
            priority = self.betting_priorities[league_id]['priority']
            weight = priority_weights[priority]
            
            weighted_accuracy += result['accuracy'] * weight
            total_weight += weight
            
            if result['target_met']:
                ready_leagues.append(result['league_name'])
        
        overall_weighted = weighted_accuracy / total_weight if total_weight > 0 else 0
        
        # Launch readiness assessment
        high_priority_ready = sum(1 for league_id, result in optimization_results.items() 
                                 if self.betting_priorities[league_id]['priority'] <= 2 and result['target_met'])
        
        assessment = {
            'overall_weighted_accuracy': overall_weighted,
            'ready_leagues': ready_leagues,
            'high_priority_ready': high_priority_ready,
            'total_leagues': len(optimization_results),
            'launch_status': self._determine_launch_status(overall_weighted, high_priority_ready, len(ready_leagues))
        }
        
        return assessment
    
    def _determine_launch_status(self, weighted_accuracy, high_priority_ready, total_ready):
        """Determine launch readiness status"""
        
        if weighted_accuracy >= 0.70 and high_priority_ready >= 1:
            return {
                'status': 'LAUNCH READY',
                'recommendation': 'Deploy European leagues for African betting market',
                'confidence': 'High'
            }
        elif weighted_accuracy >= 0.65 and high_priority_ready >= 1:
            return {
                'status': 'NEAR READY', 
                'recommendation': 'Launch with available leagues, optimize others',
                'confidence': 'Medium'
            }
        elif high_priority_ready >= 1:
            return {
                'status': 'PARTIAL READY',
                'recommendation': 'Focus launch on Premier League or La Liga',
                'confidence': 'Medium'
            }
        else:
            return {
                'status': 'OPTIMIZATION NEEDED',
                'recommendation': 'Intensive optimization of Premier League required',
                'confidence': 'Low'
            }

def main():
    """Execute European betting optimization"""
    
    optimizer = EuropeanBettingOptimizer()
    
    print("EUROPEAN BETTING MARKET OPTIMIZATION")
    print("=" * 45)
    print("Focus: Leagues African bettors actually use")
    print()
    
    # Optimize European leagues
    results = optimizer.optimize_betting_accuracy()
    
    print("OPTIMIZATION RESULTS:")
    print("-" * 25)
    
    # Display results in priority order
    for league_id in sorted(results.keys(), key=lambda x: optimizer.betting_priorities[x]['priority']):
        result = results[league_id]
        
        status_icon = "✓" if result['target_met'] else "○"
        gap = result['target_accuracy'] - result['accuracy']
        gap_text = f"(gap: {gap:.1%})" if gap > 0 else ""
        
        print(f"Priority {optimizer.betting_priorities[league_id]['priority']}: {result['league_name']}")
        print(f"  {status_icon} {result['accuracy']:.1%} accuracy {gap_text}")
        print(f"  Volume: {result['betting_volume']} | Target: {result['target_accuracy']:.1%}")
        
        if 'betting_readiness' in result:
            print(f"  Betting Markets: Home {result['betting_readiness']['home_bets']}, "
                  f"Away {result['betting_readiness']['away_bets']}, "
                  f"Draw {result['betting_readiness']['draw_bets']}")
        print()
    
    # Launch readiness assessment
    assessment = optimizer.assess_launch_readiness(results)
    
    print("AFRICAN BETTING MARKET LAUNCH ASSESSMENT:")
    print("-" * 42)
    print(f"Overall Weighted Accuracy: {assessment['overall_weighted_accuracy']:.1%}")
    print(f"Ready Leagues: {len(assessment['ready_leagues'])}/{assessment['total_leagues']}")
    print(f"High Priority Ready: {assessment['high_priority_ready']}/2")
    print(f"Status: {assessment['launch_status']['status']}")
    print(f"Recommendation: {assessment['launch_status']['recommendation']}")
    
    if assessment['ready_leagues']:
        print(f"Launch-Ready Leagues: {', '.join(assessment['ready_leagues'])}")
    
    return results, assessment

if __name__ == "__main__":
    results, assessment = main()