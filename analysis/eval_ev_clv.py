import pandas as pd
import numpy as np

oof_path = "artifacts/eval/oof_preds.parquet"
close_path = "artifacts/eval/close_probs.parquet"

CLASS2IDX = {'H': 0, 'D': 1, 'A': 2}
IDX2CLASS = {0: 'H', 1: 'D', 2: 'A'}


def normalize_triplet(h, d, a):
    v = np.clip(np.array([h, d, a], dtype=float), 1e-6, 1.0)
    s = v.sum()
    return v / s if s > 0 else np.array([1/3, 1/3, 1/3])


oof = pd.read_parquet(oof_path)
close = pd.read_parquet(close_path)

df = (oof.merge(close, on="match_id", how="inner")
      .dropna(subset=["p_hat_home", "p_hat_draw", "p_hat_away",
                      "p_close_home", "p_close_draw", "p_close_away"]))

ph = np.stack([df.p_hat_home, df.p_hat_draw, df.p_hat_away], axis=1)
pc = np.stack([df.p_close_home, df.p_close_draw, df.p_close_away], axis=1)
ph = np.vstack([normalize_triplet(*row) for row in ph])
pc = np.vstack([normalize_triplet(*row) for row in pc])

df[["p_hat_home", "p_hat_draw", "p_hat_away"]] = ph
df[["p_close_home", "p_close_draw", "p_close_away"]] = pc

y = df.y_true.map(CLASS2IDX).values
y_onehot = np.eye(3)[y]

logloss = -np.log(np.clip(ph[np.arange(len(y)), y], 1e-6, 1.0)).mean()
brier = ((ph - y_onehot)**2).sum(axis=1).mean() / 3.0
acc3 = (ph.argmax(axis=1) == y).mean()

pick_idx = ph.argmax(axis=1)
df["max_p"] = ph.max(axis=1)
df["ev_close"] = ph[np.arange(len(df)), pick_idx] - pc[np.arange(len(df)), pick_idx]

has_open = all(f"p_open_{k}" in df.columns for k in ["home", "draw", "away"])
if has_open:
    for k in ["home", "draw", "away"]:
        df[f"clv_{k}"] = df[f"p_close_{k}"] - df[f"p_open_{k}"]
    df["clv_pick"] = df[[f"clv_{IDX2CLASS[i].lower()}" for i in range(3)]].to_numpy()[np.arange(len(df)), pick_idx]
else:
    df["clv_pick"] = np.nan
    print("NOTE: p_open_* columns not found, CLV metrics will be unavailable")


def compute_ev_deciles():
    q = pd.qcut(df["max_p"], 10, labels=False, duplicates="drop")
    rows = []
    for d in sorted(df.assign(decile=q)["decile"].unique()):
        mask = q == d
        if mask.sum() == 0:
            continue
        avg_conf = df.loc[mask, "max_p"].mean()
        hit = (pick_idx[mask] == y[mask]).mean()
        mean_ev = df.loc[mask, "ev_close"].mean()
        n = mask.sum()
        rows.append((d, avg_conf, hit, mean_ev, n))
    return pd.DataFrame(rows, columns=["decile", "avg_conf", "hit_rate", "mean_ev", "n"])


def sweep(thresholds=(0.54, 0.56, 0.58, 0.60, 0.62, 0.64, 0.66, 0.68, 0.70), ev_gate=None):
    rows = []
    for t in thresholds:
        mask = df["max_p"] >= t
        if ev_gate is not None:
            mask &= df["ev_close"] > ev_gate
        kept = mask.sum()
        if kept == 0:
            rows.append((t, ev_gate, 0.0, 0, np.nan, np.nan))
            continue
        kept_idx = np.where(mask)[0]
        hit = (pick_idx[kept_idx] == y[kept_idx]).mean()
        mean_ev = df.loc[mask, "ev_close"].mean()
        rows.append((t, ev_gate, kept / len(df), kept, hit, mean_ev))
    return pd.DataFrame(rows, columns=["tau", "ev_gate", "coverage", "kept", "hit_rate", "mean_ev"])


def ece(group, bins=10):
    p = group["max_p"].to_numpy()
    group_indices = group.index.to_numpy()
    ypick = (pick_idx[group_indices] == y[group_indices]).astype(int)
    bin_edges = np.linspace(0.0, 1.0, bins + 1)
    inds = np.digitize(p, bin_edges) - 1
    e = 0
    n = len(group)
    for b in range(len(bin_edges) - 1):
        m = (inds == b)
        if m.sum() == 0:
            continue
        conf = p[m].mean()
        acc = ypick[m].mean()
        e += (m.sum() / n) * abs(acc - conf)
    return e


ev_table = compute_ev_deciles()
hitcov = sweep()
hitcov_evpos = sweep(ev_gate=0.0)
ece_global = ece(df)
ece_by_league = df.groupby("league").apply(ece).sort_values()

print("\n=== GLOBAL METRICS ===")
print(f"LogLoss: {logloss:.4f} | Brier: {brier:.4f} | 3-way Acc: {acc3*100:.1f}%")
print(f"EV_close>0 rate: {(df['ev_close']>0).mean()*100:.1f}% | Mean EV_close: {df['ev_close'].mean():+.4f}")
print(f"ECE (global): {ece_global:.4f}")

print("\n=== EV DECILES (by confidence) ===")
print(ev_table.to_string(index=False, float_format=lambda x: f"{x:.4f}"))

print("\n=== HIT@COVERAGE (no EV gate) ===")
print(hitcov.to_string(index=False, float_format=lambda x: f"{x:.4f}"))

print("\n=== HIT@COVERAGE (EV_close>0 gate) ===")
print(hitcov_evpos.to_string(index=False, float_format=lambda x: f"{x:.4f}"))

print("\n=== ECE by league (lower is better) ===")
print(ece_by_league.head(12))

print(f"\n=== SUMMARY ===")
print(f"Total matches evaluated: {len(df)}")
print(f"Date range: {df['kickoff_date'].min()} → {df['kickoff_date'].max()}")
print(f"Leagues: {df['league'].nunique()} ({', '.join(sorted(df['league'].unique())[:5])}...)")
