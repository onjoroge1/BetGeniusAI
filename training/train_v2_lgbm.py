"""
LightGBM Training for V2 Model - Dry Run

Experiments:
1. LGBM_market_only: Only market features (open/close/drift/dispersion/volatility)
2. LGBM_full: Market features + ELO ratings

This is a PIPELINE VALIDATION dry run, not production promotion.
"""

import os
import sys
import pandas as pd
import numpy as np
import lightgbm as lgb
from sklearn.model_selection import StratifiedKFold
from sklearn.metrics import log_loss, confusion_matrix
import json
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# CANONICAL LABEL MAPPING - matches prediction vector [p_home, p_draw, p_away]
CLASS_TO_IDX = {'H': 0, 'D': 1, 'A': 2}
IDX_TO_CLASS = ['H', 'D', 'A']

# Unit test - lock this mapping forever
assert CLASS_TO_IDX['H'] == 0 and CLASS_TO_IDX['D'] == 1 and CLASS_TO_IDX['A'] == 2, "Label mapping broken!"
assert IDX_TO_CLASS == ['H', 'D', 'A'], "Index to class mapping broken!"

MARKET_ONLY_FEATURES = [
    "p_last_home", "p_last_draw", "p_last_away",
    "p_open_home", "p_open_draw", "p_open_away",
    "prob_drift_home", "prob_drift_draw", "prob_drift_away",
    "drift_magnitude",
    "book_dispersion", "dispersion_home", "dispersion_draw", "dispersion_away",
    "volatility_home", "volatility_draw", "volatility_away",
    "market_entropy", "favorite_margin"
]

FULL_FEATURES = MARKET_ONLY_FEATURES + [
    "home_elo", "away_elo", "elo_diff"
]

LGBM_PARAMS = {
    "objective": "multiclass",
    "num_class": 3,
    "learning_rate": 0.05,
    "num_leaves": 31,
    "feature_fraction": 0.8,
    "min_data_in_leaf": 40,
    "lambda_l2": 2.0,
    "metric": "multi_logloss",
    "verbosity": -1,
    "seed": 42
}


def compute_metrics(y_encoded, y_pred_proba):
    """Compute evaluation metrics using canonical label order"""
    from services.metrics import normalize_triplet
    
    normalized_preds = np.array([normalize_triplet(p[0], p[1], p[2]) for p in y_pred_proba])
    
    # Use sklearn's log_loss with explicit label order
    logloss = log_loss(y_encoded, normalized_preds, labels=[0, 1, 2])
    
    # Brier score
    brier = np.mean(np.sum((normalized_preds - np.eye(3)[y_encoded])**2, axis=1))
    
    # Accuracy
    y_pred_class = np.argmax(normalized_preds, axis=1)
    accuracy = np.mean(y_pred_class == y_encoded)
    
    return {
        'logloss': logloss,
        'brier': brier / 3.0,  # Normalize to [0,1]
        'accuracy': accuracy
    }


def train_lgbm_cv(df, features, n_splits=5):
    """Train LightGBM with stratified K-fold CV using canonical label order"""
    print(f"\n{'='*70}")
    print(f"Training LightGBM with {len(features)} features")
    print(f"{'='*70}")
    print(f"Features: {features[:5]}... (showing first 5)")
    print(f"Label mapping: {CLASS_TO_IDX}")
    
    X = df[features].values
    y = df['y'].values
    
    # Use canonical mapping - never use LabelEncoder here
    y_encoded = df['y'].map(CLASS_TO_IDX).values
    
    skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)
    
    oof_preds = np.zeros((len(df), 3))
    models = []
    fold_metrics = []
    
    for fold, (train_idx, val_idx) in enumerate(skf.split(X, y_encoded), 1):
        print(f"\n--- Fold {fold}/{n_splits} ---")
        
        X_train, X_val = X[train_idx], X[val_idx]
        y_train, y_val = y_encoded[train_idx], y_encoded[val_idx]
        
        train_data = lgb.Dataset(X_train, label=y_train)
        val_data = lgb.Dataset(X_val, label=y_val, reference=train_data)
        
        model = lgb.train(
            LGBM_PARAMS,
            train_data,
            num_boost_round=200,
            valid_sets=[val_data],
            callbacks=[lgb.early_stopping(stopping_rounds=20), lgb.log_evaluation(period=0)]
        )
        
        val_preds = model.predict(X_val, num_iteration=model.best_iteration)
        oof_preds[val_idx] = val_preds
        
        fold_metrics_dict = compute_metrics(y_encoded[val_idx], val_preds)
        fold_metrics.append(fold_metrics_dict)
        
        print(f"  LogLoss: {fold_metrics_dict['logloss']:.4f}")
        print(f"  Brier:   {fold_metrics_dict['brier']:.4f}")
        print(f"  Hit:     {fold_metrics_dict['accuracy']*100:.1f}%")
        
        models.append(model)
    
    oof_metrics = compute_metrics(y_encoded, oof_preds)
    
    # Confusion matrix sanity check
    pred_idx = oof_preds.argmax(axis=1)
    cm = confusion_matrix(y_encoded, pred_idx, labels=[0, 1, 2])
    print(f"\nConfusion Matrix (H, D, A order):")
    print(f"          Predicted")
    print(f"         H    D    A")
    print(f"True H  {cm[0,0]:3d}  {cm[0,1]:3d}  {cm[0,2]:3d}")
    print(f"     D  {cm[1,0]:3d}  {cm[1,1]:3d}  {cm[1,2]:3d}")
    print(f"     A  {cm[2,0]:3d}  {cm[2,1]:3d}  {cm[2,2]:3d}")
    
    print(f"\n{'='*70}")
    print(f"OUT-OF-FOLD METRICS (n={len(df)})")
    print(f"{'='*70}")
    print(f"  LogLoss: {oof_metrics['logloss']:.4f}")
    print(f"  Brier:   {oof_metrics['brier']:.4f}")
    print(f"  Hit:     {oof_metrics['accuracy']*100:.1f}%")
    print(f"{'='*70}")
    
    feature_importance = np.mean([m.feature_importance(importance_type='gain') for m in models], axis=0)
    importance_df = pd.DataFrame({
        'feature': features,
        'importance': feature_importance
    }).sort_values('importance', ascending=False)
    
    print(f"\nTop 10 Features by Importance:")
    for idx, row in importance_df.head(10).iterrows():
        print(f"  {row['feature']:30s} {row['importance']:8.1f}")
    
    return {
        'models': models,
        'oof_preds': oof_preds,
        'oof_metrics': oof_metrics,
        'fold_metrics': fold_metrics,
        'feature_importance': importance_df,
        'y_encoded': y_encoded
    }


def compare_to_ridge(df, lgbm_preds, y_encoded):
    """Compare LightGBM predictions to V2 ridge on same samples"""
    print(f"\n{'='*70}")
    print(f"PAIRED COMPARISON: LGBM vs V2 RIDGE (same matches)")
    print(f"{'='*70}")
    
    import psycopg2
    from models.database import DatabaseManager
    
    db_manager = DatabaseManager()
    conn = psycopg2.connect(db_manager.database_url)
    cursor = conn.cursor()
    
    match_ids = tuple(df['match_id'].tolist())
    
    cursor.execute(f"""
        SELECT 
            match_id,
            p_home, p_draw, p_away
        FROM model_inference_logs
        WHERE match_id IN %s
          AND model_version = 'v2'
    """, (match_ids,))
    
    ridge_preds = {}
    for row in cursor.fetchall():
        match_id = row[0]
        if row[1] is not None:
            ridge_preds[match_id] = np.array([float(row[1]), float(row[2]), float(row[3])])
    
    cursor.close()
    conn.close()
    
    common_matches = [mid for mid in df['match_id'] if mid in ridge_preds]
    
    if len(common_matches) == 0:
        print("⚠️  No overlapping predictions with V2 ridge found")
        return None
    
    print(f"Found {len(common_matches)} matches with V2 ridge predictions")
    
    df_common = df[df['match_id'].isin(common_matches)].copy()
    df_common = df_common.sort_values('match_id')
    
    ridge_probs = np.array([ridge_preds[mid] for mid in df_common['match_id']])
    
    # Get LGBM predictions for common matches (already in same order)
    common_indices = df[df['match_id'].isin(common_matches)].index
    lgbm_probs = lgbm_preds[common_indices]
    y_common = y_encoded[common_indices]
    
    ridge_metrics = compute_metrics(y_common, ridge_probs)
    lgbm_metrics = compute_metrics(y_common, lgbm_probs)
    
    print(f"\nV2 Ridge:")
    print(f"  LogLoss: {ridge_metrics['logloss']:.4f}")
    print(f"  Brier:   {ridge_metrics['brier']:.4f}")
    print(f"  Hit:     {ridge_metrics['accuracy']*100:.1f}%")
    
    print(f"\nLightGBM:")
    print(f"  LogLoss: {lgbm_metrics['logloss']:.4f}")
    print(f"  Brier:   {lgbm_metrics['brier']:.4f}")
    print(f"  Hit:     {lgbm_metrics['accuracy']*100:.1f}%")
    
    print(f"\nΔ (LGBM - Ridge):")
    print(f"  Δ LogLoss: {lgbm_metrics['logloss'] - ridge_metrics['logloss']:+.4f}")
    print(f"  Δ Brier:   {lgbm_metrics['brier'] - ridge_metrics['brier']:+.4f}")
    print(f"  Δ Hit:     {(lgbm_metrics['accuracy'] - ridge_metrics['accuracy'])*100:+.1f} pts")
    
    return {
        'n_common': len(common_matches),
        'ridge_metrics': ridge_metrics,
        'lgbm_metrics': lgbm_metrics,
        'deltas': {
            'logloss': lgbm_metrics['logloss'] - ridge_metrics['logloss'],
            'brier': lgbm_metrics['brier'] - ridge_metrics['brier'],
            'accuracy': lgbm_metrics['accuracy'] - ridge_metrics['accuracy']
        }
    }


def analyze_ev_deciles(df, preds, y_encoded, p_close=None):
    """Analyze EV performance by decile with monotonicity check"""
    from services.metrics import normalize_triplet
    
    normalized_preds = np.array([normalize_triplet(p[0], p[1], p[2]) for p in preds])
    
    max_probs = np.max(normalized_preds, axis=1)
    picks = np.argmax(normalized_preds, axis=1)
    pick_correct = (picks == y_encoded).astype(int)
    
    # Calculate EV if closing probabilities available
    if p_close is not None:
        pick_model_prob = normalized_preds[np.arange(len(preds)), picks]
        pick_close_prob = p_close[np.arange(len(preds)), picks]
        ev_pick = pick_model_prob - pick_close_prob
    else:
        ev_pick = None
    
    # Decile analysis
    if ev_pick is not None:
        ev_df = pd.DataFrame({
            'ev': ev_pick,
            'pick_correct': pick_correct,
            'max_prob': max_probs
        })
        bins = pd.qcut(ev_df['ev'], q=10, labels=False, duplicates='drop')
        ev_df['bin'] = bins
        
        print(f"\n{'='*70}")
        print(f"EV DECILE ANALYSIS (by EV, not max_prob)")
        print(f"{'='*70}")
        print(f"Decile | Avg EV  | Hit Rate | Count")
        print(f"-------|---------|----------|------")
        
        for decile in sorted(ev_df['bin'].unique()):
            decile_data = ev_df[ev_df['bin'] == decile]
            avg_ev = decile_data['ev'].mean()
            hit_rate = decile_data['pick_correct'].mean()
            count = len(decile_data)
            print(f"  {decile:2d}   | {avg_ev:+.4f}  |  {hit_rate:.1%}  | {count:4d}")
    else:
        ev_df = pd.DataFrame({
            'max_prob': max_probs,
            'pick_correct': pick_correct
        })
        ev_df['decile'] = pd.qcut(ev_df['max_prob'], q=10, labels=False, duplicates='drop')
        
        print(f"\n{'='*70}")
        print(f"CONFIDENCE DECILE ANALYSIS (by max_prob)")
        print(f"{'='*70}")
        print(f"Decile | Avg Max Prob | Hit Rate | Count")
        print(f"-------|--------------|----------|------")
        
        for decile in sorted(ev_df['decile'].unique()):
            decile_data = ev_df[ev_df['decile'] == decile]
            avg_prob = decile_data['max_prob'].mean()
            hit_rate = decile_data['pick_correct'].mean()
            count = len(decile_data)
            print(f"  {decile:2d}   |    {avg_prob:.3f}     |  {hit_rate:.1%}  | {count:4d}")
    
    print(f"{'='*70}")


if __name__ == "__main__":
    print("="*70)
    print("LIGHTGBM DRY RUN - PIPELINE VALIDATION")
    print("="*70)
    
    data_path = 'artifacts/datasets/v2_tabular.parquet'
    df = pd.read_parquet(data_path)
    
    print(f"\nDataset: {data_path}")
    print(f"  Samples: {len(df)}")
    print(f"  Leagues: {df['league'].nunique()}")
    print(f"  Date range: {df['kickoff_date'].min()} → {df['kickoff_date'].max()}")
    
    results = {}
    
    print("\n" + "="*70)
    print("EXPERIMENT 1: MARKET-ONLY FEATURES")
    print("="*70)
    results['market_only'] = train_lgbm_cv(df, MARKET_ONLY_FEATURES)
    analyze_ev_deciles(df, results['market_only']['oof_preds'], results['market_only']['y_encoded'])
    compare_to_ridge(df, results['market_only']['oof_preds'], results['market_only']['y_encoded'])
    
    print("\n" + "="*70)
    print("EXPERIMENT 2: FULL FEATURES (Market + ELO)")
    print("="*70)
    results['full'] = train_lgbm_cv(df, FULL_FEATURES)
    analyze_ev_deciles(df, results['full']['oof_preds'], results['full']['y_encoded'])
    compare_to_ridge(df, results['full']['oof_preds'], results['full']['y_encoded'])
    
    print("\n" + "="*70)
    print("SUMMARY COMPARISON")
    print("="*70)
    print(f"\nMarket-Only OOF LogLoss: {results['market_only']['oof_metrics']['logloss']:.4f}")
    print(f"Full OOF LogLoss:        {results['full']['oof_metrics']['logloss']:.4f}")
    print(f"Δ (Full - Market):       {results['full']['oof_metrics']['logloss'] - results['market_only']['oof_metrics']['logloss']:+.4f}")
    
    if abs(results['full']['oof_metrics']['logloss'] - results['market_only']['oof_metrics']['logloss']) < 0.005:
        print("\n✅ ELO features not helping (variance too tight, as expected)")
    
    output_dir = 'artifacts/models/lgbm_dryrun'
    os.makedirs(output_dir, exist_ok=True)
    
    summary = {
        'timestamp': datetime.utcnow().isoformat(),
        'dataset': {
            'path': data_path,
            'n_samples': len(df),
            'n_leagues': int(df['league'].nunique()),
            'date_range': [str(df['kickoff_date'].min()), str(df['kickoff_date'].max())]
        },
        'market_only': {
            'oof_logloss': results['market_only']['oof_metrics']['logloss'],
            'oof_brier': results['market_only']['oof_metrics']['brier'],
            'oof_accuracy': results['market_only']['oof_metrics']['accuracy']
        },
        'full': {
            'oof_logloss': results['full']['oof_metrics']['logloss'],
            'oof_brier': results['full']['oof_metrics']['brier'],
            'oof_accuracy': results['full']['oof_metrics']['accuracy']
        }
    }
    
    with open(f'{output_dir}/dryrun_summary.json', 'w') as f:
        json.dump(summary, f, indent=2)
    
    print(f"\n💾 Results saved to: {output_dir}/dryrun_summary.json")
    print("\n" + "="*70)
    print("DRY RUN COMPLETE")
    print("="*70)
