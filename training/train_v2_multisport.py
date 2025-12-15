"""
V2 Multi-Sport Training Script (NBA & NHL)

Trains LightGBM models for basketball and hockey predictions.
These are 2-way classification models (Home/Away) unlike football's 3-way.

Usage:
    python training/train_v2_multisport.py --sport basketball
    python training/train_v2_multisport.py --sport hockey
    python training/train_v2_multisport.py --sport all

Features:
    - Moneyline odds (opening/closing)
    - Odds drift (market movement)
    - Spread lines
    - Totals (over/under)
    - Market efficiency metrics
    - Volatility features
"""

import os
import sys
import json
import pickle
import logging
import argparse
import numpy as np
import pandas as pd
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Optional

import psycopg2
from psycopg2.extras import RealDictCursor
import lightgbm as lgb
from sklearn.model_selection import TimeSeriesSplit, train_test_split
from sklearn.metrics import log_loss, accuracy_score, roc_auc_score, classification_report

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


FEATURE_COLUMNS = [
    'open_home_odds', 'open_away_odds',
    'close_home_odds', 'close_away_odds',
    'home_odds_drift', 'away_odds_drift',
    'open_home_prob', 'open_away_prob',
    'close_home_prob', 'close_away_prob',
    'home_prob_drift', 'away_prob_drift',
    'spread_line', 'home_spread_odds', 'away_spread_odds',
    'open_spread', 'spread_drift',
    'total_line', 'over_odds', 'under_odds',
    'open_total', 'total_drift',
    'overround', 'n_bookmakers', 'n_snapshots',
    'hours_before_match', 'home_odds_volatility',
    'home_is_favorite', 'odds_diff', 'prob_diff'
]


class MultiSportTrainer:
    """Trains V2 models for NBA and NHL"""
    
    def __init__(self, sport: str):
        self.sport = sport
        self.db_url = os.getenv('DATABASE_URL')
        self.output_dir = Path(f"artifacts/models/v2_{sport}")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.model = None
        self.feature_names = []
        self.metrics = {}
    
    def load_training_data(self) -> pd.DataFrame:
        """Load training data from multisport_training table"""
        logger.info(f"Loading {self.sport} training data...")
        
        conn = psycopg2.connect(self.db_url)
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        cursor.execute("""
            SELECT 
                event_id,
                home_team,
                away_team,
                match_date,
                home_score,
                away_score,
                outcome,
                features,
                consensus_home_prob,
                consensus_away_prob
            FROM multisport_training
            WHERE sport = %s
            ORDER BY match_date
        """, (self.sport,))
        
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            raise ValueError(f"No training data found for {self.sport}")
        
        logger.info(f"Loaded {len(rows)} {self.sport} games")
        
        records = []
        for row in rows:
            record = dict(row)
            features = row['features'] if isinstance(row['features'], dict) else json.loads(row['features'])
            record.update(features)
            del record['features']
            records.append(record)
        
        df = pd.DataFrame(records)
        
        df['target'] = df['outcome'].map({'H': 1, 'A': 0})
        
        return df
    
    def prepare_features(self, df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.Series]:
        """Prepare feature matrix and target vector"""
        
        available_features = [f for f in FEATURE_COLUMNS if f in df.columns]
        missing_features = [f for f in FEATURE_COLUMNS if f not in df.columns]
        
        if missing_features:
            logger.warning(f"Missing features: {missing_features}")
        
        X = df[available_features].copy()
        y = df['target']
        
        for col in X.columns:
            X[col] = pd.to_numeric(X[col], errors='coerce')
        
        X = X.fillna(0)
        
        self.feature_names = list(X.columns)
        logger.info(f"Using {len(self.feature_names)} features")
        
        return X, y
    
    def train(self, X: pd.DataFrame, y: pd.Series) -> Dict:
        """Train LightGBM model with time-series cross-validation"""
        
        logger.info(f"Training V2-{self.sport.upper()} model...")
        
        train_size = int(len(X) * 0.8)
        X_train, X_test = X.iloc[:train_size], X.iloc[train_size:]
        y_train, y_test = y.iloc[:train_size], y.iloc[train_size:]
        
        logger.info(f"Train: {len(X_train)}, Test: {len(X_test)}")
        
        params = {
            'objective': 'binary',
            'metric': 'binary_logloss',
            'boosting_type': 'gbdt',
            'num_leaves': 15,
            'learning_rate': 0.05,
            'feature_fraction': 0.8,
            'bagging_fraction': 0.8,
            'bagging_freq': 5,
            'min_child_samples': 10,
            'reg_alpha': 0.1,
            'reg_lambda': 0.1,
            'verbose': -1,
            'seed': 42
        }
        
        train_data = lgb.Dataset(X_train, label=y_train)
        valid_data = lgb.Dataset(X_test, label=y_test, reference=train_data)
        
        self.model = lgb.train(
            params,
            train_data,
            num_boost_round=500,
            valid_sets=[train_data, valid_data],
            valid_names=['train', 'valid'],
            callbacks=[
                lgb.early_stopping(stopping_rounds=50),
                lgb.log_evaluation(period=100)
            ]
        )
        
        y_pred_proba = self.model.predict(X_test)
        y_pred = (y_pred_proba > 0.5).astype(int)
        
        self.metrics = {
            'sport': self.sport,
            'train_size': len(X_train),
            'test_size': len(X_test),
            'accuracy': float(accuracy_score(y_test, y_pred)),
            'log_loss': float(log_loss(y_test, y_pred_proba)),
            'roc_auc': float(roc_auc_score(y_test, y_pred_proba)),
            'home_win_rate_actual': float(y_test.mean()),
            'home_win_rate_predicted': float(y_pred.mean()),
            'n_features': len(self.feature_names),
            'best_iteration': self.model.best_iteration,
            'trained_at': datetime.utcnow().isoformat()
        }
        
        logger.info(f"\n{'='*50}")
        logger.info(f"V2-{self.sport.upper()} Training Results")
        logger.info(f"{'='*50}")
        logger.info(f"Accuracy: {self.metrics['accuracy']:.1%}")
        logger.info(f"Log Loss: {self.metrics['log_loss']:.4f}")
        logger.info(f"ROC-AUC: {self.metrics['roc_auc']:.4f}")
        logger.info(f"Home Win Rate (actual): {self.metrics['home_win_rate_actual']:.1%}")
        logger.info(f"Home Win Rate (pred): {self.metrics['home_win_rate_predicted']:.1%}")
        
        importance = pd.DataFrame({
            'feature': self.feature_names,
            'importance': self.model.feature_importance(importance_type='gain')
        }).sort_values('importance', ascending=False)
        
        logger.info(f"\nTop 10 Features:")
        for _, row in importance.head(10).iterrows():
            logger.info(f"  {row['feature']}: {row['importance']:.1f}")
        
        return self.metrics
    
    def save_model(self):
        """Save trained model and metadata"""
        
        model_path = self.output_dir / f"v2_{self.sport}_model.pkl"
        with open(model_path, 'wb') as f:
            pickle.dump({
                'model': self.model,
                'feature_names': self.feature_names,
                'metrics': self.metrics,
                'sport': self.sport
            }, f)
        
        logger.info(f"Model saved to {model_path}")
        
        metadata_path = self.output_dir / f"v2_{self.sport}_metadata.json"
        with open(metadata_path, 'w') as f:
            json.dump({
                'feature_names': self.feature_names,
                'metrics': self.metrics,
                'sport': self.sport
            }, f, indent=2)
        
        logger.info(f"Metadata saved to {metadata_path}")
    
    def run_full_training(self) -> Dict:
        """Run complete training pipeline"""
        
        df = self.load_training_data()
        X, y = self.prepare_features(df)
        metrics = self.train(X, y)
        self.save_model()
        
        return metrics


def train_sport(sport: str) -> Dict:
    """Train model for a specific sport"""
    trainer = MultiSportTrainer(sport)
    return trainer.run_full_training()


def train_all_sports() -> Dict:
    """Train models for all supported sports"""
    results = {}
    
    for sport in ['basketball', 'hockey']:
        logger.info(f"\n{'#'*60}")
        logger.info(f"Training V2-{sport.upper()}")
        logger.info(f"{'#'*60}")
        
        try:
            results[sport] = train_sport(sport)
        except Exception as e:
            logger.error(f"Failed to train {sport}: {e}")
            results[sport] = {'error': str(e)}
    
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train V2 multi-sport models")
    parser.add_argument('--sport', type=str, default='all', 
                        choices=['basketball', 'hockey', 'all'],
                        help='Sport to train (basketball, hockey, or all)')
    
    args = parser.parse_args()
    
    if args.sport == 'all':
        results = train_all_sports()
    else:
        results = {args.sport: train_sport(args.sport)}
    
    print(f"\n{'='*60}")
    print("TRAINING SUMMARY")
    print(f"{'='*60}")
    for sport, metrics in results.items():
        if 'error' in metrics:
            print(f"{sport.upper()}: FAILED - {metrics['error']}")
        else:
            print(f"{sport.upper()}: Accuracy={metrics['accuracy']:.1%}, LogLoss={metrics['log_loss']:.4f}, AUC={metrics['roc_auc']:.4f}")
