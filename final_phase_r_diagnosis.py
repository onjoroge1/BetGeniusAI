"""
Final Phase R Diagnosis: Reconciling All BetGenius AI Metrics
Address all red flags and provide definitive performance assessment
"""

import numpy as np
import pandas as pd
import json
from typing import Dict, List, Any
from datetime import datetime

class FinalPhaseRDiagnosis:
    """Final diagnosis to reconcile all performance metrics"""
    
    def __init__(self):
        self.reported_metrics = {
            'logloss': 0.963475,
            'brier_score_raw': 0.572791,
            'accuracy_3way': 0.543,
            'accuracy_2way': 0.624,
            'market_advantage_logloss': 0.008663,
            'sample_size': 1500
        }
    
    def diagnose_brier_score_issue(self) -> Dict[str, Any]:
        """Diagnose the Brier score normalization issue"""
        
        reported_brier = self.reported_metrics['brier_score_raw']
        
        # For 3-way classification, proper Brier score should be normalized
        # Brier = mean over samples of sum_k (p_k - y_k)^2 / K
        # where K = number of classes (3 for Home/Draw/Away)
        
        corrected_brier = reported_brier / 3
        
        diagnosis = {
            'issue_identified': 'Brier score not normalized by number of classes',
            'reported_value': reported_brier,
            'corrected_value': corrected_brier,
            'explanation': f'Reported {reported_brier:.6f} should be {corrected_brier:.6f} (÷3 for 3-way classification)',
            'consistency_check': {
                'logloss_vs_brier': 'LogLoss ~0.96 is consistent with normalized Brier ~0.19',
                'reasonable_range': f'Corrected Brier {corrected_brier:.3f} is in reasonable range [0.15-0.25]',
                'severity': 'CRITICAL - affects model rating calculation'
            }
        }
        
        return diagnosis
    
    def validate_accuracy_metrics(self) -> Dict[str, Any]:
        """Validate 3-way and 2-way accuracy calculations"""
        
        acc_3way = self.reported_metrics['accuracy_3way']
        acc_2way = self.reported_metrics['accuracy_2way']
        
        validation = {
            'accuracy_3way': {
                'reported': acc_3way,
                'assessment': 'Reasonable for football prediction',
                'benchmark_comparison': {
                    'random_baseline': 0.333,
                    'improvement_over_random': (acc_3way - 0.333) / 0.333,
                    'vs_good_model_target': '55%+ is good performance',
                    'status': 'Slightly below good model threshold'
                }
            },
            'accuracy_2way': {
                'reported': acc_2way,
                'calculation_method': 'Likely collapse draws or remove draw matches',
                'assessment': 'Reasonable improvement over 3-way',
                'expected_relationship': f'2-way should be higher than 3-way: {acc_2way:.1%} > {acc_3way:.1%} ✓'
            },
            'consistency_check': {
                'relationship_valid': acc_2way > acc_3way,
                'magnitude_reasonable': (acc_2way - acc_3way) < 0.15,  # Not too large difference
                'label_mapping_concern': 'Ensure H/D/A → 0/1/2 mapping is consistent'
            }
        }
        
        return validation
    
    def analyze_market_advantage_claim(self) -> Dict[str, Any]:
        """Analyze the market advantage claim"""
        
        claimed_advantage = self.reported_metrics['market_advantage_logloss']
        
        analysis = {
            'claimed_improvement': claimed_advantage,
            'baseline_unclear': {
                'issue': 'What baseline is this compared to?',
                'possibilities': [
                    'Uniform consensus (equal weights)',
                    'Frequency-based weights',
                    'Equal consensus',
                    'Market-implied probabilities'
                ],
                'recommendation': 'Should compare weighted vs equal consensus on same data'
            },
            'magnitude_assessment': {
                'value': claimed_advantage,
                'significance': 'Small but potentially meaningful for betting',
                'context': 'LogLoss improvements of 0.008 are modest but valuable in sports betting',
                'concern': 'Need statistical significance testing'
            },
            'verification_needed': [
                'Lock evaluation slice (EURO_TOP5_T72_2019-2024)',
                'Compute paired bootstrap confidence intervals',
                'Ensure time-aware split (no future leakage)',
                'Validate horizon compliance (T-72h ±2h)'
            ]
        }
        
        return analysis
    
    def calculate_corrected_model_rating(self) -> Dict[str, Any]:
        """Calculate model rating with corrected metrics"""
        
        # Use corrected Brier score
        brier_diagnosis = self.diagnose_brier_score_issue()
        corrected_brier = brier_diagnosis['corrected_value']
        
        logloss = self.reported_metrics['logloss']
        accuracy_3way = self.reported_metrics['accuracy_3way']
        
        # Rating components (same methodology as before)
        rating_factors = {}
        
        # 1. LogLoss Performance (40% weight)
        if logloss <= 0.850:
            logloss_rating = 8
        elif logloss <= 0.920:
            logloss_rating = 6
        elif logloss <= 0.970:
            logloss_rating = 5
        else:
            logloss_rating = 4
        
        rating_factors['logloss_rating'] = logloss_rating
        
        # 2. Accuracy Performance (20% weight)
        if accuracy_3way >= 0.55:
            accuracy_rating = 8
        elif accuracy_3way >= 0.52:
            accuracy_rating = 7
        elif accuracy_3way >= 0.50:
            accuracy_rating = 6
        else:
            accuracy_rating = 5
        
        rating_factors['accuracy_rating'] = accuracy_rating
        
        # 3. Calibration (Brier score) (20% weight)
        if corrected_brier <= 0.18:
            calibration_rating = 8
        elif corrected_brier <= 0.22:
            calibration_rating = 7
        elif corrected_brier <= 0.25:
            calibration_rating = 6
        else:
            calibration_rating = 5
        
        rating_factors['calibration_rating'] = calibration_rating
        
        # 4. Robustness (10% weight)
        robustness_rating = 8  # Simple consensus approach
        rating_factors['robustness_rating'] = robustness_rating
        
        # 5. Data Quality (10% weight)  
        data_quality_rating = 7  # Real-time data but validation concerns
        rating_factors['data_quality_rating'] = data_quality_rating
        
        # Calculate weighted overall rating
        overall_rating = (
            logloss_rating * 0.40 +
            accuracy_rating * 0.20 +
            calibration_rating * 0.20 +
            robustness_rating * 0.10 +
            data_quality_rating * 0.10
        )
        
        # Determine grade
        if overall_rating >= 8.0:
            grade = "A"
            interpretation = "Excellent Model"
        elif overall_rating >= 7.0:
            grade = "B+"
            interpretation = "Very Good Model"
        elif overall_rating >= 6.0:
            grade = "B"
            interpretation = "Good Model"
        else:
            grade = "C+"
            interpretation = "Above Average Model"
        
        return {
            'corrected_rating': {
                'overall_score': round(overall_rating, 1),
                'grade': grade,
                'interpretation': interpretation
            },
            'rating_factors': rating_factors,
            'key_metrics_used': {
                'logloss': logloss,
                'brier_normalized': corrected_brier,
                'accuracy_3way': accuracy_3way
            },
            'rating_change': {
                'previous_rating': 7.1,
                'corrected_rating': round(overall_rating, 1),
                'change': round(overall_rating - 7.1, 1),
                'reason': 'Corrected Brier score normalization'
            }
        }
    
    def generate_truth_set_recommendations(self) -> Dict[str, Any]:
        """Generate recommendations for creating definitive truth set"""
        
        recommendations = {
            'immediate_actions': {
                'freeze_evaluation_slice': {
                    'run_id': 'EURO_TOP5_T72_2019_2024_FINAL',
                    'leagues': ['EPL', 'LaLiga', 'SerieA', 'Bundesliga', 'Ligue1'],
                    'horizon': 'T-72h ±2h',
                    'time_period': '2019-2024 seasons',
                    'exclusions': 'Postponed/cancelled matches'
                },
                'export_files': [
                    'y_true.csv (actual outcomes)',
                    'P_equal.csv (equal consensus probabilities)',
                    'P_weighted.csv (weighted consensus probabilities)',
                    'match_metadata.csv (IDs, dates, leagues)'
                ]
            },
            'metric_calculations': {
                'formulas_to_use': {
                    'logloss': '-mean(sum(y_true * log(P_pred)))',
                    'brier_normalized': 'mean(sum((P_pred - y_true)^2)) / num_classes',
                    'accuracy_3way': 'mean(argmax(P_pred) == argmax(y_true))',
                    'accuracy_2way': 'Specify method: remove draws OR collapse draws'
                },
                'statistical_tests': [
                    'Paired bootstrap 95% CIs for weighted vs equal',
                    'McNemar test for accuracy differences',
                    'DeLong test for LogLoss comparisons'
                ]
            },
            'quality_assurance': {
                'sanity_checks': [
                    'Probability matrices sum to 1.0 (±1e-6)',
                    'Label distribution matches expected (H:~45%, D:~27%, A:~28%)',
                    'Horizon audit: all matches within T-72h ±2h',
                    'Time-aware split: no future information leakage'
                ],
                'calibration_analysis': [
                    'Reliability diagrams per outcome',
                    'Expected Calibration Error (ECE)',
                    'Maximum Calibration Error (MCE)',
                    'Brier skill score vs climatology'
                ]
            }
        }
        
        return recommendations
    
    def run_final_diagnosis(self) -> Dict[str, Any]:
        """Run complete final diagnosis"""
        
        print("FINAL PHASE R DIAGNOSIS - BETGENIUS AI METRICS")
        print("=" * 55)
        
        # 1. Brier score diagnosis
        brier_diagnosis = self.diagnose_brier_score_issue()
        print(f"\n🔍 BRIER SCORE DIAGNOSIS:")
        print(f"   Issue: {brier_diagnosis['issue_identified']}")
        print(f"   Reported: {brier_diagnosis['reported_value']:.6f}")
        print(f"   Corrected: {brier_diagnosis['corrected_value']:.6f}")
        print(f"   Severity: {brier_diagnosis['consistency_check']['severity']}")
        
        # 2. Accuracy validation
        accuracy_validation = self.validate_accuracy_metrics()
        print(f"\n📊 ACCURACY VALIDATION:")
        acc_3way = accuracy_validation['accuracy_3way']
        acc_2way = accuracy_validation['accuracy_2way']
        print(f"   3-way: {acc_3way['reported']:.1%} - {acc_3way['assessment']}")
        print(f"   2-way: {acc_2way['reported']:.1%} - {acc_2way['assessment']}")
        print(f"   Consistency: {accuracy_validation['consistency_check']['relationship_valid']}")
        
        # 3. Market advantage analysis
        market_analysis = self.analyze_market_advantage_claim()
        print(f"\n🏪 MARKET ADVANTAGE ANALYSIS:")
        print(f"   Claimed: {market_analysis['claimed_improvement']:+.6f} LogLoss")
        print(f"   Assessment: {market_analysis['magnitude_assessment']['significance']}")
        print(f"   Concern: {market_analysis['baseline_unclear']['issue']}")
        
        # 4. Corrected model rating
        corrected_rating = self.calculate_corrected_model_rating()
        print(f"\n⭐ CORRECTED MODEL RATING:")
        rating = corrected_rating['corrected_rating']
        print(f"   Score: {rating['overall_score']}/10")
        print(f"   Grade: {rating['grade']}")
        print(f"   Classification: {rating['interpretation']}")
        change = corrected_rating['rating_change']
        print(f"   Change: {change['previous_rating']} → {change['corrected_rating']} ({change['change']:+.1f})")
        
        # 5. Truth set recommendations
        truth_set = self.generate_truth_set_recommendations()
        print(f"\n📋 TRUTH SET RECOMMENDATIONS:")
        immediate = truth_set['immediate_actions']
        print(f"   Run ID: {immediate['freeze_evaluation_slice']['run_id']}")
        print(f"   Scope: {len(immediate['freeze_evaluation_slice']['leagues'])} leagues, {immediate['freeze_evaluation_slice']['time_period']}")
        print(f"   Horizon: {immediate['freeze_evaluation_slice']['horizon']}")
        
        # Compile final results
        final_results = {
            'diagnosis_summary': {
                'major_issue_found': 'Brier score not normalized by number of classes',
                'corrected_brier': brier_diagnosis['corrected_value'],
                'impact_on_rating': f"Rating adjusted from 7.1 to {rating['overall_score']}",
                'other_metrics_status': 'Accuracy metrics appear reasonable, market advantage needs verification'
            },
            'corrected_performance': {
                'logloss': self.reported_metrics['logloss'],
                'brier_score_normalized': brier_diagnosis['corrected_value'],
                'accuracy_3way': self.reported_metrics['accuracy_3way'],
                'accuracy_2way': self.reported_metrics['accuracy_2way'],
                'model_rating': rating['overall_score'],
                'grade': rating['grade']
            },
            'brier_diagnosis': brier_diagnosis,
            'accuracy_validation': accuracy_validation,
            'market_analysis': market_analysis,
            'corrected_rating': corrected_rating,
            'truth_set_recommendations': truth_set,
            'next_steps': [
                'Create locked evaluation slice with specified parameters',
                'Recalculate all metrics using proper formulas',
                'Generate statistical significance tests',
                'Produce calibration analysis',
                'Document final defensible metrics'
            ]
        }
        
        return final_results

def main():
    """Run the final Phase R diagnosis"""
    
    diagnosis = FinalPhaseRDiagnosis()
    results = diagnosis.run_final_diagnosis()
    
    print(f"\n" + "="*55)
    print("SUMMARY OF FINDINGS")
    print("="*55)
    
    summary = results['diagnosis_summary']
    corrected = results['corrected_performance']
    
    print(f"\n🚨 CRITICAL ISSUE IDENTIFIED:")
    print(f"   {summary['major_issue_found']}")
    print(f"   Impact: {summary['impact_on_rating']}")
    
    print(f"\n✅ CORRECTED METRICS:")
    print(f"   LogLoss: {corrected['logloss']:.6f}")
    print(f"   Brier Score: {corrected['brier_score_normalized']:.6f} (normalized)")
    print(f"   3-way Accuracy: {corrected['accuracy_3way']:.1%}")
    print(f"   2-way Accuracy: {corrected['accuracy_2way']:.1%}")
    print(f"   Model Rating: {corrected['model_rating']}/10 ({corrected['grade']})")
    
    print(f"\n📋 IMMEDIATE ACTIONS REQUIRED:")
    for step in results['next_steps'][:3]:
        print(f"   • {step}")
    
    # Save results
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    # Convert any numpy types to native Python types for JSON serialization
    def convert_for_json(obj):
        if isinstance(obj, np.integer):
            return int(obj)
        elif isinstance(obj, np.floating):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, dict):
            return {k: convert_for_json(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [convert_for_json(item) for item in obj]
        return obj
    
    results_serializable = convert_for_json(results)
    
    with open(f'final_phase_r_diagnosis_{timestamp}.json', 'w') as f:
        json.dump(results_serializable, f, indent=2)
    
    with open(f'final_phase_r_diagnosis_{timestamp}.txt', 'w') as f:
        f.write("BETGENIUS AI - FINAL PHASE R DIAGNOSIS\n")
        f.write("=" * 50 + "\n\n")
        f.write(f"CRITICAL FINDING: {summary['major_issue_found']}\n\n")
        f.write(f"CORRECTED PERFORMANCE METRICS:\n")
        f.write(f"• LogLoss: {corrected['logloss']:.6f}\n")
        f.write(f"• Brier Score (normalized): {corrected['brier_score_normalized']:.6f}\n")
        f.write(f"• 3-way Accuracy: {corrected['accuracy_3way']:.1%}\n")
        f.write(f"• 2-way Accuracy: {corrected['accuracy_2way']:.1%}\n")
        f.write(f"• Model Rating: {corrected['model_rating']}/10 ({corrected['grade']})\n\n")
        f.write(f"IMPACT: Rating adjusted from 7.1 to {corrected['model_rating']}\n\n")
        f.write(f"NEXT STEPS:\n")
        for i, step in enumerate(results['next_steps'], 1):
            f.write(f"{i}. {step}\n")
    
    print(f"\n📄 Diagnosis saved: final_phase_r_diagnosis_{timestamp}.json")
    print(f"📄 Report saved: final_phase_r_diagnosis_{timestamp}.txt")
    
    return results

if __name__ == "__main__":
    main()