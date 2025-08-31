#!/usr/bin/env python3
"""
Manual Model Retraining Script
Retrain ML models with latest training data from database
"""

import sys
import os
from datetime import datetime

def retrain_models():
    """Manually trigger model retraining with latest data"""
    
    print("🤖 BetGenius AI - Manual Model Retraining")
    print("=" * 45)
    
    try:
        # Import the ML predictor
        from models.ml_predictor import MLPredictor
        from models.database import DatabaseManager
        
        print("📊 Initializing ML predictor...")
        predictor = MLPredictor()
        
        print("🔍 Checking database connection...")
        db_manager = DatabaseManager()
        
        # Check training data availability
        print("📋 Loading training data statistics...")
        stats = db_manager.get_training_stats()
        total_matches = stats.get("training_data", {}).get("total_samples", 0)
        
        print(f"📈 Available training data: {total_matches:,} matches")
        
        if total_matches < 100:
            print("⚠️  WARNING: Low training data count - model quality may be limited")
        
        # Start retraining
        print(f"\n🚀 Starting model retraining at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("   This may take 1-3 minutes...")
        
        # Retrain models
        predictor._train_models()
        
        if predictor.is_trained:
            print("✅ SUCCESS: Models retrained successfully!")
            print(f"🎯 Feature count: {len(predictor.feature_names)} features")
            print(f"🧠 Models trained: {len(predictor.models)} algorithms")
            print(f"📏 Scaler fitted: {predictor.scaler is not None}")
            
            # Test prediction to verify
            print("\n🧪 Testing prediction capability...")
            try:
                # Create sample features (all zeros for basic test)
                sample_features = [0.0] * len(predictor.feature_names)
                predictions = predictor.predict_match_outcome(
                    home_team="Test Home",
                    away_team="Test Away", 
                    features=sample_features
                )
                
                if predictions:
                    print("✅ Prediction test successful - models are operational")
                    home_prob = predictions.get('home_win_probability', 0)
                    draw_prob = predictions.get('draw_probability', 0) 
                    away_prob = predictions.get('away_win_probability', 0)
                    print(f"   Sample prediction: H={home_prob:.3f}, D={draw_prob:.3f}, A={away_prob:.3f}")
                else:
                    print("⚠️  Prediction test returned empty results")
                    
            except Exception as e:
                print(f"⚠️  Prediction test failed: {e}")
            
        else:
            print("❌ FAILED: Model retraining unsuccessful")
            print("   Check the logs above for specific error details")
            return False
            
        print(f"\n🎉 Retraining completed at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("   Models are now ready for production predictions!")
        
        return True
        
    except ImportError as e:
        print(f"❌ Import Error: {e}")
        print("   Make sure you're running this from the project root directory")
        return False
        
    except Exception as e:
        print(f"❌ Retraining failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = retrain_models()
    sys.exit(0 if success else 1)