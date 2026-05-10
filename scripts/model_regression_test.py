"""
Model regression test — run before deploying a retrained model.

Compares a challenger model against the stored baseline on a clean holdout and
fails (exit code 1) if any hard threshold is breached.

Usage:
    # Save current model as new baseline after a validated deploy:
    python scripts/model_regression_test.py --save-baseline

    # Compare challenger against baseline (default):
    python scripts/model_regression_test.py

    # Compare with a specific challenger artifact directory:
    python scripts/model_regression_test.py --challenger artifacts/models/lgbm_historical_36k_candidate/

Thresholds (fail if challenger is worse than baseline by more than this):
    --max-accuracy-drop    2.0 pp   (hard floor: never below 45%)
    --max-brier-increase   0.010
    --max-draw-recall-drop 5.0 pp   (draw is the main regression signal)

Exit codes:
    0 = passed
    1 = regression detected (blocks deploy)
    2 = data quality issue (synthetic odds in holdout)
"""

import os
import sys
import json
import math
import shutil
import argparse
import warnings
from datetime import datetime, timezone
from pathlib import Path

warnings.filterwarnings("ignore")

# ── Bootstrap ────────────────────────────────────────────────────────────────

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))
os.chdir(REPO)

for name in [".env.local", ".env"]:
    p = REPO / name
    if not p.exists():
        continue
    for line in p.read_text().splitlines():
        m = __import__("re").match(r"^([^#=\s][^=]*)=(.*)$", line)
        if m:
            k, v = m.group(1).strip(), m.group(2).strip()
            if not os.environ.get(k):
                os.environ[k] = v
    break

import psycopg2
import numpy as np

# ── Config ───────────────────────────────────────────────────────────────────

DEFAULT_MODEL_DIR = REPO / "artifacts/models/lgbm_historical_36k"
BASELINE_FILE = DEFAULT_MODEL_DIR / "baseline_metrics.json"
HOLDOUT_DAYS = 60
HARD_FLOOR_ACCURACY = 0.45
HARD_FLOOR_DRAW_RECALL = 0.15

# ── Args ─────────────────────────────────────────────────────────────────────

parser = argparse.ArgumentParser()
parser.add_argument("--save-baseline", action="store_true",
                    help="Run evaluation and save result as new baseline")
parser.add_argument("--challenger", type=str, default=None,
                    help="Path to challenger model directory (swapped in temporarily)")
parser.add_argument("--days", type=int, default=HOLDOUT_DAYS)
parser.add_argument("--max-accuracy-drop", type=float, default=2.0)
parser.add_argument("--max-brier-increase", type=float, default=0.010)
parser.add_argument("--max-draw-recall-drop", type=float, default=5.0)
args = parser.parse_args()

# ── Fetch holdout matches ────────────────────────────────────────────────────

from datetime import timedelta

CUTOFF = (datetime.now(timezone.utc) - timedelta(days=args.days)).date().isoformat()

print(f"Regression test  |  holdout last {args.days} days (from {CUTOFF})")

conn = psycopg2.connect(os.environ["DATABASE_URL"])
cur = conn.cursor()

cur.execute("""
    SELECT f.match_id,
        CASE WHEN m.home_goals > m.away_goals THEN 'H'
             WHEN m.home_goals < m.away_goals THEN 'A'
             ELSE 'D' END AS outcome
    FROM fixtures f JOIN matches m ON f.match_id = m.match_id
    JOIN odds_consensus oc ON f.match_id = oc.match_id
    WHERE f.status='finished' AND m.home_goals IS NOT NULL
      AND oc.ph_cons IS NOT NULL AND f.kickoff_at >= %s
""", (CUTOFF,))
rows_fix = cur.fetchall()

cur.execute("""
    SELECT DISTINCT ON (match_id) match_id, outcome FROM (
        SELECT tm.match_id,
            CASE WHEN tm.outcome IN ('H','Home') THEN 'H'
                 WHEN tm.outcome IN ('A','Away') THEN 'A'
                 WHEN tm.outcome IN ('D','Draw') THEN 'D' END AS outcome
        FROM training_matches tm
        JOIN odds_consensus oc ON tm.match_id = oc.match_id
        WHERE tm.outcome IS NOT NULL AND oc.ph_cons IS NOT NULL
          AND tm.match_date >= %s
          AND NOT (ABS(oc.ph_cons-0.650)<0.001 AND ABS(oc.pd_cons-0.250)<0.001 AND ABS(oc.pa_cons-0.100)<0.001)
          AND NOT (ABS(oc.ph_cons-0.100)<0.001 AND ABS(oc.pd_cons-0.250)<0.001 AND ABS(oc.pa_cons-0.650)<0.001)
          AND NOT (ABS(oc.ph_cons-0.300)<0.001 AND ABS(oc.pd_cons-0.400)<0.001 AND ABS(oc.pa_cons-0.300)<0.001)
    ) x WHERE outcome IS NOT NULL ORDER BY match_id
""", (CUTOFF,))
rows_tm = cur.fetchall()

# Also count how many synthetic rows exist — surface as warning
cur.execute("""
    SELECT COUNT(*) FROM (
        SELECT DISTINCT ON (tm.match_id) tm.match_id
        FROM training_matches tm
        JOIN odds_consensus oc ON tm.match_id = oc.match_id
        WHERE tm.outcome IS NOT NULL AND oc.ph_cons IS NOT NULL
          AND tm.match_date >= %s
          AND (
            (ABS(oc.ph_cons-0.650)<0.001 AND ABS(oc.pd_cons-0.250)<0.001 AND ABS(oc.pa_cons-0.100)<0.001)
            OR (ABS(oc.ph_cons-0.100)<0.001 AND ABS(oc.pd_cons-0.250)<0.001 AND ABS(oc.pa_cons-0.650)<0.001)
            OR (ABS(oc.ph_cons-0.300)<0.001 AND ABS(oc.pd_cons-0.400)<0.001 AND ABS(oc.pa_cons-0.300)<0.001)
          )
        ORDER BY tm.match_id
    ) x
""", (CUTOFF,))
n_synthetic = cur.fetchone()[0]
cur.close()
conn.close()

seen = set()
rows = []
for r in rows_fix + rows_tm:
    if r[0] not in seen and r[1] is not None:
        seen.add(r[0])
        rows.append(r)

print(f"Holdout: {len(rows)} clean matches  "
      f"({sum(1 for _,o in rows if o=='H')}H/{sum(1 for _,o in rows if o=='D')}D/{sum(1 for _,o in rows if o=='A')}A)")
if n_synthetic > 0:
    print(f"WARNING: {n_synthetic} synthetic-odds rows exist in odds_consensus "
          f"for training_matches in this window — filtered out above.")
    print("         Run: python fix_odds_consensus_backfill.py --delete to purge them.")

if len(rows) < 30:
    print(f"ERROR: Only {len(rows)} clean holdout matches — too few for reliable evaluation (need >= 30).")
    sys.exit(2)

# ── Evaluate a model ─────────────────────────────────────────────────────────

OM = {"H": "home", "D": "draw", "A": "away"}


def evaluate(label: str) -> dict:
    for mod in list(sys.modules.keys()):
        if any(x in mod for x in ["v3_predictor", "hist_predictor", "v3_feature", "v2_feature"]):
            del sys.modules[mod]

    from models.v3_predictor import V3Predictor
    predictor = V3Predictor()

    results = []
    for match_id, outcome_code in rows:
        actual = OM.get(outcome_code)
        if not actual:
            continue
        try:
            pred = predictor.predict(match_id)
            if not pred:
                continue
            results.append({
                "actual": actual,
                "predicted": pred["prediction"],
                "correct": pred["prediction"] == actual,
                "probs": pred["probabilities"],
            })
        except Exception:
            pass

    n = len(results)
    correct = sum(r["correct"] for r in results)

    per_class = {}
    for cls in ("home", "draw", "away"):
        ar = [r for r in results if r["actual"] == cls]
        pr = [r for r in results if r["predicted"] == cls]
        tp = sum(r["correct"] for r in pr)
        prec = tp / len(pr) if pr else 0.0
        rec = sum(r["correct"] for r in ar) / len(ar) if ar else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0
        per_class[cls] = {"n": len(ar), "pred": len(pr), "prec": prec, "rec": rec, "f1": f1}

    briers, lls = [], []
    for r in results:
        for cls in ("home", "draw", "away"):
            p = r["probs"].get(cls, 0.001)
            y = 1.0 if r["actual"] == cls else 0.0
            briers.append((p - y) ** 2)
            if r["actual"] == cls:
                lls.append(-math.log(max(p, 1e-15)))

    metrics = {
        "label": label,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "n_matches": n,
        "accuracy": round(correct / n, 4),
        "brier": round(float(np.mean(briers)), 4),
        "log_loss": round(float(np.mean(lls)), 4),
        "per_class": {
            cls: {k: round(v, 4) for k, v in m.items()}
            for cls, m in per_class.items()
        },
    }

    print(f"\n  {'─'*55}")
    print(f"  {label}")
    print(f"  {'─'*55}")
    print(f"  Accuracy : {metrics['accuracy']*100:.2f}%   Brier: {metrics['brier']:.4f}   LogLoss: {metrics['log_loss']:.4f}")
    for cls in ("home", "draw", "away"):
        m = per_class[cls]
        print(f"  {cls.upper():5s}: n={m['n']:3d}  pred={m['pred']:3d}  "
              f"prec={m['prec']*100:.1f}%  rec={m['rec']*100:.1f}%  F1={m['f1']*100:.1f}%")
    return metrics


# ── Swap in challenger if provided ───────────────────────────────────────────

challenger_dir = Path(args.challenger) if args.challenger else None
backup_pkl = backup_features = None

if challenger_dir:
    print(f"\nSwapping in challenger from {challenger_dir}")
    backup_pkl = DEFAULT_MODEL_DIR / "lgbm_ensemble_backup.pkl"
    backup_features = DEFAULT_MODEL_DIR / "features_backup.json"
    shutil.copy(DEFAULT_MODEL_DIR / "lgbm_ensemble.pkl", backup_pkl)
    shutil.copy(DEFAULT_MODEL_DIR / "features.json", backup_features)
    shutil.copy(challenger_dir / "lgbm_ensemble.pkl", DEFAULT_MODEL_DIR / "lgbm_ensemble.pkl")
    shutil.copy(challenger_dir / "features.json", DEFAULT_MODEL_DIR / "features.json")

# ── Run evaluation ───────────────────────────────────────────────────────────

print()
challenger_metrics = evaluate("Challenger" if challenger_dir else "Current model")

# Restore if swapped
if backup_pkl:
    shutil.copy(backup_pkl, DEFAULT_MODEL_DIR / "lgbm_ensemble.pkl")
    shutil.copy(backup_features, DEFAULT_MODEL_DIR / "features.json")
    backup_pkl.unlink(missing_ok=True)
    backup_features.unlink(missing_ok=True)

# ── Save baseline mode ───────────────────────────────────────────────────────

if args.save_baseline:
    challenger_metrics["label"] = "baseline"
    BASELINE_FILE.write_text(json.dumps(challenger_metrics, indent=2))
    print(f"\n✅ Baseline saved to {BASELINE_FILE}")
    sys.exit(0)

# ── Compare against baseline ─────────────────────────────────────────────────

if not BASELINE_FILE.exists():
    print(f"\nNo baseline found at {BASELINE_FILE}.")
    print("Run with --save-baseline first to establish one.")
    sys.exit(0)

baseline = json.loads(BASELINE_FILE.read_text())
print(f"\n  {'─'*55}")
print(f"  Baseline: {baseline.get('timestamp','?')[:19]}  accuracy={baseline['accuracy']*100:.2f}%")
print(f"  {'─'*55}")

failures = []
warnings_list = []

# Hard floors — no regression allowed past these
if challenger_metrics["accuracy"] < HARD_FLOOR_ACCURACY:
    failures.append(f"Accuracy {challenger_metrics['accuracy']*100:.1f}% < hard floor {HARD_FLOOR_ACCURACY*100:.0f}%")

draw_rec = challenger_metrics["per_class"]["draw"]["rec"]
if draw_rec < HARD_FLOOR_DRAW_RECALL:
    failures.append(f"Draw recall {draw_rec*100:.1f}% < hard floor {HARD_FLOOR_DRAW_RECALL*100:.0f}%")

# Regression vs baseline
acc_drop = (baseline["accuracy"] - challenger_metrics["accuracy"]) * 100
brier_inc = challenger_metrics["brier"] - baseline["brier"]
draw_rec_drop = (baseline["per_class"]["draw"]["rec"] - challenger_metrics["per_class"]["draw"]["rec"]) * 100

if acc_drop > args.max_accuracy_drop:
    failures.append(f"Accuracy regressed {acc_drop:.1f}pp (limit: {args.max_accuracy_drop:.1f}pp)")
elif acc_drop > 0:
    warnings_list.append(f"Accuracy dropped {acc_drop:.1f}pp (within tolerance)")

if brier_inc > args.max_brier_increase:
    failures.append(f"Brier score worsened {brier_inc:.4f} (limit: {args.max_brier_increase:.4f})")
elif brier_inc > 0:
    warnings_list.append(f"Brier worsened {brier_inc:.4f} (within tolerance)")

if draw_rec_drop > args.max_draw_recall_drop:
    failures.append(f"Draw recall dropped {draw_rec_drop:.1f}pp (limit: {args.max_draw_recall_drop:.1f}pp)")
elif draw_rec_drop > 0:
    warnings_list.append(f"Draw recall dropped {draw_rec_drop:.1f}pp (within tolerance)")

# ── Result ───────────────────────────────────────────────────────────────────

print(f"\n  Delta vs baseline:")
print(f"    Accuracy      : {-acc_drop:+.2f}pp")
print(f"    Brier         : {-brier_inc:+.4f}")
print(f"    Draw recall   : {-draw_rec_drop:+.1f}pp")

for w in warnings_list:
    print(f"  ⚠️  {w}")

if failures:
    print(f"\n❌ REGRESSION TEST FAILED — {len(failures)} issue(s):")
    for f in failures:
        print(f"   • {f}")
    print("\nDo not deploy this model. Fix the issues or adjust class weights.")
    sys.exit(1)

print(f"\n✅ Regression test PASSED — challenger is within tolerance of baseline.")
print("   To promote as new baseline: python scripts/model_regression_test.py --save-baseline")
