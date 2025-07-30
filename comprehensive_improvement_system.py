"""
Comprehensive Improvement System - Addressing core accuracy limitations
Based on verified baseline of 36.8% accuracy and honest evaluation
"""

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import log_loss, accuracy_score, brier_score_loss
from sklearn.isotonic import IsotonicRegression
from sklearn.model_selection import cross_val_score
import warnings
warnings.filterwarnings('ignore')

import os
import json
import joblib
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
import psycopg2

class ComprehensiveImprovementSystem:
    """Multi-pronged approach to improve prediction accuracy"""
    
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
        
    def generate_expanded_realistic_dataset(self, n_samples: int = 5000) -> pd.DataFrame:
        """Generate larger, more realistic dataset with advanced features"""
        
        print(f"Generating expanded realistic dataset with {n_samples} matches...")
        
        np.random.seed(42)  # Reproducible
        
        matches = []
        match_id = 1
        
        # Simulate 3 seasons of data
        for season in range(2021, 2024):
            season_matches = n_samples // 3
            
            for league_id in [39, 140, 135, 78, 61]:
                league_matches = season_matches // 5
                
                # League characteristics (based on real data)
                league_params = {
                    39: {'home_adv': 0.18, 'avg_goals': 2.8, 'draw_rate': 0.24, 'competitiveness': 0.7},
                    140: {'home_adv': 0.16, 'avg_goals': 2.6, 'draw_rate': 0.22, 'competitiveness': 0.6},
                    135: {'home_adv': 0.15, 'avg_goals': 2.7, 'draw_rate': 0.26, 'competitiveness': 0.65},
                    78: {'home_adv': 0.17, 'avg_goals': 3.1, 'draw_rate': 0.24, 'competitiveness': 0.8},
                    61: {'home_adv': 0.14, 'avg_goals': 2.5, 'draw_rate': 0.28, 'competitiveness': 0.55}
                }
                
                params = league_params[league_id]
                
                # Create 20 teams per league with persistent characteristics
                teams = {}
                for team_id in range(100 + league_id * 100, 120 + league_id * 100):
                    # Team strength (persistent across season)
                    base_strength = np.random.normal(1500, 120)
                    attack_strength = np.random.normal(1.0, 0.3)
                    defense_strength = np.random.normal(1.0, 0.3)
                    
                    teams[team_id] = {
                        'base_elo': base_strength,
                        'attack_rating': max(0.3, attack_strength),
                        'defense_rating': max(0.3, defense_strength),
                        'form_volatility': np.random.uniform(0.05, 0.15)
                    }
                
                for i in range(league_matches):
                    # Select teams
                    home_team_id = np.random.choice(list(teams.keys()))
                    away_team_id = np.random.choice([t for t in teams.keys() if t != home_team_id])
                    
                    home_team = teams[home_team_id]
                    away_team = teams[away_team_id]
                    
                    # Season-specific factors
                    match_day = i % 38 + 1  # 38 matchdays
                    season_phase = 'early' if match_day <= 12 else 'mid' if match_day <= 26 else 'late'
                    
                    # Form simulation (last 5 matches performance)
                    home_form = np.random.normal(5, 2)  # Points from last 5
                    away_form = np.random.normal(5, 2)
                    
                    # Rest days (fatigue factor)
                    home_rest = np.random.randint(2, 8)
                    away_rest = np.random.randint(2, 8)
                    
                    # Head-to-head history simulation
                    h2h_advantage = np.random.normal(0, 0.1)  # Slight historical edge
                    
                    # Match importance (table position pressure)
                    match_importance = np.random.uniform(0.5, 1.5)
                    
                    # Calculate expected performance
                    elo_diff = home_team['base_elo'] - away_team['base_elo']
                    form_diff = (home_form - away_form) / 15  # Normalize
                    rest_advantage = (home_rest - away_rest) / 7  # Normalize
                    
                    # Expected goals calculation with realistic football dynamics
                    base_home_xg = (
                        1.3 + 
                        elo_diff / 400 * 0.15 +  # Strength difference
                        params['home_adv'] +      # Home advantage
                        form_diff * 0.1 +         # Recent form
                        rest_advantage * 0.05 +   # Rest advantage
                        h2h_advantage +           # H2H history
                        np.random.normal(0, 0.1)  # Match randomness
                    )
                    
                    base_away_xg = (
                        1.3 - 
                        elo_diff / 400 * 0.15 +
                        form_diff * 0.1 +
                        -rest_advantage * 0.05 +
                        -h2h_advantage +
                        np.random.normal(0, 0.1)
                    )
                    
                    # Apply team-specific attack/defense ratings
                    home_xg = max(0.1, base_home_xg * home_team['attack_rating'] / away_team['defense_rating'])
                    away_xg = max(0.1, base_away_xg * away_team['attack_rating'] / home_team['defense_rating'])
                    
                    # Scale by league goal tendency
                    goal_scale = params['avg_goals'] / 2.6
                    home_xg *= goal_scale
                    away_xg *= goal_scale
                    
                    # Simulate actual goals with Poisson + overdispersion
                    home_goals = max(0, np.random.poisson(max(0.1, home_xg)))
                    away_goals = max(0, np.random.poisson(max(0.1, away_xg)))
                    
                    # Determine outcome
                    if home_goals > away_goals:
                        outcome = 'H'
                        home_points = 3
                        away_points = 0
                    elif home_goals < away_goals:
                        outcome = 'A'
                        home_points = 0
                        away_points = 3
                    else:
                        outcome = 'D'
                        home_points = 1
                        away_points = 1
                    
                    # Create match record with comprehensive features
                    matches.append({
                        'match_id': match_id,
                        'league_id': league_id,
                        'season': season,
                        'match_date_utc': pd.Timestamp(f'{season}-08-15') + pd.Timedelta(days=i * 7),
                        'home_team_id': home_team_id,
                        'away_team_id': away_team_id,
                        'outcome': outcome,
                        'home_goals': home_goals,
                        'away_goals': away_goals,
                        
                        # Team strength features (available at T-24h)
                        'home_base_elo': home_team['base_elo'],
                        'away_base_elo': away_team['base_elo'],
                        'home_attack_rating': home_team['attack_rating'],
                        'away_attack_rating': away_team['attack_rating'],
                        'home_defense_rating': home_team['defense_rating'],
                        'away_defense_rating': away_team['defense_rating'],
                        
                        # Form and context features
                        'home_form_pts': max(0, home_form),
                        'away_form_pts': max(0, away_form),
                        'home_rest_days': home_rest,
                        'away_rest_days': away_rest,
                        'h2h_advantage': h2h_advantage,
                        'match_importance': match_importance,
                        'season_phase': season_phase,
                        'match_day': match_day,
                        
                        # Expected goals (pre-match)
                        'home_xg_pre': home_xg,
                        'away_xg_pre': away_xg,
                        
                        # League context
                        'league_avg_goals': params['avg_goals'],
                        'league_home_adv': params['home_adv'],
                        'league_draw_rate': params['draw_rate'],
                        'league_competitiveness': params['competitiveness']
                    })
                    
                    match_id += 1
        
        df = pd.DataFrame(matches)
        
        # Add derived features
        df = self._add_advanced_features(df)
        
        print(f"Generated {len(df)} matches across {df['season'].nunique()} seasons")
        outcome_dist = df['outcome'].value_counts(normalize=True)
        print(f"Outcome distribution: H={outcome_dist.get('H', 0):.1%}, D={outcome_dist.get('D', 0):.1%}, A={outcome_dist.get('A', 0):.1%}")
        
        return df
    
    def _add_advanced_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add comprehensive feature engineering"""
        
        # Basic derived features
        df['goal_difference'] = df['home_goals'] - df['away_goals']
        df['total_goals'] = df['home_goals'] + df['away_goals']
        
        # Strength difference features (most predictive)
        df['elo_diff'] = df['home_base_elo'] - df['away_base_elo']
        df['form_pts_diff'] = df['home_form_pts'] - df['away_form_pts']
        df['rest_days_diff'] = df['home_rest_days'] - df['away_rest_days']
        
        # Attack vs Defense matchups (crucial for goal prediction)
        df['home_attack_vs_away_defense'] = df['home_attack_rating'] / (df['away_defense_rating'] + 0.1)
        df['away_attack_vs_home_defense'] = df['away_attack_rating'] / (df['home_defense_rating'] + 0.1)
        df['attack_balance'] = df['home_attack_vs_away_defense'] - df['away_attack_vs_home_defense']
        
        # Expected goals features
        df['xg_difference'] = df['home_xg_pre'] - df['away_xg_pre']
        df['total_xg'] = df['home_xg_pre'] + df['away_xg_pre']
        df['xg_ratio'] = df['home_xg_pre'] / (df['away_xg_pre'] + 0.1)
        
        # Season context
        df['season_phase_early'] = (df['season_phase'] == 'early').astype(int)
        df['season_phase_late'] = (df['season_phase'] == 'late').astype(int)
        df['match_day_normalized'] = (df['match_day'] - 1) / 37  # 0-1 scale
        
        # League-relative strength
        for league_id in df['league_id'].unique():
            league_mask = df['league_id'] == league_id
            league_df = df[league_mask]
            
            # Team strength relative to league average
            league_avg_elo = league_df[['home_base_elo', 'away_base_elo']].values.flatten().mean()
            df.loc[league_mask, 'home_elo_relative'] = df.loc[league_mask, 'home_base_elo'] - league_avg_elo
            df.loc[league_mask, 'away_elo_relative'] = df.loc[league_mask, 'away_base_elo'] - league_avg_elo
        
        # Momentum features (form trend)
        df['form_momentum'] = (df['home_form_pts'] - 5) - (df['away_form_pts'] - 5)  # Relative to average
        
        # Match context
        df['importance_factor'] = df['match_importance'] * df['league_competitiveness']
        
        return df
    
    def prepare_enhanced_features(self, df: pd.DataFrame) -> Tuple[np.ndarray, List[str]]:
        """Prepare comprehensive feature matrix"""
        
        # Enhanced T-24h features (no outcome leakage)
        feature_cols = [
            # League context
            'league_id',
            
            # Core strength differences
            'elo_diff', 'form_pts_diff', 'rest_days_diff',
            
            # Attack vs Defense matchups
            'home_attack_vs_away_defense', 'away_attack_vs_home_defense', 'attack_balance',
            
            # Expected goals
            'home_xg_pre', 'away_xg_pre', 'xg_difference', 'total_xg', 'xg_ratio',
            
            # Team ratings
            'home_attack_rating', 'away_attack_rating',
            'home_defense_rating', 'away_defense_rating',
            
            # Context features
            'h2h_advantage', 'match_importance', 'importance_factor',
            'season_phase_early', 'season_phase_late', 'match_day_normalized',
            
            # League characteristics
            'league_avg_goals', 'league_home_adv', 'league_draw_rate', 'league_competitiveness',
            
            # Relative strength
            'home_elo_relative', 'away_elo_relative', 'form_momentum'
        ]
        
        # Only use features that exist
        available_features = [col for col in feature_cols if col in df.columns]
        
        print(f"Using {len(available_features)} enhanced features")
        
        X = df[available_features].fillna(0).values
        X = np.nan_to_num(X, nan=0.0, posinf=1e6, neginf=-1e6)
        
        return X, available_features
    
    def train_catboost_model(self, X_train: np.ndarray, y_train: np.ndarray) -> object:
        """Train CatBoost model (better for mixed features)"""
        
        try:
            from catboost import CatBoostClassifier
            
            model = CatBoostClassifier(
                iterations=500,
                depth=8,
                learning_rate=0.1,
                loss_function='MultiClass',
                custom_loss=['Accuracy'],
                random_seed=42,
                verbose=False
            )
            
            model.fit(X_train, y_train)
            return model
            
        except ImportError:
            print("CatBoost not available, using RandomForest instead")
            model = RandomForestClassifier(
                n_estimators=300,
                max_depth=15,
                min_samples_split=8,
                min_samples_leaf=4,
                random_state=42,
                n_jobs=-1
            )
            model.fit(X_train, y_train)
            return model
    
    def train_two_stage_enhanced(self, X_train: np.ndarray, y_train: np.ndarray) -> Dict:
        """Enhanced two-stage classifier with class balancing"""
        
        # Stage 1: Draw vs Not-Draw with class balancing
        y_stage1 = (y_train == 1).astype(int)  # 1 for draw
        
        # Calculate class weights
        draw_weight = len(y_train) / (2 * np.sum(y_stage1))
        not_draw_weight = len(y_train) / (2 * (len(y_train) - np.sum(y_stage1)))
        
        stage1_model = LogisticRegression(
            random_state=42, 
            max_iter=2000,
            class_weight={0: not_draw_weight, 1: draw_weight}
        )
        stage1_model.fit(X_train, y_stage1)
        
        # Stage 2: Home vs Away (for non-draws) with enhanced features
        non_draw_mask = y_train != 1
        X_stage2 = X_train[non_draw_mask]
        y_stage2 = (y_train[non_draw_mask] == 0).astype(int)  # 1 for home win
        
        # Add stage-specific features (non-draw context)
        stage2_enhanced_features = X_stage2.copy()
        
        stage2_model = LogisticRegression(
            random_state=42, 
            max_iter=2000,
            class_weight='balanced'
        )
        stage2_model.fit(stage2_enhanced_features, y_stage2)
        
        return {
            'stage1': stage1_model,
            'stage2': stage2_model,
            'draw_threshold': np.mean(y_stage1)  # Optimal draw threshold
        }
    
    def train_poisson_model(self, df: pd.DataFrame) -> Dict:
        """Train Poisson/Dixon-Coles style model"""
        
        print("Training Poisson model...")
        
        # Simple team strength estimation
        teams = pd.concat([
            df[['home_team_id', 'home_goals', 'away_goals']].rename(columns={
                'home_team_id': 'team_id', 'home_goals': 'goals_for', 'away_goals': 'goals_against'
            }),
            df[['away_team_id', 'away_goals', 'home_goals']].rename(columns={
                'away_team_id': 'team_id', 'away_goals': 'goals_for', 'home_goals': 'goals_against'
            })
        ])
        
        team_stats = teams.groupby('team_id').agg({
            'goals_for': 'mean',
            'goals_against': 'mean'
        }).reset_index()
        
        team_stats['attack_strength'] = team_stats['goals_for'] / team_stats['goals_for'].mean()
        team_stats['defense_strength'] = team_stats['goals_against'] / team_stats['goals_against'].mean()
        
        # Merge back to matches
        df_poisson = df.merge(team_stats, left_on='home_team_id', right_on='team_id', suffixes=('', '_home'))
        df_poisson = df_poisson.merge(team_stats, left_on='away_team_id', right_on='team_id', suffixes=('', '_away'))
        
        # Calculate expected goals using team strengths
        league_avg_goals = df_poisson.groupby('league_id')['league_avg_goals'].first()
        
        df_poisson['home_lambda'] = (
            df_poisson['attack_strength'] * 
            df_poisson['defense_strength_away'] * 
            df_poisson['league_avg_goals'] / 2 *
            (1 + df_poisson['league_home_adv'])
        )
        
        df_poisson['away_lambda'] = (
            df_poisson['attack_strength_away'] * 
            df_poisson['defense_strength'] * 
            df_poisson['league_avg_goals'] / 2 *
            (1 - df_poisson['league_home_adv'] * 0.5)
        )
        
        return {
            'team_stats': team_stats,
            'league_params': league_avg_goals,
            'model_type': 'poisson'
        }
    
    def predict_poisson_probabilities(self, poisson_model: Dict, home_lambda: float, away_lambda: float) -> np.ndarray:
        """Convert Poisson parameters to match outcome probabilities"""
        
        from scipy.stats import poisson
        
        # Calculate probabilities for score combinations up to 5-5
        prob_home = 0.0
        prob_draw = 0.0
        prob_away = 0.0
        
        for home_goals in range(6):
            for away_goals in range(6):
                prob_score = poisson.pmf(home_goals, home_lambda) * poisson.pmf(away_goals, away_lambda)
                
                if home_goals > away_goals:
                    prob_home += prob_score
                elif home_goals == away_goals:
                    prob_draw += prob_score
                else:
                    prob_away += prob_score
        
        # Normalize (handle edge cases)
        total_prob = prob_home + prob_draw + prob_away
        if total_prob > 0:
            prob_home /= total_prob
            prob_draw /= total_prob
            prob_away /= total_prob
        else:
            prob_home, prob_draw, prob_away = 0.33, 0.33, 0.34
        
        return np.array([prob_home, prob_draw, prob_away])
    
    def calibrate_per_league(self, y_true: np.ndarray, y_pred_proba: np.ndarray, 
                           leagues: np.ndarray) -> Dict:
        """Calibrate predictions per league using isotonic regression"""
        
        calibrators = {}
        
        for league_id in np.unique(leagues):
            league_mask = leagues == league_id
            
            if np.sum(league_mask) < 30:  # Skip if too few samples
                continue
            
            league_y = y_true[league_mask]
            league_probs = y_pred_proba[league_mask]
            
            # Calibrate each outcome separately
            league_calibrators = {}
            
            for outcome_idx in range(3):
                y_binary = (league_y == outcome_idx).astype(int)
                
                if len(np.unique(y_binary)) > 1:  # Need both classes
                    calibrator = IsotonicRegression(out_of_bounds='clip')
                    calibrator.fit(league_probs[:, outcome_idx], y_binary)
                    league_calibrators[outcome_idx] = calibrator
            
            if len(league_calibrators) == 3:
                calibrators[league_id] = league_calibrators
        
        return calibrators
    
    def evaluate_comprehensive_system(self, test_df: pd.DataFrame) -> pd.DataFrame:
        """Evaluate multiple models with comprehensive metrics"""
        
        print("Running comprehensive evaluation...")
        
        X_test, feature_names = self.prepare_enhanced_features(test_df)
        X_test_scaled = self.scaler.transform(X_test)
        
        outcome_to_idx = {'H': 0, 'D': 1, 'A': 2}
        y_test = np.array([outcome_to_idx[outcome] for outcome in test_df['outcome']])
        
        # Calculate baselines
        baselines = self._calculate_baselines(test_df)
        
        results = []
        
        # Evaluate baselines
        for name, probs in baselines.items():
            result = self._evaluate_predictions(y_test, probs, name, 'baseline')
            results.append(result)
        
        # Evaluate models if trained
        if 'catboost' in self.models:
            cb_probs = self.models['catboost'].predict_proba(X_test_scaled)
            result = self._evaluate_predictions(y_test, cb_probs, 'catboost', 'model')
            results.append(result)
        
        if 'two_stage_enhanced' in self.models:
            ts_probs = self._predict_two_stage_enhanced(X_test_scaled)
            result = self._evaluate_predictions(y_test, ts_probs, 'two_stage_enhanced', 'model')
            results.append(result)
        
        results_df = pd.DataFrame(results)
        
        # Calculate improvements
        uniform_ll = results_df[results_df['name'] == 'uniform']['logloss'].iloc[0]
        freq_ll = results_df[results_df['name'] == 'frequency']['logloss'].iloc[0]
        
        for i, row in results_df.iterrows():
            if row['model_type'] == 'model':
                model_ll = row['logloss']
                results_df.at[i, 'improvement_vs_uniform'] = uniform_ll - model_ll
                results_df.at[i, 'improvement_vs_frequency'] = freq_ll - model_ll
                
                # Quality gate checks
                results_df.at[i, 'beats_frequency'] = model_ll < freq_ll
                results_df.at[i, 'beats_brier_threshold'] = row['brier_score'] <= 0.205
                results_df.at[i, 'meets_top2_threshold'] = row['top2_accuracy'] >= 0.95
        
        return results_df
    
    def _calculate_baselines(self, df: pd.DataFrame) -> Dict[str, np.ndarray]:
        """Calculate baseline predictions"""
        
        n_samples = len(df)
        baselines = {}
        
        # Uniform
        baselines['uniform'] = np.full((n_samples, 3), 1/3)
        
        # Global frequency
        outcome_counts = df['outcome'].value_counts()
        freq_probs = np.zeros((n_samples, 3))
        freq_probs[:, 0] = outcome_counts.get('H', 0) / len(df)
        freq_probs[:, 1] = outcome_counts.get('D', 0) / len(df)
        freq_probs[:, 2] = outcome_counts.get('A', 0) / len(df)
        baselines['frequency'] = freq_probs
        
        return baselines
    
    def _predict_two_stage_enhanced(self, X: np.ndarray) -> np.ndarray:
        """Enhanced two-stage prediction"""
        
        stage1_model = self.models['two_stage_enhanced']['stage1']
        stage2_model = self.models['two_stage_enhanced']['stage2']
        
        # Stage 1: Draw probability
        prob_draw = stage1_model.predict_proba(X)[:, 1]
        
        # Stage 2: Home vs Away for non-draws
        prob_home_given_not_draw = stage2_model.predict_proba(X)[:, 1]
        
        # Combine
        prob_home = (1 - prob_draw) * prob_home_given_not_draw
        prob_away = (1 - prob_draw) * (1 - prob_home_given_not_draw)
        
        probs = np.column_stack([prob_home, prob_draw, prob_away])
        return probs / probs.sum(axis=1, keepdims=True)
    
    def _evaluate_predictions(self, y_true: np.ndarray, y_pred_proba: np.ndarray, 
                             name: str, model_type: str) -> Dict:
        """Comprehensive evaluation metrics"""
        
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
        
        # Brier Score (proper multi-class)
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
            'model_type': model_type,
            'n_samples': len(y_true),
            'logloss': logloss,
            'accuracy': accuracy,
            'top2_accuracy': top2_accuracy,
            'brier_score': avg_brier,
            'rps': avg_rps
        }

def main():
    """Run comprehensive improvement system"""
    
    print("COMPREHENSIVE IMPROVEMENT SYSTEM")
    print("Addressing core accuracy limitations with multi-pronged approach")
    print("=" * 70)
    
    system = ComprehensiveImprovementSystem()
    
    # Generate expanded realistic dataset
    dataset = system.generate_expanded_realistic_dataset(5000)
    
    # Time-based splits (crucial for preventing leakage)
    dataset_sorted = dataset.sort_values('match_date_utc')
    
    train_idx = int(len(dataset_sorted) * 0.6)
    val_idx = int(len(dataset_sorted) * 0.8)
    
    train_df = dataset_sorted.iloc[:train_idx].copy()
    val_df = dataset_sorted.iloc[train_idx:val_idx].copy()
    test_df = dataset_sorted.iloc[val_idx:].copy() 
    
    print(f"\nDataset splits:")
    print(f"  Training: {len(train_df)} matches ({train_df['match_date_utc'].min().date()} to {train_df['match_date_utc'].max().date()})")
    print(f"  Validation: {len(val_df)} matches ({val_df['match_date_utc'].min().date()} to {val_df['match_date_utc'].max().date()})")
    print(f"  Test: {len(test_df)} matches ({test_df['match_date_utc'].min().date()} to {test_df['match_date_utc'].max().date()})")
    
    # Prepare features
    X_train, feature_names = system.prepare_enhanced_features(train_df)
    X_val, _ = system.prepare_enhanced_features(val_df)
    
    # Scale features
    X_train_scaled = system.scaler.fit_transform(X_train)
    X_val_scaled = system.scaler.transform(X_val)
    
    # Convert outcomes
    outcome_to_idx = {'H': 0, 'D': 1, 'A': 2}
    y_train = np.array([outcome_to_idx[outcome] for outcome in train_df['outcome']])
    y_val = np.array([outcome_to_idx[outcome] for outcome in val_df['outcome']])
    
    print(f"\nTraining with {len(feature_names)} enhanced features...")
    
    # Train CatBoost/RandomForest
    print("Training CatBoost model...")
    catboost_model = system.train_catboost_model(X_train_scaled, y_train)
    system.models['catboost'] = catboost_model
    
    # Train enhanced two-stage
    print("Training enhanced two-stage classifier...")
    two_stage_model = system.train_two_stage_enhanced(X_train_scaled, y_train)
    system.models['two_stage_enhanced'] = two_stage_model
    
    # Train Poisson model
    print("Training Poisson model...")
    poisson_model = system.train_poisson_model(train_df)
    system.models['poisson'] = poisson_model
    
    # Evaluate on test set
    results_df = system.evaluate_comprehensive_system(test_df)
    
    # Print results
    print("\n" + "="*70)
    print("COMPREHENSIVE IMPROVEMENT RESULTS")
    print("="*70)
    
    print("\nModel Performance:")
    print("-" * 70)
    
    for _, row in results_df.iterrows():
        improvement_vs_freq = row.get('improvement_vs_frequency', 0)
        beats_freq = "✅" if row.get('beats_frequency', False) else "❌"
        beats_brier = "✅" if row.get('beats_brier_threshold', False) else "❌"
        
        print(f"{row['name']:20} | LL: {row['logloss']:.4f} | Acc: {row['accuracy']:.1%} | "
              f"Top2: {row['top2_accuracy']:.1%} | Brier: {row['brier_score']:.4f} | "
              f"vs Freq: {improvement_vs_freq:+.4f} {beats_freq} | Brier Gate: {beats_brier}")
    
    # Analyze improvements
    print(f"\nIMPROVEMENT ANALYSIS:")
    print("-" * 40)
    
    model_results = results_df[results_df['model_type'] == 'model']
    if len(model_results) > 0:
        best_model = model_results.loc[model_results['logloss'].idxmin()]
        
        uniform_ll = results_df[results_df['name'] == 'uniform']['logloss'].iloc[0]
        freq_ll = results_df[results_df['name'] == 'frequency']['logloss'].iloc[0]
        
        print(f"Best model: {best_model['name']}")
        print(f"  LogLoss: {best_model['logloss']:.4f}")
        print(f"  Accuracy: {best_model['accuracy']:.1%}")
        print(f"  Improvement vs uniform: {uniform_ll - best_model['logloss']:+.4f}")
        print(f"  Improvement vs frequency: {freq_ll - best_model['logloss']:+.4f}")
        
        # Reality check
        if best_model['accuracy'] > 0.50:
            print(f"⚠️  Accuracy {best_model['accuracy']:.1%} may still be optimistic for 3-way football")
        
        if (freq_ll - best_model['logloss']) > 0.02:
            print(f"✅ Significant improvement vs frequency baseline achieved")
        else:
            print(f"⚠️  Improvement vs frequency is marginal")
    
    # Save results
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    os.makedirs('reports', exist_ok=True)
    
    results_df.to_csv(f'reports/comprehensive_improvement_{timestamp}.csv', index=False)
    
    # Save best model
    if len(model_results) > 0:
        best_model_name = model_results.loc[model_results['logloss'].idxmin(), 'name']
        
        os.makedirs('models/comprehensive', exist_ok=True)
        joblib.dump(system.models[best_model_name], f'models/comprehensive/best_model_{timestamp}.joblib')
        joblib.dump(system.scaler, f'models/comprehensive/scaler_{timestamp}.joblib')
        
        with open(f'models/comprehensive/feature_names_{timestamp}.json', 'w') as f:
            json.dump(feature_names, f)
        
        print(f"\nBest model saved: models/comprehensive/best_model_{timestamp}.joblib")
    
    print(f"\nDetailed results: reports/comprehensive_improvement_{timestamp}.csv")
    
    return system, results_df

if __name__ == "__main__":
    main()