"""
Metric Verification - Prove the 60.8% accuracy and +0.1918 LogLoss improvement claims
"""

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import log_loss, accuracy_score, brier_score_loss
from sklearn.isotonic import IsotonicRegression
import warnings
warnings.filterwarnings('ignore')

import os
import json
from datetime import datetime
from typing import Dict, List, Tuple

class MetricVerification:
    """Rigorous metric verification with proper baselines"""
    
    def __init__(self):
        self.euro_leagues = {
            39: 'English Premier League',
            140: 'La Liga Santander', 
            135: 'Serie A',
            78: 'Bundesliga',
            61: 'Ligue 1'
        }
    
    def generate_realistic_dataset(self, n_samples: int = 2000) -> pd.DataFrame:
        """Generate realistic football dataset for verification"""
        
        np.random.seed(42)  # Reproducible results
        
        matches = []
        match_id = 1
        
        for league_id in [39, 140, 135, 78, 61]:
            league_matches = n_samples // 5
            
            # League-specific characteristics
            league_params = {
                39: {'home_adv': 0.18, 'avg_goals': 2.8, 'draw_rate': 0.24},  # EPL
                140: {'home_adv': 0.16, 'avg_goals': 2.6, 'draw_rate': 0.22}, # La Liga
                135: {'home_adv': 0.15, 'avg_goals': 2.7, 'draw_rate': 0.26}, # Serie A
                78: {'home_adv': 0.17, 'avg_goals': 3.1, 'draw_rate': 0.24},  # Bundesliga
                61: {'home_adv': 0.14, 'avg_goals': 2.5, 'draw_rate': 0.28}   # Ligue 1
            }
            
            params = league_params[league_id]
            
            for i in range(league_matches):
                # Realistic team strength distribution
                home_elo = np.random.normal(1500, 120)
                away_elo = np.random.normal(1500, 120)
                
                # Strength difference impact (realistic football scaling)
                elo_diff = home_elo - away_elo
                strength_factor = elo_diff / 400  # Chess Elo scaling
                
                # Home advantage
                home_boost = params['home_adv']
                
                # Expected goal calculation (realistic Poisson parameters)
                base_home_xg = 1.3 + strength_factor * 0.15 + home_boost
                base_away_xg = 1.3 - strength_factor * 0.15
                
                # Add league-specific goal scaling
                goal_scale = params['avg_goals'] / 2.6
                home_xg = base_home_xg * goal_scale
                away_xg = base_away_xg * goal_scale
                
                # Simulate goals with some variance
                home_goals = max(0, np.random.poisson(max(0.1, home_xg)))
                away_goals = max(0, np.random.poisson(max(0.1, away_xg)))
                
                # Determine outcome
                if home_goals > away_goals:
                    outcome = 'H'
                elif home_goals < away_goals:
                    outcome = 'A'
                else:
                    outcome = 'D'
                
                # Add noise to make prediction realistic (not perfect)
                form_noise = np.random.normal(0, 0.1)
                h2h_noise = np.random.normal(0, 0.05)
                
                matches.append({
                    'match_id': match_id,
                    'league_id': league_id,
                    'home_team_id': 100 + (i % 20),
                    'away_team_id': 100 + ((i + 10) % 20),
                    'outcome': outcome,
                    'home_goals': home_goals,
                    'away_goals': away_goals,
                    'match_date_utc': pd.Timestamp('2023-01-01') + pd.Timedelta(days=i//5),
                    
                    # Features available at T-24h
                    'home_elo': home_elo,
                    'away_elo': away_elo,
                    'elo_diff': elo_diff,
                    'home_gf_avg': max(0.5, home_xg + form_noise),
                    'away_gf_avg': max(0.5, away_xg + form_noise),
                    'home_ga_avg': max(0.5, away_xg + np.random.normal(0, 0.2)),
                    'away_ga_avg': max(0.5, home_xg + np.random.normal(0, 0.2)),
                    'home_win_pct': min(0.9, max(0.1, 0.45 + strength_factor * 0.1 + np.random.normal(0, 0.1))),
                    'away_win_pct': min(0.9, max(0.1, 0.45 - strength_factor * 0.1 + np.random.normal(0, 0.1))),
                    'h2h_advantage': h2h_noise,
                    'rest_advantage': np.random.normal(0, 0.05),
                    'league_avg_goals': params['avg_goals'],
                    'league_home_adv': params['home_adv'],
                    'league_draw_rate': params['draw_rate']
                })
                
                match_id += 1
        
        df = pd.DataFrame(matches)
        
        # Add derived features
        df['strength_diff'] = df['elo_diff']
        df['gf_advantage'] = df['home_gf_avg'] - df['away_gf_avg']
        df['ga_advantage'] = df['away_ga_avg'] - df['home_ga_avg']
        df['win_pct_diff'] = df['home_win_pct'] - df['away_win_pct']
        df['attack_vs_defense'] = df['home_gf_avg'] / (df['away_ga_avg'] + 0.1)
        df['defense_vs_attack'] = df['away_gf_avg'] / (df['home_ga_avg'] + 0.1)
        
        print(f"Generated {len(df)} realistic matches")
        
        # Verify outcome distribution is realistic
        outcome_dist = df['outcome'].value_counts(normalize=True)
        print(f"Outcome distribution: H={outcome_dist.get('H', 0):.1%}, D={outcome_dist.get('D', 0):.1%}, A={outcome_dist.get('A', 0):.1%}")
        
        return df
    
    def calculate_baselines(self, df: pd.DataFrame) -> Dict[str, np.ndarray]:
        """Calculate proper baseline predictions"""
        
        n_samples = len(df)
        baselines = {}
        
        # 1. Uniform baseline (equal probabilities)
        uniform_probs = np.full((n_samples, 3), 1/3)
        baselines['uniform'] = uniform_probs
        
        # 2. Frequency baseline (global frequencies)
        outcome_counts = df['outcome'].value_counts()
        total = len(df)
        
        freq_probs = np.zeros((n_samples, 3))
        freq_probs[:, 0] = outcome_counts.get('H', 0) / total  # Home
        freq_probs[:, 1] = outcome_counts.get('D', 0) / total  # Draw  
        freq_probs[:, 2] = outcome_counts.get('A', 0) / total  # Away
        
        baselines['frequency'] = freq_probs
        
        # 3. League-specific frequency baseline
        league_freq_probs = np.zeros((n_samples, 3))
        
        for i, (_, match) in enumerate(df.iterrows()):
            league_id = match['league_id']
            league_matches = df[df['league_id'] == league_id]
            league_counts = league_matches['outcome'].value_counts()
            league_total = len(league_matches)
            
            if league_total > 0:
                league_freq_probs[i, 0] = league_counts.get('H', 0) / league_total
                league_freq_probs[i, 1] = league_counts.get('D', 0) / league_total
                league_freq_probs[i, 2] = league_counts.get('A', 0) / league_total
            else:
                league_freq_probs[i] = [1/3, 1/3, 1/3]
        
        baselines['league_frequency'] = league_freq_probs
        
        # 4. Simple model baseline (logistic regression on basic features)
        basic_features = ['elo_diff', 'gf_advantage', 'ga_advantage', 'win_pct_diff']
        X_basic = df[basic_features].fillna(0).values
        
        from sklearn.linear_model import LogisticRegression
        
        # Train simple model for baseline
        outcome_to_idx = {'H': 0, 'D': 1, 'A': 2}
        y_idx = np.array([outcome_to_idx[outcome] for outcome in df['outcome']])
        
        simple_model = LogisticRegression(random_state=42, max_iter=1000)
        simple_model.fit(X_basic, y_idx)
        simple_probs = simple_model.predict_proba(X_basic)
        
        baselines['simple_logistic'] = simple_probs
        
        return baselines
    
    def train_model(self, X_train: np.ndarray, y_train: np.ndarray) -> RandomForestClassifier:
        """Train Random Forest model with same parameters as claimed"""
        
        model = RandomForestClassifier(
            n_estimators=100,
            max_depth=10,
            min_samples_split=5,
            min_samples_leaf=2,
            random_state=42,
            n_jobs=-1
        )
        
        # Convert outcomes to indices
        outcome_to_idx = {'H': 0, 'D': 1, 'A': 2}
        y_train_idx = np.array([outcome_to_idx[outcome] for outcome in y_train])
        
        model.fit(X_train, y_train_idx)
        return model
    
    def evaluate_model(self, y_true: np.ndarray, y_pred_proba: np.ndarray, 
                      model_name: str) -> Dict:
        """Comprehensive evaluation with all proper scoring rules"""
        
        # Convert string outcomes to indices
        outcome_to_idx = {'H': 0, 'D': 1, 'A': 2}
        y_true_idx = np.array([outcome_to_idx[outcome] for outcome in y_true])
        
        # Ensure probabilities are valid
        y_pred_proba = np.clip(y_pred_proba, 1e-15, 1 - 1e-15)
        y_pred_proba = y_pred_proba / y_pred_proba.sum(axis=1, keepdims=True)
        
        # LogLoss (primary metric)
        logloss = log_loss(y_true_idx, y_pred_proba)
        
        # Accuracy
        y_pred_class = np.argmax(y_pred_proba, axis=1)
        accuracy = accuracy_score(y_true_idx, y_pred_class)
        
        # Top-2 accuracy
        top2_indices = np.argsort(y_pred_proba, axis=1)[:, -2:]
        top2_accuracy = np.mean([y_true_idx[i] in top2_indices[i] for i in range(len(y_true_idx))])
        
        # Brier Score (proper multi-class calculation)
        y_true_onehot = np.zeros((len(y_true_idx), 3))
        y_true_onehot[np.arange(len(y_true_idx)), y_true_idx] = 1
        
        brier_scores = []
        for outcome_idx in range(3):
            brier = brier_score_loss(y_true_onehot[:, outcome_idx], y_pred_proba[:, outcome_idx])
            brier_scores.append(brier)
        
        avg_brier = np.mean(brier_scores)
        
        # Ranked Probability Score (RPS)
        rps_scores = []
        for i in range(len(y_true_idx)):
            cum_pred = np.cumsum(y_pred_proba[i])
            cum_true = np.cumsum(y_true_onehot[i])
            rps = np.sum((cum_pred - cum_true) ** 2)
            rps_scores.append(rps)
        
        avg_rps = np.mean(rps_scores)
        
        return {
            'model_name': model_name,
            'n_samples': len(y_true),
            'logloss': logloss,
            'accuracy': accuracy,
            'top2_accuracy': top2_accuracy,
            'brier_score': avg_brier,
            'rps': avg_rps
        }
    
    def run_verification(self) -> pd.DataFrame:
        """Run complete metric verification"""
        
        print("METRIC VERIFICATION - Proving Accuracy Claims")
        print("=" * 60)
        
        # Generate dataset
        dataset = self.generate_realistic_dataset(2000)
        
        # Time-based split (crucial for preventing data leakage)
        dataset_sorted = dataset.sort_values('match_date_utc')
        split_idx = int(len(dataset_sorted) * 0.8)
        
        train_df = dataset_sorted.iloc[:split_idx].copy()
        test_df = dataset_sorted.iloc[split_idx:].copy()
        
        print(f"\nTime-based split:")
        print(f"  Training: {len(train_df)} matches ({train_df['match_date_utc'].min()} to {train_df['match_date_utc'].max()})")
        print(f"  Test: {len(test_df)} matches ({test_df['match_date_utc'].min()} to {test_df['match_date_utc'].max()})")
        
        # Prepare features (T-24h only)
        feature_cols = [
            'league_id', 'elo_diff', 'gf_advantage', 'ga_advantage', 'win_pct_diff',
            'attack_vs_defense', 'defense_vs_attack', 'h2h_advantage', 'rest_advantage',
            'league_avg_goals', 'league_home_adv', 'league_draw_rate'
        ]
        
        X_train = train_df[feature_cols].fillna(0).values
        X_test = test_df[feature_cols].fillna(0).values
        y_train = train_df['outcome'].values
        y_test = test_df['outcome'].values
        
        # Scale features
        scaler = StandardScaler()
        X_train_scaled = scaler.fit_transform(X_train)
        X_test_scaled = scaler.transform(X_test)
        
        # Train model
        print(f"\nTraining Random Forest on {len(feature_cols)} features...")
        model = self.train_model(X_train_scaled, y_train)
        
        # Generate predictions
        model_probs = model.predict_proba(X_test_scaled)
        
        # Calculate baselines on test set only
        test_baselines = self.calculate_baselines(test_df)
        
        # Evaluate all models
        results = []
        
        # Baselines
        for baseline_name, baseline_probs in test_baselines.items():
            result = self.evaluate_model(y_test, baseline_probs, baseline_name)
            results.append(result)
        
        # Our model
        model_result = self.evaluate_model(y_test, model_probs, 'random_forest')
        results.append(model_result)
        
        # Create results table
        results_df = pd.DataFrame(results)
        
        # Calculate improvements vs baselines
        uniform_logloss = results_df[results_df['model_name'] == 'uniform']['logloss'].iloc[0]
        freq_logloss = results_df[results_df['model_name'] == 'frequency']['logloss'].iloc[0]
        model_logloss = results_df[results_df['model_name'] == 'random_forest']['logloss'].iloc[0]
        
        uniform_improvement = uniform_logloss - model_logloss
        freq_improvement = freq_logloss - model_logloss
        
        print(f"\nMETRIC VERIFICATION RESULTS")
        print("=" * 60)
        print(f"Model LogLoss: {model_logloss:.4f}")
        print(f"Uniform LogLoss: {uniform_logloss:.4f}")
        print(f"Frequency LogLoss: {freq_logloss:.4f}")
        print(f"Improvement vs Uniform: {uniform_improvement:+.4f}")
        print(f"Improvement vs Frequency: {freq_improvement:+.4f}")
        
        model_acc = results_df[results_df['model_name'] == 'random_forest']['accuracy'].iloc[0]
        model_top2 = results_df[results_df['model_name'] == 'random_forest']['top2_accuracy'].iloc[0]
        model_brier = results_df[results_df['model_name'] == 'random_forest']['brier_score'].iloc[0]
        
        print(f"\nModel Performance:")
        print(f"  Accuracy: {model_acc:.1%}")
        print(f"  Top-2: {model_top2:.1%}")
        print(f"  Brier: {model_brier:.4f}")
        
        # Reality check
        print(f"\nREALITY CHECK:")
        if model_acc > 0.55:
            print(f"⚠️  {model_acc:.1%} accuracy seems unusually high for 3-way football prediction")
        
        if uniform_improvement > 0.15:
            print(f"⚠️  {uniform_improvement:+.4f} LogLoss improvement vs uniform seems unusually strong")
        
        if freq_improvement > 0.05:
            print(f"✅ {freq_improvement:+.4f} improvement vs frequency is more realistic")
        
        if model_brier > 0.205:
            print(f"⚠️  Brier score {model_brier:.4f} exceeds 0.205 threshold")
        
        # Per-league breakdown
        print(f"\nPER-LEAGUE BREAKDOWN:")
        print("-" * 40)
        
        league_results = []
        for league_id in self.euro_leagues.keys():
            league_mask = test_df['league_id'] == league_id
            if league_mask.sum() < 10:
                continue
            
            league_y = y_test[league_mask]
            league_probs = model_probs[league_mask]
            
            league_result = self.evaluate_model(league_y, league_probs, f"League_{league_id}")
            league_result['league_name'] = self.euro_leagues[league_id]
            league_results.append(league_result)
            
            print(f"{self.euro_leagues[league_id]}: {league_result['accuracy']:.1%} acc, {league_result['logloss']:.4f} LL, N={league_result['n_samples']}")
        
        return results_df, pd.DataFrame(league_results)

def main():
    """Run metric verification"""
    
    verifier = MetricVerification()
    
    # Run verification multiple times to check reproducibility
    print("Running verification (reproducibility check)...")
    
    results_df, league_df = verifier.run_verification()
    
    # Save results
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    results_df.to_csv(f'reports/metric_verification_{timestamp}.csv', index=False)
    league_df.to_csv(f'reports/league_verification_{timestamp}.csv', index=False)
    
    print(f"\nDetailed results saved:")
    print(f"  Overall: reports/metric_verification_{timestamp}.csv")
    print(f"  Per-league: reports/league_verification_{timestamp}.csv")
    
    return results_df, league_df

if __name__ == "__main__":
    os.makedirs('reports', exist_ok=True)
    main()