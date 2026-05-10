"""
V3 holdout validation: last 60-90 days of completed matches.

For each match in the window that has a known outcome and odds_consensus data,
runs the current V3 predictor and compares its prediction against the actual result.

Reports:
  - Overall accuracy (3-way H/D/A)
  - Per-class accuracy (home / draw / away)
  - Draw precision + recall
  - Confidence distribution (mean, median, by tier)
  - Accuracy by confidence tier (<40% / 40-55% / 55-70% / >70%)
  - Brier score, LogLoss
  - Specialist override hit rate (for leagues 140, 78)

Usage:
    python scripts/validate_v3_holdout.py [--days 90] [--limit 200]
"""

import os
import sys
import json
import math
import argparse
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Dict, Optional

import psycopg2
import numpy as np

sys.path.append('.')

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ── ENV ──────────────────────────────────────────────────────────────────────

def _load_env():
    root = Path(__file__).parent.parent
    for name in ['.env.local', '.env']:
        p = root / name
        if not p.exists():
            continue
        for line in p.read_text().splitlines():
            m = __import__('re').match(r'^([^#=\s][^=]*)=(.*)$', line)
            if m:
                k, v = m.group(1).strip(), m.group(2).strip()
                if not os.environ.get(k):
                    os.environ[k] = v
        break

_load_env()

# ── ARGS ─────────────────────────────────────────────────────────────────────

parser = argparse.ArgumentParser()
parser.add_argument('--days', type=int, default=90, help='Lookback window in days (default: 90)')
parser.add_argument('--limit', type=int, default=0, help='Cap at N matches (0 = all)')
args = parser.parse_args()

DAYS = args.days
LIMIT = args.limit or None
CUTOFF_DATE = (datetime.now(timezone.utc) - timedelta(days=DAYS)).date().isoformat()

logger.info(f"Holdout validation: last {DAYS} days (from {CUTOFF_DATE})")

# ── FETCH MATCHES WITH KNOWN OUTCOMES ────────────────────────────────────────

conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor()

query = """
    SELECT match_id, league_id, kickoff_at, outcome FROM (
        -- Source 1: fixtures + matches (production data)
        SELECT
            f.match_id,
            f.league_id,
            f.kickoff_at,
            CASE
                WHEN m.home_goals > m.away_goals THEN 'H'
                WHEN m.home_goals < m.away_goals THEN 'A'
                ELSE 'D'
            END AS outcome
        FROM fixtures f
        JOIN matches m ON f.match_id = m.match_id
        JOIN odds_consensus oc ON f.match_id = oc.match_id
        WHERE f.status = 'finished'
          AND m.home_goals IS NOT NULL
          AND m.away_goals IS NOT NULL
          AND oc.ph_cons IS NOT NULL
          AND f.kickoff_at >= %(cutoff)s

        UNION

        -- Source 2: training_matches — exclude synthetic template odds backfilled from outcomes
        -- (fix_odds_consensus_backfill.py inserted ph=0.65/pd=0.25/pa=0.10 etc. based on known result)
        SELECT match_id, league_id, kickoff_at, outcome FROM (
            SELECT DISTINCT ON (tm.match_id)
                tm.match_id,
                NULL::int AS league_id,
                tm.match_date AS kickoff_at,
                CASE
                    WHEN tm.outcome IN ('H', 'Home') THEN 'H'
                    WHEN tm.outcome IN ('A', 'Away') THEN 'A'
                    WHEN tm.outcome IN ('D', 'Draw') THEN 'D'
                    ELSE NULL
                END AS outcome
            FROM training_matches tm
            JOIN odds_consensus oc ON tm.match_id = oc.match_id
            WHERE tm.outcome IS NOT NULL
              AND oc.ph_cons IS NOT NULL
              AND tm.match_date >= %(cutoff)s
              AND NOT (ABS(oc.ph_cons - 0.650) < 0.001 AND ABS(oc.pd_cons - 0.250) < 0.001 AND ABS(oc.pa_cons - 0.100) < 0.001)
              AND NOT (ABS(oc.ph_cons - 0.100) < 0.001 AND ABS(oc.pd_cons - 0.250) < 0.001 AND ABS(oc.pa_cons - 0.650) < 0.001)
              AND NOT (ABS(oc.ph_cons - 0.300) < 0.001 AND ABS(oc.pd_cons - 0.400) < 0.001 AND ABS(oc.pa_cons - 0.300) < 0.001)
            ORDER BY tm.match_id, tm.match_date
        ) tm2
        WHERE outcome IS NOT NULL
    ) combined
    WHERE outcome IS NOT NULL
    ORDER BY kickoff_at DESC
"""
if LIMIT:
    query += f" LIMIT {LIMIT}"

cur.execute(query, {'cutoff': CUTOFF_DATE})
rows = cur.fetchall()
cur.close()
conn.close()

logger.info(f"Found {len(rows)} completed matches in window")

if not rows:
    logger.error("No matches found — check DB connection and date range")
    sys.exit(1)

# ── LOAD PREDICTOR ────────────────────────────────────────────────────────────

from models.v3_predictor import V3Predictor

predictor = V3Predictor()

# ── RUN PREDICTIONS ───────────────────────────────────────────────────────────

OUTCOME_MAP = {'H': 'home', 'D': 'draw', 'A': 'away'}

results = []
errors = 0
skipped = 0

for i, (match_id, league_id, kickoff_at, outcome_code) in enumerate(rows):
    actual = OUTCOME_MAP.get(outcome_code)
    if not actual:
        skipped += 1
        continue
    try:
        pred = predictor.predict(match_id)
        if not pred:
            skipped += 1
            continue
        results.append({
            'match_id': match_id,
            'league_id': league_id,
            'kickoff_at': kickoff_at,
            'actual': actual,
            'predicted': pred['prediction'],
            'correct': pred['prediction'] == actual,
            'confidence': pred.get('calibrated_confidence') or pred.get('confidence', 0),
            'raw_confidence': pred.get('raw_confidence', 0),
            'probs': pred['probabilities'],
            'model': pred.get('model', 'v3_sharp'),
            'should_surface': pred.get('should_surface'),
            'specialist_check': pred.get('specialist_check'),
            'features_used': pred.get('features_used', 0),
            'total_features': pred.get('total_features', 24),
        })
    except Exception as e:
        errors += 1
        if errors <= 5:
            logger.warning(f"  match {match_id} failed: {e}")
    if (i + 1) % 50 == 0:
        logger.info(f"  Progress: {i+1}/{len(rows)} (ok={len(results)}, skip={skipped}, err={errors})")

logger.info(f"Evaluated {len(results)} matches ({skipped} skipped, {errors} errors)")

if not results:
    logger.error("No predictions produced — check model artifacts")
    sys.exit(1)

# ── METRICS ───────────────────────────────────────────────────────────────────

def pct(n, d):
    return f"{n/d*100:.1f}%" if d > 0 else "N/A"

n = len(results)
correct = sum(r['correct'] for r in results)
accuracy = correct / n

# Per-class accuracy
for cls in ('home', 'draw', 'away'):
    cls_results = [r for r in results if r['actual'] == cls]
    cls_correct = sum(r['correct'] for r in cls_results)
    n_cls = len(cls_results)
    preds_as_cls = [r for r in results if r['predicted'] == cls]
    tp = sum(r['correct'] for r in preds_as_cls)
    precision = tp / len(preds_as_cls) if preds_as_cls else 0
    recall = cls_correct / n_cls if n_cls > 0 else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
    logger.info(f"  {cls.upper():5s}: actual={n_cls:3d}  predicted={len(preds_as_cls):3d}  "
                f"accuracy={pct(cls_correct, n_cls):7s}  prec={precision*100:.1f}%  rec={recall*100:.1f}%  F1={f1*100:.1f}%")

# Confidence stats
confs = [r['confidence'] for r in results]
conf_mean = np.mean(confs)
conf_median = np.median(confs)

# Accuracy by confidence tier
tiers = [
    ('<40%',  lambda c: c < 0.40),
    ('40-55%', lambda c: 0.40 <= c < 0.55),
    ('55-70%', lambda c: 0.55 <= c < 0.70),
    ('>70%',  lambda c: c >= 0.70),
]

# Brier score & log loss
brier_scores = []
log_losses = []
for r in results:
    probs = r['probs']
    for cls, key in [('home', 'home'), ('draw', 'draw'), ('away', 'away')]:
        p = probs.get(key, 0)
        y = 1.0 if r['actual'] == cls else 0.0
        brier_scores.append((p - y) ** 2)
        if r['actual'] == cls:
            log_losses.append(-math.log(max(p, 1e-15)))

brier = np.mean(brier_scores)
logloss = np.mean(log_losses)

# Feature coverage
feat_pcts = [r['features_used'] / max(r['total_features'], 1) for r in results]
avg_feat_coverage = np.mean(feat_pcts)

# Model breakdown
model_counts: Dict[str, int] = {}
for r in results:
    m = r['model']
    model_counts[m] = model_counts.get(m, 0) + 1

# Specialist override stats (leagues 140, 78)
spec_matches = [r for r in results if r.get('specialist_check', {}).get('specialist_available')]
spec_overrides = [r for r in spec_matches if r.get('model') == 'v3_specialist']

# should_surface rate
surfaced = [r for r in results if r.get('should_surface')]
surfaced_correct = sum(r['correct'] for r in surfaced)

# ── PRINT REPORT ──────────────────────────────────────────────────────────────

SEP = "=" * 65

print(f"\n{SEP}")
print(f"  V3 HOLDOUT VALIDATION  |  Last {DAYS} days  |  {n} matches")
print(SEP)
print(f"\n  Overall 3-way Accuracy : {accuracy*100:.2f}%  ({correct}/{n})")
print(f"  Brier Score            : {brier:.4f}  (lower is better; uniform=0.222)")
print(f"  Log Loss               : {logloss:.4f}  (lower is better; uniform=1.099)")
print(f"  Mean Confidence        : {conf_mean*100:.1f}%")
print(f"  Median Confidence      : {conf_median*100:.1f}%")
print(f"  Avg Feature Coverage   : {avg_feat_coverage*100:.1f}%")

print(f"\n  --- Per-Class ---")
for cls in ('home', 'draw', 'away'):
    cls_results = [r for r in results if r['actual'] == cls]
    cls_correct = sum(r['correct'] for r in cls_results)
    preds_as_cls = [r for r in results if r['predicted'] == cls]
    tp = sum(r['correct'] for r in preds_as_cls)
    precision = tp / len(preds_as_cls) if preds_as_cls else 0
    recall = cls_correct / len(cls_results) if cls_results else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
    print(f"  {cls.upper():5s}: actual={len(cls_results):3d}  predicted={len(preds_as_cls):3d}  "
          f"acc={pct(cls_correct, len(cls_results)):7s}  prec={precision*100:.1f}%  "
          f"rec={recall*100:.1f}%  F1={f1*100:.1f}%")

print(f"\n  --- Accuracy by Confidence Tier ---")
for label, fn in tiers:
    tier_r = [r for r in results if fn(r['confidence'])]
    tier_correct = sum(r['correct'] for r in tier_r)
    print(f"  {label:8s}: n={len(tier_r):4d}  acc={pct(tier_correct, len(tier_r)):7s}  "
          f"avg_conf={np.mean([r['confidence'] for r in tier_r])*100:.1f}%" if tier_r else f"  {label:8s}: n=0")

print(f"\n  --- Model Breakdown ---")
for model, cnt in sorted(model_counts.items(), key=lambda x: -x[1]):
    mdl_correct = sum(r['correct'] for r in results if r['model'] == model)
    print(f"  {model:25s}: n={cnt:4d}  acc={pct(mdl_correct, cnt)}")

if spec_matches:
    print(f"\n  --- Specialist Leagues (140, 78) ---")
    print(f"  Matches with specialist: {len(spec_matches)}")
    print(f"  Overrides applied      : {len(spec_overrides)}")
    if spec_overrides:
        override_correct = sum(r['correct'] for r in spec_overrides)
        non_override = [r for r in spec_matches if r['model'] != 'v3_specialist']
        non_override_correct = sum(r['correct'] for r in non_override)
        print(f"  Override accuracy      : {pct(override_correct, len(spec_overrides))}")
        if non_override:
            print(f"  Main model accuracy    : {pct(non_override_correct, len(non_override))} (same leagues, no override)")

if surfaced:
    print(f"\n  --- Should-Surface Picks ---")
    print(f"  Surfaced: {len(surfaced)}/{n}  ({len(surfaced)/n*100:.1f}%)")
    print(f"  Surfaced accuracy: {pct(surfaced_correct, len(surfaced))}")

print(f"\n{SEP}\n")

# ── SAVE JSON REPORT ──────────────────────────────────────────────────────────

report = {
    'generated_at': datetime.now(timezone.utc).isoformat(),
    'days': DAYS,
    'n_matches': n,
    'accuracy_3way': round(accuracy, 4),
    'brier_score': round(float(brier), 4),
    'log_loss': round(float(logloss), 4),
    'mean_confidence': round(float(conf_mean), 4),
    'median_confidence': round(float(conf_median), 4),
    'avg_feature_coverage': round(float(avg_feat_coverage), 4),
    'per_class': {},
    'by_confidence_tier': {},
    'model_breakdown': {},
    'specialist': {
        'n_spec_matches': len(spec_matches),
        'n_overrides': len(spec_overrides),
    },
    'surfaced': {
        'n': len(surfaced),
        'accuracy': round(surfaced_correct / len(surfaced), 4) if surfaced else None,
    }
}
for cls in ('home', 'draw', 'away'):
    cls_results = [r for r in results if r['actual'] == cls]
    cls_correct = sum(r['correct'] for r in cls_results)
    preds_as_cls = [r for r in results if r['predicted'] == cls]
    tp = sum(r['correct'] for r in preds_as_cls)
    precision = tp / len(preds_as_cls) if preds_as_cls else 0
    recall = cls_correct / len(cls_results) if cls_results else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
    report['per_class'][cls] = {
        'n_actual': len(cls_results), 'n_predicted': len(preds_as_cls),
        'accuracy': round(cls_correct / len(cls_results), 4) if cls_results else None,
        'precision': round(precision, 4), 'recall': round(recall, 4), 'f1': round(f1, 4),
    }
for label, fn in tiers:
    tier_r = [r for r in results if fn(r['confidence'])]
    tier_correct = sum(r['correct'] for r in tier_r)
    report['by_confidence_tier'][label] = {
        'n': len(tier_r),
        'accuracy': round(tier_correct / len(tier_r), 4) if tier_r else None,
        'avg_conf': round(float(np.mean([r['confidence'] for r in tier_r])), 4) if tier_r else None,
    }
for model, cnt in model_counts.items():
    mdl_correct = sum(r['correct'] for r in results if r['model'] == model)
    report['model_breakdown'][model] = {'n': cnt, 'accuracy': round(mdl_correct / cnt, 4)}

out_path = Path('scripts/holdout_report.json')
out_path.write_text(json.dumps(report, indent=2))
logger.info(f"Report saved to {out_path}")
