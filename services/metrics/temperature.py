"""
Temperature Scaling for Multiclass Calibration

Post-hoc calibration method that scales logits by a learned temperature parameter.
Optimizes for negative log-likelihood (cross-entropy) on validation data.

References:
- Guo et al. (2017): "On Calibration of Modern Neural Networks"
- For multiclass: temp_probs = softmax(logits / T) where T > 0

Author: BetGenius AI Team
Date: Oct 2025
"""

import numpy as np
from scipy.optimize import minimize_scalar
from scipy.special import softmax
from typing import List, Tuple


def probs_to_logits(probs: np.ndarray, epsilon: float = 1e-10) -> np.ndarray:
    """
    Convert probabilities to logits (inverse softmax).
    
    Args:
        probs: Array of shape (n_samples, n_classes) with probabilities
        epsilon: Small constant to avoid log(0)
    
    Returns:
        logits: Array of shape (n_samples, n_classes)
    """
    probs_clipped = np.clip(probs, epsilon, 1 - epsilon)
    logits = np.log(probs_clipped)
    
    # Subtract max for numerical stability (doesn't change softmax output)
    logits = logits - logits.max(axis=1, keepdims=True)
    
    return logits


def apply_temperature(logits: np.ndarray, temperature: float) -> np.ndarray:
    """
    Apply temperature scaling to logits and return calibrated probabilities.
    
    Args:
        logits: Array of shape (n_samples, n_classes)
        temperature: Temperature parameter T > 0
            T > 1.0 → smoother probabilities (less confident)
            T < 1.0 → sharper probabilities (more confident)
            T = 1.0 → unchanged
    
    Returns:
        calibrated_probs: Array of shape (n_samples, n_classes)
    """
    scaled_logits = logits / temperature
    return softmax(scaled_logits, axis=1)


def nll_loss(temperature: float, logits: np.ndarray, y_true_indices: np.ndarray) -> float:
    """
    Negative log-likelihood loss for given temperature on validation data.
    
    Args:
        temperature: Temperature parameter to optimize
        logits: Array of shape (n_samples, n_classes)
        y_true_indices: Array of shape (n_samples,) with true class indices
    
    Returns:
        nll: Negative log-likelihood (lower is better)
    """
    probs = apply_temperature(logits, temperature)
    
    # Extract probabilities for true classes
    true_probs = probs[np.arange(len(y_true_indices)), y_true_indices]
    
    # NLL = -mean(log(p_true))
    nll = -np.log(np.clip(true_probs, 1e-10, 1.0)).mean()
    
    return nll


def fit_temperature(
    probabilities: List[Tuple[float, float, float]],
    y_true: List[str],
    outcome_map: dict = None,
    method: str = 'bounded'
) -> Tuple[float, dict]:
    """
    Find optimal temperature parameter using validation data.
    
    Args:
        probabilities: List of (p_home, p_draw, p_away) tuples
        y_true: List of actual outcomes ('H', 'D', 'A')
        outcome_map: Dict mapping outcomes to indices (default: {'H': 0, 'D': 1, 'A': 2})
        method: Optimization method ('bounded' or 'brent')
    
    Returns:
        optimal_temp: Best temperature value
        result: Dict with optimization details (nll_before, nll_after, improvement)
    """
    if outcome_map is None:
        outcome_map = {'H': 0, 'D': 1, 'A': 2}
    
    # Convert to numpy arrays
    probs = np.array(probabilities)  # shape: (n, 3)
    y_indices = np.array([outcome_map[y] for y in y_true])
    
    # Convert probabilities to logits
    logits = probs_to_logits(probs)
    
    # Calculate baseline NLL (temperature = 1.0)
    nll_before = nll_loss(1.0, logits, y_indices)
    
    # Optimize temperature
    if method == 'bounded':
        # Search in range [0.1, 5.0] to avoid extreme values
        result = minimize_scalar(
            lambda t: nll_loss(t, logits, y_indices),
            bounds=(0.1, 5.0),
            method='bounded'
        )
    else:
        # Brent's method (faster but no hard bounds)
        result = minimize_scalar(
            lambda t: nll_loss(t, logits, y_indices),
            bracket=(0.5, 1.0, 2.0),
            method='brent'
        )
    
    optimal_temp = result.x
    nll_after = result.fun
    
    return optimal_temp, {
        'nll_before': nll_before,
        'nll_after': nll_after,
        'improvement': nll_before - nll_after,
        'pct_improvement': 100 * (nll_before - nll_after) / nll_before,
        'success': result.success,
        'n_samples': len(y_true)
    }


def calibrate_predictions(
    probabilities: List[Tuple[float, float, float]],
    temperature: float
) -> List[Tuple[float, float, float]]:
    """
    Apply learned temperature to new predictions.
    
    Args:
        probabilities: List of (p_home, p_draw, p_away) tuples
        temperature: Learned temperature parameter
    
    Returns:
        calibrated: List of calibrated (p_home, p_draw, p_away) tuples
    """
    probs = np.array(probabilities)
    logits = probs_to_logits(probs)
    calibrated = apply_temperature(logits, temperature)
    
    return [tuple(row) for row in calibrated.tolist()]


if __name__ == "__main__":
    # Example: Overconfident model
    print("=" * 60)
    print("Temperature Scaling Demo: Overconfident Model")
    print("=" * 60)
    
    # Simulate overconfident predictions
    np.random.seed(42)
    n_samples = 100
    
    # True probabilities (balanced)
    true_probs = np.array([[0.4, 0.3, 0.3]] * n_samples)
    
    # Overconfident model (sharper than true)
    overconfident = np.array([[0.6, 0.25, 0.15]] * n_samples)
    
    # Simulate outcomes from true distribution
    outcomes_idx = np.random.choice([0, 1, 2], size=n_samples, p=[0.4, 0.3, 0.3])
    outcomes = ['HDAAny'[i] for i in outcomes_idx]
    
    # Fit temperature
    temp_opt, info = fit_temperature(
        [tuple(row) for row in overconfident],
        outcomes
    )
    
    print(f"\n✅ Optimal Temperature: {temp_opt:.3f}")
    print(f"   NLL Before: {info['nll_before']:.4f}")
    print(f"   NLL After:  {info['nll_after']:.4f}")
    print(f"   Improvement: {info['improvement']:.4f} ({info['pct_improvement']:.2f}%)")
    
    # Apply to first prediction
    calibrated = calibrate_predictions([tuple(overconfident[0])], temp_opt)
    print(f"\n📊 Example Prediction:")
    print(f"   Before: H={overconfident[0][0]:.3f}, D={overconfident[0][1]:.3f}, A={overconfident[0][2]:.3f}")
    print(f"   After:  H={calibrated[0][0]:.3f}, D={calibrated[0][1]:.3f}, A={calibrated[0][2]:.3f}")
    print(f"   True:   H=0.400, D=0.300, A=0.300")
    
    print("\n" + "=" * 60)
