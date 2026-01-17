#!/usr/bin/env python3
"""
V3 Temporal Training - Strict cutoff for true out-of-sample validation
Training data: matches ≤ July 31, 2024
Test data: Aug 1, 2024 → Nov 2025 (completely untouched)
"""

import os
import sys
import pickle
import json
import numpy as np
import pandas as pd
import lightgbm as lgb
from pathlib import Path
from datetime import datetime
from sklearn.metrics import accuracy_score, log_loss
from sklearn.isotonic import IsotonicRegression

sys.path.insert(0, str(Path(__file__).parent.parent))
from features.historical_feature_builder import HistoricalFeatureBuilder

import logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')
logger = logging.getLogger(__name__)

OUTPUT_DIR = Path('artifacts/models/v3_temporal')
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

CUTOFF_DATE = '2024-07-31'

BASE_FEATURES = [
    'p_b365_h', 'p_b365_d', 'p_b365_a',
    'p_ps_h', 'p_ps_d', 'p_ps_a',
    'p_avg_h', 'p_avg_d', 'p_avg_a',
    'favorite_strength', 'underdog_value', 'draw_tendency',
    'market_overround', 'sharp_soft_divergence',
    'max_vs_avg_edge_h', 'max_vs_avg_edge_d', 'max_vs_avg_edge_a',
    'league_home_win_rate', 'league_draw_rate', 'league_goals_avg',
    'season_month',
    'expected_total_goals', 'home_goals_expected', 'away_goals_expected',
    'goal_diff_expected',
    'home_value_score', 'draw_value_score', 'away_value_score',
    'home_advantage_signal', 'draw_vs_away_ratio', 'favorite_confidence',
    'upset_potential', 'book_agreement_score', 'implied_competitiveness',
    'sharp_home_signal', 'sharp_away_signal', 'sharp_draw_signal'
]

EXPERT_FEATURES = [
    'expert_home_prob', 'expert_away_prob', 'expert_draw_prob',
    'expert_home_away_diff', 'expert_draw_confidence', 'expert_favorite_spread',
    'expert_norm_home', 'expert_norm_away', 'expert_norm_draw'
]


def train_binary_expert(X_train, y_train, expert_type):
    """Train a binary expert"""
    train_data = lgb.Dataset(X_train, label=y_train)
    
    params = {
        'objective': 'binary',
        'metric': 'binary_logloss',
        'boosting_type': 'gbdt',
        'num_leaves': 31 if expert_type != 'draw' else 25,
        'max_depth': 5 if expert_type != 'draw' else 4,
        'learning_rate': 0.05 if expert_type != 'draw' else 0.03,
        'min_data_in_leaf': 200 if expert_type != 'draw' else 300,
        'feature_fraction': 0.8 if expert_type != 'draw' else 0.7,
        'bagging_fraction': 0.8 if expert_type != 'draw' else 0.7,
        'bagging_freq': 5,
        'lambda_l1': 0.5 if expert_type != 'draw' else 1.0,
        'lambda_l2': 0.5 if expert_type != 'draw' else 1.0,
        'verbosity': -1,
        'seed': 42,
        'n_jobs': -1
    }
    
    if expert_type == 'draw':
        params['scale_pos_weight'] = 2.5
    
    model = lgb.train(params, train_data, num_boost_round=100)
    return model


def main():
    logger.info("=" * 70)
    logger.info("V3 TEMPORAL TRAINING")
    logger.info(f"Strict cutoff: {CUTOFF_DATE}")
    logger.info("No data leakage into holdout period")
    logger.info("=" * 70)
    
    builder = HistoricalFeatureBuilder()
    raw_data = builder.get_all_features_for_training(min_date='2020-01-01')
    
    df = pd.DataFrame(raw_data)
    logger.info(f"Total matches loaded: {len(df)}")
    
    df['match_date'] = pd.to_datetime(df['match_date'])
    df = df.sort_values('match_date').reset_index(drop=True)
    
    for col in BASE_FEATURES:
        if col not in df.columns:
            df[col] = 0.0
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    
    cutoff = pd.to_datetime(CUTOFF_DATE)
    train_df = df[df['match_date'] <= cutoff].copy()
    test_df = df[df['match_date'] > cutoff].copy()
    
    logger.info(f"\n--- STRICT TEMPORAL SPLIT ---")
    logger.info(f"Training: {len(train_df)} matches (up to {CUTOFF_DATE})")
    logger.info(f"Holdout:  {len(test_df)} matches (after {CUTOFF_DATE})")
    logger.info(f"Date range training: {train_df['match_date'].min().date()} to {train_df['match_date'].max().date()}")
    logger.info(f"Date range holdout:  {test_df['match_date'].min().date()} to {test_df['match_date'].max().date()}")
    
    logger.info("\n--- PHASE 1: Training Binary Experts ---")
    
    split1 = int(len(train_df) * 0.6)
    fold1 = train_df.iloc[:split1].copy()
    fold2 = train_df.iloc[split1:].copy()
    
    logger.info(f"Fold 1 (train experts): {len(fold1)} matches")
    logger.info(f"Fold 2 (train meta):    {len(fold2)} matches")
    
    experts = {}
    calibrators = {}
    
    for expert_type in ['home', 'away', 'draw']:
        target_map = {'home': 'H', 'away': 'A', 'draw': 'D'}
        y_fold1 = (fold1['outcome'] == target_map[expert_type]).astype(int)
        
        model = train_binary_expert(fold1[BASE_FEATURES], y_fold1, expert_type)
        experts[expert_type] = model
        
        raw_proba = model.predict(fold2[BASE_FEATURES])
        y_fold2 = (fold2['outcome'] == target_map[expert_type]).astype(int)
        
        calibrator = IsotonicRegression(out_of_bounds='clip')
        calibrator.fit(raw_proba, y_fold2)
        calibrators[expert_type] = calibrator
        
        logger.info(f"  {expert_type.capitalize()} expert trained and calibrated")
    
    logger.info("\n--- PHASE 2: Generating Expert Features ---")
    
    for col in EXPERT_FEATURES:
        fold2[col] = 0.0
        test_df[col] = 0.0
    
    for target_df in [fold2, test_df]:
        for expert_type, model in experts.items():
            raw = model.predict(target_df[BASE_FEATURES])
            cal = calibrators[expert_type].predict(raw)
            target_df[f'expert_{expert_type}_prob'] = np.clip(cal, 0.01, 0.99)
        
        target_df['expert_home_away_diff'] = target_df['expert_home_prob'] - target_df['expert_away_prob']
        target_df['expert_draw_confidence'] = target_df['expert_draw_prob'] * target_df.get('implied_competitiveness', 0.5)
        target_df['expert_favorite_spread'] = abs(target_df['expert_home_prob'] - target_df['expert_away_prob'])
        
        total = target_df['expert_home_prob'] + target_df['expert_away_prob'] + target_df['expert_draw_prob'] * 1.1
        target_df['expert_norm_home'] = target_df['expert_home_prob'] / total
        target_df['expert_norm_away'] = target_df['expert_away_prob'] / total
        target_df['expert_norm_draw'] = (target_df['expert_draw_prob'] * 1.1) / total
    
    logger.info("  Expert features added to fold2 and test set")
    
    logger.info("\n--- PHASE 3: Training Meta-Model ---")
    
    all_features = BASE_FEATURES + EXPERT_FEATURES
    outcome_map = {'H': 0, 'D': 1, 'A': 2}
    
    X_train = fold2[all_features]
    y_train = fold2['outcome'].map(outcome_map)
    
    logger.info(f"Training meta-model on {len(fold2)} matches with {len(all_features)} features")
    
    params = {
        'objective': 'multiclass',
        'num_class': 3,
        'metric': 'multi_logloss',
        'boosting_type': 'gbdt',
        'num_leaves': 31,
        'max_depth': 5,
        'learning_rate': 0.025,
        'min_data_in_leaf': 200,
        'feature_fraction': 0.75,
        'bagging_fraction': 0.75,
        'bagging_freq': 5,
        'lambda_l1': 0.7,
        'lambda_l2': 0.7,
        'verbosity': -1,
        'seed': 42,
        'n_jobs': -1
    }
    
    train_data = lgb.Dataset(X_train, label=y_train)
    meta_model = lgb.train(params, train_data, num_boost_round=100)
    
    logger.info("  Meta-model trained")
    
    logger.info("\n--- SAVING MODELS ---")
    
    with open(OUTPUT_DIR / 'meta_model.pkl', 'wb') as f:
        pickle.dump(meta_model, f)
    
    for expert_type in experts.keys():
        with open(OUTPUT_DIR / f'{expert_type}_expert.pkl', 'wb') as f:
            pickle.dump(experts[expert_type], f)
        with open(OUTPUT_DIR / f'{expert_type}_calibrator.pkl', 'wb') as f:
            pickle.dump(calibrators[expert_type], f)
    
    logger.info(f"  Models saved to {OUTPUT_DIR}")
    
    logger.info("\n" + "=" * 70)
    logger.info("TRUE OUT-OF-SAMPLE EVALUATION")
    logger.info("=" * 70)
    
    has_ps = (test_df['p_ps_h'] > 0) & (test_df['p_ps_d'] > 0) & (test_df['p_ps_a'] > 0)
    test_df = test_df[has_ps].copy()
    
    logger.info(f"\nTest set: {len(test_df)} matches with Pinnacle odds")
    
    X_test = test_df[all_features]
    y_test = test_df['outcome'].map(outcome_map)
    
    v3_proba = meta_model.predict(X_test)
    v3_proba = v3_proba / v3_proba.sum(axis=1, keepdims=True)
    v3_pred = np.argmax(v3_proba, axis=1)
    
    total_ps = test_df['p_ps_h'] + test_df['p_ps_d'] + test_df['p_ps_a']
    book_proba = np.column_stack([
        test_df['p_ps_h'] / total_ps,
        test_df['p_ps_d'] / total_ps,
        test_df['p_ps_a'] / total_ps
    ])
    book_pred = np.argmax(book_proba, axis=1)
    
    v3_acc = accuracy_score(y_test, v3_pred)
    v3_ll = log_loss(y_test, v3_proba)
    
    book_acc = accuracy_score(y_test, book_pred)
    book_ll = log_loss(y_test, book_proba)
    
    logger.info(f"\n                    Accuracy    LogLoss     N")
    logger.info("-" * 55)
    logger.info(f"Pinnacle De-vigged:  {book_acc:.4f}      {book_ll:.4f}      {len(test_df)}")
    logger.info(f"V3 Temporal:         {v3_acc:.4f}      {v3_ll:.4f}      {len(test_df)}")
    logger.info("-" * 55)
    logger.info(f"Difference:          {v3_acc - book_acc:+.4f}      {book_ll - v3_ll:+.4f}")
    
    logger.info("\n--- BOOTSTRAP CONFIDENCE ---")
    
    n = len(y_test)
    ll_diffs = []
    
    for _ in range(1000):
        idx = np.random.choice(n, n, replace=True)
        ll_v3 = log_loss(y_test.values[idx], v3_proba[idx])
        ll_book = log_loss(y_test.values[idx], book_proba[idx])
        ll_diffs.append(ll_book - ll_v3)
    
    ll_diffs = np.array(ll_diffs)
    
    logger.info(f"LogLoss improvement (V3 vs Pinnacle):")
    logger.info(f"  Mean: {ll_diffs.mean():.4f}")
    logger.info(f"  95% CI: [{np.percentile(ll_diffs, 2.5):.4f}, {np.percentile(ll_diffs, 97.5):.4f}]")
    logger.info(f"  P(V3 better): {(ll_diffs > 0).mean()*100:.1f}%")
    
    logger.info("\n--- PER-OUTCOME CALIBRATION ---")
    
    outcome_names = ['Home', 'Draw', 'Away']
    for oidx, oname in enumerate(outcome_names):
        actual = (y_test.values == oidx).mean()
        v3_mean = v3_proba[:, oidx].mean()
        book_mean = book_proba[:, oidx].mean()
        logger.info(f"  {oname}: Actual={actual:.3f}, V3={v3_mean:.3f}, Pinnacle={book_mean:.3f}")
    
    ll_improvement = book_ll - v3_ll
    
    if ll_improvement > 0 and (ll_diffs > 0).mean() > 0.9:
        verdict = "PASSES"
        verdict_detail = "V3 shows statistically significant improvement over Pinnacle"
    elif ll_improvement > 0 and (ll_diffs > 0).mean() > 0.5:
        verdict = "INCONCLUSIVE_POSITIVE"
        verdict_detail = "V3 shows slight improvement, but not statistically significant"
    elif abs(ll_improvement) < 0.01:
        verdict = "MATCHES"
        verdict_detail = "V3 approximately matches Pinnacle probability quality"
    else:
        verdict = "FAILS"
        verdict_detail = "V3 does not beat Pinnacle on this holdout"
    
    logger.info(f"\n--- VERDICT: {verdict} ---")
    logger.info(f"  {verdict_detail}")
    
    metadata = {
        'version': 'v3_temporal',
        'trained_at': datetime.now().isoformat(),
        'cutoff_date': CUTOFF_DATE,
        'training_samples': len(train_df),
        'test_samples': len(test_df),
        'features': all_features,
        'results': {
            'v3_accuracy': float(v3_acc),
            'v3_logloss': float(v3_ll),
            'book_accuracy': float(book_acc),
            'book_logloss': float(book_ll),
            'logloss_improvement': float(ll_improvement),
            'bootstrap_mean': float(ll_diffs.mean()),
            'bootstrap_ci_lower': float(np.percentile(ll_diffs, 2.5)),
            'bootstrap_ci_upper': float(np.percentile(ll_diffs, 97.5)),
            'prob_v3_better': float((ll_diffs > 0).mean())
        },
        'verdict': verdict,
        'verdict_detail': verdict_detail
    }
    
    with open(OUTPUT_DIR / 'metadata.json', 'w') as f:
        json.dump(metadata, f, indent=2)
    
    logger.info(f"\nResults saved to: {OUTPUT_DIR}")
    
    return metadata


if __name__ == "__main__":
    main()
