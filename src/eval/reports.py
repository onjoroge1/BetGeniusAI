"""
Evaluation Reports - Calibration analysis and model diagnostics
"""

import numpy as np
import pandas as pd
from sklearn.calibration import calibration_curve
from sklearn.metrics import brier_score_loss
import psycopg2
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import json
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
import matplotlib.pyplot as plt
import warnings
warnings.filterwarnings('ignore')

class CalibrationReporter:
    """Generate calibration reports and reliability analysis"""
    
    def __init__(self):
        self.euro_leagues = {
            39: 'English Premier League',
            140: 'La Liga Santander', 
            135: 'Serie A',
            78: 'Bundesliga',
            61: 'Ligue 1'
        }
    
    def get_db_connection(self):
        """Get database connection"""
        return psycopg2.connect(os.environ['DATABASE_URL'])
    
    def load_calibration_data(self, start_date: str = None, 
                            end_date: str = None) -> pd.DataFrame:
        """Load data for calibration analysis"""
        
        if start_date is None:
            start_date = (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d')
        if end_date is None:
            end_date = datetime.now().strftime('%Y-%m-%d')
        
        conn = self.get_db_connection()
        
        query = """
        SELECT 
            cp.match_id,
            cp.time_bucket,
            cp.consensus_h,
            cp.consensus_d,
            cp.consensus_a,
            cp.dispersion_h,
            cp.dispersion_d,
            cp.dispersion_a,
            m.league_id,
            m.match_date_utc,
            m.outcome
        FROM consensus_predictions cp
        JOIN matches m ON cp.match_id = m.match_id
        WHERE m.match_date_utc >= %s
          AND m.match_date_utc <= %s
          AND m.outcome IS NOT NULL
          AND m.league_id IN (39, 140, 135, 78, 61)
          AND cp.time_bucket = '24h'
        ORDER BY m.match_date_utc ASC
        """
        
        df = pd.read_sql_query(query, conn, params=[start_date, end_date])
        conn.close()
        
        return df
    
    def calculate_calibration_metrics(self, y_true: np.ndarray, 
                                    y_prob: np.ndarray, n_bins: int = 10) -> Dict:
        """Calculate calibration metrics for binary outcome"""
        
        try:
            # Calibration curve
            fraction_of_positives, mean_predicted_value = calibration_curve(
                y_true, y_prob, n_bins=n_bins, strategy='uniform'
            )
            
            # Expected Calibration Error (ECE)
            bin_boundaries = np.linspace(0, 1, n_bins + 1)
            bin_lowers = bin_boundaries[:-1]
            bin_uppers = bin_boundaries[1:]
            
            ece = 0.0
            mce = 0.0
            
            for bin_lower, bin_upper in zip(bin_lowers, bin_uppers):
                in_bin = (y_prob > bin_lower) & (y_prob <= bin_upper)
                prop_in_bin = in_bin.mean()
                
                if prop_in_bin > 0:
                    accuracy_in_bin = y_true[in_bin].mean()
                    avg_confidence_in_bin = y_prob[in_bin].mean()
                    
                    ece += np.abs(avg_confidence_in_bin - accuracy_in_bin) * prop_in_bin
                    mce = max(mce, np.abs(avg_confidence_in_bin - accuracy_in_bin))
            
            # Brier score
            brier = brier_score_loss(y_true, y_prob)
            
            # Reliability (calibration) and resolution components
            reliability = np.mean((mean_predicted_value - fraction_of_positives) ** 2)
            resolution = np.mean((fraction_of_positives - np.mean(y_true)) ** 2)
            
            return {
                'ece': float(ece),
                'mce': float(mce),
                'brier_score': float(brier),
                'reliability': float(reliability),
                'resolution': float(resolution),
                'n_samples': len(y_true),
                'calibration_curve': {
                    'fraction_positives': fraction_of_positives.tolist(),
                    'mean_predicted': mean_predicted_value.tolist()
                }
            }
            
        except Exception as e:
            return {
                'error': str(e),
                'n_samples': len(y_true)
            }
    
    def generate_calibration_report(self, data_df: pd.DataFrame) -> Dict:
        """Generate comprehensive calibration report"""
        
        if len(data_df) == 0:
            return {'error': 'No calibration data available'}
        
        print(f"🔧 Analyzing calibration for {len(data_df)} predictions")
        
        # Prepare outcome labels
        data_df = data_df.copy()
        data_df['outcome_h'] = (data_df['outcome'] == 'H').astype(int)
        data_df['outcome_d'] = (data_df['outcome'] == 'D').astype(int)
        data_df['outcome_a'] = (data_df['outcome'] == 'A').astype(int)
        
        calibration_results = {}
        
        # Overall calibration analysis
        overall_results = {}
        
        for outcome_name, prob_col, outcome_col in [
            ('home', 'consensus_h', 'outcome_h'),
            ('draw', 'consensus_d', 'outcome_d'),
            ('away', 'consensus_a', 'outcome_a')
        ]:
            y_true = data_df[outcome_col].values
            y_prob = data_df[prob_col].values
            
            # Remove any invalid probabilities
            valid_mask = (~np.isnan(y_prob)) & (y_prob >= 0) & (y_prob <= 1)
            if valid_mask.sum() == 0:
                continue
            
            y_true_clean = y_true[valid_mask]
            y_prob_clean = y_prob[valid_mask]
            
            metrics = self.calculate_calibration_metrics(y_true_clean, y_prob_clean)
            overall_results[outcome_name] = metrics
        
        calibration_results['overall'] = overall_results
        
        # Per-league calibration analysis
        league_results = {}
        
        for league_id in self.euro_leagues.keys():
            league_data = data_df[data_df['league_id'] == league_id]
            
            if len(league_data) < 20:  # Minimum sample size
                continue
            
            league_name = self.euro_leagues[league_id]
            league_calibration = {}
            
            for outcome_name, prob_col, outcome_col in [
                ('home', 'consensus_h', 'outcome_h'),
                ('draw', 'consensus_d', 'outcome_d'),
                ('away', 'consensus_a', 'outcome_a')
            ]:
                y_true = league_data[outcome_col].values
                y_prob = league_data[prob_col].values
                
                valid_mask = (~np.isnan(y_prob)) & (y_prob >= 0) & (y_prob <= 1)
                if valid_mask.sum() < 10:
                    continue
                
                y_true_clean = y_true[valid_mask]
                y_prob_clean = y_prob[valid_mask]
                
                metrics = self.calculate_calibration_metrics(y_true_clean, y_prob_clean)
                league_calibration[outcome_name] = metrics
            
            if league_calibration:
                league_results[league_id] = {
                    'league_name': league_name,
                    'outcomes': league_calibration,
                    'total_matches': len(league_data)
                }
        
        calibration_results['by_league'] = league_results
        
        # Summary statistics
        summary = self._calculate_calibration_summary(calibration_results)
        calibration_results['summary'] = summary
        
        return calibration_results
    
    def _calculate_calibration_summary(self, calibration_results: Dict) -> Dict:
        """Calculate summary calibration statistics"""
        
        overall = calibration_results.get('overall', {})
        by_league = calibration_results.get('by_league', {})
        
        summary = {
            'total_leagues_analyzed': len(by_league),
            'overall_metrics': {},
            'league_averages': {},
            'calibration_quality': 'unknown'
        }
        
        # Overall metrics summary
        if overall:
            avg_ece = np.mean([
                metrics.get('ece', np.nan) 
                for metrics in overall.values() 
                if 'ece' in metrics
            ])
            
            avg_mce = np.mean([
                metrics.get('mce', np.nan) 
                for metrics in overall.values() 
                if 'mce' in metrics
            ])
            
            avg_brier = np.mean([
                metrics.get('brier_score', np.nan) 
                for metrics in overall.values() 
                if 'brier_score' in metrics
            ])
            
            summary['overall_metrics'] = {
                'avg_ece': float(avg_ece) if not np.isnan(avg_ece) else None,
                'avg_mce': float(avg_mce) if not np.isnan(avg_mce) else None,
                'avg_brier': float(avg_brier) if not np.isnan(avg_brier) else None
            }
        
        # League averages
        if by_league:
            league_eces = []
            league_mces = []
            league_briers = []
            
            for league_data in by_league.values():
                outcomes = league_data.get('outcomes', {})
                for outcome_metrics in outcomes.values():
                    if 'ece' in outcome_metrics:
                        league_eces.append(outcome_metrics['ece'])
                    if 'mce' in outcome_metrics:
                        league_mces.append(outcome_metrics['mce'])
                    if 'brier_score' in outcome_metrics:
                        league_briers.append(outcome_metrics['brier_score'])
            
            if league_eces:
                summary['league_averages'] = {
                    'avg_ece': float(np.mean(league_eces)),
                    'avg_mce': float(np.mean(league_mces)) if league_mces else None,
                    'avg_brier': float(np.mean(league_briers)) if league_briers else None,
                    'ece_std': float(np.std(league_eces))
                }
                
                # Calibration quality assessment
                avg_ece = np.mean(league_eces)
                if avg_ece <= 0.05:
                    summary['calibration_quality'] = 'excellent'
                elif avg_ece <= 0.10:
                    summary['calibration_quality'] = 'good'
                elif avg_ece <= 0.15:
                    summary['calibration_quality'] = 'acceptable'
                else:
                    summary['calibration_quality'] = 'poor'
        
        return summary
    
    def save_calibration_report(self, calibration_data: Dict, 
                              output_path: str):
        """Save calibration report to JSON"""
        
        # Add metadata
        report = {
            'calibration_analysis': calibration_data,
            'generated_at': datetime.now().isoformat(),
            'euro_leagues': self.euro_leagues,
            'analysis_type': 'consensus_calibration'
        }
        
        with open(output_path, 'w') as f:
            json.dump(report, f, indent=2, default=str)
        
        print(f"✅ Calibration report saved: {output_path}")
    
    def print_calibration_summary(self, calibration_data: Dict):
        """Print calibration summary to console"""
        
        summary = calibration_data.get('summary', {})
        overall = calibration_data.get('overall', {})
        
        print("\n" + "="*60)
        print("CALIBRATION ANALYSIS SUMMARY")
        print("="*60)
        
        # Overall quality
        quality = summary.get('calibration_quality', 'unknown')
        quality_status = {
            'excellent': '✅ EXCELLENT',
            'good': '✅ GOOD', 
            'acceptable': '⚠️ ACCEPTABLE',
            'poor': '❌ POOR',
            'unknown': '❓ UNKNOWN'
        }
        
        print(f"Overall Calibration Quality: {quality_status.get(quality, quality)}")
        
        # Metrics
        overall_metrics = summary.get('overall_metrics', {})
        if overall_metrics:
            print(f"Average ECE: {overall_metrics.get('avg_ece', 'N/A'):.4f}")
            print(f"Average MCE: {overall_metrics.get('avg_mce', 'N/A'):.4f}")
            print(f"Average Brier: {overall_metrics.get('avg_brier', 'N/A'):.4f}")
        
        # Per-outcome breakdown
        if overall:
            print("\nPer-Outcome Calibration:")
            for outcome, metrics in overall.items():
                if 'ece' in metrics:
                    print(f"  {outcome.upper()}: ECE={metrics['ece']:.4f}, "
                          f"Brier={metrics['brier_score']:.4f}, "
                          f"n={metrics['n_samples']}")
        
        print(f"\nLeagues Analyzed: {summary.get('total_leagues_analyzed', 0)}")

def main():
    """Generate calibration report"""
    
    reporter = CalibrationReporter()
    
    # Load calibration data
    print("📊 Loading calibration data...")
    data_df = reporter.load_calibration_data()
    
    if len(data_df) == 0:
        print("❌ No calibration data available")
        return
    
    # Generate calibration analysis
    calibration_data = reporter.generate_calibration_report(data_df)
    
    if 'error' in calibration_data:
        print(f"❌ Calibration analysis failed: {calibration_data['error']}")
        return
    
    # Create reports directory
    os.makedirs('reports', exist_ok=True)
    
    # Save report
    output_path = 'reports/CALIBRATION_STATS.json'
    reporter.save_calibration_report(calibration_data, output_path)
    
    # Print summary
    reporter.print_calibration_summary(calibration_data)
    
    print(f"\n✅ Calibration analysis complete!")
    print(f"📊 Report: {output_path}")
    
    return calibration_data

if __name__ == "__main__":
    main()