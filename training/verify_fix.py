#!/usr/bin/env python3
"""Verify the fix: parity should equal 1.0"""

# Test old formula (wrong)
def old_formula(rest_h, rest_a):
    return rest_h / (rest_a + 1.0)

# Test new formula (correct)
def new_formula(rest_h, rest_a):
    return (rest_h + 1.0) / (rest_a + 1.0)

print("Test Cases:")
print("="*60)

test_cases = [
    (5, 5, "Equal rest (5 days each)"),
    (7, 7, "Equal rest (7 days each)"),
    (3, 7, "Home disadvantage (3 vs 7)"),
    (7, 3, "Home advantage (7 vs 3)"),
    (0, 0, "Edge case: zero days")
]

for rest_h, rest_a, desc in test_cases:
    old = old_formula(rest_h, rest_a)
    new = new_formula(rest_h, rest_a)
    
    if rest_h == rest_a:
        expected = 1.0
        status_old = "✅" if abs(old - expected) < 0.01 else f"❌ (should be 1.0)"
        status_new = "✅" if abs(new - expected) < 0.01 else f"❌ (should be 1.0)"
    else:
        status_old = "?"
        status_new = "✅" if new > 0 else "❌"
    
    print(f"\n{desc}:")
    print(f"  Old formula: {rest_h}/({rest_a}+1) = {old:.3f} {status_old}")
    print(f"  New formula: ({rest_h}+1)/({rest_a}+1) = {new:.3f} {status_new}")

print("\n" + "="*60)
print("Conclusion:")
print("  Old formula: Incorrectly biases neutral cases below 1.0")
print("  New formula: Correctly represents parity as 1.0")
print("="*60)
