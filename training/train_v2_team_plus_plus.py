"""
V2-Team++ Training Script - Phase 2 Model (50 features)

This script trains a LightGBM model using:
- Phase 1 features (46): odds, ELO, form, H2H, advanced stats, schedule
- Phase 2 features (4): rest_days, schedule_congestion

Expected accuracy lift: +1-3% over Phase 1 baseline
"""

import os
import sys
import pandas as pd
import numpy as np
import lightgbm as lgb
from sklearn.model_selection import StratifiedKFold
from sklearn.metrics import log_loss, confusion_matrix
import json
import pickle
from datetime import datetime
from pathlib import Path

sys.path.append('.')
from features.v2_feature_builder import get_v2_feature_builder
from sqlalchemy import create_engine, text

# CANONICAL LABEL MAPPING
CLASS_TO_IDX = {'H': 0, 'D': 1, 'A': 2}
IDX_TO_CLASS = ['H', 'D', 'A']

# LightGBM Parameters
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


def normalize_triplet(h: float, d: float, a: float) -> tuple:
    """Normalize probabilities to sum to 1"""
    total = h + d + a
    if total <= 0:
        return (1/3, 1/3, 1/3)
    return (h/total, d/total, a/total)


def compute_metrics(y_encoded, y_pred_proba):
    """Compute evaluation metrics"""
    normalized_preds = np.array([normalize_triplet(p[0], p[1], p[2]) for p in y_pred_proba])
    
    logloss = log_loss(y_encoded, normalized_preds, labels=[0, 1, 2])
    
    # Brier score (normalized)
    brier = np.mean(np.sum((normalized_preds - np.eye(3)[y_encoded])**2, axis=1))
    
    # Accuracy
    y_pred_class = np.argmax(normalized_preds, axis=1)
    accuracy = np.mean(y_pred_class == y_encoded)
    
    return {
        'logloss': logloss,
        'brier': brier / 3.0,
        'accuracy': accuracy
    }


def load_training_data(min_date='2023-07-01', max_date='2025-01-01', limit=None):
    """
    Load training data with 50 features using V2FeatureBuilder
    
    OPTIMIZED FOR PHASE 2 DEMONSTRATION:
    - Focuses on recent matches (2023-2024)
    - Includes 378 matches with real Phase 2 context data
    - Faster feature building for quick validation
    """
    print("="*70)
    print("  V2-TEAM++ DATA LOADING (Phase 2 - OPTIMIZED)")
    print("="*70)
    print(f"Date range: {min_date} to {max_date}")
    if limit:
        print(f"Limit: {limit} matches")
    
    database_url = os.getenv('DATABASE_URL')
    engine = create_engine(database_url)
    
    # Get finished matches with outcomes
    limit_clause = f"LIMIT {limit}" if limit else ""
    query = text(f"""
        SELECT 
            tm.match_id,
            tm.home_team,
            tm.away_team,
            tm.match_date,
            tm.outcome,
            tm.league_id,
            CASE WHEN mc.match_id IS NOT NULL THEN TRUE ELSE FALSE END as has_phase2_data
        FROM training_matches tm
        LEFT JOIN match_context mc ON tm.match_id = mc.match_id
        WHERE tm.match_date >= :min_date
          AND tm.match_date < :max_date
          AND tm.outcome IS NOT NULL
          AND tm.outcome IN ('H', 'D', 'A')
        ORDER BY tm.match_date DESC
        {limit_clause}
    """)
    
    with engine.connect() as conn:
        matches = pd.read_sql(query, conn, params={"min_date": min_date, "max_date": max_date})
    
    print(f"\n✅ Loaded {len(matches)} matches")
    print(f"   Date range: {matches['match_date'].min()} to {matches['match_date'].max()}")
    print(f"   Matches with Phase 2 data: {matches['has_phase2_data'].sum()} ({matches['has_phase2_data'].mean()*100:.1f}%)")
    print(f"   Outcome distribution:")
    print(f"      Home: {(matches['outcome']=='H').sum()} ({(matches['outcome']=='H').mean()*100:.1f}%)")
    print(f"      Draw: {(matches['outcome']=='D').sum()} ({(matches['outcome']=='D').mean()*100:.1f}%)")
    print(f"      Away: {(matches['outcome']=='A').sum()} ({(matches['outcome']=='A').mean()*100:.1f}%)")
    
    # Build features for all matches
    print(f"\n🔨 Building 50 features for {len(matches)} matches...")
    print("   This may take a few minutes...")
    
    builder = get_v2_feature_builder()
    features_list = []
    failed = 0
    
    for idx, row in matches.iterrows():
        try:
            features = builder.build_features(row['match_id'])
            features['match_id'] = row['match_id']
            features['outcome'] = row['outcome']
            features['match_date'] = row['match_date']
            features_list.append(features)
            
            if (idx + 1) % 500 == 0:
                print(f"   Processed {idx+1}/{len(matches)} matches...")
        except Exception as e:
            failed += 1
            if failed < 10:
                print(f"   ⚠️  Failed match {row['match_id']}: {e}")
    
    df = pd.DataFrame(features_list)
    
    print(f"\n✅ Feature extraction complete")
    print(f"   Success: {len(df)} matches")
    print(f"   Failed: {failed} matches")
    print(f"   Features: {len([c for c in df.columns if c not in ['match_id', 'outcome', 'match_date']])} columns")
    
    return df


def train_lgbm_cv(df, n_splits=5):
    """Train LightGBM with stratified K-fold CV"""
    print(f"\n{'='*70}")
    print(f"  V2-TEAM++ TRAINING (Phase 2 - 50 Features)")
    print(f"{'='*70}")
    
    # Extract features (exclude metadata columns)
    feature_cols = [c for c in df.columns if c not in ['match_id', 'outcome', 'match_date']]
    
    print(f"Training with {len(feature_cols)} features")
    print(f"Phase 1 features: 46 (odds, ELO, form, H2H, advanced, schedule)")
    print(f"Phase 2 features: 4 (rest_days_home/away, schedule_congestion_home/away_7d)")
    print(f"\nFirst 10 features: {feature_cols[:10]}")
    
    X = df[feature_cols].values
    y = df['outcome'].values
    y_encoded = df['outcome'].map(CLASS_TO_IDX).values
    
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
            num_boost_round=300,
            valid_sets=[val_data],
            callbacks=[lgb.early_stopping(stopping_rounds=30), lgb.log_evaluation(period=0)]
        )
        
        val_preds = model.predict(X_val, num_iteration=model.best_iteration)
        oof_preds[val_idx] = val_preds
        
        fold_metrics_dict = compute_metrics(y_encoded[val_idx], val_preds)
        fold_metrics.append(fold_metrics_dict)
        
        print(f"  LogLoss: {fold_metrics_dict['logloss']:.4f}")
        print(f"  Brier:   {fold_metrics_dict['brier']:.4f}")
        print(f"  Accuracy: {fold_metrics_dict['accuracy']*100:.1f}%")
        
        models.append(model)
    
    oof_metrics = compute_metrics(y_encoded, oof_preds)
    
    # Confusion matrix
    pred_idx = oof_preds.argmax(axis=1)
    cm = confusion_matrix(y_encoded, pred_idx, labels=[0, 1, 2])
    
    print(f"\n{'='*70}")
    print(f"  CONFUSION MATRIX")
    print(f"{'='*70}")
    print(f"          Predicted")
    print(f"         H    D    A")
    print(f"True H  {cm[0,0]:4d}  {cm[0,1]:3d}  {cm[0,2]:3d}")
    print(f"     D  {cm[1,0]:4d}  {cm[1,1]:3d}  {cm[1,2]:3d}")
    print(f"     A  {cm[2,0]:4d}  {cm[2,1]:3d}  {cm[2,2]:3d}")
    
    print(f"\n{'='*70}")
    print(f"  V2-TEAM++ OUT-OF-FOLD METRICS (n={len(df)})")
    print(f"{'='*70}")
    print(f"  LogLoss:  {oof_metrics['logloss']:.4f}")
    print(f"  Brier:    {oof_metrics['brier']:.4f}")
    print(f"  Accuracy: {oof_metrics['accuracy']*100:.1f}%")
    print(f"{'='*70}")
    
    # Feature importance
    feature_importance = np.mean([m.feature_importance(importance_type='gain') for m in models], axis=0)
    importance_df = pd.DataFrame({
        'feature': feature_cols,
        'importance': feature_importance
    }).sort_values('importance', ascending=False)
    
    print(f"\nTop 20 Features by Importance:")
    for idx, row in importance_df.head(20).iterrows():
        phase = "Phase 2" if 'rest_days' in row['feature'] or 'schedule_congestion' in row['feature'] else "Phase 1"
        print(f"  {row['feature']:35s} {row['importance']:8.1f}  [{phase}]")
    
    # Check Phase 2 feature importance
    phase2_features = [f for f in feature_cols if 'rest_days' in f or 'schedule_congestion' in f]
    phase2_importance = importance_df[importance_df['feature'].isin(phase2_features)]
    print(f"\nPhase 2 Feature Rankings:")
    for idx, row in phase2_importance.iterrows():
        rank = list(importance_df['feature']).index(row['feature']) + 1
        print(f"  {row['feature']:35s} Rank: {rank:2d}/50  Importance: {row['importance']:8.1f}")
    
    return {
        'models': models,
        'oof_preds': oof_preds,
        'oof_metrics': oof_metrics,
        'fold_metrics': fold_metrics,
        'feature_importance': importance_df,
        'feature_cols': feature_cols,
        'y_encoded': y_encoded
    }


def save_model(results, output_dir='artifacts/models/v2_team_plus_plus'):
    """Save trained model"""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    print(f"\n💾 Saving model to {output_path}...")
    
    # Save models
    with open(output_path / "lgbm_ensemble.pkl", "wb") as f:
        pickle.dump(results['models'], f)
    
    # Save features
    with open(output_path / "features.json", "w") as f:
        json.dump(results['feature_cols'], f, indent=2)
    
    # Save metadata
    metadata = {
        'model_name': 'V2-Team++',
        'phase': 'Phase 2',
        'total_features': len(results['feature_cols']),
        'phase1_features': 46,
        'phase2_features': 4,
        'trained_at': datetime.now().isoformat(),
        'oof_metrics': results['oof_metrics'],
        'fold_metrics': results['fold_metrics'],
        'feature_list': results['feature_cols']
    }
    
    with open(output_path / "metadata.json", "w") as f:
        json.dump(metadata, f, indent=2)
    
    # Save feature importance
    results['feature_importance'].to_csv(output_path / "feature_importance.csv", index=False)
    
    print(f"✅ Model saved successfully")
    print(f"   - lgbm_ensemble.pkl")
    print(f"   - features.json ({len(results['feature_cols'])} features)")
    print(f"   - metadata.json")
    print(f"   - feature_importance.csv")


def main():
    """Main training pipeline"""
    print("\n" + "="*70)
    print("  V2-TEAM++ MODEL TRAINING - PHASE 2 DEMONSTRATION")
    print("  50 Features: Phase 1 (46) + Phase 2 (4)")
    print("  Training on recent matches (2023-2024) for quick validation")
    print("="*70)
    
    # Load data - focus on recent matches for speed
    df = load_training_data(min_date='2023-07-01', max_date='2025-01-01', limit=3000)
    
    # Train model
    results = train_lgbm_cv(df, n_splits=5)
    
    # Save model
    save_model(results)
    
    print("\n" + "="*70)
    print("  ✅ V2-TEAM++ TRAINING COMPLETE")
    print("="*70)
    print(f"  Final Accuracy: {results['oof_metrics']['accuracy']*100:.1f}%")
    print(f"  Final LogLoss:  {results['oof_metrics']['logloss']:.4f}")
    print(f"  Final Brier:    {results['oof_metrics']['brier']:.4f}")
    print("="*70)
    
    return results


if __name__ == "__main__":
    results = main()
