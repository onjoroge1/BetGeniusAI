"""
Static Forecaster Training Pipeline - Accuracy-first model training
"""

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split, TimeSeriesSplit
from sklearn.calibration import CalibratedClassifierCV
import warnings
warnings.filterwarnings('ignore')

from typing import Dict, List, Tuple, Optional
import os
import json
from datetime import datetime

from .data_snapshot import StaticSnapshotBuilder
from .models import (
    TwoStageClassifier, PoissonDixonColes, GoalDifferenceRegressor,
    EnsembleMetaLearner, save_model_artifacts
)
from .evaluation import StaticEvaluator

class StaticTrainer:
    """Training pipeline for static accuracy-first forecasting"""
    
    def __init__(self, snapshot_time_hours: int = 24):
        """
        Initialize trainer
        
        Args:
            snapshot_time_hours: Hours before kickoff for feature cutoff
        """
        self.snapshot_time = snapshot_time_hours
        self.data_builder = StaticSnapshotBuilder(snapshot_time_hours)
        self.evaluator = StaticEvaluator()
        
        self.models = {}
        self.calibrators = {}
        self.training_metadata = {}
        
    def build_training_dataset(self, min_date: str = None, 
                             max_date: str = None) -> pd.DataFrame:
        """Build training dataset with feature engineering"""
        
        print(f"🔧 Building training dataset (T-{self.snapshot_time}h snapshot)...")
        
        dataset = self.data_builder.build_static_dataset(min_date, max_date)
        
        if len(dataset) == 0:
            raise ValueError("No training data available")
        
        # Additional feature engineering for training
        dataset = self._enhance_features(dataset)
        
        # Quality gates for training data
        self._validate_training_data(dataset)
        
        return dataset
    
    def _enhance_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add enhanced features for better prediction accuracy"""
        
        df = df.copy()
        
        # Goal expectation features
        df['expected_total_goals'] = (df['home_gf_avg'] + df['away_gf_avg'] + 
                                    df['home_ga_avg'] + df['away_ga_avg']) / 2
        
        # Strength ratios
        df['elo_ratio'] = df['home_elo'] / (df['away_elo'] + 1e-6)
        df['attack_ratio'] = df['home_gf_avg'] / (df['away_gf_avg'] + 1e-6)
        df['defense_ratio'] = df['away_ga_avg'] / (df['home_ga_avg'] + 1e-6)
        
        # Form momentum
        df['form_momentum_home'] = df['home_form_pts'] / 15.0  # Normalize to [0,1]
        df['form_momentum_away'] = df['away_form_pts'] / 15.0
        df['form_momentum_diff'] = df['form_momentum_home'] - df['form_momentum_away']
        
        # Match importance (simplified)
        df['match_importance'] = np.where(
            df['league_id'].isin([39, 140, 135]), 1.0, 0.8  # Top leagues get higher importance
        )
        
        # Rest advantage
        df['rest_advantage'] = np.where(
            df['rest_diff'] > 2, 0.1,  # Home team better rested
            np.where(df['rest_diff'] < -2, -0.1, 0.0)  # Away team better rested
        )
        
        # H2H dominance
        h2h_total = df['h2h_home_wins'] + df['h2h_draws'] + df['h2h_away_wins']
        df['h2h_home_dominance'] = df['h2h_home_wins'] / (h2h_total + 1e-6)
        df['h2h_balance'] = df['h2h_draws'] / (h2h_total + 1e-6)
        
        return df
    
    def _validate_training_data(self, df: pd.DataFrame):
        """Validate training data quality"""
        
        print("🔍 Validating training data quality...")
        
        # Minimum sample sizes per league
        min_samples_per_league = 50
        
        league_counts = df['league_id'].value_counts()
        insufficient_leagues = league_counts[league_counts < min_samples_per_league]
        
        if len(insufficient_leagues) > 0:
            print(f"⚠️ Warning: {len(insufficient_leagues)} leagues have < {min_samples_per_league} samples")
        
        # Outcome balance check
        outcome_dist = df['outcome'].value_counts(normalize=True)
        print(f"Outcome distribution: H={outcome_dist.get('H', 0):.1%}, "
              f"D={outcome_dist.get('D', 0):.1%}, A={outcome_dist.get('A', 0):.1%}")
        
        # Check for extreme class imbalance
        min_outcome_pct = outcome_dist.min()
        if min_outcome_pct < 0.15:
            print(f"⚠️ Warning: Extreme class imbalance detected (min: {min_outcome_pct:.1%})")
        
        # Feature completeness
        feature_completeness = (1 - df.isnull().sum() / len(df)).min()
        print(f"Feature completeness: {feature_completeness:.1%}")
        
        if feature_completeness < 0.95:
            print("⚠️ Warning: Some features have >5% missing values")
        
        # Temporal distribution
        date_range = df['match_date_utc'].max() - df['match_date_utc'].min()
        print(f"Temporal span: {date_range.days} days")
        
        print("✅ Training data validation complete")
    
    def train_all_models(self, dataset: pd.DataFrame, 
                        test_size: float = 0.2) -> Dict:
        """Train all model architectures with proper validation"""
        
        print("🎯 Training all model architectures...")
        
        # Time-aware split to prevent data leakage
        dataset_sorted = dataset.sort_values('match_date_utc')
        split_idx = int(len(dataset_sorted) * (1 - test_size))
        
        train_df = dataset_sorted.iloc[:split_idx].copy()
        test_df = dataset_sorted.iloc[split_idx:].copy()
        
        print(f"Training set: {len(train_df)} matches")
        print(f"Test set: {len(test_df)} matches")
        print(f"Training date range: {train_df['match_date_utc'].min()} to {train_df['match_date_utc'].max()}")
        print(f"Test date range: {test_df['match_date_utc'].min()} to {test_df['match_date_utc'].max()}")
        
        # Validation split for meta-learning
        train_split_idx = int(len(train_df) * 0.8)
        base_train_df = train_df.iloc[:train_split_idx].copy()
        meta_train_df = train_df.iloc[train_split_idx:].copy()
        
        # 1. Two-Stage Classifier
        print("\n1️⃣ Training Two-Stage Classifier...")
        twostage_model = TwoStageClassifier()
        twostage_metrics = twostage_model.fit(base_train_df)
        self.models['twostage'] = twostage_model
        
        # 2. Poisson/Dixon-Coles
        print("\n2️⃣ Training Poisson/Dixon-Coles...")
        poisson_model = PoissonDixonColes()
        poisson_metrics = poisson_model.fit(base_train_df)
        self.models['poisson'] = poisson_model
        
        # 3. Goal Difference Regressor
        print("\n3️⃣ Training Goal Difference Regressor...")
        goalreg_model = GoalDifferenceRegressor()
        goalreg_metrics = goalreg_model.fit(base_train_df)
        self.models['goal_regression'] = goalreg_model
        
        # 4. Ensemble Meta-Learner
        print("\n4️⃣ Training Ensemble Meta-Learner...")
        base_models = [twostage_model, poisson_model, goalreg_model]
        ensemble_model = EnsembleMetaLearner(base_models)
        ensemble_metrics = ensemble_model.fit(base_train_df, meta_train_df)
        self.models['ensemble'] = ensemble_model
        
        # Store training metadata
        self.training_metadata = {
            'training_date': datetime.now().isoformat(),
            'snapshot_time_hours': self.snapshot_time,
            'train_samples': len(train_df),
            'test_samples': len(test_df),
            'meta_train_samples': len(meta_train_df),
            'base_train_samples': len(base_train_df),
            'training_metrics': {
                'twostage': twostage_metrics,
                'poisson': poisson_metrics,
                'goal_regression': goalreg_metrics,
                'ensemble': ensemble_metrics
            },
            'date_ranges': {
                'train_start': train_df['match_date_utc'].min().isoformat(),
                'train_end': train_df['match_date_utc'].max().isoformat(),
                'test_start': test_df['match_date_utc'].min().isoformat(),
                'test_end': test_df['match_date_utc'].max().isoformat()
            }
        }
        
        print("✅ All models trained successfully")
        
        return {
            'train_df': train_df,
            'test_df': test_df,
            'meta_train_df': meta_train_df,
            'base_train_df': base_train_df
        }
    
    def calibrate_models(self, train_df: pd.DataFrame) -> Dict:
        """Apply per-league calibration to all models"""
        
        print("🎯 Calibrating models per league...")
        
        # Get league IDs with sufficient data
        min_samples_for_calibration = 30
        league_counts = train_df['league_id'].value_counts()
        valid_leagues = league_counts[league_counts >= min_samples_for_calibration].index.tolist()
        
        print(f"Calibrating for {len(valid_leagues)} leagues with sufficient data")
        
        calibration_results = {}
        
        for model_name, model in self.models.items():
            print(f"Calibrating {model_name}...")
            
            league_calibrators = {}
            
            for league_id in valid_leagues:
                league_data = train_df[train_df['league_id'] == league_id]
                
                if len(league_data) < min_samples_for_calibration:
                    continue
                
                try:
                    # Generate base predictions
                    base_probs = model.predict_proba(league_data)
                    y_true = league_data['outcome'].values
                    
                    # Convert to indices for calibration
                    outcome_to_idx = {'H': 0, 'D': 1, 'A': 2}
                    y_true_idx = np.array([outcome_to_idx[outcome] for outcome in y_true])
                    
                    # Calibrate each outcome separately using isotonic regression
                    from sklearn.isotonic import IsotonicRegression
                    
                    outcome_calibrators = {}
                    
                    for outcome_idx in range(3):
                        y_binary = (y_true_idx == outcome_idx).astype(int)
                        
                        if y_binary.sum() >= 5:  # Minimum positives for calibration
                            calibrator = IsotonicRegression(out_of_bounds='clip')
                            calibrator.fit(base_probs[:, outcome_idx], y_binary)
                            outcome_calibrators[outcome_idx] = calibrator
                    
                    if outcome_calibrators:
                        league_calibrators[league_id] = outcome_calibrators
                
                except Exception as e:
                    print(f"Error calibrating {model_name} for league {league_id}: {e}")
            
            self.calibrators[model_name] = league_calibrators
            calibration_results[model_name] = {
                'leagues_calibrated': len(league_calibrators),
                'total_leagues': len(valid_leagues)
            }
        
        print("✅ Calibration complete")
        return calibration_results
    
    def apply_calibration(self, model_name: str, predictions: np.ndarray,
                         league_ids: np.ndarray) -> np.ndarray:
        """Apply per-league calibration to predictions"""
        
        if model_name not in self.calibrators:
            return predictions
        
        calibrated_predictions = predictions.copy()
        model_calibrators = self.calibrators[model_name]
        
        for i, league_id in enumerate(league_ids):
            if league_id in model_calibrators:
                league_calibrators = model_calibrators[league_id]
                
                for outcome_idx, calibrator in league_calibrators.items():
                    try:
                        calibrated_prob = calibrator.transform([predictions[i, outcome_idx]])[0]
                        calibrated_predictions[i, outcome_idx] = calibrated_prob
                    except:
                        pass  # Keep original prediction if calibration fails
        
        # Renormalize probabilities
        calibrated_predictions = calibrated_predictions / calibrated_predictions.sum(axis=1, keepdims=True)
        
        return calibrated_predictions
    
    def evaluate_models(self, test_df: pd.DataFrame) -> Dict:
        """Comprehensive evaluation of all trained models"""
        
        print("📊 Evaluating all models...")
        
        # Generate predictions for all models
        model_predictions = {}
        
        for model_name, model in self.models.items():
            print(f"Generating predictions for {model_name}...")
            
            try:
                # Base predictions
                base_preds = model.predict_proba(test_df)
                
                # Apply calibration
                calibrated_preds = self.apply_calibration(
                    model_name, base_preds, test_df['league_id'].values
                )
                
                model_predictions[f"{model_name}_base"] = base_preds
                model_predictions[f"{model_name}_calibrated"] = calibrated_preds
                
            except Exception as e:
                print(f"Error generating predictions for {model_name}: {e}")
        
        # Evaluate against baselines
        overall_results = self.evaluator.compare_against_baselines(
            test_df, model_predictions
        )
        
        # Per-league evaluation
        league_results = self.evaluator.evaluate_by_league(
            test_df, model_predictions
        )
        
        # Check promotion gates
        promotion_results = self.evaluator.check_promotion_gates(
            overall_results, min_samples=len(test_df) // 10
        )
        
        return {
            'overall': overall_results,
            'by_league': league_results,
            'promotion_gates': promotion_results,
            'model_predictions': model_predictions
        }
    
    def save_production_models(self, evaluation_results: Dict,
                             output_dir: str = 'models/static') -> Dict:
        """Save production-ready models based on evaluation results"""
        
        print("💾 Saving production models...")
        
        os.makedirs(output_dir, exist_ok=True)
        
        # Find best performing model
        overall_results = evaluation_results['overall']
        promotion_results = evaluation_results['promotion_gates']
        
        # Filter to approved models
        approved_models = [
            model_name for model_name, promo_data in promotion_results.items()
            if promo_data['promotion_status'] == 'APPROVED'
        ]
        
        if not approved_models:
            print("⚠️ No models passed promotion gates")
            # Save best model anyway for further development
            non_baseline_models = [
                name for name, data in overall_results.items()
                if data.get('model_type') != 'baseline' and 'error' not in data
            ]
            
            if non_baseline_models:
                best_model = min(non_baseline_models, 
                               key=lambda x: overall_results[x].get('logloss', float('inf')))
                approved_models = [best_model]
        
        saved_models = {}
        
        for model_name in approved_models:
            # Extract base model name (remove _calibrated suffix)
            base_model_name = model_name.replace('_calibrated', '').replace('_base', '')
            
            if base_model_name in self.models:
                model_obj = self.models[base_model_name]
                
                # Prepare metadata
                model_metadata = {
                    'model_name': model_name,
                    'base_model_type': type(model_obj).__name__,
                    'snapshot_time_hours': self.snapshot_time,
                    'training_metadata': self.training_metadata,
                    'evaluation_results': overall_results[model_name],
                    'promotion_status': promotion_results[model_name],
                    'calibrators': self.calibrators.get(base_model_name, {})
                }
                
                # Save model and metadata
                model_path, metadata_path = save_model_artifacts(
                    {
                        'model': model_obj,
                        'calibrators': self.calibrators.get(base_model_name, {}),
                        'feature_names': getattr(model_obj, 'feature_names', None)
                    },
                    model_name,
                    model_metadata,
                    output_dir
                )
                
                saved_models[model_name] = {
                    'model_path': model_path,
                    'metadata_path': metadata_path,
                    'performance': overall_results[model_name]
                }
        
        print(f"✅ Saved {len(saved_models)} production models")
        return saved_models
    
    def generate_training_report(self, evaluation_results: Dict,
                               output_dir: str = 'reports/static') -> str:
        """Generate comprehensive training report"""
        
        # Generate evaluation report
        report_path = self.evaluator.generate_evaluation_report(
            evaluation_results['overall'],
            evaluation_results['by_league'],
            evaluation_results['promotion_gates'],
            output_dir
        )
        
        # Save detailed results
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        results_path = f"{output_dir}/training_results_{timestamp}.json"
        
        full_results = {
            'training_metadata': self.training_metadata,
            'evaluation_results': evaluation_results,
            'calibration_info': {
                model_name: {
                    'leagues_with_calibrators': len(calibrators)
                    for league_id, calibrators in self.calibrators.get(model_name, {}).items()
                }
                for model_name in self.calibrators.keys()
            }
        }
        
        self.evaluator.save_results(full_results, results_path)
        
        print(f"📊 Training report generated: {report_path}")
        print(f"📊 Detailed results saved: {results_path}")
        
        return report_path

def main():
    """Run complete static training pipeline"""
    
    print("🚀 Starting Static Forecasting Training Pipeline")
    print("=" * 60)
    
    # Initialize trainer
    trainer = StaticTrainer(snapshot_time_hours=24)
    
    # Build training dataset
    try:
        dataset = trainer.build_training_dataset()
    except Exception as e:
        print(f"❌ Failed to build dataset: {e}")
        print("Using synthetic data for demonstration...")
        
        # Create synthetic dataset for demo
        np.random.seed(42)
        n_samples = 1000
        
        dataset = pd.DataFrame({
            'match_id': range(1, n_samples + 1),
            'league_id': np.random.choice([39, 140, 135, 78, 61], n_samples),
            'match_date_utc': pd.date_range('2023-01-01', periods=n_samples, freq='D'),
            'outcome': np.random.choice(['H', 'D', 'A'], n_samples, p=[0.45, 0.25, 0.30]),
            'home_elo': np.random.normal(1500, 100, n_samples),
            'away_elo': np.random.normal(1500, 100, n_samples),
            'elo_diff': np.random.normal(0, 150, n_samples),
            'home_advantage': np.random.normal(0.15, 0.05, n_samples),
            'league_avg_goals': np.random.normal(2.7, 0.3, n_samples)
        })
        
        # Add required numeric columns
        for col in ['home_wins_pct', 'away_wins_pct', 'home_gf_avg', 'away_gf_avg',
                   'home_ga_avg', 'away_ga_avg', 'home_form_pts', 'away_form_pts']:
            dataset[col] = np.random.uniform(0, 3, n_samples)
    
    if len(dataset) < 100:
        print(f"❌ Insufficient data: {len(dataset)} samples")
        return
    
    # Train all models
    train_data = trainer.train_all_models(dataset)
    
    # Calibrate models
    calibration_results = trainer.calibrate_models(train_data['train_df'])
    
    # Evaluate models
    evaluation_results = trainer.evaluate_models(train_data['test_df'])
    
    # Save production models
    saved_models = trainer.save_production_models(evaluation_results)
    
    # Generate reports
    trainer.generate_training_report(evaluation_results)
    
    print("\n🎯 TRAINING PIPELINE COMPLETE")
    print("=" * 60)
    
    # Summary
    overall_results = evaluation_results['overall']
    promotion_results = evaluation_results['promotion_gates']
    
    approved_models = [
        name for name, data in promotion_results.items()
        if data['promotion_status'] == 'APPROVED'
    ]
    
    print(f"Models trained: {len(trainer.models)}")
    print(f"Models approved for production: {len(approved_models)}")
    print(f"Models saved: {len(saved_models)}")
    
    if approved_models:
        print(f"✅ Production ready: {', '.join(approved_models)}")
    else:
        print("⚠️ No models passed all promotion gates")
    
    return {
        'trainer': trainer,
        'evaluation_results': evaluation_results,
        'saved_models': saved_models
    }

if __name__ == "__main__":
    main()