"""
WC Model Training + Honest Temporal-Holdout Validation
=======================================================
Trains a calibrated H/D/A model for international football on the 3,800+ match
history, and — applying the hard lesson from V3 — validates it against baselines
on a TEMPORAL holdout before anyone trusts it.

Features (all leak-safe, computed from pre-match state — NO market odds):
  - elo_diff          : (home_elo + HFA_if_not_neutral) − away_elo
  - expected_home     : ELO expected score in [0,1]
  - neutral           : 1 if neutral venue (most tournament games)
  - is_knockout       : 1 if knockout stage
  - home_form / away_form : points-per-game over each team's last 5 internationals
  - form_diff         : home_form − away_form
  - h2h_home_rate     : home team's historical win rate vs this opponent

Baselines the trained model must beat to justify itself:
  1. ELO argmax        — pure NationalEloModel.predict_proba (no training)
  2. Majority class    — always predict the most common outcome (home)

Decision: if the trained model does not beat the ELO baseline on the holdout,
SHIP THE ELO MODEL DIRECTLY (it's a legitimate standalone predictor). Don't
add a trained layer that only adds noise — exactly the V3 mistake.

Usage:
    python training/train_wc_model.py [--holdout-frac 0.2]
"""

import os
import re
import sys
import json
import argparse
import logging
from collections import deque, defaultdict
from pathlib import Path
from datetime import datetime, timezone

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))
os.chdir(REPO)
for ef in [".env.local", ".env"]:
    p = REPO / ef
    if p.exists():
        for line in p.read_text().splitlines():
            m = re.match(r"^([^#=\s][^=]*)=(.*)$", line)
            if m and not os.environ.get(m.group(1).strip()):
                os.environ[m.group(1).strip()] = m.group(2).strip()
        break

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("train_wc")

import numpy as np
import lightgbm as lgb
from models.national_elo import NationalEloModel, HOME_ADVANTAGE

parser = argparse.ArgumentParser()
parser.add_argument("--holdout-frac", type=float, default=0.2)
args = parser.parse_args()

OUTCOME_MAP = {"H": 0, "D": 1, "A": 2}
IDX = {0: "Home", 1: "Draw", 2: "Away"}
FEATURES = ["elo_diff", "expected_home", "neutral", "is_knockout",
            "home_form", "away_form", "form_diff", "h2h_home_rate"]

# ── Step 1: ELO history (chronological, pre-game state) ───────────────────────
logger.info("Building ELO history…")
elo = NationalEloModel()
history = elo.build_from_history(persist=False)   # don't overwrite live ratings during training
logger.info(f"Got {len(history)} matches with pre-game ELO")

# ── Step 2: enrich with leak-safe form + h2h (single chronological pass) ──────
last5 = defaultdict(lambda: deque(maxlen=5))   # team_id -> recent points (3/1/0)
h2h = defaultdict(lambda: [0, 0])              # (a,b) sorted -> [a_wins, total]

def form_ppg(team_id):
    d = last5[team_id]
    return sum(d) / len(d) if d else 1.0       # neutral prior 1.0 ppg

rows = []
for h in history:
    hid, aid = h["home_id"], h["away_id"]
    key = tuple(sorted((hid, aid)))
    hh, tot = h2h[key]
    # home team's win rate vs this opp (leak-safe: from prior meetings)
    if key[0] == hid:
        h2h_home_rate = (hh / tot) if tot else 0.5
    else:
        h2h_home_rate = ((tot - hh) / tot) if tot else 0.5

    rows.append({
        "elo_diff": h["elo_diff"],
        "expected_home": h["expected_home"],
        "neutral": h["neutral"],
        "is_knockout": h["is_knockout"],
        "home_form": form_ppg(hid),
        "away_form": form_ppg(aid),
        "form_diff": form_ppg(hid) - form_ppg(aid),
        "h2h_home_rate": h2h_home_rate,
        "outcome": h["outcome"],
        "expected_home_raw": h["expected_home"],   # kept for ELO baseline
        "match_date": h["match_date"],
    })

    # update form + h2h AFTER recording (leak-safe)
    o = h["outcome"]
    last5[hid].append(3 if o == "H" else (1 if o == "D" else 0))
    last5[aid].append(3 if o == "A" else (1 if o == "D" else 0))
    h2h[key][1] += 1
    if (o == "H" and key[0] == hid) or (o == "A" and key[0] == aid):
        h2h[key][0] += 1

# ── Step 3: temporal split ────────────────────────────────────────────────────
n = len(rows)
split = int(n * (1 - args.holdout_frac))
train, hold = rows[:split], rows[split:]
logger.info(f"Temporal split: train {len(train)} (early) / holdout {len(hold)} (recent)")

def Xy(data):
    X = np.array([[r[f] for f in FEATURES] for r in data], dtype=float)
    y = np.array([OUTCOME_MAP[r["outcome"]] for r in data])
    return X, y

X_tr, y_tr = Xy(train)
X_ho, y_ho = Xy(hold)

# ── Step 4: train LightGBM (draw-aware class weights) ─────────────────────────
counts = np.bincount(y_tr, minlength=3)
cw = np.sqrt(len(y_tr) / (3.0 * counts.clip(min=1)))
cw[1] *= 1.3   # mild draw boost (intl draw rate ~22%)
w = np.array([cw[c] for c in y_tr])
params = {"objective": "multiclass", "num_class": 3, "metric": "multi_logloss",
          "learning_rate": 0.03, "num_leaves": 16, "max_depth": 4,
          "min_data_in_leaf": 25, "feature_fraction": 0.8, "bagging_fraction": 0.8,
          "bagging_freq": 3, "lambda_l1": 0.3, "lambda_l2": 0.7, "verbose": -1, "seed": 42}
model = lgb.train(params, lgb.Dataset(X_tr, label=y_tr, weight=w), num_boost_round=250)

# ── Step 5: evaluate on holdout vs baselines ──────────────────────────────────
def acc(pred, y): return float((pred == y).mean())
def brier(proba, y):
    oh = np.zeros_like(proba); oh[np.arange(len(y)), y] = 1
    return float(((proba - oh) ** 2).sum(axis=1).mean())

# trained model
m_proba = model.predict(X_ho)
m_pred = m_proba.argmax(axis=1)
# ELO baseline: expected_home → argmax via predict_proba mapping
elo_proba = []
for r in hold:
    e = r["expected_home_raw"]
    d = max(0.08, 0.30 * (1 - 2 * abs(e - 0.5)))
    elo_proba.append([(1 - d) * e, d, (1 - d) * (1 - e)])
elo_proba = np.array(elo_proba)
elo_pred = elo_proba.argmax(axis=1)
# majority class
maj = np.full(len(y_ho), np.bincount(y_tr).argmax())

m_acc, e_acc, maj_acc = acc(m_pred, y_ho), acc(elo_pred, y_ho), acc(maj, y_ho)
m_brier, e_brier = brier(m_proba, y_ho), brier(elo_proba, y_ho)
nH = len(y_ho)
se = (m_acc * (1 - m_acc) / nH) ** 0.5

print("\n" + "=" * 60)
print("  WC MODEL — TEMPORAL HOLDOUT vs BASELINES")
print("=" * 60)
print(f"  Holdout matches: {nH}")
print(f"  {'Predictor':<22}{'Accuracy':>10}{'Brier':>10}")
print(f"  {'-'*42}")
print(f"  {'Trained LightGBM':<22}{m_acc:>9.1%}{m_brier:>10.4f}")
print(f"  {'ELO baseline':<22}{e_acc:>9.1%}{e_brier:>10.4f}")
print(f"  {'Majority (home)':<22}{maj_acc:>9.1%}{'—':>10}")
print(f"\n  Trained model 95% CI: [{m_acc-1.96*se:.1%}, {m_acc+1.96*se:.1%}]")
print("\n  Per-class (trained):")
for i, name in IDX.items():
    mask = y_ho == i
    if mask.sum():
        print(f"     {name:<6} {acc(m_pred[mask], y_ho[mask]):>6.1%}  (n={int(mask.sum())})")

print("\n  VERDICT:")
if m_acc >= e_acc and m_brier <= e_brier + 0.005:
    print(f"  ✅ Trained model beats/ties ELO ({m_acc:.1%} vs {e_acc:.1%}) — SHIP TRAINED MODEL")
    winner = "trained"
elif e_acc >= maj_acc:
    print(f"  ➖ Trained model doesn't beat ELO. ELO ({e_acc:.1%}) is solid — SHIP ELO DIRECTLY")
    winner = "elo"
else:
    print(f"  ❌ Neither beats majority-class meaningfully — international signal weak at this sample")
    winner = "elo"
print("=" * 60)

# Feature importance
imp = sorted(zip(FEATURES, model.feature_importance()), key=lambda kv: -kv[1])
print("\n  Feature importance (trained):")
for f, v in imp:
    print(f"     {f:<18} {v}")

# Save model + metadata
OUT = REPO / "artifacts" / "models" / "wc_model"
OUT.mkdir(parents=True, exist_ok=True)
model.save_model(str(OUT / "lgbm_wc.txt"))
(OUT / "features.json").write_text(json.dumps(FEATURES))
(OUT / "metadata.json").write_text(json.dumps({
    "trained_at": datetime.now(timezone.utc).isoformat(),
    "n_train": len(train), "n_holdout": nH,
    "trained_acc": m_acc, "elo_acc": e_acc, "majority_acc": maj_acc,
    "trained_brier": m_brier, "elo_brier": e_brier,
    "recommended": winner,
    "features": FEATURES,
}, indent=2))
logger.info(f"Saved WC model + metadata to {OUT} (recommended: {winner})")
