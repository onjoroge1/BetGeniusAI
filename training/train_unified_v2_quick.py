#!/usr/bin/env python3
"""
Quick Unified V2 Training Script
Trains on a smaller subset for faster iteration and validation.
"""

import os
import sys
import logging
import numpy as np
import pandas as pd
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor
import joblib
import lightgbm as lgb
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import log_loss, accuracy_score

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from features.unified_v2_feature_builder import UnifiedV2FeatureBuilder

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get('DATABASE_URL')
MODELS_DIR = 'models/saved'

def get_training_matches(limit: int = 400):
    """Get matches for training (limit for quick training)."""
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    cur.execute("""
        SELECT 
            m.match_id, m.fixture_id, m.home_team_id, m.away_team_id, 
            m.home_team, m.away_team, m.league_id, m.match_date, m.outcome
        FROM training_matches m
        WHERE m.outcome IS NOT NULL
          AND m.match_date >= '2024-01-01'
        ORDER BY m.match_date DESC
        LIMIT %s
    """, (limit,))
    
    matches = cur.fetchall()
    conn.close()
    return matches

def build_dataset(matches, builder):
    """Build feature dataset from matches."""
    X_data = []
    y_data = []
    match_ids = []
    skipped = 0
    feature_names = None
    
    outcome_map = {'H': 0, 'D': 1, 'A': 2, 'Home': 0, 'Draw': 1, 'Away': 2}
    
    for i, m in enumerate(matches):
        try:
            outcome = outcome_map.get(m['outcome'])
            if outcome is None:
                skipped += 1
                continue
            features = builder.build_features(m['match_id'])
            if features and all(v is not None for v in features.values()):
                X_data.append(list(features.values()))
                y_data.append(outcome)
                match_ids.append(m['match_id'])
                if feature_names is None:
                    feature_names = list(features.keys())
            else:
                skipped += 1
        except Exception as e:
            skipped += 1
        
        if (i + 1) % 50 == 0:
            logger.info(f"  Progress: {i+1}/{len(matches)} matches ({len(X_data)} built, {skipped} skipped)")
    
    logger.info(f"  Final: {len(X_data)} samples built, {skipped} skipped")
    X = np.array(X_data)
    y = np.array(y_data)
    
    return X, y, feature_names or [], match_ids

def train_model(X, y, feature_names):
    """Train LightGBM model with time-series CV."""
    tscv = TimeSeriesSplit(n_splits=5)
    
    params = {
        'objective': 'multiclass',
        'num_class': 3,
        'metric': 'multi_logloss',
        'learning_rate': 0.05,
        'num_leaves': 31,
        'max_depth': 6,
        'min_child_samples': 20,
        'subsample': 0.8,
        'colsample_bytree': 0.8,
        'reg_alpha': 0.1,
        'reg_lambda': 0.1,
        'random_state': 42,
        'verbosity': -1
    }
    
    fold_scores = []
    fold_accuracies = []
    
    for fold, (train_idx, val_idx) in enumerate(tscv.split(X)):
        X_train, X_val = X[train_idx], X[val_idx]
        y_train, y_val = y[train_idx], y[val_idx]
        
        train_data = lgb.Dataset(X_train, label=y_train, feature_name=feature_names)
        val_data = lgb.Dataset(X_val, label=y_val, feature_name=feature_names, reference=train_data)
        
        model = lgb.train(
            params,
            train_data,
            num_boost_round=500,
            valid_sets=[val_data],
            callbacks=[lgb.early_stopping(50), lgb.log_evaluation(0)]
        )
        
        y_pred_proba = model.predict(X_val)
        logloss = log_loss(y_val, y_pred_proba)
        accuracy = accuracy_score(y_val, np.argmax(y_pred_proba, axis=1))
        
        fold_scores.append(logloss)
        fold_accuracies.append(accuracy)
        logger.info(f"Fold {fold+1}: LogLoss={logloss:.4f}, Accuracy={accuracy:.4f}")
    
    avg_logloss = np.mean(fold_scores)
    avg_accuracy = np.mean(fold_accuracies)
    
    logger.info(f"\n📊 CV RESULTS:")
    logger.info(f"  Average LogLoss: {avg_logloss:.4f}")
    logger.info(f"  Average Accuracy: {avg_accuracy:.4f} ({avg_accuracy*100:.1f}%)")
    
    # Train final model on all data
    logger.info("\nTraining final model on all data...")
    full_train = lgb.Dataset(X, label=y, feature_name=feature_names)
    final_model = lgb.train(params, full_train, num_boost_round=300)
    
    return final_model, avg_logloss, avg_accuracy

def main():
    logger.info("=" * 60)
    logger.info("UNIFIED V2 QUICK TRAINING - 61 FEATURES")
    logger.info("=" * 60)
    
    # Get training data (limited for quick training)
    matches = get_training_matches(limit=400)
    logger.info(f"Found {len(matches)} matches for training")
    
    # Initialize feature builder
    builder = UnifiedV2FeatureBuilder()
    logger.info(f"✅ UnifiedV2FeatureBuilder initialized (61 features)")
    
    # Build dataset
    logger.info(f"Building features for {len(matches)} matches...")
    X, y, feature_names, match_ids = build_dataset(matches, builder)
    logger.info(f"Built {len(X)} samples with {len(feature_names)} features")
    
    # Train model
    model, logloss, accuracy = train_model(X, y, feature_names)
    
    # Save model
    os.makedirs(MODELS_DIR, exist_ok=True)
    model_path = os.path.join(MODELS_DIR, 'unified_v2_model.pkl')
    joblib.dump({
        'model': model,
        'feature_names': feature_names,
        'logloss': logloss,
        'accuracy': accuracy,
        'trained_at': datetime.now().isoformat()
    }, model_path)
    logger.info(f"\n✅ Model saved to {model_path}")
    
    # Feature importance
    importance = model.feature_importance(importance_type='gain')
    importance_df = pd.DataFrame({
        'feature': feature_names,
        'importance': importance
    }).sort_values('importance', ascending=False)
    
    logger.info("\n📈 TOP 15 FEATURES:")
    for _, row in importance_df.head(15).iterrows():
        logger.info(f"  {row['feature']:40} {row['importance']:.2f}")
    
    logger.info("\n" + "=" * 60)
    logger.info(f"🎯 FINAL RESULTS: Accuracy={accuracy*100:.1f}% (target: 52-54%)")
    logger.info("=" * 60)

if __name__ == '__main__':
    main()
