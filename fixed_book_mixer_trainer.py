#!/usr/bin/env python3
# fixed_book_mixer_trainer.py — instance-wise book mixing with better error handling
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
    if ctx_cols:
        X = df[ctx_cols].fillna(0).to_numpy(dtype=float)
    else:
        X = np.ones((len(df), 1))  # Bias term only
    return X, ctx_cols

def list_books(df):
    books = set()
    for c in df.columns:
        if c.startswith("pH_"):
            book = c.split("_", 1)[1]
            books.add(book)
    books = [b for b in sorted(books) if f"pD_{b}" in df.columns and f"pA_{b}" in df.columns]
    return books

def normalize_book_probs(df, books):
    for b in books:
        pH_col = f"pH_{b}"
        pD_col = f"pD_{b}"
        pA_col = f"pA_{b}"
        
        if all(col in df.columns for col in [pH_col, pD_col, pA_col]):
            P = df[[pH_col, pD_col, pA_col]].fillna(1/3).to_numpy()
            P = np.clip(P, EPS, 1-EPS)
            P = P / P.sum(axis=1, keepdims=True)
            df[[pH_col, pD_col, pA_col]] = P
    return df

def train_gating(df, epochs=300, lr=0.05, l2=1e-3, outdir="./book_mixer_artifacts"):
    print(f"Training with {len(df)} samples...")
    
    books = list_books(df)
    print(f"Found books: {books}")
    
    if len(books) == 0:
        raise ValueError("No books found in data")
    
    df = normalize_book_probs(df, books)
    X, ctx_cols = build_context(df)
    y = df["y"].fillna(0).astype(int).to_numpy()
    
    print(f"Context features: {len(ctx_cols)}")
    print(f"Books: {len(books)}")
    
    N, D = X.shape
    B = len(books)
    K = 3

    logp_books = np.zeros((N, B, K), dtype=float)
    for j, b in enumerate(books):
        pH_col = f"pH_{b}"
        pD_col = f"pD_{b}"
        pA_col = f"pA_{b}"
        
        if all(col in df.columns for col in [pH_col, pD_col, pA_col]):
            P = df[[pH_col, pD_col, pA_col]].to_numpy()
            logp_books[:, j, :] = np.log(np.clip(P, EPS, 1-EPS))
        else:
            # Fallback to uniform
            logp_books[:, j, :] = np.log(1/3)

    # Check for NaN/inf in data
    if np.any(~np.isfinite(logp_books)):
        print("Warning: Non-finite values in logp_books, clipping...")
        logp_books = np.nan_to_num(logp_books, nan=np.log(1/3), posinf=np.log(1-EPS), neginf=np.log(EPS))
    
    if np.any(~np.isfinite(X)):
        print("Warning: Non-finite values in X, filling...")
        X = np.nan_to_num(X, nan=0.0)

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
        
        # Check for overflow
        if np.any(np.abs(logits_books) > 50):
            print("Warning: Large logits detected, clipping...")
            logits_books = np.clip(logits_books, -50, 50)
        
        w = softmax(logits_books, axis=1)
        mix_logp = np.sum(w[:,:,None] * logp_books, axis=1)
        P_mix = softmax(mix_logp, axis=1)

        p_true = np.clip(P_mix[np.arange(N), y], EPS, 1-EPS)
        nll = -np.log(p_true).mean()
        reg = l2 * np.sum(U*U)
        loss = nll + reg
        
        # Check for NaN
        if not np.isfinite(loss):
            print(f"NaN/inf loss detected: nll={nll}, reg={reg}")
            return np.inf, np.zeros_like(U), np.zeros_like(c)

        Y = np.eye(3)[y]
        G_mix = (P_mix - Y) / N
        G_w = np.sum(G_mix[:,None,:] * logp_books, axis=2)
        Gw_center = G_w - np.sum(w * G_w, axis=1, keepdims=True)
        dlogits = w * Gw_center
        dU = X.T @ dlogits + 2*l2*U
        dc = dlogits.sum(axis=0, keepdims=True)
        
        # Check gradients
        if np.any(~np.isfinite(dU)) or np.any(~np.isfinite(dc)):
            print("NaN/inf gradients detected, zeroing...")
            dU = np.nan_to_num(dU, nan=0.0)
            dc = np.nan_to_num(dc, nan=0.0)
        
        return loss, dU, dc

    best = {"loss": 1e9, "U": U.copy(), "c": c.copy()}
    
    for ep in range(1, epochs+1):
        loss, dU, dc = loss_and_grads(U, c)
        
        if not np.isfinite(loss):
            print(f"Stopping training at epoch {ep} due to non-finite loss")
            break
            
        # Gradient clipping
        grad_norm = np.sqrt(np.sum(dU**2) + np.sum(dc**2))
        if grad_norm > 10:
            dU = dU * 10 / grad_norm
            dc = dc * 10 / grad_norm
        
        U -= lr * dU
        c -= lr * dc
        
        if loss < best["loss"] and np.isfinite(loss):
            best = {"loss": float(loss), "U": U.copy(), "c": c.copy()}
            
        if ep % 20 == 0 or ep == 1:
            print(f"[epoch {ep:04d}] loss={loss:.6f}")

    U, c = best["U"], best["c"]
    w, P_mix = forward(U, c)

    # Compute baselines
    P_eq = np.exp(np.mean(logp_books, axis=1))
    P_eq = P_eq / P_eq.sum(axis=1, keepdims=True)
    
    # Simple static weights from per-book LL
    LL_per_book = []
    for j in range(len(books)):
        P_b = np.exp(logp_books[:,j,:])
        P_b = P_b / P_b.sum(axis=1, keepdims=True)
        p = np.clip(P_b[np.arange(N), y], EPS, 1-EPS)
        LL_per_book.append(float(-np.log(p).mean()))
    
    LL_per_book = np.array(LL_per_book)
    if np.all(np.isfinite(LL_per_book)):
        sw = np.exp(-(LL_per_book - LL_per_book.min()))
        sw = sw / sw.sum()
    else:
        sw = np.ones(len(books)) / len(books)
    
    mix_logp_static = np.sum(sw[None,:,None] * logp_books, axis=1)
    P_static = softmax(mix_logp_static, axis=1)

    def rep(label, P):
        return {"label":label, "logloss":logloss_mc(y,P), "brier":brier_mc(y,P), "top2":top2_acc(y,P)}

    metrics = [
        rep("equal_geom", P_eq), 
        rep("static_weighted_geom", P_static), 
        rep("learned_mix_geom", P_mix)
    ]

    # Calculate improvements
    equal_ll = metrics[0]['logloss']
    static_ll = metrics[1]['logloss'] 
    learned_ll = metrics[2]['logloss']
    
    metrics.append({
        "label": "improvements",
        "static_vs_equal": equal_ll - static_ll,
        "learned_vs_equal": equal_ll - learned_ll,
        "learned_vs_static": static_ll - learned_ll
    })

    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    
    np.save(outdir / f"U_{ts}.npy", U)
    np.save(outdir / f"c_{ts}.npy", c)
    
    with open(outdir / f"metrics_{ts}.json", "w") as f:
        json.dump(metrics, f, indent=2)

    # Per-match weights and consensus
    out = pd.DataFrame({"match_idx": np.arange(N), "y": y})
    for j,b in enumerate(books):
        out[f"w_{b}"] = w[:,j]
    out["pH_mix"] = P_mix[:,0]; out["pD_mix"] = P_mix[:,1]; out["pA_mix"] = P_mix[:,2]
    out["pH_eq"]  = P_eq[:,0];  out["pD_eq"]  = P_eq[:,1];  out["pA_eq"]  = P_eq[:,2]
    out["pH_static"] = P_static[:,0]; out["pD_static"] = P_static[:,1]; out["pA_static"] = P_static[:,2]
    out.to_csv(outdir / f"MIXED_CONSENSUS_{ts}.csv", index=False)
    
    print(f"Artifacts written to {outdir}")
    
    # Print results
    print(f"\n📊 BOOK MIXING RESULTS:")
    for metric in metrics:
        if metric['label'] == 'improvements':
            print(f"\n💡 IMPROVEMENTS:")
            print(f"   • Static vs Equal: {metric['static_vs_equal']:.6f}")
            print(f"   • Learned vs Equal: {metric['learned_vs_equal']:.6f}")
            print(f"   • Learned vs Static: {metric['learned_vs_static']:.6f}")
        else:
            print(f"   • {metric['label']}: LL={metric['logloss']:.6f}, Brier={metric['brier']:.6f}, Top2={metric['top2']:.3f}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=str, required=True)
    ap.add_argument("--epochs", type=int, default=300)
    ap.add_argument("--lr", type=float, default=0.05)
    ap.add_argument("--l2", type=float, default=1e-3)
    ap.add_argument("--outdir", type=str, default="./book_mixer_artifacts")
    args = ap.parse_args()

    df = pd.read_csv(args.data)
    print(f"Loaded {len(df)} rows from {args.data}")

    train_gating(df, epochs=args.epochs, lr=args.lr, l2=args.l2, outdir=args.outdir)

if __name__ == "__main__":
    main()