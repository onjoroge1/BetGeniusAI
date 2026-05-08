"""
Retrain lgbm_historical_36k with draw/away class weights.

Council recommendation:
  - Draw: 1.35x weight (address under-prediction)
  - Away: 1.15x weight (mild boost)
  - TimeSeriesSplit(5) instead of 3 folds

Output: artifacts/models/lgbm_historical_36k/ (overwrites)
"""

import os
import sys
import json
import pickle
import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.metrics import log_loss
from pathlib import Path
from datetime import datetime

sys.path.insert(0, '.')

DATA_PATH = 'artifacts/datasets/v2_tabular_historical.parquet'
OUTPUT_DIR = Path('artifacts/models/lgbm_historical_36k')

CLASS_TO_IDX = {'H': 0, 'D': 1, 'A': 2}
IDX_TO_CLASS = ['H', 'D', 'A']

# Draw/away class weight boost (H=1.0 baseline)
# Diagnostic shows draw prob averages 0.352 on actual draws but home wins at 0.372
# — the 1.35x weight wasn't enough to push draw above home. 2.0x should close the gap.
CLASS_WEIGHTS = {0: 1.0, 1: 2.0, 2: 1.2}

LGBM_PARAMS = {
    "objective": "multiclass",
    "num_class": 3,
    "metric": "multi_logloss",
    "learning_rate": 0.03,
    "num_leaves": 31,
    "min_data_in_leaf": 50,
    "lambda_l2": 3.0,
    "feature_fraction": 0.75,
    "verbosity": -1,
    "seed": 42,
    "is_unbalance": False,
}

N_FOLDS = 5
N_ROUNDS = 2000
EARLY_STOP = 200


def compute_accuracy(y_true, proba):
    y_pred = np.argmax(proba, axis=1)
    return np.mean(y_pred == y_true)


def per_class_metrics(y_true, proba):
    y_pred = np.argmax(proba, axis=1)
    out = {}
    for cls_idx, name in enumerate(IDX_TO_CLASS):
        actual = y_true == cls_idx
        predicted = y_pred == cls_idx
        tp = np.sum(actual & predicted)
        prec = tp / np.sum(predicted) if np.sum(predicted) > 0 else 0
        rec = tp / np.sum(actual) if np.sum(actual) > 0 else 0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0
        out[name] = {'precision': prec, 'recall': rec, 'f1': f1, 'n': int(np.sum(actual))}
    return out


def time_aware_splits(df, n_splits=5):
    df = df.sort_values('kickoff_date').reset_index(drop=True)
    df['_sy'] = pd.to_datetime(df['kickoff_date']).dt.year
    df.loc[pd.to_datetime(df['kickoff_date']).dt.month < 7, '_sy'] -= 1
    seasons = sorted(df['_sy'].unique())
    test_size = max(1, len(seasons) // (n_splits + 1))
    splits = []
    for i in range(n_splits):
        test_start = len(seasons) - (n_splits - i) * test_size
        test_seasons = seasons[test_start:test_start + test_size]
        train_seasons = seasons[:test_start]
        if not train_seasons or not test_seasons:
            continue
        tr = df[df['_sy'].isin(train_seasons)].index.values
        va = df[df['_sy'].isin(test_seasons)].index.values
        if len(tr) > 100 and len(va) > 50:
            splits.append((tr, va))
            print(f"  Fold {len(splits)}: train={len(tr):,} ({min(train_seasons)}-{max(train_seasons)}) "
                  f"| val={len(va):,} ({min(test_seasons)}-{max(test_seasons)})")
    df.drop(columns=['_sy'], inplace=True)
    return splits, df


def train():
    print("=" * 65)
    print("RETRAIN HISTORICAL MODEL — DRAW/AWAY CLASS WEIGHTS")
    print("=" * 65)

    df = pd.read_parquet(DATA_PATH)
    print(f"Loaded {len(df):,} rows from {DATA_PATH}")

    exclude = {'match_id', 'league', 'kickoff_date', 'y', 'season_year'}
    feat_cols = [c for c in df.columns if c not in exclude]
    print(f"Features: {len(feat_cols)}")

    df = df[df['y'].isin(CLASS_TO_IDX)].copy()
    y = df['y'].map(CLASS_TO_IDX).values
    X = df[feat_cols].values

    print(f"\nOutcome distribution:")
    for cls, idx in CLASS_TO_IDX.items():
        n = int((y == idx).sum())
        print(f"  {cls}: {n} ({n/len(y)*100:.1f}%)")

    print(f"\nClass weights: {CLASS_WEIGHTS}")
    sample_weights = np.array([CLASS_WEIGHTS[yi] for yi in y])

    print(f"\nBuilding {N_FOLDS}-fold time-aware splits...")
    splits, df = time_aware_splits(df, N_FOLDS)
    if not splits:
        print("ERROR: no valid splits")
        return

    oof_probs = np.zeros((len(df), 3))
    models = []

    for fold_idx, (tr_idx, va_idx) in enumerate(splits, 1):
        print(f"\n{'─' * 55}")
        print(f"Fold {fold_idx}/{len(splits)}")

        X_tr, y_tr = X[tr_idx], y[tr_idx]
        X_va, y_va = X[va_idx], y[va_idx]
        sw_tr = sample_weights[tr_idx]

        tr_ds = lgb.Dataset(X_tr, label=y_tr, weight=sw_tr, feature_name=feat_cols)
        va_ds = lgb.Dataset(X_va, label=y_va, reference=tr_ds)

        model = lgb.train(
            LGBM_PARAMS,
            tr_ds,
            num_boost_round=N_ROUNDS,
            valid_sets=[va_ds],
            callbacks=[
                lgb.early_stopping(EARLY_STOP, verbose=False),
                lgb.log_evaluation(500),
            ],
        )
        models.append(model)

        preds = model.predict(X_va)
        oof_probs[va_idx] = preds
        fold_acc = compute_accuracy(y_va, preds)
        print(f"  Fold accuracy: {fold_acc*100:.2f}%")

    # OOF metrics on folds that were scored
    scored_mask = oof_probs.sum(axis=1) > 0
    oof_acc = compute_accuracy(y[scored_mask], oof_probs[scored_mask])
    oof_ll = log_loss(y[scored_mask], oof_probs[scored_mask], labels=[0, 1, 2])
    cls_metrics = per_class_metrics(y[scored_mask], oof_probs[scored_mask])

    print(f"\n{'=' * 55}")
    print(f"OOF Results ({scored_mask.sum():,} samples):")
    print(f"  3-way Accuracy: {oof_acc*100:.2f}%")
    print(f"  LogLoss:        {oof_ll:.4f}")
    for cls, m in cls_metrics.items():
        print(f"  {cls}: prec={m['precision']*100:.1f}%  rec={m['recall']*100:.1f}%  F1={m['f1']*100:.1f}%  n={m['n']}")

    # Save
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with open(OUTPUT_DIR / "lgbm_ensemble.pkl", "wb") as f:
        pickle.dump(models, f)

    with open(OUTPUT_DIR / "features.json", "w") as f:
        json.dump(feat_cols, f, indent=2)

    metadata = {
        "timestamp": datetime.utcnow().isoformat(),
        "n_folds": len(models),
        "n_features": len(feat_cols),
        "class_weights": CLASS_WEIGHTS,
        "params": LGBM_PARAMS,
        "oof_metrics": {
            "logloss": float(oof_ll),
            "accuracy_3way": float(oof_acc),
            "per_class": {k: {kk: float(vv) for kk, vv in v.items()} for k, v in cls_metrics.items()},
        },
    }
    with open(OUTPUT_DIR / "metadata.json", "w") as f:
        json.dump(metadata, f, indent=2)

    # Feature importance
    imp = models[-1].feature_importance(importance_type='gain')
    imp_df = pd.DataFrame({'feature': feat_cols, 'importance': imp}).sort_values('importance', ascending=False)
    imp_df.to_csv(OUTPUT_DIR / "feature_importance.csv", index=False)

    print(f"\nSaved model to {OUTPUT_DIR}")
    print(f"Top 5 features: {list(imp_df['feature'].head(5))}")
    print("=" * 55)


if __name__ == "__main__":
    train()
