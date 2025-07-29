"""
Static Evaluation Framework - Accuracy-first proper scoring rules
"""

import numpy as np
import pandas as pd
from sklearn.metrics import log_loss, brier_score_loss, accuracy_score
from sklearn.calibration import calibration_curve
from sklearn.model_selection import train_test_split
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import warnings
warnings.filterwarnings('ignore')

from typing import Dict, List, Tuple, Optional
import json
import os
from datetime import datetime

class StaticEvaluator:
    """Comprehensive evaluation for static accuracy-first forecasting"""
    
    def __init__(self):
        self.euro_leagues = {
            39: 'English Premier League',
            140: 'La Liga Santander', 
            135: 'Serie A',
            78: 'Bundesliga',
            61: 'Ligue 1'
        }
    
    def evaluate_model(self, y_true: np.ndarray, y_pred_proba: np.ndarray,
                      sample_weight: np.ndarray = None) -> Dict:
        """
        Comprehensive model evaluation with proper scoring rules
        
        Args:
            y_true: True outcomes as strings ['H', 'D', 'A']
            y_pred_proba: Predicted probabilities (n_samples, 3) for [H, D, A]
            sample_weight: Optional sample weights
            
        Returns:
            Dictionary with evaluation metrics
        """
        
        # Convert string outcomes to indices
        outcome_to_idx = {'H': 0, 'D': 1, 'A': 2}
        y_true_idx = np.array([outcome_to_idx[outcome] for outcome in y_true])
        
        # Ensure probabilities are valid
        y_pred_proba = np.clip(y_pred_proba, 1e-15, 1 - 1e-15)
        y_pred_proba = y_pred_proba / y_pred_proba.sum(axis=1, keepdims=True)
        
        # Basic accuracy metrics
        y_pred_class = np.argmax(y_pred_proba, axis=1)
        accuracy = accuracy_score(y_true_idx, y_pred_class, sample_weight=sample_weight)
        
        # Top-2 accuracy
        top2_indices = np.argsort(y_pred_proba, axis=1)[:, -2:]
        top2_accuracy = np.mean([y_true_idx[i] in top2_indices[i] for i in range(len(y_true_idx))])
        
        # LogLoss (primary metric)
        logloss = log_loss(y_true_idx, y_pred_proba, sample_weight=sample_weight)
        
        # Brier Score (multi-class)
        # Convert to one-hot encoding for Brier calculation
        y_true_onehot = np.zeros((len(y_true_idx), 3))
        y_true_onehot[np.arange(len(y_true_idx)), y_true_idx] = 1
        
        brier_scores = []
        for outcome_idx in range(3):
            brier = brier_score_loss(
                y_true_onehot[:, outcome_idx], 
                y_pred_proba[:, outcome_idx],
                sample_weight=sample_weight
            )
            brier_scores.append(brier)
        
        avg_brier = np.mean(brier_scores)
        
        # Ranked Probability Score (RPS)
        rps_scores = []
        for i in range(len(y_true_idx)):
            # Cumulative probabilities
            cum_pred = np.cumsum(y_pred_proba[i])
            cum_true = np.cumsum(y_true_onehot[i])
            
            # RPS is sum of squared differences of cumulative probabilities
            rps = np.sum((cum_pred - cum_true) ** 2)
            rps_scores.append(rps)
        
        avg_rps = np.mean(rps_scores)
        
        # Per-outcome metrics
        outcome_metrics = {}
        outcome_names = ['home', 'draw', 'away']
        
        for idx, outcome_name in enumerate(outcome_names):
            outcome_mask = y_true_idx == idx
            if outcome_mask.sum() > 0:
                outcome_acc = accuracy_score(
                    y_true_idx[outcome_mask], 
                    y_pred_class[outcome_mask]
                )
                outcome_brier = brier_scores[idx]
                
                outcome_metrics[outcome_name] = {
                    'accuracy': outcome_acc,
                    'brier_score': outcome_brier,
                    'count': outcome_mask.sum(),
                    'avg_predicted_prob': y_pred_proba[outcome_mask, idx].mean()
                }
        
        # Calibration metrics
        calibration_metrics = self._calculate_calibration_metrics(
            y_true_onehot, y_pred_proba
        )
        
        return {
            # Primary metrics
            'logloss': logloss,
            'brier_score': avg_brier,
            'rps': avg_rps,
            'accuracy': accuracy,
            'top2_accuracy': top2_accuracy,
            
            # Per-outcome breakdown
            'outcome_metrics': outcome_metrics,
            
            # Calibration
            'calibration': calibration_metrics,
            
            # Sample info
            'n_samples': len(y_true),
            'outcome_distribution': {
                outcome_names[i]: (y_true_idx == i).sum() 
                for i in range(3)
            }
        }
    
    def _calculate_calibration_metrics(self, y_true_onehot: np.ndarray, 
                                     y_pred_proba: np.ndarray) -> Dict:
        """Calculate calibration metrics for each outcome"""
        
        calibration_results = {}
        outcome_names = ['home', 'draw', 'away']
        
        for idx, outcome_name in enumerate(outcome_names):
            try:
                # Calibration curve
                fraction_of_positives, mean_predicted_value = calibration_curve(
                    y_true_onehot[:, idx], y_pred_proba[:, idx], 
                    n_bins=10, strategy='uniform'
                )
                
                # Expected Calibration Error (ECE)
                bin_boundaries = np.linspace(0, 1, 11)
                bin_lowers = bin_boundaries[:-1]
                bin_uppers = bin_boundaries[1:]
                
                ece = 0.0
                mce = 0.0
                
                for bin_lower, bin_upper in zip(bin_lowers, bin_uppers):
                    in_bin = (y_pred_proba[:, idx] > bin_lower) & (y_pred_proba[:, idx] <= bin_upper)
                    prop_in_bin = in_bin.mean()
                    
                    if prop_in_bin > 0:
                        accuracy_in_bin = y_true_onehot[:, idx][in_bin].mean()
                        avg_confidence_in_bin = y_pred_proba[:, idx][in_bin].mean()
                        
                        ece += np.abs(avg_confidence_in_bin - accuracy_in_bin) * prop_in_bin
                        mce = max(mce, np.abs(avg_confidence_in_bin - accuracy_in_bin))
                
                calibration_results[outcome_name] = {
                    'ece': ece,
                    'mce': mce,
                    'calibration_curve': {
                        'fraction_positives': fraction_of_positives.tolist(),
                        'mean_predicted': mean_predicted_value.tolist()
                    }
                }
                
            except Exception as e:
                calibration_results[outcome_name] = {
                    'ece': np.nan,
                    'mce': np.nan,
                    'error': str(e)
                }
        
        # Overall calibration quality
        valid_eces = [
            cal['ece'] for cal in calibration_results.values() 
            if not np.isnan(cal.get('ece', np.nan))
        ]
        
        if valid_eces:
            avg_ece = np.mean(valid_eces)
            if avg_ece <= 0.05:
                quality = 'excellent'
            elif avg_ece <= 0.10:
                quality = 'good'
            elif avg_ece <= 0.15:
                quality = 'acceptable'
            else:
                quality = 'poor'
        else:
            quality = 'unknown'
        
        calibration_results['overall_quality'] = quality
        calibration_results['avg_ece'] = np.mean(valid_eces) if valid_eces else np.nan
        
        return calibration_results
    
    def compare_against_baselines(self, dataset: pd.DataFrame, 
                                model_predictions: Dict[str, np.ndarray]) -> Dict:
        """
        Compare models against baselines
        
        Args:
            dataset: Dataset with true outcomes
            model_predictions: Dict mapping model names to prediction arrays
            
        Returns:
            Comprehensive comparison results
        """
        
        print("Comparing models against baselines...")
        
        y_true = dataset['outcome'].values
        
        # Generate baseline predictions
        baselines = self._generate_baselines(dataset)
        
        # Combine all predictions
        all_predictions = {**baselines, **model_predictions}
        
        # Evaluate all models
        results = {}
        
        for model_name, y_pred_proba in all_predictions.items():
            print(f"Evaluating {model_name}...")
            
            try:
                model_results = self.evaluate_model(y_true, y_pred_proba)
                model_results['model_type'] = 'baseline' if model_name in baselines else 'model'
                results[model_name] = model_results
                
            except Exception as e:
                print(f"Error evaluating {model_name}: {e}")
                results[model_name] = {'error': str(e)}
        
        # Calculate improvements vs best baseline
        baseline_results = {k: v for k, v in results.items() if k in baselines}
        
        if baseline_results:
            best_baseline_logloss = min([
                r.get('logloss', float('inf')) 
                for r in baseline_results.values()
                if 'logloss' in r
            ])
            
            # Add improvement metrics
            for model_name, model_results in results.items():
                if model_name not in baselines and 'logloss' in model_results:
                    improvement = best_baseline_logloss - model_results['logloss']
                    model_results['logloss_improvement_vs_baseline'] = improvement
                    model_results['beats_baseline'] = improvement >= 0.005  # Target threshold
        
        return results
    
    def _generate_baselines(self, dataset: pd.DataFrame) -> Dict[str, np.ndarray]:
        """Generate baseline predictions"""
        
        baselines = {}
        n_samples = len(dataset)
        
        # Uniform baseline (equal probabilities)
        uniform_probs = np.full((n_samples, 3), 1/3)
        baselines['uniform'] = uniform_probs
        
        # Frequency baseline (global frequencies)
        outcome_counts = dataset['outcome'].value_counts()
        total_matches = len(dataset)
        
        freq_probs = np.zeros((n_samples, 3))
        freq_probs[:, 0] = outcome_counts.get('H', 0) / total_matches  # Home
        freq_probs[:, 1] = outcome_counts.get('D', 0) / total_matches  # Draw
        freq_probs[:, 2] = outcome_counts.get('A', 0) / total_matches  # Away
        
        baselines['frequency'] = freq_probs
        
        # League-specific frequency baseline
        league_freq_probs = np.zeros((n_samples, 3))
        
        for i, (_, match) in enumerate(dataset.iterrows()):
            league_id = match['league_id']
            league_matches = dataset[dataset['league_id'] == league_id]
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
    
    def evaluate_by_league(self, dataset: pd.DataFrame, 
                          model_predictions: Dict[str, np.ndarray]) -> Dict:
        """Evaluate models per league"""
        
        print("Evaluating by league...")
        
        league_results = {}
        
        for league_id in self.euro_leagues.keys():
            league_mask = dataset['league_id'] == league_id
            league_data = dataset[league_mask]
            
            if len(league_data) < 10:  # Minimum sample size
                continue
            
            league_name = self.euro_leagues[league_id]
            print(f"Evaluating {league_name} ({len(league_data)} matches)...")
            
            y_true_league = league_data['outcome'].values
            
            league_model_results = {}
            
            for model_name, y_pred_full in model_predictions.items():
                y_pred_league = y_pred_full[league_mask]
                
                try:
                    model_results = self.evaluate_model(y_true_league, y_pred_league)
                    league_model_results[model_name] = model_results
                except Exception as e:
                    league_model_results[model_name] = {'error': str(e)}
            
            league_results[league_id] = {
                'league_name': league_name,
                'n_matches': len(league_data),
                'models': league_model_results
            }
        
        return league_results
    
    def check_promotion_gates(self, results: Dict, min_samples: int = 300) -> Dict:
        """Check if models meet promotion criteria"""
        
        promotion_results = {}
        
        # Quality gates
        logloss_threshold = 0.005  # Must beat baseline by this amount
        brier_threshold = 0.205    # Must be below this
        top2_threshold = 0.95      # Must be above this
        
        for model_name, model_results in results.items():
            if model_results.get('model_type') == 'baseline':
                continue
            
            if 'error' in model_results:
                promotion_results[model_name] = {
                    'promotion_status': 'FAILED',
                    'reason': 'Evaluation error'
                }
                continue
            
            # Check criteria
            gates_passed = {}
            
            # Sample size
            n_samples = model_results.get('n_samples', 0)
            gates_passed['sample_size'] = n_samples >= min_samples
            
            # LogLoss improvement
            logloss_improvement = model_results.get('logloss_improvement_vs_baseline', 0)
            gates_passed['logloss_improvement'] = logloss_improvement >= logloss_threshold
            
            # Brier score
            brier_score = model_results.get('brier_score', float('inf'))
            gates_passed['brier_score'] = brier_score <= brier_threshold
            
            # Top-2 accuracy
            top2_accuracy = model_results.get('top2_accuracy', 0)
            gates_passed['top2_accuracy'] = top2_accuracy >= top2_threshold
            
            # Overall promotion decision
            all_passed = all(gates_passed.values())
            
            promotion_results[model_name] = {
                'promotion_status': 'APPROVED' if all_passed else 'REJECTED',
                'gates_passed': gates_passed,
                'metrics': {
                    'n_samples': n_samples,
                    'logloss_improvement': logloss_improvement,
                    'brier_score': brier_score,
                    'top2_accuracy': top2_accuracy
                },
                'thresholds': {
                    'min_samples': min_samples,
                    'logloss_threshold': logloss_threshold,
                    'brier_threshold': brier_threshold,
                    'top2_threshold': top2_threshold
                }
            }
        
        return promotion_results
    
    def generate_evaluation_report(self, results: Dict, 
                                 league_results: Dict = None,
                                 promotion_results: Dict = None,
                                 output_dir: str = 'reports/static') -> str:
        """Generate comprehensive evaluation report"""
        
        os.makedirs(output_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        report_path = f"{output_dir}/static_evaluation_report_{timestamp}.md"
        
        with open(report_path, 'w') as f:
            f.write("# Static Forecasting Evaluation Report\n\n")
            f.write(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            
            # Overall results
            f.write("## Overall Model Performance\n\n")
            f.write("| Model | LogLoss | Brier | RPS | Accuracy | Top-2 | Type |\n")
            f.write("|-------|---------|-------|-----|----------|-------|------|\n")
            
            for model_name, model_results in results.items():
                if 'error' in model_results:
                    continue
                
                model_type = model_results.get('model_type', 'model')
                logloss = model_results.get('logloss', 0)
                brier = model_results.get('brier_score', 0)
                rps = model_results.get('rps', 0)
                accuracy = model_results.get('accuracy', 0)
                top2 = model_results.get('top2_accuracy', 0)
                
                f.write(f"| {model_name} | {logloss:.4f} | {brier:.4f} | {rps:.4f} | {accuracy:.1%} | {top2:.1%} | {model_type} |\n")
            
            # Improvements vs baseline
            f.write("\n## Improvements vs Baseline\n\n")
            for model_name, model_results in results.items():
                if model_results.get('model_type') == 'baseline':
                    continue
                
                improvement = model_results.get('logloss_improvement_vs_baseline', 0)
                beats_baseline = model_results.get('beats_baseline', False)
                status = "✅ BEATS BASELINE" if beats_baseline else "❌ BELOW THRESHOLD"
                
                f.write(f"**{model_name}:** {improvement:+.4f} LogLoss improvement {status}\n\n")
            
            # Promotion gates
            if promotion_results:
                f.write("## Promotion Gate Results\n\n")
                for model_name, promo_results in promotion_results.items():
                    status = promo_results['promotion_status']
                    f.write(f"### {model_name}: {status}\n\n")
                    
                    gates = promo_results['gates_passed']
                    for gate_name, passed in gates.items():
                        status_icon = "✅" if passed else "❌"
                        f.write(f"- {gate_name}: {status_icon}\n")
                    
                    f.write("\n")
            
            # League-specific results
            if league_results:
                f.write("## League-Specific Performance\n\n")
                for league_id, league_data in league_results.items():
                    league_name = league_data['league_name']
                    n_matches = league_data['n_matches']
                    
                    f.write(f"### {league_name} ({n_matches} matches)\n\n")
                    f.write("| Model | LogLoss | Accuracy | Top-2 |\n")
                    f.write("|-------|---------|----------|-------|\n")
                    
                    for model_name, model_results in league_data['models'].items():
                        if 'error' in model_results:
                            continue
                        
                        logloss = model_results.get('logloss', 0)
                        accuracy = model_results.get('accuracy', 0)
                        top2 = model_results.get('top2_accuracy', 0)
                        
                        f.write(f"| {model_name} | {logloss:.4f} | {accuracy:.1%} | {top2:.1%} |\n")
                    
                    f.write("\n")
        
        print(f"Evaluation report saved: {report_path}")
        return report_path
    
    def save_results(self, results: Dict, output_path: str):
        """Save detailed results to JSON"""
        
        # Convert numpy types to native Python for JSON serialization
        def convert_numpy(obj):
            if isinstance(obj, np.ndarray):
                return obj.tolist()
            elif isinstance(obj, np.integer):
                return int(obj)
            elif isinstance(obj, np.floating):
                return float(obj)
            elif isinstance(obj, dict):
                return {k: convert_numpy(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [convert_numpy(item) for item in obj]
            else:
                return obj
        
        results_clean = convert_numpy(results)
        results_clean['generated_at'] = datetime.now().isoformat()
        
        with open(output_path, 'w') as f:
            json.dump(results_clean, f, indent=2, default=str)
        
        print(f"Detailed results saved: {output_path}")

def main():
    """Run static evaluation framework demo"""
    
    evaluator = StaticEvaluator()
    
    # Demo with synthetic data
    np.random.seed(42)
    n_samples = 1000
    
    # Create synthetic dataset
    dataset = pd.DataFrame({
        'outcome': np.random.choice(['H', 'D', 'A'], n_samples, p=[0.45, 0.25, 0.30]),
        'league_id': np.random.choice([39, 140, 135, 78, 61], n_samples)
    })
    
    # Create synthetic model predictions
    model_predictions = {
        'synthetic_model': np.random.dirichlet([2, 1, 1.5], n_samples)
    }
    
    # Run evaluation
    results = evaluator.compare_against_baselines(dataset, model_predictions)
    
    # Check promotion gates
    promotion_results = evaluator.check_promotion_gates(results)
    
    # Generate report
    os.makedirs('reports/static', exist_ok=True)
    report_path = evaluator.generate_evaluation_report(
        results, promotion_results=promotion_results
    )
    
    # Save detailed results
    evaluator.save_results(results, 'reports/static/evaluation_results.json')
    
    print("Static evaluation framework demo complete!")
    
    return results

if __name__ == "__main__":
    main()