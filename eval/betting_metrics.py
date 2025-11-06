"""
Betting-Centric Evaluation Metrics

Measures what actually matters for a betting model:
- Expected Value (EV) - theoretical profit per dollar
- Closing Line Value (CLV) - edge vs. closing odds
- Calibration (ECE) - reliability of probabilities
- Log Loss & Brier Score - probability accuracy
- Policy Backtests - simulated betting performance

These metrics >>> simple accuracy for betting applications.
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from sklearn.metrics import log_loss, brier_score_loss
import logging

logger = logging.getLogger(__name__)


def expected_value(prob: float, decimal_odds: float) -> float:
    """
    Calculate Expected Value (EV) of a bet
    
    Formula: EV = p_win * (odds - 1) - p_lose
    
    Args:
        prob: Model's probability of outcome (0-1)
        decimal_odds: Bookmaker's decimal odds
        
    Returns:
        Expected value per $1 staked (e.g., 0.05 = 5% expected return)
        
    Example:
        >>> expected_value(0.55, 2.0)  # 55% prob at 2.0 odds
        0.10  # 10% EV
    """
    payout_multiplier = decimal_odds - 1.0
    p_lose = 1.0 - prob
    
    ev = (prob * payout_multiplier) - p_lose
    return ev


def closing_line_value(model_price: float, closing_price: float) -> float:
    """
    Calculate Closing Line Value (CLV)
    
    CLV is the gold standard for measuring betting skill.
    Positive CLV = beating the closing line = long-term profit.
    
    Args:
        model_price: Your model's fair decimal odds
        closing_price: Market's closing decimal odds
        
    Returns:
        CLV as probability delta (positive = good)
        
    Example:
        >>> closing_line_value(2.5, 2.0)  # You got better price
        0.10  # 10% CLV (huge edge!)
    """
    model_prob = 1.0 / model_price
    closing_prob = 1.0 / closing_price
    
    clv = closing_prob - model_prob
    return clv


def expected_calibration_error(
    y_true: np.ndarray,
    y_pred_proba: np.ndarray,
    n_bins: int = 10
) -> float:
    """
    Calculate Expected Calibration Error (ECE)
    
    Measures how well predicted probabilities match actual frequencies.
    Lower is better. ECE < 0.05 is excellent calibration.
    
    Args:
        y_true: True labels (0, 1, 2 for 3-way classification)
        y_pred_proba: Predicted probabilities (N x 3 array)
        n_bins: Number of confidence bins
        
    Returns:
        ECE value (0-1, lower is better)
        
    Example:
        If model predicts 70% confidence, ECE measures if it's right 70% of the time
    """
    # Get confidence (max probability) and predicted class
    confidences = np.max(y_pred_proba, axis=1)
    predictions = np.argmax(y_pred_proba, axis=1)
    accuracies = (predictions == y_true).astype(float)
    
    # Create bins
    bin_boundaries = np.linspace(0, 1, n_bins + 1)
    bin_lowers = bin_boundaries[:-1]
    bin_uppers = bin_boundaries[1:]
    
    ece = 0.0
    for bin_lower, bin_upper in zip(bin_lowers, bin_uppers):
        # Find samples in this bin
        in_bin = (confidences > bin_lower) & (confidences <= bin_upper)
        prop_in_bin = np.mean(in_bin)
        
        if prop_in_bin > 0:
            # Average confidence and accuracy in bin
            avg_confidence_in_bin = np.mean(confidences[in_bin])
            avg_accuracy_in_bin = np.mean(accuracies[in_bin])
            
            # ECE contribution
            ece += np.abs(avg_confidence_in_bin - avg_accuracy_in_bin) * prop_in_bin
    
    return ece


def evaluate_predictions(
    df: pd.DataFrame,
    prob_cols: List[str] = ['proba_home', 'proba_draw', 'proba_away'],
    price_cols: List[str] = ['price_home', 'price_draw', 'price_away'],
    closing_price_cols: Optional[List[str]] = None,
    outcome_col: str = 'outcome'
) -> Dict[str, float]:
    """
    Comprehensive evaluation of betting model predictions
    
    Args:
        df: DataFrame with predictions and outcomes
            Required columns:
            - outcome: actual result (0=away, 1=draw, 2=home)
            - proba_home/draw/away: model probabilities
            - price_home/draw/away: available odds
            Optional:
            - closing_price_home/draw/away: closing odds for CLV
        prob_cols: Column names for model probabilities
        price_cols: Column names for available odds
        closing_price_cols: Column names for closing odds (optional)
        outcome_col: Column name for actual outcome
        
    Returns:
        Dictionary of metrics:
        {
            'logloss': float,
            'brier': float,
            'ece': float,
            'accuracy_3way': float,
            'accuracy_2way': float,
            'avg_ev': float,
            'avg_clv': float,  # if closing prices provided
            'flat_stake_roi': float,  # simulated betting return
            'kelly_roi': float,  # Kelly criterion betting
            'sharpe': float  # risk-adjusted return
        }
    """
    results = {}
    
    # Extract arrays
    y_true = df[outcome_col].values
    y_pred_proba = df[prob_cols].values
    prices = df[price_cols].values
    
    # Basic probability metrics
    results['logloss'] = log_loss(y_true, y_pred_proba)
    
    # Brier score (average across outcomes)
    brier_scores = []
    for k in range(3):
        y_binary = (y_true == k).astype(int)
        brier_scores.append(brier_score_loss(y_binary, y_pred_proba[:, k]))
    results['brier'] = np.mean(brier_scores)
    
    # Calibration
    results['ece'] = expected_calibration_error(y_true, y_pred_proba)
    
    # Accuracy
    y_pred = np.argmax(y_pred_proba, axis=1)
    results['accuracy_3way'] = np.mean(y_pred == y_true)
    
    # 2-way accuracy (remove draws)
    non_draw = y_true != 1
    if np.sum(non_draw) > 0:
        results['accuracy_2way'] = np.mean(y_pred[non_draw] == y_true[non_draw])
    else:
        results['accuracy_2way'] = np.nan
    
    # Betting metrics
    evs = []
    bets = []
    returns = []
    kelly_stakes = []
    kelly_returns = []
    
    for i in range(len(df)):
        # Find outcome with highest EV
        outcome_evs = []
        for k in range(3):
            prob = y_pred_proba[i, k]
            price = prices[i, k]
            ev = expected_value(prob, price)
            outcome_evs.append(ev)
        
        best_outcome = np.argmax(outcome_evs)
        best_ev = outcome_evs[best_outcome]
        
        # Only bet if positive EV
        if best_ev > 0:
            evs.append(best_ev)
            bets.append(1)  # Flat stake
            
            # Simulate outcome
            if y_true[i] == best_outcome:
                # Win
                returns.append(prices[i, best_outcome] - 1.0)
            else:
                # Loss
                returns.append(-1.0)
            
            # Kelly criterion stake (capped at 5% for safety)
            prob = y_pred_proba[i, best_outcome]
            price = prices[i, best_outcome]
            kelly = (price * prob - 1) / (price - 1)
            kelly_stake = min(kelly * 0.5, 0.05)  # Half Kelly, max 5%
            kelly_stakes.append(kelly_stake)
            kelly_returns.append(kelly_stake * returns[-1] / bets[-1])  # Scaled return
    
    # EV metrics
    results['avg_ev'] = np.mean(evs) if evs else 0.0
    results['num_bets'] = len(bets)
    results['bet_frequency'] = len(bets) / len(df)
    
    # Simulated performance
    if bets:
        results['flat_stake_roi'] = np.sum(returns) / np.sum(bets)
        results['flat_stake_total_return'] = np.sum(returns)
        results['hit_rate'] = np.mean(np.array(returns) > 0)
        
        # Kelly performance
        results['kelly_roi'] = np.sum(kelly_returns) / np.sum(kelly_stakes) if np.sum(kelly_stakes) > 0 else 0.0
        
        # Sharpe ratio (risk-adjusted)
        if len(returns) > 1:
            results['sharpe'] = np.mean(returns) / (np.std(returns) + 1e-10) * np.sqrt(len(returns))
        else:
            results['sharpe'] = 0.0
    else:
        results['flat_stake_roi'] = 0.0
        results['flat_stake_total_return'] = 0.0
        results['hit_rate'] = 0.0
        results['kelly_roi'] = 0.0
        results['sharpe'] = 0.0
    
    # CLV metrics (if closing prices provided)
    if closing_price_cols:
        closing_prices = df[closing_price_cols].values
        clvs = []
        
        for i in range(len(df)):
            for k in range(3):
                model_price = 1.0 / y_pred_proba[i, k] if y_pred_proba[i, k] > 0 else 100.0
                closing_price = closing_prices[i, k]
                
                if closing_price > 1.0:  # Valid closing price
                    clv = closing_line_value(model_price, closing_price)
                    clvs.append(clv)
        
        results['avg_clv'] = np.mean(clvs) if clvs else 0.0
        results['positive_clv_pct'] = np.mean(np.array(clvs) > 0) * 100 if clvs else 0.0
    
    return results


def print_evaluation_report(metrics: Dict[str, float], title: str = "Model Evaluation"):
    """Pretty print evaluation metrics"""
    print("\n" + "="*60)
    print(f"  {title}")
    print("="*60)
    
    print("\n📊 Probability Metrics:")
    print(f"  Log Loss:        {metrics.get('logloss', 0):.4f}  (lower is better)")
    print(f"  Brier Score:     {metrics.get('brier', 0):.4f}  (lower is better)")
    print(f"  ECE:             {metrics.get('ece', 0):.4f}  (calibration quality)")
    
    print("\n🎯 Accuracy:")
    print(f"  3-way:           {metrics.get('accuracy_3way', 0)*100:.2f}%")
    print(f"  2-way (no draw): {metrics.get('accuracy_2way', 0)*100:.2f}%")
    
    print("\n💰 Betting Performance:")
    print(f"  Avg EV:          {metrics.get('avg_ev', 0)*100:+.2f}%")
    print(f"  Bets Made:       {metrics.get('num_bets', 0):.0f} ({metrics.get('bet_frequency', 0)*100:.1f}% of matches)")
    print(f"  Flat Stake ROI:  {metrics.get('flat_stake_roi', 0)*100:+.2f}%")
    print(f"  Hit Rate:        {metrics.get('hit_rate', 0)*100:.1f}%")
    print(f"  Kelly ROI:       {metrics.get('kelly_roi', 0)*100:+.2f}%")
    print(f"  Sharpe Ratio:    {metrics.get('sharpe', 0):.2f}")
    
    if 'avg_clv' in metrics:
        print("\n📈 Closing Line Value:")
        print(f"  Avg CLV:         {metrics.get('avg_clv', 0)*100:+.2f}%")
        print(f"  Positive CLV:    {metrics.get('positive_clv_pct', 0):.1f}% of bets")
    
    print("\n" + "="*60)
    
    # Quality assessment
    print("\n✨ Quality Assessment:")
    
    # Calibration
    ece = metrics.get('ece', 1.0)
    if ece < 0.05:
        cal_grade = "EXCELLENT"
    elif ece < 0.10:
        cal_grade = "GOOD"
    elif ece < 0.15:
        cal_grade = "FAIR"
    else:
        cal_grade = "POOR"
    print(f"  Calibration:     {cal_grade}")
    
    # Betting edge
    roi = metrics.get('flat_stake_roi', 0)
    if roi > 0.05:
        edge_grade = "ELITE"
    elif roi > 0.02:
        edge_grade = "STRONG"
    elif roi > 0:
        edge_grade = "PROFITABLE"
    else:
        edge_grade = "UNPROFITABLE"
    print(f"  Betting Edge:    {edge_grade}")
    
    # CLV
    if 'avg_clv' in metrics:
        clv = metrics.get('avg_clv', 0)
        if clv > 0.02:
            clv_grade = "EXCELLENT"
        elif clv > 0:
            clv_grade = "POSITIVE"
        else:
            clv_grade = "NEGATIVE"
        print(f"  CLV Grade:       {clv_grade}")
    
    print()


if __name__ == "__main__":
    # Example usage
    print("Betting Metrics Module - Example Usage")
    print("="*60)
    
    # Create synthetic test data
    np.random.seed(42)
    n_matches = 100
    
    # Simulate slightly better-than-market model
    df = pd.DataFrame({
        'outcome': np.random.choice([0, 1, 2], n_matches, p=[0.25, 0.28, 0.47]),
        'proba_away': np.random.beta(2, 5, n_matches),
        'proba_draw': np.random.beta(2, 3, n_matches),
        'proba_home': np.random.beta(5, 2, n_matches),
        'price_away': np.random.uniform(2.0, 5.0, n_matches),
        'price_draw': np.random.uniform(3.0, 4.0, n_matches),
        'price_home': np.random.uniform(1.5, 3.0, n_matches),
    })
    
    # Normalize probabilities
    prob_sum = df['proba_away'] + df['proba_draw'] + df['proba_home']
    df['proba_away'] /= prob_sum
    df['proba_draw'] /= prob_sum
    df['proba_home'] /= prob_sum
    
    # Evaluate
    metrics = evaluate_predictions(df)
    print_evaluation_report(metrics, "Example Model Evaluation")
