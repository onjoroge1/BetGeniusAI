"""
Model Comparison Analysis
Compare current sophisticated model with initial baseline
"""

import pandas as pd
import numpy as np
import json
import os
from pathlib import Path

class ModelComparisonAnalysis:
    """Compare current model with initial baseline"""
    
    def __init__(self):
        pass
    
    def load_latest_results(self):
        """Load the latest Week 2 results"""
        
        results_dir = 'models/complete_week2'
        if not os.path.exists(results_dir):
            return None
            
        result_files = [f for f in os.listdir(results_dir) if f.startswith('week2_results_') and f.endswith('.json')]
        if not result_files:
            return None
            
        latest_file = sorted(result_files)[-1]
        with open(os.path.join(results_dir, latest_file), 'r') as f:
            return json.load(f)
    
    def analyze_performance_trajectory(self):
        """Analyze the performance trajectory from baseline to current"""
        
        print("MODEL COMPARISON ANALYSIS")
        print("=" * 40)
        
        # Load latest results
        latest_results = self.load_latest_results()
        if not latest_results:
            print("No Week 2 results found")
            return
        
        baseline_metrics = latest_results['baseline_metrics']
        training_results = latest_results['training_results']
        
        # Extract key metrics
        equal_weight_ll = baseline_metrics.get('equal_weight_logloss', 0)
        weighted_ll = baseline_metrics.get('weighted_logloss', 0)
        enhanced_consensus_ll = baseline_metrics['enhanced_consensus_logloss']
        
        best_result = training_results['best_result']
        if best_result:
            final_model_ll = best_result['calibrated']['model_logloss']
            market_ll = best_result['calibrated']['market_logloss']
            residual_improvement = best_result['calibrated']['logloss_improvement']
        else:
            final_model_ll = enhanced_consensus_ll
            market_ll = enhanced_consensus_ll
            residual_improvement = 0
        
        print(f"\n📊 PERFORMANCE TRAJECTORY:")
        print(f"   1. Equal Weight Baseline: {equal_weight_ll:.6f}")
        print(f"   2. Weighted Consensus: {weighted_ll:.6f}")
        print(f"   3. Instance-wise Mixing: {enhanced_consensus_ll:.6f}")
        print(f"   4. Final Residual Model: {final_model_ll:.6f}")
        
        # Calculate improvements at each stage
        stage1_improvement = equal_weight_ll - weighted_ll if weighted_ll > 0 else 0
        stage2_improvement = weighted_ll - enhanced_consensus_ll if weighted_ll > 0 else equal_weight_ll - enhanced_consensus_ll
        stage3_improvement = residual_improvement
        total_improvement = equal_weight_ll - final_model_ll
        
        print(f"\n🔄 IMPROVEMENT BREAKDOWN:")
        print(f"   • Equal → Weighted: {stage1_improvement:+.6f}")
        print(f"   • Weighted → Instance-wise: {stage2_improvement:+.6f}")
        print(f"   • Instance-wise → Residual: {stage3_improvement:+.6f}")
        print(f"   • TOTAL IMPROVEMENT: {total_improvement:+.6f}")
        
        # Complexity analysis
        feature_count = len(training_results['training_info']['feature_names']) if 'feature_names' in training_results['training_info'] else latest_results['data_info']['feature_count']
        consensus_type = latest_results['consensus_type']
        
        print(f"\n🔧 SYSTEM COMPLEXITY:")
        print(f"   • Initial Model: Simple equal-weight average")
        print(f"   • Current Model: {feature_count} features, {consensus_type}")
        print(f"   • Enhancement Layers: 4 (weighted → instance-wise → movement → residual)")
        
        # Reality check
        print(f"\n🎯 REALITY CHECK:")
        
        if total_improvement > 0:
            print(f"   ✅ TECHNICAL SUCCESS: Model shows {total_improvement:.6f} LogLoss improvement")
            print(f"   📈 Complexity justified by measurable gains")
        else:
            print(f"   ⚠️  PERFORMANCE CONCERN: Model shows {total_improvement:.6f} LogLoss degradation")
            print(f"   🤔 Complexity may not be justified by performance")
        
        # Market efficiency context
        print(f"\n🏪 MARKET EFFICIENCY CONTEXT:")
        print(f"   • Market Consensus LogLoss: {market_ll:.6f}")
        print(f"   • Our Best Model LogLoss: {final_model_ll:.6f}")
        
        if final_model_ll > market_ll:
            gap = final_model_ll - market_ll
            print(f"   📊 Performance Gap: {gap:.6f} (worse than market)")
            print(f"   💡 Market consensus is {gap:.6f} LogLoss better than our model")
        else:
            gap = market_ll - final_model_ll
            print(f"   🎯 Performance Advantage: {gap:.6f} (better than market)")
            print(f"   🚀 Our model beats market consensus by {gap:.6f} LogLoss")
        
        # Practical implications
        print(f"\n💼 PRACTICAL IMPLICATIONS:")
        
        if total_improvement <= 0:
            print("   🔴 HONEST ASSESSMENT:")
            print("   • Current sophisticated model performs worse than simple baseline")
            print("   • Market consensus at T-72h is highly efficient")
            print("   • Complex features may be adding noise rather than signal")
            print("   • Consider returning to simpler, more robust approach")
            
            print(f"\n   💡 RECOMMENDATIONS:")
            print("   • Use simple weighted consensus as production model")
            print("   • Focus on operational excellence and user experience")
            print("   • Consider different prediction horizons (T-24h, T-12h)")
            print("   • Invest in data quality and coverage improvements")
        else:
            print("   🟢 POSITIVE ASSESSMENT:")
            print("   • Sophisticated model shows measurable improvement")
            print("   • Complex features are adding genuine predictive value")
            print("   • Technical investment is justified")
            
            print(f"\n   🚀 RECOMMENDATIONS:")
            print("   • Deploy current sophisticated model")
            print("   • Continue refining feature engineering")
            print("   • Monitor performance in production")
        
        return {
            'equal_weight_ll': equal_weight_ll,
            'final_model_ll': final_model_ll,
            'total_improvement': total_improvement,
            'market_ll': market_ll,
            'feature_count': feature_count,
            'consensus_type': consensus_type,
            'is_improvement': total_improvement > 0,
            'beats_market': final_model_ll < market_ll
        }
    
    def compare_with_historical_baselines(self):
        """Compare with historical baseline performance"""
        
        print("\n📈 HISTORICAL BASELINE COMPARISON:")
        
        # These are typical baselines from the project
        historical_baselines = {
            'random_uniform': 1.0986,  # -log(1/3)
            'market_consensus_typical': 0.82,  # Typical market performance
            'simple_ml_model': 0.81,   # Simple Random Forest
            'week1_target': 0.80,      # Week 1 achievement target
            'week2_target': 0.785      # Week 2 achievement target (0.80 - 0.015)
        }
        
        latest_results = self.load_latest_results()
        if latest_results and latest_results['training_results']['best_result']:
            current_model_ll = latest_results['training_results']['best_result']['calibrated']['model_logloss']
            
            print(f"   Current Model: {current_model_ll:.6f}")
            for name, baseline_ll in historical_baselines.items():
                diff = baseline_ll - current_model_ll
                if diff > 0:
                    print(f"   vs {name}: {diff:+.6f} (better)")
                else:
                    print(f"   vs {name}: {diff:+.6f} (worse)")

def main():
    analyzer = ModelComparisonAnalysis()
    result = analyzer.analyze_performance_trajectory()
    analyzer.compare_with_historical_baselines()
    
    print(f"\n" + "=" * 60)
    print("FINAL VERDICT")
    print("=" * 60)
    
    if result and not result['is_improvement']:
        print("🔴 CURRENT MODEL IS NOT AN IMPROVEMENT")
        print("   The sophisticated Week 2 system performs worse than the simple baseline.")
        print("   This is a common outcome in efficient markets where complexity")
        print("   can add noise rather than signal.")
        print("\n   RECOMMENDATION: Consider using the simple weighted consensus")
        print("   as the production model and focus on operational excellence.")
    elif result and result['is_improvement']:
        print("🟢 CURRENT MODEL IS AN IMPROVEMENT")
        print("   The sophisticated system successfully improves upon the baseline.")
        print("   The added complexity is justified by measurable performance gains.")
        print("\n   RECOMMENDATION: Deploy the current sophisticated model.")
    else:
        print("❓ UNABLE TO DETERMINE")
        print("   Insufficient data to make a definitive comparison.")

if __name__ == "__main__":
    main()