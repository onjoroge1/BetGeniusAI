import pandas as pd
import numpy as np
from pathlib import Path

print("Loading training matrix...")
df = pd.read_parquet("artifacts/datasets/v2_tabular_historical.parquet")

print(f"Total samples: {len(df)}")
print(f"Date range: {df['kickoff_date'].min()} → {df['kickoff_date'].max()}")

IDX2CLASS = {0: 'H', 1: 'D', 2: 'A'}

if 'y' in df.columns:
    df['y_true'] = df['y']
elif 'result' in df.columns:
    df['y_true'] = df['result']
elif 'outcome' in df.columns:
    df['y_true'] = df['outcome'].map({0: 'H', 1: 'D', 2: 'A'})
else:
    print("ERROR: No y/result/outcome column found")
    exit(1)

df['kickoff_date'] = pd.to_datetime(df['kickoff_date'])

print("\nExporting CLOSE (no-vig) probabilities...")
close_cols = ['match_id', 'p_close_home', 'p_close_draw', 'p_close_away']
for col in close_cols[1:]:
    if col not in df.columns:
        alt_col = col.replace('p_close', 'p_last')
        if alt_col in df.columns:
            df[col] = df[alt_col]
        else:
            print(f"WARNING: {col} not found, using market baseline")
            if 'p_market_home' in df.columns:
                df[col] = df[col.replace('close', 'market')]
            else:
                print(f"ERROR: Cannot find {col} or alternatives")
                exit(1)

close_df = df[close_cols].copy()
close_df.to_parquet("artifacts/eval/close_probs.parquet", index=False)
print(f"✅ Exported {len(close_df)} close probabilities")

print("\nExporting mock OOF predictions (using last/close as baseline)...")
if all(f'p_last_{o}' in df.columns for o in ['home', 'draw', 'away']):
    oof_df = pd.DataFrame({
        'match_id': df['match_id'],
        'league': df['league'],
        'kickoff_date': df['kickoff_date'],
        'y_true': df['y_true'],
        'p_hat_home': df['p_last_home'],
        'p_hat_draw': df['p_last_draw'],
        'p_hat_away': df['p_last_away'],
    })
    oof_df.to_parquet("artifacts/eval/oof_preds.parquet", index=False)
    print(f"✅ Exported {len(oof_df)} OOF predictions (close/last baseline)")
    print("\nNOTE: These are CLOSE probabilities as placeholder (EV=0 baseline).")
    print("Replace with actual LightGBM OOF predictions after training completes.")
else:
    print("ERROR: Cannot find p_last_* probabilities")
    exit(1)

print("\n=== Export complete ===")
print("Files created:")
print("  - artifacts/eval/close_probs.parquet")
print("  - artifacts/eval/oof_preds.parquet")
print("\nNext: Run full LightGBM training, then update oof_preds.parquet with actual predictions")
