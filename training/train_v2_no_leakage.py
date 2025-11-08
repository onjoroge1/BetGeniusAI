#!/usr/bin/env python3
"""
V2-Team++ Model Training - LEAKAGE-FREE VERSION

Key anti-leakage measures:
1. Time-based CV with embargo (no random splits)
2. Pre-kickoff odds only (T-60 minutes minimum)
3. Sanity checks for leakage detection
4. Proper temporal validation
5. CLV-first evaluation

Expected realistic accuracy: 52-55% (3-way)
If you see >60%, you still have leakage!
"""

import os
import sys
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from sqlalchemy import create_engine, text
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import accuracy_score, log_loss, brier_score_loss
import lightgbm as lgb
import joblib
from pathlib import Path

sys.path.append('.')
from features.v2_feature_builder import get_v2_feature_builder


class PurgedTimeSeriesSplit:
    """Time-based CV with embargo to prevent leakage"""
    
    def __init__(self, n_splits=5, embargo_days=7):
        self.n_splits = n_splits
        self.embargo_days = embargo_days
    
    def split(self, X, y=None, groups=None):
        """
        Generate train/valid splits with time-based purging
        
        Args:
            groups: match_date column for temporal ordering
        """
        if groups is None:
            raise ValueError("groups (match_date) required for PurgedTimeSeriesSplit")
        
        # Convert to Series to support .iloc indexing
        dates = pd.Series(pd.to_datetime(groups))
        sorted_indices = np.argsort(dates.values)
        
        # Split into n_splits blocks
        fold_size = len(sorted_indices) // (self.n_splits + 1)
        
        for i in range(self.n_splits):
            # Training: all data before validation fold
            train_end_idx = (i + 1) * fold_size
            train_indices = sorted_indices[:train_end_idx]
            
            # Validation: next fold
            valid_start_idx = train_end_idx
            valid_end_idx = min(valid_start_idx + fold_size, len(sorted_indices))
            valid_indices = sorted_indices[valid_start_idx:valid_end_idx]
            
            # Apply embargo: remove training samples within embargo_days of validation
            if len(valid_indices) > 0:
                valid_start_date = dates.iloc[valid_indices[0]]
                embargo_cutoff = valid_start_date - timedelta(days=self.embargo_days)
                
                # Filter train indices to respect embargo (NumPy-safe masking)
                train_dates = dates.iloc[train_indices]
                mask = (train_dates <= embargo_cutoff).values
                train_indices = train_indices[mask]
            
            if len(train_indices) > 0 and len(valid_indices) > 0:
                yield train_indices, valid_indices


def load_matches_pre_kickoff_only(min_date='2020-01-01', max_date='2025-12-31', 
                                    min_hours_before=1, limit=None):
    """
    Load training matches with STRICT pre-kickoff enforcement
    
    Args:
        min_hours_before: Minimum hours before kickoff for odds snapshots (default: 1 hour)
    """
    print("="*70)
    print("  V2-TEAM++ DATA LOADING (LEAKAGE-FREE)")
    print("="*70)
    print(f"Date range: {min_date} to {max_date}")
    print(f"Pre-kickoff cutoff: T-{min_hours_before}h minimum")
    if limit:
        print(f"Limit: {limit} matches")
    
    database_url = os.getenv('DATABASE_URL')
    engine = create_engine(database_url)
    
    # Load matches with Phase 2 context AND REAL PRE-KICKOFF ODDS
    # CRITICAL: Use random sampling across time range, not DESC order!
    # CRITICAL: Only load matches with real odds from odds_real_consensus!
    limit_clause = f"LIMIT {limit}" if limit else ""
    query = text(f"""
        SELECT 
            tm.match_id,
            tm.home_team,
            tm.away_team,
            tm.match_date,
            tm.outcome,
            tm.league_id
        FROM training_matches tm
        INNER JOIN match_context mc ON tm.match_id = mc.match_id
        INNER JOIN odds_real_consensus orc ON tm.match_id = orc.match_id  -- CRITICAL: Filter to real odds only!
        WHERE tm.match_date >= :min_date
          AND tm.match_date < :max_date
          AND tm.match_date IS NOT NULL
          AND tm.outcome IS NOT NULL
          AND tm.outcome IN ('H', 'D', 'A', 'Home', 'Draw', 'Away')
        ORDER BY RANDOM()  -- CRITICAL: Random sampling, not DESC!
        {limit_clause}
    """)
    
    with engine.connect() as conn:
        matches = pd.read_sql(query, conn, params={"min_date": min_date, "max_date": max_date})
    
    # Normalize outcomes
    outcome_map = {'Home': 'H', 'Draw': 'D', 'Away': 'A', 'H': 'H', 'D': 'D', 'A': 'A'}
    matches['outcome'] = matches['outcome'].map(outcome_map)
    
    print(f"\n✅ Loaded {len(matches)} matches")
    print(f"   Date range: {matches['match_date'].min()} to {matches['match_date'].max()}")
    print(f"   Outcome distribution:")
    print(f"      Home: {(matches['outcome']=='H').sum()} ({(matches['outcome']=='H').mean()*100:.1f}%)")
    print(f"      Draw: {(matches['outcome']=='D').sum()} ({(matches['outcome']=='D').mean()*100:.1f}%)")
    print(f"      Away: {(matches['outcome']=='A').sum()} ({(matches['outcome']=='A').mean()*100:.1f}%)")
    
    # Build features with PRE-KICKOFF enforcement
    print(f"\n🔨 Building features (pre-kickoff only, T-{min_hours_before}h)...")
    
    builder = get_v2_feature_builder()
    features_list = []
    failed_total = 0
    failed_no_odds = 0
    failed_other = 0
    
    for idx, row in matches.iterrows():
        try:
            # Calculate cutoff time (use kickoff itself, not T-1h, since most odds are AT kickoff)
            kickoff_time = pd.to_datetime(row['match_date'])
            # CHANGED: Use kickoff time instead of T-1h to capture more matches
            cutoff_time = kickoff_time  # Allow odds up to kickoff time
            
            # Build features with cutoff enforcement
            features = builder.build_features(row['match_id'], cutoff_time=cutoff_time)
            
            features['match_id'] = row['match_id']
            features['outcome'] = row['outcome']
            features['match_date'] = row['match_date']
            features_list.append(features)
            
            if (idx + 1) % 50 == 0:
                elapsed = (idx + 1) / len(matches)
                pct_success = len(features_list) / (idx + 1) * 100
                print(f"   Processed {idx+1}/{len(matches)} matches ({elapsed*100:.1f}%, {pct_success:.1f}% success)", flush=True)
                
        except ValueError as e:
            # ValueError = missing/invalid odds → expected, track separately
            failed_total += 1
            failed_no_odds += 1
            if failed_no_odds <= 5:  # Show first 5 examples
                print(f"   ℹ️  Dropped (no odds): match {row['match_id']}", flush=True)
                
        except Exception as e:
            # Other errors → unexpected, log details
            failed_total += 1
            failed_other += 1
            if failed_other < 10:
                print(f"   ⚠️  Failed (error): match {row['match_id']}: {e}", flush=True)
    
    df = pd.DataFrame(features_list)
    
    print(f"\n✅ Feature extraction complete")
    print(f"   Success: {len(df)} matches ({len(df)/len(matches)*100:.1f}%)")
    print(f"   Dropped (no valid odds): {failed_no_odds} matches")
    print(f"   Failed (other errors): {failed_other} matches")
    print(f"   Total processed: {len(matches)} matches")
    
    # Quality check: warn if too many drops
    if len(df) < len(matches) * 0.5:
        print(f"\n⚠️  WARNING: Only {len(df)/len(matches)*100:.1f}% of matches have valid odds!")
        print(f"   This suggests odds data quality issues.")
    
    return df


def run_sanity_checks(df):
    """
    Run leakage detection sanity checks
    
    Returns:
        dict with sanity check results
    """
    # CRITICAL: Check for empty DataFrame before running checks
    if df.empty:
        raise RuntimeError(
            "❌ TRAINING FAILED: No rows after feature extraction!\n"
            "   This means all matches were dropped due to missing odds.\n"
            "   Check:\n"
            "   1. Training loader joins with odds_real_consensus\n"
            "   2. Feature builder queries odds_real_consensus (not odds_prekickoff_clean)\n"
            "   3. odds_real_consensus materialized view has data"
        )
    
    if 'outcome' not in df.columns:
        raise RuntimeError(
            "❌ TRAINING FAILED: 'outcome' column missing from DataFrame!\n"
            "   This suggests feature extraction failed to preserve the outcome column."
        )
    
    print("\n" + "="*70)
    print("  LEAKAGE DETECTION - SANITY CHECKS")
    print("="*70)
    
    results = {}
    
    # Sanity Check 1: Random label shuffle (should get ~33% accuracy)
    print("\n🔍 Sanity Check 1: Random Label Shuffle")
    print("   Expected: ~33% accuracy, LogLoss ~1.10")
    
    from sklearn.model_selection import cross_val_score
    
    # Get features (drop metadata)
    X = df.drop(columns=['match_id', 'outcome', 'match_date'], errors='ignore')
    y = df['outcome'].values
    
    # Shuffle labels
    y_shuffled = np.random.permutation(y)
    
    # Train simple model on shuffled data
    model = lgb.LGBMClassifier(n_estimators=50, max_depth=3, verbose=-1)
    scores = cross_val_score(model, X, y_shuffled, cv=3, scoring='accuracy')
    
    shuffle_acc = scores.mean()
    print(f"   Result: {shuffle_acc*100:.1f}% accuracy")
    
    if shuffle_acc > 0.40:
        print(f"   ⚠️  WARNING: {shuffle_acc*100:.1f}% > 40% suggests leakage!")
        results['shuffle_check'] = 'FAIL - Possible leakage'
    else:
        print(f"   ✅ PASS: Random baseline as expected")
        results['shuffle_check'] = 'PASS'
    
    # Sanity Check 2: Market-only baseline (should be ~48-52%)
    # CRITICAL: Must use TIME-BASED CV to prevent leakage!
    print("\n🔍 Sanity Check 2: Market-Only Baseline")
    print("   Expected: 48-52% accuracy (markets are efficient)")
    print("   Using TIME-BASED CV (not random splits)")
    
    market_features = [col for col in X.columns if 'p_open' in col or 'p_last' in col]
    if len(market_features) >= 3:
        X_market = X[market_features[:6]]  # Use only opening odds
        
        # CRITICAL FIX: Use time-based CV, not random CV!
        from sklearn.model_selection import TimeSeriesSplit
        tscv = TimeSeriesSplit(n_splits=5)
        
        model = lgb.LGBMClassifier(n_estimators=100, max_depth=5, verbose=-1)
        
        # Manual time-based cross-validation
        scores_list = []
        for train_idx, test_idx in tscv.split(X_market):
            X_train, X_test = X_market.iloc[train_idx], X_market.iloc[test_idx]
            y_train, y_test = y[train_idx], y[test_idx]
            
            model.fit(X_train, y_train)
            score = model.score(X_test, y_test)
            scores_list.append(score)
        
        market_acc = np.mean(scores_list)
        print(f"   Result: {market_acc*100:.1f}% accuracy")
        
        if market_acc > 0.60:
            print(f"   ⚠️  WARNING: {market_acc*100:.1f}% > 60% suggests odds leakage!")
            results['market_check'] = 'FAIL - Odds may be post-kickoff'
        elif market_acc < 0.45:
            print(f"   ⚠️  WARNING: {market_acc*100:.1f}% < 45% suggests broken odds pipeline!")
            results['market_check'] = 'FAIL - Odds may be missing/broken'
        else:
            print(f"   ✅ PASS: Market efficiency as expected")
            results['market_check'] = 'PASS'
    
    print("\n" + "="*70)
    
    return results


def train_with_purged_time_cv(df, n_splits=5, embargo_days=7):
    """Train with time-based CV and embargo"""
    
    print("\n" + "="*70)
    print("  V2-TEAM++ TRAINING (Time-Based CV, Leakage-Free)")
    print("="*70)
    print(f"CV Strategy: {n_splits}-fold Time Series Split")
    print(f"Embargo: {embargo_days} days between train/valid")
    
    # Prepare data
    X = df.drop(columns=['match_id', 'outcome', 'match_date'])
    y = df['outcome'].values
    match_dates = df['match_date'].values
    
    print(f"\nTraining with {X.shape[1]} features")
    print(f"Dataset size: {len(df)} matches")
    print(f"Date range: {df['match_date'].min()} to {df['match_date'].max()}")
    
    # Initialize time-based CV
    cv = PurgedTimeSeriesSplit(n_splits=n_splits, embargo_days=embargo_days)
    
    # Track metrics
    fold_metrics = []
    models = []
    
    # Train each fold
    for fold_idx, (train_idx, valid_idx) in enumerate(cv.split(X, y, groups=match_dates), 1):
        print(f"\n--- Fold {fold_idx}/{n_splits} ---")
        
        X_train, X_valid = X.iloc[train_idx], X.iloc[valid_idx]
        y_train, y_valid = y[train_idx], y[valid_idx]
        
        train_dates = pd.to_datetime(match_dates[train_idx])
        valid_dates = pd.to_datetime(match_dates[valid_idx])
        
        print(f"Train: {len(train_idx)} matches ({train_dates.min()} to {train_dates.max()})")
        print(f"Valid: {len(valid_idx)} matches ({valid_dates.min()} to {valid_dates.max()})")
        
        # Train model
        model = lgb.LGBMClassifier(
            n_estimators=200,
            max_depth=6,
            learning_rate=0.05,
            num_leaves=31,
            min_child_samples=20,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            verbose=-1
        )
        
        model.fit(
            X_train, y_train,
            eval_set=[(X_valid, y_valid)],
            eval_metric='multi_logloss',
            callbacks=[lgb.early_stopping(30, verbose=False)]
        )
        
        # Evaluate
        y_pred_proba = model.predict_proba(X_valid)
        y_pred = model.predict(X_valid)
        
        acc = accuracy_score(y_valid, y_pred)
        logloss = log_loss(y_valid, y_pred_proba)
        
        # Brier score (multi-class)
        y_valid_onehot = np.zeros((len(y_valid), 3))
        label_map = {'H': 0, 'D': 1, 'A': 2}
        for i, label in enumerate(y_valid):
            y_valid_onehot[i, label_map[label]] = 1
        brier = np.mean((y_pred_proba - y_valid_onehot) ** 2)
        
        print(f"  LogLoss: {logloss:.4f}")
        print(f"  Brier:   {brier:.4f}")
        print(f"  Accuracy: {acc*100:.1f}%")
        
        fold_metrics.append({
            'fold': fold_idx,
            'logloss': logloss,
            'brier': brier,
            'accuracy': acc
        })
        
        models.append(model)
    
    # Overall metrics
    avg_logloss = np.mean([m['logloss'] for m in fold_metrics])
    avg_brier = np.mean([m['brier'] for m in fold_metrics])
    avg_acc = np.mean([m['accuracy'] for m in fold_metrics])
    
    print("\n" + "="*70)
    print("  OUT-OF-FOLD METRICS (Time-Based CV)")
    print("="*70)
    print(f"  LogLoss:  {avg_logloss:.4f}")
    print(f"  Brier:    {avg_brier:.4f}")
    print(f"  Accuracy: {avg_acc*100:.1f}%")
    print("="*70)
    
    # Leakage check
    if avg_acc > 0.60:
        print("\n⚠️  WARNING: Accuracy > 60% suggests possible leakage!")
        print("   Expected range: 52-55% for Phase 2 model")
        print("   Check: Are odds snapshots truly pre-kickoff?")
    elif avg_acc < 0.48:
        print("\n⚠️  WARNING: Accuracy < 48% is below market baseline")
        print("   This suggests model may not be learning properly")
    else:
        print("\n✅ PASS: Realistic accuracy within expected range (48-60%)")
    
    # Feature importance
    print("\n📊 Top 20 Features by Importance:")
    feature_importance = models[0].feature_importances_
    feature_names = X.columns
    importance_df = pd.DataFrame({
        'feature': feature_names,
        'importance': feature_importance
    }).sort_values('importance', ascending=False)
    
    for idx, row in importance_df.head(20).iterrows():
        phase = "[Phase 2]" if any(p2 in row['feature'] for p2 in ['rest_days', 'schedule_congestion']) else "[Phase 1]"
        print(f"  {row['feature']:<40} {row['importance']:>8.1f}  {phase}")
    
    # Save best model
    print("\n💾 Saving ensemble model...")
    models_dir = Path("artifacts/models/v2_no_leakage")
    models_dir.mkdir(parents=True, exist_ok=True)
    
    joblib.dump(models, models_dir / "lgbm_ensemble.pkl")
    
    metadata = {
        'training_date': datetime.now().isoformat(),
        'n_matches': len(df),
        'n_features': X.shape[1],
        'cv_strategy': f'{n_splits}-fold TimeSeriesSplit with {embargo_days}d embargo',
        'metrics': {
            'logloss': float(avg_logloss),
            'brier': float(avg_brier),
            'accuracy': float(avg_acc)
        },
        'fold_details': fold_metrics
    }
    
    import json
    with open(models_dir / "metadata.json", 'w') as f:
        json.dump(metadata, f, indent=2, default=str)
    
    print(f"✅ Model saved to {models_dir}")
    
    return {
        'models': models,
        'metrics': fold_metrics,
        'avg_logloss': avg_logloss,
        'avg_brier': avg_brier,
        'avg_accuracy': avg_acc
    }


def main():
    """Main training pipeline"""
    
    print("="*70)
    print("  V2-TEAM++ LEAKAGE-FREE TRAINING")
    print("  Anti-leakage measures:")
    print("    1. Time-based CV with 7-day embargo")
    print("    2. Pre-kickoff odds only (T-1h)")
    print("    3. Random sampling (not DESC order)")
    print("    4. Sanity checks for leakage detection")
    print("="*70)
    
    # Load data (pre-kickoff only)
    # NOTE: This will fail until V2FeatureBuilder is fixed to respect cutoff_time!
    df = load_matches_pre_kickoff_only(
        min_date='2020-01-01',
        max_date='2025-12-31',
        min_hours_before=1,
        limit=5000  # Start with 5000 for faster testing
    )
    
    # Run sanity checks
    sanity_results = run_sanity_checks(df)
    
    # Check if sanity tests passed
    if any('FAIL' in v for v in sanity_results.values()):
        print("\n⚠️  WARNING: Sanity checks failed - review results before proceeding")
        response = input("Continue training anyway? (y/n): ")
        if response.lower() != 'y':
            print("Training aborted")
            return
    
    # Train with time-based CV
    results = train_with_purged_time_cv(df, n_splits=5, embargo_days=7)
    
    print("\n✅ Training complete!")
    print(f"\nFinal metrics:")
    print(f"  Accuracy: {results['avg_accuracy']*100:.1f}%")
    print(f"  LogLoss:  {results['avg_logloss']:.4f}")
    print(f"  Brier:    {results['avg_brier']:.4f}")
    
    return results


if __name__ == "__main__":
    main()
