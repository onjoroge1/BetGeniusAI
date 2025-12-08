"""
Unified V2 LightGBM Training Script - Complete 61-Feature Model

Trains a unified V2 model using all available features:
- V2 Base Features (50): Odds, ELO, form, H2H, advanced stats, context, drift
- V3 Sharp Intelligence (11): Sharp books, league ECE, timing

Usage:
    python training/train_unified_v2.py

Expected Results:
    - 3-way accuracy: 53-56% (target: beat V1's 54.3%)
    - LogLoss: < 1.00
    - Brier Score: < 0.20
"""

import os
import sys
import json
import pickle
import logging
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

import psycopg2
import lightgbm as lgb
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import log_loss, accuracy_score

sys.path.append('.')
from features.unified_v2_feature_builder import UnifiedV2FeatureBuilder

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

OUTPUT_DIR = Path("artifacts/models/unified_v2")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def get_trainable_matches() -> List[Tuple[int, str, datetime]]:
    """
    Get matches suitable for unified V2 training
    
    Requirements:
    - Finished matches with known outcomes
    - Has odds_consensus data (for base features)
    - Recent enough for relevant training (2022+)
    """
    conn = psycopg2.connect(os.getenv('DATABASE_URL'))
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT 
            f.match_id,
            CASE 
                WHEN m.home_goals > m.away_goals THEN 'H'
                WHEN m.home_goals < m.away_goals THEN 'A'
                ELSE 'D'
            END as outcome,
            f.kickoff_at
        FROM fixtures f
        JOIN matches m ON f.match_id = m.match_id
        WHERE f.status = 'finished'
          AND m.home_goals IS NOT NULL
          AND m.away_goals IS NOT NULL
          AND f.kickoff_at >= '2024-01-01'
        ORDER BY f.kickoff_at
    """)
    
    matches = cursor.fetchall()
    
    if len(matches) < 2000:
        logger.info("Few matches from fixtures, trying training_matches...")
        # Use tm.id as match_id (historical_features uses training_matches.id)
        # Also need tm.match_id for odds_snapshots which uses API football match_id
        # FILTER: Only include matches that have odds OR historical_features
        cursor.execute("""
            SELECT DISTINCT ON (tm.id)
                tm.id as match_id,
                tm.match_id as api_match_id,
                CASE 
                    WHEN tm.outcome IN ('H', 'Home') THEN 'H'
                    WHEN tm.outcome IN ('A', 'Away') THEN 'A'
                    WHEN tm.outcome IN ('D', 'Draw') THEN 'D'
                    ELSE tm.outcome
                END as outcome,
                tm.match_date as kickoff_at
            FROM training_matches tm
            WHERE tm.outcome IS NOT NULL
              AND tm.match_date >= '2020-01-01'
              AND (
                  -- Has odds data (via API football match_id)
                  EXISTS (SELECT 1 FROM odds_snapshots os WHERE os.match_id = tm.match_id)
                  OR
                  -- Has historical features (via training_matches.id)
                  EXISTS (SELECT 1 FROM historical_features hf WHERE hf.match_id = tm.id)
              )
            ORDER BY tm.id, tm.match_date
        """)
        matches = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    logger.info(f"Found {len(matches)} trainable matches")
    return matches


def build_training_dataset(matches: List[Tuple], max_matches: int = None) -> pd.DataFrame:
    """Build training dataset with unified V2 features"""
    
    builder = UnifiedV2FeatureBuilder()
    records = []
    skipped = 0
    
    if max_matches:
        matches = matches[:max_matches]
    
    logger.info(f"Building features for {len(matches)} matches...")
    
    for i, row in enumerate(matches):
        # Handle both 3-column (fixtures) and 4-column (training_matches) formats
        if len(row) == 4:
            match_id, api_match_id, outcome, kickoff = row
        else:
            match_id, outcome, kickoff = row
            api_match_id = None
            
        try:
            features = builder.build_features(match_id, cutoff_time=kickoff)
            features['match_id'] = match_id
            features['outcome'] = outcome
            features['kickoff'] = kickoff
            records.append(features)
            
            if (i + 1) % 50 == 0:
                logger.info(f"  Progress: {i+1}/{len(matches)} matches ({len(records)} built, {skipped} skipped)")
                
        except ValueError as e:
            skipped += 1
            if skipped <= 5:
                logger.warning(f"  Skip match {match_id}: {e}")
            continue
        except Exception as e:
            skipped += 1
            logger.error(f"  Error match {match_id}: {e}")
            continue
    
    if not records:
        raise ValueError("No training data could be built")
    
    df = pd.DataFrame(records)
    logger.info(f"Built {len(df)} training samples with {len(df.columns)} columns (skipped {skipped})")
    
    feature_cols = [c for c in df.columns if c not in ['match_id', 'outcome', 'kickoff']]
    non_zero_counts = {col: (df[col] != 0).sum() for col in feature_cols}
    
    logger.info("\nFeature coverage (non-zero values):")
    for col in sorted(feature_cols):
        pct = non_zero_counts[col] / len(df) * 100
        status = "✓" if pct > 50 else "⚠️" if pct > 10 else "❌"
        if pct < 100:
            logger.info(f"  {status} {col}: {pct:.1f}%")
    
    return df


def train_unified_v2_model(df: pd.DataFrame, n_splits: int = 5, exclude_sparse: bool = True) -> Dict:
    """Train unified V2 LightGBM with time-series cross-validation
    
    Args:
        df: Training dataframe with features
        n_splits: Number of CV folds
        exclude_sparse: If True, exclude features with <5% coverage (default True)
    """
    
    # Get feature columns, optionally excluding sparse ones
    all_feature_cols = [c for c in df.columns if c not in ['match_id', 'outcome', 'kickoff']]
    
    if exclude_sparse:
        # Use the sparse features list from feature builder
        sparse_features = UnifiedV2FeatureBuilder.SPARSE_FEATURES
        feature_cols = [c for c in all_feature_cols if c not in sparse_features]
        excluded = [c for c in all_feature_cols if c in sparse_features]
        logger.info(f"\nExcluding {len(excluded)} sparse features: {excluded}")
    else:
        feature_cols = all_feature_cols
    
    X = df[feature_cols].fillna(0).values
    
    outcome_map = {'H': 0, 'D': 1, 'A': 2}
    y = df['outcome'].map(outcome_map).values
    
    logger.info(f"\nTraining unified V2 with {len(feature_cols)} features, {len(y)} samples")
    logger.info(f"Class distribution: H={sum(y==0)}, D={sum(y==1)}, A={sum(y==2)}")
    
    params = {
        'objective': 'multiclass',
        'num_class': 3,
        'metric': 'multi_logloss',
        'boosting_type': 'gbdt',
        'learning_rate': 0.03,
        'num_leaves': 31,
        'max_depth': 6,
        'min_data_in_leaf': 20,
        'feature_fraction': 0.8,
        'bagging_fraction': 0.8,
        'bagging_freq': 5,
        'lambda_l1': 0.1,
        'lambda_l2': 0.1,
        'verbose': -1,
        'force_row_wise': True,
        'seed': 42
    }
    
    n_splits = min(n_splits, len(y) // 50)
    if n_splits < 2:
        n_splits = 2
    
    gap_size = max(20, len(y) // 50)
    tscv = TimeSeriesSplit(n_splits=n_splits, gap=gap_size)
    logger.info(f"Using TimeSeriesSplit with gap={gap_size} for embargo period")
    
    models = []
    oof_preds = np.zeros((len(y), 3))
    oof_mask = np.zeros(len(y), dtype=bool)
    fold_metrics = []
    
    for fold, (train_idx, val_idx) in enumerate(tscv.split(X)):
        logger.info(f"\n--- Fold {fold + 1}/{n_splits} ---")
        logger.info(f"Train: {len(train_idx)} samples, Val: {len(val_idx)} samples")
        
        X_train, X_val = X[train_idx], X[val_idx]
        y_train, y_val = y[train_idx], y[val_idx]
        
        train_data = lgb.Dataset(X_train, label=y_train)
        val_data = lgb.Dataset(X_val, label=y_val, reference=train_data)
        
        model = lgb.train(
            params,
            train_data,
            num_boost_round=2000,
            valid_sets=[train_data, val_data],
            valid_names=['train', 'valid'],
            callbacks=[
                lgb.early_stopping(stopping_rounds=100),
                lgb.log_evaluation(period=200)
            ]
        )
        
        val_preds = model.predict(X_val, num_iteration=model.best_iteration)
        oof_preds[val_idx] = val_preds
        oof_mask[val_idx] = True
        
        val_pred_labels = np.argmax(val_preds, axis=1)
        fold_acc = accuracy_score(y_val, val_pred_labels)
        fold_logloss = log_loss(y_val, val_preds)
        
        fold_metrics.append({
            'fold': fold + 1,
            'accuracy': fold_acc,
            'logloss': fold_logloss,
            'best_iteration': model.best_iteration
        })
        
        logger.info(f"Fold {fold + 1}: Accuracy={fold_acc:.3f}, LogLoss={fold_logloss:.4f}")
        
        models.append(model)
    
    y_valid = y[oof_mask]
    preds_valid = oof_preds[oof_mask]
    
    oof_accuracy = accuracy_score(y_valid, np.argmax(preds_valid, axis=1))
    oof_logloss = log_loss(y_valid, preds_valid)
    
    brier_components = []
    for i, cls in enumerate([0, 1, 2]):
        y_binary = (y_valid == cls).astype(float)
        pred_probs = preds_valid[:, i]
        brier_components.append(np.mean((y_binary - pred_probs) ** 2))
    oof_brier = np.mean(brier_components)
    
    logger.info(f"\n{'='*50}")
    logger.info(f"UNIFIED V2 OOF METRICS:")
    logger.info(f"  3-Way Accuracy: {oof_accuracy:.3f} ({oof_accuracy*100:.1f}%)")
    logger.info(f"  LogLoss: {oof_logloss:.4f}")
    logger.info(f"  Brier Score: {oof_brier:.4f}")
    logger.info(f"  Validated Samples: {len(y_valid)}/{len(y)}")
    logger.info(f"{'='*50}")
    
    feature_importance = []
    for i, col in enumerate(feature_cols):
        avg_importance = np.mean([m.feature_importance()[i] for m in models])
        feature_importance.append({'feature': col, 'importance': avg_importance})
    
    feature_importance.sort(key=lambda x: x['importance'], reverse=True)
    
    logger.info("\nTop 15 Feature Importance:")
    for fi in feature_importance[:15]:
        logger.info(f"  {fi['feature']}: {fi['importance']:.2f}")
    
    return {
        'models': models,
        'feature_cols': feature_cols,
        'oof_metrics': {
            'accuracy_3way': oof_accuracy,
            'logloss': oof_logloss,
            'brier_score': oof_brier,
            'n_samples': len(y_valid),
            'n_folds': n_splits
        },
        'fold_metrics': fold_metrics,
        'feature_importance': feature_importance,
        'params': params
    }


def random_label_sanity_check(df: pd.DataFrame, feature_cols: List[str], n_trials: int = 3) -> Dict:
    """Run sanity check with randomized labels to detect leakage"""
    
    logger.info("\n--- RANDOM LABEL SANITY CHECK ---")
    
    X = df[feature_cols].fillna(0).values
    y = df['outcome'].map({'H': 0, 'D': 1, 'A': 2}).values
    
    random_accuracies = []
    
    for trial in range(n_trials):
        y_random = np.random.permutation(y)
        
        n_splits = min(3, len(y) // 50)
        if n_splits < 2:
            n_splits = 2
        
        tscv = TimeSeriesSplit(n_splits=n_splits, gap=5)
        
        fold_accs = []
        for train_idx, val_idx in tscv.split(X):
            X_train, X_val = X[train_idx], X[val_idx]
            y_train, y_val = y_random[train_idx], y_random[val_idx]
            
            train_data = lgb.Dataset(X_train, label=y_train)
            
            params = {
                'objective': 'multiclass',
                'num_class': 3,
                'learning_rate': 0.1,
                'num_leaves': 15,
                'verbose': -1,
                'force_row_wise': True
            }
            
            model = lgb.train(params, train_data, num_boost_round=50)
            preds = model.predict(X_val)
            acc = accuracy_score(y_val, np.argmax(preds, axis=1))
            fold_accs.append(acc)
        
        random_accuracies.append(np.mean(fold_accs))
    
    avg_random_acc = np.mean(random_accuracies)
    majority_baseline = max(sum(y == 0), sum(y == 1), sum(y == 2)) / len(y)
    threshold = majority_baseline + 0.05
    
    status = "PASS" if avg_random_acc < threshold else "FAIL - POTENTIAL LEAKAGE"
    
    logger.info(f"Random Label Accuracy: {avg_random_acc:.3f}")
    logger.info(f"Threshold: {threshold:.3f} (majority baseline {majority_baseline:.3f} + 0.05)")
    logger.info(f"Status: {status}")
    
    return {
        'random_accuracy': avg_random_acc,
        'threshold': threshold,
        'status': status
    }


def train_two_tier_ensemble(df: pd.DataFrame) -> Dict:
    """Train a two-tier ensemble: lite model (all matches) + premium model (odds matches)
    
    The lite model uses only historical features (high coverage, no odds required).
    The premium model uses all non-sparse features including odds (higher accuracy when available).
    """
    
    logger.info("\n" + "="*60)
    logger.info("TRAINING TWO-TIER ENSEMBLE")
    logger.info("="*60)
    
    # Define feature tiers
    # Lite features: form, h2h, advanced stats, context (NO ODDS - must work without odds data)
    lite_feature_names = (
        UnifiedV2FeatureBuilder.FORM_FEATURES +
        UnifiedV2FeatureBuilder.H2H_FEATURES +
        UnifiedV2FeatureBuilder.ADVANCED_STATS_FEATURES +
        UnifiedV2FeatureBuilder.CONTEXT_FEATURES +
        UnifiedV2FeatureBuilder.ECE_FEATURES +
        UnifiedV2FeatureBuilder.HISTORICAL_FLAGS
    )
    # Filter to columns that exist in dataframe and are not sparse
    sparse_features = UnifiedV2FeatureBuilder.SPARSE_FEATURES
    lite_features = [f for f in lite_feature_names if f in df.columns and f not in sparse_features]
    
    # Premium features: all non-sparse features including odds
    all_feature_cols = [c for c in df.columns if c not in ['match_id', 'outcome', 'kickoff']]
    premium_features = [c for c in all_feature_cols if c not in sparse_features]
    
    # Split data: matches with odds vs without
    has_odds = df['has_odds'] == 1 if 'has_odds' in df.columns else df['p_last_home'] > 0
    df_with_odds = df[has_odds].copy()
    df_all = df.copy()
    
    logger.info(f"Total matches: {len(df_all)}")
    logger.info(f"Matches with odds (premium): {len(df_with_odds)}")
    logger.info(f"Lite features: {len(lite_features)}")
    logger.info(f"Premium features: {len(premium_features)}")
    
    # Train lite model on all matches using ONLY lite features (no odds)
    logger.info("\n--- LITE MODEL (All Matches, No Odds Features) ---")
    df_lite = df_all[['match_id', 'outcome', 'kickoff'] + lite_features].copy()
    lite_result = _train_model_on_features(df_lite, lite_features, n_splits=5)
    logger.info(f"Lite accuracy: {lite_result['oof_metrics']['accuracy_3way']:.3f}")
    
    # Train premium model on matches WITH odds using all premium features
    premium_result = None
    if len(df_with_odds) >= 200:
        logger.info("\n--- PREMIUM MODEL (Odds Matches, All Features) ---")
        df_premium = df_with_odds[['match_id', 'outcome', 'kickoff'] + premium_features].copy()
        premium_result = _train_model_on_features(df_premium, premium_features, n_splits=5)
        logger.info(f"Premium accuracy: {premium_result['oof_metrics']['accuracy_3way']:.3f}")
    else:
        logger.warning(f"Not enough odds matches for premium model ({len(df_with_odds)} < 200)")
    
    return {
        'lite': lite_result,
        'premium': premium_result,
        'lite_features': lite_features,
        'premium_features': premium_features,
        'summary': {
            'lite_accuracy': lite_result['oof_metrics']['accuracy_3way'],
            'lite_samples': lite_result['oof_metrics']['n_samples'],
            'premium_accuracy': premium_result['oof_metrics']['accuracy_3way'] if premium_result else None,
            'premium_samples': premium_result['oof_metrics']['n_samples'] if premium_result else 0
        }
    }


def _train_model_on_features(df: pd.DataFrame, feature_cols: List[str], n_splits: int = 5) -> Dict:
    """Train LightGBM model on specific feature columns
    
    This ensures exact feature order is preserved for inference.
    """
    
    X = df[feature_cols].fillna(0).values
    
    outcome_map = {'H': 0, 'D': 1, 'A': 2}
    y = df['outcome'].map(outcome_map).values
    
    logger.info(f"Training with {len(feature_cols)} features, {len(y)} samples")
    logger.info(f"Class distribution: H={sum(y==0)}, D={sum(y==1)}, A={sum(y==2)}")
    
    params = {
        'objective': 'multiclass',
        'num_class': 3,
        'metric': 'multi_logloss',
        'boosting_type': 'gbdt',
        'learning_rate': 0.03,
        'num_leaves': 31,
        'max_depth': 6,
        'min_data_in_leaf': 20,
        'feature_fraction': 0.8,
        'bagging_fraction': 0.8,
        'bagging_freq': 5,
        'lambda_l1': 0.1,
        'lambda_l2': 0.1,
        'verbose': -1,
        'force_row_wise': True,
        'seed': 42
    }
    
    n_splits = min(n_splits, len(y) // 50)
    if n_splits < 2:
        n_splits = 2
    
    gap_size = max(20, len(y) // 50)
    tscv = TimeSeriesSplit(n_splits=n_splits, gap=gap_size)
    
    models = []
    oof_preds = np.zeros((len(y), 3))
    oof_mask = np.zeros(len(y), dtype=bool)
    fold_metrics = []
    
    for fold, (train_idx, val_idx) in enumerate(tscv.split(X)):
        logger.info(f"--- Fold {fold + 1}/{n_splits} ---")
        
        X_train, X_val = X[train_idx], X[val_idx]
        y_train, y_val = y[train_idx], y[val_idx]
        
        train_data = lgb.Dataset(X_train, label=y_train)
        val_data = lgb.Dataset(X_val, label=y_val, reference=train_data)
        
        model = lgb.train(
            params,
            train_data,
            num_boost_round=2000,
            valid_sets=[train_data, val_data],
            valid_names=['train', 'valid'],
            callbacks=[
                lgb.early_stopping(stopping_rounds=100),
                lgb.log_evaluation(period=200)
            ]
        )
        
        val_preds = model.predict(X_val, num_iteration=model.best_iteration)
        oof_preds[val_idx] = val_preds
        oof_mask[val_idx] = True
        
        val_pred_labels = np.argmax(val_preds, axis=1)
        fold_acc = accuracy_score(y_val, val_pred_labels)
        fold_logloss = log_loss(y_val, val_preds)
        
        fold_metrics.append({
            'fold': fold + 1,
            'accuracy': fold_acc,
            'logloss': fold_logloss
        })
        
        logger.info(f"Fold {fold + 1}: Accuracy={fold_acc:.3f}, LogLoss={fold_logloss:.4f}")
        models.append(model)
    
    y_valid = y[oof_mask]
    preds_valid = oof_preds[oof_mask]
    
    oof_accuracy = accuracy_score(y_valid, np.argmax(preds_valid, axis=1))
    oof_logloss = log_loss(y_valid, preds_valid)
    
    brier_components = []
    for i, cls in enumerate([0, 1, 2]):
        y_binary = (y_valid == cls).astype(float)
        pred_probs = preds_valid[:, i]
        brier_components.append(np.mean((y_binary - pred_probs) ** 2))
    oof_brier = np.mean(brier_components)
    
    # Feature importance
    feature_importance = []
    for i, col in enumerate(feature_cols):
        avg_importance = np.mean([m.feature_importance()[i] for m in models])
        feature_importance.append({'feature': col, 'importance': avg_importance})
    feature_importance.sort(key=lambda x: x['importance'], reverse=True)
    
    return {
        'models': models,
        'feature_cols': feature_cols,  # Exact order preserved for inference
        'oof_metrics': {
            'accuracy_3way': oof_accuracy,
            'logloss': oof_logloss,
            'brier_score': oof_brier,
            'n_samples': len(y_valid),
            'n_folds': n_splits
        },
        'fold_metrics': fold_metrics,
        'feature_importance': feature_importance,
        'params': params
    }


def save_model(results: Dict, feature_cols: List[str]):
    """Save trained model and metadata"""
    
    model_path = OUTPUT_DIR / "lgbm_ensemble.pkl"
    with open(model_path, "wb") as f:
        pickle.dump(results['models'], f)
    
    features_path = OUTPUT_DIR / "features.json"
    with open(features_path, "w") as f:
        json.dump(feature_cols, f, indent=2)
    
    metadata = {
        'model_type': 'Unified_V2_LightGBM',
        'trained_at': datetime.now(timezone.utc).isoformat(),
        'n_features': len(feature_cols),
        'oof_metrics': results['oof_metrics'],
        'fold_metrics': results['fold_metrics'],
        'feature_importance': results['feature_importance'][:20],
        'params': results['params']
    }
    
    metadata_path = OUTPUT_DIR / "metadata.json"
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2)
    
    logger.info(f"\nModel saved to {OUTPUT_DIR}/")
    logger.info(f"  - lgbm_ensemble.pkl ({len(results['models'])} models)")
    logger.info(f"  - features.json ({len(feature_cols)} features)")
    logger.info(f"  - metadata.json")


def save_two_tier_model(results: Dict):
    """Save two-tier ensemble model"""
    
    output_dir = OUTPUT_DIR / "two_tier"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Save lite model
    lite_path = output_dir / "lite_ensemble.pkl"
    with open(lite_path, "wb") as f:
        pickle.dump(results['lite']['models'], f)
    
    lite_features_path = output_dir / "lite_features.json"
    with open(lite_features_path, "w") as f:
        json.dump(results['lite_features'], f, indent=2)
    
    # Save premium model if available
    if results['premium']:
        premium_path = output_dir / "premium_ensemble.pkl"
        with open(premium_path, "wb") as f:
            pickle.dump(results['premium']['models'], f)
        
        premium_features_path = output_dir / "premium_features.json"
        with open(premium_features_path, "w") as f:
            json.dump(results['premium_features'], f, indent=2)
    
    # Save metadata
    metadata = {
        'model_type': 'Two_Tier_Ensemble',
        'trained_at': datetime.now(timezone.utc).isoformat(),
        'lite': {
            'n_features': len(results['lite_features']),
            'accuracy': results['summary']['lite_accuracy'],
            'n_samples': results['summary']['lite_samples']
        },
        'premium': {
            'n_features': len(results['premium_features']),
            'accuracy': results['summary']['premium_accuracy'],
            'n_samples': results['summary']['premium_samples']
        } if results['premium'] else None
    }
    
    metadata_path = output_dir / "metadata.json"
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2)
    
    logger.info(f"\nTwo-tier model saved to {output_dir}/")
    logger.info(f"  - lite_ensemble.pkl")
    logger.info(f"  - lite_features.json ({len(results['lite_features'])} features)")
    if results['premium']:
        logger.info(f"  - premium_ensemble.pkl")
        logger.info(f"  - premium_features.json ({len(results['premium_features'])} features)")


def main(two_tier: bool = False, max_matches: int = None):
    """Main training pipeline
    
    Args:
        two_tier: If True, train separate lite + premium models
        max_matches: Limit number of matches (for testing)
    """
    
    logger.info("="*60)
    logger.info("UNIFIED V2 TRAINING - FILTERED & OPTIMIZED")
    logger.info("="*60)
    
    matches = get_trainable_matches()
    
    if max_matches:
        matches = matches[:max_matches]
    
    if len(matches) < 50:
        logger.error(f"Insufficient training data: {len(matches)} matches (need >= 50)")
        return
    
    df = build_training_dataset(matches)
    
    if len(df) < 50:
        logger.error(f"Insufficient valid samples: {len(df)} (need >= 50)")
        return
    
    if two_tier:
        # Train two-tier ensemble (lite + premium)
        results = train_two_tier_ensemble(df)
        
        # Sanity check on lite model
        feature_cols = results['lite']['feature_cols']
        sanity = random_label_sanity_check(df, feature_cols)
        
        if sanity['status'] == "PASS":
            save_two_tier_model(results)
            
            logger.info("\n" + "="*60)
            logger.info("TRAINING COMPLETE - TWO-TIER ENSEMBLE")
            logger.info("="*60)
            logger.info(f"Lite Accuracy: {results['summary']['lite_accuracy']*100:.1f}%")
            if results['premium']:
                logger.info(f"Premium Accuracy: {results['summary']['premium_accuracy']*100:.1f}%")
            logger.info(f"Sanity Check: {sanity['status']}")
        else:
            logger.error("SANITY CHECK FAILED - Model not saved")
    else:
        # Standard single model training with sparse features excluded
        results = train_unified_v2_model(df, exclude_sparse=True)
        
        feature_cols = results['feature_cols']
        sanity = random_label_sanity_check(df, feature_cols)
        
        if sanity['status'] == "PASS":
            save_model(results, feature_cols)
            
            logger.info("\n" + "="*60)
            logger.info("TRAINING COMPLETE - UNIFIED V2 MODEL")
            logger.info("="*60)
            logger.info(f"Accuracy: {results['oof_metrics']['accuracy_3way']*100:.1f}%")
            logger.info(f"LogLoss: {results['oof_metrics']['logloss']:.4f}")
            logger.info(f"Features: {len(feature_cols)}")
            logger.info(f"Samples: {results['oof_metrics']['n_samples']}")
            logger.info(f"Sanity Check: {sanity['status']}")
        else:
            logger.error("SANITY CHECK FAILED - Model not saved")
            logger.error("Investigate potential data leakage before proceeding")


if __name__ == "__main__":
    main()
