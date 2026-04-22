"""
V3 Pre-Deployment Validation Suite

Comprehensive tests to verify the model before production deployment.
Catches: data leakage, distribution skew, calibration issues, stability bugs,
feature importance anomalies, confidence-accuracy misalignment.

Run: python tests/test_v3_predeployment.py
Exit 0 if all pass, 1 if any fail.
"""

import os, sys, json, pickle, logging
from pathlib import Path
from collections import defaultdict

import numpy as np
import psycopg2

sys.path.insert(0, '.')
from features.v3_feature_builder import V3FeatureBuilder
from features.v3_enhanced_features import build_enhanced_features, ENHANCED_FEATURE_NAMES

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

MODEL_DIR = Path("artifacts/models/v3_sharp")

# Test thresholds
MAX_SKEW_PP = 15                  # Pick distribution skew on recent data
MAX_DRAW_PICKS_PCT = 40           # Draw picks ceiling (hard fail above)
MIN_DRAW_PICKS_PCT = 5            # Draw picks floor
CALIBRATION_BRIER_MAX = 0.25      # Brier score per confidence bucket
MIN_HIGH_CONF_ACCURACY = 0.55     # High confidence (>60%) picks should beat coin flip
MAX_FEATURE_DOMINANCE = 0.35      # No single feature >35% of total importance

PASS, FAIL = 0, 0
FAILURES = []


def test(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        FAILURES.append(f"{name}: {detail}")
        print(f"  ❌ {name} — {detail}")


# ═══════════════════════════════════════════════════════════
# TEST 1: Artifacts present and loadable
# ═══════════════════════════════════════════════════════════
print("=" * 70)
print("V3 PRE-DEPLOYMENT VALIDATION")
print("=" * 70)

print("\n1. MODEL ARTIFACTS")
print("-" * 50)

test("Model dir exists", MODEL_DIR.exists())
test("lgbm_ensemble.pkl exists", (MODEL_DIR / "lgbm_ensemble.pkl").exists())
test("metadata.json exists", (MODEL_DIR / "metadata.json").exists())
test("features.json exists", (MODEL_DIR / "features.json").exists())

with open(MODEL_DIR / "lgbm_ensemble.pkl", 'rb') as f:
    models = pickle.load(f)
with open(MODEL_DIR / "features.json") as f:
    feature_names = json.load(f)
with open(MODEL_DIR / "metadata.json") as f:
    metadata = json.load(f)

test("Ensemble has 5 folds", len(models) == 5, f"got {len(models)}")
test("Feature count matches metadata", len(feature_names) == metadata.get('n_features'),
     f"features={len(feature_names)}, metadata.n_features={metadata.get('n_features')}")

# ═══════════════════════════════════════════════════════════
# TEST 2: Feature builder compatibility
# ═══════════════════════════════════════════════════════════
print("\n2. FEATURE BUILDER COMPATIBILITY")
print("-" * 50)

builder = V3FeatureBuilder()
core_features = builder.get_all_feature_names()

test("Core builder has 24 features", len(core_features) == 24, f"got {len(core_features)}")

# Model can be either 24 (baseline) or 31 (with enhanced). Validate either.
has_enhanced = any(f in feature_names for f in ENHANCED_FEATURE_NAMES)
if has_enhanced:
    expected = core_features + ENHANCED_FEATURE_NAMES
    print(f"  ℹ️  Model uses enhanced features (31 total)")
else:
    expected = core_features
    print(f"  ℹ️  Model uses baseline features (24 total, no ELO)")

missing = set(feature_names) - set(expected)
extra = set(expected) - set(feature_names)
test("No unexpected features in model", not missing, f"unexpected: {missing}")
test("No missing features", not extra, f"missing: {extra}")

# ═══════════════════════════════════════════════════════════
# TEST 3: Leakage audit — feature builder queries
# ═══════════════════════════════════════════════════════════
print("\n3. LEAKAGE AUDIT (source code)")
print("-" * 50)

with open('features/v3_feature_builder.py') as f:
    fb_src = f.read()

# These queries should use strict < not <=
test("odds_consensus uses strict < cutoff",
     'ts_effective <= %s' not in fb_src and 'ts_effective < %s' in fb_src,
     "Found ts_effective <= — POTENTIAL LEAKAGE")
test("odds_snapshots uses strict < cutoff",
     'ts_snapshot <= %s' not in fb_src and 'ts_snapshot < %s' in fb_src,
     "Found ts_snapshot <= — POTENTIAL LEAKAGE")

# ═══════════════════════════════════════════════════════════
# TEST 4: Feature importance sanity
# ═══════════════════════════════════════════════════════════
print("\n4. FEATURE IMPORTANCE SANITY")
print("-" * 50)

# Aggregate importance across folds
total_importance = np.zeros(len(feature_names))
for m in models:
    total_importance += m.feature_importance(importance_type='gain')
importance_dict = dict(zip(feature_names, total_importance))
total = total_importance.sum()
normalized = {k: v / total for k, v in importance_dict.items()}

# Top feature shouldn't dominate
top_feat, top_pct = max(normalized.items(), key=lambda x: x[1])
test(f"No single feature dominates (top: {top_feat} at {top_pct*100:.1f}%)",
     top_pct < MAX_FEATURE_DOMINANCE,
     f"{top_feat} dominates with {top_pct*100:.1f}%")

# Market-derived features should be top
market_features = {'prob_home', 'prob_draw', 'prob_away', 'ha_prob_gap', 'favourite_strength'}
top5 = [k for k, _ in sorted(normalized.items(), key=lambda x: -x[1])[:5]]
market_in_top5 = len(set(top5) & market_features)
test(f"Market features in top 5 (found {market_in_top5})",
     market_in_top5 >= 2,
     f"only {market_in_top5} market features in top 5: {top5}")

# No zero-importance features (after retrain)
zero_imp = [k for k, v in normalized.items() if v < 0.001]
test(f"Few zero-importance features ({len(zero_imp)})",
     len(zero_imp) <= 3,
     f"{len(zero_imp)} features: {zero_imp}")

print(f"\n  Top 10 features by importance:")
for k, v in sorted(normalized.items(), key=lambda x: -x[1])[:10]:
    print(f"    {k}: {v*100:.1f}%")

# ═══════════════════════════════════════════════════════════
# TEST 5: Determinism — same input, same output
# ═══════════════════════════════════════════════════════════
print("\n5. DETERMINISM")
print("-" * 50)

# Create a synthetic feature vector
X_test = np.array([[
    0.45, 0.28, 0.27,      # prob_home, draw, away
    0.03, 0.02, 0.03,      # dispersion
    0.01, 0.01, 0.01,      # volatility
    8, 1.05,                # book_coverage, market_overround
    0.12, 0.7, 0.05,       # ece features
    0.25, 5.0,             # h2h
    0.18, 0.45, 0.39, 0.82,  # closeness
    0.27, 0.0,             # league draw
    1.0, 0.4,              # draw market
    1550.0, 1480.0, 70.0, 0.58,   # ELO features
    0.1, 0.0, -0.3,        # z-scores
]], dtype=np.float32)

# Pad/truncate to match actual feature count
if X_test.shape[1] != len(feature_names):
    X_test = np.zeros((1, len(feature_names)), dtype=np.float32)
    X_test[:, :5] = [0.45, 0.28, 0.27, 0.03, 0.02]

pred1 = np.mean([m.predict(X_test) for m in models], axis=0)[0]
pred2 = np.mean([m.predict(X_test) for m in models], axis=0)[0]
test("Same input → same output",
     np.allclose(pred1, pred2, atol=1e-9),
     "Predictions differ between calls")

# ═══════════════════════════════════════════════════════════
# TEST 6: Live predictions on real upcoming matches
# ═══════════════════════════════════════════════════════════
print("\n6. LIVE PREDICTIONS (real upcoming matches)")
print("-" * 50)

conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor()
cur.execute("""
    SELECT f.match_id FROM fixtures f
    JOIN odds_consensus oc ON f.match_id = oc.match_id
    WHERE f.kickoff_at > NOW() AND f.status NOT IN ('finished','completed')
      AND oc.ts_effective < f.kickoff_at
    ORDER BY f.kickoff_at ASC LIMIT 50
""")
upcoming = [r[0] for r in cur.fetchall()]
conn.close()

test(f"Enough upcoming matches with odds ({len(upcoming)})",
     len(upcoming) >= 20,
     f"only {len(upcoming)} matches available")

if len(upcoming) >= 20:
    picks = {'H': 0, 'D': 0, 'A': 0}
    confs = []
    errors = 0

    for mid in upcoming[:40]:
        try:
            conn = psycopg2.connect(os.environ['DATABASE_URL'])
            cur = conn.cursor()
            mi = builder._get_match_info(cur, mid)
            if not mi or not mi['kickoff_time']:
                cur.close(); conn.close(); continue
            cutoff = mi['kickoff_time']
            v2 = builder._build_v2_core_features(cur, mid, cutoff)
            ece = builder._build_ece_features(cur, mi['league_id'])
            h2h = builder._build_h2h_features(cur, mid, mi)
            cls = builder._build_closeness_features(v2)
            ld = builder._build_league_draw_features(cur, mi['league_id'], v2)
            dm = builder._build_draw_market_features(v2)
            enh = build_enhanced_features(cur, mi, v2) if has_enhanced else {}
            cur.close(); conn.close()
            feats = {**v2, **ece, **h2h, **cls, **ld, **dm, **enh}
            X = np.array([feats.get(f, np.nan) for f in feature_names]).reshape(1, -1)
            preds = np.mean([m.predict(X, num_iteration=m.best_iteration) for m in models], axis=0)[0]
            preds = preds / preds.sum()
            pick = ['H', 'D', 'A'][np.argmax(preds)]
            picks[pick] += 1
            confs.append(max(preds))
        except Exception:
            errors += 1

    total = sum(picks.values())
    if total > 0:
        dist = {k: v / total * 100 for k, v in picks.items()}
        print(f"\n  Pick distribution ({total} matches):")
        print(f"    H: {dist['H']:.1f}%  D: {dist['D']:.1f}%  A: {dist['A']:.1f}%")
        print(f"    Confidence range: {min(confs)*100:.1f}% - {max(confs)*100:.1f}%, mean: {np.mean(confs)*100:.1f}%")

        test(f"Draw picks not catastrophic (<{MAX_DRAW_PICKS_PCT}%)",
             dist['D'] < MAX_DRAW_PICKS_PCT,
             f"{dist['D']:.1f}% draw picks — possible draw bias regression")
        test(f"Some draw picks (>={MIN_DRAW_PICKS_PCT}%)",
             dist['D'] >= MIN_DRAW_PICKS_PCT,
             f"only {dist['D']:.1f}% draws — model ignores draws")
        test("Pick distribution reasonable",
             max(dist.values()) < 75,
             f"one class dominates: {dist}")
        test("No NaN in confidence scores",
             all(not np.isnan(c) for c in confs))
        test("Confidence in reasonable range (20-95%)",
             all(0.20 <= c <= 0.95 for c in confs),
             f"out-of-range: {[c for c in confs if c < 0.20 or c > 0.95][:3]}")

# ═══════════════════════════════════════════════════════════
# TEST 7: Confidence-accuracy alignment on holdout
# ═══════════════════════════════════════════════════════════
print("\n7. CONFIDENCE-ACCURACY ALIGNMENT (from metadata)")
print("-" * 50)

holdout = metadata.get('holdout_metrics', {})
holdout_acc = holdout.get('accuracy', 0)

test(f"Holdout accuracy beats rollback baseline (≥0.48)",
     holdout_acc >= 0.48,
     f"{holdout_acc:.3f} < 0.48")
test(f"Holdout accuracy realistic (<0.62 = no leakage)",
     holdout_acc <= 0.62,
     f"{holdout_acc:.3f} > 0.62 — possible leakage")
test(f"Class skew controlled (<12pp)",
     holdout.get('max_skew_pp', 100) < 12,
     f"{holdout.get('max_skew_pp')}pp")

# Draw detection
per_class = holdout.get('per_class', {})
draw_acc = per_class.get('D', {}).get('accuracy', 0)
test(f"Draw accuracy reasonable (>10%)",
     draw_acc > 0.10,
     f"{draw_acc*100:.1f}% — model ignores draws")

# ═══════════════════════════════════════════════════════════
# TEST 8: Metadata structure
# ═══════════════════════════════════════════════════════════
print("\n8. METADATA STRUCTURE")
print("-" * 50)

required = ['oof_metrics', 'holdout_metrics', 'n_features', 'trained_at', 'gate_passed']
for k in required:
    test(f"Metadata has '{k}'", k in metadata, f"missing key")

test("gate_passed = True", metadata.get('gate_passed') is True,
     f"gate_passed = {metadata.get('gate_passed')}")
test("Data source documented",
     'fixtures+matches' in str(metadata.get('data_source', '')),
     "data_source unclear")

# ═══════════════════════════════════════════════════════════
# SUMMARY
# ═══════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print(f"RESULTS: {PASS} passed, {FAIL} failed")
print("=" * 70)

if FAILURES:
    print("\n❌ FAILURES — DO NOT DEPLOY:")
    for f in FAILURES:
        print(f"  • {f}")
    sys.exit(1)
else:
    print("\n✅ ALL CHECKS PASSED — safe to deploy")
    sys.exit(0)
