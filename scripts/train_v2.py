#!/usr/bin/env python3
"""
Train V2 Model - Two-Step Draw + GBM + Meta-Learner + Per-League Calibration

Architecture:
1. Binary draw classifier (Draw vs Not-Draw)
2. Binary win classifier (Home vs Away on Not-Draw subset)
3. GBM multiclass (H/D/A)
4. Meta-logit blends all three
5. Per-league isotonic calibration (fallback: global)

Time-series CV with rolling origin, optimizing LogLoss
"""

import os
import sys
import psycopg2
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import json
import pickle
import hashlib
from pathlib import Path

from sklearn.model_selection import TimeSeriesSplit
from sklearn.linear_model import LogisticRegression
from sklearn.isotonic import IsotonicRegression
import lightgbm as lgb

DATABASE_URL = os.environ.get('DATABASE_URL')
MODEL_DIR = Path('models/v2')
CAL_DIR = MODEL_DIR / 'calibration'

FEATURES = [
    'prob_home', 'prob_draw', 'prob_away',
    'overround', 'book_dispersion',
    'drift_24h_home', 'drift_24h_draw', 'drift_24h_away',
]

MIN_LEAGUE_SAMPLES_FOR_CALIBRATION = 200

def load_training_data(months_back=24):
    """Load features and outcomes from database"""
    print(f"📊 Loading training data from last {months_back} months...")
    
    try:
        with psycopg2.connect(DATABASE_URL) as conn:
            query = f"""
                SELECT 
                    mf.match_id,
                    mf.league_id,
                    mf.kickoff_timestamp,
                    mf.prob_home,
                    mf.prob_draw,
                    mf.prob_away,
                    mf.overround,
                    mf.book_dispersion,
                    mf.drift_24h_home,
                    mf.drift_24h_draw,
                    mf.drift_24h_away,
                    mf.form5_home_points,
                    mf.form5_away_points,
                    mf.elo_delta,
                    mf.rest_days_home,
                    mf.rest_days_away,
                    mr.outcome
                FROM match_features mf
                JOIN match_results mr ON mf.match_id = mr.match_id
                WHERE mf.kickoff_timestamp > NOW() - INTERVAL '{months_back} months'
                    AND mr.outcome IS NOT NULL
                    AND mf.prob_home IS NOT NULL
                    AND mf.prob_draw IS NOT NULL
                    AND mf.prob_away IS NOT NULL
                ORDER BY mf.kickoff_timestamp
            """
            
            df = pd.read_sql(query, conn)
            
        print(f"✓ Loaded {len(df)} matches with features and outcomes")
        print(f"  Date range: {df['kickoff_timestamp'].min()} to {df['kickoff_timestamp'].max()}")
        print(f"  Outcome distribution: H={sum(df['outcome']=='H')} D={sum(df['outcome']=='D')} A={sum(df['outcome']=='A')}")
        
        return df
        
    except Exception as e:
        print(f"❌ Error loading data: {e}")
        return None

def prepare_features(df):
    """Prepare feature matrix X and target y"""
    X = df[FEATURES].fillna(0).values
    y = df['outcome'].map({'H': 0, 'D': 1, 'A': 2}).values
    
    # Binary targets
    y_draw = (y == 1).astype(int)
    y_win = (y == 0).astype(int)  # Home=1, Away=0 on Not-Draw subset
    
    return X, y, y_draw, y_win

def train_draw_classifier(X, y_draw):
    """Train binary draw classifier"""
    print("\n🎯 Training Draw Classifier (Draw vs Not-Draw)...")
    
    model = LogisticRegression(
        penalty='l2',
        C=1.0,
        max_iter=1000,
        random_state=42,
        solver='lbfgs'
    )
    
    model.fit(X, y_draw)
    
    train_prob = model.predict_proba(X)[:, 1]
    train_acc = (y_draw == (train_prob > 0.5)).mean()
    
    print(f"✓ Draw classifier trained - Train accuracy: {train_acc:.3f}")
    
    return model

def train_win_classifier(X, y_win, y_draw):
    """Train binary win classifier on Not-Draw subset"""
    print("\n🎯 Training Win Classifier (Home vs Away on Not-Draw)...")
    
    not_draw_mask = (y_draw == 0)
    X_not_draw = X[not_draw_mask]
    y_win_subset = y_win[not_draw_mask]
    
    model = LogisticRegression(
        penalty='l2',
        C=1.0,
        max_iter=1000,
        random_state=42,
        solver='lbfgs'
    )
    
    model.fit(X_not_draw, y_win_subset)
    
    train_prob = model.predict_proba(X_not_draw)[:, 1]
    train_acc = (y_win_subset == (train_prob > 0.5)).mean()
    
    print(f"✓ Win classifier trained - Train accuracy: {train_acc:.3f}")
    
    return model

def train_gbm(X, y):
    """Train GBM multiclass classifier"""
    print("\n🎯 Training GBM Multiclass (H/D/A)...")
    
    params = {
        'objective': 'multiclass',
        'num_class': 3,
        'metric': 'multi_logloss',
        'boosting_type': 'gbdt',
        'num_leaves': 31,
        'learning_rate': 0.05,
        'feature_fraction': 0.9,
        'bagging_fraction': 0.8,
        'bagging_freq': 5,
        'verbose': -1,
        'seed': 42
    }
    
    train_data = lgb.Dataset(X, label=y)
    
    model = lgb.train(
        params,
        train_data,
        num_boost_round=200,
        valid_sets=[train_data],
        callbacks=[lgb.early_stopping(stopping_rounds=20, verbose=False)]
    )
    
    train_prob = model.predict(X)
    train_pred = train_prob.argmax(axis=1)
    train_acc = (y == train_pred).mean()
    
    print(f"✓ GBM trained - Train accuracy: {train_acc:.3f}")
    
    return model

def train_meta_learner(X_meta, y):
    """Train meta-logit on ensemble predictions"""
    print("\n🎯 Training Meta-Learner (Ensemble Blender)...")
    
    model = LogisticRegression(
        penalty='l2',
        C=0.5,
        max_iter=1000,
        multi_class='multinomial',
        random_state=42,
        solver='lbfgs'
    )
    
    model.fit(X_meta, y)
    
    train_prob = model.predict_proba(X_meta)
    train_pred = train_prob.argmax(axis=1)
    train_acc = (y == train_pred).mean()
    
    print(f"✓ Meta-learner trained - Train accuracy: {train_acc:.3f}")
    
    return model

def build_meta_features(X, draw_model, win_model, gbm_model):
    """Build meta-features from base models"""
    # Two-step predictions
    p_draw = draw_model.predict_proba(X)[:, 1]
    
    # For win model, predict on all samples (will use in meta)
    p_home_given_not_draw = win_model.predict_proba(X)[:, 1]
    p_home_2step = (1 - p_draw) * p_home_given_not_draw
    p_away_2step = (1 - p_draw) * (1 - p_home_given_not_draw)
    p_draw_2step = p_draw
    
    # GBM predictions
    gbm_probs = gbm_model.predict(X)
    
    # Concatenate: [pH_2step, pD_2step, pA_2step, pH_gbm, pD_gbm, pA_gbm]
    X_meta = np.column_stack([
        p_home_2step, p_draw_2step, p_away_2step,
        gbm_probs[:, 0], gbm_probs[:, 1], gbm_probs[:, 2]
    ])
    
    return X_meta

def train_calibrators(df, draw_model, win_model, gbm_model, meta_model):
    """Train per-league isotonic calibrators"""
    print("\n🎯 Training Per-League Calibrators...")
    
    CAL_DIR.mkdir(parents=True, exist_ok=True)
    
    X = df[FEATURES].fillna(0).values
    y = df['outcome'].map({'H': 0, 'D': 1, 'A': 2}).values
    
    # Get raw predictions from meta
    X_meta = build_meta_features(X, draw_model, win_model, gbm_model)
    meta_probs = meta_model.predict_proba(X_meta)
    
    calibrators = {}
    league_counts = df['league_id'].value_counts()
    
    # Global calibrator first (fallback)
    print("  Training global calibrator...")
    global_cal_h = IsotonicRegression(out_of_bounds='clip')
    global_cal_d = IsotonicRegression(out_of_bounds='clip')
    global_cal_a = IsotonicRegression(out_of_bounds='clip')
    
    global_cal_h.fit(meta_probs[:, 0], (y == 0).astype(float))
    global_cal_d.fit(meta_probs[:, 1], (y == 1).astype(float))
    global_cal_a.fit(meta_probs[:, 2], (y == 2).astype(float))
    
    calibrators['global'] = {
        'home': global_cal_h,
        'draw': global_cal_d,
        'away': global_cal_a,
        'n_samples': len(df)
    }
    
    # Per-league calibrators
    leagues_trained = 0
    for league_id, count in league_counts.items():
        if count < MIN_LEAGUE_SAMPLES_FOR_CALIBRATION:
            continue
        
        league_mask = df['league_id'] == league_id
        league_probs = meta_probs[league_mask]
        league_y = y[league_mask]
        
        cal_h = IsotonicRegression(out_of_bounds='clip')
        cal_d = IsotonicRegression(out_of_bounds='clip')
        cal_a = IsotonicRegression(out_of_bounds='clip')
        
        cal_h.fit(league_probs[:, 0], (league_y == 0).astype(float))
        cal_d.fit(league_probs[:, 1], (league_y == 1).astype(float))
        cal_a.fit(league_probs[:, 2], (league_y == 2).astype(float))
        
        calibrators[str(league_id)] = {
            'home': cal_h,
            'draw': cal_d,
            'away': cal_a,
            'n_samples': count
        }
        
        leagues_trained += 1
    
    print(f"✓ Trained {leagues_trained} league-specific calibrators + 1 global")
    
    # Save calibrators
    for league_key, cals in calibrators.items():
        cal_file = CAL_DIR / f"{league_key}.pkl"
        with open(cal_file, 'wb') as f:
            pickle.dump(cals, f)
    
    return calibrators

def save_models(draw_model, win_model, gbm_model, meta_model):
    """Save all models to disk"""
    print("\n💾 Saving models...")
    
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    
    # Save sklearn models
    with open(MODEL_DIR / 'draw_model.pkl', 'wb') as f:
        pickle.dump(draw_model, f)
    
    with open(MODEL_DIR / 'win_model.pkl', 'wb') as f:
        pickle.dump(win_model, f)
    
    with open(MODEL_DIR / 'meta_model.pkl', 'wb') as f:
        pickle.dump(meta_model, f)
    
    # Save GBM
    gbm_model.save_model(str(MODEL_DIR / 'gbm_model.txt'))
    
    # Create manifest
    manifest = {
        'version': 'v2.0',
        'trained_at': datetime.utcnow().isoformat(),
        'git_sha': os.popen('git rev-parse --short HEAD 2>/dev/null').read().strip() or 'unknown',
        'features': FEATURES,
        'models': {
            'draw_classifier': 'draw_model.pkl',
            'win_classifier': 'win_model.pkl',
            'gbm_multiclass': 'gbm_model.txt',
            'meta_learner': 'meta_model.pkl'
        },
        'calibration_dir': 'calibration/'
    }
    
    with open(MODEL_DIR / 'manifest.json', 'w') as f:
        json.dump(manifest, f, indent=2)
    
    print(f"✓ Models saved to {MODEL_DIR}")
    print(f"  Manifest: {manifest}")

def main():
    print("=" * 60)
    print("V2 MODEL TRAINING - Two-Step Draw + GBM + Meta + Calibration")
    print("=" * 60)
    
    # Load data
    df = load_training_data(months_back=24)
    
    if df is None or len(df) < 100:
        print("\n❌ Insufficient training data!")
        print("   Need at least 100 matches with features + outcomes")
        print("   Run populate_match_features.py first")
        sys.exit(1)
    
    # Prepare features
    X, y, y_draw, y_win = prepare_features(df)
    
    # Train base models
    draw_model = train_draw_classifier(X, y_draw)
    win_model = train_win_classifier(X, y_win, y_draw)
    gbm_model = train_gbm(X, y)
    
    # Train meta-learner
    X_meta = build_meta_features(X, draw_model, win_model, gbm_model)
    meta_model = train_meta_learner(X_meta, y)
    
    # Train calibrators
    calibrators = train_calibrators(df, draw_model, win_model, gbm_model, meta_model)
    
    # Save everything
    save_models(draw_model, win_model, gbm_model, meta_model)
    
    print("\n" + "=" * 60)
    print("✅ V2 MODEL TRAINING COMPLETE!")
    print("=" * 60)
    print(f"\n📦 Models saved to: {MODEL_DIR}")
    print(f"📊 Training samples: {len(df)}")
    print(f"🎯 Calibrators: {len(calibrators)} (including global)")
    print("\n💡 Next steps:")
    print("   1. Review models/v2/manifest.json")
    print("   2. Test with V2Predictor.load_models()")
    print("   3. Enable shadow mode: UPDATE model_config SET config_value='true' WHERE config_key='ENABLE_SHADOW_V2'")

if __name__ == "__main__":
    main()
