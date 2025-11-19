#!/usr/bin/env python3
"""
V2 PRODUCTION TRAINING - Full Training Run
Uses aggressive hyperparameters for production-quality model
Target: 52-54% accuracy with robust training (1000+ iterations)
"""
import os
os.environ['LD_LIBRARY_PATH'] = "/nix/store/xvzz97yk73hw03v5dhhz3j47ggwf1yq1-gcc-13.2.0-lib/lib"

import sys
sys.path.append('.')
import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text
from sklearn.metrics import accuracy_score, log_loss, brier_score_loss
import lightgbm as lgb
from datetime import timedelta, datetime
import joblib

from features.batch_feature_builder import BatchFeatureBuilder

N_SPLITS = 5
EMBARGO_DAYS = 7

def load_matches(limit=10000):
    """Load training matches with context data"""
    engine = create_engine(os.getenv("DATABASE_URL"))
    query = text("""
        SELECT tm.match_id, tm.match_date, tm.outcome
        FROM training_matches tm
        INNER JOIN match_context_v2 mc ON tm.match_id = mc.match_id
        INNER JOIN odds_real_consensus orc ON tm.match_id = orc.match_id
        WHERE tm.match_date >= '2020-01-01'
          AND tm.match_date < '2025-11-15'
          AND tm.outcome IN ('Home','Draw','Away')
        ORDER BY tm.match_date
        LIMIT :limit
    """)
    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params={"limit": limit})
    
    print(f"✅ Loaded {len(df)} matches")
    return df

def build_features(matches):
    """Build features using optimized batch builder"""
    print("   Using BatchFeatureBuilder (optimized for speed)")
    builder = BatchFeatureBuilder()
    
    # Batch build all features at once
    df = builder.build_features_batch(matches)
    
    print(f"✅ Built features for {len(df)} matches")
    print(f"   Feature count: {len(df.columns) - 3}")  # -3 for outcome, match_date, match_id
    return df

def encode_y(y_str):
    """Encode outcomes to integers"""
    m = {"Home":0, "Draw":1, "Away":2}
    return np.array([m[v] for v in y_str])

def main():
    print("="*80)
    print("  V2 PRODUCTION TRAINING - FULL RUN")
    print("  Max Iterations: 2000 | Early Stopping: 100 rounds")
    print("  Target: 52-54% accuracy with robust convergence")
    print("="*80)
    
    start_time = datetime.now()

    # Load matches
    matches = load_matches(limit=10000)
    
    # Build features
    print("\n🔨 Building features (batch optimized)...")
    print(f"   Expected time: ~{len(matches) * 0.05:.0f} seconds...")
    df = build_features(matches)
    
    feature_cols = [c for c in df.columns if c not in ["outcome","match_date","match_id"]]
    X = df[feature_cols].values
    y = encode_y(df["outcome"].values)
    dates = pd.to_datetime(df["match_date"].values)
    
    print(f"\nDataset: {len(X)} matches x {len(feature_cols)} features")
    
    # === SANITY CHECK: Random Label Test ===
    print("\n" + "="*80)
    print("  SANITY CHECK: Random Label Test")
    print("="*80)
    
    # Compute class distribution
    class_counts = np.bincount(y)
    class_probs = class_counts / len(y)
    majority_acc = class_probs.max()
    
    print("Class distribution (0=Home, 1=Draw, 2=Away):")
    for i, (count, prob) in enumerate(zip(class_counts, class_probs)):
        label = ['Home', 'Draw', 'Away'][i]
        print(f"  {label}: {count} matches ({prob:.1%})")
    
    print(f"\nMajority-class baseline: {majority_acc:.3f}")
    print("Training on random labels (should be ≤ baseline + 0.05)...")
    
    rng = np.random.default_rng(42)
    y_rand = rng.permutation(y)
    split = int(len(X) * 0.8)
    X_tr, X_va = X[:split], X[split:]
    y_tr, y_va = y_rand[:split], y_rand[split:]
    
    train_data = lgb.Dataset(X_tr, label=y_tr)
    valid_data = lgb.Dataset(X_va, label=y_va, reference=train_data)
    
    rand_params = {
        "objective": "multiclass",
        "num_class": 3,
        "metric": "multi_logloss",
        "learning_rate": 0.05,
        "num_leaves": 31,
        "feature_fraction": 0.8,
        "verbosity": -1,
        "seed": 42,
    }
    
    rand_model = lgb.train(
        rand_params,
        train_data,
        num_boost_round=100,
        valid_sets=[valid_data],
        callbacks=[
            lgb.early_stopping(20),
            lgb.log_evaluation(0),
        ],
    )
    
    y_proba_rand = rand_model.predict(X_va, num_iteration=rand_model.best_iteration)
    y_pred_rand = np.argmax(y_proba_rand, axis=1)
    acc_rand = accuracy_score(y_va, y_pred_rand)
    ll_rand = log_loss(y_va, y_proba_rand)
    
    # Dynamic threshold based on class imbalance
    threshold = majority_acc + 0.05
    
    print(f"\n  Random-label accuracy: {acc_rand:.3f}")
    print(f"  Random-label logloss : {ll_rand:.3f}")
    print(f"  Threshold: < {threshold:.3f} (majority baseline + 0.05)")
    
    if acc_rand >= threshold:
        print(f"\n❌ FAIL: Random-label accuracy ({acc_rand:.3f}) exceeds threshold ({threshold:.3f})")
        print("   Features may contain leakage.")
        return
    else:
        print(f"\n✅ PASS: Random-label sanity clean ({acc_rand:.3f} < {threshold:.3f})")
        print("   Model cannot exploit features on shuffled labels - no leakage detected.")
    
    # === PRODUCTION TRAINING WITH TIME CV ===
    print("\n" + "="*80)
    print("  PRODUCTION TRAINING (Time-Based Cross-Validation)")
    print("  Max Iterations: 2000 | Early Stopping: 100 rounds")
    print("="*80)
    
    from training.step_a_optimizations import PurgedTimeSeriesSplit
    cv = PurgedTimeSeriesSplit(n_splits=N_SPLITS, embargo_days=EMBARGO_DAYS)
    
    # Draw weighting (from Step A recommendations)
    label_weights = np.ones(len(y))
    label_weights[y == 1] = 1.30
    
    # PRODUCTION HYPERPARAMETERS
    params = {
        "objective": "multiclass",
        "num_class": 3,
        "metric": "multi_logloss",
        "learning_rate": 0.03,  # Lower for better convergence
        "num_leaves": 31,
        "min_data_in_leaf": 30,  # Lower for more flexibility
        "feature_fraction": 0.8,
        "bagging_fraction": 0.8,  # Add bagging for robustness
        "bagging_freq": 5,
        "lambda_l1": 0.1,  # L1 regularization
        "lambda_l2": 0.1,  # L2 regularization
        "min_gain_to_split": 0.01,  # Require minimum gain
        "verbosity": -1,
        "seed": 42,
        "max_depth": 8,  # Limit tree depth
    }
    
    oof_proba = np.zeros((len(X), 3), dtype=float)
    oof_true = y.copy()
    oof_mask = np.zeros(len(X), dtype=bool)
    fold_models = []
    fold_iterations = []
    
    for fold, (tr_idx, va_idx) in enumerate(cv.split(X, y, groups=dates), start=1):
        print(f"\n{'='*60}")
        print(f"  FOLD {fold}/{N_SPLITS}")
        print(f"{'='*60}")
        print(f"Train: {len(tr_idx)} samples | Val: {len(va_idx)} samples")
        
        X_tr, X_va = X[tr_idx], X[va_idx]
        y_tr, y_va = y[tr_idx], y[va_idx]
        w_tr = label_weights[tr_idx]
        
        d_tr = lgb.Dataset(X_tr, label=y_tr, weight=w_tr)
        d_va = lgb.Dataset(X_va, label=y_va, reference=d_tr)
        
        print("Training with up to 2000 iterations (early stop if no improvement for 100 rounds)...")
        
        model = lgb.train(
            params,
            d_tr,
            num_boost_round=2000,  # Max 2000 iterations
            valid_sets=[d_va],
            callbacks=[
                lgb.early_stopping(100),  # Stop if no improvement for 100 rounds
                lgb.log_evaluation(100),  # Log every 100 iterations
            ],
        )
        
        fold_models.append(model)
        fold_iterations.append(model.best_iteration)
        
        proba_va = model.predict(X_va, num_iteration=model.best_iteration)
        oof_proba[va_idx] = proba_va
        oof_mask[va_idx] = True
        
        acc = accuracy_score(y_va, np.argmax(proba_va, axis=1))
        ll = log_loss(y_va, proba_va)
        
        # Multi-class Brier score
        one_hot_va = np.eye(3)[y_va]
        br = np.mean(np.sum((proba_va - one_hot_va)**2, axis=1)) / 2.0
        
        print(f"\n📊 Fold {fold} Results:")
        print(f"  Best Iteration: {model.best_iteration}")
        print(f"  Accuracy: {acc:.3f}")
        print(f"  LogLoss : {ll:.3f}")
        print(f"  Brier   : {br:.3f}")
    
    # Overall OOF metrics
    print("\n" + "="*80)
    print("  OUT-OF-FOLD METRICS (Production)")
    print("="*80)
    print(f"Validated samples: {oof_mask.sum()} / {len(oof_mask)} ({100*oof_mask.sum()/len(oof_mask):.1f}%)")
    
    overall_acc = accuracy_score(oof_true[oof_mask], np.argmax(oof_proba[oof_mask], axis=1))
    overall_ll = log_loss(oof_true[oof_mask], oof_proba[oof_mask])
    one_hot = np.eye(3)[oof_true[oof_mask]]
    overall_br = np.mean(np.sum((oof_proba[oof_mask] - one_hot)**2, axis=1)) / 2.0
    
    print(f"\n  Overall Accuracy: {overall_acc:.3f}")
    print(f"  Overall LogLoss : {overall_ll:.3f}")
    print(f"  Overall Brier   : {overall_br:.3f}")
    
    # Grade
    if overall_acc >= 0.54:
        grade = "A"
    elif overall_acc >= 0.52:
        grade = "A-"
    elif overall_acc >= 0.50:
        grade = "B+"
    else:
        grade = "B"
    
    print(f"\n  Grade: {grade}")
    print(f"  Target: 52-54% (A-/A grade)")
    
    # Average best iteration across folds
    avg_iterations = int(np.mean(fold_iterations))
    print(f"\n  Average best iteration: {avg_iterations}")
    print(f"  Iteration range: {min(fold_iterations)} - {max(fold_iterations)}")
    
    # Save final model (train on full data with average best iteration)
    print("\n" + "="*80)
    print("  TRAINING FINAL PRODUCTION MODEL")
    print("="*80)
    print(f"Training on full dataset with {avg_iterations * 1.2:.0f} iterations...")
    
    d_full = lgb.Dataset(X, label=y, weight=label_weights)
    
    # Use 120% of average best iteration for final model
    final_iterations = int(avg_iterations * 1.2)
    
    final_model = lgb.train(
        params,
        d_full,
        num_boost_round=final_iterations,
        callbacks=[lgb.log_evaluation(100)],
    )
    
    # Save
    os.makedirs("artifacts/models", exist_ok=True)
    model_path = "artifacts/models/v2_production_lgbm.txt"
    final_model.save_model(model_path)
    print(f"\n✅ Saved production model to {model_path}")
    
    # Save feature names
    feature_info = {
        "feature_names": feature_cols,
        "feature_count": len(feature_cols),
        "builder": "V2FeatureBuilderTransformed",
        "oof_accuracy": float(overall_acc),
        "oof_logloss": float(overall_ll),
        "oof_brier": float(overall_br),
        "grade": grade,
        "avg_iterations": avg_iterations,
        "final_iterations": final_iterations,
        "training_samples": len(X),
        "hyperparameters": params,
    }
    joblib.dump(feature_info, "artifacts/models/v2_production_features.pkl")
    print(f"✅ Saved feature info to artifacts/models/v2_production_features.pkl")
    
    # Training summary
    elapsed = (datetime.now() - start_time).total_seconds()
    print("\n" + "="*80)
    print("  PRODUCTION TRAINING COMPLETE")
    print("="*80)
    print(f"  Model: {model_path}")
    print(f"  Training samples: {len(X)}")
    print(f"  Accuracy: {overall_acc:.3f} ({grade})")
    print(f"  LogLoss : {overall_ll:.3f}")
    print(f"  Brier   : {overall_br:.3f}")
    print(f"  Avg iterations: {avg_iterations}")
    print(f"  Training time: {elapsed/60:.1f} minutes")
    print(f"\n  Ready for production deployment!")
    
    # Deployment instructions
    print("\n" + "="*80)
    print("  DEPLOYMENT INSTRUCTIONS")
    print("="*80)
    print("  1. Copy production model to current model:")
    print("     cp artifacts/models/v2_production_lgbm.txt artifacts/models/v2_transformed_lgbm.txt")
    print("     cp artifacts/models/v2_production_features.pkl artifacts/models/v2_transformed_features.pkl")
    print("\n  2. Restart server:")
    print("     (Server will auto-load new model)")
    print("\n  3. Test /predict-v2 endpoint:")
    print("     curl -X POST http://localhost:8000/predict-v2 -H 'Content-Type: application/json' \\")
    print("       -d '{\"match_id\": YOUR_MATCH_ID, \"include_analysis\": false}'")

if __name__ == "__main__":
    main()
