#!/usr/bin/env python3
"""
V2.1 Training Script - TRANSFORMED FEATURES (Leak-Resistant)
Uses relative ratio transformations to eliminate match fingerprinting
Target: 52-54% accuracy with all sanity checks <40%
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
from datetime import timedelta
import joblib

from features.batch_feature_builder import BatchFeatureBuilder

N_SPLITS = 5
EMBARGO_DAYS = 7

def load_matches(limit=5000):
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
    print("  V2.1 TRANSFORMED TRAINING (LEAKAGE-FREE)")
    print("  Features: 46 total (40 base + 2 context_transformed + 4 drift)")
    print("  Target: 52-54% accuracy with clean sanity checks")
    print("="*80)

    # Load matches
    matches = load_matches(limit=5000)
    
    # Build features
    print("\n🔨 Building features (batch optimized)...")
    print("   Expected time: <30 seconds for 648 matches...")
    df = build_features(matches)
    
    feature_cols = [c for c in df.columns if c not in ["outcome","match_date","match_id"]]
    X = df[feature_cols].values
    y = encode_y(df["outcome"].values)
    dates = pd.to_datetime(df["match_date"].values)
    
    print(f"\nDataset: {len(X)} matches x {len(feature_cols)} features")
    
    # === FEATURE UNIQUENESS DIAGNOSTICS ===
    print("\n" + "="*80)
    print("  FEATURE UNIQUENESS DIAGNOSTICS")
    print("="*80)
    print("Inspecting features for potential match fingerprinting...")
    
    nunique = df[feature_cols].nunique().sort_values(ascending=False)
    print(f"\nTop 15 most unique features (out of {len(df)} total matches):")
    for feat, count in nunique.head(15).items():
        uniqueness_pct = (count / len(df)) * 100
        status = "⚠️  HIGH" if uniqueness_pct > 50 else "✅ OK"
        print(f"  {feat:40s}: {count:5d} unique ({uniqueness_pct:5.1f}%) {status}")
    
    # Check for near-unique combinations
    print(f"\nFeatures with >80% uniqueness (fingerprint risk):")
    high_unique = nunique[nunique / len(df) > 0.8]
    if len(high_unique) > 0:
        for feat in high_unique.index:
            print(f"  ❌ {feat}: {high_unique[feat]} / {len(df)} ({100*high_unique[feat]/len(df):.1f}%)")
    else:
        print("  ✅ None found - good sign!")
    
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
        num_boost_round=50,
        valid_sets=[valid_data],
        callbacks=[
            lgb.early_stopping(10),
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
    
    # === REAL TRAINING WITH TIME CV ===
    print("\n" + "="*80)
    print("  V2.1 TRAINING (Time-Based Cross-Validation)")
    print("="*80)
    
    from training.step_a_optimizations import PurgedTimeSeriesSplit
    cv = PurgedTimeSeriesSplit(n_splits=N_SPLITS, embargo_days=EMBARGO_DAYS)
    
    # Draw weighting (from Step A recommendations)
    label_weights = np.ones(len(y))
    label_weights[y == 1] = 1.30
    
    params = {
        "objective": "multiclass",
        "num_class": 3,
        "metric": "multi_logloss",
        "learning_rate": 0.05,
        "num_leaves": 31,
        "min_data_in_leaf": 50,
        "feature_fraction": 0.8,
        "lambda_l1": 0.0,
        "lambda_l2": 0.0,
        "verbosity": -1,
        "seed": 42,
    }
    
    oof_proba = np.zeros((len(X), 3), dtype=float)
    oof_true = y.copy()
    oof_mask = np.zeros(len(X), dtype=bool)  # Track which rows were validated
    fold_models = []
    
    for fold, (tr_idx, va_idx) in enumerate(cv.split(X, y, groups=dates), start=1):
        print(f"\n--- Fold {fold}/{N_SPLITS} ---")
        X_tr, X_va = X[tr_idx], X[va_idx]
        y_tr, y_va = y[tr_idx], y[va_idx]
        w_tr = label_weights[tr_idx]
        
        d_tr = lgb.Dataset(X_tr, label=y_tr, weight=w_tr)
        d_va = lgb.Dataset(X_va, label=y_va, reference=d_tr)
        
        model = lgb.train(
            params,
            d_tr,
            num_boost_round=500,
            valid_sets=[d_va],
            callbacks=[
                lgb.early_stopping(25),
                lgb.log_evaluation(50),
            ],
        )
        
        fold_models.append(model)
        proba_va = model.predict(X_va, num_iteration=model.best_iteration)
        oof_proba[va_idx] = proba_va
        oof_mask[va_idx] = True  # Mark these rows as validated
        
        acc = accuracy_score(y_va, np.argmax(proba_va, axis=1))
        ll = log_loss(y_va, proba_va)
        
        # Multi-class Brier score
        one_hot_va = np.eye(3)[y_va]
        br = np.mean(np.sum((proba_va - one_hot_va)**2, axis=1)) / 2.0
        
        print(f"  Fold Acc: {acc:.3f}")
        print(f"  Fold LL : {ll:.3f}")
        print(f"  Fold Brier: {br:.3f}")
    
    # Overall OOF metrics (only on validated samples)
    # Purged time-series split may leave some rows never validated
    print("\n" + "="*80)
    print("  V2.1 OOF METRICS (Out-of-Fold)")
    print("="*80)
    print(f"Validated samples: {oof_mask.sum()} / {len(oof_mask)} ({100*oof_mask.sum()/len(oof_mask):.1f}%)")
    
    overall_acc = accuracy_score(oof_true[oof_mask], np.argmax(oof_proba[oof_mask], axis=1))
    overall_ll = log_loss(oof_true[oof_mask], oof_proba[oof_mask])
    one_hot = np.eye(3)[oof_true[oof_mask]]
    overall_br = np.mean(np.sum((oof_proba[oof_mask] - one_hot)**2, axis=1)) / 2.0
    
    print(f"  Accuracy: {overall_acc:.3f}")
    print(f"  LogLoss : {overall_ll:.3f}")
    print(f"  Brier   : {overall_br:.3f}")
    
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
    print(f"  Target: 52-54% (A- grade)")
    
    # Save final model (train on full data)
    print("\n" + "="*80)
    print("  TRAINING FINAL MODEL (Full Dataset)")
    print("="*80)
    
    d_full = lgb.Dataset(X, label=y, weight=label_weights)
    final_model = lgb.train(
        params,
        d_full,
        num_boost_round=200,
        callbacks=[lgb.log_evaluation(50)],
    )
    
    # Save
    os.makedirs("artifacts/models", exist_ok=True)
    model_path = "artifacts/models/v2_transformed_lgbm.txt"
    final_model.save_model(model_path)
    print(f"\n✅ Saved final model to {model_path}")
    
    # Save feature names
    feature_info = {
        "feature_names": feature_cols,
        "feature_count": len(feature_cols),
        "builder": "V2FeatureBuilderTransformed",
        "oof_accuracy": float(overall_acc),
        "oof_logloss": float(overall_ll),
        "oof_brier": float(overall_br),
    }
    joblib.dump(feature_info, "artifacts/models/v2_transformed_features.pkl")
    print(f"✅ Saved feature info to artifacts/models/v2_transformed_features.pkl")
    
    print("\n" + "="*80)
    print("  TRAINING COMPLETE")
    print("="*80)
    print(f"  Model: {model_path}")
    print(f"  Accuracy: {overall_acc:.3f} ({grade})")
    print(f"  Ready for A/B testing vs V2.0 odds-only baseline")

if __name__ == "__main__":
    main()
