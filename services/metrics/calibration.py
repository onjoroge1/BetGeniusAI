"""
Calibration metrics: ECE, reliability diagrams, and calibration curves.
"""
import numpy as np
from typing import List, Dict, Tuple
from collections import defaultdict


def ece_multiclass(y_true: List[str], probabilities: List[Tuple[float, float, float]], n_bins: int = 10) -> float:
    """
    Calculate Expected Calibration Error (ECE) for multiclass predictions.
    
    ECE measures the difference between predicted confidence and actual accuracy
    across confidence bins.
    
    Args:
        y_true: List of true outcomes ('H', 'D', 'A')
        probabilities: List of (p_home, p_draw, p_away) tuples
        n_bins: Number of bins for calibration
    
    Returns:
        ECE score (lower is better, 0 is perfectly calibrated)
    
    References:
        "On Calibration of Modern Neural Networks" (Guo et al., 2017)
    """
    if len(y_true) != len(probabilities):
        raise ValueError("y_true and probabilities must have same length")
    
    if len(y_true) == 0:
        return 0.0
    
    # Get max probability and predicted class for each sample
    confidences = []
    predictions = []
    
    outcome_map = {'H': 0, 'D': 1, 'A': 2}
    
    for ph, pd, pa in probabilities:
        probs = [ph, pd, pa]
        max_prob = max(probs)
        pred_class = probs.index(max_prob)
        
        confidences.append(max_prob)
        predictions.append(pred_class)
    
    # Convert true labels to class indices
    true_classes = [outcome_map[y] for y in y_true]
    
    # Create bins
    bin_boundaries = np.linspace(0, 1, n_bins + 1)
    bin_lowers = bin_boundaries[:-1]
    bin_uppers = bin_boundaries[1:]
    
    ece = 0.0
    
    for bin_lower, bin_upper in zip(bin_lowers, bin_uppers):
        # Find samples in this bin
        in_bin = [
            i for i, conf in enumerate(confidences)
            if bin_lower <= conf < bin_upper or (bin_upper == 1.0 and conf == 1.0)
        ]
        
        if len(in_bin) > 0:
            # Average confidence in bin
            avg_confidence = np.mean([confidences[i] for i in in_bin])
            
            # Accuracy in bin
            accuracy = np.mean([
                1.0 if predictions[i] == true_classes[i] else 0.0
                for i in in_bin
            ])
            
            # Weighted contribution to ECE
            bin_weight = len(in_bin) / len(y_true)
            ece += bin_weight * abs(avg_confidence - accuracy)
    
    return ece


def reliability_table(
    y_true: List[str], 
    probabilities: List[Tuple[float, float, float]], 
    n_bins: int = 10
) -> List[Dict]:
    """
    Generate reliability table for calibration analysis.
    
    Args:
        y_true: List of true outcomes ('H', 'D', 'A')
        probabilities: List of (p_home, p_draw, p_away) tuples
        n_bins: Number of bins
    
    Returns:
        List of dicts with bin statistics:
        [{"bin": "0.0-0.1", "avg_max_p": 0.05, "true_freq": 0.04, "count": 10}, ...]
    """
    if len(y_true) != len(probabilities):
        raise ValueError("y_true and probabilities must have same length")
    
    if len(y_true) == 0:
        return []
    
    outcome_map = {'H': 0, 'D': 1, 'A': 2}
    
    # Get max probability and predicted class for each sample
    confidences = []
    predictions = []
    
    for ph, pd, pa in probabilities:
        probs = [ph, pd, pa]
        max_prob = max(probs)
        pred_class = probs.index(max_prob)
        
        confidences.append(max_prob)
        predictions.append(pred_class)
    
    true_classes = [outcome_map[y] for y in y_true]
    
    # Create bins
    bin_boundaries = np.linspace(0, 1, n_bins + 1)
    bin_lowers = bin_boundaries[:-1]
    bin_uppers = bin_boundaries[1:]
    
    reliability_data = []
    
    for bin_lower, bin_upper in zip(bin_lowers, bin_uppers):
        # Find samples in this bin
        in_bin = [
            i for i, conf in enumerate(confidences)
            if bin_lower <= conf < bin_upper or (bin_upper == 1.0 and conf == 1.0)
        ]
        
        if len(in_bin) > 0:
            avg_confidence = float(np.mean([confidences[i] for i in in_bin]))
            accuracy = float(np.mean([
                1.0 if predictions[i] == true_classes[i] else 0.0
                for i in in_bin
            ]))
            
            reliability_data.append({
                "bin": f"{bin_lower:.2f}-{bin_upper:.2f}",
                "avg_max_p": round(avg_confidence, 4),
                "true_freq": round(accuracy, 4),
                "count": len(in_bin),
                "gap": round(abs(avg_confidence - accuracy), 4)
            })
    
    return reliability_data


def ece_by_league(
    y_true: List[str],
    probabilities: List[Tuple[float, float, float]],
    leagues: List[str],
    n_bins: int = 10
) -> List[Dict]:
    """
    Calculate ECE separately for each league.
    
    Args:
        y_true: List of true outcomes
        probabilities: List of probability tuples
        leagues: List of league names (aligned with y_true)
        n_bins: Number of bins
    
    Returns:
        List of {"league": "EPL", "ece": 0.03, "sample_size": 50}
    """
    if not (len(y_true) == len(probabilities) == len(leagues)):
        raise ValueError("All inputs must have same length")
    
    # Group by league
    league_data = defaultdict(lambda: {"y_true": [], "probs": []})
    
    for y, prob, league in zip(y_true, probabilities, leagues):
        league_data[league]["y_true"].append(y)
        league_data[league]["probs"].append(prob)
    
    results = []
    for league, data in league_data.items():
        if len(data["y_true"]) >= 10:  # Minimum sample size
            ece = ece_multiclass(data["y_true"], data["probs"], n_bins)
            results.append({
                "league": league,
                "ece": round(ece, 4),
                "sample_size": len(data["y_true"])
            })
    
    return sorted(results, key=lambda x: x["ece"], reverse=True)
