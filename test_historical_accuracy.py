#!/usr/bin/env python3
"""
Historical Model Accuracy Test - Tests model on historical matches
Uses training_matches data with consensus odds to simulate predictions
"""

import os
import psycopg2
import numpy as np
from typing import Dict
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

def test_historical_accuracy():
    """Test model accuracy using historical consensus predictions"""
    
    print("=" * 70)
    print("🎯 HISTORICAL MODEL ACCURACY TEST - BetGenius AI")
    print("=" * 70)
    print("Testing consensus model on historical matches with actual results")
    print()
    
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    
    # Get historical matches with consensus odds and actual results
    cursor.execute("""
        SELECT 
            oc.match_id,
            oc.ph_cons,
            oc.pd_cons,
            oc.pa_cons,
            tm.outcome,
            tm.home_team,
            tm.away_team,
            COALESCE(lm.league_name, 'Unknown') as league,
            oc.n_books,
            oc.horizon_hours
        FROM odds_consensus oc
        JOIN training_matches tm ON oc.match_id = tm.match_id
        LEFT JOIN league_map lm ON tm.league_id = lm.league_id
        WHERE tm.outcome IN ('H', 'D', 'A')
          AND oc.ph_cons > 0
          AND oc.pd_cons > 0
          AND oc.pa_cons > 0
          AND oc.horizon_hours BETWEEN 24 AND 72  -- Use 24-72h window like production
        ORDER BY RANDOM()
        LIMIT 500
    """)
    
    matches = cursor.fetchall()
    
    if not matches:
        print("❌ No historical matches with consensus odds found!")
        print("\nTrying alternative: Check training_matches for any results...")
        
        cursor.execute("""
            SELECT COUNT(*) as total,
                   COUNT(CASE WHEN outcome IN ('H','D','A') THEN 1 END) as with_results
            FROM training_matches
        """)
        stats = cursor.fetchone()
        print(f"Training matches: {stats[0]} total, {stats[1]} with results")
        
        cursor.close()
        conn.close()
        return
    
    print(f"📊 Found {len(matches)} historical matches with consensus odds\n")
    
    # Calculate metrics
    brier_scores = []
    log_losses = []
    correct_predictions = 0
    
    for row in matches:
        match_id, p_h, p_d, p_a, actual, home, away, league, n_books, horizon = row
        
        # Normalize probabilities
        total = p_h + p_d + p_a
        if total > 0:
            p_h = p_h / total
            p_d = p_d / total
            p_a = p_a / total
        
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
        
        # Print first 5 samples
        if len(brier_scores) <= 5:
            result_emoji = "✅" if predicted == actual else "❌"
            print(f"{result_emoji} {home} vs {away} ({league})")
            print(f"   Predicted: {predicted} ({probs[predicted]:.3f}) | Actual: {actual}")
            print(f"   Odds from {n_books} books at T-{horizon}h")
            print(f"   Brier: {brier:.4f} | LogLoss: {logloss:.4f}")
            print()
    
    # Calculate aggregate metrics
    avg_brier = np.mean(brier_scores)
    avg_logloss = np.mean(log_losses)
    accuracy = (correct_predictions / len(matches)) * 100
    
    print("=" * 70)
    print("📈 OVERALL METRICS")
    print("=" * 70)
    print()
    print(f"Total Matches Tested:  {len(matches)}")
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
    print(f"Consensus Model:       Brier={avg_brier:.3f}, LogLoss={avg_logloss:.3f}")
    print(f"Improvement:           Brier={brier_improvement:+.1f}%, LogLoss={logloss_improvement:+.1f}%")
    print()
    
    # Model rating
    print("🏆 MODEL RATING")
    print("-" * 70)
    
    if avg_brier < 0.15:
        rating = "A+ (Excellent)"
        grade = 9.5
    elif avg_brier < 0.18:
        rating = "A (Very Good)"
        grade = 8.5
    elif avg_brier < 0.22:
        rating = "B+ (Good)"
        grade = 7.5
    elif avg_brier < 0.25:
        rating = "B (Above Average)"
        grade = 6.5
    elif avg_brier < 0.30:
        rating = "C (Average)"
        grade = 5.5
    else:
        rating = "D (Needs Improvement)"
        grade = 4.0
    
    print(f"Model Rating:          {rating} ({grade}/10)")
    print(f"Based on Brier Score:  {avg_brier:.4f}")
    print()
    
    # League breakdown
    print("📊 LEAGUE BREAKDOWN")
    print("-" * 70)
    
    cursor.execute("""
        SELECT 
            COALESCE(lm.league_name, 'Unknown') as league,
            COUNT(*) as matches,
            AVG(CASE WHEN (
                CASE 
                    WHEN oc.ph_cons >= oc.pd_cons AND oc.ph_cons >= oc.pa_cons THEN 'H'
                    WHEN oc.pd_cons >= oc.ph_cons AND oc.pd_cons >= oc.pa_cons THEN 'D'
                    ELSE 'A'
                END
            ) = tm.outcome THEN 1.0 ELSE 0.0 END) * 100 as accuracy
        FROM odds_consensus oc
        JOIN training_matches tm ON oc.match_id = tm.match_id
        LEFT JOIN league_map lm ON tm.league_id = lm.league_id
        WHERE tm.outcome IN ('H', 'D', 'A')
          AND oc.ph_cons > 0 AND oc.pd_cons > 0 AND oc.pa_cons > 0
        GROUP BY lm.league_name
        HAVING COUNT(*) >= 10
        ORDER BY accuracy DESC
        LIMIT 10
    """)
    
    league_stats = cursor.fetchall()
    
    for league, count, acc in league_stats:
        print(f"{league:30} {count:4} matches, {acc:.1f}% accuracy")
    
    cursor.close()
    conn.close()
    
    print()
    print("=" * 70)
    print("💡 NOTE: Future predictions will be automatically tracked and")
    print("   accuracy calculated when matches complete (every 6 hours)")
    print("=" * 70)

if __name__ == "__main__":
    test_historical_accuracy()
