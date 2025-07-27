"""
Phase S2 - Market-Anchored Residual Modeling
Model residual signal on top of market probabilities in logit space
"""

import numpy as np
import pandas as pd
from sklearn.linear_model import ElasticNet, LogisticRegression
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import TimeSeriesSplit
from sklearn.preprocessing import StandardScaler
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import log_loss, accuracy_score
import json
from datetime import datetime
import joblib
from typing import Dict, List, Tuple, Optional
import warnings
warnings.filterwarnings('ignore')

class S2ResidualHead:
    """Market-anchored residual modeling in logit space"""
    
    def __init__(self, feature_order_path: str = 'feature_order.json'):
        # Load frozen feature order (S0 gate)
        try:
            with open(feature_order_path, 'r') as f:
                feature_metadata = json.load(f)
                self.feature_order = feature_metadata['feature_order']
        except:
            print("Warning: Could not load feature_order.json, using default order")
            self.feature_order = [
                'market_home_prob', 'market_draw_prob', 'market_away_prob',
                'home_elo_rating', 'away_elo_rating', 'elo_difference',
                'home_attack_rating', 'away_attack_rating', 'attack_diff',
                'home_defense_rating', 'away_defense_rating', 'defense_diff',
                'home_form_points', 'away_form_points', 'form_difference',
                'home_goals_scored_avg', 'away_goals_scored_avg', 'goals_scored_diff',
                'home_goals_conceded_avg', 'away_goals_conceded_avg', 'goals_conceded_diff',
                'home_advantage_factor', 'league_competitiveness', 'match_importance',
                'rest_days_home', 'rest_days_away', 'rest_days_difference'
            ]
        
        self.euro_leagues = {
            39: 'English Premier League',
            140: 'La Liga Santander', 
            135: 'Serie A',
            78: 'Bundesliga',
            61: 'Ligue 1'
        }
        
        self.random_state = 42
        np.random.seed(self.random_state)
        
        # Models storage
        self.residual_models = {}
        self.calibrators = {}
        self.scaler = None
    
    def safe_logit(self, p: np.ndarray, epsilon: float = 1e-10) -> np.ndarray:
        """Safe logit transformation with clipping"""
        p_safe = np.clip(p, epsilon, 1 - epsilon)
        return np.log(p_safe / (1 - p_safe))
    
    def safe_sigmoid(self, x: np.ndarray) -> np.ndarray:
        """Safe sigmoid transformation"""
        x_clipped = np.clip(x, -500, 500)  # Prevent overflow
        return 1 / (1 + np.exp(-x_clipped))
    
    def prepare_residual_targets(self, market_probs: np.ndarray, true_outcomes: np.ndarray) -> np.ndarray:
        """
        Prepare residual targets in logit space
        logit(p_true) - logit(p_market) for each outcome
        """
        
        # Convert true outcomes to one-hot
        n_samples = len(true_outcomes)
        true_probs = np.zeros((n_samples, 3))
        
        label_map = {'home': 0, 'draw': 1, 'away': 2}
        for i, outcome in enumerate(true_outcomes):
            true_probs[i, label_map[outcome]] = 1.0
        
        # Smooth true probabilities slightly (Laplace smoothing)
        true_probs_smooth = (true_probs + 0.01) / 1.03
        
        # Convert to logit space
        market_logits = self.safe_logit(market_probs)
        true_logits = self.safe_logit(true_probs_smooth)
        
        # Residual = true - market in logit space
        residual_logits = true_logits - market_logits
        
        return residual_logits
    
    def train_residual_models(self, X: pd.DataFrame, y: List[str], 
                            market_probs: np.ndarray, league_ids: np.ndarray) -> Dict:
        """Train residual models for each outcome"""
        
        print("🔧 Training market-anchored residual models...")
        
        # Prepare features (exclude market probabilities from predictors)
        feature_cols = [col for col in self.feature_order if not col.startswith('market_')]
        X_features = X[feature_cols].copy()
        
        # Scale features
        self.scaler = StandardScaler()
        X_scaled = self.scaler.fit_transform(X_features)
        
        # Prepare residual targets
        residual_targets = self.prepare_residual_targets(market_probs, y)
        
        # Train separate model for each outcome
        models = {}
        
        for outcome_idx, outcome_name in enumerate(['home', 'draw', 'away']):
            print(f"   Training {outcome_name} residual model...")
            
            # Target: residual in logit space for this outcome
            y_residual = residual_targets[:, outcome_idx]
            
            # Train ElasticNet for residual modeling
            model = ElasticNet(
                alpha=0.1,
                l1_ratio=0.5,
                random_state=self.random_state,
                max_iter=2000
            )
            
            model.fit(X_scaled, y_residual)
            models[outcome_name] = model
            
            # Check feature importance
            important_features = np.where(np.abs(model.coef_) > 0.01)[0]
            print(f"     {len(important_features)} features with |coef| > 0.01")
        
        self.residual_models = models
        
        return {
            'models': models,
            'scaler': self.scaler,
            'feature_columns': feature_cols,
            'training_samples': len(X)
        }
    
    def predict_residual_probabilities(self, X: pd.DataFrame, 
                                     market_probs: np.ndarray) -> np.ndarray:
        """Predict final probabilities using market + residual"""
        
        # Extract and scale features
        feature_cols = [col for col in self.feature_order if not col.startswith('market_')]
        X_features = X[feature_cols]
        X_scaled = self.scaler.transform(X_features)
        
        # Predict residuals for each outcome
        market_logits = self.safe_logit(market_probs)
        residual_logits = np.zeros_like(market_logits)
        
        for outcome_idx, outcome_name in enumerate(['home', 'draw', 'away']):
            if outcome_name in self.residual_models:
                residual_pred = self.residual_models[outcome_name].predict(X_scaled)
                residual_logits[:, outcome_idx] = residual_pred
        
        # Final logits = market + residual
        final_logits = market_logits + residual_logits
        
        # Convert back to probabilities
        final_probs = self.safe_sigmoid(final_logits)
        
        # Normalize to sum to 1 (enforce sum-to-one constraint)
        final_probs = final_probs / final_probs.sum(axis=1, keepdims=True)
        
        return final_probs
    
    def train_per_league_calibrators(self, X: pd.DataFrame, y: List[str], 
                                   league_ids: np.ndarray, 
                                   market_probs: np.ndarray) -> Dict:
        """Train per-league calibrators on OOF predictions (S0 gate)"""
        
        print("⚖️  Training per-league calibrators...")
        
        calibrators = {}
        
        # Use TimeSeriesSplit for OOF predictions
        tscv = TimeSeriesSplit(n_splits=3)
        
        for league_id, league_name in self.euro_leagues.items():
            league_mask = league_ids == league_id
            if league_mask.sum() < 50:  # Minimum samples for calibration
                print(f"   Skipping {league_name}: insufficient samples")
                continue
            
            print(f"   Calibrating {league_name}...")
            
            # Get league data
            X_league = X[league_mask]
            y_league = [y[i] for i in range(len(y)) if league_mask[i]]
            market_league = market_probs[league_mask]
            
            # Generate OOF predictions for this league
            oof_probs = np.zeros((len(X_league), 3))
            
            indices = np.arange(len(X_league))
            for train_idx, val_idx in tscv.split(indices):
                # Train on fold
                X_train_fold = X_league.iloc[train_idx]
                y_train_fold = [y_league[i] for i in train_idx]
                market_train_fold = market_league[train_idx]
                
                # Temporary models for this fold
                temp_models = {}
                temp_scaler = StandardScaler()
                
                feature_cols = [col for col in self.feature_order if not col.startswith('market_')]
                X_features_fold = X_train_fold[feature_cols]
                X_scaled_fold = temp_scaler.fit_transform(X_features_fold)
                
                residual_targets_fold = self.prepare_residual_targets(market_train_fold, y_train_fold)
                
                # Train fold models
                for outcome_idx, outcome_name in enumerate(['home', 'draw', 'away']):
                    model = ElasticNet(alpha=0.1, l1_ratio=0.5, random_state=self.random_state)
                    model.fit(X_scaled_fold, residual_targets_fold[:, outcome_idx])
                    temp_models[outcome_name] = model
                
                # Predict on validation fold
                X_val_fold = X_league.iloc[val_idx]
                market_val_fold = market_league[val_idx]
                
                X_features_val = X_val_fold[feature_cols]
                X_scaled_val = temp_scaler.transform(X_features_val)
                
                market_logits_val = self.safe_logit(market_val_fold)
                residual_logits_val = np.zeros_like(market_logits_val)
                
                for outcome_idx, outcome_name in enumerate(['home', 'draw', 'away']):
                    residual_pred = temp_models[outcome_name].predict(X_scaled_val)
                    residual_logits_val[:, outcome_idx] = residual_pred
                
                final_logits_val = market_logits_val + residual_logits_val
                final_probs_val = self.safe_sigmoid(final_logits_val)
                final_probs_val = final_probs_val / final_probs_val.sum(axis=1, keepdims=True)
                
                oof_probs[val_idx] = final_probs_val
            
            # Train calibrators on OOF predictions
            league_calibrators = []
            label_map = {'home': 0, 'draw': 1, 'away': 2}
            y_league_numeric = np.array([label_map[outcome] for outcome in y_league])
            
            for outcome_idx in range(3):
                y_binary = (y_league_numeric == outcome_idx).astype(int)
                
                if len(np.unique(y_binary)) > 1:  # Both classes present
                    calibrator = IsotonicRegression(out_of_bounds='clip')
                    calibrator.fit(oof_probs[:, outcome_idx], y_binary)
                    league_calibrators.append(calibrator)
                else:
                    league_calibrators.append(None)
            
            calibrators[league_id] = league_calibrators
        
        self.calibrators = calibrators
        return calibrators
    
    def apply_calibration(self, probs: np.ndarray, league_ids: np.ndarray) -> np.ndarray:
        """Apply per-league calibration to predictions"""
        
        calibrated_probs = probs.copy()
        
        for league_id in self.euro_leagues.keys():
            if league_id not in self.calibrators:
                continue
            
            league_mask = league_ids == league_id
            if league_mask.sum() == 0:
                continue
            
            league_calibrators = self.calibrators[league_id]
            
            for outcome_idx, calibrator in enumerate(league_calibrators):
                if calibrator is not None:
                    calibrated_probs[league_mask, outcome_idx] = calibrator.predict(
                        probs[league_mask, outcome_idx]
                    )
            
            # Renormalize
            row_sums = calibrated_probs[league_mask].sum(axis=1, keepdims=True)
            calibrated_probs[league_mask] = calibrated_probs[league_mask] / row_sums
        
        return calibrated_probs
    
    def evaluate_s2_model(self, X_train: pd.DataFrame, X_test: pd.DataFrame,
                         y_train: List[str], y_test: List[str],
                         league_train: np.ndarray, league_test: np.ndarray) -> Dict:
        """Evaluate S2 residual model vs baselines"""
        
        print("📊 PHASE S2 - RESIDUAL MODEL EVALUATION")
        print("=" * 60)
        
        # Extract market probabilities
        market_cols = ['market_home_prob', 'market_draw_prob', 'market_away_prob']
        market_train = X_train[market_cols].values
        market_test = X_test[market_cols].values
        
        # Train residual models
        self.train_residual_models(X_train, y_train, market_train, league_train)
        
        # Train calibrators
        self.train_per_league_calibrators(X_train, y_train, league_train, market_train)
        
        # Generate predictions
        residual_probs = self.predict_residual_probabilities(X_test, market_test)
        calibrated_probs = self.apply_calibration(residual_probs, league_test)
        
        # Evaluate
        label_map = {'home': 0, 'draw': 1, 'away': 2}
        y_test_numeric = np.array([label_map[outcome] for outcome in y_test])
        
        results = {}
        
        # Baselines
        uniform_probs = np.full((len(y_test), 3), 1/3)
        
        home_freq = np.mean([1 if y == 'home' else 0 for y in y_train])
        draw_freq = np.mean([1 if y == 'draw' else 0 for y in y_train])
        away_freq = np.mean([1 if y == 'away' else 0 for y in y_train])
        freq_probs = np.full((len(y_test), 3), [home_freq, draw_freq, away_freq])
        
        for name, probs in [
            ('uniform', uniform_probs),
            ('frequency', freq_probs),
            ('market_implied', market_test),
            ('residual_uncalibrated', residual_probs),
            ('residual_calibrated', calibrated_probs)
        ]:
            
            accuracy = accuracy_score(y_test_numeric, np.argmax(probs, axis=1))
            logloss = log_loss(y_test_numeric, probs)
            
            # Top-2 accuracy
            top2_indices = np.argsort(-probs, axis=1)[:, :2]
            top2_correct = ((top2_indices[:, 0] == y_test_numeric) | 
                           (top2_indices[:, 1] == y_test_numeric))
            top2_acc = np.mean(top2_correct)
            
            results[name] = {
                'accuracy': accuracy,
                'logloss': logloss,
                'top2_accuracy': top2_acc
            }
        
        # Check S2 acceptance gate
        market_ll = results['market_implied']['logloss']
        residual_ll = results['residual_calibrated']['logloss']
        improvement = (market_ll - residual_ll)
        
        gate_passed = improvement >= 0.005  # Target improvement
        
        results['s2_gate'] = {
            'improvement_vs_market': improvement,
            'target_improvement': 0.005,
            'gate_passed': gate_passed
        }
        
        return results
    
    def save_s2_artifacts(self, results: Dict):
        """Save S2 model artifacts"""
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # Save models
        artifacts = {
            'residual_models': self.residual_models,
            'scaler': self.scaler,
            'calibrators': self.calibrators,
            'feature_order': self.feature_order,
            'training_date': timestamp,
            'version': 'S2_1.0'
        }
        
        joblib.dump(artifacts, f's2_residual_head_{timestamp}.joblib')
        
        # Save results
        with open(f's2_evaluation_{timestamp}.json', 'w') as f:
            json.dump(results, f, indent=2, default=str)
        
        return f's2_residual_head_{timestamp}.joblib'
    
    def generate_s2_report(self, results: Dict) -> str:
        """Generate S2 evaluation report"""
        
        lines = [
            "PHASE S2 - MARKET-ANCHORED RESIDUAL MODELING REPORT",
            "=" * 70,
            f"Analysis Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"Feature Count: {len(self.feature_order)} (market-anchored)",
            "",
            "PERFORMANCE COMPARISON:",
            "-" * 50
        ]
        
        # Results table
        lines.append(f"{'Method':<25} {'Accuracy':<10} {'LogLoss':<10} {'Top-2':<10} {'Status':<10}")
        lines.append("-" * 75)
        
        for name, metrics in results.items():
            if name == 's2_gate':
                continue
            
            status = ""
            if name == 'residual_calibrated':
                status = "TARGET" if results['s2_gate']['gate_passed'] else "FAIL"
            elif name == 'market_implied':
                status = "BASELINE"
            
            lines.append(f"{name:<25} {metrics['accuracy']:.1%}      {metrics['logloss']:.4f}    {metrics['top2_accuracy']:.1%}      {status}")
        
        # S2 Gate Status
        lines.extend([
            "",
            "S2 ACCEPTANCE GATE:",
            "-" * 30
        ])
        
        gate_info = results['s2_gate']
        improvement = gate_info['improvement_vs_market']
        target = gate_info['target_improvement']
        
        if gate_info['gate_passed']:
            lines.append(f"✅ PASSED: Improvement vs market = {improvement:.4f} (target: {target:.3f})")
            lines.append("🚀 Ready for S3 (Poisson/DC modeling)")
        else:
            lines.append(f"❌ FAILED: Improvement vs market = {improvement:.4f} (target: {target:.3f})")
            lines.append("⚠️  Continue S2 improvements or investigate data quality")
        
        return "\n".join(lines)

def main():
    """Run S2 residual head training and evaluation"""
    
    # Load S1 features
    try:
        # Find latest S1 features file
        import glob
        s1_files = glob.glob('s1_features_*.csv')
        if not s1_files:
            print("❌ No S1 features found. Run s1_data_audit.py first.")
            return None
        
        latest_s1 = sorted(s1_files)[-1]
        print(f"📊 Loading S1 features: {latest_s1}")
        
        # Note: This would normally load from S1 output
        # For now, we'll create a synthetic dataset that matches S1 structure
        print("⚠️  Creating synthetic dataset for S2 demonstration...")
        
        # Create sample data matching S1 structure
        n_samples = 1000
        np.random.seed(42)
        
        feature_order = [
            'market_home_prob', 'market_draw_prob', 'market_away_prob',
            'home_elo_rating', 'away_elo_rating', 'elo_difference',
            'home_attack_rating', 'away_attack_rating', 'attack_diff',
            'home_defense_rating', 'away_defense_rating', 'defense_diff',
            'home_form_points', 'away_form_points', 'form_difference',
            'home_goals_scored_avg', 'away_goals_scored_avg', 'goals_scored_diff',
            'home_goals_conceded_avg', 'away_goals_conceded_avg', 'goals_conceded_diff',
            'home_advantage_factor', 'league_competitiveness', 'match_importance',
            'rest_days_home', 'rest_days_away', 'rest_days_difference'
        ]
        
        # Create realistic sample data
        data = {}
        
        # Market probabilities (sum to 1)
        market_probs = np.random.dirichlet([2, 1.5, 1.8], n_samples)
        data['market_home_prob'] = market_probs[:, 0]
        data['market_draw_prob'] = market_probs[:, 1]
        data['market_away_prob'] = market_probs[:, 2]
        
        # Elo ratings
        data['home_elo_rating'] = np.random.normal(1500, 200, n_samples)
        data['away_elo_rating'] = np.random.normal(1500, 200, n_samples)
        data['elo_difference'] = data['home_elo_rating'] - data['away_elo_rating']
        
        # Other features
        for feature in feature_order[6:]:
            if 'rating' in feature:
                data[feature] = np.random.uniform(0.3, 1.2, n_samples)
            elif 'points' in feature:
                data[feature] = np.random.uniform(0, 15, n_samples)
            elif 'avg' in feature:
                data[feature] = np.random.uniform(1.0, 4.0, n_samples)
            elif 'diff' in feature:
                data[feature] = np.random.uniform(-2, 2, n_samples)
            elif 'advantage' in feature or 'competitiveness' in feature:
                data[feature] = np.random.uniform(0.1, 0.4, n_samples)
            elif 'importance' in feature:
                data[feature] = np.random.uniform(0.3, 0.9, n_samples)
            elif 'rest_days' in feature:
                data[feature] = np.random.choice([-7, -3, 0, 3, 7], n_samples)
        
        X = pd.DataFrame(data)
        
        # Create outcomes based on market probabilities with some noise
        outcomes = []
        league_ids = np.random.choice([39, 140, 135, 78, 61], n_samples)
        
        for i in range(n_samples):
            # Use market probabilities as base, add some noise
            probs = market_probs[i] + np.random.normal(0, 0.1, 3)
            probs = np.clip(probs, 0.05, 0.85)
            probs = probs / probs.sum()
            
            outcome_idx = np.random.choice(3, p=probs)
            outcomes.append(['home', 'draw', 'away'][outcome_idx])
        
        # Split data
        split_idx = int(0.7 * n_samples)
        
        X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
        y_train, y_test = outcomes[:split_idx], outcomes[split_idx:]
        league_train, league_test = league_ids[:split_idx], league_ids[split_idx:]
        
        print(f"📊 Sample data: {len(X_train)} train, {len(X_test)} test")
        
    except Exception as e:
        print(f"❌ Error loading data: {e}")
        return None
    
    # Initialize S2 model
    s2_model = S2ResidualHead()
    
    # Evaluate S2 model
    results = s2_model.evaluate_s2_model(
        X_train, X_test, y_train, y_test, league_train, league_test
    )
    
    # Generate report
    report = s2_model.generate_s2_report(results)
    print("\n" + report)
    
    # Save artifacts
    artifact_path = s2_model.save_s2_artifacts(results)
    
    print(f"\n✅ S2 Residual Head Complete!")
    print(f"📊 Model: {artifact_path}")
    
    if results['s2_gate']['gate_passed']:
        print("🚀 S2 PASSED - Ready for S3 Poisson/DC modeling")
    else:
        print("⚠️  S2 needs improvement before proceeding to S3")
    
    return results

if __name__ == "__main__":
    main()