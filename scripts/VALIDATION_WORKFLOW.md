# Model Validation Workflow

## The three tests to run before any model deploy

### 1. Data quality check (embedded in every holdout)
The holdout query automatically excludes synthetic template odds
(ph=0.65/pd=0.25/pa=0.10 etc.) inserted by `fix_odds_consensus_backfill.py`.
If > 0 synthetic rows exist, a WARNING is printed — not a failure.
To purge them: see the "Delete synthetic odds" task chip in Claude Code.

### 2. Regression test (run after every retrain)
```bash
# First run after establishing a new baseline:
python scripts/model_regression_test.py --save-baseline

# After retraining a challenger model, compare before deploying:
python scripts/model_regression_test.py

# Or swap in a specific candidate directory:
python scripts/model_regression_test.py --challenger artifacts/models/lgbm_historical_36k_v2/
```

Hard thresholds (fail = exit code 1, blocks deploy):
- Accuracy < 45% (hard floor)
- Draw recall < 15% (hard floor — model must surface draws)
- Accuracy drop vs baseline > 2pp
- Brier worsening > 0.010
- Draw recall drop vs baseline > 5pp

### 3. Before/after comparison (run when changing class weights or architecture)
```bash
python /tmp/run_comparison.py   # see scripts/validate_v3_holdout.py for the query
```

---

## What the 2.0× draw weight change actually did (2026-05-08)

| | Before | After | Delta |
|---|---|---|---|
| 3-way accuracy | 56.0% | 52.0% | −4pp |
| Brier score | 0.1857 | 0.1918 | +0.006 |
| Draw recall | 0.0% | 37.5% | **+37.5pp** |
| Draw F1 | 0.0% | 31.6% | **+31.6pp** |
| Home recall | 86.1% | 66.7% | −19pp |

The original model predicted Home 54/75 times and never predicted Draw.
The 4pp accuracy drop is the expected cost of honest draw prediction.
For betting purposes the current model is strictly better — the old one
produced zero actionable draw picks.

---

## The data leak we found (2026-05-08)

`fix_odds_consensus_backfill.py` inserted synthetic "odds" into `odds_consensus`
for training_matches that had no real collected odds:

```python
if outcome == 'Home':   ph_cons, pd_cons, pa_cons = 0.65, 0.25, 0.10
elif outcome == 'Away': ph_cons, pd_cons, pa_cons = 0.10, 0.25, 0.65
else:                   ph_cons, pd_cons, pa_cons = 0.30, 0.40, 0.30
```

This caused 87.3% fake accuracy (74.6% of holdout matches were contaminated).
V3 sharp training was NOT contaminated (synthetic rows had ts_effective = kickoff,
excluded by the old `ts_effective < kickoff` filter).

Fix: `validate_v3_holdout.py` and `model_regression_test.py` both filter these out.
Database cleanup (DELETE ~6,310 rows) is tracked as a separate task.

---

## Continuous validation (recommended cron)

Add to crontab for weekly automated check:
```
0 6 * * 1  cd /path/to/repo && /opt/homebrew/bin/python3 scripts/model_regression_test.py >> logs/weekly_validation.log 2>&1
```

This will:
- Fail (exit 1) and log if the current deployed model has regressed vs its own baseline
- Warn if synthetic odds are accumulating in odds_consensus
- Provide a rolling record of model health over time
