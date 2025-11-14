#!/usr/bin/env python3
"""
LEAK DETECTOR: Isolate which feature groups cause leakage

Tests each feature group independently with random-label sanity check.
Expected: ~33% accuracy. If >40%, that group is leaky.
"""

import os, sys, numpy as np, pandas as pd
from sqlalchemy import create_engine, text
from sklearn.metrics import accuracy_score, log_loss
from sklearn.model_selection import train_test_split
import lightgbm as lgb

sys.path.append('.')
from features.v2_feature_builder import get_v2_feature_builder

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
    'elo': ['home_elo', 'away_elo', 'elo_diff'],
    'form': [
        'home_form_points', 'away_form_points',
        'home_form_goals_scored', 'home_form_goals_conceded',
        'away_form_goals_scored', 'away_form_goals_conceded',
    ],
    'h2h': ['h2h_home_wins', 'h2h_draws', 'h2h_away_wins'],
    'advanced': [
        'home_avg_shots', 'away_avg_shots',
        'home_avg_shots_on_target', 'away_avg_shots_on_target',
        'home_avg_corners', 'away_avg_corners',
        'home_avg_yellows', 'away_avg_yellows',
    ],
    'schedule': [
        'days_since_home_last_match', 'days_since_away_last_match',
        'rest_days_home', 'rest_days_away',
        'schedule_congestion_home_7d', 'schedule_congestion_away_7d',
    ],
}

print("="*70)
print("  LEAK DETECTOR: Feature Group Ablation")
print("="*70)
print("Testing each feature group with random-label sanity check")
print("Expected: ~33% accuracy. If >40%, group is LEAKY.\n")

# Load data
database_url = os.getenv('DATABASE_URL')
engine = create_engine(database_url)

query = text("""
    SELECT tm.match_id, tm.match_date, tm.outcome
    FROM training_matches tm
    INNER JOIN match_context mc ON tm.match_id = mc.match_id
    INNER JOIN odds_real_consensus orc ON tm.match_id = orc.match_id
    INNER JOIN odds_early_snapshot oes ON tm.match_id = oes.match_id
    WHERE tm.match_date >= '2020-01-01'
      AND tm.outcome IN ('Home', 'Draw', 'Away')
    ORDER BY RANDOM()
    LIMIT 300
""")

with engine.connect() as conn:
    matches = pd.read_sql(query, conn)

matches['outcome'] = matches['outcome'].map({'Home': 'H', 'Draw': 'D', 'Away': 'A'})
print(f"✅ Loaded {len(matches)} matches\n")

# Build ALL features
print("🔨 Building ALL features...")
builder = get_v2_feature_builder()
features_list = []

for idx, row in matches.iterrows():
    try:
        features = builder.build_features(row['match_id'], 
                                         cutoff_time=pd.to_datetime(row['match_date']))
        features['outcome'] = row['outcome']
        features_list.append(features)
        
        if (idx + 1) % 50 == 0:
            print(f"   {idx+1}/{len(matches)}", flush=True)
    except:
        continue

df = pd.DataFrame(features_list)
print(f"✅ Built {len(df)} vectors with {len(df.columns)-1} features\n")

if len(df) < 100:
    print("❌ Insufficient data")
    sys.exit(1)

# Test each group
y = np.array([{'H': 0, 'D': 1, 'A': 2}[l] for l in df['outcome'].values])
np.random.seed(42)
y_random = np.random.permutation(y)

print("="*70)
print("TESTING FEATURE GROUPS")
print("="*70)

results = []

for group_name, feature_list in FEATURE_GROUPS.items():
    # Get available features from this group
    available = [f for f in feature_list if f in df.columns]
    
    if len(available) == 0:
        print(f"\n❌ {group_name.upper()}: No features found")
        continue
    
    X = df[available].values
    
    # Split
    X_train, X_valid, y_train_rand, y_valid = train_test_split(
        X, y_random, test_size=0.25, shuffle=False
    )
    
    # Train with random labels
    try:
        model = lgb.train(
            {'objective': 'multiclass', 'num_class': 3, 'verbosity': -1, 'num_leaves': 15},
            lgb.Dataset(X_train, label=y_train_rand),
            num_boost_round=30,
            callbacks=[lgb.log_evaluation(0)]
        )
        
        y_pred = model.predict(X_valid)
        acc = accuracy_score(y_valid, np.argmax(y_pred, axis=1))
        ll = log_loss(y_valid, y_pred)
        
        verdict = "✅ CLEAN" if acc < 0.40 else "❌ LEAKY"
        
        print(f"\n{group_name.upper()} ({len(available)} features):")
        print(f"  Accuracy: {acc:.3f} ({acc*100:.1f}%)")
        print(f"  LogLoss:  {ll:.3f}")
        print(f"  Verdict:  {verdict}")
        
        results.append({
            'group': group_name,
            'features': len(available),
            'accuracy': acc,
            'logloss': ll,
            'verdict': verdict
        })
        
    except Exception as e:
        print(f"\n{group_name.upper()}: ERROR - {e}")

# Summary
print("\n" + "="*70)
print("LEAK DETECTION SUMMARY")
print("="*70)

df_results = pd.DataFrame(results)
df_results = df_results.sort_values('accuracy', ascending=False)

print("\nRanked by accuracy (high = leaky):")
for _, row in df_results.iterrows():
    print(f"  {row['group']:12s}: {row['accuracy']:.3f}  {row['verdict']}")

leaky_groups = df_results[df_results['accuracy'] >= 0.40]['group'].tolist()
clean_groups = df_results[df_results['accuracy'] < 0.40]['group'].tolist()

print(f"\n🔴 LEAKY GROUPS ({len(leaky_groups)}): {', '.join(leaky_groups)}")
print(f"🟢 CLEAN GROUPS ({len(clean_groups)}): {', '.join(clean_groups)}")

print("\n" + "="*70)
print("NEXT STEPS:")
print("="*70)
if leaky_groups:
    print(f"1. Investigate {leaky_groups[0]} feature builder code")
    print("2. Check for date filters: ensure WHERE match_date < cutoff_time")
    print("3. Look for aggregate tables that include future matches")
    print("4. Fix the leaky feature computation")
    print("5. Re-run this script to verify fix")
else:
    print("✅ All groups clean! Safe to proceed with full training.")
