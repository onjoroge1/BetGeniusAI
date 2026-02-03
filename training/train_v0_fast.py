"""
V0 Form-Only Model - Fast Training

Uses pre-computed ELO from team_elo table for fast training.
Builds minimal feature set: ELO difference + home advantage.
"""

import os
import json
import logging
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Dict
from sqlalchemy import create_engine, text

import lightgbm as lgb
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import accuracy_score, log_loss

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MODEL_DIR = "models/saved"
MODEL_NAME = "v0_form_model"


def load_fast_training_data() -> pd.DataFrame:
    """Load training data with ELO features directly from DB."""
    engine = create_engine(os.environ['DATABASE_URL'])
    
    query = """
        WITH match_data AS (
            SELECT 
                f.match_id,
                f.home_team_id,
                f.away_team_id,
                f.league_id,
                f.kickoff_at,
                m.outcome,
                COALESCE(he.elo_rating, 1500) as home_elo,
                COALESCE(ae.elo_rating, 1500) as away_elo,
                COALESCE(he.wins, 0) as home_wins,
                COALESCE(he.draws, 0) as home_draws,
                COALESCE(he.losses, 0) as home_losses,
                COALESCE(ae.wins, 0) as away_wins,
                COALESCE(ae.draws, 0) as away_draws,
                COALESCE(ae.losses, 0) as away_losses,
                COALESCE(he.matches_played, 0) as home_matches,
                COALESCE(ae.matches_played, 0) as away_matches
            FROM fixtures f
            JOIN matches m ON f.match_id = m.match_id
            LEFT JOIN team_elo he ON f.home_team_id = he.team_id
            LEFT JOIN team_elo ae ON f.away_team_id = ae.team_id
            WHERE f.status = 'finished'
            AND f.home_team_id IS NOT NULL
            AND f.away_team_id IS NOT NULL
            AND m.outcome IS NOT NULL
            ORDER BY f.kickoff_at ASC
        )
        SELECT * FROM match_data
    """
    
    df = pd.read_sql(query, engine)
    logger.info(f"Loaded {len(df)} training samples")
    return df


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """Build feature columns from raw data."""
    df['elo_diff'] = df['home_elo'] - df['away_elo']
    
    df['elo_expected'] = 1.0 / (1.0 + 10 ** ((df['away_elo'] - df['home_elo'] - 100) / 400.0))
    
    home_total = df['home_wins'] + df['home_draws'] + df['home_losses']
    away_total = df['away_wins'] + df['away_draws'] + df['away_losses']
    
    df['home_win_rate'] = np.where(home_total > 0, df['home_wins'] / home_total, 0.33)
    df['away_win_rate'] = np.where(away_total > 0, df['away_wins'] / away_total, 0.33)
    df['home_draw_rate'] = np.where(home_total > 0, df['home_draws'] / home_total, 0.33)
    df['away_draw_rate'] = np.where(away_total > 0, df['away_draws'] / away_total, 0.33)
    
    df['win_rate_diff'] = df['home_win_rate'] - df['away_win_rate']
    
    df['is_tier1'] = df['league_id'].isin([39, 140, 78, 135, 61]).astype(int)
    
    df['home_experience'] = np.log1p(df['home_matches'])
    df['away_experience'] = np.log1p(df['away_matches'])
    
    return df


def train_model(df: pd.DataFrame) -> tuple:
    """Train LightGBM model."""
    feature_cols = [
        'elo_diff', 'elo_expected', 
        'home_win_rate', 'away_win_rate',
        'home_draw_rate', 'away_draw_rate',
        'win_rate_diff',
        'is_tier1',
        'home_experience', 'away_experience'
    ]
    
    X = df[feature_cols].values
    
    outcome_map = {'H': 2, 'D': 1, 'A': 0}
    y = df['outcome'].map(outcome_map).values
    
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
        
        train_data = lgb.Dataset(X_train, label=y_train, feature_name=feature_cols)
        val_data = lgb.Dataset(X_val, label=y_val, feature_name=feature_cols, reference=train_data)
        
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
    
    logger.info(f"CV Mean LogLoss: {np.mean(cv_scores):.4f}")
    logger.info(f"CV Mean Accuracy: {np.mean(cv_accuracies):.4f}")
    
    full_train_data = lgb.Dataset(X, label=y, feature_name=feature_cols)
    final_model = lgb.train(params, full_train_data, num_boost_round=200)
    
    metrics = {
        'cv_logloss_mean': float(np.mean(cv_scores)),
        'cv_accuracy_mean': float(np.mean(cv_accuracies)),
        'n_samples': len(X),
        'n_features': len(feature_cols),
        'feature_names': feature_cols,
        'trained_at': datetime.utcnow().isoformat()
    }
    
    return final_model, metrics


def save_model(model, metrics: Dict):
    """Save model and metadata."""
    os.makedirs(MODEL_DIR, exist_ok=True)
    
    model_path = f"{MODEL_DIR}/{MODEL_NAME}_latest.txt"
    meta_path = f"{MODEL_DIR}/{MODEL_NAME}_latest_meta.json"
    
    model.save_model(model_path)
    with open(meta_path, 'w') as f:
        json.dump(metrics, f, indent=2)
    
    logger.info(f"Model saved to {model_path}")
    return model_path


def main():
    """Main training pipeline."""
    logger.info("=" * 60)
    logger.info("V0 Form-Only Model - Fast Training")
    logger.info("=" * 60)
    
    df = load_fast_training_data()
    df = build_features(df)
    
    logger.info(f"Training samples: {len(df)}")
    logger.info(f"Outcome distribution: {df['outcome'].value_counts().to_dict()}")
    
    model, metrics = train_model(df)
    save_model(model, metrics)
    
    logger.info("=" * 60)
    logger.info("Training Complete!")
    logger.info(f"  Samples: {metrics['n_samples']}")
    logger.info(f"  CV Accuracy: {metrics['cv_accuracy_mean']:.4f}")
    logger.info(f"  CV LogLoss: {metrics['cv_logloss_mean']:.4f}")
    logger.info("=" * 60)
    
    return model, metrics


if __name__ == "__main__":
    main()
