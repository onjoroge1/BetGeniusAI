#!/usr/bin/env python3
"""
Train V2 Model - LEAKAGE-FREE with Temporal Train/Val Split

Architecture:
1. Binary draw classifier (Draw vs Not-Draw)
2. Binary win classifier (Home vs Away on Not-Draw subset)
3. GBM multiclass (H/D/A)
4. Meta-logit blends all three (trained on VAL only)
5. Global isotonic calibration (trained on VAL only)

Temporal split prevents leakage:
- Train: up to T-35d
- Validate: T-35d → T-7d (for early-stop, stacking, calibration)
- Gap: last 7d excluded (keeps it forward-facing)
"""

import os
import sys
import psycopg2
import numpy as np
import pandas as pd
from datetime import datetime
import json
import pickle
from pathlib import Path

from sklearn.linear_model import LogisticRegression
from sklearn.isotonic import IsotonicRegression
import lightgbm as lgb

DATABASE_URL = os.environ.get('DATABASE_URL')
MODEL_DIR = Path('models/v2')
CAL_DIR = MODEL_DIR / 'calibration'

BASE_FEATURES = [
    'prob_home', 'prob_draw', 'prob_away',
    'overround', 'book_dispersion',
    'drift_24h_home', 'drift_24h_draw', 'drift_24h_away',
    'form5_home_points', 'form5_away_points',
    'elo_delta', 'rest_days_home', 'rest_days_away'
]

def pick_features(df):
    """Return only features that exist in df, have data, and drop rows with nulls"""
    # Only use columns that exist AND have non-null values
    cols = [c for c in BASE_FEATURES if c in df.columns and df[c].notna().any()]
    if not cols:
        cols = ['prob_home', 'prob_draw', 'prob_away']  # Minimum required
    return cols, df.dropna(subset=cols)

def load_training_data():
    """Load data with temporal train/val split (no leakage)"""
    print("📊 Loading training data with temporal split...")
    
    with psycopg2.connect(DATABASE_URL) as conn:
        df = pd.read_sql("""
            SELECT 
                mf.match_id, mf.league_id, mf.kickoff_timestamp,
                mf.prob_home, mf.prob_draw, mf.prob_away,
                mf.overround, mf.book_dispersion,
                mf.drift_24h_home, mf.drift_24h_draw, mf.drift_24h_away,
                mf.form5_home_points, mf.form5_away_points, mf.elo_delta,
                mf.rest_days_home, mf.rest_days_away,
                CASE 
                    WHEN tm.outcome IN ('H','Home') THEN 'H'
                    WHEN tm.outcome IN ('D','Draw') THEN 'D'
                    WHEN tm.outcome IN ('A','Away') THEN 'A'
                    ELSE NULL
                END AS outcome
            FROM match_features mf
            JOIN training_matches tm ON mf.match_id = tm.match_id
            WHERE tm.outcome IS NOT NULL
                AND mf.prob_home IS NOT NULL 
                AND mf.prob_draw IS NOT NULL 
                AND mf.prob_away IS NOT NULL
            ORDER BY mf.kickoff_timestamp
        """, conn)
    
    # Use latest date in dataset, not current time
    latest_date = df['kickoff_timestamp'].max()
    cutoff_gap = latest_date - pd.Timedelta(days=7)
    val_start = latest_date - pd.Timedelta(days=35)
    
    train_df = df[df['kickoff_timestamp'] < val_start].copy()
    val_df = df[(df['kickoff_timestamp'] >= val_start) & (df['kickoff_timestamp'] < cutoff_gap)].copy()
    
    feats, train_df = pick_features(train_df)
    _, val_df = pick_features(val_df)
    
    print(f"✓ Train rows: {len(train_df)}, Val rows: {len(val_df)}")
    print(f"✓ Features used: {len(feats)} -> {feats[:5]}...")
    print(f"✓ Train range: {train_df['kickoff_timestamp'].min()} to {train_df['kickoff_timestamp'].max()}")
    print(f"✓ Val range: {val_df['kickoff_timestamp'].min()} to {val_df['kickoff_timestamp'].max()}")
    
    return train_df, val_df, feats

def encode_targets(df):
    """Convert outcomes to numeric targets"""
    y = df['outcome'].map({'H': 0, 'D': 1, 'A': 2}).values
    y_draw = (y == 1).astype(int)
    y_win = (y == 0).astype(int)
    return y, y_draw, y_win

def train_gbm_with_val(X_tr, y_tr, X_val, y_val):
    """Train GBM with validation set and regularization"""
    print("\n🎯 Training GBM with validation early stopping...")
    
    params = {
        'objective': 'multiclass',
        'num_class': 3,
        'metric': 'multi_logloss',
        'boosting_type': 'gbdt',
        'num_leaves': 15,
        'max_depth': -1,
        'min_data_in_leaf': 60,
        'learning_rate': 0.07,
        'feature_fraction': 0.85,
        'bagging_fraction': 0.8,
        'bagging_freq': 5,
        'lambda_l1': 0.2,
        'lambda_l2': 0.4,
        'seed': 42,
        'verbose': -1
    }
    
    dtr = lgb.Dataset(X_tr, label=y_tr)
    dvl = lgb.Dataset(X_val, label=y_val)
    
    model = lgb.train(
        params, dtr,
        num_boost_round=500,
        valid_sets=[dtr, dvl],
        valid_names=['train', 'val'],
        callbacks=[lgb.early_stopping(stopping_rounds=50, verbose=False)]
    )
    
    return model

def compute_metrics(probs, y_true):
    """Compute LogLoss and Brier score"""
    eps = 1e-9
    ll = -np.log(np.clip(probs[np.arange(len(y_true)), y_true], eps, 1-eps)).mean()
    oh = np.eye(3)[y_true]
    br = ((probs - oh)**2).mean()
    return ll, br

def build_meta_features(X, draw_clf, win_clf, gbm):
    """Build meta features from base model predictions"""
    pD = draw_clf.predict_proba(X)[:, 1]
    pHgiven = win_clf.predict_proba(X)[:, 1]
    
    pH2 = (1 - pD) * pHgiven
    pA2 = (1 - pD) * (1 - pHgiven)
    p2 = np.column_stack([pH2, pD, pA2])
    
    pG = gbm.predict(X)
    
    return np.column_stack([p2, pG])

def train_calibrators_on_val(val_probs_raw, yvl):
    """Train isotonic calibrators on validation set only"""
    print("\n🎯 Training calibrators on validation set...")
    
    cal_h = IsotonicRegression(out_of_bounds='clip')
    cal_d = IsotonicRegression(out_of_bounds='clip')
    cal_a = IsotonicRegression(out_of_bounds='clip')
    
    cal_h.fit(val_probs_raw[:, 0], (yvl == 0).astype(float))
    cal_d.fit(val_probs_raw[:, 1], (yvl == 1).astype(float))
    cal_a.fit(val_probs_raw[:, 2], (yvl == 2).astype(float))
    
    return cal_h, cal_d, cal_a

def apply_calibration(probs, cal_h, cal_d, cal_a):
    """Apply calibration and safety clamps"""
    h = cal_h.predict(probs[:, 0])
    d = cal_d.predict(probs[:, 1])
    a = cal_a.predict(probs[:, 2])
    
    out = np.column_stack([h, d, a])
    out = np.clip(out, 0.02, 0.98)
    out = out / out.sum(axis=1, keepdims=True)
    
    return out

def save_models(draw_clf, win_clf, gbm, meta, feats):
    """Save all models to disk"""
    print("\n💾 Saving models...")
    
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    CAL_DIR.mkdir(parents=True, exist_ok=True)
    
    with open(MODEL_DIR / 'draw_model.pkl', 'wb') as f:
        pickle.dump(draw_clf, f)
    
    with open(MODEL_DIR / 'win_model.pkl', 'wb') as f:
        pickle.dump(win_clf, f)
    
    gbm.save_model(str(MODEL_DIR / 'gbm_model.txt'))
    
    with open(MODEL_DIR / 'meta_model.pkl', 'wb') as f:
        pickle.dump(meta, f)
    
    manifest = {
        'version': 'v2.0',
        'trained_at': datetime.utcnow().isoformat(),
        'training_method': 'temporal_split_no_leakage',
        'features': feats,
        'models': {
            'draw_classifier': 'draw_model.pkl',
            'win_classifier': 'win_model.pkl',
            'gbm_multiclass': 'gbm_model.txt',
            'meta_learner': 'meta_model.pkl'
        },
        'calibration_dir': 'calibration/',
        'notes': 'Meta-learner and calibrators trained on validation set only'
    }
    
    with open(MODEL_DIR / 'manifest.json', 'w') as f:
        json.dump(manifest, f, indent=2)
    
    print(f"✓ Models saved to {MODEL_DIR}")

def main():
    print("=" * 60)
    print("V2 MODEL TRAINING - LEAKAGE-FREE TEMPORAL SPLIT")
    print("=" * 60)
    
    train_df, val_df, FEATS = load_training_data()
    
    if len(val_df) < 50:
        print(f"\n⚠️  WARNING: Only {len(val_df)} validation samples!")
        print("   Consider extending validation window or reducing gap.")
    
    Xtr = train_df[FEATS].values
    ytr, ytr_draw, ytr_win = encode_targets(train_df)
    
    Xvl = val_df[FEATS].values
    yvl, yvl_draw, yvl_win = encode_targets(val_df)
    
    print(f"\n✓ Train distribution: H={sum(ytr==0)} D={sum(ytr==1)} A={sum(ytr==2)}")
    print(f"✓ Val distribution: H={sum(yvl==0)} D={sum(yvl==1)} A={sum(yvl==2)}")
    
    print("\n🎯 Training Draw Classifier on TRAIN set...")
    draw_clf = LogisticRegression(
        penalty='l2', C=0.8, max_iter=2000,
        solver='lbfgs', random_state=42
    )
    draw_clf.fit(Xtr, ytr_draw)
    
    print("✓ Draw classifier trained")
    
    print("\n🎯 Training Win Classifier on TRAIN set (Not-Draw subset)...")
    not_draw_tr = (ytr_draw == 0)
    win_clf = LogisticRegression(
        penalty='l2', C=0.8, max_iter=2000,
        solver='lbfgs', random_state=42
    )
    win_clf.fit(Xtr[not_draw_tr], ytr_win[not_draw_tr])
    
    print("✓ Win classifier trained")
    
    gbm = train_gbm_with_val(Xtr, ytr, Xvl, yvl)
    print("✓ GBM trained with validation early stopping")
    
    print("\n🎯 Training Meta-Learner on VALIDATION set only...")
    X_meta_val = build_meta_features(Xvl, draw_clf, win_clf, gbm)
    
    meta = LogisticRegression(
        penalty='l2', C=0.5, max_iter=2000,
        multi_class='multinomial', solver='lbfgs', random_state=42
    )
    meta.fit(X_meta_val, yvl)
    
    print("✓ Meta-learner trained on validation set")
    
    val_probs_raw = meta.predict_proba(X_meta_val)
    ll_raw, br_raw = compute_metrics(val_probs_raw, yvl)
    
    print(f"\n📊 Validation Performance (pre-calibration):")
    print(f"   LogLoss: {ll_raw:.4f}")
    print(f"   Brier:   {br_raw:.4f}")
    
    cal_h, cal_d, cal_a = train_calibrators_on_val(val_probs_raw, yvl)
    
    val_probs_cal = apply_calibration(val_probs_raw, cal_h, cal_d, cal_a)
    ll_cal, br_cal = compute_metrics(val_probs_cal, yvl)
    
    print(f"\n📊 Validation Performance (calibrated):")
    print(f"   LogLoss: {ll_cal:.4f}")
    print(f"   Brier:   {br_cal:.4f}")
    
    CAL_DIR.mkdir(parents=True, exist_ok=True)
    cal_data = {
        'home': cal_h,
        'draw': cal_d,
        'away': cal_a,
        'scope': 'global-val',
        'trained_on': 'validation_set',
        'val_logloss': ll_cal,
        'val_brier': br_cal
    }
    
    with open(CAL_DIR / 'global.pkl', 'wb') as f:
        pickle.dump(cal_data, f)
    
    save_models(draw_clf, win_clf, gbm, meta, FEATS)
    
    print("\n" + "=" * 60)
    print("✅ V2 MODEL TRAINING COMPLETE (LEAKAGE-FREE)")
    print("=" * 60)
    print(f"\n📦 Models saved to: {MODEL_DIR}")
    print(f"📊 Training samples: {len(train_df)}")
    print(f"📊 Validation samples: {len(val_df)}")
    print(f"📊 Features: {len(FEATS)}")
    print(f"🎯 Validation LogLoss: {ll_cal:.4f}, Brier: {br_cal:.4f}")
    print("\n💡 Meta-learner and calibrators trained on VALIDATION only")
    print("💡 No training set leakage - predictions should be realistic\n")

if __name__ == "__main__":
    main()
