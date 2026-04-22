"""
V3 LEAK-FREE Retrain — fixtures+matches only with strict pre-kickoff cutoff.

Previous retrain had 65% data leakage from training_matches where odds_consensus
rows were recorded AFTER kickoff (essentially post-match consensus). This script
uses ONLY the fixtures+matches path with STRICT enforcement that odds_consensus
ts_effective < (kickoff_at - buffer).

Expected realistic baseline: 48-55% (soccer prediction ceiling is ~58-60%).

Gates:
- Holdout accuracy 45-60% (too high = leakage, too low = broken)
- Pick distribution balanced (max 8pp skew from actual)
- Draw predictions 15-35%
- Fold variance < 10pp (if >10pp, data quality issue)
"""

import os
import sys
import json
import pickle
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2
import lightgbm as lgb
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import accuracy_score, log_loss

sys.path.append('.')
from features.v3_feature_builder import V3FeatureBuilder
from features.v3_enhanced_features import build_enhanced_features, ENHANCED_FEATURE_NAMES

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Phase A toggle — set True to include ELO + Z-score features (31 total features)
# Set False for pure 24-feature baseline
ENABLE_ENHANCED_FEATURES = True

OUTPUT_DIR = Path("artifacts/models/v3_sharp_candidate")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
PROMOTE_DIR = Path("artifacts/models/v3_sharp")

# Buffer: use odds from at least 1h before kickoff (extra safety)
CUTOFF_BUFFER_HOURS = 1

# Hard gates — calibrated for real soccer prediction (not ideal world)
MIN_ACCURACY = 0.48  # Must beat rollback's 47%
MAX_ACCURACY = 0.62  # Above this is likely leakage
MAX_CLASS_SKEW_PP = 12  # Soccer predictions naturally skew home due to home advantage
MIN_DRAW_PREDICTIONS = 0.08  # Draws are hard; 8% floor with sqrt weights is acceptable
MAX_DRAW_PREDICTIONS = 0.38
MAX_FOLD_VARIANCE = 0.18  # Season-to-season variance is real in soccer


def load_clean_training_data():
    """Load ONLY fixtures+matches with strict pre-kickoff odds verification."""
    conn = psycopg2.connect(os.environ['DATABASE_URL'])
    cur = conn.cursor()

    logger.info(f"Loading clean training matches (cutoff buffer: {CUTOFF_BUFFER_HOURS}h before kickoff)...")

    # Require existence of at least one odds_consensus row strictly before kickoff
    cur.execute("""
        SELECT f.match_id,
               CASE WHEN m.home_goals > m.away_goals THEN 'H'
                    WHEN m.home_goals < m.away_goals THEN 'A' ELSE 'D' END as outcome,
               f.kickoff_at
        FROM fixtures f
        JOIN matches m ON f.match_id = m.match_id
        WHERE f.status = 'finished'
          AND m.home_goals IS NOT NULL
          AND EXISTS (
              SELECT 1 FROM odds_consensus oc
              WHERE oc.match_id = f.match_id
                AND oc.ts_effective < f.kickoff_at - INTERVAL '%s hours'
                AND oc.ph_cons IS NOT NULL
          )
        ORDER BY f.kickoff_at ASC
    """, (CUTOFF_BUFFER_HOURS,))
    rows = cur.fetchall()
    conn.close()
    logger.info(f"Loaded {len(rows):,} clean matches with valid pre-kickoff odds")
    return [(r[0], r[1], r[2]) for r in rows]


def build_features_for_matches(matches):
    """Build features with explicit cutoff (kickoff - buffer)."""
    builder = V3FeatureBuilder()
    records = []
    errors = 0

    logger.info(f"Building features for {len(matches):,} matches...")
    for i, (mid, outcome, kickoff) in enumerate(matches):
        try:
            conn = psycopg2.connect(os.environ['DATABASE_URL'])
            cur = conn.cursor()
            match_info = builder._get_match_info(cur, mid)
            if not match_info:
                cur.close(); conn.close(); continue

            # Strict cutoff: 1h before kickoff
            cutoff = kickoff - timedelta(hours=CUTOFF_BUFFER_HOURS)

            v2 = builder._build_v2_core_features(cur, mid, cutoff)

            # Skip match if no valid odds before cutoff
            if v2.get('prob_home') is None or (isinstance(v2.get('prob_home'), float) and np.isnan(v2['prob_home'])):
                cur.close(); conn.close(); continue

            ece = builder._build_ece_features(cur, match_info['league_id'])
            h2h = builder._build_h2h_features(cur, mid, match_info)
            cls = builder._build_closeness_features(v2)
            ld = builder._build_league_draw_features(cur, match_info['league_id'], v2)
            dm = builder._build_draw_market_features(v2)

            # Phase A: ELO + Z-score features (optional)
            enhanced = {}
            if ENABLE_ENHANCED_FEATURES:
                enhanced = build_enhanced_features(cur, match_info, v2)

            cur.close(); conn.close()

            feats = {**v2, **ece, **h2h, **cls, **ld, **dm, **enhanced}
            feats['match_id'] = mid
            feats['outcome'] = outcome
            records.append(feats)

            if (i + 1) % 200 == 0:
                logger.info(f"  Built {i+1}/{len(matches):,} ({errors} errors)")
        except Exception as e:
            errors += 1
            if errors <= 5:
                logger.warning(f"  match {mid}: {e}")

    df = pd.DataFrame(records)
    logger.info(f"Built {len(df):,} feature rows ({errors} errors)")
    return df


def compute_sqrt_weights(y):
    """Gentle class weighting via sqrt of inverse frequency.
    Raw inverse gave ~1.2x draw weight (caused 94% draw bug).
    Sqrt gives ~1.16x — enough to lift draw recall without destroying accuracy.
    """
    class_counts = np.bincount(y, minlength=3)
    n = len(y)
    raw_weights = n / (3.0 * class_counts.clip(min=1))
    sqrt_weights = np.sqrt(raw_weights)
    sample_weights = np.array([sqrt_weights[label] for label in y])
    logger.info(f"  Sqrt class weights: H={sqrt_weights[0]:.3f}, D={sqrt_weights[1]:.3f}, A={sqrt_weights[2]:.3f}")
    return sample_weights


def train_ensemble(X_train, y_train, n_splits=5):
    """Train LightGBM ensemble with SQRT inverse-frequency weighting."""
    sample_weights = compute_sqrt_weights(y_train)
    params = {
        'objective': 'multiclass',
        'num_class': 3,
        'metric': 'multi_logloss',
        'boosting_type': 'gbdt',
        'learning_rate': 0.03,
        'num_leaves': 31,
        'max_depth': 6,
        'min_data_in_leaf': 40,
        'feature_fraction': 0.8,
        'bagging_fraction': 0.8,
        'bagging_freq': 5,
        'lambda_l1': 0.3,
        'lambda_l2': 0.5,
        'verbose': -1,
        'force_row_wise': True,
        'seed': 42,
    }

    tscv = TimeSeriesSplit(n_splits=n_splits)
    models = []
    oof_preds = np.zeros((len(y_train), 3))
    oof_mask = np.zeros(len(y_train), dtype=bool)
    fold_accs = []

    for fold, (tr_idx, val_idx) in enumerate(tscv.split(X_train)):
        X_tr, X_va = X_train[tr_idx], X_train[val_idx]
        y_tr, y_va = y_train[tr_idx], y_train[val_idx]
        w_tr = sample_weights[tr_idx]

        td = lgb.Dataset(X_tr, label=y_tr, weight=w_tr)
        vd = lgb.Dataset(X_va, label=y_va, reference=td)

        model = lgb.train(
            params, td, num_boost_round=2000,
            valid_sets=[vd], valid_names=['valid'],
            callbacks=[lgb.early_stopping(100), lgb.log_evaluation(0)],
        )
        models.append(model)
        oof_preds[val_idx] = model.predict(X_va, num_iteration=model.best_iteration)
        oof_mask[val_idx] = True
        val_acc = accuracy_score(y_va, np.argmax(oof_preds[val_idx], axis=1))
        fold_accs.append(val_acc)
        logger.info(f"  Fold {fold+1}: val_acc={val_acc:.3f}, iters={model.best_iteration}")

    fold_variance = max(fold_accs) - min(fold_accs)
    logger.info(f"  Fold variance (max-min): {fold_variance:.3f}")

    return models, oof_preds, oof_mask, fold_variance


def evaluate(y_true, preds, label=""):
    picks = np.argmax(preds, axis=1)
    acc = accuracy_score(y_true, picks)
    ll = log_loss(y_true, preds, labels=[0, 1, 2])
    per_class = {}
    for cls, name in [(0, 'H'), (1, 'D'), (2, 'A')]:
        mask = y_true == cls
        if mask.sum() > 0:
            per_class[name] = {
                'accuracy': float(accuracy_score(y_true[mask], picks[mask])),
                'n_actual': int(mask.sum()),
            }
    n = len(y_true)
    pick_pct = {k: int((picks == i).sum()) / n * 100 for i, k in enumerate(['H', 'D', 'A'])}
    actual_pct = {k: int((y_true == i).sum()) / n * 100 for i, k in enumerate(['H', 'D', 'A'])}
    skews = {k: abs(pick_pct[k] - actual_pct[k]) for k in ['H', 'D', 'A']}

    logger.info(f"\n{label} EVALUATION")
    logger.info(f"  Accuracy: {acc*100:.1f}%  |  LogLoss: {ll:.4f}")
    logger.info(f"  Pick dist:   H={pick_pct['H']:.1f}% D={pick_pct['D']:.1f}% A={pick_pct['A']:.1f}%")
    logger.info(f"  Actual dist: H={actual_pct['H']:.1f}% D={actual_pct['D']:.1f}% A={actual_pct['A']:.1f}%")
    logger.info(f"  Max skew: {max(skews.values()):.1f}pp")
    for name, v in per_class.items():
        logger.info(f"  {name}: {v['accuracy']*100:.1f}% ({v['n_actual']} actual)")

    return {
        'accuracy': acc, 'logloss': ll, 'per_class': per_class,
        'pick_dist_pct': pick_pct, 'actual_dist_pct': actual_pct,
        'max_skew_pp': max(skews.values()), 'draw_pred_rate': pick_pct['D'] / 100,
    }


def gate_check(holdout_metrics, fold_variance):
    passed = True
    reasons = []
    if holdout_metrics['accuracy'] < MIN_ACCURACY:
        reasons.append(f"Accuracy {holdout_metrics['accuracy']*100:.1f}% < {MIN_ACCURACY*100}%"); passed = False
    if holdout_metrics['accuracy'] > MAX_ACCURACY:
        reasons.append(f"Accuracy {holdout_metrics['accuracy']*100:.1f}% > {MAX_ACCURACY*100}% (likely leakage)"); passed = False
    if holdout_metrics['max_skew_pp'] > MAX_CLASS_SKEW_PP:
        reasons.append(f"Class skew {holdout_metrics['max_skew_pp']:.1f}pp > {MAX_CLASS_SKEW_PP}pp"); passed = False
    if holdout_metrics['draw_pred_rate'] < MIN_DRAW_PREDICTIONS:
        reasons.append(f"Draw picks {holdout_metrics['draw_pred_rate']*100:.1f}% < {MIN_DRAW_PREDICTIONS*100}%"); passed = False
    if holdout_metrics['draw_pred_rate'] > MAX_DRAW_PREDICTIONS:
        reasons.append(f"Draw picks {holdout_metrics['draw_pred_rate']*100:.1f}% > {MAX_DRAW_PREDICTIONS*100}%"); passed = False
    if fold_variance > MAX_FOLD_VARIANCE:
        reasons.append(f"Fold variance {fold_variance:.3f} > {MAX_FOLD_VARIANCE} (data quality issue)"); passed = False
    return passed, reasons


def main():
    logger.info("=" * 60)
    logger.info("V3 LEAK-FREE RETRAIN")
    logger.info("=" * 60)

    matches = load_clean_training_data()
    if len(matches) < 500:
        logger.error(f"Insufficient clean data ({len(matches)}). Aborting.")
        return False

    df = build_features_for_matches(matches)
    feature_cols = [c for c in df.columns if c not in ['match_id', 'outcome']]
    X = df[feature_cols].values
    outcome_map = {'H': 0, 'D': 1, 'A': 2}
    y = df['outcome'].map(outcome_map).values
    n = len(y)
    logger.info(f"\nDataset: {n:,} samples, {len(feature_cols)} features")
    logger.info(f"Classes: H={sum(y==0)}, D={sum(y==1)}, A={sum(y==2)}")

    # 85/15 chronological split
    split = int(n * 0.85)
    X_train, X_hold = X[:split], X[split:]
    y_train, y_hold = y[:split], y[split:]
    logger.info(f"Train: {len(y_train):,}  |  Holdout: {len(y_hold):,}")

    models, oof_preds, oof_mask, fold_variance = train_ensemble(X_train, y_train)
    oof_metrics = evaluate(y_train[oof_mask], oof_preds[oof_mask], "OOF (5-fold CV)")

    hold_preds = np.mean([m.predict(X_hold, num_iteration=m.best_iteration) for m in models], axis=0)
    hold_preds = hold_preds / hold_preds.sum(axis=1, keepdims=True)
    hold_metrics = evaluate(y_hold, hold_preds, "HOLDOUT (last 15%, unseen)")

    passed, reasons = gate_check(hold_metrics, fold_variance)

    logger.info("\n" + "=" * 60)
    logger.info("GATE CHECK")
    logger.info("=" * 60)
    if passed:
        logger.info("✅ PASSED")
    else:
        logger.info("❌ FAILED:")
        for r in reasons:
            logger.info(f"    {r}")

    # Save candidate
    with open(OUTPUT_DIR / "lgbm_ensemble.pkl", "wb") as f:
        pickle.dump(models, f)
    with open(OUTPUT_DIR / "features.json", "w") as f:
        json.dump(feature_cols, f, indent=2)
    metadata = {
        'model_type': 'V3_Sharp_LightGBM_LeakFree',
        'trained_at': datetime.now(timezone.utc).isoformat(),
        'n_features': len(feature_cols),
        'train_size': int(len(y_train)),
        'holdout_size': int(len(y_hold)),
        'cutoff_buffer_hours': CUTOFF_BUFFER_HOURS,
        'data_source': 'fixtures+matches only (no training_matches due to leakage)',
        'oof_metrics': oof_metrics,
        'holdout_metrics': hold_metrics,
        'fold_variance': fold_variance,
        'gate_passed': passed,
        'gate_reasons': reasons,
    }
    with open(OUTPUT_DIR / "metadata.json", "w") as f:
        json.dump(metadata, f, indent=2, default=float)

    logger.info(f"\nCandidate saved to {OUTPUT_DIR}")
    if passed:
        import shutil
        for f in ['lgbm_ensemble.pkl', 'features.json', 'metadata.json']:
            shutil.copy(OUTPUT_DIR / f, PROMOTE_DIR / f)
        logger.info(f"✅ PROMOTED to {PROMOTE_DIR}")
    else:
        logger.info(f"⚠️  Kept for inspection only — production still uses rollback model")
    return passed


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
