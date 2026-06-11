"""
V3 Temporal Holdout Validation — Honest Out-of-Sample Test
===========================================================
Council-mandated (2026-06-02): before deploying/deleting/retraining anything,
prove the V3 model beats the trivial "always pick the bookmaker favorite"
baseline on matches it never trained on.

Why this and not validate_v3_holdout.py:
  - train_v3_sharp.py has NO upper date bound → the production model trained on
    everything, so its OOF metrics are not a clean out-of-sample test.
  - This script does a strict TEMPORAL split: train on the earliest X% of matches
    (chronologically), validate on the most recent (1-X)% the model never saw.
  - It computes the FAVORITE BASELINE (argmax of consensus odds) on the exact same
    holdout matches, so we answer the only question that matters:
        "Does the model do anything beyond reading the betting line?"

What it reports:
  - V3 accuracy vs Favorite-baseline accuracy (the headline gate)
  - Brier score for both (calibration / probabilistic quality)
  - Per-class accuracy + draw recall/precision
  - Log loss

Decision gate (council):
  PROCEED to deploy/A/B/C only if:
    V3_acc >= favorite_acc (at least ties)  AND
    V3_brier <= favorite_brier + 0.005       AND
    draw_recall >= 0.25
  Otherwise STOP — the model isn't beating the line and needs rethinking,
  not deployment.

Usage:
    python scripts/validate_temporal_holdout.py [--holdout-frac 0.2] [--draw-boost 1.5]

Run on Replit or anywhere with DATABASE_URL + training data.
"""

import os
import re
import sys
import json
import argparse
import logging
from pathlib import Path
from datetime import datetime, timezone

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))
os.chdir(REPO)

# Load env
for ef in [".env.local", ".env"]:
    p = REPO / ef
    if p.exists():
        for line in p.read_text().splitlines():
            m = re.match(r"^([^#=\s][^=]*)=(.*)$", line)
            if m and not os.environ.get(m.group(1).strip()):
                os.environ[m.group(1).strip()] = m.group(2).strip()
        break

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger("temporal_holdout")

import numpy as np
import lightgbm as lgb

from training.train_v3_sharp import (
    get_trainable_matches, build_training_dataset, compute_sample_weights,
)

parser = argparse.ArgumentParser()
parser.add_argument("--holdout-frac", type=float, default=0.2,
                    help="Fraction of most-recent matches to hold out (default 0.2)")
parser.add_argument("--draw-boost", type=float, default=1.5,
                    help="Draw class weight boost used in training (default 1.5)")
args = parser.parse_args()

OUTCOME_MAP = {"H": 0, "D": 1, "A": 2}
IDX_NAME = {0: "Home", 1: "Draw", 2: "Away"}

# ── Step 1: chronological match list ──────────────────────────────────────────
logger.info("Loading trainable matches (chronologically sorted)…")
matches = get_trainable_matches()  # [(match_id, outcome)] sorted by date
n = len(matches)
split = int(n * (1 - args.holdout_frac))
train_matches = matches[:split]
hold_matches = matches[split:]
logger.info(f"Total {n} matches → train {len(train_matches)} (early) / holdout {len(hold_matches)} (recent)")

# ── Step 2: build features for each split ─────────────────────────────────────
logger.info("Building features for TRAIN split…")
df_train = build_training_dataset(train_matches)
logger.info("Building features for HOLDOUT split…")
df_hold = build_training_dataset(hold_matches)

# Verify no match_id overlap (leakage guard)
overlap = set(df_train["match_id"]) & set(df_hold["match_id"])
if overlap:
    logger.error(f"❌ LEAKAGE: {len(overlap)} match_ids in both train and holdout — aborting")
    sys.exit(1)
logger.info(f"✅ No match_id overlap. Train={len(df_train)}, Holdout={len(df_hold)} usable samples")

if len(df_hold) < 150:
    logger.warning(f"⚠️  Holdout has only {len(df_hold)} samples — result will be noisy. "
                   f"Interpret CI accordingly.")

feature_cols = [c for c in df_train.columns if c not in ("match_id", "outcome")]

X_train = df_train[feature_cols].values
y_train = df_train["outcome"].map(OUTCOME_MAP).values
X_hold = df_hold[feature_cols].values
y_hold = df_hold["outcome"].map(OUTCOME_MAP).values

# ── Step 3: train on the EARLY split only ─────────────────────────────────────
logger.info(f"Training LightGBM on {len(X_train)} early matches (draw_boost={args.draw_boost})…")
sample_weights = compute_sample_weights(y_train, draw_boost=args.draw_boost)
params = {
    "objective": "multiclass", "num_class": 3, "metric": "multi_logloss",
    "boosting_type": "gbdt", "learning_rate": 0.02, "num_leaves": 20,
    "max_depth": 5, "min_data_in_leaf": 30, "feature_fraction": 0.7,
    "bagging_fraction": 0.7, "bagging_freq": 3, "lambda_l1": 0.5,
    "lambda_l2": 1.0, "verbose": -1, "force_row_wise": True, "seed": 42,
}
dtrain = lgb.Dataset(X_train, label=y_train, weight=sample_weights)
model = lgb.train(params, dtrain, num_boost_round=300)

# ── Step 4: predict on holdout ────────────────────────────────────────────────
v3_proba = model.predict(X_hold)               # (n,3)
v3_pick = v3_proba.argmax(axis=1)

# Favorite baseline: argmax of consensus implied probs (the betting line itself)
fav_cols = ["prob_home", "prob_draw", "prob_away"]
fav_proba = df_hold[fav_cols].values
# normalize (strip overround) for a fair Brier comparison
fav_norm = fav_proba / np.clip(fav_proba.sum(axis=1, keepdims=True), 1e-9, None)
fav_pick = fav_norm.argmax(axis=1)

# ── Step 5: metrics ───────────────────────────────────────────────────────────
def accuracy(pick, y):
    return float((pick == y).mean())

def brier(proba, y):
    onehot = np.zeros_like(proba)
    onehot[np.arange(len(y)), y] = 1.0
    return float(((proba - onehot) ** 2).sum(axis=1).mean())

def logloss(proba, y):
    p = np.clip(proba, 1e-12, 1.0)
    return float(-np.log(p[np.arange(len(y)), y]).mean())

v3_acc = accuracy(v3_pick, y_hold)
fav_acc = accuracy(fav_pick, y_hold)
v3_brier = brier(v3_proba, y_hold)
fav_brier = brier(fav_norm, y_hold)
v3_ll = logloss(v3_proba, y_hold)
fav_ll = logloss(fav_norm, y_hold)

# draw metrics for V3
draw_mask_true = (y_hold == 1)
draw_mask_pred = (v3_pick == 1)
draw_recall = float((v3_pick[draw_mask_true] == 1).mean()) if draw_mask_true.sum() else 0.0
draw_precision = float((y_hold[draw_mask_pred] == 1).mean()) if draw_mask_pred.sum() else 0.0

# per-class accuracy
per_class = {}
for idx, name in IDX_NAME.items():
    mask = (y_hold == idx)
    per_class[name] = (float((v3_pick[mask] == idx).mean()) if mask.sum() else 0.0, int(mask.sum()))

# Wilson 95% CI half-width for V3 accuracy
nH = len(y_hold)
se = (v3_acc * (1 - v3_acc) / nH) ** 0.5 if nH else 0.0
ci_lo, ci_hi = max(0, v3_acc - 1.96 * se), min(1, v3_acc + 1.96 * se)

# ── Report ────────────────────────────────────────────────────────────────────
print("\n" + "=" * 64)
print("  V3 TEMPORAL HOLDOUT — vs BOOKMAKER-FAVORITE BASELINE")
print("=" * 64)
print(f"  Holdout matches (most recent {args.holdout_frac:.0%}): {nH}")
print(f"  Holdout date span:  {df_hold['match_id'].count()} samples")
print()
print(f"  {'Metric':<22}{'V3 model':>12}{'Favorite':>12}{'Δ (V3−Fav)':>14}")
print(f"  {'-'*60}")
print(f"  {'Accuracy':<22}{v3_acc:>11.1%}{fav_acc:>12.1%}{(v3_acc-fav_acc):>+13.1%}")
print(f"  {'Brier (lower=better)':<22}{v3_brier:>12.4f}{fav_brier:>12.4f}{(v3_brier-fav_brier):>+14.4f}")
print(f"  {'LogLoss (lower=better)':<22}{v3_ll:>12.4f}{fav_ll:>12.4f}{(v3_ll-fav_ll):>+14.4f}")
print()
print(f"  V3 accuracy 95% CI:  [{ci_lo:.1%}, {ci_hi:.1%}]")
print()
print("  V3 per-class accuracy:")
for name, (acc, cnt) in per_class.items():
    print(f"     {name:<6} {acc:>6.1%}  (n={cnt})")
print(f"  Draw recall:    {draw_recall:.1%}")
print(f"  Draw precision: {draw_precision:.1%}")
print()

# ── Decision gate ─────────────────────────────────────────────────────────────
acc_ok = v3_acc >= fav_acc
brier_ok = v3_brier <= fav_brier + 0.005
draw_ok = draw_recall >= 0.25
print("  DECISION GATE (council):")
print(f"     V3 acc ≥ favorite acc ........ {'✅' if acc_ok else '❌'}  ({v3_acc:.1%} vs {fav_acc:.1%})")
print(f"     V3 Brier ≤ favorite + 0.005 .. {'✅' if brier_ok else '❌'}  ({v3_brier:.4f} vs {fav_brier+0.005:.4f})")
print(f"     Draw recall ≥ 25% ............ {'✅' if draw_ok else '❌'}  ({draw_recall:.1%})")
print()
if acc_ok and brier_ok and draw_ok:
    print("  ✅ PROCEED — V3 at least ties the line and adds draw coverage. Deploy/A/B/C justified.")
elif brier_ok and v3_acc >= fav_acc - 0.01:
    print("  ➖ MARGINAL — V3 roughly matches the line. Defensible as a calibrated baseline,")
    print("     but the edge is unproven. Deploy cautiously; prioritise non-market features.")
else:
    print("  ❌ STOP — V3 does NOT beat picking the favorite. Do not deploy on accuracy grounds.")
    print("     The model is echoing the line with added noise. Rethink before A/B/C.")
print("=" * 64)

# Persist result
result = {
    "validated_at": datetime.now(timezone.utc).isoformat(),
    "holdout_frac": args.holdout_frac,
    "n_holdout": nH,
    "v3_accuracy": v3_acc, "favorite_accuracy": fav_acc,
    "v3_brier": v3_brier, "favorite_brier": fav_brier,
    "v3_logloss": v3_ll, "favorite_logloss": fav_ll,
    "draw_recall": draw_recall, "draw_precision": draw_precision,
    "per_class": {k: v[0] for k, v in per_class.items()},
    "ci95": [ci_lo, ci_hi],
    "gate_passed": bool(acc_ok and brier_ok and draw_ok),
}
out = REPO / "scripts" / "temporal_holdout_result.json"
out.write_text(json.dumps(result, indent=2))
logger.info(f"Result saved to {out}")
