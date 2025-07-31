#!/usr/bin/env python3
# book_mixer_trainer.py — instance-wise book mixing with softmax gating
import argparse, json
from pathlib import Path
import numpy as np
import pandas as pd
from datetime import datetime

EPS = 1e-15

def softmax(x, axis=-1):
    x = x - np.max(x, axis=axis, keepdims=True)
    ex = np.exp(x)
    return ex / np.sum(ex, axis=axis, keepdims=True)

def logloss_mc(y, P):
    p = np.clip(P[np.arange(len(P)), y], EPS, 1-EPS)
    return float(-np.log(p).mean())

def brier_mc(y, P):
    Y = np.eye(3)[y]
    return float(((P - Y)**2).mean())

def top2_acc(y, P):
    top2 = np.argsort(-P, axis=1)[:, :2]
    return float(((top2[:,0] == y) | (top2[:,1] == y)).mean())

def build_context(df):
    ctx_cols = [c for c in df.columns if c.startswith("ctx_")]
    X = df[ctx_cols].to_numpy(dtype=float) if ctx_cols else np.zeros((len(df),1))
    return X, ctx_cols

def list_books(df):
    books = set()
    for c in df.columns:
        if c.startswith("pH_"):
            books.add(c.split("_",1)[1])
    books = [b for b in sorted(books) if f"pD_{b}" in df.columns and f"pA_{b}" in df.columns]
    return books

def normalize_book_probs(df, books):
    for b in books:
        P = df[[f"pH_{b}", f"pD_{b}", f"pA_{b}"]].to_numpy()
        P = np.clip(P, EPS, 1-EPS)
        P = P / P.sum(axis=1, keepdims=True)
        df[[f"pH_{b}", f"pD_{b}", f"pA_{b}"]] = P
    return df

def synthetic_data(N=2000, B=4, seed=123):
    rng = np.random.default_rng(seed)
    base = np.array([0.45,0.30,0.25])
    P_true = rng.dirichlet(base*10, size=N)
    y = np.array([rng.choice(3, p=P_true[i]) for i in range(N)])
    books = [f"b{i+1}" for i in range(B)]
    df = pd.DataFrame({"y": y})
    disp = rng.uniform(0, 0.05, size=N)
    nbooks = rng.integers(2, B+1, size=N)
    has_pin = (rng.random(size=N) < 0.6).astype(int)
    df["ctx_dispersion"] = disp
    df["ctx_n_books"] = nbooks
    df["ctx_overround"] = rng.uniform(1.02, 1.08, size=N)
    df["ctx_has_pinnacle"] = has_pin
    for b in books:
        sharp = (b == "b1")
        noise = rng.normal(scale=0.04 if sharp else 0.08, size=(N,3))
        P_b = P_true + noise
        P_b = np.clip(P_b, 0.001, 0.999)
        P_b = P_b / P_b.sum(axis=1, keepdims=True)
        df[f"pH_{b}"] = P_b[:,0]
        df[f"pD_{b}"] = P_b[:,1]
        df[f"pA_{b}"] = P_b[:,2]
    return df

def train_gating(df, epochs=300, lr=0.05, l2=1e-3, outdir="./book_mixer_artifacts"):
    books = list_books(df)
    df = normalize_book_probs(df, books)
    X, ctx_cols = build_context(df)
    y = df["y"].to_numpy(dtype=int)

    N, D = X.shape
    B = len(books)
    K = 3

    logp_books = np.zeros((N, B, K), dtype=float)
    for j, b in enumerate(books):
        P = df[[f"pH_{b}", f"pD_{b}", f"pA_{b}"]].to_numpy()
        logp_books[:, j, :] = np.log(np.clip(P, EPS, 1-EPS))

    rng = np.random.default_rng(42)
    U = rng.normal(scale=0.01, size=(D, B))
    c = np.zeros((1, B))

    def forward(U, c):
        logits_books = X @ U + c
        w = softmax(logits_books, axis=1)
        mix_logp = np.sum(w[:,:,None] * logp_books, axis=1)
        P_mix = softmax(mix_logp, axis=1)
        return w, P_mix

    def loss_and_grads(U, c):
        logits_books = X @ U + c
        w = softmax(logits_books, axis=1)
        mix_logp = np.sum(w[:,:,None] * logp_books, axis=1)
        P_mix = softmax(mix_logp, axis=1)

        p_true = np.clip(P_mix[np.arange(N), y], EPS, 1-EPS)
        nll = -np.log(p_true).mean()
        reg = l2 * np.sum(U*U)
        loss = nll + reg

        Y = np.eye(3)[y]
        G_mix = (P_mix - Y) / N
        G_w = np.sum(G_mix[:,None,:] * logp_books, axis=2)
        Gw_center = G_w - np.sum(w * G_w, axis=1, keepdims=True)
        dlogits = w * Gw_center
        dU = X.T @ dlogits + 2*l2*U
        dc = dlogits.sum(axis=0, keepdims=True)
        return loss, dU, dc

    best = {"loss": 1e9, "U": U.copy(), "c": c.copy()}
    for ep in range(1, epochs+1):
        loss, dU, dc = loss_and_grads(U, c)
        U -= lr * dU
        c -= lr * dc
        if loss < best["loss"]:
            best = {"loss": float(loss), "U": U.copy(), "c": c.copy()}
        if ep % 20 == 0 or ep == 1:
            print(f"[epoch {ep:04d}] loss={loss:.6f}")

    U, c = best["U"], best["c"]
    w, P_mix = forward(U, c)

    # baselines
    P_eq = np.exp(np.mean(logp_books, axis=1)); P_eq = P_eq / P_eq.sum(axis=1, keepdims=True)
    # simple static weights from per-book LL
    LL_per_book = []
    for j in range(len(books)):
        P_b = np.exp(logp_books[:,j,:]); P_b = P_b / P_b.sum(axis=1, keepdims=True)
        p = np.clip(P_b[np.arange(N), y], EPS, 1-EPS)
        LL_per_book.append(float(-np.log(p).mean()))
    LL_per_book = np.array(LL_per_book)
    sw = np.exp(-(LL_per_book - LL_per_book.min()))
    sw = sw / sw.sum()
    mix_logp_static = np.sum(sw[None,:,None] * logp_books, axis=1)
    P_static = softmax(mix_logp_static, axis=1)

    def rep(label, P):
        return {"label":label, "logloss":logloss_mc(y,P), "brier":brier_mc(y,P), "top2":top2_acc(y,P)}

    metrics = [rep("equal_geom", P_eq), rep("static_weighted_geom", P_static), rep("learned_mix_geom", P_mix)]

    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    np.save(outdir / f"U_{ts}.npy", U)
    np.save(outdir / f"c_{ts}.npy", c)
    import json
    with open(outdir / f"metrics_{ts}.json", "w") as f:
        json.dump(metrics, f, indent=2)

    # per-match weights and consensus
    books = list_books(df)  # to keep order
    out = pd.DataFrame({"match_idx": np.arange(N), "y": y})
    for j,b in enumerate(books):
        out[f"w_{b}"] = w[:,j]
    out["pH_mix"] = P_mix[:,0]; out["pD_mix"] = P_mix[:,1]; out["pA_mix"] = P_mix[:,2]
    out["pH_eq"]  = P_eq[:,0];  out["pD_eq"]  = P_eq[:,1];  out["pA_eq"]  = P_eq[:,2]
    out.to_csv(outdir / f"MIXED_CONSENSUS_{ts}.csv", index=False)
    print("Artifacts written to", outdir)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=str, default="")
    ap.add_argument("--epochs", type=int, default=300)
    ap.add_argument("--lr", type=float, default=0.05)
    ap.add_argument("--l2", type=float, default=1e-3)
    ap.add_argument("--outdir", type=str, default="./book_mixer_artifacts")
    args = ap.parse_args()

    if args.data and Path(args.data).exists():
        df = pd.read_csv(args.data)
        print(f"Loaded {len(df)} rows from {args.data}")
    else:
        print("No --data provided; generating synthetic dataset...")
        df = synthetic_data(N=2000, B=4, seed=123)

    train_gating(df, epochs=args.epochs, lr=args.lr, l2=args.l2, outdir=args.outdir)

if __name__ == "__main__":
    main()