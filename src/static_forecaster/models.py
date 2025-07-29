"""
Static Forecasting Models - Multiple architectures for accuracy optimization
"""

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import cross_val_score, StratifiedKFold
from sklearn.calibration import CalibratedClassifierCV
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import log_loss, brier_score_loss
import lightgbm as lgb
import warnings
warnings.filterwarnings('ignore')

from typing import Dict, List, Tuple, Optional
import joblib
import json
from datetime import datetime

class TwoStageClassifier:
    """Two-stage classifier: Draw vs Not-Draw, then Home vs Away"""
    
    def __init__(self, stage1_params=None, stage2_params=None):
        """
        Initialize two-stage classifier
        
        Args:
            stage1_params: Parameters for Draw vs Not-Draw classifier
            stage2_params: Parameters for Home vs Away classifier
        """
        
        # Default parameters optimized for accuracy
        default_stage1 = {
            'objective': 'binary',
            'metric': 'binary_logloss',
            'boosting_type': 'gbdt',
            'num_leaves': 31,
            'learning_rate': 0.05,
            'feature_fraction': 0.8,
            'bagging_fraction': 0.8,
            'bagging_freq': 5,
            'verbose': -1,
            'random_state': 42
        }
        
        default_stage2 = {
            'objective': 'binary',
            'metric': 'binary_logloss',
            'boosting_type': 'gbdt',
            'num_leaves': 31,
            'learning_rate': 0.05,
            'feature_fraction': 0.8,
            'bagging_fraction': 0.8,
            'bagging_freq': 5,
            'verbose': -1,
            'random_state': 42
        }
        
        self.stage1_params = stage1_params or default_stage1
        self.stage2_params = stage2_params or default_stage2
        
        self.stage1_model = None  # Draw vs Not-Draw
        self.stage2_model = None  # Home vs Away (given Not-Draw)
        self.feature_names = None
        self.scaler = StandardScaler()
        
    def prepare_features(self, df: pd.DataFrame) -> np.ndarray:
        """Prepare feature matrix excluding target variables"""
        
        # Exclude target and metadata columns
        exclude_cols = [
            'match_id', 'outcome', 'home_goals', 'away_goals', 'goal_difference',
            'total_goals', 'match_date_utc', 'feature_cutoff_time', 'home_team_id',
            'away_team_id', 'season'
        ]
        
        feature_cols = [col for col in df.columns if col not in exclude_cols]
        self.feature_names = feature_cols
        
        X = df[feature_cols].values
        
        # Handle any missing values
        X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
        
        return X
    
    def fit(self, df: pd.DataFrame) -> Dict:
        """
        Fit two-stage classifier
        
        Returns:
            Dictionary with training metrics
        """
        
        print("Training Two-Stage Classifier...")
        
        X = self.prepare_features(df)
        y = df['outcome'].values
        
        # Scale features
        X_scaled = self.scaler.fit_transform(X)
        
        # Stage 1: Draw vs Not-Draw
        y_stage1 = (y == 'D').astype(int)
        
        self.stage1_model = lgb.LGBMClassifier(**self.stage1_params)
        self.stage1_model.fit(X_scaled, y_stage1)
        
        stage1_cv_score = cross_val_score(
            self.stage1_model, X_scaled, y_stage1, 
            cv=5, scoring='neg_log_loss'
        ).mean()
        
        # Stage 2: Home vs Away (for non-draw matches)
        non_draw_mask = y != 'D'
        X_stage2 = X_scaled[non_draw_mask]
        y_stage2 = (y[non_draw_mask] == 'H').astype(int)
        
        if len(y_stage2) > 0:
            self.stage2_model = lgb.LGBMClassifier(**self.stage2_params)
            self.stage2_model.fit(X_stage2, y_stage2)
            
            stage2_cv_score = cross_val_score(
                self.stage2_model, X_stage2, y_stage2,
                cv=5, scoring='neg_log_loss'
            ).mean()
        else:
            stage2_cv_score = -1.0
        
        print(f"Stage 1 CV LogLoss: {-stage1_cv_score:.4f}")
        print(f"Stage 2 CV LogLoss: {-stage2_cv_score:.4f}")
        
        return {
            'stage1_cv_logloss': -stage1_cv_score,
            'stage2_cv_logloss': -stage2_cv_score,
            'n_features': len(self.feature_names),
            'n_samples': len(df)
        }
    
    def predict_proba(self, df: pd.DataFrame) -> np.ndarray:
        """
        Predict 3-way probabilities
        
        Returns:
            Array of shape (n_samples, 3) with [P(H), P(D), P(A)]
        """
        
        X = self.prepare_features(df)
        X_scaled = self.scaler.transform(X)
        
        # Stage 1: Probability of Draw
        prob_draw = self.stage1_model.predict_proba(X_scaled)[:, 1]
        
        # Stage 2: Among non-draws, probability of Home win
        prob_home_given_not_draw = self.stage2_model.predict_proba(X_scaled)[:, 1]
        
        # Combine stages
        prob_home = (1 - prob_draw) * prob_home_given_not_draw
        prob_away = (1 - prob_draw) * (1 - prob_home_given_not_draw)
        
        # Ensure probabilities sum to 1
        probs = np.column_stack([prob_home, prob_draw, prob_away])
        probs = probs / probs.sum(axis=1, keepdims=True)
        
        return probs

class PoissonDixonColes:
    """Poisson/Dixon-Coles model for goal-based prediction"""
    
    def __init__(self, tau=0.1, xi=0.03):
        """
        Initialize Poisson model
        
        Args:
            tau: Time decay parameter
            xi: Low-scoring bias adjustment
        """
        self.tau = tau
        self.xi = xi
        self.home_attack = {}
        self.away_attack = {}
        self.home_defense = {}
        self.away_defense = {}
        self.home_advantage = 0.0
        self.avg_goals = 2.7
        
    def fit(self, df: pd.DataFrame) -> Dict:
        """Fit Poisson model using simplified approach"""
        
        print("Training Poisson/Dixon-Coles Model...")
        
        # Simplified team strength estimation
        teams = set(df['home_team_id'].tolist() + df['away_team_id'].tolist())
        
        # Initialize team parameters
        for team in teams:
            self.home_attack[team] = 1.0
            self.away_attack[team] = 1.0
            self.home_defense[team] = 1.0
            self.away_defense[team] = 1.0
        
        # Calculate team averages
        for team in teams:
            home_matches = df[df['home_team_id'] == team]
            away_matches = df[df['away_team_id'] == team]
            
            if len(home_matches) > 0:
                self.home_attack[team] = home_matches['home_goals'].mean()
                self.home_defense[team] = home_matches['away_goals'].mean()
            
            if len(away_matches) > 0:
                self.away_attack[team] = away_matches['away_goals'].mean()
                self.away_defense[team] = away_matches['home_goals'].mean()
        
        # Calculate home advantage
        total_home_goals = df['home_goals'].sum()
        total_away_goals = df['away_goals'].sum()
        total_matches = len(df)
        
        if total_matches > 0:
            home_avg = total_home_goals / total_matches
            away_avg = total_away_goals / total_matches
            self.home_advantage = home_avg / away_avg if away_avg > 0 else 1.15
            self.avg_goals = (total_home_goals + total_away_goals) / (2 * total_matches)
        
        print(f"Home advantage factor: {self.home_advantage:.3f}")
        print(f"Average goals per team per match: {self.avg_goals:.2f}")
        
        return {
            'home_advantage': self.home_advantage,
            'avg_goals': self.avg_goals,
            'n_teams': len(teams),
            'n_matches': len(df)
        }
    
    def predict_proba(self, df: pd.DataFrame) -> np.ndarray:
        """Predict 3-way probabilities using Poisson model"""
        
        probs = []
        
        for _, match in df.iterrows():
            home_team = match['home_team_id']
            away_team = match['away_team_id']
            
            # Expected goals
            home_attack_strength = self.home_attack.get(home_team, 1.0)
            away_defense_strength = self.away_defense.get(away_team, 1.0)
            
            away_attack_strength = self.away_attack.get(away_team, 1.0)
            home_defense_strength = self.home_defense.get(home_team, 1.0)
            
            lambda_home = home_attack_strength * away_defense_strength * self.home_advantage
            lambda_away = away_attack_strength * home_defense_strength
            
            # Ensure reasonable bounds
            lambda_home = np.clip(lambda_home, 0.1, 5.0)
            lambda_away = np.clip(lambda_away, 0.1, 5.0)
            
            # Calculate probabilities using Poisson distributions
            prob_home = 0.0
            prob_draw = 0.0
            prob_away = 0.0
            
            # Sum over reasonable goal ranges
            for h_goals in range(6):
                for a_goals in range(6):
                    prob_score = (np.exp(-lambda_home) * (lambda_home ** h_goals) / np.math.factorial(h_goals)) * \
                                (np.exp(-lambda_away) * (lambda_away ** a_goals) / np.math.factorial(a_goals))
                    
                    if h_goals > a_goals:
                        prob_home += prob_score
                    elif h_goals == a_goals:
                        prob_draw += prob_score
                    else:
                        prob_away += prob_score
            
            # Normalize
            total = prob_home + prob_draw + prob_away
            if total > 0:
                prob_home /= total
                prob_draw /= total
                prob_away /= total
            else:
                prob_home, prob_draw, prob_away = 0.45, 0.25, 0.30
            
            probs.append([prob_home, prob_draw, prob_away])
        
        return np.array(probs)

class GoalDifferenceRegressor:
    """Goal difference regression mapped to 3-way probabilities"""
    
    def __init__(self, model_params=None):
        """Initialize goal difference regressor"""
        
        default_params = {
            'objective': 'regression',
            'metric': 'rmse',
            'boosting_type': 'gbdt',
            'num_leaves': 31,
            'learning_rate': 0.05,
            'feature_fraction': 0.8,
            'bagging_fraction': 0.8,
            'bagging_freq': 5,
            'verbose': -1,
            'random_state': 42
        }
        
        self.model_params = model_params or default_params
        self.model = None
        self.feature_names = None
        self.scaler = StandardScaler()
        
    def prepare_features(self, df: pd.DataFrame) -> np.ndarray:
        """Prepare feature matrix"""
        
        # Same feature preparation as TwoStageClassifier
        exclude_cols = [
            'match_id', 'outcome', 'home_goals', 'away_goals', 'goal_difference',
            'total_goals', 'match_date_utc', 'feature_cutoff_time', 'home_team_id',
            'away_team_id', 'season'
        ]
        
        feature_cols = [col for col in df.columns if col not in exclude_cols]
        self.feature_names = feature_cols
        
        X = df[feature_cols].values
        X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
        
        return X
    
    def fit(self, df: pd.DataFrame) -> Dict:
        """Fit goal difference regressor"""
        
        print("Training Goal Difference Regressor...")
        
        X = self.prepare_features(df)
        y = df['goal_difference'].values  # home_goals - away_goals
        
        # Scale features
        X_scaled = self.scaler.fit_transform(X)
        
        # Train regressor
        self.model = lgb.LGBMRegressor(**self.model_params)
        self.model.fit(X_scaled, y)
        
        # Cross-validation score
        cv_score = cross_val_score(
            self.model, X_scaled, y, cv=5, scoring='neg_mean_squared_error'
        ).mean()
        
        print(f"Goal Difference CV RMSE: {np.sqrt(-cv_score):.4f}")
        
        return {
            'cv_rmse': np.sqrt(-cv_score),
            'n_features': len(self.feature_names),
            'n_samples': len(df)
        }
    
    def predict_proba(self, df: pd.DataFrame) -> np.ndarray:
        """Predict probabilities by mapping goal difference to outcomes"""
        
        X = self.prepare_features(df)
        X_scaled = self.scaler.transform(X)
        
        # Predict goal differences
        goal_diffs = self.model.predict(X_scaled)
        
        # Map to probabilities using sigmoid-like functions
        probs = []
        
        for gd in goal_diffs:
            # Use logistic functions to map goal difference to probabilities
            # Calibrated roughly to football statistics
            
            # Probability of home win increases with positive goal difference
            prob_home = 1 / (1 + np.exp(-1.5 * gd))
            
            # Probability of draw peaks around goal difference = 0
            prob_draw = 0.4 * np.exp(-0.5 * gd**2)
            
            # Probability of away win
            prob_away = 1 - prob_home - prob_draw
            
            # Ensure valid probabilities
            prob_away = max(0, prob_away)
            
            # Normalize
            total = prob_home + prob_draw + prob_away
            if total > 0:
                prob_home /= total
                prob_draw /= total
                prob_away /= total
            else:
                prob_home, prob_draw, prob_away = 0.45, 0.25, 0.30
            
            probs.append([prob_home, prob_draw, prob_away])
        
        return np.array(probs)

class EnsembleMetaLearner:
    """Meta-learner to combine multiple model predictions"""
    
    def __init__(self, base_models: List, meta_model=None):
        """
        Initialize ensemble meta-learner
        
        Args:
            base_models: List of base model instances
            meta_model: Meta-learning model (default: LogisticRegression)
        """
        self.base_models = base_models
        self.meta_model = meta_model or LogisticRegression(
            random_state=42, max_iter=1000
        )
        self.model_names = [type(model).__name__ for model in base_models]
        
    def fit(self, train_df: pd.DataFrame, val_df: pd.DataFrame) -> Dict:
        """
        Fit ensemble using out-of-fold predictions for meta-learning
        
        Args:
            train_df: Training data for base models
            val_df: Validation data for meta-model training
        """
        
        print("Training Ensemble Meta-Learner...")
        
        # Train base models on training data
        base_metrics = {}
        for i, model in enumerate(self.base_models):
            model_name = self.model_names[i]
            print(f"Training {model_name}...")
            
            try:
                metrics = model.fit(train_df)
                base_metrics[model_name] = metrics
            except Exception as e:
                print(f"Error training {model_name}: {e}")
                base_metrics[model_name] = {'error': str(e)}
        
        # Generate out-of-fold predictions on validation set
        meta_features = []
        
        for model in self.base_models:
            try:
                model_probs = model.predict_proba(val_df)
                meta_features.append(model_probs)
            except Exception as e:
                print(f"Error generating predictions: {e}")
                # Fallback to uniform predictions
                n_samples = len(val_df)
                uniform_probs = np.full((n_samples, 3), 1/3)
                meta_features.append(uniform_probs)
        
        # Combine base model predictions as meta-features
        # Shape: (n_samples, n_models * 3)
        X_meta = np.hstack(meta_features)
        
        # Prepare meta-targets (one-hot encoded outcomes)
        y_meta = val_df['outcome'].values
        y_meta_encoded = np.zeros((len(y_meta), 3))
        for i, outcome in enumerate(y_meta):
            if outcome == 'H':
                y_meta_encoded[i, 0] = 1
            elif outcome == 'D':
                y_meta_encoded[i, 1] = 1
            else:  # 'A'
                y_meta_encoded[i, 2] = 1
        
        # Train meta-model for each outcome
        self.meta_models = []
        
        for outcome_idx in range(3):
            meta_model_copy = LogisticRegression(random_state=42, max_iter=1000)
            meta_model_copy.fit(X_meta, y_meta_encoded[:, outcome_idx])
            self.meta_models.append(meta_model_copy)
        
        print(f"Ensemble trained with {len(self.base_models)} base models")
        
        return {
            'base_models': base_metrics,
            'n_base_models': len(self.base_models),
            'meta_features_shape': X_meta.shape
        }
    
    def predict_proba(self, df: pd.DataFrame) -> np.ndarray:
        """Generate ensemble predictions"""
        
        # Get base model predictions
        base_predictions = []
        
        for model in self.base_models:
            try:
                model_probs = model.predict_proba(df)
                base_predictions.append(model_probs)
            except Exception as e:
                print(f"Error in ensemble prediction: {e}")
                # Fallback to uniform
                n_samples = len(df)
                uniform_probs = np.full((n_samples, 3), 1/3)
                base_predictions.append(uniform_probs)
        
        # Combine as meta-features
        X_meta = np.hstack(base_predictions)
        
        # Generate meta-model predictions
        ensemble_probs = np.zeros((len(df), 3))
        
        for outcome_idx in range(3):
            outcome_probs = self.meta_models[outcome_idx].predict_proba(X_meta)[:, 1]
            ensemble_probs[:, outcome_idx] = outcome_probs
        
        # Normalize probabilities
        ensemble_probs = ensemble_probs / ensemble_probs.sum(axis=1, keepdims=True)
        
        return ensemble_probs

def save_model_artifacts(model, model_name: str, metadata: Dict, 
                        output_dir: str = 'models/static'):
    """Save model artifacts with metadata"""
    
    import os
    os.makedirs(output_dir, exist_ok=True)
    
    # Save model
    model_path = f"{output_dir}/{model_name}.joblib"
    joblib.dump(model, model_path)
    
    # Save metadata
    metadata_with_timestamp = {
        **metadata,
        'model_name': model_name,
        'saved_at': datetime.now().isoformat(),
        'model_path': model_path
    }
    
    metadata_path = f"{output_dir}/{model_name}_metadata.json"
    with open(metadata_path, 'w') as f:
        json.dump(metadata_with_timestamp, f, indent=2, default=str)
    
    print(f"Model saved: {model_path}")
    print(f"Metadata saved: {metadata_path}")
    
    return model_path, metadata_path

def load_model_artifacts(model_name: str, models_dir: str = 'models/static'):
    """Load model artifacts"""
    
    model_path = f"{models_dir}/{model_name}.joblib"
    metadata_path = f"{models_dir}/{model_name}_metadata.json"
    
    model = joblib.load(model_path)
    
    with open(metadata_path, 'r') as f:
        metadata = json.load(f)
    
    return model, metadata