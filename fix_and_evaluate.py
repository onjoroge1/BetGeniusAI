"""
Export OOF predictions from trained model and re-run evaluation
"""
import pandas as pd
import numpy as np
import json
from pathlib import Path

print("="*70)
print("EXPORTING OOF PREDICTIONS FOR EVALUATION")
print("="*70)

# Load the training data to get match metadata
data = pd.read_parquet("artifacts/datasets/v2_tabular_historical.parquet")
print(f"\n✅ Loaded dataset: {len(data):,} matches")

# Load OOF predictions from training
model_dir = Path("artifacts/models/lgbm_historical_36k")
oof_preds = np.load(model_dir / "oof_predictions.npy")
print(f"✅ Loaded OOF predictions: {oof_preds.shape}")

# Load metadata to verify
with open(model_dir / "metadata.json") as f:
    metadata = json.load(f)
    print(f"✅ Training metadata loaded")

# Create predictions dataframe
oof_df = pd.DataFrame({
    'match_id': data['match_id'].values,
    'league': data['league'].values,
    'kickoff_date': data['kickoff_date'].values,
    'y_true': data['y'].values,
    'p_hat_home': oof_preds[:, 0],
    'p_hat_draw': oof_preds[:, 1],
    'p_hat_away': oof_preds[:, 2]
})

print(f"\n✅ Created OOF predictions dataframe")
print(f"   Shape: {oof_df.shape}")
print(f"   Date range: {oof_df['kickoff_date'].min()} → {oof_df['kickoff_date'].max()}")

# Check if predictions are different from baseline
p_close = data[['p_close_home', 'p_close_draw', 'p_close_away']].values
diff = np.abs(oof_preds - p_close).mean()
print(f"\n📊 Prediction difference from baseline: {diff:.4f}")

if diff < 0.001:
    print("⚠️  WARNING: Predictions are very close to baseline!")
    print("   This might indicate the model is just learning the market.")
else:
    print("✅ Predictions differ from baseline - model is learning patterns!")

# Save to expected location
output_dir = Path("artifacts/eval")
output_dir.mkdir(parents=True, exist_ok=True)

oof_df.to_parquet(output_dir / "oof_preds.parquet", index=False)
print(f"\n✅ Saved OOF predictions to: {output_dir / 'oof_preds.parquet'}")

# Also save baseline probabilities if not already there
close_df = pd.DataFrame({
    'match_id': data['match_id'].values,
    'p_close_home': data['p_close_home'].values,
    'p_close_draw': data['p_close_draw'].values,
    'p_close_away': data['p_close_away'].values
})
close_df.to_parquet(output_dir / "close_probs.parquet", index=False)
print(f"✅ Saved baseline probabilities to: {output_dir / 'close_probs.parquet'}")

print("\n" + "="*70)
print("READY FOR EVALUATION")
print("="*70)
print("\nRun this now:")
print("  python analysis/promotion_gate_checker.py")
print("\n" + "="*70)
