#!/usr/bin/env python3
"""
LEAK DETECTOR V2: Exact Training Setup Mirror

This version uses the EXACT same data loading, CV strategy, and sanity checks
as train_v2_no_leakage.py to eliminate test inconsistencies.
"""

import os, sys, numpy as np, pandas as pd
from datetime import timedelta
from sqlalchemy import create_engine, text
from sklearn.metrics import accuracy_score, log_loss
import lightgbm as lgb

sys.path.append('.')
from features.v2_feature_builder import get_v2_feature_builder

# Copied from train_v2_no_leakage.py
class PurgedTimeSeriesSplit:
    """Time-based CV with embargo to prevent leakage"""
    
    def __init__(self, n_splits=5, embargo_days=7):
        self.n_splits = n_splits
        self.embargo_days = embargo_days
    
    def split(self, X, y=None, groups=None):
        if groups is None:
            raise ValueError("groups (match_date) required")
        
        dates = pd.Series(pd.to_datetime(groups))
        sorted_indices = np.argsort(dates.values)
        fold_size = len(sorted_indices) // (self.n_splits + 1)
        
        for i in range(self.n_splits):
            train_end_idx = (i + 1) * fold_size
            train_indices = sorted_indices[:train_end_idx]
            valid_start_idx = train_end_idx
            valid_end_idx = min(valid_start_idx + fold_size, len(sorted_indices))
            valid_indices = sorted_indices[valid_start_idx:valid_end_idx]
            
            if len(valid_indices) > 0:
                valid_start_date = dates.iloc[valid_indices[0]]
                embargo_cutoff = valid_start_date - timedelta(days=self.embargo_days)
                train_dates = dates.iloc[train_indices]
                mask = (train_dates <= embargo_cutoff).values
                train_indices = train_indices[mask]
            
            if len(train_indices) > 0 and len(valid_indices) > 0:
                yield train_indices, valid_indices

# Define feature groups
FEATURE_GROUPS = {
    'odds': [
        'p_open_home', 'p_open_draw', 'p_open_away',
        'p_last_home', 'p_last_draw', 'p_last_away',
        'num_books_last', 'book_dispersion', 'market_entropy',
        'dispersion_home', 'dispersion_draw', 'dispersion_away',
        'favorite_margin',
        'prob_drift_home', 'prob_drift_draw', 'prob_drift_away', 'drift_magnitude',
    ],
    'team_context': [
        'home_elo', 'away_elo', 'elo_diff',
        'home_form_points', 'away_form_points',
        'home_form_goals_scored', 'home_form_goals_conceded',
        'away_form_goals_scored', 'away_form_goals_conceded',
        'h2h_home_wins', 'h2h_draws', 'h2h_away_wins',
        'days_since_home_last_match', 'days_since_away_last_match',
        'rest_days_home', 'rest_days_away',
        'schedule_congestion_home_7d', 'schedule_congestion_away_7d',
    ],
}

print("="*70)
print("  LEAK DETECTOR V2: Training Setup Mirror")
print("="*70)
print("Using EXACT same setup as train_v2_no_leakage.py:")
print("  - Same query (recent 2025 matches)")
print("  - Same CV (5-fold TimeSeriesSplit + 7-day embargo)")
print("  - Same random-label test logic\n")

# Load data - EXACT SAME QUERY as train_v2_no_leakage.py
database_url = os.getenv('DATABASE_URL')
engine = create_engine(database_url)

query = text("""
    SELECT 
        tm.match_id,
        tm.match_date,
        tm.outcome
    FROM training_matches tm
    INNER JOIN match_context mc ON tm.match_id = mc.match_id
    INNER JOIN odds_real_consensus orc ON tm.match_id = orc.match_id
    WHERE tm.match_date >= '2020-01-01'
      AND tm.match_date < '2025-12-31'
      AND tm.match_date IS NOT NULL
      AND tm.outcome IS NOT NULL
      AND tm.outcome IN ('H', 'D', 'A', 'Home', 'Draw', 'Away')
    ORDER BY RANDOM()
    LIMIT 500
""")

with engine.connect() as conn:
    matches = pd.read_sql(query, conn)

matches['outcome'] = matches['outcome'].map({'Home': 'H', 'Draw': 'D', 'Away': 'A', 
                                              'H': 'H', 'D': 'D', 'A': 'A'})
print(f"✅ Loaded {len(matches)} matches")
print(f"   Date range: {matches['match_date'].min()} to {matches['match_date'].max()}\n")

# Build ALL features
print("🔨 Building ALL 50 features...")
builder = get_v2_feature_builder()
features_list = []

for idx, row in matches.iterrows():
    try:
        features = builder.build_features(row['match_id'], 
                                         cutoff_time=pd.to_datetime(row['match_date']))
        features['outcome'] = row['outcome']
        features['match_date'] = row['match_date']
        features_list.append(features)
        
        if (idx + 1) % 50 == 0:
            print(f"   {idx+1}/{len(matches)}", flush=True)
    except:
        continue

df = pd.DataFrame(features_list)
print(f"✅ Built {len(df)} vectors with {len(df.columns)-2} features\n")

if len(df) < 100:
    print("❌ Insufficient data")
    sys.exit(1)

# Prepare data
y = np.array([{'H': 0, 'D': 1, 'A': 2}[l] for l in df['outcome'].values])
dates = df['match_date'].values

# Test function
def test_features_with_random_labels(feature_cols, group_name):
    """Test with EXACT same logic as train_v2_no_leakage.py sanity check"""
    X = df[feature_cols].values
    
    # Global permutation (same as training)
    np.random.seed(42)
    y_random = np.random.permutation(y)
    
    # Use TimeSeriesSplit like training
    cv = PurgedTimeSeriesSplit(n_splits=3, embargo_days=7)  # 3 folds for speed
    
    accuracies = []
    logloss_scores = []
    
    for fold_idx, (train_idx, valid_idx) in enumerate(cv.split(X, y_random, groups=dates)):
        X_train, X_valid = X[train_idx], X[valid_idx]
        y_train, y_valid = y_random[train_idx], y[valid_idx]  # Use REAL y for validation!
        
        model = lgb.train(
            {'objective': 'multiclass', 'num_class': 3, 'verbosity': -1, 'num_leaves': 15},
            lgb.Dataset(X_train, label=y_train),
            num_boost_round=30,
            callbacks=[lgb.log_evaluation(0)]
        )
        
        y_pred = model.predict(X_valid)
        acc = accuracy_score(y_valid, np.argmax(y_pred, axis=1))
        ll = log_loss(y_valid, y_pred)
        
        accuracies.append(acc)
        logloss_scores.append(ll)
    
    mean_acc = np.mean(accuracies)
    mean_ll = np.mean(logloss_scores)
    verdict = "✅ CLEAN" if mean_acc < 0.40 else "❌ LEAKY"
    
    print(f"\n{group_name} ({len(feature_cols)} features):")
    print(f"  Mean CV Accuracy: {mean_acc:.3f} ({mean_acc*100:.1f}%)")
    print(f"  Mean LogLoss:     {mean_ll:.3f}")
    print(f"  Verdict:          {verdict}")
    
    return {'group': group_name, 'features': len(feature_cols), 
            'accuracy': mean_acc, 'logloss': mean_ll, 'verdict': verdict}

# Test each group
print("="*70)
print("TESTING FEATURE GROUPS (TimeSeriesSplit CV)")
print("="*70)

results = []

# Test odds-only
odds_features = [f for f in FEATURE_GROUPS['odds'] if f in df.columns]
if odds_features:
    results.append(test_features_with_random_labels(odds_features, 'ODDS ONLY'))

# Test team/context only
team_features = [f for f in FEATURE_GROUPS['team_context'] if f in df.columns]
if team_features:
    results.append(test_features_with_random_labels(team_features, 'TEAM/CONTEXT ONLY'))

# Test ALL 50 features (the critical test!)
all_features = [c for c in df.columns if c not in ['outcome', 'match_date']]
results.append(test_features_with_random_labels(all_features, 'ALL 50 FEATURES'))

# Summary
print("\n" + "="*70)
print("LEAK DETECTION SUMMARY (TimeSeriesSplit)")
print("="*70)

df_results = pd.DataFrame(results)
print("\nResults:")
for _, row in df_results.iterrows():
    print(f"  {row['group']:20s}: {row['accuracy']:.3f}  {row['verdict']}")

if df_results[df_results['accuracy'] >= 0.40].shape[0] > 0:
    print("\n⚠️  LEAKAGE DETECTED in one or more groups")
    print("\nDiagnostic:")
    if df_results[df_results['group'] == 'ODDS ONLY']['accuracy'].iloc[0] < 0.40:
        print("  • Odds features: CLEAN ✅")
    if df_results[df_results['group'] == 'TEAM/CONTEXT ONLY']['accuracy'].iloc[0] < 0.40:
        print("  • Team/context features: CLEAN ✅")
    if df_results[df_results['group'] == 'ALL 50 FEATURES']['accuracy'].iloc[0] >= 0.40:
        print("  • Combined features: LEAKY ❌")
        print("\n  → Likely an INTERACTION EFFECT or implicit ID creation")
        print("  → Investigate: Feature combinations that uniquely identify matches")
else:
    print("\n✅ ALL CLEAN! No leakage detected.")

print("\n" + "="*70)
print("COMPARISON WITH FULL TRAINING")
print("="*70)
print(f"This test: {df_results[df_results['group']=='ALL 50 FEATURES']['accuracy'].iloc[0]:.3f}")
print("Full training reports: 0.42-0.43")
print("\nIf these match → Real interaction leak")
print("If these differ → Test implementation bug in training")
