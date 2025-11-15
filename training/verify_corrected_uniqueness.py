#!/usr/bin/env python3
"""Verify uniqueness with CORRECTED formula"""
import sys
sys.path.append('.')
from sqlalchemy import create_engine, text
import os
from collections import Counter

engine = create_engine(os.getenv('DATABASE_URL'))

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

# Corrected transformation
trans_patterns = []
for row in data:
    rest_h, rest_a, cong_h, cong_a = row
    # CORRECTED: +1 to both numerator and denominator
    rest_adv = round((rest_h + 1) / (rest_a + 1), 2)
    cong_ratio = round((cong_h + 1) / (cong_a + 1), 2)
    trans_patterns.append((rest_adv, cong_ratio))

trans_counter = Counter(trans_patterns)

print("CORRECTED FORMULA RESULTS:")
print("="*60)
print(f"Total matches: {len(data)}")
print(f"Unique patterns: {len(trans_counter)}")
print(f"Uniqueness: {100*len(trans_counter)/len(data):.2f}%")
print(f"Collision rate: {100*(len(data) - len(trans_counter))/len(data):.2f}%")

print(f"\nTop 10 most common patterns:")
for pattern, count in trans_counter.most_common(10):
    print(f"  rest_adv={pattern[0]:.2f}, cong_ratio={pattern[1]:.2f}: {count} matches ({100*count/len(data):.1f}%)")

# Verification
if 100*len(trans_counter)/len(data) < 40:
    print("\n✅ PASS: Uniqueness < 40% (should pass sanity checks)")
else:
    print(f"\n⚠️  WARNING: Uniqueness still high but improved from 81.61%")

# Test parity cases
parity_pattern = (1.0, 1.0)  # Both teams equal rest and congestion
if parity_pattern in trans_counter:
    print(f"\n✅ Parity check: (1.0, 1.0) found {trans_counter[parity_pattern]} times")
else:
    print(f"\n⚠️  Parity pattern not found (expected some matches with equal rest)")
