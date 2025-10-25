"""
Generate predictions for entire dataset using trained LightGBM ensemble
"""
import pandas as pd
import numpy as np
import pickle
import json
from pathlib import Path

print("="*70)
print("GENERATING FULL DATASET PREDICTIONS")
print("="*70)

# Load dataset
data = pd.read_parquet("artifacts/datasets/v2_tabular_historical.parquet")
print(f"\n✅ Loaded dataset: {len(data):,} matches")
print(f"   Date range: {data['kickoff_date'].min()} → {data['kickoff_date'].max()}")

# Load trained models
model_dir = Path("artifacts/models/lgbm_historical_36k")
with open(model_dir / "lgbm_ensemble.pkl", "rb") as f:
    models = pickle.load(f)
print(f"✅ Loaded {len(models)} trained models")

# Load features
with open(model_dir / "features.json") as f:
    feature_cols = json.load(f)
print(f"✅ Loaded {len(feature_cols)} features")

# Prepare features
X = data[feature_cols].values

# Generate predictions using ensemble (average of all folds)
print(f"\nGenerating ensemble predictions...")
all_preds = []
for i, model in enumerate(models, 1):
    preds = model.predict(X, num_iteration=model.best_iteration)
    all_preds.append(preds)
    print(f"  Model {i}/{len(models)}: {preds.shape}")

# Average predictions
ensemble_preds = np.mean(all_preds, axis=0)
print(f"✅ Ensemble predictions: {ensemble_preds.shape}")

# Normalize
def normalize_triplet(h, d, a):
    total = h + d + a
    if total <= 0:
        return 1/3, 1/3, 1/3
    return h/total, d/total, a/total

ensemble_preds_norm = np.array([normalize_triplet(p[0], p[1], p[2]) for p in ensemble_preds])

# Quick sanity check
print(f"\n📊 Prediction statistics:")
print(f"   Home prob range: [{ensemble_preds_norm[:, 0].min():.3f}, {ensemble_preds_norm[:, 0].max():.3f}]")
print(f"   Draw prob range: [{ensemble_preds_norm[:, 1].min():.3f}, {ensemble_preds_norm[:, 1].max():.3f}]")
print(f"   Away prob range: [{ensemble_preds_norm[:, 2].min():.3f}, {ensemble_preds_norm[:, 2].max():.3f}]")
print(f"   Sum check: {ensemble_preds_norm.sum(axis=1).mean():.6f} (should be 1.0)")

# Create predictions dataframe
pred_df = pd.DataFrame({
    'match_id': data['match_id'].values,
    'league': data['league'].values,
    'kickoff_date': data['kickoff_date'].values,
    'y_true': data['y'].values,
    'p_hat_home': ensemble_preds_norm[:, 0],
    'p_hat_draw': ensemble_preds_norm[:, 1],
    'p_hat_away': ensemble_preds_norm[:, 2]
})

# Save
output_dir = Path("artifacts/eval")
output_dir.mkdir(parents=True, exist_ok=True)

pred_df.to_parquet(output_dir / "oof_preds.parquet", index=False)
print(f"\n✅ Saved predictions to: {output_dir / 'oof_preds.parquet'}")

# Sample
print(f"\n📋 Sample predictions:")
print(pred_df[['y_true', 'p_hat_home', 'p_hat_draw', 'p_hat_away']].head(10))

print("\n" + "="*70)
print("✅ COMPLETE - Ready for evaluation!")
print("="*70)
print("\nNext step:")
print("  python analysis/promotion_gate_checker.py")
print("="*70)
