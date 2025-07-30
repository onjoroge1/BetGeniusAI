"""
Improved Static System - Following the verified accuracy-first roadmap
"""

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import TimeSeriesSplit
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import log_loss, accuracy_score, brier_score_loss
from sklearn.isotonic import IsotonicRegression
import warnings
warnings.filterwarnings('ignore')

import os
import json
import joblib
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
import psycopg2

class ImprovedStaticSystem:
    """Production-ready static forecasting system with proper validation"""
    
    def __init__(self):
        self.euro_leagues = {
            39: 'English Premier League',
            140: 'La Liga Santander', 
            135: 'Serie A',
            78: 'Bundesliga',
            61: 'Ligue 1'
        }
        
        self.models = {}
        self.calibrators = {}
        self.feature_names = None
        self.scaler = StandardScaler()
        
    def load_real_match_data(self, min_date: str = None, max_date: str = None) -> pd.DataFrame:
        """Load real match data from database with T-24h constraint"""
        
        if min_date is None:
            min_date = (datetime.now() - timedelta(days=1095)).strftime('%Y-%m-%d')  # 3 years
        if max_date is None:
            max_date = datetime.now().strftime('%Y-%m-%d')
        
        print(f"Loading real match data: {min_date} to {max_date}")
        
        try:
            conn = psycopg2.connect(os.environ['DATABASE_URL'])
            
            # Get comprehensive match data
            query = """
            SELECT 
                match_id,
                league_id,
                season,
                match_date_utc,
                home_team_id,
                away_team_id,
                outcome,
                home_goals,
                away_goals
            FROM matches
            WHERE match_date_utc >= %s
              AND match_date_utc <= %s
              AND outcome IS NOT NULL
              AND league_id IN (39, 140, 135, 78, 61)
              AND home_goals IS NOT NULL
              AND away_goals IS NOT NULL
            ORDER BY match_date_utc ASC
            """
            
            df = pd.read_sql_query(query, conn, params=[min_date + ' 00:00:00', max_date + ' 23:59:59'])
            conn.close()
            
            if len(df) < 500:
                print(f"Warning: Only {len(df)} matches available. Need more data for reliable evaluation.")
                return df
            
            print(f"Loaded {len(df)} real matches")
            
            # Add T-24h features
            df = self._engineer_t24h_features(df)
            
            return df
            
        except Exception as e:
            print(f"Database error: {e}")
            print("Cannot proceed without real match data for verification")
            return pd.DataFrame()
    
    def _engineer_t24h_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Engineer features available at T-24h before kickoff"""
        
        print("Engineering T-24h features...")
        
        # Basic derived features
        df['goal_difference'] = df['home_goals'] - df['away_goals']
        df['total_goals'] = df['home_goals'] + df['away_goals']
        
        # League-level statistics (computed from historical data)
        league_stats = df.groupby('league_id').agg({
            'home_goals': 'mean',
            'away_goals': 'mean',
            'total_goals': 'mean',
            'outcome': lambda x: (x == 'H').mean()
        }).add_prefix('league_')
        
        df = df.merge(league_stats, left_on='league_id', right_index=True)
        
        # Team strength estimation (using expanding window to prevent leakage)
        team_features = []
        
        for _, match in df.iterrows():
            match_date = match['match_date_utc']
            home_team = match['home_team_id']
            away_team = match['away_team_id']
            league_id = match['league_id']
            
            # Only use data from before this match (T-24h constraint)
            cutoff_date = match_date - timedelta(hours=24)
            historical_df = df[df['match_date_utc'] < cutoff_date]
            
            if len(historical_df) == 0:
                # No historical data - use league averages
                team_features.append({
                    'home_elo': 1500,
                    'away_elo': 1500,
                    'home_form_pts': 5,
                    'away_form_pts': 5,
                    'home_gf_avg': match['league_home_goals'],
                    'away_gf_avg': match['league_away_goals'],
                    'home_ga_avg': match['league_away_goals'],
                    'away_ga_avg': match['league_home_goals'],
                    'h2h_home_wins': 1,
                    'h2h_draws': 1,
                    'h2h_away_wins': 1
                })
                continue
            
            # Calculate team strengths from historical data
            home_features = self._calculate_team_strength(historical_df, home_team, league_id, cutoff_date)
            away_features = self._calculate_team_strength(historical_df, away_team, league_id, cutoff_date)
            
            # Head-to-head history
            h2h_features = self._calculate_h2h(historical_df, home_team, away_team)
            
            team_features.append({
                **{f'home_{k}': v for k, v in home_features.items()},
                **{f'away_{k}': v for k, v in away_features.items()},
                **h2h_features
            })
        
        # Add team features to dataframe
        team_df = pd.DataFrame(team_features)
        df = pd.concat([df.reset_index(drop=True), team_df], axis=1)
        
        # Derived difference features (crucial for prediction)
        df['elo_diff'] = df['home_elo'] - df['away_elo']
        df['form_pts_diff'] = df['home_form_pts'] - df['away_form_pts']
        df['gf_avg_diff'] = df['home_gf_avg'] - df['away_gf_avg']
        df['ga_avg_diff'] = df['away_ga_avg'] - df['home_ga_avg']  # Lower GA is better for home
        
        # Attack vs Defense matchups
        df['home_attack_vs_away_defense'] = df['home_gf_avg'] / (df['away_ga_avg'] + 0.1)
        df['away_attack_vs_home_defense'] = df['away_gf_avg'] / (df['home_ga_avg'] + 0.1)
        
        # League context
        df['league_competitiveness'] = 1.0 - np.abs(df['league_outcome'] - 0.5)  # Higher when balanced
        df['home_advantage'] = df['league_outcome'] - 0.33  # League-specific home advantage
        
        return df
    
    def _calculate_team_strength(self, historical_df: pd.DataFrame, team_id: int, 
                               league_id: int, cutoff_date: pd.Timestamp) -> Dict:
        """Calculate team strength metrics from historical matches"""
        
        # Get team's matches
        team_matches = historical_df[
            ((historical_df['home_team_id'] == team_id) | 
             (historical_df['away_team_id'] == team_id)) &
            (historical_df['league_id'] == league_id)
        ].sort_values('match_date_utc').tail(20)  # Last 20 matches
        
        if len(team_matches) == 0:
            return {
                'elo': 1500,
                'form_pts': 5,
                'gf_avg': 1.5,
                'ga_avg': 1.5
            }
        
        # Calculate basic stats
        points = 0
        goals_for = 0
        goals_against = 0
        
        # Recent form (last 5 matches)
        recent_matches = team_matches.tail(5)
        recent_points = 0
        
        for _, match in team_matches.iterrows():
            is_home = match['home_team_id'] == team_id
            team_goals = match['home_goals'] if is_home else match['away_goals']
            opp_goals = match['away_goals'] if is_home else match['home_goals']
            
            goals_for += team_goals
            goals_against += opp_goals
            
            # Points calculation
            if team_goals > opp_goals:
                match_points = 3
            elif team_goals == opp_goals:
                match_points = 1
            else:
                match_points = 0
            
            points += match_points
            
            # Recent form
            if match['match_id'] in recent_matches['match_id'].values:
                recent_points += match_points
        
        n_matches = len(team_matches)
        
        # Simple Elo approximation
        win_rate = points / (n_matches * 3) if n_matches > 0 else 0.33
        elo = 1500 + (win_rate - 0.5) * 400
        
        return {
            'elo': elo,
            'form_pts': recent_points,
            'gf_avg': goals_for / n_matches if n_matches > 0 else 1.5,
            'ga_avg': goals_against / n_matches if n_matches > 0 else 1.5
        }
    
    def _calculate_h2h(self, historical_df: pd.DataFrame, home_team: int, away_team: int) -> Dict:
        """Calculate head-to-head record"""
        
        h2h_matches = historical_df[
            ((historical_df['home_team_id'] == home_team) & (historical_df['away_team_id'] == away_team)) |
            ((historical_df['home_team_id'] == away_team) & (historical_df['away_team_id'] == home_team))
        ].tail(10)  # Last 10 H2H matches
        
        if len(h2h_matches) == 0:
            return {'h2h_home_wins': 1, 'h2h_draws': 1, 'h2h_away_wins': 1}
        
        home_wins = 0
        draws = 0
        away_wins = 0
        
        for _, match in h2h_matches.iterrows():
            if match['home_team_id'] == home_team:
                # This team was playing at home in this H2H match
                if match['outcome'] == 'H':
                    home_wins += 1
                elif match['outcome'] == 'D':
                    draws += 1
                else:
                    away_wins += 1
            else:
                # This team was playing away in this H2H match
                if match['outcome'] == 'A':
                    home_wins += 1
                elif match['outcome'] == 'D':
                    draws += 1
                else:
                    away_wins += 1
        
        return {
            'h2h_home_wins': home_wins,
            'h2h_draws': draws,
            'h2h_away_wins': away_wins
        }
    
    def prepare_features(self, df: pd.DataFrame) -> np.ndarray:
        """Prepare feature matrix for training (T-24h features only)"""
        
        # Core T-24h features (no outcome leakage)
        t24h_features = [
            'league_id',
            'elo_diff', 'form_pts_diff', 'gf_avg_diff', 'ga_avg_diff',
            'home_attack_vs_away_defense', 'away_attack_vs_home_defense',
            'league_home_goals', 'league_away_goals', 'league_total_goals',
            'league_competitiveness', 'home_advantage',
            'h2h_home_wins', 'h2h_draws', 'h2h_away_wins',
            'home_elo', 'away_elo', 'home_form_pts', 'away_form_pts'
        ]
        
        # Only use features that exist
        available_features = [col for col in t24h_features if col in df.columns]
        self.feature_names = available_features
        
        print(f"Using {len(available_features)} T-24h features")
        
        X = df[available_features].fillna(0).values
        X = np.nan_to_num(X, nan=0.0, posinf=1e6, neginf=-1e6)
        
        return X
    
    def calculate_baselines(self, df: pd.DataFrame) -> Dict[str, np.ndarray]:
        """Calculate proper baseline predictions"""
        
        n_samples = len(df)
        baselines = {}
        
        # Uniform baseline
        baselines['uniform'] = np.full((n_samples, 3), 1/3)
        
        # Frequency baseline (global)
        outcome_counts = df['outcome'].value_counts()
        total = len(df)
        freq_probs = np.zeros((n_samples, 3))
        freq_probs[:, 0] = outcome_counts.get('H', 0) / total
        freq_probs[:, 1] = outcome_counts.get('D', 0) / total
        freq_probs[:, 2] = outcome_counts.get('A', 0) / total
        baselines['frequency'] = freq_probs
        
        # League-specific frequency
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
        
        return baselines
    
    def train_models(self, train_df: pd.DataFrame, val_df: pd.DataFrame) -> Dict:
        """Train multiple model architectures"""
        
        print("Training multiple model architectures...")
        
        X_train = self.prepare_features(train_df)
        X_val = self.prepare_features(val_df)
        
        # Scale features
        X_train_scaled = self.scaler.fit_transform(X_train)
        X_val_scaled = self.scaler.transform(X_val)
        
        # Convert outcomes
        outcome_to_idx = {'H': 0, 'D': 1, 'A': 2}
        y_train = np.array([outcome_to_idx[outcome] for outcome in train_df['outcome']])
        y_val = np.array([outcome_to_idx[outcome] for outcome in val_df['outcome']])
        
        # 1. Random Forest
        print("Training Random Forest...")
        rf_model = RandomForestClassifier(
            n_estimators=200,
            max_depth=12,
            min_samples_split=10,
            min_samples_leaf=5,
            random_state=42,
            n_jobs=-1
        )
        rf_model.fit(X_train_scaled, y_train)
        self.models['random_forest'] = rf_model
        
        # 2. Two-stage classifier
        print("Training Two-Stage Classifier...")
        
        # Stage 1: Draw vs Not-Draw
        y_train_stage1 = (y_train == 1).astype(int)  # 1 for draw
        stage1_model = LogisticRegression(random_state=42, max_iter=1000)
        stage1_model.fit(X_train_scaled, y_train_stage1)
        
        # Stage 2: Home vs Away (for non-draws)
        non_draw_mask = y_train != 1
        X_train_stage2 = X_train_scaled[non_draw_mask]
        y_train_stage2 = (y_train[non_draw_mask] == 0).astype(int)  # 1 for home win
        
        stage2_model = LogisticRegression(random_state=42, max_iter=1000)
        stage2_model.fit(X_train_stage2, y_train_stage2)
        
        self.models['two_stage'] = {
            'stage1': stage1_model,
            'stage2': stage2_model
        }
        
        print("Model training complete")
        
        return {
            'n_train': len(train_df),
            'n_val': len(val_df),
            'n_features': len(self.feature_names)
        }
    
    def predict_two_stage(self, X: np.ndarray) -> np.ndarray:
        """Generate predictions from two-stage model"""
        
        stage1_model = self.models['two_stage']['stage1']
        stage2_model = self.models['two_stage']['stage2']
        
        # Stage 1: Probability of draw
        prob_draw = stage1_model.predict_proba(X)[:, 1]
        
        # Stage 2: Among non-draws, probability of home win
        prob_home_given_not_draw = stage2_model.predict_proba(X)[:, 1]
        
        # Combine stages
        prob_home = (1 - prob_draw) * prob_home_given_not_draw
        prob_away = (1 - prob_draw) * (1 - prob_home_given_not_draw)
        
        # Ensure probabilities sum to 1
        probs = np.column_stack([prob_home, prob_draw, prob_away])
        probs = probs / probs.sum(axis=1, keepdims=True)
        
        return probs
    
    def evaluate_comprehensive(self, test_df: pd.DataFrame) -> pd.DataFrame:
        """Comprehensive evaluation with all models and baselines"""
        
        print("Running comprehensive evaluation...")
        
        X_test = self.prepare_features(test_df)
        X_test_scaled = self.scaler.transform(X_test)
        
        outcome_to_idx = {'H': 0, 'D': 1, 'A': 2}
        y_test = np.array([outcome_to_idx[outcome] for outcome in test_df['outcome']])
        
        # Get baselines
        baselines = self.calculate_baselines(test_df)
        
        # Get model predictions
        model_predictions = {}
        
        # Random Forest
        if 'random_forest' in self.models:
            rf_probs = self.models['random_forest'].predict_proba(X_test_scaled)
            model_predictions['random_forest'] = rf_probs
        
        # Two-stage
        if 'two_stage' in self.models:
            ts_probs = self.predict_two_stage(X_test_scaled)
            model_predictions['two_stage'] = ts_probs
        
        # Evaluate all
        all_predictions = {**baselines, **model_predictions}
        
        results = []
        for name, probs in all_predictions.items():
            result = self._evaluate_predictions(y_test, probs, name)
            result['model_type'] = 'baseline' if name in baselines else 'model'
            results.append(result)
        
        results_df = pd.DataFrame(results)
        
        # Add improvement calculations
        uniform_ll = results_df[results_df['name'] == 'uniform']['logloss'].iloc[0]
        freq_ll = results_df[results_df['name'] == 'frequency']['logloss'].iloc[0]
        
        for i, row in results_df.iterrows():
            if row['model_type'] == 'model':
                model_ll = row['logloss']
                results_df.at[i, 'improvement_vs_uniform'] = uniform_ll - model_ll
                results_df.at[i, 'improvement_vs_frequency'] = freq_ll - model_ll
        
        return results_df
    
    def _evaluate_predictions(self, y_true: np.ndarray, y_pred_proba: np.ndarray, name: str) -> Dict:
        """Evaluate predictions with proper scoring rules"""
        
        # Ensure valid probabilities
        y_pred_proba = np.clip(y_pred_proba, 1e-15, 1 - 1e-15)
        y_pred_proba = y_pred_proba / y_pred_proba.sum(axis=1, keepdims=True)
        
        # LogLoss
        logloss = log_loss(y_true, y_pred_proba)
        
        # Accuracy
        y_pred = np.argmax(y_pred_proba, axis=1)
        accuracy = accuracy_score(y_true, y_pred)
        
        # Top-2 accuracy
        top2_indices = np.argsort(y_pred_proba, axis=1)[:, -2:]
        top2_accuracy = np.mean([y_true[i] in top2_indices[i] for i in range(len(y_true))])
        
        # Brier Score
        y_true_onehot = np.zeros((len(y_true), 3))
        y_true_onehot[np.arange(len(y_true)), y_true] = 1
        
        brier_scores = []
        for k in range(3):
            brier = brier_score_loss(y_true_onehot[:, k], y_pred_proba[:, k])
            brier_scores.append(brier)
        
        avg_brier = np.mean(brier_scores)
        
        # RPS
        rps_scores = []
        for i in range(len(y_true)):
            cum_pred = np.cumsum(y_pred_proba[i])
            cum_true = np.cumsum(y_true_onehot[i])
            rps = np.sum((cum_pred - cum_true) ** 2)
            rps_scores.append(rps)
        
        avg_rps = np.mean(rps_scores)
        
        return {
            'name': name,
            'n_samples': len(y_true),
            'logloss': logloss,
            'accuracy': accuracy,
            'top2_accuracy': top2_accuracy,
            'brier_score': avg_brier,
            'rps': avg_rps
        }
    
    def check_quality_gates(self, results_df: pd.DataFrame) -> Dict:
        """Check if models meet quality gates per league"""
        
        gates = {}
        
        for _, row in results_df.iterrows():
            if row['model_type'] != 'model':
                continue
            
            model_name = row['name']
            
            # Quality thresholds
            logloss_threshold = 0.01  # Must beat baseline by this much
            brier_threshold = 0.205
            top2_threshold = 0.95
            min_samples = 300
            
            gates_passed = {
                'sample_size': row['n_samples'] >= min_samples,
                'logloss_improvement': row.get('improvement_vs_frequency', 0) >= logloss_threshold,
                'brier_score': row['brier_score'] <= brier_threshold,
                'top2_accuracy': row['top2_accuracy'] >= top2_threshold
            }
            
            gates[model_name] = {
                'gates_passed': gates_passed,
                'all_passed': all(gates_passed.values()),
                'metrics': {
                    'logloss': row['logloss'],
                    'brier': row['brier_score'],
                    'top2': row['top2_accuracy'],
                    'n_samples': row['n_samples']
                }
            }
        
        return gates

def main():
    """Run improved static system with real data verification"""
    
    print("IMPROVED STATIC SYSTEM - Real Data Verification")
    print("=" * 60)
    
    system = ImprovedStaticSystem()
    
    # Load real match data
    dataset = system.load_real_match_data()
    
    if len(dataset) < 500:
        print("Insufficient real data for proper evaluation")
        return
    
    print(f"Dataset: {len(dataset)} matches, {dataset['match_date_utc'].min()} to {dataset['match_date_utc'].max()}")
    
    # Time-based splits
    dataset_sorted = dataset.sort_values('match_date_utc')
    
    # 60% train, 20% val, 20% test
    train_idx = int(len(dataset_sorted) * 0.6)
    val_idx = int(len(dataset_sorted) * 0.8)
    
    train_df = dataset_sorted.iloc[:train_idx].copy()
    val_df = dataset_sorted.iloc[train_idx:val_idx].copy()
    test_df = dataset_sorted.iloc[val_idx:].copy()
    
    print(f"Splits: {len(train_df)} train, {len(val_df)} val, {len(test_df)} test")
    
    # Train models
    training_info = system.train_models(train_df, val_df)
    
    # Evaluate on test set
    results_df = system.evaluate_comprehensive(test_df)
    
    # Check quality gates
    quality_gates = system.check_quality_gates(results_df)
    
    # Generate report
    print("\n" + "="*60)
    print("IMPROVED SYSTEM RESULTS")
    print("="*60)
    
    print("\nModel Performance:")
    for _, row in results_df.iterrows():
        improvement_vs_freq = row.get('improvement_vs_frequency', 0)
        status = "✅" if improvement_vs_freq > 0 else "❌"
        
        print(f"{row['name']:20} | LL: {row['logloss']:.4f} | Acc: {row['accuracy']:.1%} | "
              f"Top2: {row['top2_accuracy']:.1%} | Brier: {row['brier_score']:.4f} | "
              f"vs Freq: {improvement_vs_freq:+.4f} {status}")
    
    print("\nQuality Gates:")
    for model_name, gate_info in quality_gates.items():
        status = "✅ PASS" if gate_info['all_passed'] else "❌ FAIL"
        print(f"{model_name}: {status}")
        
        for gate_name, passed in gate_info['gates_passed'].items():
            gate_status = "✅" if passed else "❌"
            print(f"  {gate_name}: {gate_status}")
    
    # Save results
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    os.makedirs('reports', exist_ok=True)
    
    results_df.to_csv(f'reports/improved_system_results_{timestamp}.csv', index=False)
    
    with open(f'reports/quality_gates_{timestamp}.json', 'w') as f:
        json.dump(quality_gates, f, indent=2, default=str)
    
    print(f"\nResults saved: reports/improved_system_results_{timestamp}.csv")
    
    return system, results_df, quality_gates

if __name__ == "__main__":
    main()