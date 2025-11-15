#!/usr/bin/env python3
"""Quick ablation test with transformed features - 200 matches only"""
import os
os.environ['LD_LIBRARY_PATH'] = "/nix/store/xvzz97yk73hw03v5dhhz3j47ggwf1yq1-gcc-13.2.0-lib/lib"

import sys
sys.path.append('.')
import numpy as np
import pandas as pd
import lightgbm as lgb
from sqlalchemy import create_engine, text
from datetime import timedelta

from features.v2_feature_builder_transformed import V2FeatureBuilderTransformed

print("="*80)
print("QUICK ABLATION TEST - TRANSFORMED FEATURES")
print("="*80)

# Load 200 matches
engine = create_engine(os.getenv('DATABASE_URL'))
query = text("""
    SELECT match_id, match_date, outcome
    FROM training_matches
    WHERE match_date >= '2025-08-01'
      AND match_date < '2025-11-15'
      AND outcome IN ('Home', 'Draw', 'Away')
    ORDER BY match_date
    LIMIT 200
""")

with engine.connect() as conn:
    matches = pd.read_sql(query, conn)

print(f"✅ Loaded {len(matches)} matches\n")

# Build features
print("Building features with TRANSFORMED builder...")
builder = V2FeatureBuilderTransformed()
all_features = []
labels = []

for idx, row in matches.iterrows():
    if (idx+1) % 50 == 0:
        print(f"  Progress: {idx+1}/{len(matches)}")
    
    try:
        cutoff = row['match_date'] - timedelta(hours=1)
        features = builder.build_features(row['match_id'], cutoff)
        all_features.append(features)
        
        label_map = {'Home': 0, 'Draw': 1, 'Away': 2}
        labels.append(label_map[row['outcome']])
    except:
        continue

X_df = pd.DataFrame(all_features)
y = np.array(labels)

print(f"✅ Built features for {len(X_df)} matches")
print(f"   Feature count: {len(X_df.columns)}")

# Quick sanity test: Random labels
print("\n" + "="*80)
print("RANDOM LABEL SANITY TEST")
print("="*80)

feature_cols = [c for c in X_df.columns if c not in ['match_date', 'match_id']]
X = X_df[feature_cols].values

# Shuffle labels
np.random.seed(42)
y_random = np.random.permutation(y)

# Simple train/val split
split = int(len(X) * 0.8)
X_train, X_val = X[:split], X[split:]
y_train, y_val = y_random[:split], y_random[split:]

train_data = lgb.Dataset(X_train, label=y_train)

params = {
    'objective': 'multiclass',
    'num_class': 3,
    'num_leaves': 15,
    'learning_rate': 0.05,
    'feature_fraction': 0.8,
    'verbose': -1
}

print("\nTraining on random labels (should overfit if leak exists)...")
model = lgb.train(params, train_data, num_boost_round=50, verbose_eval=False)

# Predict
y_proba = model.predict(X_val)
y_pred = np.argmax(y_proba, axis=1)
acc = (y_pred == y_val).mean()

print(f"\nRandom label accuracy: {acc:.3f}")
print(f"Expected: ~0.333 (random guess)")
print(f"Threshold: < 0.40 = CLEAN")

if acc < 0.40:
    print(f"\n✅ PASS - Transformed features look clean!")
    print(f"   Accuracy {acc:.3f} is below 0.40 threshold")
else:
    print(f"\n❌ FAIL - Still shows leakage")
    print(f"   Accuracy {acc:.3f} exceeds 0.40 threshold")

# Test odds-only subset
print("\n" + "="*80)
print("ODDS-ONLY TEST (Known clean baseline)")
print("="*80)

odds_features = [c for c in feature_cols if c.startswith('p_') or 'dispersion' in c or 'volatility' in c or c in ['num_books_last', 'num_snapshots', 'coverage_hours', 'market_entropy', 'favorite_margin', 'book_dispersion']]
X_odds = X_df[odds_features].values

X_train_odds, X_val_odds = X_odds[:split], X_odds[split:]
train_data_odds = lgb.Dataset(X_train_odds, label=y_train)

model_odds = lgb.train(params, train_data_odds, num_boost_round=50, verbose_eval=False)
y_proba_odds = model_odds.predict(X_val_odds)
y_pred_odds = np.argmax(y_proba_odds, axis=1)
acc_odds = (y_pred_odds == y_val).mean()

print(f"Odds-only random label accuracy: {acc_odds:.3f}")
print(f"Expected: ~0.30-0.35 (baseline clean)")

if acc_odds < 0.38:
    print(f"✅ Odds baseline is clean")

print("\n" + "="*80)
print("SUMMARY")
print("="*80)
print(f"Full model (transformed): {acc:.3f} {'✅ CLEAN' if acc < 0.40 else '❌ LEAKY'}")
print(f"Odds-only baseline:       {acc_odds:.3f} {'✅ CLEAN' if acc_odds < 0.38 else '⚠️  CHECK'}")
