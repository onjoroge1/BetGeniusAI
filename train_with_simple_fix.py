"""
Train Delta-Logit with Simple Fixed Consensus
Quick training with the fixed consensus data
"""

import pandas as pd
import numpy as np
from residual_delta_logit_trainer import DeltaLogitResidualTrainer
from sklearn.model_selection import train_test_split
import os
import json
from datetime import datetime

def load_latest_fixed_data():
    """Load latest fixed consensus data"""
    
    fixed_dir = 'consensus/simple_fix'
    if os.path.exists(fixed_dir):
        files = [f for f in os.listdir(fixed_dir) if f.startswith('simple_fixed_consensus_') and f.endswith('.csv')]
        if files:
            latest = sorted(files)[-1]
            path = os.path.join(fixed_dir, latest)
            print(f"Loading fixed data from {path}")
            return pd.read_csv(path)
    
    raise FileNotFoundError("No fixed consensus data found")

def train_with_fixed_consensus():
    """Train residual model with fixed consensus"""
    
    print("TRAIN WITH FIXED CONSENSUS")
    print("=" * 30)
    
    # Load data
    df = load_latest_fixed_data()
    print(f"Loaded {len(df)} matches")
    
    # Prepare features and targets
    feature_cols = [col for col in df.columns if col.startswith('feat_')] + ['dispH', 'dispD', 'dispA', 'n_books']
    market_cols = ['pH_mkt', 'pD_mkt', 'pA_mkt']
    
    X = df[feature_cols].fillna(0).values
    market_probs = df[market_cols].values  
    y = df['y'].values
    
    print(f"Features: {len(feature_cols)}")
    print(f"Samples: {len(X)}")
    
    # Split data
    X_train, X_val, market_train, market_val, y_train, y_val = train_test_split(
        X, market_probs, y, test_size=0.25, random_state=42, stratify=y
    )
    
    # Test multiple configurations quickly
    configs = [
        {'lambda_param': 0.6, 'clip_value': 1.0, 'l2_reg': 0.001, 'lr': 0.05, 'epochs': 200},
        {'lambda_param': 0.7, 'clip_value': 0.9, 'l2_reg': 0.001, 'lr': 0.04, 'epochs': 200},
        {'lambda_param': 0.8, 'clip_value': 1.1, 'l2_reg': 0.002, 'lr': 0.03, 'epochs': 200}
    ]
    
    best_improvement = -float('inf')
    best_config = None
    best_trainer = None
    results = []
    
    for i, config in enumerate(configs):
        print(f"\nTesting config {i+1}: λ={config['lambda_param']}, clip={config['clip_value']}")
        
        trainer = DeltaLogitResidualTrainer(**config)
        
        # Train
        trainer.fit(X_train, market_train, y_train, X_val, market_val, y_val, verbose=False)
        
        # Evaluate
        pred = trainer.predict(X_val, market_val)
        metrics = trainer.compute_metrics(pred, y_val, market_val)
        
        # Calibrate
        trainer.calibrate_temperature(X_val, market_val, y_val)
        cal_pred = trainer.predict_calibrated(X_val, market_val)
        cal_metrics = trainer.compute_metrics(cal_pred, y_val, market_val)
        
        improvement = cal_metrics['logloss_improvement']
        
        print(f"  Improvement: {improvement:.4f}")
        print(f"  Final LogLoss: {cal_metrics['model_logloss']:.4f}")
        print(f"  Temperature: {trainer.temperature:.3f}")
        
        result = {
            'config': config,
            'uncalibrated': metrics,
            'calibrated': cal_metrics,
            'temperature': trainer.temperature
        }
        results.append(result)
        
        if improvement > best_improvement:
            best_improvement = improvement
            best_config = config
            best_trainer = trainer
    
    # Compute baselines for comparison
    equal_probs = df[['pH_equal', 'pD_equal', 'pA_equal']].values
    weighted_probs = df[['pH_mkt', 'pD_mkt', 'pA_mkt']].values
    
    y_onehot = np.zeros((len(df), 3))
    y_onehot[np.arange(len(df)), df['y']] = 1
    
    equal_ll = -np.mean(np.sum(y_onehot * np.log(np.clip(equal_probs, 1e-15, 1-1e-15)), axis=1))
    weighted_ll = -np.mean(np.sum(y_onehot * np.log(np.clip(weighted_probs, 1e-15, 1-1e-15)), axis=1))
    
    # Save results
    os.makedirs('models/simple_fix_results', exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    final_results = {
        'timestamp': timestamp,
        'baselines': {
            'equal_logloss': float(equal_ll),
            'weighted_logloss': float(weighted_ll),
            'weighted_improvement': float(equal_ll - weighted_ll)
        },
        'best_config': best_config,
        'best_metrics': results[configs.index(best_config)]['calibrated'] if best_config else None,
        'all_results': results,
        'data_info': {
            'samples': len(df),
            'features': len(feature_cols),
            'train_samples': len(X_train),
            'val_samples': len(X_val)
        }
    }
    
    results_path = f'models/simple_fix_results/results_{timestamp}.json'
    with open(results_path, 'w') as f:
        json.dump(final_results, f, indent=2, default=str)
    
    # Save best model
    if best_trainer:
        best_trainer.save_artifacts('models/simple_fix_results', feature_cols, timestamp)
    
    # Print summary
    print(f"\n" + "=" * 50)
    print("TRAINING WITH FIXED CONSENSUS COMPLETE")
    print("=" * 50)
    
    print(f"\n📊 BASELINE COMPARISON:")
    print(f"   • Equal Weight LogLoss: {equal_ll:.4f}")
    print(f"   • Weighted LogLoss: {weighted_ll:.4f}")
    print(f"   • Weighted Improvement: {equal_ll - weighted_ll:.4f}")
    
    if best_config and final_results['best_metrics']:
        best_metrics = final_results['best_metrics']
        print(f"\n🎯 BEST RESIDUAL MODEL:")
        print(f"   • Config: λ={best_config['lambda_param']}, clip={best_config['clip_value']}")
        print(f"   • Model LogLoss: {best_metrics['model_logloss']:.4f}")
        print(f"   • Market LogLoss: {best_metrics['market_logloss']:.4f}")
        print(f"   • Residual Improvement: {best_metrics['logloss_improvement']:.4f}")
        print(f"   • Total Improvement: {(equal_ll - weighted_ll) + best_metrics['logloss_improvement']:.4f}")
        print(f"   • Accuracy: {best_metrics['model_accuracy']:.3f}")
        print(f"   • Top-2: {best_metrics['model_top2']:.3f}")
        
        # Target assessment
        total_improvement = (equal_ll - weighted_ll) + best_metrics['logloss_improvement']
        baseline = 0.8157
        expected = baseline - total_improvement
        
        print(f"\n🚀 PROJECTION:")
        print(f"   • Current Baseline: {baseline:.4f}")
        print(f"   • Expected Production: {expected:.4f}")
        
        if total_improvement >= 0.015:
            print(f"   ✅ Week 2 target achieved: {total_improvement:.4f} >= 0.015")
        else:
            print(f"   📊 Progress: {total_improvement:.4f} / 0.015 target")
    
    print(f"\nResults saved: {results_path}")
    
    return final_results

if __name__ == "__main__":
    train_with_fixed_consensus()