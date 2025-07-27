"""
Model Diagnostics - Find the actual working production model
"""

import joblib
import numpy as np
import os
from datetime import datetime

def find_working_models():
    """Find models that can actually generate predictions"""
    
    print("🔍 MODEL DIAGNOSTICS")
    print("=" * 40)
    
    models_dir = 'models'
    model_files = [f for f in os.listdir(models_dir) if f.endswith(('.joblib', '.pkl'))]
    
    print(f"Found {len(model_files)} model files")
    
    working_models = []
    
    for model_file in model_files:
        try:
            model_path = os.path.join(models_dir, model_file)
            model = joblib.load(model_path)
            
            # Test with dummy data
            test_X = np.random.rand(3, 6)  # 3 samples, 6 features
            
            if hasattr(model, 'predict_proba'):
                try:
                    predictions = model.predict_proba(test_X)
                    if predictions.shape[1] == 3:  # 3-class predictions
                        working_models.append({
                            'file': model_file,
                            'model': model,
                            'type': type(model).__name__,
                            'test_prediction': predictions[0]
                        })
                        print(f"✅ {model_file}: {type(model).__name__} - WORKING")
                    else:
                        print(f"⚠️  {model_file}: Wrong output shape {predictions.shape}")
                except Exception as e:
                    print(f"❌ {model_file}: Prediction failed - {str(e)[:50]}")
            else:
                print(f"❌ {model_file}: No predict_proba method")
                
        except Exception as e:
            print(f"❌ {model_file}: Load failed - {str(e)[:50]}")
    
    print(f"\n✅ Found {len(working_models)} working models")
    
    return working_models

def test_model_with_real_features(model, model_name):
    """Test model with realistic feature values"""
    
    print(f"\n🧪 Testing {model_name} with realistic features:")
    
    # Create realistic feature vectors
    test_features = np.array([
        [1, 0.85, 0.90, 0.20, 2.7, 0.6],  # Top league match
        [2, 0.70, 0.75, 0.15, 2.5, 0.4],  # Mid league match
        [3, 0.60, 0.60, 0.25, 2.3, 0.5]   # Lower league match
    ])
    
    try:
        predictions = model.predict_proba(test_features)
        
        print("Feature set: [league_tier, competitiveness, regional_strength, home_advantage, expected_goals, importance]")
        for i, (features, probs) in enumerate(zip(test_features, predictions)):
            print(f"Match {i+1}: {features}")
            print(f"  Predictions: Home={probs[0]:.3f}, Draw={probs[1]:.3f}, Away={probs[2]:.3f}")
            print(f"  Sum: {probs.sum():.3f}")
        
        return True
        
    except Exception as e:
        print(f"❌ Failed: {e}")
        return False

def main():
    """Run model diagnostics"""
    
    working_models = find_working_models()
    
    if not working_models:
        print("\n❌ No working models found!")
        return None
    
    # Test the best working model
    best_model = working_models[0]
    print(f"\n🎯 Testing best model: {best_model['file']}")
    
    success = test_model_with_real_features(best_model['model'], best_model['file'])
    
    if success:
        print(f"\n✅ RECOMMENDED MODEL: {best_model['file']}")
        print(f"   Type: {best_model['type']}")
        print(f"   Sample prediction: {best_model['test_prediction']}")
        
        return best_model
    else:
        print(f"\n❌ Model testing failed")
        return None

if __name__ == "__main__":
    result = main()