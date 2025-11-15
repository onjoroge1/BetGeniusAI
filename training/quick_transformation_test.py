#!/usr/bin/env python3
"""Quick test: Verify transformation logic reduces uniqueness"""
import sys
sys.path.append('.')
from sqlalchemy import create_engine, text
import os
from collections import Counter

engine = create_engine(os.getenv('DATABASE_URL'))

# Get raw context features from database
query = text("""
    SELECT 
        rest_days_home,
        rest_days_away,
        schedule_congestion_home_7d,
        schedule_congestion_away_7d
    FROM match_context
    LIMIT 1370
""")

with engine.connect() as conn:
    data = conn.execute(query).fetchall()

print(f"Analyzing {len(data)} matches...\n")

# Test 1: Original patterns
orig_patterns = [(row[0], row[1], row[2], row[3]) for row in data]
orig_counter = Counter(orig_patterns)
print("ORIGINAL (Raw Values):")
print(f"  Unique patterns: {len(orig_counter)} / {len(data)}")
print(f"  Uniqueness: {100*len(orig_counter)/len(data):.2f}%")
print(f"  Top pattern: {orig_counter.most_common(1)[0]}")

# Test 2: Transformed (relative ratios)
trans_patterns = []
for row in data:
    rest_h, rest_a, cong_h, cong_a = row
    rest_adv = round(rest_h / (rest_a + 1), 2)
    cong_ratio = round((cong_h + 1) / (cong_a + 1), 2)
    trans_patterns.append((rest_adv, cong_ratio))

trans_counter = Counter(trans_patterns)
print("\nTRANSFORMED (Relative Ratios):")
print(f"  Unique patterns: {len(trans_counter)} / {len(data)}")
print(f"  Uniqueness: {100*len(trans_counter)/len(data):.2f}%")
print(f"  Top pattern: {trans_counter.most_common(1)[0]}")

# Test 3: Binned
def bin_rest(days):
    if days <= 2: return 0
    elif days <= 4: return 1
    elif days <= 7: return 2
    else: return 3

def bin_cong(count):
    if count == 0: return 0
    elif count == 1: return 1
    elif count == 2: return 2
    else: return 3

binned_patterns = []
for row in data:
    rest_h, rest_a, cong_h, cong_a = row
    binned_patterns.append((
        bin_rest(rest_h),
        bin_rest(rest_a),
        bin_cong(cong_h),
        bin_cong(cong_a)
    ))

binned_counter = Counter(binned_patterns)
print("\nBINNED (Coarse Buckets):")
print(f"  Unique patterns: {len(binned_counter)} / {len(data)}")
print(f"  Uniqueness: {100*len(binned_counter)/len(data):.2f}%")
print(f"  Top pattern: {binned_counter.most_common(1)[0]}")

# Summary
print("\n" + "="*60)
print("SUMMARY")
print("="*60)
orig_uniq = 100*len(orig_counter)/len(data)
trans_uniq = 100*len(trans_counter)/len(data)
binned_uniq = 100*len(binned_counter)/len(data)

print(f"Original:    {orig_uniq:.2f}% unique ({len(orig_counter)} patterns)")
print(f"Transformed: {trans_uniq:.2f}% unique ({len(trans_counter)} patterns) - Reduction: {orig_uniq - trans_uniq:.2f}pp")
print(f"Binned:      {binned_uniq:.2f}% unique ({len(binned_counter)} patterns) - Reduction: {orig_uniq - binned_uniq:.2f}pp")

if trans_uniq < 50:
    print("\n✅ RECOMMENDED: Use transformed (relative ratios)")
    print(f"   {trans_uniq:.1f}% uniqueness is acceptable")
elif binned_uniq < 50:
    print("\n✅ RECOMMENDED: Use binned (coarse buckets)")
    print(f"   {binned_uniq:.1f}% uniqueness is acceptable")
else:
    print("\n⚠️  Both still high uniqueness, but improvement over original")
    print("   Proceed with transformed and test sanity checks")
