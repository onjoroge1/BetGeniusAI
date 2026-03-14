"""
Multisport V3 Training Script — NBA and NHL

Trains a separate LightGBM model for each sport using 46 features across 7 groups:
  Odds, Spread/Totals, Rest/Schedule, Team Form, ELO, H2H, Season Context

Binary classification: H=1 / A=0  (no draws in NBA/NHL)

Usage:
    python training/train_multisport_v3.py
    python training/train_multisport_v3.py --sport basketball_nba
    python training/train_multisport_v3.py --sport icehockey_nhl
"""

import os
import sys
import json
import pickle
import logging
import argparse
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple, Optional

import psycopg2
import lightgbm as lgb
from sklearn.calibration import CalibratedClassifierCV
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import log_loss, accuracy_score, brier_score_loss

sys.path.insert(0, '.')
from features.multisport_feature_builder import MultisportFeatureBuilder

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

SPORT_CONFIGS = {
    'basketball_nba': {
        'name':       'NBA Basketball',
        'output_dir': 'artifacts/models/v3_basketball',
        'min_samples': 150,
        'lgbm_params': {
            'objective':        'binary',
            'metric':           'binary_logloss',
            'boosting_type':    'gbdt',
            'num_leaves':       31,
            'learning_rate':    0.05,
            'feature_fraction': 0.8,
            'bagging_fraction': 0.8,
            'bagging_freq':     5,
            'min_data_in_leaf': 15,
            'lambda_l1':        0.1,
            'lambda_l2':        0.1,
            'verbose':          -1,
            'n_jobs':           -1,
        },
        'n_estimators':  500,
        'early_stopping': 50,
    },
    'icehockey_nhl': {
        'name':       'NHL Hockey',
        'output_dir': 'artifacts/models/v3_hockey',
        'min_samples': 150,
        'lgbm_params': {
            'objective':        'binary',
            'metric':           'binary_logloss',
            'boosting_type':    'gbdt',
            'num_leaves':       31,
            'learning_rate':    0.05,
            'feature_fraction': 0.8,
            'bagging_fraction': 0.8,
            'bagging_freq':     5,
            'min_data_in_leaf': 10,
            'lambda_l1':        0.1,
            'lambda_l2':        0.1,
            'verbose':          -1,
            'n_jobs':           -1,
        },
        'n_estimators':  500,
        'early_stopping': 50,
    },
}


def load_training_data(sport_key: str) -> pd.DataFrame:
    """Load records from multisport_training that have features."""
    conn = psycopg2.connect(os.getenv('DATABASE_URL'))
    cursor = conn.cursor()
    cursor.execute("""
        SELECT event_id, home_team, away_team, match_date, outcome,
               features, consensus_home_prob, consensus_away_prob,
               home_score, away_score
        FROM multisport_training
        WHERE sport_key = %s
          AND outcome IN ('H','A')
          AND features IS NOT NULL
          AND features::text NOT IN ('null', '{}')
        ORDER BY match_date ASC
    """, (sport_key,))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    if not rows:
        return pd.DataFrame()

    records = []
    for row in rows:
        event_id, home, away, match_date, outcome, feats_json, cp_home, cp_away, hs, as_ = row
        if isinstance(feats_json, str):
            try:
                feats = json.loads(feats_json)
            except (json.JSONDecodeError, TypeError):
                continue
        elif isinstance(feats_json, dict):
            feats = feats_json
        else:
            continue

        rec = {
            'event_id':   event_id,
            'home_team':  home,
            'away_team':  away,
            'match_date': match_date,
            'outcome':    outcome,
            'label':      1 if outcome == 'H' else 0,
        }
        rec.update(feats)
        records.append(rec)

    return pd.DataFrame(records)


def compute_missing_features_on_the_fly(
    sport_key: str,
    db_url: str,
    n_limit: Optional[int] = None,
) -> pd.DataFrame:
    """
    For training records that still lack features JSON, compute them live.
    Falls back to using consensus_home_prob as a minimal feature set.
    """
    conn = psycopg2.connect(db_url)
    cursor = conn.cursor()

    query = """
        SELECT event_id, home_team, away_team, match_date, outcome,
               consensus_home_prob, consensus_away_prob, home_score, away_score
        FROM multisport_training
        WHERE sport_key = %s
          AND outcome IN ('H','A')
          AND consensus_home_prob IS NOT NULL
        ORDER BY match_date ASC
    """
    if n_limit:
        query += f" LIMIT {n_limit}"
    cursor.execute(query, (sport_key,))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    builder = MultisportFeatureBuilder(db_url)
    records = []
    errors  = 0

    logger.info(f"Building features for {len(rows)} {sport_key} records...")
    for i, row in enumerate(rows, 1):
        if i % 50 == 0:
            logger.info(f"  {i}/{len(rows)} (errors: {errors})")
        event_id, home, away, match_date, outcome, cp_home, cp_away, hs, as_ = row
        try:
            from datetime import datetime
            cutoff = datetime.combine(match_date, datetime.min.time()).replace(tzinfo=timezone.utc)
            feats = builder.build_features(sport_key, event_id, home, away, match_date, cutoff)
            rec = {
                'event_id':   event_id,
                'home_team':  home,
                'away_team':  away,
                'match_date': match_date,
                'outcome':    outcome,
                'label':      1 if outcome == 'H' else 0,
            }
            rec.update(feats)
            records.append(rec)
        except Exception as e:
            errors += 1
            # Minimal fallback: just odds
            records.append({
                'event_id':   event_id,
                'home_team':  home,
                'away_team':  away,
                'match_date': match_date,
                'outcome':    outcome,
                'label':      1 if outcome == 'H' else 0,
                'prob_home':  float(cp_home or 0.5),
                'prob_away':  float(cp_away or 0.5),
            })

    logger.info(f"Feature building done. Errors: {errors}/{len(rows)}")
    return pd.DataFrame(records)


def train_sport_model(sport_key: str) -> Dict:
    cfg = SPORT_CONFIGS[sport_key]
    logger.info("=" * 60)
    logger.info(f"V3 TRAINING — {cfg['name']} ({sport_key})")
    logger.info("=" * 60)

    db_url = os.getenv('DATABASE_URL')
    output_dir = Path(cfg['output_dir'])
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Load pre-computed features from DB
    df = load_training_data(sport_key)
    logger.info(f"Loaded {len(df)} records with pre-computed features")

    # 2. If insufficient, compute on the fly for all records
    if len(df) < cfg['min_samples']:
        logger.info(f"Only {len(df)} have features — computing all records on the fly...")
        df = compute_missing_features_on_the_fly(sport_key, db_url)

    if len(df) < cfg['min_samples']:
        logger.error(f"Still only {len(df)} samples after on-the-fly build. Need {cfg['min_samples']}.")
        return {'status': 'insufficient_data', 'n_samples': len(df)}

    # 3. Prepare feature matrix
    feature_names = MultisportFeatureBuilder.get_feature_names()
    available = [f for f in feature_names if f in df.columns]
    missing   = [f for f in feature_names if f not in df.columns]
    if missing:
        logger.warning(f"Missing {len(missing)} features (will fill with 0): {missing[:5]}...")
        for f in missing:
            df[f] = 0.0

    df = df.sort_values('match_date').reset_index(drop=True)
    X = df[feature_names].fillna(0.0).values.astype(float)
    y = df['label'].values

    logger.info(f"Training set: {len(df)} samples | {len(feature_names)} features")
    logger.info(f"Class distribution: H={y.sum()} ({y.mean():.1%}), A={(1-y).sum()} ({(1-y).mean():.1%})")
    logger.info(f"Feature population: {(df[available] != 0).mean().mean():.1%} non-zero")

    # 4. Population report
    pop = (df[available] != 0).mean().sort_values(ascending=False)
    logger.info("\nFeature Population:")
    for feat, pct in pop.items():
        logger.info(f"  {feat}: {pct:.1%}")

    # 5. Temporal cross-validation (walk-forward)
    n_splits   = min(5, max(3, len(df) // 60))
    tscv       = TimeSeriesSplit(n_splits=n_splits)
    oof_preds  = np.zeros(len(df))
    fold_accs  = []
    fold_losses = []

    logger.info(f"\nRunning {n_splits}-fold temporal CV...")
    for fold, (train_idx, val_idx) in enumerate(tscv.split(X), 1):
        X_tr, X_val = X[train_idx], X[val_idx]
        y_tr, y_val = y[train_idx], y[val_idx]

        dtrain = lgb.Dataset(X_tr, label=y_tr)
        dval   = lgb.Dataset(X_val, label=y_val, reference=dtrain)

        model = lgb.train(
            cfg['lgbm_params'],
            dtrain,
            num_boost_round=cfg['n_estimators'],
            valid_sets=[dtrain, dval],
            callbacks=[
                lgb.early_stopping(cfg['early_stopping'], verbose=False),
                lgb.log_evaluation(0),
            ],
        )
        preds = model.predict(X_val)
        oof_preds[val_idx] = preds

        acc  = accuracy_score(y_val, (preds > 0.5).astype(int))
        loss = log_loss(y_val, np.column_stack([1 - preds, preds]))
        fold_accs.append(acc)
        fold_losses.append(loss)
        logger.info(f"  Fold {fold}/{n_splits}: acc={acc:.4f}  logloss={loss:.4f}  iter={model.best_iteration}")

    # 6. Final model on full dataset
    logger.info("\nTraining final model on full dataset...")
    best_iter = int(np.mean([m.best_iteration for m in [model]]) * 1.1)   # slight boost

    dtrain_full = lgb.Dataset(X, label=y)
    final_model = lgb.train(
        cfg['lgbm_params'],
        dtrain_full,
        num_boost_round=max(best_iter, 50),
        callbacks=[lgb.log_evaluation(0)],
    )

    # 7. OOF metrics
    oof_valid = oof_preds[oof_preds > 0]
    oof_y     = y[oof_preds > 0]
    mean_acc  = float(np.mean(fold_accs))
    mean_loss = float(np.mean(fold_losses))
    brier     = float(brier_score_loss(y, oof_preds.clip(0.01, 0.99), pos_label=1))

    logger.info("\n" + "=" * 60)
    logger.info(f"  2-way Accuracy : {mean_acc:.4f} ({mean_acc:.2%})")
    logger.info(f"  LogLoss        : {mean_loss:.4f}")
    logger.info(f"  Brier Score    : {brier:.4f}")
    logger.info("=" * 60)

    # 8. Feature importance
    importance = final_model.feature_importance(importance_type='gain')
    feat_imp = sorted(zip(feature_names, importance), key=lambda x: -x[1])
    logger.info("\nTop 15 Features:")
    for fname, imp in feat_imp[:15]:
        logger.info(f"  {fname}: {imp:.2f}")

    # 9. Save artifacts
    model_path    = output_dir / 'lgbm_model.txt'
    features_path = output_dir / 'features.json'
    meta_path     = output_dir / 'metadata.json'

    final_model.save_model(str(model_path))

    with open(features_path, 'w') as f:
        json.dump(feature_names, f, indent=2)

    metadata = {
        'model_type':    f'V3_{cfg["name"].replace(" ", "_")}_LightGBM',
        'sport_key':     sport_key,
        'trained_at':    datetime.now(timezone.utc).isoformat(),
        'n_features':    len(feature_names),
        'n_samples':     len(df),
        'n_folds':       n_splits,
        'oof_metrics': {
            'accuracy':    mean_acc,
            'logloss':     mean_loss,
            'brier_score': brier,
        },
        'feature_importance': [
            {'feature': f, 'importance': float(imp)} for f, imp in feat_imp
        ],
        'feature_population': {
            f: float(pop.get(f, 0.0)) for f in feature_names
        },
    }
    with open(meta_path, 'w') as f:
        json.dump(metadata, f, indent=2)

    logger.info(f"\n✅ Model saved to {output_dir}")
    return {'status': 'ok', 'sport_key': sport_key, 'accuracy': mean_acc, 'logloss': mean_loss}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--sport', choices=list(SPORT_CONFIGS.keys()) + ['all'], default='all')
    args = parser.parse_args()

    sports = list(SPORT_CONFIGS.keys()) if args.sport == 'all' else [args.sport]
    results = {}
    for sport in sports:
        results[sport] = train_sport_model(sport)

    logger.info("\n=== TRAINING SUMMARY ===")
    for sport, res in results.items():
        logger.info(f"  {sport}: {res}")


if __name__ == '__main__':
    main()
