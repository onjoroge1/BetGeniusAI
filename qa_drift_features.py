"""
QA Script: Verify drift features implementation
"""
import sys
sys.path.insert(0, '/home/runner/BetGeniusAI')

from features.v2_feature_builder import V2FeatureBuilder
import psycopg2
import os
from datetime import datetime

print("="*60)
print("QA: DRIFT FEATURES IMPLEMENTATION")
print("="*60)

# 1. Check odds_early_snapshot coverage
print("\n1. Checking odds_early_snapshot coverage...")
conn = psycopg2.connect(os.getenv('DATABASE_URL'))
cursor = conn.cursor()

cursor.execute("""
    SELECT COUNT(*) as total_matches,
           AVG(num_books_early) as avg_books,
           MIN(max_secs_to_kickoff/3600.0) as min_hours,
           MAX(max_secs_to_kickoff/3600.0) as max_hours
    FROM odds_early_snapshot
""")
result = cursor.fetchone()
print(f"   Total matches with early odds: {result[0]}")
print(f"   Avg bookmakers: {result[1]:.1f}")
print(f"   Hours before kickoff range: {result[2]:.1f}h - {result[3]:.1f}h")

# 2. Verify feature extraction
print("\n2. Testing feature extraction...")
builder = V2FeatureBuilder()

# Test with match that has drift data
test_match = 1374260
features = builder.build_features(test_match, cutoff_time=datetime(2025, 11, 1))

print(f"   Total features extracted: {len(features)}")

# 3. Verify drift features
drift_features = {k: v for k, v in features.items() if 'drift' in k}
print(f"\n3. Drift features ({len(drift_features)} total):")
for feature, value in sorted(drift_features.items()):
    print(f"   {feature}: {value:.6f}")

# 4. Feature breakdown
phase1 = 42
phase2 = 4
phase25 = 4
expected_total = phase1 + phase2 + phase25

print(f"\n4. Feature breakdown:")
print(f"   Phase 1 (base): {phase1}")
print(f"   Phase 2 (context): {phase2}")
print(f"   Phase 2.5 (drift): {phase25}")
print(f"   Expected total: {expected_total}")
print(f"   Actual total: {len(features)}")

# 5. Check training dataset coverage
cursor.execute("""
    SELECT 
        COUNT(DISTINCT tm.match_id) as total_matches,
        COUNT(DISTINCT CASE WHEN oes.match_id IS NOT NULL THEN tm.match_id END) as matches_with_drift,
        ROUND(100.0 * COUNT(DISTINCT CASE WHEN oes.match_id IS NOT NULL THEN tm.match_id END) / COUNT(DISTINCT tm.match_id), 1) as pct_coverage
    FROM training_matches tm
    LEFT JOIN odds_early_snapshot oes ON tm.match_id = oes.match_id
    WHERE tm.has_odds = TRUE
""")
coverage = cursor.fetchone()
print(f"\n5. Training dataset coverage:")
print(f"   Total matches with odds: {coverage[0]}")
print(f"   Matches with drift features: {coverage[1]}")
print(f"   Coverage: {coverage[2]}%")

cursor.close()
conn.close()

# Final verdict
print("\n" + "="*60)
if len(features) == expected_total and drift_features['drift_magnitude'] > 0:
    print("✅ QA PASS: Drift features implementation verified")
    print("="*60)
else:
    print("❌ QA FAIL: Issues detected")
    print("="*60)
