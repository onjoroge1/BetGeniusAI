"""
Fast LightGBM training with single time-based train/test split
Quick version for model evaluation
"""

import os
import sys
import pandas as pd
import numpy as np
import lightgbm as lgb
from sklearn.metrics import log_loss
import json
from datetime import datetime
import pickle

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

CLASS_TO_IDX = {'H': 0, 'D': 1, 'A': 2}

LGBM_PARAMS = {
    "objective": "multiclass",
    "num_class": 3,
    "metric": "multi_logloss",
    "learning_rate": 0.03,
    "num_leaves": 31,
    "min_data_in_leaf": 60,
    "lambda_l2": 3.0,
    "feature_fraction": 0.75,
    "verbosity": -1,
    "seed": 42
}


def normalize_triplet(ph, pd, pa):
    total = ph + pd + pa
    if total <= 0:
        return 1/3, 1/3, 1/3
    return ph/total, pd/total, pa/total


def compute_metrics(y_true, y_pred_proba):
    normalized_preds = np.array([normalize_triplet(p[0], p[1], p[2]) for p in y_pred_proba])
    
    logloss = log_loss(y_true, normalized_preds, labels=[0, 1, 2])
    brier = np.mean(np.sum((normalized_preds - np.eye(3)[y_true])**2, axis=1)) / 3.0
    
    y_pred_class = np.argmax(normalized_preds, axis=1)
    accuracy_3way = np.mean(y_pred_class == y_true)
    
    mask = y_true != 1
    accuracy_2way = np.mean(y_pred_class[mask] == y_true[mask]) if np.sum(mask) > 0 else 0.0
    
    return {
        'logloss': logloss,
        'brier': brier,
        'accuracy_3way': accuracy_3way,
        'accuracy_2way': accuracy_2way
    }


print("="*70)
print("FAST LIGHTGBM TRAINING - SINGLE SPLIT")
print("="*70)

# Load data
df = pd.read_parquet('artifacts/datasets/v2_tabular_historical.parquet')
df['kickoff_date'] = pd.to_datetime(df['kickoff_date'])

print(f"\nDataset: {len(df):,} matches")
print(f"Date range: {df['kickoff_date'].min()} → {df['kickoff_date'].max()}")

# Time-based split: Train on 2002-2021, Test on 2022-2024
train_mask = df['kickoff_date'] < '2022-01-01'
test_mask = df['kickoff_date'] >= '2022-01-01'

df_train = df[train_mask].copy()
df_test = df[test_mask].copy()

print(f"\nTrain: {len(df_train):,} ({df_train['kickoff_date'].min()} → {df_train['kickoff_date'].max()})")
print(f"Test:  {len(df_test):,} ({df_test['kickoff_date'].min()} → {df_test['kickoff_date'].max()})")

# Features
exclude_cols = ['match_id', 'league', 'kickoff_date', 'y']
feature_cols = [c for c in df.columns if c not in exclude_cols]

X_train = df_train[feature_cols].values
X_test = df_test[feature_cols].values
y_train = df_train['y'].map(CLASS_TO_IDX).values
y_test = df_test['y'].map(CLASS_TO_IDX).values

print(f"\nFeatures: {len(feature_cols)}")

# Train
print(f"\nTraining...")
train_data = lgb.Dataset(X_train, label=y_train, feature_name=feature_cols)
test_data = lgb.Dataset(X_test, label=y_test, reference=train_data, feature_name=feature_cols)

model = lgb.train(
    LGBM_PARAMS,
    train_data,
    num_boost_round=1000,
    valid_sets=[test_data],
    callbacks=[lgb.early_stopping(stopping_rounds=100), lgb.log_evaluation(period=50)]
)

# Evaluate
print(f"\n{'='*70}")
print("FINAL RESULTS")
print("="*70)

y_pred_test = model.predict(X_test, num_iteration=model.best_iteration)
metrics = compute_metrics(y_test, y_pred_test)

print(f"\nTest Set (n={len(df_test):,}, 2022-2024):")
print(f"  LogLoss:    {metrics['logloss']:.4f}")
print(f"  Brier:      {metrics['brier']:.4f}")
print(f"  3-way Acc:  {metrics['accuracy_3way']*100:.1f}%")
print(f"  2-way Acc:  {metrics['accuracy_2way']*100:.1f}%")
print(f"  Best iter:  {model.best_iteration}")

# Feature importance
importance = model.feature_importance(importance_type='gain')
importance_df = pd.DataFrame({
    'feature': feature_cols,
    'importance': importance
}).sort_values('importance', ascending=False)

print(f"\nTop 15 Features:")
for idx, row in importance_df.head(15).iterrows():
    print(f"  {row['feature']:35s} {row['importance']:10.1f}")

# Save
output_dir = 'artifacts/models/lgbm_historical_36k'
os.makedirs(output_dir, exist_ok=True)

with open(f'{output_dir}/lgbm_model.pkl', 'wb') as f:
    pickle.dump(model, f)

with open(f'{output_dir}/features.json', 'w') as f:
    json.dump(feature_cols, f, indent=2)

metadata = {
    'timestamp': datetime.utcnow().isoformat(),
    'n_train': len(df_train),
    'n_test': len(df_test),
    'train_period': [str(df_train['kickoff_date'].min()), str(df_train['kickoff_date'].max())],
    'test_period': [str(df_test['kickoff_date'].min()), str(df_test['kickoff_date'].max())],
    'params': LGBM_PARAMS,
    'test_metrics': {k: float(v) for k, v in metrics.items()},
    'best_iteration': int(model.best_iteration)
}

with open(f'{output_dir}/metadata.json', 'w') as f:
    json.dump(metadata, f, indent=2)

importance_df.to_csv(f'{output_dir}/feature_importance.csv', index=False)

print(f"\n💾 Model saved to: {output_dir}/")
print("="*70)
