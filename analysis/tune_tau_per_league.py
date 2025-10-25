import pandas as pd
import numpy as np

print("\n" + "="*70)
print("PER-LEAGUE THRESHOLD TUNER")
print("="*70)

df = pd.read_parquet("artifacts/eval/oof_preds.parquet")
cl = pd.read_parquet("artifacts/eval/close_probs.parquet")
df = df.merge(cl, on="match_id", how="inner")

def norm(a, b, c):
    x = np.clip(np.array([a, b, c], float), 1e-6, 1)
    s = x.sum()
    return x / s

ph = np.vstack([norm(*r) for r in df[["p_hat_home", "p_hat_draw", "p_hat_away"]].to_numpy()])
pc = np.vstack([norm(*r) for r in df[["p_close_home", "p_close_draw", "p_close_away"]].to_numpy()])
y = df["y_true"].map({'H': 0, 'D': 1, 'A': 2}).to_numpy()
pick = ph.argmax(1)
df["max_p"] = ph.max(1)
df["ev_close"] = ph[np.arange(len(df)), pick] - pc[np.arange(len(df)), pick]

def sweep(group, taus=(0.56, 0.58, 0.60, 0.62, 0.64), ev_gate=None, min_kept=150):
    best = None
    for t in taus:
        m = (group["max_p"] >= t)
        if ev_gate is not None:
            m &= (group["ev_close"] > ev_gate)
        kept = m.sum()
        if kept < min_kept:
            continue
        hit = (group.loc[m, "_pick"] == group.loc[m, "_y"]).mean()
        ev = group.loc[m, "ev_close"].mean()
        score = hit + 0.5 * ev
        cand = (t, kept, hit, ev, score)
        if best is None or score > best[-1]:
            best = cand
    return best

tmp = df.assign(_y=y, _pick=pick)
rows = []
for lg, g in tmp.groupby("league"):
    res = sweep(g, ev_gate=0.0)
    if res:
        t, kept, hit, ev, score = res
        rows.append((lg, t, kept, hit, ev, score))

out = pd.DataFrame(rows, columns=["league", "tau", "kept", "hit", "mean_ev", "score"]).sort_values("score", ascending=False)

print(f"\nOptimal thresholds per league (min 150 samples, EV > 0 gate):\n")
print(out.to_string(index=False, float_format=lambda x: f"{x:.4f}"))

out.to_csv("artifacts/eval/league_tau_table.csv", index=False)
print(f"\n✅ Saved to artifacts/eval/league_tau_table.csv")

print("\nUsage:")
print("  - Load league_tau_table.csv into selection service")
print("  - For unlisted leagues or low sample, fall back to global τ=0.62")
print("  - Update monthly or after 10%+ sample growth\n")
