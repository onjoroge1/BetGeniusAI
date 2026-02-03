"""
V0 Form-Only Model Training

Trains a LightGBM model using only form features (ELO, recent results, H2H).
No odds data required - can train on ALL historical matches.

Model outputs: H/D/A probabilities for match result prediction.
"""

import os
import json
import logging
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Dict, Tuple
import joblib

from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import accuracy_score, log_loss
from sklearn.preprocessing import LabelEncoder

import lightgbm as lgb

from features.v0_form_feature_builder import V0FormFeatureBuilder, FEATURE_NAMES

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MODEL_DIR = "models/saved"
MODEL_NAME = "v0_form_model"


def load_training_data(limit: int = None) -> pd.DataFrame:
    """Load training data from database."""
    builder = V0FormFeatureBuilder()
    dataset = builder.build_training_dataset(limit=limit)
    
    if not dataset:
        raise ValueError("No training data available")
    
    df = pd.DataFrame(dataset)
    logger.info(f"Loaded {len(df)} training samples")
    
    return df


def prepare_features(df: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray, list]:
    """Prepare feature matrix and labels."""
    feature_cols = [c for c in FEATURE_NAMES if c in df.columns]
    
    X = df[feature_cols].values
    
    le = LabelEncoder()
    le.classes_ = np.array(['A', 'D', 'H'])
    y = le.transform(df['outcome'].values)
    
    return X, y, feature_cols


def train_model(X: np.ndarray, y: np.ndarray, feature_names: list) -> Tuple[lgb.Booster, Dict]:
    """Train LightGBM model with time-series cross-validation."""
    
    params = {
        'objective': 'multiclass',
        'num_class': 3,
        'metric': 'multi_logloss',
        'boosting_type': 'gbdt',
        'num_leaves': 31,
        'learning_rate': 0.05,
        'feature_fraction': 0.8,
        'bagging_fraction': 0.8,
        'bagging_freq': 5,
        'verbose': -1,
        'seed': 42
    }
    
    tscv = TimeSeriesSplit(n_splits=5)
    cv_scores = []
    cv_accuracies = []
    
    for fold, (train_idx, val_idx) in enumerate(tscv.split(X)):
        X_train, X_val = X[train_idx], X[val_idx]
        y_train, y_val = y[train_idx], y[val_idx]
        
        train_data = lgb.Dataset(X_train, label=y_train, feature_name=feature_names)
        val_data = lgb.Dataset(X_val, label=y_val, feature_name=feature_names, reference=train_data)
        
        model = lgb.train(
            params,
            train_data,
            num_boost_round=200,
            valid_sets=[val_data],
            callbacks=[lgb.early_stopping(stopping_rounds=20, verbose=False)]
        )
        
        val_probs = model.predict(X_val)
        val_preds = np.argmax(val_probs, axis=1)
        
        logloss = log_loss(y_val, val_probs, labels=[0, 1, 2])
        accuracy = accuracy_score(y_val, val_preds)
        
        cv_scores.append(logloss)
        cv_accuracies.append(accuracy)
        logger.info(f"Fold {fold+1}: LogLoss={logloss:.4f}, Accuracy={accuracy:.4f}")
    
    logger.info(f"CV Mean LogLoss: {np.mean(cv_scores):.4f} (+/- {np.std(cv_scores):.4f})")
    logger.info(f"CV Mean Accuracy: {np.mean(cv_accuracies):.4f} (+/- {np.std(cv_accuracies):.4f})")
    
    full_train_data = lgb.Dataset(X, label=y, feature_name=feature_names)
    final_model = lgb.train(
        params,
        full_train_data,
        num_boost_round=200
    )
    
    metrics = {
        'cv_logloss_mean': float(np.mean(cv_scores)),
        'cv_logloss_std': float(np.std(cv_scores)),
        'cv_accuracy_mean': float(np.mean(cv_accuracies)),
        'cv_accuracy_std': float(np.std(cv_accuracies)),
        'n_samples': len(X),
        'n_features': len(feature_names),
        'feature_names': feature_names,
        'trained_at': datetime.utcnow().isoformat()
    }
    
    return final_model, metrics


def save_model(model: lgb.Booster, metrics: Dict):
    """Save model and metadata."""
    os.makedirs(MODEL_DIR, exist_ok=True)
    
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    model_path = f"{MODEL_DIR}/{MODEL_NAME}_{timestamp}.txt"
    meta_path = f"{MODEL_DIR}/{MODEL_NAME}_{timestamp}_meta.json"
    
    model.save_model(model_path)
    with open(meta_path, 'w') as f:
        json.dump(metrics, f, indent=2)
    
    latest_path = f"{MODEL_DIR}/{MODEL_NAME}_latest.txt"
    latest_meta_path = f"{MODEL_DIR}/{MODEL_NAME}_latest_meta.json"
    
    model.save_model(latest_path)
    with open(latest_meta_path, 'w') as f:
        json.dump(metrics, f, indent=2)
    
    logger.info(f"Model saved to {model_path}")
    logger.info(f"Latest model: {latest_path}")
    
    return model_path


def main():
    """Main training pipeline."""
    logger.info("=" * 60)
    logger.info("V0 Form-Only Model Training")
    logger.info("=" * 60)
    
    logger.info("Loading training data...")
    df = load_training_data()
    
    logger.info(f"Dataset shape: {df.shape}")
    logger.info(f"Outcome distribution: {df['outcome'].value_counts().to_dict()}")
    
    logger.info("Preparing features...")
    X, y, feature_names = prepare_features(df)
    logger.info(f"Feature matrix: {X.shape}, Features: {feature_names}")
    
    logger.info("Training model...")
    model, metrics = train_model(X, y, feature_names)
    
    logger.info("Saving model...")
    model_path = save_model(model, metrics)
    
    logger.info("=" * 60)
    logger.info("Training Complete!")
    logger.info(f"  Samples: {metrics['n_samples']}")
    logger.info(f"  Features: {metrics['n_features']}")
    logger.info(f"  CV Accuracy: {metrics['cv_accuracy_mean']:.4f}")
    logger.info(f"  CV LogLoss: {metrics['cv_logloss_mean']:.4f}")
    logger.info("=" * 60)
    
    return model, metrics


if __name__ == "__main__":
    main()
