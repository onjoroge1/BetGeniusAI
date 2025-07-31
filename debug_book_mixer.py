"""Debug the book mixer data issue"""

import pandas as pd
import numpy as np

# Load data
df = pd.read_csv('book_mixer_data/book_mixer_input_20250731_173828.csv')

print("Data shape:", df.shape)
print("\nColumns:", df.columns.tolist())
print("\nFirst few rows:")
print(df.head())

print("\nData types:")
print(df.dtypes)

print("\nNaN counts:")
print(df.isnull().sum())

print("\nUnique y values:", df['y'].unique())

# Check book probability columns
book_cols = [col for col in df.columns if col.startswith('pH_') or col.startswith('pD_') or col.startswith('pA_')]
print(f"\nBook probability columns: {book_cols}")

for col in book_cols:
    if col in df.columns:
        print(f"{col}: min={df[col].min():.6f}, max={df[col].max():.6f}, nan_count={df[col].isnull().sum()}")

# Check context columns
ctx_cols = [col for col in df.columns if col.startswith('ctx_')]
print(f"\nContext columns: {ctx_cols}")

for col in ctx_cols:
    if col in df.columns:
        print(f"{col}: min={df[col].min():.6f}, max={df[col].max():.6f}, nan_count={df[col].isnull().sum()}")