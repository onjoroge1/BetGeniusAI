#!/usr/bin/env python3
"""
LEAK DETECTOR V2 FAST: Quick diagnostic using 200 matches
"""

import os, sys, numpy as np, pandas as pd
from datetime import timedelta
from sqlalchemy import create_engine, text
from sklearn.metrics import accuracy_score, log_loss
import lightgbm as lgb

sys.path.append('.')
from features.v2_feature_builder import get_v2_feature_builder

class PurgedTimeSeriesSplit:
    def __init__(self, n_splits=3, embargo_days=7):
        self.n_splits = n_splits
        self.embargo_days = embargo_days
    
    def split(self, X, y=None, groups=None):
        if groups is None:
            raise ValueError("groups required")
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

print("="*70)
print("  LEAK DETECTOR V2 FAST (200 matches)")
print("="*70)

database_url = os.getenv('DATABASE_URL')
engine = create_engine(database_url)

query = text("""
    SELECT tm.match_id, tm.match_date, tm.outcome
    FROM training_matches tm
    INNER JOIN match_context mc ON tm.match_id = mc.match_id
    INNER JOIN odds_real_consensus orc ON tm.match_id = orc.match_id
    WHERE tm.match_date >= '2025-08-01'
      AND tm.outcome IN ('H', 'D', 'A', 'Home', 'Draw', 'Away')
    ORDER BY RANDOM()
    LIMIT 200
""")

with engine.connect() as conn:
    matches = pd.read_sql(query, conn)

matches['outcome'] = matches['outcome'].map({'Home': 'H', 'Draw': 'D', 'Away': 'A', 
                                              'H': 'H', 'D': 'D', 'A': 'A'})
print(f"✅ Loaded {len(matches)} matches\n")

print("🔨 Building features...")
builder = get_v2_feature_builder()
features_list = []

for idx, row in matches.iterrows():
    try:
        features = builder.build_features(row['match_id'], 
                                         cutoff_time=pd.to_datetime(row['match_date']))
        features['outcome'] = row['outcome']
        features['match_date'] = row['match_date']
        features_list.append(features)
        
        if (idx + 1) % 25 == 0:
            print(f"   {idx+1}/{len(matches)}", flush=True)
    except:
        continue

df = pd.DataFrame(features_list)
print(f"✅ Built {len(df)} vectors\n")

# Test ALL 50 features with TimeSeriesSplit
all_features = [c for c in df.columns if c not in ['outcome', 'match_date']]
X = df[all_features].values
y = np.array([{'H': 0, 'D': 1, 'A': 2}[l] for l in df['outcome'].values])
dates = df['match_date'].values

np.random.seed(42)
y_random = np.random.permutation(y)

cv = PurgedTimeSeriesSplit(n_splits=3, embargo_days=7)
accuracies = []

print("Testing ALL 50 features with TimeSeriesSplit + embargo...")
for fold_idx, (train_idx, valid_idx) in enumerate(cv.split(X, y_random, groups=dates)):
    X_train, X_valid = X[train_idx], X[valid_idx]
    y_train, y_valid = y_random[train_idx], y[valid_idx]
    
    model = lgb.train(
        {'objective': 'multiclass', 'num_class': 3, 'verbosity': -1},
        lgb.Dataset(X_train, label=y_train),
        num_boost_round=30,
        callbacks=[lgb.log_evaluation(0)]
    )
    
    y_pred = model.predict(X_valid)
    acc = accuracy_score(y_valid, np.argmax(y_pred, axis=1))
    accuracies.append(acc)
    print(f"  Fold {fold_idx+1}: {acc:.3f}")

mean_acc = np.mean(accuracies)
print(f"\n{'='*70}")
print(f"RESULT: {mean_acc:.3f} ({mean_acc*100:.1f}%)")
print(f"{'='*70}")

if mean_acc >= 0.40:
    print("❌ LEAKY - Interaction effect confirmed")
    print("\nThis matches full training (42-43%)")
    print("→ Real leak when features are combined")
else:
    print("✅ CLEAN - Test bug in full training")
    print("\nThis differs from full training (42-43%)")
    print("→ Bug in train_v2_no_leakage.py sanity check")
