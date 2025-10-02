#!/usr/bin/env python3
"""
Model Accuracy Test - Brier Score, Log Loss, and Hit Rate
Tests the current model against actual match results
"""

import os
import psycopg2
import numpy as np
from typing import Dict, List, Tuple
from datetime import datetime

DATABASE_URL = os.getenv('DATABASE_URL')

def calculate_brier_score(probs: Dict[str, float], actual: str) -> float:
    """Calculate Brier score for a single prediction"""
    p_h = probs.get('H', 0.0)
    p_d = probs.get('D', 0.0)
    p_a = probs.get('A', 0.0)
    
    # One-hot encode actual outcome
    y_true = {'H': [1, 0, 0], 'D': [0, 1, 0], 'A': [0, 0, 1]}
    actual_vec = y_true.get(actual, [0, 0, 0])
    pred_vec = [p_h, p_d, p_a]
    
    # Brier = mean squared error
    brier = sum((p - y)**2 for p, y in zip(pred_vec, actual_vec)) / 3
    return brier

def calculate_log_loss(probs: Dict[str, float], actual: str) -> float:
    """Calculate log loss for a single prediction"""
    epsilon = 1e-15  # Avoid log(0)
    p = probs.get(actual, 0.0)
    p = max(min(p, 1 - epsilon), epsilon)  # Clip to [epsilon, 1-epsilon]
    return -np.log(p)

def test_model_accuracy():
    """Test model accuracy using prediction_snapshots and match results"""
    
    print("=" * 70)
    print("🎯 MODEL ACCURACY TEST - BetGenius AI")
    print("=" * 70)
    print()
    
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    
    # Get predictions with actual results
    cursor.execute("""
        SELECT 
            ps.match_id,
            ps.probs_h,
            ps.probs_d,
            ps.probs_a,
            ps.confidence,
            ps.served_at,
            tm.outcome,
            tm.home_team,
            tm.away_team,
            ps.league
        FROM prediction_snapshots ps
        JOIN training_matches tm ON ps.match_id = tm.match_id
        WHERE tm.outcome IN ('H', 'D', 'A')
          AND ps.probs_h > 0
          AND ps.probs_d > 0
          AND ps.probs_a > 0
        ORDER BY ps.served_at DESC
    """)
    
    predictions = cursor.fetchall()
    cursor.close()
    conn.close()
    
    if not predictions:
        print("❌ No predictions with match results found!")
        print("\nPossible reasons:")
        print("  • Matches haven't been played yet (future matches)")
        print("  • Match results not collected in training_matches table")
        print("  • prediction_snapshots table is empty")
        return
    
    print(f"📊 Found {len(predictions)} predictions with match results\n")
    
    # Calculate metrics
    brier_scores = []
    log_losses = []
    correct_predictions = 0
    
    for row in predictions:
        match_id, p_h, p_d, p_a, conf, served_at, actual, home, away, league = row
        
        probs = {'H': p_h, 'D': p_d, 'A': p_a}
        
        # Calculate metrics
        brier = calculate_brier_score(probs, actual)
        logloss = calculate_log_loss(probs, actual)
        
        brier_scores.append(brier)
        log_losses.append(logloss)
        
        # Check if prediction was correct
        predicted = max(probs, key=probs.get)
        if predicted == actual:
            correct_predictions += 1
        
        # Print sample predictions
        if len(brier_scores) <= 5:
            result_emoji = "✅" if predicted == actual else "❌"
            print(f"{result_emoji} Match {match_id}: {home} vs {away}")
            print(f"   Predicted: {predicted} ({probs[predicted]:.3f})")
            print(f"   Actual: {actual}")
            print(f"   Brier: {brier:.4f} | LogLoss: {logloss:.4f}")
            print()
    
    # Calculate aggregate metrics
    avg_brier = np.mean(brier_scores)
    avg_logloss = np.mean(log_losses)
    accuracy = (correct_predictions / len(predictions)) * 100
    
    # Normalized Brier Score (0 to 1 scale)
    # Perfect = 0, Random = 0.667, Worst = 2
    normalized_brier = avg_brier / 2  # Normalize to 0-1 scale
    
    print("=" * 70)
    print("📈 OVERALL METRICS")
    print("=" * 70)
    print()
    print(f"Total Predictions:     {len(predictions)}")
    print(f"Correct Predictions:   {correct_predictions}")
    print()
    print(f"✨ Hit Rate (Accuracy): {accuracy:.1f}%")
    print(f"✨ Brier Score:         {avg_brier:.4f}  (lower is better, 0 = perfect)")
    print(f"✨ Log Loss:            {avg_logloss:.4f}  (lower is better, 0 = perfect)")
    print()
    
    # Benchmarks
    print("📊 BENCHMARK COMPARISON")
    print("-" * 70)
    random_brier = 0.667  # Expected Brier for random 3-way prediction
    random_logloss = 1.099  # -log(1/3)
    
    brier_improvement = ((random_brier - avg_brier) / random_brier) * 100
    logloss_improvement = ((random_logloss - avg_logloss) / random_logloss) * 100
    
    print(f"Random Baseline:       Brier={random_brier:.3f}, LogLoss={random_logloss:.3f}")
    print(f"Your Model:            Brier={avg_brier:.3f}, LogLoss={avg_logloss:.3f}")
    print(f"Improvement:           Brier={brier_improvement:+.1f}%, LogLoss={logloss_improvement:+.1f}%")
    print()
    
    # Model rating
    print("🏆 MODEL RATING")
    print("-" * 70)
    
    if avg_brier < 0.15:
        rating = "A+ (Excellent)"
    elif avg_brier < 0.20:
        rating = "A (Very Good)"
    elif avg_brier < 0.25:
        rating = "B (Good)"
    elif avg_brier < 0.30:
        rating = "C (Average)"
    else:
        rating = "D (Needs Improvement)"
    
    print(f"Model Rating:          {rating}")
    print(f"Based on Brier Score:  {avg_brier:.4f}")
    print()
    
    # Confidence analysis
    print("📊 CONFIDENCE ANALYSIS")
    print("-" * 70)
    
    cursor = conn.cursor()
    cursor.execute("""
        SELECT 
            CASE 
                WHEN ps.confidence < 0.3 THEN 'Low (< 0.3)'
                WHEN ps.confidence < 0.5 THEN 'Medium (0.3-0.5)'
                ELSE 'High (> 0.5)'
            END as conf_band,
            COUNT(*) as count,
            AVG(CASE WHEN (
                CASE 
                    WHEN ps.probs_h >= ps.probs_d AND ps.probs_h >= ps.probs_a THEN 'H'
                    WHEN ps.probs_d >= ps.probs_h AND ps.probs_d >= ps.probs_a THEN 'D'
                    ELSE 'A'
                END
            ) = tm.outcome THEN 1.0 ELSE 0.0 END) * 100 as accuracy
        FROM prediction_snapshots ps
        JOIN training_matches tm ON ps.match_id = tm.match_id
        WHERE tm.outcome IN ('H', 'D', 'A')
        GROUP BY conf_band
        ORDER BY conf_band
    """)
    
    conf_analysis = cursor.fetchall()
    cursor.close()
    conn.close()
    
    for band, count, acc in conf_analysis:
        print(f"{band:20} {count:3} predictions, {acc:.1f}% accuracy")
    
    print()
    print("=" * 70)

if __name__ == "__main__":
    test_model_accuracy()
