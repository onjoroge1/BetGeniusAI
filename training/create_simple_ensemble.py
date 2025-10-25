import pandas as pd
import numpy as np
from sklearn.metrics import log_loss, accuracy_score, brier_score_loss

print("\n" + "="*70)
print("SIMPLE ENSEMBLE: V1 CONSENSUS + LIGHTGBM")
print("="*70)

CLASS2IDX = {'H': 0, 'D': 1, 'A': 2}

def normalize_triplet(h, d, a):
    v = np.clip(np.array([h, d, a], dtype=float), 1e-6, 1.0)
    s = v.sum()
    return v / s if s > 0 else np.array([1/3, 1/3, 1/3])

lgbm = pd.read_parquet("artifacts/eval/oof_preds.parquet")
close = pd.read_parquet("artifacts/eval/close_probs.parquet")

df = lgbm.merge(close, on="match_id", how="inner")

p_lgbm = np.stack([df.p_hat_home, df.p_hat_draw, df.p_hat_away], axis=1)
p_v1 = np.stack([df.p_close_home, df.p_close_draw, df.p_close_away], axis=1)

p_lgbm = np.vstack([normalize_triplet(*row) for row in p_lgbm])
p_v1 = np.vstack([normalize_triplet(*row) for row in p_v1])

y = df.y_true.map(CLASS2IDX).values
y_onehot = np.eye(3)[y]

print(f"\nEvaluating {len(df):,} matches")

ll_lgbm = log_loss(y, p_lgbm)
ll_v1 = log_loss(y, p_v1)
acc_lgbm = accuracy_score(y, p_lgbm.argmax(axis=1))
acc_v1 = accuracy_score(y, p_v1.argmax(axis=1))

print("\n" + "="*70)
print("BASELINE PERFORMANCE")
print("="*70)
print(f"LightGBM     - LogLoss: {ll_lgbm:.4f} | Accuracy: {acc_lgbm*100:.1f}%")
print(f"V1 Consensus - LogLoss: {ll_v1:.4f}   | Accuracy: {acc_v1*100:.1f}%")

print("\n" + "="*70)
print("ENSEMBLE ALPHA SEARCH")
print("="*70)
print(f"{'Alpha':<8} {'LogLoss':<10} {'Accuracy':<10} {'Brier':<10} {'Notes':<20}")
print("-" * 70)

best_alpha = None
best_logloss = float('inf')
results = []

for alpha in np.arange(0.0, 1.05, 0.05):
    p_blend = alpha * p_lgbm + (1 - alpha) * p_v1
    p_blend = np.vstack([normalize_triplet(*row) for row in p_blend])
    
    ll = log_loss(y, p_blend)
    acc = accuracy_score(y, p_blend.argmax(axis=1))
    brier = brier_score_loss(y_onehot.ravel(), p_blend.ravel())
    
    results.append({
        'alpha': alpha,
        'logloss': ll,
        'accuracy': acc,
        'brier': brier
    })
    
    note = ""
    if alpha == 0.0:
        note = "Pure V1"
    elif alpha == 1.0:
        note = "Pure LightGBM"
    elif ll < best_logloss:
        best_logloss = ll
        best_alpha = alpha
        best_acc = acc
        best_brier = brier
        note = "← BEST"
    
    print(f"{alpha:.2f}     {ll:.4f}     {acc*100:.1f}%      {brier:.4f}    {note}")

print("\n" + "="*70)
print("OPTIMAL ENSEMBLE")
print("="*70)
print(f"Best alpha (LightGBM weight): {best_alpha:.2f}")
print(f"Optimal LogLoss:              {best_logloss:.4f}")
print(f"Optimal Accuracy:             {best_acc*100:.1f}%")
print(f"Optimal Brier:                {best_brier:.4f}")

improvement_vs_v1 = (best_acc - acc_v1) * 100
improvement_vs_lgbm = (best_acc - acc_lgbm) * 100

print(f"\nImprovement vs V1:            {improvement_vs_v1:+.1f}%")
print(f"Improvement vs LightGBM:      {improvement_vs_lgbm:+.1f}%")

results_df = pd.DataFrame(results)
results_df.to_csv("artifacts/eval/ensemble_alpha_search.csv", index=False)
print(f"\n✅ Saved alpha search results to artifacts/eval/ensemble_alpha_search.csv")

ensemble_config = {
    'alpha': float(best_alpha),
    'logloss': float(best_logloss),
    'accuracy': float(best_acc),
    'brier': float(best_brier),
    'evaluated_samples': int(len(df))
}

import json
with open("artifacts/eval/ensemble_config.json", "w") as f:
    json.dump(ensemble_config, f, indent=2)

print(f"✅ Saved ensemble config to artifacts/eval/ensemble_config.json")

print("\n" + "="*70)
print("DEPLOYMENT CODE")
print("="*70)
print(f"""
# Add to your prediction service:

def predict_ensemble(p_lgbm, p_v1):
    '''
    Optimal weighted ensemble
    '''
    alpha = {best_alpha:.2f}  # LightGBM weight
    p_final = alpha * p_lgbm + (1 - alpha) * p_v1
    
    # Normalize
    p_final = p_final / p_final.sum()
    
    return p_final

# Expected performance:
# - Accuracy: {best_acc*100:.1f}%
# - LogLoss: {best_logloss:.4f}
# - Improvement: {improvement_vs_v1:+.1f}% vs V1 Consensus
""")

print("\n" + "="*70 + "\n")
