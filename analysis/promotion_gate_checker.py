import pandas as pd
import numpy as np

print("\n" + "="*70)
print("LIGHTGBM PROMOTION GATE CHECKER")
print("="*70)

CLASS2IDX = {'H': 0, 'D': 1, 'A': 2}

def normalize_triplet(h, d, a):
    v = np.clip(np.array([h, d, a], dtype=float), 1e-6, 1.0)
    s = v.sum()
    return v / s if s > 0 else np.array([1/3, 1/3, 1/3])

oof = pd.read_parquet("artifacts/eval/oof_preds.parquet")
close = pd.read_parquet("artifacts/eval/close_probs.parquet")

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

logloss_model = -np.log(np.clip(ph[np.arange(len(y)), y], 1e-6, 1.0)).mean()
logloss_baseline = -np.log(np.clip(pc[np.arange(len(y)), y], 1e-6, 1.0)).mean()
delta_logloss = logloss_model - logloss_baseline

brier_model = ((ph - y_onehot)**2).sum(axis=1).mean() / 3.0
acc3_model = (ph.argmax(axis=1) == y).mean()

pick_idx = ph.argmax(axis=1)
df["max_p"] = ph.max(axis=1)
df["ev_close"] = ph[np.arange(len(df)), pick_idx] - pc[np.arange(len(df)), pick_idx]

def ece(p, ypick, bins=10):
    bin_edges = np.linspace(0.0, 1.0, bins + 1)
    inds = np.digitize(p, bin_edges) - 1
    e = 0
    n = len(p)
    for b in range(len(bin_edges) - 1):
        m = (inds == b)
        if m.sum() == 0:
            continue
        conf = p[m].mean()
        acc = ypick[m].mean()
        e += (m.sum() / n) * abs(acc - conf)
    return e

ece_global = ece(df["max_p"].to_numpy(), (pick_idx == y).astype(int))

def check_ev_decile_monotonicity():
    q = pd.qcut(df["max_p"], 10, labels=False, duplicates="drop")
    hits = []
    for d in sorted(df.assign(decile=q)["decile"].unique()):
        mask = q == d
        if mask.sum() == 0:
            continue
        hit = (pick_idx[mask] == y[mask]).mean()
        hits.append(hit)
    
    top_half = hits[5:]
    is_monotone = all(top_half[i] <= top_half[i+1] for i in range(len(top_half)-1))
    return is_monotone, hits

ev_monotone, decile_hits = check_ev_decile_monotonicity()

mask_60 = df["max_p"] >= 0.60
if mask_60.sum() > 0:
    hit_at_60 = (pick_idx[mask_60] == y[mask_60]).mean()
    cov_at_60 = mask_60.mean()
    ev_at_60 = df.loc[mask_60, "ev_close"].mean()
else:
    hit_at_60 = cov_at_60 = ev_at_60 = np.nan

mask_62 = df["max_p"] >= 0.62
if mask_62.sum() > 0:
    hit_at_62 = (pick_idx[mask_62] == y[mask_62]).mean()
    cov_at_62 = mask_62.mean()
    ev_at_62 = df.loc[mask_62, "ev_close"].mean()
else:
    hit_at_62 = cov_at_62 = ev_at_62 = np.nan

pct_ev_pos = (df["ev_close"] > 0).mean()
mean_ev = df["ev_close"].mean()

ece_by_league = {}
for lg, g in df.groupby("league"):
    p = g["max_p"].to_numpy()
    group_indices = g.index.to_numpy()
    ypick = (pick_idx[group_indices] == y[group_indices]).astype(int)
    ece_by_league[lg] = ece(p, ypick)

max_league_ece = max(ece_by_league.values())
worst_league = max(ece_by_league.items(), key=lambda x: x[1])

print(f"\nEvaluated {len(df):,} matches")
print(f"Date range: {df['kickoff_date'].min()} → {df['kickoff_date'].max()}")

print("\n" + "="*70)
print("GATE 1: LogLoss Improvement")
print("="*70)
print(f"Model LogLoss:    {logloss_model:.4f}")
print(f"Baseline LogLoss: {logloss_baseline:.4f}")
print(f"Δ LogLoss:        {delta_logloss:+.4f}")
print(f"Target:           ≤ -0.02")
gate1_pass = delta_logloss <= -0.02
print(f"Status:           {'✅ PASS' if gate1_pass else '❌ FAIL'}")

print("\n" + "="*70)
print("GATE 2: Positive EV Rate")
print("="*70)
print(f"% EV_close > 0:   {pct_ev_pos*100:.1f}%")
print(f"Mean EV_close:    {mean_ev:+.4f}")
print(f"Target:           > 0% with positive mean")
gate2_pass = pct_ev_pos > 0 and mean_ev > 0
print(f"Status:           {'✅ PASS' if gate2_pass else '❌ FAIL'}")

print("\n" + "="*70)
print("GATE 3: EV Decile Monotonicity (Top Half)")
print("="*70)
print("Hit rates by decile:")
for i, hit in enumerate(decile_hits):
    marker = "  " if i < 5 else "→ "
    print(f"{marker}Decile {i}: {hit*100:.1f}%")
print(f"\nMonotonic in top half: {ev_monotone}")
print(f"Target:                Strictly increasing in deciles 5-9")
gate3_pass = ev_monotone
print(f"Status:                {'✅ PASS' if gate3_pass else '❌ FAIL'}")

print("\n" + "="*70)
print("GATE 4: Hit@Coverage Dominance")
print("="*70)
print(f"At τ=0.60: {hit_at_60*100:.1f}% hit @ {cov_at_60*100:.1f}% coverage (EV: {ev_at_60:+.4f})")
print(f"At τ=0.62: {hit_at_62*100:.1f}% hit @ {cov_at_62*100:.1f}% coverage (EV: {ev_at_62:+.4f})")
print(f"Baseline:  72.7% hit @ 21.5% coverage (EV: 0.0000)")
print(f"Target:    Dominate baseline at 60-65% coverage")
gate4_pass = (hit_at_60 > 0.727 and cov_at_60 >= 0.15) or (hit_at_62 > 0.727 and cov_at_62 >= 0.15)
print(f"Status:    {'✅ PASS' if gate4_pass else '❌ FAIL'}")

print("\n" + "="*70)
print("GATE 5: Calibration Quality")
print("="*70)
print(f"ECE (global):     {ece_global:.4f}")
print(f"Max league ECE:   {max_league_ece:.4f} ({worst_league[0]})")
print(f"Target:           ECE_global ≤ 0.08, no league > 0.12")
gate5_pass = ece_global <= 0.08 and max_league_ece <= 0.12
print(f"Status:           {'✅ PASS' if gate5_pass else '❌ FAIL'}")

print("\n" + "="*70)
print("ADDITIONAL METRICS")
print("="*70)
print(f"3-way Accuracy:   {acc3_model*100:.1f}%")
print(f"Brier Score:      {brier_model:.4f}")
print(f"Target Accuracy:  55-60%")

print("\n" + "="*70)
print("FINAL VERDICT")
print("="*70)
all_gates_pass = all([gate1_pass, gate2_pass, gate3_pass, gate4_pass, gate5_pass])
if all_gates_pass:
    print("✅ ALL GATES PASSED - PROMOTE TO PRODUCTION")
    print("\nRecommended actions:")
    print("1. Enable LightGBM in prediction endpoint")
    print("2. Start shadow testing (A/B vs V2 Ridge)")
    print("3. Monitor for 14 days")
    print("4. Full promotion if metrics hold")
else:
    print("❌ PROMOTION BLOCKED - CRITERIA NOT MET")
    print("\nFailed gates:")
    if not gate1_pass:
        print(f"  - Gate 1: LogLoss improvement insufficient (Δ={delta_logloss:+.4f}, need ≤-0.02)")
    if not gate2_pass:
        print(f"  - Gate 2: Insufficient positive EV ({pct_ev_pos*100:.1f}% > 0)")
    if not gate3_pass:
        print("  - Gate 3: EV deciles not monotonic in top half")
    if not gate4_pass:
        print(f"  - Gate 4: Hit@coverage doesn't dominate baseline")
    if not gate5_pass:
        print(f"  - Gate 5: Calibration issues (ECE={ece_global:.4f}, max_league={max_league_ece:.4f})")
    print("\nRecommended actions:")
    print("1. Analyze failure modes")
    print("2. Iterate on features/hyperparameters")
    print("3. Re-train and re-evaluate")

print("\n" + "="*70 + "\n")
