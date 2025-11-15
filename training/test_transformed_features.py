#!/usr/bin/env python3
"""
Quick pilot test: Compare original vs transformed features
Goal: Verify transformations reduce uniqueness and pass sanity checks
"""
import os
os.environ['LD_LIBRARY_PATH'] = "/nix/store/xvzz97yk73hw03v5dhhz3j47ggwf1yq1-gcc-13.2.0-lib/lib"

import sys
sys.path.append('.')

from features.v2_feature_builder import V2FeatureBuilder
from features.v2_feature_builder_transformed import get_v2_feature_builder_transformed
from sqlalchemy import create_engine, text
import pandas as pd
from datetime import timedelta
from collections import Counter

# Sample matches
engine = create_engine(os.getenv('DATABASE_URL'))

query = text("""
    SELECT match_id, match_date
    FROM training_matches
    WHERE match_date >= '2025-08-01'
      AND match_date < '2025-11-15'
    ORDER BY match_date
    LIMIT 200
""")

with engine.connect() as conn:
    matches = pd.read_sql(query, conn)

print(f"Testing {len(matches)} matches...\n")

# Test 1: Original features (4 raw values)
print("="*60)
print("TEST 1: Original Features (Raw Values)")
print("="*60)

builder_orig = V2FeatureBuilder()
orig_patterns = []

for idx, row in matches.iterrows():
    try:
        cutoff = row['match_date'] - timedelta(hours=1)
        features = builder_orig.build_features(row['match_id'], cutoff)
        
        # Extract time features
        pattern = (
            features.get('rest_days_home', 7.0),
            features.get('rest_days_away', 7.0),
            features.get('schedule_congestion_home_7d', 0.0),
            features.get('schedule_congestion_away_7d', 0.0)
        )
        orig_patterns.append(pattern)
    except:
        continue

orig_counter = Counter(orig_patterns)
unique_orig = len(orig_counter)
total_orig = len(orig_patterns)
collision_rate_orig = 100 * (total_orig - unique_orig) / total_orig if total_orig > 0 else 0

print(f"Total patterns: {total_orig}")
print(f"Unique patterns: {unique_orig}")
print(f"Collision rate: {collision_rate_orig:.2f}%")
print(f"Uniqueness: {100 - collision_rate_orig:.2f}%")
print(f"\nTop 5 most common patterns:")
for pattern, count in orig_counter.most_common(5):
    print(f"  {pattern}: {count} matches ({100*count/total_orig:.1f}%)")

# Test 2: Transformed features (2 relative ratios)
print("\n" + "="*60)
print("TEST 2: Transformed Features (Relative Ratios)")
print("="*60)

builder_trans = get_v2_feature_builder_transformed(use_binned=False)
trans_patterns = []

for idx, row in matches.iterrows():
    try:
        cutoff = row['match_date'] - timedelta(hours=1)
        features = builder_trans.build_features(row['match_id'], cutoff)
        
        # Extract transformed features (round to 2 decimals to group similar)
        pattern = (
            round(features.get('rest_advantage', 1.0), 2),
            round(features.get('congestion_ratio', 1.0), 2)
        )
        trans_patterns.append(pattern)
    except:
        continue

trans_counter = Counter(trans_patterns)
unique_trans = len(trans_counter)
total_trans = len(trans_patterns)
collision_rate_trans = 100 * (total_trans - unique_trans) / total_trans if total_trans > 0 else 0

print(f"Total patterns: {total_trans}")
print(f"Unique patterns: {unique_trans}")
print(f"Collision rate: {collision_rate_trans:.2f}%")
print(f"Uniqueness: {100 - collision_rate_trans:.2f}%")
print(f"\nTop 5 most common patterns:")
for pattern, count in trans_counter.most_common(5):
    print(f"  rest_adv={pattern[0]}, cong_ratio={pattern[1]}: {count} matches ({100*count/total_trans:.1f}%)")

# Test 3: Binned features (4 binned values)
print("\n" + "="*60)
print("TEST 3: Binned Features (Coarse Buckets)")
print("="*60)

builder_binned = get_v2_feature_builder_transformed(use_binned=True)
binned_patterns = []

for idx, row in matches.iterrows():
    try:
        cutoff = row['match_date'] - timedelta(hours=1)
        features = builder_binned.build_features(row['match_id'], cutoff)
        
        # Extract binned features
        pattern = (
            features.get('rest_home_bin', 2.0),
            features.get('rest_away_bin', 2.0),
            features.get('congestion_home_bin', 0.0),
            features.get('congestion_away_bin', 0.0)
        )
        binned_patterns.append(pattern)
    except:
        continue

binned_counter = Counter(binned_patterns)
unique_binned = len(binned_counter)
total_binned = len(binned_patterns)
collision_rate_binned = 100 * (total_binned - unique_binned) / total_binned if total_binned > 0 else 0

print(f"Total patterns: {total_binned}")
print(f"Unique patterns: {unique_binned}")
print(f"Collision rate: {collision_rate_binned:.2f}%")
print(f"Uniqueness: {100 - collision_rate_binned:.2f}%")
print(f"\nTop 5 most common patterns:")
for pattern, count in binned_counter.most_common(5):
    print(f"  {pattern}: {count} matches ({100*count/total_binned:.1f}%)")

# Summary
print("\n" + "="*60)
print("SUMMARY: Uniqueness Reduction")
print("="*60)
print(f"Original (raw):       {100 - collision_rate_orig:.2f}% unique")
print(f"Transformed (ratios): {100 - collision_rate_trans:.2f}% unique")
print(f"Binned (buckets):     {100 - collision_rate_binned:.2f}% unique")

reduction_trans = (100 - collision_rate_orig) - (100 - collision_rate_trans)
reduction_binned = (100 - collision_rate_orig) - (100 - collision_rate_binned)

print(f"\nUniqueness reduction:")
print(f"  Transformed: {reduction_trans:.2f} percentage points")
print(f"  Binned: {reduction_binned:.2f} percentage points")

# Decision
print("\n" + "="*60)
print("RECOMMENDATION")
print("="*60)

if collision_rate_trans >= 50:
    print("✅ Use TRANSFORMED (relative ratios) - High collision rate!")
    print(f"   {collision_rate_trans:.1f}% collision rate is good")
elif collision_rate_binned >= 50:
    print("✅ Use BINNED (coarse buckets) - Good collision rate")
    print(f"   {collision_rate_binned:.1f}% collision rate is acceptable")
else:
    print("⚠️  Both still somewhat unique, but better than original")
    print(f"   Recommend testing both in ablation script")
    print(f"   Transformed: {collision_rate_trans:.1f}% collision")
    print(f"   Binned: {collision_rate_binned:.1f}% collision")
