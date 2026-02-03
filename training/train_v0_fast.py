"""
V0 Form-Only Model - Fast Training

Uses pre-computed ELO from team_elo table for fast training.
Builds minimal 4-feature set matching v0_form_predictor:
  elo_diff, elo_expected, home_advantage, elo_tier_diff
Uses LogisticRegression for simplicity and speed.
"""

import os
import json
import logging
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Dict
from sqlalchemy import create_engine, text

from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import accuracy_score, log_loss
from sklearn.preprocessing import StandardScaler

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
    """Build 4 feature columns matching v0_form_predictor."""
    df['elo_diff'] = df['home_elo'] - df['away_elo']
    
    df['elo_expected'] = 1.0 / (1.0 + 10 ** ((df['away_elo'] - df['home_elo'] - 100) / 400.0))
    
    df['home_advantage'] = 100.0
    
    def get_tier(elo):
        if elo >= 1700:
            return 3
        elif elo >= 1550:
            return 2
        elif elo >= 1400:
            return 1
        else:
            return 0
    
    df['home_tier'] = df['home_elo'].apply(get_tier)
    df['away_tier'] = df['away_elo'].apply(get_tier)
    df['elo_tier_diff'] = df['home_tier'] - df['away_tier']
    
    return df


def train_model(df: pd.DataFrame) -> tuple:
    """Train LogisticRegression model with 4 features matching v0_form_predictor."""
    feature_cols = ['elo_diff', 'elo_expected', 'home_advantage', 'elo_tier_diff']
    
    X = df[feature_cols].values
    
    outcome_map = {'H': 0, 'D': 1, 'A': 2}
    y = df['outcome'].map(outcome_map).values
    
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    
    tscv = TimeSeriesSplit(n_splits=5)
    cv_scores = []
    cv_accuracies = []
    
    for fold, (train_idx, val_idx) in enumerate(tscv.split(X_scaled)):
        X_train, X_val = X_scaled[train_idx], X_scaled[val_idx]
        y_train, y_val = y[train_idx], y[val_idx]
        
        model = LogisticRegression(
            multi_class='multinomial',
            solver='lbfgs',
            max_iter=500,
            random_state=42
        )
        model.fit(X_train, y_train)
        
        val_probs = model.predict_proba(X_val)
        val_preds = model.predict(X_val)
        
        logloss = log_loss(y_val, val_probs, labels=[0, 1, 2])
        accuracy = accuracy_score(y_val, val_preds)
        
        cv_scores.append(logloss)
        cv_accuracies.append(accuracy)
        logger.info(f"Fold {fold+1}: LogLoss={logloss:.4f}, Accuracy={accuracy:.4f}")
    
    logger.info(f"CV Mean LogLoss: {np.mean(cv_scores):.4f}")
    logger.info(f"CV Mean Accuracy: {np.mean(cv_accuracies):.4f}")
    
    final_model = LogisticRegression(
        multi_class='multinomial',
        solver='lbfgs',
        max_iter=500,
        random_state=42
    )
    final_model.fit(X_scaled, y)
    
    metrics = {
        'cv_logloss_mean': float(np.mean(cv_scores)),
        'cv_accuracy_mean': float(np.mean(cv_accuracies)),
        'n_samples': len(X),
        'n_features': len(feature_cols),
        'feature_names': feature_cols,
        'model_type': 'LogisticRegression',
        'classes': ['H', 'D', 'A'],
        'trained_at': datetime.utcnow().isoformat()
    }
    
    return final_model, scaler, metrics


def save_model(model, scaler, metrics: Dict):
    """Save model, scaler, and metadata."""
    import joblib
    os.makedirs(MODEL_DIR, exist_ok=True)
    
    model_path = f"{MODEL_DIR}/{MODEL_NAME}_latest.pkl"
    scaler_path = f"{MODEL_DIR}/{MODEL_NAME}_scaler.pkl"
    meta_path = f"{MODEL_DIR}/{MODEL_NAME}_latest_meta.json"
    
    joblib.dump(model, model_path)
    joblib.dump(scaler, scaler_path)
    with open(meta_path, 'w') as f:
        json.dump(metrics, f, indent=2)
    
    logger.info(f"Model saved to {model_path}")
    return model_path


def main():
    """Main training pipeline."""
    logger.info("=" * 60)
    logger.info("V0 Form-Only Model - Fast Training (LogisticRegression)")
    logger.info("=" * 60)
    
    df = load_fast_training_data()
    df = build_features(df)
    
    logger.info(f"Training samples: {len(df)}")
    logger.info(f"Outcome distribution: {df['outcome'].value_counts().to_dict()}")
    
    model, scaler, metrics = train_model(df)
    save_model(model, scaler, metrics)
    
    logger.info("=" * 60)
    logger.info("Training Complete!")
    logger.info(f"  Samples: {metrics['n_samples']}")
    logger.info(f"  CV Accuracy: {metrics['cv_accuracy_mean']:.4f}")
    logger.info(f"  CV LogLoss: {metrics['cv_logloss_mean']:.4f}")
    logger.info("=" * 60)
    
    return model, metrics


if __name__ == "__main__":
    main()
