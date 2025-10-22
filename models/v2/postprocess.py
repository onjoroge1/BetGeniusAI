"""
V2 Postprocessing Operations: Blend & Constraint Application

Provides modular operations for adjusting V2 predictions with market blending,
KL divergence capping, and delta temperature scaling.

Author: BetGenius AI Team
Date: Oct 2025
"""

import numpy as np
from typing import Tuple, Optional


def _safe_norm(p: np.ndarray) -> np.ndarray:
    """Safely normalize probability vector"""
    s = max(1e-9, p.sum())
    return p / s


def _to_logits(p: np.ndarray) -> np.ndarray:
    """
    Convert probabilities to logits (log-odds space).
    Clips to avoid infinities and centers for numerical stability.
    """
    p = np.clip(p, 1e-6, 1 - 1e-6)
    z = np.log(p)
    z -= z.mean()  # Center (optional, helps stability)
    return z


def _from_logits(z: np.ndarray) -> np.ndarray:
    """Convert logits back to probabilities via softmax"""
    e = np.exp(z - z.max())  # Numerical stability
    return e / e.sum()


def kl_divergence(p: np.ndarray, q: np.ndarray) -> float:
    """
    Calculate KL(p || q) divergence.
    
    Args:
        p: True distribution
        q: Approximate distribution
    
    Returns:
        KL divergence (non-negative)
    """
    p = np.clip(p, 1e-9, 1.0)
    q = np.clip(q, 1e-9, 1.0)
    return float((p * (np.log(p) - np.log(q))).sum())


def apply_blend_and_constraints(
    p_market: np.ndarray,
    p_model: np.ndarray,
    *,
    alpha: float,
    kl_cap: Optional[float] = None,
    delta_tau: float = 1.0
) -> np.ndarray:
    """
    Apply V2 postprocessing: delta scaling, market blending, and KL capping.
    
    Process:
    1. Compute model delta from market in logit space
    2. Scale delta by delta_tau (temperature on the delta)
    3. Apply delta to market logits → adjusted probs
    4. Blend adjusted probs with market (convex combination)
    5. Optionally project back if KL(blend || market) exceeds cap
    
    Args:
        p_market: Market consensus probabilities [ph, pd, pa]
        p_model: V2 raw model probabilities [ph, pd, pa]
        alpha: Blend weight for market (0=pure model, 1=pure market)
        kl_cap: Maximum allowed KL divergence from market (None=no cap)
        delta_tau: Temperature for scaling model-market delta (>1 = smoother)
    
    Returns:
        Final adjusted probabilities [ph, pd, pa]
    
    Example:
        >>> p_mkt = np.array([0.4, 0.3, 0.3])
        >>> p_mod = np.array([0.5, 0.25, 0.25])
        >>> p_adj = apply_blend_and_constraints(
        ...     p_mkt, p_mod, alpha=0.7, kl_cap=0.20, delta_tau=1.0
        ... )
    """
    # Step 1: Model delta in logit space (sharpen/soften with delta_tau)
    z_mkt = _to_logits(p_market)
    z_mod = _to_logits(p_model)
    delta = (z_mod - z_mkt) / max(1e-6, delta_tau)
    
    # Step 2: Apply delta to market logits
    z_adj = z_mkt + delta
    p_adj = _from_logits(z_adj)
    
    # Step 3: Convex blend with market
    p_blend = _safe_norm((1 - alpha) * p_adj + alpha * p_market)
    
    # Step 4: Optional KL projection back to cap
    if kl_cap is not None:
        k = kl_divergence(p_blend, p_market)
        if k > kl_cap:
            # Binary search for interpolation weight t ∈ [0,1]
            # to satisfy KL(mix || market) ≤ cap
            lo, hi = 0.0, 1.0
            for _ in range(12):  # 12 iterations → precision ~0.0002
                mid = (lo + hi) / 2
                p_try = _safe_norm((1 - mid) * p_blend + mid * p_market)
                if kl_divergence(p_try, p_market) > kl_cap:
                    lo = mid  # Need more market
                else:
                    hi = mid
            
            # Apply final interpolation
            t = hi
            p_blend = _safe_norm((1 - t) * p_blend + t * p_market)
    
    return p_blend


if __name__ == "__main__":
    # Demo: Overconfident model gets pulled back toward market
    print("=" * 60)
    print("V2 Postprocessing Demo")
    print("=" * 60)
    
    p_market = np.array([0.40, 0.30, 0.30])
    p_model = np.array([0.60, 0.25, 0.15])  # Overconfident on home
    
    print(f"\nMarket:  H={p_market[0]:.3f}, D={p_market[1]:.3f}, A={p_market[2]:.3f}")
    print(f"Model:   H={p_model[0]:.3f}, D={p_model[1]:.3f}, A={p_model[2]:.3f}")
    print(f"KL(model || market) = {kl_divergence(p_model, p_market):.4f}")
    
    # Test different configurations
    configs = [
        {"alpha": 0.5, "kl_cap": None, "delta_tau": 1.0, "name": "50% blend, no cap"},
        {"alpha": 0.7, "kl_cap": None, "delta_tau": 1.0, "name": "70% market blend"},
        {"alpha": 0.5, "kl_cap": 0.15, "delta_tau": 1.0, "name": "KL cap = 0.15"},
        {"alpha": 0.5, "kl_cap": None, "delta_tau": 1.5, "name": "Δ-temp = 1.5 (smoother)"},
    ]
    
    for cfg in configs:
        name = cfg.pop("name")
        p_adj = apply_blend_and_constraints(p_market, p_model, **cfg)
        kl = kl_divergence(p_adj, p_market)
        
        print(f"\n{name}:")
        print(f"  Result:  H={p_adj[0]:.3f}, D={p_adj[1]:.3f}, A={p_adj[2]:.3f}")
        print(f"  KL from market: {kl:.4f}")
    
    print("\n" + "=" * 60)
