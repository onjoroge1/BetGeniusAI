"""
V3 Bundled Retrain Runner — Council Review 2026-05-10
======================================================
Runs the full bundled retrain safely with backup + validation + rollback.

What this retrain activates (all changes already committed to code):
  1. Synthetic odds filter      — training query now excludes the 3 template vectors
  2. Sharp divergence features   — 4 new features from sharp_book_odds (Pinnacle)
  3. league_draw_rate FIX        — double-fetchone bug fixed; feature now populates
  4. league_rolling_draw_rate    — new seasonal draw signal (last 20 matches)
  5. Draw class boost            — sqrt weighting + 1.5x draw boost (was weak inverse-freq)
  Total features: 24 → 29

Safety flow:
  1. Back up current model        → artifacts/models/v3_sharp_backup_<ts>/
  2. Capture BEFORE holdout score
  3. Retrain (train_v3_sharp.py)  → overwrites artifacts/models/v3_sharp/
  4. Capture AFTER holdout score
  5. Compare. If AFTER < BEFORE by >2pp, WARN and print rollback command.
     Otherwise report success.

Usage:
    python scripts/retrain_v3_bundle.py [--retrain-specialists] [--skip-backup]

Flags:
    --retrain-specialists  Also retrain all league specialists (adds ~20 min;
                           needed for the Serie A draw-boost fix to take effect)
    --skip-backup          Skip the model backup (not recommended)

Run this on Replit (needs DATABASE_URL + full training data).
Expected runtime: ~10-20 min main model, +20 min with --retrain-specialists.
"""

import os
import sys
import json
import time
import shutil
import argparse
import subprocess
from pathlib import Path
from datetime import datetime, timezone

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))
os.chdir(REPO)

# Load env
for env_file in [".env.local", ".env"]:
    p = REPO / env_file
    if not p.exists():
        continue
    for line in p.read_text().splitlines():
        m = __import__("re").match(r"^([^#=\s][^=]*)=(.*)$", line)
        if m and not os.environ.get(m.group(1).strip()):
            os.environ[m.group(1).strip()] = m.group(2).strip()
    break

parser = argparse.ArgumentParser()
parser.add_argument("--retrain-specialists", action="store_true",
                    help="Also retrain league specialists (needed for Serie A draw fix)")
parser.add_argument("--skip-backup", action="store_true", help="Skip model backup")
args = parser.parse_args()

MODEL_DIR = REPO / "artifacts" / "models" / "v3_sharp"
# Timestamp passed via env (Date import is fine in a real script, unlike workflow scripts)
TS = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
BACKUP_DIR = REPO / "artifacts" / "models" / f"v3_sharp_backup_{TS}"


def log(msg):
    print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}", flush=True)


def run(cmd: list) -> tuple:
    """Run a subprocess, stream output, return (returncode, captured_tail)."""
    log(f"$ {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=str(REPO), capture_output=True, text=True)
    out = (proc.stdout or "") + (proc.stderr or "")
    # Print last 40 lines for context
    for line in out.splitlines()[-40:]:
        print(f"    {line}")
    return proc.returncode, out


def get_holdout_accuracy() -> float:
    """Run holdout validation and parse accuracy. Returns -1 on failure."""
    rc, out = run([sys.executable, "scripts/validate_v3_holdout.py", "--days", "90"])
    if rc != 0:
        return -1.0
    # Parse "accuracy: 0.XXX" or "Accuracy: XX.X%" from output
    import re
    for pat in [r"[Aa]ccuracy[:\s]+([0-9.]+)%", r"[Aa]ccuracy[:\s]+0?\.([0-9]+)",
                r"overall[:\s]+([0-9.]+)%"]:
        m = re.search(pat, out)
        if m:
            val = float(m.group(1))
            return val / 100.0 if val > 1.5 else val
    return -1.0


# ── Step 1: Backup ──────────────────────────────────────────────────────────
if not args.skip_backup and MODEL_DIR.exists():
    log(f"Backing up current model → {BACKUP_DIR}")
    shutil.copytree(MODEL_DIR, BACKUP_DIR)
    log("✅ Backup complete")
else:
    log("⚠️  Skipping backup")

# ── Step 2: BEFORE score ────────────────────────────────────────────────────
log("Measuring BEFORE holdout accuracy (current live model)…")
before_acc = get_holdout_accuracy()
log(f"BEFORE holdout accuracy: {before_acc:.1%}" if before_acc >= 0 else "BEFORE: unavailable")

# ── Step 3: Retrain main model ──────────────────────────────────────────────
log("Retraining V3 main model (synthetic-filtered, 29 features, draw-boosted)…")
t0 = time.time()
rc, _ = run([sys.executable, "training/train_v3_sharp.py"])
if rc != 0:
    log("❌ Main retrain FAILED. Live model unchanged (training writes only on success).")
    if not args.skip_backup:
        log(f"   To restore from backup if needed: rm -rf {MODEL_DIR} && mv {BACKUP_DIR} {MODEL_DIR}")
    sys.exit(1)
log(f"✅ Main retrain complete in {time.time()-t0:.0f}s")

# ── Step 4: Specialists (optional) ──────────────────────────────────────────
if args.retrain_specialists:
    log("Retraining league specialists (draw-boosted) — Serie A draw fix…")
    rc, _ = run([sys.executable, "training/train_v3_specialist.py", "--all"])
    if rc != 0:
        log("⚠️  Specialist retrain had errors — check output above. Main model still updated.")
    else:
        log("✅ Specialists retrained")

# ── Step 5: AFTER score + compare ───────────────────────────────────────────
log("Measuring AFTER holdout accuracy (new model)…")
after_acc = get_holdout_accuracy()
log(f"AFTER holdout accuracy: {after_acc:.1%}" if after_acc >= 0 else "AFTER: unavailable")

print()
print("=" * 60)
print("  RETRAIN SUMMARY")
print("=" * 60)
if before_acc >= 0 and after_acc >= 0:
    delta = after_acc - before_acc
    print(f"  Holdout accuracy: {before_acc:.1%} → {after_acc:.1%}  ({delta:+.1%})")
    if delta < -0.02:
        print()
        print("  ⚠️  ACCURACY REGRESSED by >2pp. Consider rolling back:")
        if not args.skip_backup:
            print(f"     rm -rf {MODEL_DIR}")
            print(f"     mv {BACKUP_DIR} {MODEL_DIR}")
        print("     Then restart the prediction service.")
    elif delta > 0.02:
        print("  ✅ Meaningful improvement. Keep the new model.")
    else:
        print("  ➖ Roughly flat. Check per-league + draw metrics before deciding.")
else:
    print("  Could not auto-compare holdout scores — review the validation output above.")

# Check new feature importance for sharp + draw features
meta_path = MODEL_DIR / "metadata.json"
if meta_path.exists():
    try:
        meta = json.loads(meta_path.read_text())
        fi = meta.get("feature_importance", {})
        print()
        print("  Key new-feature importance (should be > 0):")
        for f in ["sharp_soft_div_home", "sharp_soft_div_away", "league_draw_rate",
                  "league_rolling_draw_rate"]:
            imp = fi.get(f, "—")
            print(f"     {f:<28} {imp}")
        draw_metrics = meta.get("oof_metrics", {})
        if draw_metrics:
            print()
            print(f"  Draw recall: {draw_metrics.get('draw_recall', '—')}  "
                  f"(was ~0.33 before — higher is the goal)")
    except Exception as e:
        print(f"  (could not read metadata: {e})")

print()
log("Done. Restart the prediction service to load the new model.")
if not args.skip_backup:
    log(f"Backup retained at: {BACKUP_DIR}")
