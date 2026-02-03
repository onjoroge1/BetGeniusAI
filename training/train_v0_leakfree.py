"""
V0 Form-Only Model - Leak-Free Training with Binary Experts

Computes ELO ratings chronologically (point-in-time) to avoid data leakage.
Tests binary decomposition: Home vs Rest, Away vs Rest, Draw vs Rest.
"""

import os
import json
import logging
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Dict, Tuple, List
from collections import defaultdict
from sqlalchemy import create_engine, text

from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import accuracy_score, log_loss
from sklearn.calibration import CalibratedClassifierCV
import joblib

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MODEL_DIR = "models/saved"
MODEL_NAME = "v0_form_model"

K_FACTOR = 32
HOME_ADVANTAGE = 100
INITIAL_ELO = 1500


class ChronologicalELO:
    """Computes ELO ratings in temporal order (leak-free)."""
    
    def __init__(self):
        self.ratings = {}
        self.match_history = defaultdict(list)
        self.h2h_history = defaultdict(list)
    
    def get_elo(self, team_id: int) -> float:
        return self.ratings.get(team_id, INITIAL_ELO)
    
    def get_form(self, team_id: int, n: int = 5) -> Dict:
        """Get last N match results for a team."""
        history = self.match_history[team_id][-n:]
        if not history:
            return {'wins': 0, 'draws': 0, 'losses': 0, 'matches': 0, 'points': 0}
        
        wins = sum(1 for r in history if r == 'W')
        draws = sum(1 for r in history if r == 'D')
        losses = sum(1 for r in history if r == 'L')
        return {
            'wins': wins,
            'draws': draws, 
            'losses': losses,
            'matches': len(history),
            'points': wins * 3 + draws
        }
    
    def get_h2h(self, home_id: int, away_id: int) -> Dict:
        """Get head-to-head history."""
        key = tuple(sorted([home_id, away_id]))
        history = self.h2h_history[key]
        if not history:
            return {'home_wins': 0, 'away_wins': 0, 'draws': 0, 'matches': 0}
        
        home_wins = sum(1 for h, a, r in history if (h == home_id and r == 'H') or (a == home_id and r == 'A'))
        away_wins = sum(1 for h, a, r in history if (h == away_id and r == 'H') or (a == away_id and r == 'A'))
        draws = sum(1 for h, a, r in history if r == 'D')
        return {
            'home_wins': home_wins,
            'away_wins': away_wins,
            'draws': draws,
            'matches': len(history)
        }
    
    def update(self, home_id: int, away_id: int, outcome: str):
        """Update ratings after a match."""
        home_elo = self.get_elo(home_id)
        away_elo = self.get_elo(away_id)
        
        expected_home = 1.0 / (1.0 + 10 ** ((away_elo - home_elo - HOME_ADVANTAGE) / 400.0))
        
        if outcome == 'H':
            home_score, away_score = 1.0, 0.0
            self.match_history[home_id].append('W')
            self.match_history[away_id].append('L')
        elif outcome == 'A':
            home_score, away_score = 0.0, 1.0
            self.match_history[home_id].append('L')
            self.match_history[away_id].append('W')
        else:
            home_score, away_score = 0.5, 0.5
            self.match_history[home_id].append('D')
            self.match_history[away_id].append('D')
        
        self.ratings[home_id] = home_elo + K_FACTOR * (home_score - expected_home)
        self.ratings[away_id] = away_elo + K_FACTOR * (away_score - (1 - expected_home))
        
        key = tuple(sorted([home_id, away_id]))
        self.h2h_history[key].append((home_id, away_id, outcome))


def load_matches() -> pd.DataFrame:
    """Load all matches in chronological order."""
    engine = create_engine(os.environ['DATABASE_URL'])
    
    query = """
        SELECT 
            f.match_id,
            f.home_team_id,
            f.away_team_id,
            f.league_id,
            f.kickoff_at,
            m.outcome
        FROM fixtures f
        JOIN matches m ON f.match_id = m.match_id
        WHERE f.status = 'finished'
        AND f.home_team_id IS NOT NULL
        AND f.away_team_id IS NOT NULL
        AND m.outcome IS NOT NULL
        ORDER BY f.kickoff_at ASC
    """
    
    df = pd.read_sql(query, engine)
    logger.info(f"Loaded {len(df)} matches from {df['kickoff_at'].min()} to {df['kickoff_at'].max()}")
    return df


def build_features_chronological(df: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray, List[str]]:
    """Build features with leak-free ELO computation."""
    elo = ChronologicalELO()
    
    features = []
    targets = []
    
    tier1_leagues = {39, 140, 78, 135, 61}
    
    for idx, row in df.iterrows():
        home_id = row['home_team_id']
        away_id = row['away_team_id']
        league_id = row['league_id']
        outcome = row['outcome']
        
        home_elo = elo.get_elo(home_id)
        away_elo = elo.get_elo(away_id)
        home_form = elo.get_form(home_id, n=5)
        away_form = elo.get_form(away_id, n=5)
        h2h = elo.get_h2h(home_id, away_id)
        
        elo_diff = home_elo - away_elo
        elo_expected = 1.0 / (1.0 + 10 ** ((away_elo - home_elo - HOME_ADVANTAGE) / 400.0))
        
        def get_tier(rating):
            if rating >= 1700: return 3
            elif rating >= 1550: return 2
            elif rating >= 1400: return 1
            else: return 0
        
        home_form_pts = home_form['points'] / max(home_form['matches'], 1) if home_form['matches'] > 0 else 1.0
        away_form_pts = away_form['points'] / max(away_form['matches'], 1) if away_form['matches'] > 0 else 1.0
        
        home_win_rate = home_form['wins'] / max(home_form['matches'], 1) if home_form['matches'] > 0 else 0.33
        away_win_rate = away_form['wins'] / max(away_form['matches'], 1) if away_form['matches'] > 0 else 0.33
        home_draw_rate = home_form['draws'] / max(home_form['matches'], 1) if home_form['matches'] > 0 else 0.33
        away_draw_rate = away_form['draws'] / max(away_form['matches'], 1) if away_form['matches'] > 0 else 0.33
        
        h2h_home_rate = h2h['home_wins'] / max(h2h['matches'], 1) if h2h['matches'] > 0 else 0.4
        h2h_draw_rate = h2h['draws'] / max(h2h['matches'], 1) if h2h['matches'] > 0 else 0.25
        
        feature_vec = [
            elo_diff,
            elo_expected,
            HOME_ADVANTAGE,
            get_tier(home_elo) - get_tier(away_elo),
            home_elo,
            away_elo,
            home_form_pts - away_form_pts,
            home_win_rate - away_win_rate,
            home_draw_rate,
            away_draw_rate,
            home_form['matches'],
            away_form['matches'],
            1 if league_id in tier1_leagues else 0,
            h2h['matches'],
            h2h_home_rate,
            h2h_draw_rate,
        ]
        
        features.append(feature_vec)
        targets.append({'H': 0, 'D': 1, 'A': 2}[outcome])
        
        elo.update(home_id, away_id, outcome)
    
    feature_names = [
        'elo_diff', 'elo_expected', 'home_advantage', 'elo_tier_diff',
        'home_elo', 'away_elo', 'form_pts_diff', 'win_rate_diff',
        'home_draw_rate', 'away_draw_rate', 'home_matches', 'away_matches',
        'is_tier1', 'h2h_matches', 'h2h_home_rate', 'h2h_draw_rate'
    ]
    
    return np.array(features), np.array(targets), feature_names


def train_binary_experts(X_train, y_train, X_test, y_test) -> Dict:
    """Train binary classifiers: Home vs Rest, Away vs Rest, Draw vs Rest."""
    
    results = {}
    expert_models = {}
    
    y_home = (y_train == 0).astype(int)
    y_away = (y_train == 2).astype(int)
    y_draw = (y_train == 1).astype(int)
    
    y_home_test = (y_test == 0).astype(int)
    y_away_test = (y_test == 2).astype(int)
    y_draw_test = (y_test == 1).astype(int)
    
    for name, y_binary, y_test_binary in [
        ('home', y_home, y_home_test),
        ('away', y_away, y_away_test),
        ('draw', y_draw, y_draw_test)
    ]:
        model = LogisticRegression(max_iter=500, random_state=42, class_weight='balanced')
        model.fit(X_train, y_binary)
        
        probs = model.predict_proba(X_test)[:, 1]
        preds = model.predict(X_test)
        
        acc = accuracy_score(y_test_binary, preds)
        ll = log_loss(y_test_binary, probs)
        
        results[name] = {'accuracy': acc, 'logloss': ll, 'probs': probs}
        expert_models[name] = model
        logger.info(f"  {name.upper()} Expert: Accuracy={acc:.2%}, LogLoss={ll:.4f}")
    
    return results, expert_models


def ensemble_voting(expert_results: Dict, y_test: np.ndarray) -> Dict:
    """Test different ensemble strategies."""
    
    home_probs = expert_results['home']['probs']
    away_probs = expert_results['away']['probs']
    draw_probs = expert_results['draw']['probs']
    
    strategies = {}
    
    raw_probs = np.column_stack([home_probs, draw_probs, away_probs])
    normalized_probs = raw_probs / raw_probs.sum(axis=1, keepdims=True)
    preds = np.argmax(normalized_probs, axis=1)
    strategies['normalized_avg'] = {
        'accuracy': accuracy_score(y_test, preds),
        'logloss': log_loss(y_test, normalized_probs)
    }
    
    softmax_probs = np.exp(raw_probs) / np.exp(raw_probs).sum(axis=1, keepdims=True)
    preds = np.argmax(softmax_probs, axis=1)
    strategies['softmax'] = {
        'accuracy': accuracy_score(y_test, preds),
        'logloss': log_loss(y_test, softmax_probs)
    }
    
    weights = np.array([0.45, 0.20, 0.35])
    weighted_probs = raw_probs * weights
    weighted_probs = weighted_probs / weighted_probs.sum(axis=1, keepdims=True)
    preds = np.argmax(weighted_probs, axis=1)
    strategies['weighted'] = {
        'accuracy': accuracy_score(y_test, preds),
        'logloss': log_loss(y_test, weighted_probs)
    }
    
    return strategies


def train_stacked_meta(X_train, y_train, X_test, y_test, expert_models: Dict) -> Tuple:
    """Train a stacked meta-model using expert predictions as features."""
    
    home_train = expert_models['home'].predict_proba(X_train)[:, 1]
    away_train = expert_models['away'].predict_proba(X_train)[:, 1]
    draw_train = expert_models['draw'].predict_proba(X_train)[:, 1]
    
    home_test = expert_models['home'].predict_proba(X_test)[:, 1]
    away_test = expert_models['away'].predict_proba(X_test)[:, 1]
    draw_test = expert_models['draw'].predict_proba(X_test)[:, 1]
    
    X_meta_train = np.column_stack([X_train, home_train, draw_train, away_train])
    X_meta_test = np.column_stack([X_test, home_test, draw_test, away_test])
    
    meta_model = LogisticRegression(max_iter=500, random_state=42)
    meta_model.fit(X_meta_train, y_train)
    
    preds = meta_model.predict(X_meta_test)
    probs = meta_model.predict_proba(X_meta_test)
    
    acc = accuracy_score(y_test, preds)
    ll = log_loss(y_test, probs)
    
    return meta_model, {'accuracy': acc, 'logloss': ll}


def train_baseline(X_train, y_train, X_test, y_test) -> Dict:
    """Train baseline 3-class classifier."""
    model = LogisticRegression(max_iter=500, random_state=42)
    model.fit(X_train, y_train)
    
    preds = model.predict(X_test)
    probs = model.predict_proba(X_test)
    
    return {
        'model': model,
        'accuracy': accuracy_score(y_test, preds),
        'logloss': log_loss(y_test, probs)
    }


def main():
    """Main training pipeline."""
    logger.info("=" * 70)
    logger.info("V0 Form-Only Model - LEAK-FREE Training with Binary Experts")
    logger.info("=" * 70)
    
    df = load_matches()
    X, y, feature_names = build_features_chronological(df)
    
    logger.info(f"Features: {len(feature_names)} ({', '.join(feature_names[:5])}...)")
    logger.info(f"Samples: {len(X)}")
    logger.info(f"Outcome distribution: H={sum(y==0)}, D={sum(y==1)}, A={sum(y==2)}")
    
    split = int(len(X) * 0.8)
    X_train, X_test = X[:split], X[split:]
    y_train, y_test = y[:split], y[split:]
    
    logger.info(f"Train: {len(X_train)}, Test: {len(X_test)} (80/20 temporal split)")
    
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)
    
    logger.info("\n--- Baseline 3-Class Classifier ---")
    baseline = train_baseline(X_train_scaled, y_train, X_test_scaled, y_test)
    logger.info(f"Baseline: Accuracy={baseline['accuracy']:.2%}, LogLoss={baseline['logloss']:.4f}")
    
    logger.info("\n--- Binary Expert Training ---")
    expert_results, expert_models = train_binary_experts(X_train_scaled, y_train, X_test_scaled, y_test)
    
    logger.info("\n--- Ensemble Voting Strategies ---")
    voting_results = ensemble_voting(expert_results, y_test)
    for strategy, metrics in voting_results.items():
        logger.info(f"  {strategy}: Accuracy={metrics['accuracy']:.2%}, LogLoss={metrics['logloss']:.4f}")
    
    logger.info("\n--- Stacked Meta-Model ---")
    meta_model, meta_results = train_stacked_meta(X_train_scaled, y_train, X_test_scaled, y_test, expert_models)
    logger.info(f"Stacked Meta: Accuracy={meta_results['accuracy']:.2%}, LogLoss={meta_results['logloss']:.4f}")
    
    logger.info("\n" + "=" * 70)
    logger.info("SUMMARY")
    logger.info("=" * 70)
    
    all_results = {
        'Baseline (3-class)': baseline['accuracy'],
        'Normalized Avg': voting_results['normalized_avg']['accuracy'],
        'Softmax': voting_results['softmax']['accuracy'],
        'Weighted': voting_results['weighted']['accuracy'],
        'Stacked Meta': meta_results['accuracy']
    }
    
    best_method = max(all_results, key=all_results.get)
    best_acc = all_results[best_method]
    
    for method, acc in sorted(all_results.items(), key=lambda x: x[1], reverse=True):
        marker = " <-- BEST" if method == best_method else ""
        logger.info(f"  {method}: {acc:.2%}{marker}")
    
    logger.info(f"\nBest method: {best_method} at {best_acc:.2%}")
    logger.info(f"Comparison: V3=52.8%, V1=53%, Random=33%")
    
    os.makedirs(MODEL_DIR, exist_ok=True)
    
    if best_method == 'Stacked Meta':
        full_X_scaled = scaler.fit_transform(X)
        
        for name in ['home', 'away', 'draw']:
            y_binary = (y == {'home': 0, 'away': 2, 'draw': 1}[name]).astype(int)
            expert_models[name].fit(full_X_scaled, y_binary)
        
        home_probs = expert_models['home'].predict_proba(full_X_scaled)[:, 1]
        away_probs = expert_models['away'].predict_proba(full_X_scaled)[:, 1]
        draw_probs = expert_models['draw'].predict_proba(full_X_scaled)[:, 1]
        X_meta = np.column_stack([full_X_scaled, home_probs, draw_probs, away_probs])
        meta_model.fit(X_meta, y)
        
        joblib.dump({
            'scaler': scaler,
            'experts': expert_models,
            'meta_model': meta_model,
            'feature_names': feature_names,
            'model_type': 'stacked_binary_experts'
        }, f"{MODEL_DIR}/{MODEL_NAME}_latest.pkl")
    else:
        baseline['model'].fit(scaler.fit_transform(X), y)
        joblib.dump({
            'scaler': scaler,
            'model': baseline['model'],
            'feature_names': feature_names,
            'model_type': 'baseline_3class'
        }, f"{MODEL_DIR}/{MODEL_NAME}_latest.pkl")
    
    metrics = {
        'best_method': best_method,
        'cv_accuracy_mean': float(best_acc),
        'cv_logloss_mean': float(voting_results.get(best_method.lower().replace(' ', '_'), meta_results if best_method == 'Stacked Meta' else baseline).get('logloss', 1.0)),
        'n_samples': len(X),
        'n_features': len(feature_names),
        'feature_names': feature_names,
        'model_type': 'stacked_binary_experts' if best_method == 'Stacked Meta' else 'baseline_3class',
        'trained_at': datetime.utcnow().isoformat(),
        'leak_free': True
    }
    
    with open(f"{MODEL_DIR}/{MODEL_NAME}_latest_meta.json", 'w') as f:
        json.dump(metrics, f, indent=2)
    
    logger.info(f"\nModel saved to {MODEL_DIR}/{MODEL_NAME}_latest.pkl")
    return metrics


if __name__ == "__main__":
    main()
