#!/usr/bin/env python3
# movement_feature_builder.py — build multi-timepoint movement features
import argparse
from pathlib import Path
import numpy as np
import pandas as pd
from datetime import datetime
EPS = 1e-12

def softmax(x, axis=-1):
    x = x - np.max(x, axis=axis, keepdims=True)
    ex = np.exp(x)
    return ex / np.sum(ex, axis=axis, keepdims=True)

def synth_snapshots(N=400, seed=7):
    rng = np.random.default_rng(seed)
    match_id = np.arange(N)
    league_id = rng.integers(1,6,size=N)
    rows = []
    for i in range(N):
        base = np.array([0.45,0.3,0.25])
        p_open = rng.dirichlet(base*10)
        drift = rng.normal(scale=0.05, size=3); drift -= drift.mean()
        p_168 = p_open
        p_120 = softmax(np.log(p_open) + drift*0.5)
        p_72  = softmax(np.log(p_open) + drift*1.0)
        for secs_to in [168*3600, 120*3600, 72*3600]:
            if secs_to == 168*3600: P = p_168
            elif secs_to == 120*3600: P = p_120
            else: P = p_72
            for b in ["B365","PIN","WH"]:
                noise = rng.normal(scale=0.01, size=3)
                Pb = softmax(np.log(P) + noise)
                for o,idx in zip(["H","D","A"], [0,1,2]):
                    rows.append({
                        "match_id": i,
                        "league_id": int(league_id[i]),
                        "book_id": b,
                        "ts_snapshot": f"2025-01-01T00:00:00Z",
                        "secs_to_kickoff": int(secs_to),
                        "outcome": o,
                        "odds_decimal": float(1.0/Pb[idx]),
                        "implied_prob": float(Pb[idx]),
                        "market_margin": float(1.0/Pb.sum())
                    })
    return pd.DataFrame(rows)

def build_features(df):
    agg = df.groupby(["match_id","secs_to_kickoff","outcome"]).agg(
        p=("implied_prob","mean"),
        disp=("implied_prob","std"),
        n_books=("implied_prob","count")
    ).reset_index()
    P = agg.pivot_table(index=["match_id","secs_to_kickoff"],
                        columns="outcome",
                        values="p").reset_index().rename_axis(None, axis=1)
    P.columns = ["match_id","secs_to_kickoff","pA","pD","pH"]
    P = P[["match_id","secs_to_kickoff","pH","pD","pA"]]
    def nearest(dfm, target):
        j = (dfm["secs_to_kickoff"]-target).abs().idxmin()
        return dfm.loc[[j]]
    feats = []
    for mid, grp in P.groupby("match_id"):
        rows = []
        for target in [168*3600, 120*3600, 72*3600]:
            rows.append(nearest(grp, target))
        S = pd.concat(rows).sort_values("secs_to_kickoff")
        S = S.set_index("secs_to_kickoff")
        if 72*3600 not in S.index:
            continue
        logit = lambda p: np.log(np.clip(p, 1e-12, 1-1e-12))
        l168 = logit(S.loc[168*3600, ["pH","pD","pA"]]) if 168*3600 in S.index else None
        l120 = logit(S.loc[120*3600, ["pH","pD","pA"]]) if 120*3600 in S.index else None
        l72  = logit(S.loc[72*3600,  ["pH","pD","pA"]])
        d168_72 = (l72 - l168) if l168 is not None else pd.Series([0,0,0], index=["pH","pD","pA"])
        d120_72 = (l72 - l120) if l120 is not None else pd.Series([0,0,0], index=["pH","pD","pA"])
        if l168 is not None:
            slope = (l72 - l168) / (96)
        elif l120 is not None:
            slope = (l72 - l120) / (48)
        else:
            slope = pd.Series([0,0,0], index=["pH","pD","pA"])
        Ls = []
        if l168 is not None: Ls.append(l168.values)
        if l120 is not None: Ls.append(l120.values)
        Ls.append(l72.values)
        vol = np.std(np.vstack(Ls), axis=0) if len(Ls) >= 2 else np.array([0,0,0])
        row = {
            "match_id": mid,
            "pH_mkt": float(np.exp(l72["pH"])),
            "pD_mkt": float(np.exp(l72["pD"])),
            "pA_mkt": float(np.exp(l72["pA"])),
            "feat_dlogit_H_168_72": float(d168_72["pH"]),
            "feat_dlogit_D_168_72": float(d168_72["pD"]),
            "feat_dlogit_A_168_72": float(d168_72["pA"]),
            "feat_dlogit_H_120_72": float(d120_72["pH"]),
            "feat_dlogit_D_120_72": float(d120_72["pD"]),
            "feat_dlogit_A_120_72": float(d120_72["pA"]),
            "feat_slope_H": float(slope["pH"]),
            "feat_slope_D": float(slope["pD"]),
            "feat_slope_A": float(slope["pA"]),
            "feat_vol_H": float(vol[0]),
            "feat_vol_D": float(vol[1]),
            "feat_vol_A": float(vol[2]),
        }
        feats.append(row)
    return pd.DataFrame(feats)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=str, default="")
    ap.add_argument("--out", type=str, default="./movement_features.csv")
    args = ap.parse_args()
    if args.data and Path(args.data).exists():
        df = pd.read_csv(args.data)
        print(f"Loaded {len(df)} snapshot rows from {args.data}")
    else:
        print("No --data provided; generating synthetic snapshots...")
        df = synth_snapshots(N=400, seed=9)
    feats = build_features(df)
    feats.to_csv(args.out, index=False)
    print(f"Wrote movement features to {args.out} with shape {feats.shape}")

if __name__ == "__main__":
    main()
