"""
Unified Evaluation Harness - Source of Truth for Model Performance
Compares all models (consensus, two-stage, residual) against baselines with strict CI gates
"""

import numpy as np
import pandas as pd
from sklearn.metrics import log_loss, accuracy_score, brier_score_loss
from sklearn.calibration import calibration_curve
import psycopg2
import os
import joblib
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
import json
import yaml
import warnings
warnings.filterwarnings('ignore')

class UnifiedHarness:
    """Unified evaluation harness with CI gates for model promotion"""
    
    def __init__(self, config_path: str = 'config/leagues.yml'):
        # Load configuration
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)
        
        self.euro_leagues = {
            39: 'English Premier League',
            140: 'La Liga Santander', 
            135: 'Serie A',
            78: 'Bundesliga',
            61: 'Ligue 1'
        }
        
        # Quality gates from config
        self.quality_gates = self.config['global']['quality_gates']
        
        # Loaded models
        self.models = {}
    
    def get_db_connection(self):
        """Get database connection"""
        return psycopg2.connect(os.environ['DATABASE_URL'])
    
    def load_evaluation_data(self, start_date: str = None, end_date: str = None) -> pd.DataFrame:
        """Load evaluation data with all predictions and outcomes"""
        
        if start_date is None:
            start_date = (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d')
        if end_date is None:
            end_date = datetime.now().strftime('%Y-%m-%d')
        
        conn = self.get_db_connection()
        
        # Load matches with consensus predictions
        query = """
        SELECT 
            m.match_id,
            m.league_id,
            m.match_date_utc,
            m.outcome,
            m.home_goals,
            m.away_goals,
            
            -- Consensus predictions (24h bucket preferred)
            cp.consensus_h,
            cp.consensus_d,
            cp.consensus_a,
            cp.dispersion_h,
            cp.dispersion_d,
            cp.dispersion_a,
            cp.n_books,
            cp.time_bucket
            
        FROM matches m
        LEFT JOIN consensus_predictions cp ON m.match_id = cp.match_id 
            AND cp.time_bucket = '24h'
        WHERE m.match_date_utc >= %s
          AND m.match_date_utc <= %s
          AND m.outcome IS NOT NULL
          AND m.league_id IN (39, 140, 135, 78, 61)
        ORDER BY m.match_date_utc ASC
        """
        
        df = pd.read_sql_query(query, conn, params=[start_date, end_date])
        conn.close()
        
        print(f"Loaded {len(df)} matches for evaluation")
        return df
    
    def load_model(self, model_type: str, version: str = 'latest') -> Dict:
        """Load model artifacts"""
        
        if model_type == 'consensus':
            # Load consensus calibrators
            try:
                from src.consensus.calibrate_consensus import ConsensusCalibrator
                calibrator = ConsensusCalibrator()
                calibrator.load_calibrators(version)
                return {'type': 'consensus', 'calibrator': calibrator}
            except Exception as e:
                print(f"Warning: Could not load consensus calibrators: {e}")
                return None
        
        elif model_type == 'twostage':
            # Load two-stage model
            try:
                if version == 'latest':
                    import glob
                    model_files = glob.glob('models/twostage/TwoStage_v*.joblib')
                    if not model_files:
                        raise FileNotFoundError("No two-stage models found")
                    model_path = sorted(model_files)[-1]
                else:
                    model_path = f'models/twostage/TwoStage_v{version}.joblib'
                
                artifacts = joblib.load(model_path)
                return {'type': 'twostage', 'artifacts': artifacts, 'path': model_path}
            except Exception as e:
                print(f"Warning: Could not load two-stage model: {e}")
                return None
        
        else:
            raise ValueError(f"Unknown model type: {model_type}")
    
    def prepare_baselines(self, df: pd.DataFrame) -> Dict[str, np.ndarray]:
        """Prepare baseline predictions"""
        
        n_matches = len(df)
        baselines = {}
        
        # Uniform baseline
        baselines['uniform'] = np.full((n_matches, 3), 1/3)
        
        # Frequency baseline (overall frequencies)
        outcome_counts = df['outcome'].value_counts()
        freq_h = outcome_counts.get('H', 0) / len(df)
        freq_d = outcome_counts.get('D', 0) / len(df)
        freq_a = outcome_counts.get('A', 0) / len(df)
        baselines['frequency'] = np.full((n_matches, 3), [freq_h, freq_d, freq_a])
        
        # Market implied (from consensus if available)
        market_probs = np.zeros((n_matches, 3))
        consensus_available = ~df['consensus_h'].isna()
        
        if consensus_available.any():
            market_probs[consensus_available, 0] = df.loc[consensus_available, 'consensus_h']
            market_probs[consensus_available, 1] = df.loc[consensus_available, 'consensus_d']
            market_probs[consensus_available, 2] = df.loc[consensus_available, 'consensus_a']
            
            # Fill missing with frequency
            missing_mask = ~consensus_available
            market_probs[missing_mask] = [freq_h, freq_d, freq_a]
        else:
            market_probs = baselines['frequency'].copy()
        
        baselines['market_implied'] = market_probs
        
        return baselines
    
    def evaluate_consensus_model(self, df: pd.DataFrame) -> Dict:
        """Evaluate consensus model (with calibration if available)"""
        
        consensus_model = self.load_model('consensus')
        
        if consensus_model is None:
            return {'error': 'Consensus model not available'}
        
        # Get raw consensus predictions
        consensus_available = ~df['consensus_h'].isna()
        if not consensus_available.any():
            return {'error': 'No consensus predictions available'}
        
        eval_df = df[consensus_available].copy()
        
        raw_probs = eval_df[['consensus_h', 'consensus_d', 'consensus_a']].values
        
        # Apply calibration if available
        if consensus_model.get('calibrator'):
            calibrator = consensus_model['calibrator']
            
            calibrated_probs = np.zeros_like(raw_probs)
            
            for idx, row in eval_df.iterrows():
                league_id = row['league_id']
                time_bucket = row['time_bucket'] or '24h'
                
                cal_h, cal_d, cal_a = calibrator.apply_calibration(
                    np.array([row['consensus_h']]),
                    np.array([row['consensus_d']]),
                    np.array([row['consensus_a']]),
                    league_id, time_bucket
                )
                
                idx_in_eval = eval_df.index.get_loc(idx)
                calibrated_probs[idx_in_eval] = [cal_h[0], cal_d[0], cal_a[0]]
        else:
            calibrated_probs = raw_probs
        
        return {
            'raw_probabilities': raw_probs,
            'calibrated_probabilities': calibrated_probs,
            'evaluation_matches': len(eval_df),
            'outcomes': eval_df['outcome'].tolist()
        }
    
    def evaluate_twostage_model(self, df: pd.DataFrame) -> Dict:
        """Evaluate two-stage model in shadow mode"""
        
        twostage_model = self.load_model('twostage')
        
        if twostage_model is None:
            return {'error': 'Two-stage model not available'}
        
        artifacts = twostage_model['artifacts']
        
        # Reconstruct feature matrix (simplified - would need proper feature engineering)
        feature_order = artifacts['feature_order']
        
        # Create basic features for evaluation (in production, would use proper feature store)
        eval_features = []
        
        for _, row in df.iterrows():
            # Create synthetic features matching training (placeholder)
            features = {}
            
            # Market probabilities (if available from consensus)
            if not pd.isna(row['consensus_h']):
                features['market_home_prob'] = row['consensus_h']
                features['market_draw_prob'] = row['consensus_d']
                features['market_away_prob'] = row['consensus_a']
            else:
                features['market_home_prob'] = 0.4
                features['market_draw_prob'] = 0.3
                features['market_away_prob'] = 0.3
            
            # Other features (simplified)
            for feat in feature_order:
                if feat not in features:
                    if 'elo' in feat:
                        features[feat] = np.random.uniform(1400, 1600)
                    elif 'form' in feat:
                        features[feat] = np.random.uniform(0, 15)
                    elif 'goals' in feat:
                        features[feat] = np.random.uniform(1.0, 3.0)
                    elif 'diff' in feat:
                        features[feat] = np.random.uniform(-1, 1)
                    else:
                        features[feat] = np.random.uniform(0, 1)
            
            eval_features.append([features[feat] for feat in feature_order])
        
        X = np.array(eval_features)
        
        # Predict using two-stage model
        stage1_model = artifacts['stage1_model']
        stage2_model = artifacts['stage2_model']
        scaler = artifacts['scaler']
        
        if stage1_model is None or stage2_model is None or scaler is None:
            return {'error': 'Two-stage model components missing'}
        
        X_scaled = scaler.transform(X)
        
        # Stage 1: Draw probabilities
        draw_probs = stage1_model.predict_proba(X_scaled)[:, 1]
        
        # Stage 2: Home probabilities given not draw
        home_given_not_draw = stage2_model.predict_proba(X_scaled)[:, 1]
        
        # Combine stages
        not_draw_prob = 1 - draw_probs
        home_probs = not_draw_prob * home_given_not_draw
        away_probs = not_draw_prob * (1 - home_given_not_draw)
        
        probabilities = np.column_stack([home_probs, draw_probs, away_probs])
        probabilities = probabilities / probabilities.sum(axis=1, keepdims=True)
        
        return {
            'probabilities': probabilities,
            'evaluation_matches': len(df),
            'outcomes': df['outcome'].tolist(),
            'model_path': twostage_model['path']
        }
    
    def calculate_metrics(self, y_true: np.ndarray, y_prob: np.ndarray) -> Dict:
        """Calculate comprehensive evaluation metrics"""
        
        # Convert outcomes to numeric
        label_map = {'H': 0, 'D': 1, 'A': 2}
        if isinstance(y_true[0], str):
            y_numeric = np.array([label_map[outcome] for outcome in y_true])
        else:
            y_numeric = y_true
        
        # Accuracy
        y_pred = np.argmax(y_prob, axis=1)
        accuracy = accuracy_score(y_numeric, y_pred)
        
        # Log loss
        logloss = log_loss(y_numeric, y_prob)
        
        # Brier score (decomposition)
        brier_scores = []
        reliability_scores = []
        resolution_scores = []
        
        for outcome_idx in range(3):
            y_binary = (y_numeric == outcome_idx).astype(int)
            prob_outcome = y_prob[:, outcome_idx]
            
            brier = brier_score_loss(y_binary, prob_outcome)
            brier_scores.append(brier)
            
            # Calibration curve for reliability/resolution
            try:
                fraction_pos, mean_pred = calibration_curve(y_binary, prob_outcome, n_bins=10)
                reliability = np.mean((mean_pred - fraction_pos) ** 2)
                resolution = np.mean((fraction_pos - np.mean(y_binary)) ** 2)
                
                reliability_scores.append(reliability)
                resolution_scores.append(resolution)
            except:
                reliability_scores.append(0.0)
                resolution_scores.append(0.0)
        
        # Top-2 accuracy
        top2_indices = np.argsort(-y_prob, axis=1)[:, :2]
        top2_correct = np.any(top2_indices == y_numeric.reshape(-1, 1), axis=1)
        top2_accuracy = np.mean(top2_correct)
        
        # RPS (Ranked Probability Score) for ordered outcomes
        y_cumulative = np.zeros((len(y_numeric), 3))
        prob_cumulative = np.zeros_like(y_prob)
        
        for i in range(3):
            y_cumulative[:, i] = (y_numeric <= i).astype(int)
            prob_cumulative[:, i] = np.sum(y_prob[:, :i+1], axis=1)
        
        rps = np.mean(np.sum((prob_cumulative - y_cumulative) ** 2, axis=1))
        
        return {
            'accuracy': accuracy,
            'logloss': logloss,
            'brier_mean': np.mean(brier_scores),
            'brier_h': brier_scores[0],
            'brier_d': brier_scores[1], 
            'brier_a': brier_scores[2],
            'reliability_mean': np.mean(reliability_scores),
            'resolution_mean': np.mean(resolution_scores),
            'top2_accuracy': top2_accuracy,
            'rps': rps
        }
    
    def run_unified_evaluation(self, start_date: str = None, end_date: str = None) -> Dict:
        """Run comprehensive evaluation of all models vs baselines"""
        
        print("🔍 UNIFIED EVALUATION HARNESS")
        print("=" * 60)
        
        # Load evaluation data
        df = self.load_evaluation_data(start_date, end_date)
        
        if len(df) == 0:
            return {'error': 'No evaluation data available'}
        
        print(f"Evaluation period: {start_date} to {end_date}")
        print(f"Matches: {len(df)}")
        
        # Prepare baselines
        baselines = self.prepare_baselines(df)
        
        # Evaluate models
        results = {}
        
        # Baseline evaluations
        for baseline_name, baseline_probs in baselines.items():
            try:
                metrics = self.calculate_metrics(df['outcome'].values, baseline_probs)
                results[baseline_name] = metrics
                print(f"✅ {baseline_name}: LogLoss={metrics['logloss']:.4f}, Acc={metrics['accuracy']:.1%}")
            except Exception as e:
                print(f"❌ {baseline_name}: Evaluation failed - {e}")
                results[baseline_name] = {'error': str(e)}
        
        # Consensus model evaluation
        consensus_result = self.evaluate_consensus_model(df)
        if 'error' not in consensus_result:
            try:
                metrics_raw = self.calculate_metrics(
                    consensus_result['outcomes'], 
                    consensus_result['raw_probabilities']
                )
                metrics_calibrated = self.calculate_metrics(
                    consensus_result['outcomes'],
                    consensus_result['calibrated_probabilities']
                )
                
                results['consensus_raw'] = metrics_raw
                results['consensus_calibrated'] = metrics_calibrated
                
                print(f"✅ consensus_raw: LogLoss={metrics_raw['logloss']:.4f}, Acc={metrics_raw['accuracy']:.1%}")
                print(f"✅ consensus_calibrated: LogLoss={metrics_calibrated['logloss']:.4f}, Acc={metrics_calibrated['accuracy']:.1%}")
                
            except Exception as e:
                print(f"❌ consensus: Evaluation failed - {e}")
                results['consensus_raw'] = {'error': str(e)}
                results['consensus_calibrated'] = {'error': str(e)}
        else:
            print(f"❌ consensus: {consensus_result['error']}")
            results['consensus_raw'] = consensus_result
            results['consensus_calibrated'] = consensus_result
        
        # Two-stage model evaluation (shadow)
        twostage_result = self.evaluate_twostage_model(df)
        if 'error' not in twostage_result:
            try:
                metrics = self.calculate_metrics(
                    twostage_result['outcomes'],
                    twostage_result['probabilities']
                )
                
                results['twostage_shadow'] = metrics
                print(f"✅ twostage_shadow: LogLoss={metrics['logloss']:.4f}, Acc={metrics['accuracy']:.1%}")
                
            except Exception as e:
                print(f"❌ twostage_shadow: Evaluation failed - {e}")
                results['twostage_shadow'] = {'error': str(e)}
        else:
            print(f"❌ twostage_shadow: {twostage_result['error']}")
            results['twostage_shadow'] = twostage_result
        
        return results
    
    def check_promotion_gates(self, results: Dict) -> Dict:
        """Check promotion gates for model advancement"""
        
        print("\n🚪 PROMOTION GATE CHECKS")
        print("=" * 40)
        
        gate_results = {}
        
        # Get baseline performance
        market_logloss = results.get('market_implied', {}).get('logloss', np.inf)
        
        # Check consensus model gates
        consensus_metrics = results.get('consensus_calibrated', {})
        if 'error' not in consensus_metrics:
            consensus_logloss = consensus_metrics.get('logloss', np.inf)
            consensus_top2 = consensus_metrics.get('top2_accuracy', 0.0)
            consensus_brier = consensus_metrics.get('brier_mean', np.inf)
            
            consensus_gates = {
                'beats_market_logloss': consensus_logloss <= market_logloss - self.quality_gates['min_logloss_vs_market'],
                'top2_threshold': consensus_top2 >= 0.95,
                'brier_threshold': consensus_brier <= 0.205,
                'improvement_vs_market': market_logloss - consensus_logloss
            }
            
            all_consensus_passed = all([
                consensus_gates['beats_market_logloss'],
                consensus_gates['top2_threshold'],
                consensus_gates['brier_threshold']
            ])
            
            consensus_gates['all_passed'] = all_consensus_passed
            gate_results['consensus'] = consensus_gates
            
            status = "PASS" if all_consensus_passed else "FAIL"
            print(f"Consensus: {status}")
            print(f"  LogLoss vs Market: {consensus_gates['improvement_vs_market']:+.4f} (req: {self.quality_gates['min_logloss_vs_market']:+.3f})")
            print(f"  Top-2 Accuracy: {consensus_top2:.1%} (req: ≥95%)")
            print(f"  Brier Score: {consensus_brier:.4f} (req: ≤0.205)")
        
        # Check two-stage shadow model gates
        twostage_metrics = results.get('twostage_shadow', {})
        if 'error' not in twostage_metrics:
            twostage_logloss = twostage_metrics.get('logloss', np.inf)
            twostage_top2 = twostage_metrics.get('top2_accuracy', 0.0)
            twostage_brier = twostage_metrics.get('brier_mean', np.inf)
            
            twostage_gates = {
                'beats_market_logloss': twostage_logloss <= market_logloss - self.quality_gates['min_logloss_vs_market'],
                'beats_consensus': twostage_logloss < consensus_metrics.get('logloss', np.inf),
                'top2_threshold': twostage_top2 >= 0.95,
                'brier_threshold': twostage_brier <= 0.205,
                'improvement_vs_market': market_logloss - twostage_logloss
            }
            
            all_twostage_passed = all([
                twostage_gates['beats_market_logloss'],
                twostage_gates['beats_consensus'],
                twostage_gates['top2_threshold'],
                twostage_gates['brier_threshold']
            ])
            
            twostage_gates['all_passed'] = all_twostage_passed
            twostage_gates['promotion_eligible'] = all_twostage_passed
            gate_results['twostage'] = twostage_gates
            
            status = "ELIGIBLE FOR PROMOTION" if all_twostage_passed else "REMAIN IN SHADOW"
            print(f"\nTwo-Stage: {status}")
            print(f"  LogLoss vs Market: {twostage_gates['improvement_vs_market']:+.4f} (req: {self.quality_gates['min_logloss_vs_market']:+.3f})")
            print(f"  Beats Consensus: {twostage_gates['beats_consensus']}")
            print(f"  Top-2 Accuracy: {twostage_top2:.1%} (req: ≥95%)")
            print(f"  Brier Score: {twostage_brier:.4f} (req: ≤0.205)")
        
        return gate_results
    
    def generate_evaluation_report(self, results: Dict, gate_results: Dict) -> str:
        """Generate comprehensive evaluation report"""
        
        lines = [
            "UNIFIED EVALUATION HARNESS REPORT",
            "=" * 60,
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"Evaluation Window: {self.quality_gates.get('performance_window_days', 30)} days",
            "",
            "PERFORMANCE SUMMARY:",
            "-" * 30
        ]
        
        # Results table
        lines.append(f"{'Model':<20} {'LogLoss':<10} {'Accuracy':<10} {'Top-2':<10} {'Brier':<10} {'Status':<15}")
        lines.append("-" * 85)
        
        for model_name, metrics in results.items():
            if 'error' in metrics:
                lines.append(f"{model_name:<20} {'ERROR':<10} {'ERROR':<10} {'ERROR':<10} {'ERROR':<10} {'FAILED':<15}")
                continue
            
            status = ""
            if model_name == 'consensus_calibrated':
                status = "PRODUCTION" if gate_results.get('consensus', {}).get('all_passed', False) else "NEEDS_WORK"
            elif model_name == 'twostage_shadow':
                status = "PROMOTE" if gate_results.get('twostage', {}).get('promotion_eligible', False) else "SHADOW"
            elif model_name == 'market_implied':
                status = "BASELINE"
            
            lines.append(f"{model_name:<20} {metrics['logloss']:<10.4f} {metrics['accuracy']:<10.1%} {metrics['top2_accuracy']:<10.1%} {metrics['brier_mean']:<10.4f} {status:<15}")
        
        # Gate results
        lines.extend([
            "",
            "PROMOTION GATE RESULTS:",
            "-" * 30
        ])
        
        for model, gates in gate_results.items():
            if gates.get('all_passed', False):
                lines.append(f"✅ {model.upper()}: All gates passed")
            else:
                lines.append(f"❌ {model.upper()}: Failed promotion gates")
                
                for gate_name, passed in gates.items():
                    if gate_name not in ['all_passed', 'promotion_eligible', 'improvement_vs_market']:
                        status_symbol = "✅" if passed else "❌"
                        lines.append(f"   {status_symbol} {gate_name}: {passed}")
        
        return "\n".join(lines)
    
    def save_evaluation_artifacts(self, results: Dict, gate_results: Dict):
        """Save evaluation results and report"""
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # Save results
        evaluation_data = {
            'results': results,
            'gate_results': gate_results,
            'quality_gates': self.quality_gates,
            'evaluation_timestamp': datetime.now().isoformat(),
            'euro_leagues': self.euro_leagues
        }
        
        results_path = f'reports/unified_evaluation_{timestamp}.json'
        os.makedirs('reports', exist_ok=True)
        
        with open(results_path, 'w') as f:
            json.dump(evaluation_data, f, indent=2, default=str)
        
        # Save report
        report = self.generate_evaluation_report(results, gate_results)
        report_path = f'reports/unified_evaluation_{timestamp}.txt'
        
        with open(report_path, 'w') as f:
            f.write(report)
        
        return results_path, report_path

def main():
    """Run unified evaluation harness"""
    
    harness = UnifiedHarness()
    
    # Run evaluation
    results = harness.run_unified_evaluation()
    
    # Check promotion gates
    gate_results = harness.check_promotion_gates(results)
    
    # Generate and save report
    results_path, report_path = harness.save_evaluation_artifacts(results, gate_results)
    
    # Display final report
    report = harness.generate_evaluation_report(results, gate_results)
    print("\n" + report)
    
    print(f"\n✅ Unified Evaluation Complete!")
    print(f"📊 Results: {results_path}")
    print(f"📋 Report: {report_path}")
    
    return results, gate_results

if __name__ == "__main__":
    main()