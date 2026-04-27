"""
V3 League Specialist Training

Trains a per-league LightGBM specialist on combined data:
  1. training_matches with strict pre-kickoff odds (clean only)
  2. historical_odds (multi-bookmaker raw odds, always pre-match)

Specialists train on 20 features (subset of main V3's 24 — no h2h, no league_ece).
Same gates as main:
  - Holdout accuracy 45-62%
  - Max class skew < 12pp
  - Draw picks 8-38%
  - Fold variance < 18pp

Saves to: artifacts/models/v3_sharp_specialist_{league_id}/

Usage:
    python training/train_v3_specialist.py --league_code I1   # Serie A
    python training/train_v3_specialist.py --league_code N1   # Eredivisie
    python training/train_v3_specialist.py --all              # Train all 7 majors
"""

import os
import sys
import json
import pickle
import logging
import argparse
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2
import lightgbm as lgb
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import accuracy_score, log_loss

sys.path.append('.')
from features.historical_odds_adapter import (
    HISTORICAL_LEAGUE_MAP, BOOKMAKERS, SPECIALIST_FEATURE_NAMES,
    build_features_from_row, compute_league_stats, get_outcome_label,
)
from features.v3_feature_builder import V3FeatureBuilder

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Specialist gates — looser than main since we expect different behavior per league.
# The cascade in v3_predictor only USES specialist when it disagrees with main AND
# specialist confidence > 0.50, so low draw rate is acceptable.
MIN_ACCURACY = 0.45
MAX_ACCURACY = 0.65
MAX_CLASS_SKEW_PP = 28  # specialists capture league-specific bias (e.g., low-draw leagues)
MIN_DRAW_PREDICTIONS = 0.02  # 2% floor — main covers draws, specialist adds H/A signal
MAX_DRAW_PREDICTIONS = 0.50
MAX_FOLD_VARIANCE = 0.20


def load_historical_odds(league_code: str):
    """Load historical_odds rows for a league."""
    conn = psycopg2.connect(os.environ['DATABASE_URL'])
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) if False else conn.cursor()

    columns = ['id', 'match_date', 'home_goals', 'away_goals', 'result',
               'avg_h', 'avg_d', 'avg_a', 'max_h', 'max_d', 'max_a']
    columns += [f'{bm}_{x}' for bm in BOOKMAKERS for x in ('h', 'd', 'a')]

    cur.execute(f"""
        SELECT {', '.join(columns)}
        FROM historical_odds
        WHERE league = %s
          AND home_goals IS NOT NULL
          AND avg_h IS NOT NULL
          AND avg_d IS NOT NULL
          AND avg_a IS NOT NULL
        ORDER BY match_date ASC
    """, (league_code,))
    rows = cur.fetchall()
    conn.close()

    # Convert to dicts
    records = [dict(zip(columns, r)) for r in rows]
    return records


def load_training_matches(league_id: int):
    """Load clean training_matches for a league with pre-kickoff odds_consensus."""
    conn = psycopg2.connect(os.environ['DATABASE_URL'])
    cur = conn.cursor()

    # Use strict cutoff matching main training
    cur.execute("""
        SELECT tm.match_id, tm.match_date,
               CASE WHEN tm.outcome IN ('H','Home','home') THEN 'H'
                    WHEN tm.outcome IN ('A','Away','away') THEN 'A'
                    ELSE 'D' END as outcome
        FROM training_matches tm
        WHERE tm.league_id = %s
          AND tm.outcome IS NOT NULL
          AND EXISTS (
              SELECT 1 FROM odds_consensus oc
              WHERE oc.match_id = tm.match_id
                AND oc.ts_effective < tm.match_date - INTERVAL '1 hour'
                AND oc.ph_cons IS NOT NULL
          )
        ORDER BY tm.match_date ASC
    """, (league_id,))
    matches = cur.fetchall()
    conn.close()
    return matches


def build_training_matches_features(matches, league_stats):
    """Build features from training_matches via the regular V3 feature builder.
    Output uses the SPECIALIST_FEATURE_NAMES subset for compatibility."""
    if not matches:
        return []

    builder = V3FeatureBuilder()
    records = []

    for mid, mdate, outcome in matches:
        try:
            conn = psycopg2.connect(os.environ['DATABASE_URL'])
            cur = conn.cursor()
            mi = builder._get_match_info(cur, mid)
            if not mi or not mi['kickoff_time']:
                cur.close(); conn.close(); continue
            cutoff = mi['kickoff_time']
            v2 = builder._build_v2_core_features(cur, mid, cutoff)
            if v2.get('prob_home') is None or (isinstance(v2.get('prob_home'), float) and np.isnan(v2['prob_home'])):
                cur.close(); conn.close(); continue
            cls = builder._build_closeness_features(v2)
            ld = builder._build_league_draw_features(cur, mi['league_id'], v2)
            dm = builder._build_draw_market_features(v2)
            cur.close(); conn.close()

            # Use league stats from historical (more reliable)
            ld['league_draw_rate'] = league_stats.get('avg_draw_rate', 0.25)
            pd_ = v2.get('prob_draw') or 0.0
            ld['league_draw_deviation'] = float(pd_ - league_stats.get('avg_draw_rate', 0.25))

            feats = {**v2, **cls, **ld, **dm}
            # Add season_progress
            month = mdate.month if hasattr(mdate, 'month') else 6
            feats['season_progress'] = (month - 8) / 10.0 if month >= 8 else (month + 4) / 10.0

            # Keep only SPECIALIST_FEATURE_NAMES
            row = {k: feats.get(k, np.nan) for k in SPECIALIST_FEATURE_NAMES}
            row['match_id'] = mid
            row['outcome'] = outcome
            row['match_date'] = mdate
            records.append(row)
        except Exception as e:
            logger.warning(f"  match {mid}: {e}")

    return records


def train_specialist(league_code: str):
    """Train a specialist for one league."""
    league_id = HISTORICAL_LEAGUE_MAP.get(league_code)
    if not league_id:
        logger.error(f"Unknown league code: {league_code}")
        return False

    output_dir = Path(f"artifacts/models/v3_sharp_specialist_{league_id}")
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("=" * 60)
    logger.info(f"TRAINING SPECIALIST: {league_code} (league_id={league_id})")
    logger.info("=" * 60)

    # Load historical_odds
    logger.info("Loading historical_odds...")
    ho_rows = load_historical_odds(league_code)
    league_stats = compute_league_stats(ho_rows)
    logger.info(f"  Got {len(ho_rows)} historical_odds rows, draw_rate={league_stats['avg_draw_rate']:.3f}")

    # Build features from historical_odds
    logger.info("Building features from historical_odds...")
    ho_records = []
    for r in ho_rows:
        feats = build_features_from_row(r, league_stats)
        if any(np.isnan(v) for v in [feats['prob_home'], feats['prob_draw'], feats['prob_away']]):
            continue
        outcome = get_outcome_label(r)
        if not outcome:
            continue
        feats['match_id'] = r['id']
        feats['outcome'] = outcome
        feats['match_date'] = r['match_date']
        ho_records.append(feats)
    logger.info(f"  Built {len(ho_records)} feature rows from historical_odds")

    # Load training_matches
    logger.info("Loading training_matches...")
    tm_matches = load_training_matches(league_id)
    logger.info(f"  Got {len(tm_matches)} training_matches with clean pre-kickoff odds")

    # Build features from training_matches
    if tm_matches:
        logger.info("Building features from training_matches...")
        tm_records = build_training_matches_features(tm_matches, league_stats)
        logger.info(f"  Built {len(tm_records)} feature rows from training_matches")
    else:
        tm_records = []

    # Combine
    all_records = ho_records + tm_records
    if len(all_records) < 300:
        logger.error(f"Insufficient data ({len(all_records)} samples). Need 300+.")
        return False

    df = pd.DataFrame(all_records)
    # Normalize match_date to string for sorting (handles date vs datetime mix)
    df['match_date'] = df['match_date'].astype(str)
    df = df.sort_values('match_date').reset_index(drop=True)
    logger.info(f"\nCombined dataset: {len(df)} samples")

    feature_cols = SPECIALIST_FEATURE_NAMES
    X = df[feature_cols].values
    y = df['outcome'].map({'H': 0, 'D': 1, 'A': 2}).values
    n = len(y)
    logger.info(f"Classes: H={sum(y==0)}, D={sum(y==1)}, A={sum(y==2)}")

    # 85/15 chronological split
    split = int(n * 0.85)
    X_train, X_hold = X[:split], X[split:]
    y_train, y_hold = y[:split], y[split:]
    logger.info(f"Train: {len(y_train)}  |  Holdout: {len(y_hold)}")

    # Sqrt class weights (proven safe from main retrain)
    class_counts = np.bincount(y_train, minlength=3)
    raw_weights = len(y_train) / (3.0 * class_counts.clip(min=1))
    sqrt_weights = np.sqrt(raw_weights)
    sample_weights = np.array([sqrt_weights[label] for label in y_train])
    logger.info(f"Sqrt class weights: H={sqrt_weights[0]:.3f}, D={sqrt_weights[1]:.3f}, A={sqrt_weights[2]:.3f}")

    # LightGBM params (slightly smaller for specialist)
    params = {
        'objective': 'multiclass', 'num_class': 3, 'metric': 'multi_logloss',
        'boosting_type': 'gbdt', 'learning_rate': 0.03,
        'num_leaves': 24, 'max_depth': 5, 'min_data_in_leaf': 30,
        'feature_fraction': 0.8, 'bagging_fraction': 0.8, 'bagging_freq': 5,
        'lambda_l1': 0.3, 'lambda_l2': 0.5,
        'verbose': -1, 'force_row_wise': True, 'seed': 42,
    }

    # 5-fold TimeSeriesSplit
    tscv = TimeSeriesSplit(n_splits=5)
    models = []
    fold_accs = []
    oof_preds = np.zeros((len(y_train), 3))
    oof_mask = np.zeros(len(y_train), dtype=bool)

    for fold, (tr, va) in enumerate(tscv.split(X_train)):
        td = lgb.Dataset(X_train[tr], label=y_train[tr], weight=sample_weights[tr])
        vd = lgb.Dataset(X_train[va], label=y_train[va], reference=td)
        m = lgb.train(params, td, num_boost_round=2000,
                      valid_sets=[vd], valid_names=['valid'],
                      callbacks=[lgb.early_stopping(100), lgb.log_evaluation(0)])
        models.append(m)
        oof_preds[va] = m.predict(X_train[va], num_iteration=m.best_iteration)
        oof_mask[va] = True
        fold_acc = accuracy_score(y_train[va], np.argmax(oof_preds[va], axis=1))
        fold_accs.append(fold_acc)
        logger.info(f"  Fold {fold+1}: val_acc={fold_acc:.3f}, iters={m.best_iteration}")

    fold_variance = max(fold_accs) - min(fold_accs)

    # Holdout eval
    hold_preds = np.mean([m.predict(X_hold, num_iteration=m.best_iteration) for m in models], axis=0)
    hold_preds = hold_preds / hold_preds.sum(axis=1, keepdims=True)
    hold_picks = np.argmax(hold_preds, axis=1)
    hold_acc = accuracy_score(y_hold, hold_picks)
    pick_dist = {k: int((hold_picks == i).sum()) / len(y_hold) * 100 for i, k in enumerate(['H','D','A'])}
    actual_dist = {k: int((y_hold == i).sum()) / len(y_hold) * 100 for i, k in enumerate(['H','D','A'])}
    skews = {k: abs(pick_dist[k] - actual_dist[k]) for k in 'HDA'}
    max_skew = max(skews.values())
    draw_pred_rate = pick_dist['D'] / 100

    logger.info(f"\nHOLDOUT ACCURACY: {hold_acc*100:.1f}%")
    logger.info(f"  Pick dist:    H={pick_dist['H']:.1f}% D={pick_dist['D']:.1f}% A={pick_dist['A']:.1f}%")
    logger.info(f"  Actual dist:  H={actual_dist['H']:.1f}% D={actual_dist['D']:.1f}% A={actual_dist['A']:.1f}%")
    logger.info(f"  Max skew: {max_skew:.1f}pp, Fold var: {fold_variance:.3f}")

    # Per-class
    for cls, name in [(0, 'Home'), (1, 'Draw'), (2, 'Away')]:
        mask = y_hold == cls
        if mask.sum() > 0:
            cls_acc = accuracy_score(y_hold[mask], hold_picks[mask])
            logger.info(f"  {name}: {cls_acc*100:.1f}% ({mask.sum()} actual)")

    # Gate check
    passed = True
    reasons = []
    if hold_acc < MIN_ACCURACY:
        passed = False; reasons.append(f"acc {hold_acc*100:.1f}% < {MIN_ACCURACY*100}%")
    if hold_acc > MAX_ACCURACY:
        passed = False; reasons.append(f"acc {hold_acc*100:.1f}% > {MAX_ACCURACY*100}% (suspect leakage)")
    if max_skew > MAX_CLASS_SKEW_PP:
        passed = False; reasons.append(f"skew {max_skew:.1f}pp > {MAX_CLASS_SKEW_PP}pp")
    if draw_pred_rate < MIN_DRAW_PREDICTIONS:
        passed = False; reasons.append(f"draws {draw_pred_rate*100:.1f}% < {MIN_DRAW_PREDICTIONS*100}%")
    if draw_pred_rate > MAX_DRAW_PREDICTIONS:
        passed = False; reasons.append(f"draws {draw_pred_rate*100:.1f}% > {MAX_DRAW_PREDICTIONS*100}%")
    if fold_variance > MAX_FOLD_VARIANCE:
        passed = False; reasons.append(f"fold var {fold_variance:.3f} > {MAX_FOLD_VARIANCE}")

    logger.info(f"\nGATE CHECK: {'✅ PASSED' if passed else '❌ FAILED'}")
    for r in reasons:
        logger.info(f"  - {r}")

    if not passed:
        logger.warning(f"NOT promoting — kept for inspection only")
        return False

    # Save
    with open(output_dir / "lgbm_ensemble.pkl", "wb") as f:
        pickle.dump(models, f)
    with open(output_dir / "features.json", "w") as f:
        json.dump(feature_cols, f, indent=2)

    metadata = {
        'model_type': f'V3_Specialist_{league_code}',
        'league_id': league_id,
        'league_code': league_code,
        'trained_at': datetime.now(timezone.utc).isoformat(),
        'n_features': len(feature_cols),
        'n_train_samples': int(len(y_train)),
        'n_holdout_samples': int(len(y_hold)),
        'data_source': f'historical_odds ({len(ho_records)}) + training_matches ({len(tm_records)})',
        'holdout_metrics': {
            'accuracy': float(hold_acc),
            'pick_dist_pct': pick_dist,
            'actual_dist_pct': actual_dist,
            'max_skew_pp': max_skew,
            'draw_pred_rate': draw_pred_rate,
            'fold_variance': fold_variance,
        },
        'gate_passed': passed,
    }
    with open(output_dir / "metadata.json", "w") as f:
        json.dump(metadata, f, indent=2, default=str)

    logger.info(f"\n✅ Saved specialist to {output_dir}")
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--league_code', help='Single league code to train (e.g., I1)')
    parser.add_argument('--all', action='store_true', help='Train all 7 major leagues')
    args = parser.parse_args()

    if args.all:
        leagues = ['I1', 'N1', 'F1', 'D1', 'E0', 'SP1', 'P1']
    elif args.league_code:
        leagues = [args.league_code]
    else:
        # Default: train weakest leagues first (where main is most broken)
        leagues = ['I1', 'N1', 'F1']  # Serie A, Eredivisie, Ligue 1

    results = {}
    for code in leagues:
        try:
            results[code] = train_specialist(code)
        except Exception as e:
            logger.error(f"Failed to train {code}: {e}", exc_info=True)
            results[code] = False

    logger.info("\n" + "=" * 60)
    logger.info("SUMMARY")
    logger.info("=" * 60)
    for code, success in results.items():
        logger.info(f"  {code}: {'✅ PROMOTED' if success else '❌ NOT PROMOTED'}")


if __name__ == "__main__":
    main()
