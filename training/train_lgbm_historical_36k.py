"""
LightGBM Training on 36k+ Historical Dataset with Time-Aware CV

Trains on the expanded dataset with proper temporal validation.
Conservative params tuned for the larger dataset size.
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
IDX_TO_CLASS = ['H', 'D', 'A']

# Conservative params for 36k+ samples
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
    """Normalize probabilities to sum to 1"""
    total = ph + pd + pa
    if total <= 0:
        return 1/3, 1/3, 1/3
    return ph/total, pd/total, pa/total


def compute_metrics(y_true, y_pred_proba):
    """Compute all evaluation metrics"""
    normalized_preds = np.array([normalize_triplet(p[0], p[1], p[2]) for p in y_pred_proba])
    
    logloss = log_loss(y_true, normalized_preds, labels=[0, 1, 2])
    
    # Brier score (normalized)
    brier = np.mean(np.sum((normalized_preds - np.eye(3)[y_true])**2, axis=1)) / 3.0
    
    # 3-way accuracy
    y_pred_class = np.argmax(normalized_preds, axis=1)
    accuracy_3way = np.mean(y_pred_class == y_true)
    
    # 2-way accuracy (excluding draws)
    mask = y_true != 1
    if np.sum(mask) > 0:
        accuracy_2way = np.mean(y_pred_class[mask] == y_true[mask])
    else:
        accuracy_2way = 0.0
    
    return {
        'logloss': logloss,
        'brier': brier,
        'accuracy_3way': accuracy_3way,
        'accuracy_2way': accuracy_2way
    }


def time_aware_split(df, n_splits=5):
    """Create time-aware train/val splits based on seasons"""
    df = df.sort_values('kickoff_date').copy()
    
    # Add season year
    df['season_year'] = pd.to_datetime(df['kickoff_date']).dt.year
    df.loc[pd.to_datetime(df['kickoff_date']).dt.month < 7, 'season_year'] -= 1
    
    seasons = sorted(df['season_year'].unique())
    
    print(f"  Total seasons: {len(seasons)} ({seasons[0]}-{seasons[-1]})")
    
    # Use rolling window for CV
    test_size = len(seasons) // (n_splits + 1)
    
    splits = []
    for i in range(n_splits):
        test_start_idx = len(seasons) - (n_splits - i) * test_size
        test_end_idx = test_start_idx + test_size
        
        test_seasons = seasons[test_start_idx:test_end_idx]
        train_seasons = seasons[:test_start_idx]
        
        train_mask = df['season_year'].isin(train_seasons)
        val_mask = df['season_year'].isin(test_seasons)
        
        train_idx = df[train_mask].index.values
        val_idx = df[val_mask].index.values
        
        if len(train_idx) > 0 and len(val_idx) > 0:
            splits.append((train_idx, val_idx))
            print(f"  Fold {i+1}: Train={len(train_idx):,} ({min(train_seasons)}-{max(train_seasons)}) | "
                  f"Val={len(val_idx):,} ({min(test_seasons)}-{max(test_seasons)})")
    
    return splits


def train_lgbm_with_time_cv(df, feature_cols, n_splits=5):
    """Train LightGBM with time-aware CV"""
    print(f"\n{'='*70}")
    print(f"LIGHTGBM TRAINING - TIME-AWARE CV")
    print(f"{'='*70}")
    print(f"Total samples: {len(df):,}")
    print(f"Features: {len(feature_cols)}")
    print(f"Label mapping: {CLASS_TO_IDX}")
    
    X = df[feature_cols].values
    y_encoded = df['y'].map(CLASS_TO_IDX).values
    
    print(f"\nCreating time-aware splits...")
    splits = time_aware_split(df, n_splits)
    
    oof_preds = np.zeros((len(df), 3))
    models = []
    fold_metrics = []
    
    for fold, (train_idx, val_idx) in enumerate(splits, 1):
        print(f"\n{'─'*70}")
        print(f"Fold {fold}/{len(splits)}")
        print(f"{'─'*70}")
        
        X_train, X_val = X[train_idx], X[val_idx]
        y_train, y_val = y_encoded[train_idx], y_encoded[val_idx]
        
        train_data = lgb.Dataset(X_train, label=y_train, feature_name=feature_cols)
        val_data = lgb.Dataset(X_val, label=y_val, reference=train_data, feature_name=feature_cols)
        
        model = lgb.train(
            LGBM_PARAMS,
            train_data,
            num_boost_round=2000,
            valid_sets=[val_data],
            callbacks=[
                lgb.early_stopping(stopping_rounds=200),
                lgb.log_evaluation(period=100)
            ]
        )
        
        val_preds = model.predict(X_val, num_iteration=model.best_iteration)
        oof_preds[val_idx] = val_preds
        
        metrics = compute_metrics(y_val, val_preds)
        fold_metrics.append(metrics)
        
        print(f"\n  Fold {fold} Results:")
        print(f"    LogLoss:  {metrics['logloss']:.4f}")
        print(f"    Brier:    {metrics['brier']:.4f}")
        print(f"    3-way:    {metrics['accuracy_3way']*100:.1f}%")
        print(f"    2-way:    {metrics['accuracy_2way']*100:.1f}%")
        print(f"    Best iteration: {model.best_iteration}")
        
        models.append(model)
    
    # Overall OOF metrics
    oof_metrics = compute_metrics(y_encoded, oof_preds)
    
    print(f"\n{'='*70}")
    print(f"OUT-OF-FOLD RESULTS (n={len(df):,})")
    print(f"{'='*70}")
    print(f"  LogLoss:  {oof_metrics['logloss']:.4f}")
    print(f"  Brier:    {oof_metrics['brier']:.4f}")
    print(f"  3-way:    {oof_metrics['accuracy_3way']*100:.1f}%")
    print(f"  2-way:    {oof_metrics['accuracy_2way']*100:.1f}%")
    
    # Cross-fold variance
    ll_std = np.std([m['logloss'] for m in fold_metrics])
    acc_std = np.std([m['accuracy_3way'] for m in fold_metrics])
    print(f"\n  Cross-Fold Stability:")
    print(f"    LogLoss σ: {ll_std:.4f}")
    print(f"    3-way σ:   {acc_std:.4f}")
    
    # Feature importance
    feature_importance = np.mean([m.feature_importance(importance_type='gain') for m in models], axis=0)
    importance_df = pd.DataFrame({
        'feature': feature_cols,
        'importance': feature_importance
    }).sort_values('importance', ascending=False)
    
    print(f"\n{'='*70}")
    print(f"TOP 15 FEATURES (by gain)")
    print(f"{'='*70}")
    for idx, row in importance_df.head(15).iterrows():
        print(f"  {row['feature']:35s} {row['importance']:10.1f}")
    print(f"{'='*70}")
    
    return {
        'models': models,
        'oof_preds': oof_preds,
        'oof_metrics': oof_metrics,
        'fold_metrics': fold_metrics,
        'feature_importance': importance_df,
        'y_encoded': y_encoded,
        'feature_cols': feature_cols
    }


def save_model(results, output_dir='artifacts/models/lgbm_historical_36k'):
    """Save trained models and metadata"""
    os.makedirs(output_dir, exist_ok=True)
    
    # Save ensemble model (average predictions)
    with open(f'{output_dir}/lgbm_ensemble.pkl', 'wb') as f:
        pickle.dump(results['models'], f)
    
    # Save feature list
    with open(f'{output_dir}/features.json', 'w') as f:
        json.dump(results['feature_cols'], f, indent=2)
    
    # Save metadata
    metadata = {
        'timestamp': datetime.utcnow().isoformat(),
        'n_folds': len(results['models']),
        'n_features': len(results['feature_cols']),
        'params': LGBM_PARAMS,
        'oof_metrics': {
            'logloss': float(results['oof_metrics']['logloss']),
            'brier': float(results['oof_metrics']['brier']),
            'accuracy_3way': float(results['oof_metrics']['accuracy_3way']),
            'accuracy_2way': float(results['oof_metrics']['accuracy_2way'])
        },
        'fold_metrics': [
            {
                'logloss': float(m['logloss']),
                'brier': float(m['brier']),
                'accuracy_3way': float(m['accuracy_3way']),
                'accuracy_2way': float(m['accuracy_2way'])
            }
            for m in results['fold_metrics']
        ]
    }
    
    with open(f'{output_dir}/metadata.json', 'w') as f:
        json.dump(metadata, f, indent=2)
    
    # Save feature importance
    results['feature_importance'].to_csv(f'{output_dir}/feature_importance.csv', index=False)
    
    # Save OOF predictions
    np.save(f'{output_dir}/oof_predictions.npy', results['oof_preds'])
    np.save(f'{output_dir}/y_encoded.npy', results['y_encoded'])
    
    print(f"\n💾 Model saved to: {output_dir}")
    print(f"   - lgbm_ensemble.pkl")
    print(f"   - features.json")
    print(f"   - metadata.json")
    print(f"   - feature_importance.csv")
    print(f"   - oof_predictions.npy")


if __name__ == "__main__":
    print("="*70)
    print("LIGHTGBM TRAINING - 36K+ HISTORICAL DATASET")
    print("="*70)
    
    data_path = 'artifacts/datasets/v2_tabular_historical.parquet'
    
    print(f"\nLoading data from: {data_path}")
    df = pd.read_parquet(data_path)
    
    print(f"\n📊 Dataset Summary:")
    print(f"   Total matches: {len(df):,}")
    print(f"   Date range: {df['kickoff_date'].min()} → {df['kickoff_date'].max()}")
    print(f"   Leagues: {df['league'].nunique()}")
    print(f"\n   Outcome distribution:")
    outcome_dist = df['y'].value_counts(normalize=True).sort_index()
    for outcome, pct in outcome_dist.items():
        print(f"     {outcome}: {pct*100:.1f}%")
    
    # Identify feature columns
    exclude_cols = ['match_id', 'league', 'kickoff_date', 'y', 'season_year']
    feature_cols = [c for c in df.columns if c not in exclude_cols]
    
    print(f"\n   Features: {len(feature_cols)}")
    print(f"     Market: {sum(1 for f in feature_cols if 'p_' in f or 'prob_' in f or 'entropy' in f)}")
    print(f"     Form: {sum(1 for f in feature_cols if 'form' in f)}")
    print(f"     Historical: {sum(1 for f in feature_cols if any(x in f for x in ['h2h', 'last', 'adv_']))}")
    
    # Train (use 3 folds for faster training)
    results = train_lgbm_with_time_cv(df, feature_cols, n_splits=3)
    
    # Save
    save_model(results)
    
    print(f"\n{'='*70}")
    print("✅ TRAINING COMPLETE")
    print(f"{'='*70}")
    print(f"\nFinal OOF Performance:")
    print(f"  LogLoss:    {results['oof_metrics']['logloss']:.4f}")
    print(f"  Brier:      {results['oof_metrics']['brier']:.4f}")
    print(f"  3-way Acc:  {results['oof_metrics']['accuracy_3way']*100:.1f}%")
    print(f"  2-way Acc:  {results['oof_metrics']['accuracy_2way']*100:.1f}%")
    print(f"\n{'='*70}")
