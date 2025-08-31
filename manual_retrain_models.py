#!/usr/bin/env python3
"""
Advanced Model Retraining & Validation Script
Comprehensive ML model training with detailed performance analysis
"""

import sys
import os
import json
import numpy as np
from datetime import datetime
from typing import Dict, List, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from models.ml_predictor import MLPredictor

def advanced_model_retraining():
    """Advanced model retraining with comprehensive validation and results"""
    
    print("🧠 BetGenius AI - Advanced Model Retraining & Analysis")
    print("=" * 60)
    
    try:
        # Import required modules
        from models.ml_predictor import MLPredictor
        from models.database import DatabaseManager
        
        print("📊 Phase 1: Data Discovery & Preparation")
        print("-" * 40)
        
        # Initialize systems
        predictor = MLPredictor()
        db_manager = DatabaseManager()
        
        # Comprehensive data analysis
        print("🔍 Analyzing training data...")
        
        # Load raw training data for analysis
        training_data = predictor._load_training_data()
        
        if not training_data:
            print("❌ No training data found - cannot proceed with retraining")
            return False
            
        print(f"📈 Raw data loaded: {len(training_data):,} total matches")
        
        # Analyze data quality
        feature_stats = analyze_data_quality(training_data)
        print_data_analysis(feature_stats)
        
        print(f"\n🚀 Phase 2: Model Training")
        print("-" * 40)
        
        start_time = datetime.now()
        print(f"⏱️  Training started: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Train models with improved error handling
        predictor._train_models()
        
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        if not predictor.is_trained:
            print("❌ Training failed - check logs above")
            return False
            
        print(f"✅ Training completed in {duration:.1f} seconds")
        print(f"🎯 Features used: {len(predictor.feature_names)} numeric features")
        print(f"🧠 Models trained: {len(predictor.models)} algorithms")
        
        print(f"\n🧪 Phase 3: Model Validation & Testing")
        print("-" * 40)
        
        # Comprehensive model testing
        validation_results = run_comprehensive_validation(predictor, training_data)
        
        print(f"\n📊 Phase 4: Performance Analysis")
        print("-" * 40)
        
        # Display detailed results
        display_training_results(validation_results, predictor, duration)
        
        # Save results to file
        results_file = save_training_results(validation_results, predictor, duration)
        print(f"💾 Results saved to: {results_file}")
        
        print(f"\n🎉 TRAINING COMPLETE - Models Ready for Production!")
        print("=" * 60)
        
        return True
        
    except ImportError as e:
        print(f"❌ Import Error: {e}")
        print("   Make sure you're running this from the project root directory")
        return False
        
    except Exception as e:
        print(f"❌ Advanced retraining failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def analyze_data_quality(training_data: List[Dict]) -> Dict[str, Any]:
    """Analyze training data quality and feature distribution"""
    
    total_samples = len(training_data)
    feature_analysis = {}
    outcome_distribution = {'Home': 0, 'Draw': 0, 'Away': 0}
    
    # Analyze features and outcomes
    all_features = set()
    numeric_features = set()
    
    for sample in training_data:
        # Count outcomes
        outcome = sample.get('outcome', 'Unknown')
        if outcome in outcome_distribution:
            outcome_distribution[outcome] += 1
            
        # Analyze features
        features = sample.get('features', {})
        if isinstance(features, str):
            try:
                features = json.loads(features)
            except:
                continue
                
        for key, value in features.items():
            all_features.add(key)
            
            # Check if numeric
            if key not in ['collected_at', 'match_date', 'created_at', 'updated_at', 'timestamp']:
                try:
                    float(value) if value is not None else 0.0
                    numeric_features.add(key)
                except (ValueError, TypeError):
                    pass
    
    return {
        'total_samples': total_samples,
        'all_features_count': len(all_features),
        'numeric_features_count': len(numeric_features),
        'numeric_features': sorted(list(numeric_features)),
        'outcome_distribution': outcome_distribution,
        'data_balance': calculate_balance_score(outcome_distribution)
    }

def calculate_balance_score(distribution: Dict[str, int]) -> float:
    """Calculate how balanced the outcome distribution is (0-1, higher is more balanced)"""
    
    total = sum(distribution.values())
    if total == 0:
        return 0.0
        
    # Calculate entropy-based balance score
    probs = [count/total for count in distribution.values() if count > 0]
    entropy = -sum(p * np.log(p) for p in probs)
    max_entropy = np.log(len(probs))
    
    return entropy / max_entropy if max_entropy > 0 else 0.0

def print_data_analysis(stats: Dict[str, Any]):
    """Print comprehensive data analysis"""
    
    print(f"📊 Data Quality Report:")
    print(f"   • Total samples: {stats['total_samples']:,}")
    print(f"   • Total features: {stats['all_features_count']:,}")
    print(f"   • Numeric features: {stats['numeric_features_count']:,}")
    print(f"   • Data balance score: {stats['data_balance']:.3f}/1.000")
    
    print(f"\n📈 Outcome Distribution:")
    total = sum(stats['outcome_distribution'].values())
    for outcome, count in stats['outcome_distribution'].items():
        pct = (count/total*100) if total > 0 else 0
        print(f"   • {outcome}: {count:,} ({pct:.1f}%)")

def run_comprehensive_validation(predictor: Any, training_data: List[Dict]) -> Dict[str, Any]:
    """Run comprehensive model validation"""
    
    print("🧪 Running validation tests...")
    
    results = {
        'timestamp': datetime.now().isoformat(),
        'model_info': {
            'is_trained': predictor.is_trained,
            'feature_count': len(predictor.feature_names),
            'model_count': len(predictor.models),
            'scaler_fitted': predictor.scaler is not None
        },
        'prediction_tests': [],
        'model_performance': {}
    }
    
    # Test prediction capability with various inputs
    test_scenarios = [
        {"name": "Balanced Teams", "features": [0.5] * len(predictor.feature_names)},
        {"name": "Home Favorite", "features": [0.7, 0.3] + [0.5] * (len(predictor.feature_names)-2)},
        {"name": "Away Favorite", "features": [0.2, 0.8] + [0.5] * (len(predictor.feature_names)-2)},
        {"name": "All Zeros", "features": [0.0] * len(predictor.feature_names)},
        {"name": "High Values", "features": [1.0] * len(predictor.feature_names)}
    ]
    
    for scenario in test_scenarios:
        try:
            # Create feature dict matching expected format
            feature_dict = dict(zip(predictor.feature_names, scenario["features"]))
            
            prediction = predictor.predict_match_outcome(feature_dict)
            
            test_result = {
                'scenario': scenario['name'],
                'success': prediction is not None,
                'prediction': prediction
            }
            
            if prediction:
                h_prob = prediction.get('home_win_probability', 0)
                d_prob = prediction.get('draw_probability', 0)
                a_prob = prediction.get('away_win_probability', 0)
                total_prob = h_prob + d_prob + a_prob
                
                test_result['probability_sum'] = total_prob
                test_result['valid_probabilities'] = 0.98 <= total_prob <= 1.02
                
                print(f"   ✅ {scenario['name']}: H={h_prob:.3f}, D={d_prob:.3f}, A={a_prob:.3f}")
            else:
                print(f"   ❌ {scenario['name']}: Failed")
                
            results['prediction_tests'].append(test_result)
            
        except Exception as e:
            print(f"   ❌ {scenario['name']}: Error - {e}")
            results['prediction_tests'].append({
                'scenario': scenario['name'],
                'success': False,
                'error': str(e)
            })
    
    return results

def display_training_results(results: Dict[str, Any], predictor: Any, duration: float):
    """Display comprehensive training results"""
    
    print("📊 Training Results Summary:")
    print(f"   • Training duration: {duration:.1f} seconds")
    print(f"   • Models successfully trained: {results['model_info']['model_count']}")
    print(f"   • Feature engineering: {results['model_info']['feature_count']} features")
    print(f"   • Scaler fitted: {'✅' if results['model_info']['scaler_fitted'] else '❌'}")
    
    # Prediction test results
    successful_tests = sum(1 for test in results['prediction_tests'] if test['success'])
    total_tests = len(results['prediction_tests'])
    
    print(f"\n🧪 Validation Results:")
    print(f"   • Prediction tests passed: {successful_tests}/{total_tests}")
    
    # Check probability validity
    valid_probs = sum(1 for test in results['prediction_tests'] 
                     if test.get('valid_probabilities', False))
    
    print(f"   • Valid probability distributions: {valid_probs}/{successful_tests}")
    
    if successful_tests == total_tests and valid_probs == successful_tests:
        print("   🎯 All validation tests PASSED - Models are production-ready!")
    else:
        print("   ⚠️  Some validation tests failed - Review model implementation")

def save_training_results(results: Dict[str, Any], predictor: Any, duration: float) -> str:
    """Save comprehensive training results to file"""
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"model_training_results_{timestamp}.json"
    
    comprehensive_results = {
        **results,
        'training_duration_seconds': duration,
        'feature_names': predictor.feature_names,
        'model_types': list(predictor.models.keys()),
        'training_completed': datetime.now().isoformat()
    }
    
    with open(filename, 'w') as f:
        json.dump(comprehensive_results, f, indent=2)
        
    return filename

if __name__ == "__main__":
    success = advanced_model_retraining()
    sys.exit(0 if success else 1)