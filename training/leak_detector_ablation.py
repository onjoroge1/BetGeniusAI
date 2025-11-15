#!/usr/bin/env python3
"""
Systematic Feature Ablation Test
Pinpoints which feature combinations cause leakage
"""
import os
os.environ['LD_LIBRARY_PATH'] = "/nix/store/xvzz97yk73hw03v5dhhz3j47ggwf1yq1-gcc-13.2.0-lib/lib"

import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.model_selection import TimeSeriesSplit
from datetime import datetime, timedelta
import sys
sys.path.append('.')
from features.v2_feature_builder import get_v2_feature_builder
from features.v2_feature_builder_transformed import V2FeatureBuilderTransformed

def get_feature_builder(use_transformed=False):
    """Factory: select original or transformed builder"""
    if use_transformed:
        print("🔄 Using TRANSFORMED feature builder (leak-resistant)")
        return V2FeatureBuilderTransformed()
    else:
        print("📊 Using ORIGINAL feature builder")
        return get_v2_feature_builder()

# Feature group definitions
# Note: schedule group deprecated (duplicates), context uses transformed features if enabled
FEATURE_GROUPS_ORIGINAL = {
    'odds': [
        'p_last_home', 'p_last_draw', 'p_last_away',
        'p_open_home', 'p_open_draw', 'p_open_away',
        'dispersion_home', 'dispersion_draw', 'dispersion_away',
        'book_dispersion', 'volatility_home', 'volatility_draw', 'volatility_away',
        'num_books_last', 'num_snapshots', 'coverage_hours',
        'market_entropy', 'favorite_margin'
    ],
    'elo': ['home_elo', 'away_elo', 'elo_diff'],
    'form': [
        'form_home_points', 'form_away_points',
        'form_home_goals_scored', 'form_away_goals_scored',
        'form_home_goals_conceded', 'form_away_goals_conceded'
    ],
    'home_adv': ['home_advantage_home', 'home_advantage_away'],
    'h2h': ['h2h_home_wins', 'h2h_draws', 'h2h_away_wins'],
    'advanced': [
        'home_shots', 'away_shots',
        'home_shots_on_target', 'away_shots_on_target',
        'home_corners', 'away_corners',
        'home_yellows', 'away_yellows'
    ],
    'context': [
        'rest_days_home', 'rest_days_away',
        'schedule_congestion_home_7d', 'schedule_congestion_away_7d'
    ],
    'drift': ['prob_drift_home', 'prob_drift_draw', 'prob_drift_away', 'drift_magnitude']
}

FEATURE_GROUPS_TRANSFORMED = {
    'odds': FEATURE_GROUPS_ORIGINAL['odds'],
    'elo': FEATURE_GROUPS_ORIGINAL['elo'],
    'form': FEATURE_GROUPS_ORIGINAL['form'],
    'home_adv': FEATURE_GROUPS_ORIGINAL['home_adv'],
    'h2h': FEATURE_GROUPS_ORIGINAL['h2h'],
    'advanced': FEATURE_GROUPS_ORIGINAL['advanced'],
    'context_transformed': ['rest_advantage', 'congestion_ratio'],  # 4 raw → 2 transformed
    'drift': FEATURE_GROUPS_ORIGINAL['drift']
}

def test_feature_combination(X, y, feature_names, test_name):
    """Test a specific feature combination for leakage"""
    print(f"\n{'='*60}")
    print(f"Testing: {test_name}")
    print(f"Features: {len(feature_names)} ({', '.join(list(FEATURE_GROUPS.keys()) if '+' in test_name else [test_name])})")
    print(f"{'='*60}")
    
    # Create random labels (global, reused across folds)
    np.random.seed(42)
    y_random = np.random.permutation(y)
    
    # TimeSeriesSplit with embargo
    tscv = TimeSeriesSplit(n_splits=5)
    random_accs = []
    
    for fold, (train_idx, val_idx) in enumerate(tscv.split(X)):
        # Apply 7-day embargo
        last_train_date = X.iloc[train_idx]['match_date'].max()
        embargo_cutoff = last_train_date + timedelta(days=7)
        val_idx_filtered = [i for i in val_idx if X.iloc[i]['match_date'] >= embargo_cutoff]
        
        if len(val_idx_filtered) < 10:
            continue
            
        X_train = X.iloc[train_idx][feature_names]
        y_train_random = y_random[train_idx]
        X_val = X.iloc[val_idx_filtered][feature_names]
        y_val_random = y_random[val_idx_filtered]
        
        # Train on random labels
        train_data = lgb.Dataset(X_train, label=y_train_random)
        params = {
            'objective': 'multiclass',
            'num_class': 3,
            'num_leaves': 15,
            'learning_rate': 0.05,
            'feature_fraction': 0.8,
            'verbosity': -1
        }
        
        model = lgb.train(
            params,
            train_data,
            num_boost_round=50,
            callbacks=[lgb.log_evaluation(0)]
        )
        
        # Predict and measure accuracy
        preds = model.predict(X_val)
        pred_classes = np.argmax(preds, axis=1)
        acc = (pred_classes == y_val_random).mean()
        random_accs.append(acc)
    
    mean_acc = np.mean(random_accs)
    status = "✅ CLEAN" if mean_acc < 0.40 else ("⚠️  BORDERLINE" if mean_acc < 0.42 else "❌ LEAKY")
    
    print(f"Random label accuracy: {mean_acc:.3f} {status}")
    print(f"Expected: ~0.333 (random guess)")
    print(f"Threshold: < 0.40 = clean, 0.40-0.42 = borderline, > 0.42 = leaky")
    
    return {
        'test_name': test_name,
        'n_features': len(feature_names),
        'random_acc': mean_acc,
        'status': status
    }

def main():
    """Run systematic ablation tests"""
    print("="*80)
    print("SYSTEMATIC FEATURE ABLATION TEST")
    print("Goal: Pinpoint which feature combinations cause leakage")
    print("="*80)
    
    # Check if using transformed features
    use_transformed = os.getenv("V2_USE_TRANSFORMED", "0") == "1"
    FEATURE_GROUPS = FEATURE_GROUPS_TRANSFORMED if use_transformed else FEATURE_GROUPS_ORIGINAL
    
    print(f"\nMode: {'TRANSFORMED (leak-resistant)' if use_transformed else 'ORIGINAL'}")
    print(f"Feature groups: {list(FEATURE_GROUPS.keys())}")
    
    # Load data
    print("\nLoading training data...")
    builder = get_feature_builder(use_transformed=use_transformed)
    
    # Get recent matches (Aug-Nov 2025, same as training)
    from sqlalchemy import create_engine, text
    engine = create_engine(os.getenv('DATABASE_URL'))
    
    query = text("""
        SELECT match_id, match_date, outcome
        FROM training_matches
        WHERE match_date >= '2025-08-01'
          AND match_date < '2025-11-15'
          AND outcome IN ('Home', 'Draw', 'Away')
        ORDER BY match_date
        LIMIT 1000
    """)
    
    with engine.connect() as conn:
        matches = pd.read_sql(query, conn)
    
    print(f"Loaded {len(matches)} matches")
    
    # Build all features
    print("Building features (this may take 5-10 minutes)...")
    all_features = []
    labels = []
    valid_matches = []
    
    for idx, row in matches.iterrows():
        if idx % 100 == 0:
            print(f"  Progress: {idx}/{len(matches)}")
        
        try:
            cutoff = row['match_date'] - timedelta(hours=1)
            features = builder.build_features(row['match_id'], cutoff)
            features['match_date'] = row['match_date']
            all_features.append(features)
            
            # Encode labels
            label_map = {'Home': 0, 'Draw': 1, 'Away': 2}
            labels.append(label_map[row['outcome']])
            valid_matches.append(row['match_id'])
        except Exception as e:
            continue
    
    X = pd.DataFrame(all_features)
    y = np.array(labels)
    
    print(f"Built features for {len(X)} matches")
    
    # Test combinations
    results = []
    
    # Test 1: Baseline (odds only)
    print("\n" + "="*80)
    print("PHASE 1: BASELINE TESTS")
    print("="*80)
    
    results.append(test_feature_combination(
        X, y, FEATURE_GROUPS['odds'], "1. Odds Only (Baseline)"
    ))
    
    # Test 2: Odds + Drift
    drift_features = FEATURE_GROUPS['odds'] + FEATURE_GROUPS['drift']
    results.append(test_feature_combination(
        X, y, drift_features, "2. Odds + Drift"
    ))
    
    # Test 3: Odds + ELO
    print("\n" + "="*80)
    print("PHASE 2: TEAM INTELLIGENCE TESTS")
    print("="*80)
    
    elo_features = FEATURE_GROUPS['odds'] + FEATURE_GROUPS['elo']
    results.append(test_feature_combination(
        X, y, elo_features, "3. Odds + ELO"
    ))
    
    # Test 4: Odds + Form
    form_features = FEATURE_GROUPS['odds'] + FEATURE_GROUPS['form']
    results.append(test_feature_combination(
        X, y, form_features, "4. Odds + Form"
    ))
    
    # Test 5: Odds + H2H
    h2h_features = FEATURE_GROUPS['odds'] + FEATURE_GROUPS['h2h']
    results.append(test_feature_combination(
        X, y, h2h_features, "5. Odds + H2H"
    ))
    
    # Test 6: CRITICAL - Time-based features
    print("\n" + "="*80)
    print("PHASE 3: TIME-BASED TESTS (CRITICAL)")
    print("="*80)
    
    if use_transformed:
        # Transformed mode: test context_transformed features
        print("Testing TRANSFORMED context features (leak-resistant)...")
        
        context_trans_features = FEATURE_GROUPS['odds'] + FEATURE_GROUPS['context_transformed']
        results.append(test_feature_combination(
            X, y, context_trans_features, "6. Odds + Context_Transformed (2 ratios)"
        ))
    else:
        # Original mode: test schedule + context (known leaky)
        # Test 7: Odds + Schedule
        if 'schedule' in FEATURE_GROUPS:
            schedule_features = FEATURE_GROUPS['odds'] + FEATURE_GROUPS['schedule']
            results.append(test_feature_combination(
                X, y, schedule_features, "6. Odds + Schedule (SUSPECTED)"
            ))
        
        # Test 8: Odds + Context
        context_features = FEATURE_GROUPS['odds'] + FEATURE_GROUPS['context']
        results.append(test_feature_combination(
            X, y, context_features, "7. Odds + Context (SUSPECTED)"
        ))
        
        # Test 9: Odds + Schedule + Context (CRITICAL)
        if 'schedule' in FEATURE_GROUPS:
            time_features = FEATURE_GROUPS['odds'] + FEATURE_GROUPS['schedule'] + FEATURE_GROUPS['context']
            results.append(test_feature_combination(
                X, y, time_features, "8. Odds + Schedule + Context (HIGH RISK)"
            ))
    
    # Test 10: Team features combined
    print("\n" + "="*80)
    print("PHASE 4: INTERACTION TESTS")
    print("="*80)
    
    team_features = (FEATURE_GROUPS['odds'] + FEATURE_GROUPS['elo'] + 
                     FEATURE_GROUPS['form'] + FEATURE_GROUPS['h2h'])
    results.append(test_feature_combination(
        X, y, team_features, "9. Odds + All Team Features"
    ))
    
    # Test 11: All features (replication)
    all_features_list = []
    for group in FEATURE_GROUPS.values():
        all_features_list.extend(group)
    
    test_name = f"10. ALL {len(all_features_list)} FEATURES ({'Transformed' if use_transformed else 'Original'})"
    results.append(test_feature_combination(
        X, y, all_features_list, test_name
    ))
    
    # Summary table
    print("\n" + "="*80)
    print("FINAL RESULTS SUMMARY")
    print("="*80)
    
    print("\n{:<40} {:>12} {:>12} {:>15}".format("Test", "Features", "Random Acc", "Status"))
    print("-" * 80)
    
    for r in results:
        print("{:<40} {:>12} {:>12.3f} {:>15}".format(
            r['test_name'][:40], r['n_features'], r['random_acc'], r['status']
        ))
    
    print("\n" + "="*80)
    print("DIAGNOSIS")
    print("="*80)
    
    # Identify leak source
    leaky_tests = [r for r in results if 'LEAKY' in r['status']]
    
    if not leaky_tests:
        print("✅ NO LEAK DETECTED - All feature combinations pass!")
        print("   → Training sanity check may have implementation bug")
    else:
        print(f"❌ LEAK DETECTED in {len(leaky_tests)} test(s):")
        for r in leaky_tests:
            print(f"   - {r['test_name']}: {r['random_acc']:.3f}")
        
        # Identify which features cause leak
        if any('Schedule' in r['test_name'] or 'Context' in r['test_name'] 
               for r in leaky_tests):
            print("\n🎯 PRIMARY SUSPECT: Time-based features (schedule/context)")
            print("   → rest_days_*, days_since_*, schedule_congestion_*")
            print("   → RECOMMENDATION: Remove or bin these features")
        elif any('Form' in r['test_name'] or 'H2H' in r['test_name'] 
                 for r in leaky_tests):
            print("\n🎯 PRIMARY SUSPECT: Team identity features (form/h2h)")
            print("   → Combined with other features, creates match fingerprint")
            print("   → RECOMMENDATION: Reduce feature granularity or remove interactions")
    
    print("\n" + "="*80)
    print("NEXT STEPS")
    print("="*80)
    print("1. Review which tests failed (random_acc > 0.40)")
    print("2. Remove or transform the leaky feature groups")
    print("3. Retrain with clean feature set (target: 46-48 features)")
    print("4. Verify all sanity checks pass (<0.40)")
    print("5. Apply Step A optimizations (hyperparams, class balance)")
    print("6. Deploy clean V2.1 to production")

if __name__ == "__main__":
    main()
