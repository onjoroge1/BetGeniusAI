"""
Probability Calibration System - Phase 3 Implementation
Converts model predictions into well-calibrated probabilities for profitable betting
"""

import numpy as np
import pandas as pd
import joblib
import matplotlib.pyplot as plt
from sklearn.calibration import CalibratedClassifierCV, calibration_curve
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss
from sklearn.model_selection import cross_val_predict
import os
from typing import Dict, Tuple, List, Optional
import warnings
warnings.filterwarnings('ignore')

class ProbabilityCalibrator:
    """
    Calibrates model probabilities using isotonic regression or Platt scaling
    Ensures probabilities reflect true likelihood for betting applications
    """
    
    def __init__(self, method='isotonic'):
        """
        Initialize calibrator
        
        Args:
            method: 'isotonic' or 'platt' calibration method
        """
        self.method = method
        self.calibrators = {}
        self.is_fitted = False
        
    def fit_calibrator(self, model, X_calib, y_calib):
        """
        Fit probability calibrators for each outcome
        
        Args:
            model: Trained two-stage model
            X_calib: Calibration features
            y_calib: Calibration labels (0=Home, 1=Draw, 2=Away)
        """
        print(f"🎯 Fitting {self.method} probability calibrator...")
        
        # Get uncalibrated probabilities from two-stage model
        uncalibrated_probs = self._get_uncalibrated_probabilities(model, X_calib)
        
        # Fit calibrators for each outcome
        for outcome_idx, outcome_name in enumerate(['Home', 'Draw', 'Away']):
            # Binary labels for this outcome
            binary_labels = (y_calib == outcome_idx).astype(int)
            outcome_probs = uncalibrated_probs[:, outcome_idx]
            
            if self.method == 'isotonic':
                calibrator = IsotonicRegression(out_of_bounds='clip')
            else:  # platt
                calibrator = LogisticRegression()
                outcome_probs = outcome_probs.reshape(-1, 1)
            
            # Fit calibrator
            calibrator.fit(outcome_probs, binary_labels)
            self.calibrators[outcome_name] = calibrator
            
            print(f"  ✅ {outcome_name} calibrator fitted")
        
        self.is_fitted = True
        print(f"🎉 Probability calibration complete!")
        
    def predict_calibrated_probabilities(self, model, X):
        """
        Get calibrated probabilities for new data
        
        Args:
            model: Trained two-stage model
            X: Features for prediction
            
        Returns:
            Calibrated probabilities [N, 3] for Home/Draw/Away
        """
        if not self.is_fitted:
            raise ValueError("Calibrator must be fitted before prediction")
        
        # Get uncalibrated probabilities
        uncalibrated_probs = self._get_uncalibrated_probabilities(model, X)
        
        # Apply calibration to each outcome
        calibrated_probs = np.zeros_like(uncalibrated_probs)
        
        for outcome_idx, outcome_name in enumerate(['Home', 'Draw', 'Away']):
            calibrator = self.calibrators[outcome_name]
            outcome_probs = uncalibrated_probs[:, outcome_idx]
            
            if self.method == 'platt':
                outcome_probs = outcome_probs.reshape(-1, 1)
            
            calibrated_probs[:, outcome_idx] = calibrator.predict(outcome_probs)
        
        # Normalize to ensure probabilities sum to 1
        row_sums = calibrated_probs.sum(axis=1, keepdims=True)
        calibrated_probs = calibrated_probs / (row_sums + 1e-8)
        
        return calibrated_probs
    
    def _get_uncalibrated_probabilities(self, model, X):
        """Get uncalibrated probabilities from two-stage model"""
        # Stage 1: Draw vs Not-Draw probabilities
        draw_probs = model['model_draw_vs_not'].predict_proba(X)[:, 1]  # Probability of draw
        not_draw_probs = 1 - draw_probs
        
        # Stage 2: Home vs Away probabilities (for non-draws)
        home_vs_away_probs = model['model_home_vs_away'].predict_proba(X)[:, 1]  # Probability of home win
        
        # Combine into 3-class probabilities
        home_probs = not_draw_probs * home_vs_away_probs
        away_probs = not_draw_probs * (1 - home_vs_away_probs)
        draw_probs_final = draw_probs
        
        # Stack into matrix
        uncalibrated_probs = np.column_stack([home_probs, draw_probs_final, away_probs])
        
        # Normalize
        row_sums = uncalibrated_probs.sum(axis=1, keepdims=True)
        uncalibrated_probs = uncalibrated_probs / (row_sums + 1e-8)
        
        return uncalibrated_probs
    
    def evaluate_calibration(self, model, X_test, y_test, save_plots=True):
        """
        Evaluate calibration quality with reliability plots and Brier score
        
        Args:
            model: Trained two-stage model
            X_test: Test features
            y_test: Test labels
            save_plots: Whether to save reliability plots
            
        Returns:
            Dict with calibration metrics
        """
        print("📊 Evaluating probability calibration...")
        
        # Get both uncalibrated and calibrated probabilities
        uncalibrated_probs = self._get_uncalibrated_probabilities(model, X_test)
        calibrated_probs = self.predict_calibrated_probabilities(model, X_test)
        
        metrics = {}
        
        # Calculate metrics for each outcome
        for outcome_idx, outcome_name in enumerate(['Home', 'Draw', 'Away']):
            binary_labels = (y_test == outcome_idx).astype(int)
            
            # Brier Score (lower is better)
            uncal_brier = brier_score_loss(binary_labels, uncalibrated_probs[:, outcome_idx])
            cal_brier = brier_score_loss(binary_labels, calibrated_probs[:, outcome_idx])
            
            # Reliability (calibration curve)
            if save_plots:
                self._plot_reliability_curve(
                    binary_labels, 
                    uncalibrated_probs[:, outcome_idx],
                    calibrated_probs[:, outcome_idx],
                    outcome_name
                )
            
            metrics[outcome_name] = {
                'uncalibrated_brier': uncal_brier,
                'calibrated_brier': cal_brier,
                'brier_improvement': uncal_brier - cal_brier
            }
            
            print(f"  {outcome_name} - Brier Score: {uncal_brier:.4f} → {cal_brier:.4f} (Δ{cal_brier-uncal_brier:+.4f})")
        
        # Overall log loss
        uncal_logloss = log_loss(y_test, uncalibrated_probs)
        cal_logloss = log_loss(y_test, calibrated_probs)
        
        metrics['overall'] = {
            'uncalibrated_logloss': uncal_logloss,
            'calibrated_logloss': cal_logloss,
            'logloss_improvement': uncal_logloss - cal_logloss
        }
        
        print(f"  Overall Log Loss: {uncal_logloss:.4f} → {cal_logloss:.4f} (Δ{cal_logloss-uncal_logloss:+.4f})")
        
        return metrics
    
    def _plot_reliability_curve(self, y_true, prob_uncal, prob_cal, outcome_name):
        """Plot reliability diagram comparing uncalibrated vs calibrated"""
        plt.figure(figsize=(10, 6))
        
        # Reliability curves
        fraction_pos_uncal, mean_pred_uncal = calibration_curve(y_true, prob_uncal, n_bins=10)
        fraction_pos_cal, mean_pred_cal = calibration_curve(y_true, prob_cal, n_bins=10)
        
        # Plot
        plt.subplot(1, 2, 1)
        plt.plot([0, 1], [0, 1], 'k--', label='Perfect Calibration')
        plt.plot(mean_pred_uncal, fraction_pos_uncal, 'ro-', label='Uncalibrated')
        plt.plot(mean_pred_cal, fraction_pos_cal, 'bo-', label='Calibrated')
        plt.xlabel('Mean Predicted Probability')
        plt.ylabel('Fraction of Positives')
        plt.title(f'{outcome_name} - Reliability Plot')
        plt.legend()
        plt.grid(True, alpha=0.3)
        
        # Histogram of predictions
        plt.subplot(1, 2, 2)
        plt.hist(prob_uncal, bins=20, alpha=0.5, label='Uncalibrated', density=True)
        plt.hist(prob_cal, bins=20, alpha=0.5, label='Calibrated', density=True)
        plt.xlabel('Predicted Probability')
        plt.ylabel('Density')
        plt.title(f'{outcome_name} - Probability Distribution')
        plt.legend()
        plt.grid(True, alpha=0.3)
        
        plt.tight_layout()
        
        # Save plot
        os.makedirs('calibration_plots', exist_ok=True)
        plt.savefig(f'calibration_plots/{outcome_name.lower()}_reliability.png', dpi=150, bbox_inches='tight')
        plt.close()
        
        print(f"  📈 Reliability plot saved: calibration_plots/{outcome_name.lower()}_reliability.png")
    
    def get_top2_accuracy(self, probabilities, y_true):
        """Calculate Top-2 accuracy (correct prediction in top 2 most likely outcomes)"""
        # Get top 2 predictions for each sample
        top2_predictions = np.argsort(probabilities, axis=1)[:, -2:]
        
        # Check if true label is in top 2
        correct_in_top2 = np.any(top2_predictions == y_true.reshape(-1, 1), axis=1)
        
        return np.mean(correct_in_top2)
    
    def save_calibrator(self, filepath='models/probability_calibrator.joblib'):
        """Save fitted calibrator"""
        if not self.is_fitted:
            raise ValueError("Calibrator must be fitted before saving")
        
        calibrator_data = {
            'method': self.method,
            'calibrators': self.calibrators,
            'is_fitted': self.is_fitted
        }
        
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        joblib.dump(calibrator_data, filepath)
        print(f"💾 Calibrator saved: {filepath}")
    
    def load_calibrator(self, filepath='models/probability_calibrator.joblib'):
        """Load fitted calibrator"""
        calibrator_data = joblib.load(filepath)
        
        self.method = calibrator_data['method']
        self.calibrators = calibrator_data['calibrators']
        self.is_fitted = calibrator_data['is_fitted']
        
        print(f"📂 Calibrator loaded: {filepath}")

def main():
    """Test probability calibration system"""
    print("🚀 Phase 3: Probability Calibration System")
    print("=" * 50)
    
    try:
        # Load enhanced model
        model_data = joblib.load('models/clean_production_model.joblib')
        print("✅ Enhanced model loaded")
        
        # Load a sample of training data for calibration
        from enhanced_two_stage_trainer import EnhancedTwoStageTrainer
        trainer = EnhancedTwoStageTrainer()
        dataset = trainer.build_enhanced_dataset(limit_matches=500)
        
        if len(dataset) < 100:
            print("❌ Insufficient data for calibration")
            return
        
        # Prepare data
        feature_cols = [col for col in dataset.columns if col not in ['match_id', 'outcome']]
        X = dataset[feature_cols].fillna(0).values
        
        outcome_map = {'Home': 0, 'Draw': 1, 'Away': 2}
        y = dataset['outcome'].map(outcome_map).values
        
        # Scale features
        scaler = model_data['scaler']
        X_scaled = scaler.transform(X)
        
        # Split for calibration and evaluation
        split_idx = int(len(X) * 0.6)  # Use 60% for calibration, 40% for evaluation
        X_calib, X_eval = X_scaled[:split_idx], X_scaled[split_idx:]
        y_calib, y_eval = y[:split_idx], y[split_idx:]
        
        print(f"📊 Calibration data: {len(X_calib)} samples")
        print(f"📊 Evaluation data: {len(X_eval)} samples")
        
        # Initialize and fit calibrator
        calibrator = ProbabilityCalibrator(method='isotonic')
        calibrator.fit_calibrator(model_data, X_calib, y_calib)
        
        # Evaluate calibration
        metrics = calibrator.evaluate_calibration(model_data, X_eval, y_eval)
        
        # Get calibrated probabilities for evaluation
        calibrated_probs = calibrator.predict_calibrated_probabilities(model_data, X_eval)
        
        # Calculate key metrics
        top2_accuracy = calibrator.get_top2_accuracy(calibrated_probs, y_eval)
        accuracy_3way = np.mean(np.argmax(calibrated_probs, axis=1) == y_eval)
        
        print(f"\n🎯 Calibrated Model Performance:")
        print(f"  3-way Accuracy: {accuracy_3way:.3f}")
        print(f"  Top-2 Accuracy: {top2_accuracy:.3f}")
        print(f"  Log Loss: {metrics['overall']['calibrated_logloss']:.4f}")
        
        # Save calibrator
        calibrator.save_calibrator()
        
        print(f"\n✅ Probability calibration system ready!")
        print(f"🎯 Next: Implement betting layer with odds ingestion")
        
    except Exception as e:
        print(f"❌ Calibration error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()