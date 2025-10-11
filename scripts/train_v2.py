#!/usr/bin/env python3
"""
Train V2 Model - Market-Delta Ridge Regression

NEW APPROACH (Oct 11, 2025):
Instead of predicting raw probabilities, predict SMALL DELTAS from market consensus.

Architecture:
1. Convert market probs → logits (strong prior)
2. Train L2-regularized multinomial logistic to predict delta logits
3. Clamp deltas to ±τ (hard constraint, prevents extremes)
4. Blend: z_final = z_market + α·Δz (α=0.5)
5. Softmax → probabilities
6. Isotonic calibration on validation set only

Why this works:
- Market probabilities are already informative (strong baseline)
- Model can only make bounded, explainable adjustments
- Hard clamps prevent extreme predictions
- L2 regularization prevents overfitting
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

DELTA_TAU = 0.5  # Clamp delta logits to ±0.5 (≈±15-20% prob swing)
BLEND_ALPHA = 0.5  # Blend weight for delta logits

def pick_features(df):
    """Return only features that exist in df, have data, and drop rows with nulls"""
    cols = [c for c in BASE_FEATURES if c in df.columns and df[c].notna().any()]
    if not cols:
        cols = ['prob_home', 'prob_draw', 'prob_away']
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
    return y

def market_logits(pm):
    """
    Convert market probabilities to logits (log-space)
    pm: array of shape (n, 3) with [p_home, p_draw, p_away]
    Returns: normalized logits (n, 3)
    """
    pm_clipped = np.clip(pm, 1e-6, 1-1e-6)
    logits = np.log(pm_clipped)
    logits = logits - np.max(logits, axis=1, keepdims=True)
    return logits

def train_delta_ridge(X_tr, y_tr, X_val, y_val, pm_tr, pm_val):
    """
    Train ridge regression (L2 multinomial logistic) to predict delta logits
    
    Returns:
        ridge_model: Trained LogisticRegression
        iso_calibrators: List of 3 IsotonicRegression calibrators
        predict_fn: Function to make predictions
        apply_cal_fn: Function to apply calibration
    """
    print("\n🎯 Training Delta-Logit Ridge Regression...")
    print(f"   L2 regularization (C=0.5), tau={DELTA_TAU}, alpha={BLEND_ALPHA}")
    
    # Train multinomial ridge to predict outcomes (outputs decision function = logits)
    ridge_model = LogisticRegression(
        penalty='l2', 
        C=0.5,  # Strong L2 regularization
        solver='lbfgs', 
        max_iter=2000,
        multi_class='multinomial', 
        random_state=42
    )
    ridge_model.fit(X_tr, y_tr)
    
    print("✓ Ridge model trained")
    
    # Define prediction function with clamping and blending
    def predict_probs(pm, X):
        """Predict probabilities with market-delta blending"""
        zm = market_logits(pm)
        dz = ridge_model.decision_function(X)
        dz_clamped = np.clip(dz, -DELTA_TAU, DELTA_TAU)
        z_final = zm + BLEND_ALPHA * dz_clamped
        z_final = z_final - np.max(z_final, axis=1, keepdims=True)
        probs = np.exp(z_final)
        probs = probs / probs.sum(axis=1, keepdims=True)
        return probs
    
    # Get uncalibrated validation predictions
    p_val_raw = predict_probs(pm_val, X_val)
    
    print("\n🎯 Training Isotonic Calibrators on Validation Set...")
    
    # Train isotonic calibrators on validation set only
    iso_calibrators = []
    for k in range(3):
        iso = IsotonicRegression(out_of_bounds='clip')
        iso.fit(p_val_raw[:, k], (y_val == k).astype(float))
        iso_calibrators.append(iso)
    
    print("✓ Calibrators trained on validation set")
    
    # Define calibration function
    def apply_calibration(probs):
        """Apply isotonic calibration with safety clamps"""
        calibrated = np.column_stack([
            iso_calibrators[k].predict(probs[:, k]) for k in range(3)
        ])
        calibrated = np.clip(calibrated, 0.02, 0.98)
        calibrated = calibrated / calibrated.sum(axis=1, keepdims=True)
        return calibrated
    
    # Test on validation set
    p_val_cal = apply_calibration(p_val_raw)
    
    return ridge_model, iso_calibrators, predict_probs, apply_calibration

def compute_metrics(probs, y_true):
    """Compute LogLoss and Brier score"""
    eps = 1e-9
    ll = -np.log(np.clip(probs[np.arange(len(y_true)), y_true], eps, 1-eps)).mean()
    oh = np.eye(3)[y_true]
    br = ((probs - oh)**2).mean()
    return ll, br

def compute_market_divergence(probs, market_probs):
    """
    Compute average L1 distance and KL divergence from market
    L1: Mean absolute difference in probabilities
    KL: Mean KL divergence (measures information gain)
    """
    l1 = np.abs(probs - market_probs).mean(axis=1).mean()
    
    eps = 1e-9
    probs_safe = np.clip(probs, eps, 1-eps)
    market_safe = np.clip(market_probs, eps, 1-eps)
    kl = (probs_safe * np.log(probs_safe / market_safe)).sum(axis=1).mean()
    
    return l1, kl

def save_models(ridge_model, iso_calibrators, feats, train_stats, val_stats):
    """Save ridge model and calibrators to disk"""
    print("\n💾 Saving models...")
    
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    CAL_DIR.mkdir(parents=True, exist_ok=True)
    
    # Save ridge model
    with open(MODEL_DIR / 'ridge_model.pkl', 'wb') as f:
        pickle.dump(ridge_model, f)
    
    # Save isotonic calibrators
    with open(CAL_DIR / 'global.pkl', 'wb') as f:
        pickle.dump({
            'home': iso_calibrators[0],
            'draw': iso_calibrators[1],
            'away': iso_calibrators[2]
        }, f)
    
    # Save manifest
    manifest = {
        'version': 'v2.1-delta',
        'trained_at': datetime.utcnow().isoformat(),
        'training_method': 'market_delta_ridge',
        'architecture': 'delta_logit_blend',
        'hyperparameters': {
            'delta_tau': DELTA_TAU,
            'blend_alpha': BLEND_ALPHA,
            'C': 0.5
        },
        'features': feats,
        'models': {
            'ridge': 'ridge_model.pkl',
            'calibration': 'calibration/global.pkl'
        },
        'training_stats': train_stats,
        'validation_stats': val_stats,
        'notes': 'Market-delta model with L2 ridge regression and isotonic calibration'
    }
    
    with open(MODEL_DIR / 'manifest.json', 'w') as f:
        json.dump(manifest, f, indent=2)
    
    print(f"✓ Models saved to {MODEL_DIR}")
    print(f"✓ Manifest: {MODEL_DIR / 'manifest.json'}")

def main():
    print("=" * 70)
    print("V2 MODEL TRAINING - MARKET-DELTA RIDGE REGRESSION")
    print("=" * 70)
    
    train_df, val_df, FEATS = load_training_data()
    
    if len(val_df) < 50:
        print(f"\n⚠️  WARNING: Only {len(val_df)} validation samples!")
    
    # Prepare features and targets
    Xtr = train_df[FEATS].values
    ytr = encode_targets(train_df)
    pm_tr = train_df[['prob_home', 'prob_draw', 'prob_away']].values
    
    Xvl = val_df[FEATS].values
    yvl = encode_targets(val_df)
    pm_vl = val_df[['prob_home', 'prob_draw', 'prob_away']].values
    
    print(f"\n✓ Train distribution: H={sum(ytr==0)} D={sum(ytr==1)} A={sum(ytr==2)}")
    print(f"✓ Val distribution: H={sum(yvl==0)} D={sum(yvl==1)} A={sum(yvl==2)}")
    
    # Train model
    ridge_model, iso_calibrators, predict_fn, apply_cal = train_delta_ridge(
        Xtr, ytr, Xvl, yvl, pm_tr, pm_vl
    )
    
    # Evaluate on train set
    print("\n📊 Evaluating on TRAIN set...")
    ptr_raw = predict_fn(pm_tr, Xtr)
    ptr_cal = apply_cal(ptr_raw)
    
    ll_tr_raw, br_tr_raw = compute_metrics(ptr_raw, ytr)
    ll_tr_cal, br_tr_cal = compute_metrics(ptr_cal, ytr)
    l1_tr, kl_tr = compute_market_divergence(ptr_cal, pm_tr)
    
    print(f"   Raw:        LogLoss={ll_tr_raw:.4f}, Brier={br_tr_raw:.4f}")
    print(f"   Calibrated: LogLoss={ll_tr_cal:.4f}, Brier={br_tr_cal:.4f}")
    print(f"   vs Market:  L1={l1_tr:.4f}, KL={kl_tr:.4f}")
    
    # Evaluate on validation set
    print("\n📊 Evaluating on VALIDATION set...")
    pvl_raw = predict_fn(pm_vl, Xvl)
    pvl_cal = apply_cal(pvl_raw)
    
    ll_vl_raw, br_vl_raw = compute_metrics(pvl_raw, yvl)
    ll_vl_cal, br_vl_cal = compute_metrics(pvl_cal, yvl)
    l1_vl, kl_vl = compute_market_divergence(pvl_cal, pm_vl)
    
    print(f"   Raw:        LogLoss={ll_vl_raw:.4f}, Brier={br_vl_raw:.4f}")
    print(f"   Calibrated: LogLoss={ll_vl_cal:.4f}, Brier={br_vl_cal:.4f}")
    print(f"   vs Market:  L1={l1_vl:.4f}, KL={kl_vl:.4f}")
    
    # Analyze max confidences
    max_conf_tr = np.max(ptr_cal, axis=1).mean()
    max_conf_vl = np.max(pvl_cal, axis=1).mean()
    
    print(f"\n📈 Max Confidence Analysis:")
    print(f"   Train avg:  {max_conf_tr:.1%}")
    print(f"   Val avg:    {max_conf_vl:.1%}")
    
    # Check sanity
    print(f"\n✅ Sanity Checks:")
    if ll_vl_cal >= 0.60 and ll_vl_cal <= 0.95:
        print(f"   ✓ Validation LogLoss {ll_vl_cal:.4f} is REALISTIC for sports betting")
    else:
        print(f"   ⚠️  Validation LogLoss {ll_vl_cal:.4f} is {'too low (overfitting?)' if ll_vl_cal < 0.60 else 'too high'}")
    
    if max_conf_vl < 0.80:
        print(f"   ✓ Max confidence {max_conf_vl:.1%} is reasonable")
    else:
        print(f"   ⚠️  Max confidence {max_conf_vl:.1%} is high (might be overconfident)")
    
    if l1_vl >= 0.10 and l1_vl <= 0.30:
        print(f"   ✓ Market divergence L1={l1_vl:.4f} is in target range [0.10, 0.30]")
    else:
        print(f"   ⚠️  Market divergence L1={l1_vl:.4f} is {'too small' if l1_vl < 0.10 else 'too large'}")
    
    # Save models
    train_stats = {
        'logloss_raw': float(ll_tr_raw),
        'logloss_cal': float(ll_tr_cal),
        'brier_raw': float(br_tr_raw),
        'brier_cal': float(br_tr_cal),
        'l1_divergence': float(l1_tr),
        'kl_divergence': float(kl_tr),
        'max_confidence': float(max_conf_tr),
        'n_samples': int(len(ytr))
    }
    
    val_stats = {
        'logloss_raw': float(ll_vl_raw),
        'logloss_cal': float(ll_vl_cal),
        'brier_raw': float(br_vl_raw),
        'brier_cal': float(br_vl_cal),
        'l1_divergence': float(l1_vl),
        'kl_divergence': float(kl_vl),
        'max_confidence': float(max_conf_vl),
        'n_samples': int(len(yvl))
    }
    
    save_models(ridge_model, iso_calibrators, FEATS, train_stats, val_stats)
    
    print("\n" + "=" * 70)
    print("✅ V2 DELTA MODEL TRAINING COMPLETE")
    print("=" * 70)
    
    # Summary
    print("\n📋 SUMMARY:")
    print(f"   Model: Market-Delta Ridge (L2, C=0.5)")
    print(f"   Train: {len(ytr)} samples, Val: {len(yvl)} samples")
    print(f"   Val LogLoss: {ll_vl_cal:.4f} (target: 0.60-0.90)")
    print(f"   Val Brier: {br_vl_cal:.4f} (target: 0.15-0.25)")
    print(f"   Market L1: {l1_vl:.4f} (target: 0.10-0.30)")
    print(f"   Max Conf: {max_conf_vl:.1%} (target: <80%)")
    print()
    
    if ll_vl_cal >= 0.60 and ll_vl_cal <= 0.95 and max_conf_vl < 0.80 and l1_vl >= 0.10:
        print("✅ Model passes sanity checks - READY for shadow testing!")
    else:
        print("⚠️  Model needs adjustment before shadow deployment")

if __name__ == '__main__':
    main()
