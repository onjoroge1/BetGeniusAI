"""
Quick test script to validate drift feature extraction
"""
import sys
sys.path.insert(0, '/home/runner/BetGeniusAI')

from features.v2_feature_builder import V2FeatureBuilder
from datetime import datetime

# Initialize builder
print("Initializing V2FeatureBuilder...")
builder = V2FeatureBuilder()

# Test with a match that has drift data
test_match_id = 1374260  # Known to have drift data from our SQL tests

print(f"\n🧪 Testing drift feature extraction for match {test_match_id}...")

try:
    features = builder.build_features(test_match_id, cutoff_time=datetime(2025, 11, 1))
    
    print(f"\n✅ Feature extraction successful!")
    print(f"Total features: {len(features)}")
    
    # Extract drift features
    drift_features = {k: v for k, v in features.items() if 'drift' in k}
    
    print(f"\n📊 Drift Features ({len(drift_features)} total):")
    for feature, value in sorted(drift_features.items()):
        print(f"  {feature}: {value:.6f}")
    
    # Validate feature count
    expected_count = 54
    if len(features) == expected_count:
        print(f"\n✅ PASS: Feature count correct ({expected_count})")
    else:
        print(f"\n❌ FAIL: Expected {expected_count} features, got {len(features)}")
        
    # Check if drift features are non-zero (should be for this match)
    if drift_features['drift_magnitude'] > 0:
        print(f"✅ PASS: Drift features populated (magnitude: {drift_features['drift_magnitude']:.4f})")
    else:
        print(f"⚠️  WARNING: Drift magnitude is zero (may not have early odds)")
        
except Exception as e:
    print(f"\n❌ ERROR: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "="*60)
print("Test complete!")
