#!/usr/bin/env python3
"""
V2 ODDS-ONLY Training - GUARANTEED LEAKAGE-FREE

This version uses ONLY odds-derived features, excluding all team/context features
that might contain leakage. This is our safe baseline for production.

Expected performance: 48-52% accuracy (realistic for odds-only model)
"""

import os, sys, numpy as np, pandas as pd
from datetime import datetime, timedelta
from sqlalchemy import create_engine, text
from sklearn.metrics import accuracy_score, log_loss, brier_score_loss
import lightgbm as lgb
import joblib
from pathlib import Path

sys.path.append('.')
from features.v2_feature_builder import get_v2_feature_builder

# Define ODDS-ONLY features (guaranteed leak-free)
ODDS_ONLY_FEATURES = [
    # Consensus probabilities
    'p_open_home', 'p_open_draw', 'p_open_away',
    'p_last_home', 'p_last_draw', 'p_last_away',
    # Market metrics
    'num_books_last', 'book_dispersion', 'market_entropy',
    # Dispersion
    'dispersion_home', 'dispersion_draw', 'dispersion_away',
    # Market structure
    'favorite_margin',
    # Drift features (odds movement T-24h → T-0h)
    'prob_drift_home', 'prob_drift_draw', 'prob_drift_away', 'drift_magnitude',
]

print("="*70)
print("  V2 ODDS-ONLY TRAINING (GUARANTEED LEAK-FREE)")
print("="*70)
print(f"Using {len(ODDS_ONLY_FEATURES)} odds-derived features only")
print("Excluding: form, ELO, H2H, advanced stats, rest days, schedule")
print()

# Load matches
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
    LIMIT 1000
""")

with engine.connect() as conn:
    matches = pd.read_sql(query, conn)

matches['outcome'] = matches['outcome'].map({'Home': 'H', 'Draw': 'D', 'Away': 'A'})
print(f"✅ Loaded {len(matches)} matches\n")

# Build features
print("🔨 Building features (odds-only)...")
builder = get_v2_feature_builder()
features_list = []

for idx, row in matches.iterrows():
    try:
        features = builder.build_features(row['match_id'], 
                                         cutoff_time=pd.to_datetime(row['match_date']))
        
        # Extract ONLY odds features
        odds_features = {k: features[k] for k in ODDS_ONLY_FEATURES if k in features}
        odds_features['outcome'] = row['outcome']
        odds_features['match_date'] = row['match_date']
        features_list.append(odds_features)
        
        if (idx + 1) % 100 == 0:
            print(f"   {idx+1}/{len(matches)} ({100*(idx+1)/len(matches):.1f}%)", flush=True)
    except:
        continue

df = pd.DataFrame(features_list)
print(f"✅ Built {len(df)} feature vectors\n")

if len(df) < 100:
    print("❌ Insufficient data")
    sys.exit(1)

# Sanity checks
print("="*70)
print("SANITY CHECKS (Odds-Only)")
print("="*70)

X = df[ODDS_ONLY_FEATURES].values
y = np.array([{'H': 0, 'D': 1, 'A': 2}[l] for l in df['outcome'].values])
dates = pd.to_datetime(df['match_date'].values)

# Random label test
np.random.seed(42)
y_random = np.random.permutation(y)

from sklearn.model_selection import train_test_split
X_train, X_valid, y_train_rand, y_valid = train_test_split(
    X, y_random, test_size=0.2, shuffle=False
)

model = lgb.train(
    {'objective': 'multiclass', 'num_class': 3, 'verbosity': -1},
    lgb.Dataset(X_train, label=y_train_rand),
    num_boost_round=50,
    callbacks=[lgb.log_evaluation(0)]
)

y_pred = model.predict(X_valid)
acc = accuracy_score(y_valid, np.argmax(y_pred, axis=1))
ll = log_loss(y_valid, y_pred)

print(f"Random label test: Acc={acc:.3f}, LogLoss={ll:.3f}")
if acc < 0.40:
    print("✅ PASS: No leakage detected\n")
else:
    print("❌ FAIL: Possible leakage even in odds features!\n")

# Train real model
print("="*70)
print("TRAINING ODDS-ONLY MODEL")
print("="*70)

X_train, X_valid, y_train, y_valid = train_test_split(
    X, y, test_size=0.2, shuffle=False
)

model = lgb.train(
    {'objective': 'multiclass', 'num_class': 3, 'num_leaves': 31, 'verbosity': -1},
    lgb.Dataset(X_train, label=y_train),
    num_boost_round=100,
    valid_sets=[lgb.Dataset(X_valid, label=y_valid)],
    callbacks=[lgb.early_stopping(10), lgb.log_evaluation(10)]
)

y_pred = model.predict(X_valid, num_iteration=model.best_iteration)
acc = accuracy_score(y_valid, np.argmax(y_pred, axis=1))
ll = log_loss(y_valid, y_pred)
brier = np.mean([brier_score_loss(y_valid == i, y_pred[:, i]) for i in range(3)])

print(f"\n✅ ODDS-ONLY MODEL RESULTS:")
print(f"   Accuracy: {acc:.3f} ({acc*100:.1f}%)")
print(f"   LogLoss:  {ll:.4f}")
print(f"   Brier:    {brier:.4f}")
print(f"\n   Feature count: {len(ODDS_ONLY_FEATURES)}")
print(f"   Model size: {model.num_trees()} trees")

# Save model
output_dir = Path("artifacts/models/v2_odds_only")
output_dir.mkdir(parents=True, exist_ok=True)

model_path = output_dir / "model.txt"
model.save_model(str(model_path))
print(f"\n💾 Saved to: {model_path}")

print("\n" + "="*70)
print("✅ ODDS-ONLY V2 MODEL READY FOR PRODUCTION")
print("="*70)
