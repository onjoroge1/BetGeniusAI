"""
V2-NBA Model Training Script
Binary classification for NBA games (Home Win vs Away Win)
Uses LightGBM with market odds features
"""

import os
import sys
import pandas as pd
import numpy as np
import lightgbm as lgb
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import log_loss, accuracy_score, roc_auc_score
from sklearn.calibration import CalibratedClassifierCV
import joblib
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

CLASS_TO_IDX = {'H': 0, 'A': 1}
IDX_TO_CLASS = ['H', 'A']

NBA_FEATURES = [
    "home_prob", "away_prob",
    "home_odds", "away_odds", 
    "overround",
    "n_bookmakers",
    "home_spread", "total_line",
    "home_spread_odds", "away_spread_odds",
    "over_odds", "under_odds"
]

LGBM_PARAMS = {
    "objective": "binary",
    "metric": "binary_logloss",
    "boosting_type": "gbdt",
    "num_leaves": 31,
    "learning_rate": 0.05,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 5,
    "min_child_samples": 20,
    "n_estimators": 200,
    "verbose": -1,
    "random_state": 42
}


def load_training_data():
    """Load NBA training data from database"""
    from sqlalchemy import create_engine, text
    
    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        raise ValueError("DATABASE_URL not set")
    
    engine = create_engine(database_url)
    
    query = """
        WITH training_matches AS (
            SELECT 
                t.event_id,
                t.home_team,
                t.away_team,
                t.match_date,
                t.home_score,
                t.away_score,
                t.outcome,
                t.consensus_home_prob,
                t.consensus_away_prob
            FROM multisport_training t
            WHERE t.sport_key = 'basketball_nba'
            AND t.outcome IS NOT NULL
        ),
        odds_agg AS (
            SELECT 
                o.event_id,
                AVG(o.home_odds) as home_odds,
                AVG(o.away_odds) as away_odds,
                AVG(o.home_prob) as home_prob,
                AVG(o.away_prob) as away_prob,
                AVG(o.overround) as overround,
                AVG(o.n_bookmakers) as n_bookmakers,
                AVG(o.home_spread) as home_spread,
                AVG(o.total_line) as total_line,
                AVG(o.home_spread_odds) as home_spread_odds,
                AVG(o.away_spread_odds) as away_spread_odds,
                AVG(o.over_odds) as over_odds,
                AVG(o.under_odds) as under_odds
            FROM multisport_odds_snapshots o
            WHERE o.sport_key = 'basketball_nba'
            AND o.is_consensus = true
            GROUP BY o.event_id
        )
        SELECT 
            t.*,
            o.home_odds,
            o.away_odds,
            o.home_prob,
            o.away_prob,
            o.overround,
            o.n_bookmakers,
            o.home_spread,
            o.total_line,
            o.home_spread_odds,
            o.away_spread_odds,
            o.over_odds,
            o.under_odds
        FROM training_matches t
        JOIN odds_agg o ON t.event_id = o.event_id
        ORDER BY t.match_date
    """
    
    df = pd.read_sql(text(query), engine)
    print(f"Loaded {len(df)} NBA training matches with odds")
    return df


def prepare_features(df):
    """Prepare feature matrix and labels"""
    df = df.copy()
    
    df['label'] = df['outcome'].map(CLASS_TO_IDX)
    df = df.dropna(subset=['label'])
    
    available_features = [f for f in NBA_FEATURES if f in df.columns]
    print(f"Using {len(available_features)} features: {available_features}")
    
    X = df[available_features].copy()
    
    for col in X.columns:
        X[col] = pd.to_numeric(X[col], errors='coerce')
    
    X = X.fillna(X.median())
    
    y = df['label'].astype(int)
    
    return X, y, available_features


def train_model(X, y, feature_names):
    """Train LightGBM model with time-series cross-validation"""
    
    tscv = TimeSeriesSplit(n_splits=3)
    
    cv_scores = []
    cv_accuracies = []
    models = []
    
    for fold, (train_idx, val_idx) in enumerate(tscv.split(X)):
        X_train, X_val = X.iloc[train_idx], X.iloc[val_idx]
        y_train, y_val = y.iloc[train_idx], y.iloc[val_idx]
        
        model = lgb.LGBMClassifier(**LGBM_PARAMS)
        model.fit(
            X_train, y_train,
            eval_set=[(X_val, y_val)],
            callbacks=[lgb.early_stopping(20, verbose=False)]
        )
        
        y_pred_proba = model.predict_proba(X_val)[:, 1]
        y_pred = model.predict(X_val)
        
        logloss = log_loss(y_val, y_pred_proba)
        acc = accuracy_score(y_val, y_pred)
        
        cv_scores.append(logloss)
        cv_accuracies.append(acc)
        models.append(model)
        
        print(f"Fold {fold+1}: LogLoss={logloss:.4f}, Accuracy={acc:.1%}")
    
    avg_logloss = np.mean(cv_scores)
    avg_acc = np.mean(cv_accuracies)
    print(f"\nCV Mean: LogLoss={avg_logloss:.4f}, Accuracy={avg_acc:.1%}")
    
    final_model = lgb.LGBMClassifier(**LGBM_PARAMS)
    final_model.fit(X, y)
    
    return final_model, avg_acc, avg_logloss, feature_names


def save_model(model, accuracy, logloss, feature_names):
    """Save trained model to artifacts"""
    
    artifacts_dir = os.path.join(os.path.dirname(__file__), '..', 'models', 'artifacts')
    os.makedirs(artifacts_dir, exist_ok=True)
    
    model_path = os.path.join(artifacts_dir, 'v2_nba_model.joblib')
    
    model_data = {
        'model': model,
        'feature_names': feature_names,
        'accuracy': accuracy,
        'logloss': logloss,
        'class_mapping': CLASS_TO_IDX,
        'idx_to_class': IDX_TO_CLASS,
        'trained_at': datetime.utcnow().isoformat(),
        'sport': 'basketball_nba',
        'version': 'v2'
    }
    
    joblib.dump(model_data, model_path)
    print(f"\nModel saved to {model_path}")
    print(f"  Accuracy: {accuracy:.1%}")
    print(f"  LogLoss: {logloss:.4f}")
    print(f"  Features: {len(feature_names)}")
    
    return model_path


def main():
    print("=" * 60)
    print("V2-NBA Model Training")
    print("=" * 60)
    
    df = load_training_data()
    
    if len(df) < 30:
        print(f"WARNING: Only {len(df)} training samples. Model may be unreliable.")
        print("Recommend collecting more historical data before production use.")
    
    X, y, feature_names = prepare_features(df)
    
    print(f"\nTraining set: {len(X)} samples")
    print(f"Class distribution: Home={sum(y==0)}, Away={sum(y==1)}")
    
    model, accuracy, logloss, features = train_model(X, y, feature_names)
    
    model_path = save_model(model, accuracy, logloss, features)
    
    print("\n" + "=" * 60)
    print("Training Complete!")
    print("=" * 60)
    
    return {
        'model_path': model_path,
        'accuracy': accuracy,
        'logloss': logloss,
        'n_samples': len(X),
        'n_features': len(features)
    }


if __name__ == "__main__":
    result = main()
    print(f"\nResult: {result}")
