#!/usr/bin/env python3
"""
Validate Market Baseline with TimeSeriesSplit

This script measures the accuracy of using market probabilities alone (no ML model)
with the same TimeSeriesSplit validation used for training.

Expected result: 48-52% accuracy (market should be reasonably calibrated)

If market baseline is significantly different:
- Too low (e.g., 45%): Odds quality issues or distribution skew
- Too high (e.g., 55%): Potential data leakage (using post-kickoff odds)

Usage:
    python scripts/validate_market_baseline.py
"""

import os
import sys
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from sqlalchemy import create_engine, text
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import accuracy_score, log_loss, brier_score_loss

sys.path.append('.')


def validate_market_baseline():
    """
    Measure market-only performance using TimeSeriesSplit
    """
    print("="*70)
    print("  MARKET BASELINE VALIDATION")
    print("="*70)
    print("Measuring market probability accuracy with same CV as model training")
    print("")
    
    database_url = os.getenv('DATABASE_URL')
    engine = create_engine(database_url)
    
    # Load matches with market probabilities
    query = text("""
        SELECT 
            tm.match_id,
            tm.match_date,
            tm.outcome,
            orc.ph_cons as p_home,
            orc.pd_cons as p_draw,
            orc.pa_cons as p_away,
            orc.n_books
        FROM training_matches tm
        INNER JOIN match_context mc ON tm.match_id = mc.match_id
        INNER JOIN odds_real_consensus orc ON tm.match_id = orc.match_id
        WHERE tm.match_date >= '2025-08-18'
          AND tm.match_date < '2025-12-31'
          AND tm.match_date IS NOT NULL
          AND tm.outcome IS NOT NULL
        ORDER BY RANDOM()
    """)
    
    with engine.connect() as conn:
        df = pd.read_sql(query, conn)
    
    print(f"✅ Loaded {len(df)} matches with market probabilities\n")
    
    # Check probability sums
    df['prob_sum'] = df['p_home'] + df['p_draw'] + df['p_away']
    print(f"📊 Probability sum statistics:")
    print(f"   Min: {df['prob_sum'].min():.4f}")
    print(f"   Mean: {df['prob_sum'].mean():.4f}")
    print(f"   Max: {df['prob_sum'].max():.4f}")
    print(f"   Std: {df['prob_sum'].std():.4f}")
    
    # Normalize probabilities (remove bookmaker margin)
    df['p_home_norm'] = df['p_home'] / df['prob_sum']
    df['p_draw_norm'] = df['p_draw'] / df['prob_sum']
    df['p_away_norm'] = df['p_away'] / df['prob_sum']
    
    # Sort by date for TimeSeriesSplit
    df = df.sort_values('match_date').reset_index(drop=True)
    
    # Prepare labels
    outcome_map = {'H': 0, 'D': 1, 'A': 2, 'Home': 0, 'Draw': 1, 'Away': 2}
    y = df['outcome'].map(outcome_map)
    
    # Market probabilities as predictions
    market_probs = df[['p_home_norm', 'p_draw_norm', 'p_away_norm']].values
    
    # TimeSeriesSplit (same as training)
    print("\n" + "="*70)
    print("  TIME-BASED CROSS-VALIDATION (5-Fold)")
    print("="*70)
    
    tscv = TimeSeriesSplit(n_splits=5)
    dates = pd.to_datetime(df['match_date'])
    
    fold_results = []
    
    for fold_idx, (train_idx, valid_idx) in enumerate(tscv.split(df), 1):
        # Get validation set
        y_valid = y.iloc[valid_idx]
        probs_valid = market_probs[valid_idx]
        dates_valid = dates.iloc[valid_idx]
        
        # Calculate metrics
        y_pred = probs_valid.argmax(axis=1)
        accuracy = accuracy_score(y_valid, y_pred)
        logloss = log_loss(y_valid, probs_valid)
        
        # Brier score (multiclass)
        y_onehot = np.zeros((len(y_valid), 3))
        y_onehot[np.arange(len(y_valid)), y_valid] = 1
        brier = np.mean(np.sum((probs_valid - y_onehot)**2, axis=1))
        
        fold_results.append({
            'fold': fold_idx,
            'n_valid': len(valid_idx),
            'date_min': dates_valid.min(),
            'date_max': dates_valid.max(),
            'accuracy': accuracy,
            'logloss': logloss,
            'brier': brier
        })
        
        print(f"\nFold {fold_idx}:")
        print(f"   Valid samples: {len(valid_idx)}")
        print(f"   Date range: {dates_valid.min().date()} to {dates_valid.max().date()}")
        print(f"   Accuracy: {accuracy:.4f} ({accuracy*100:.2f}%)")
        print(f"   LogLoss: {logloss:.4f}")
        print(f"   Brier: {brier:.4f}")
    
    # Overall results
    results_df = pd.DataFrame(fold_results)
    avg_accuracy = results_df['accuracy'].mean()
    avg_logloss = results_df['logloss'].mean()
    avg_brier = results_df['brier'].mean()
    
    print("\n" + "="*70)
    print("  OVERALL MARKET BASELINE")
    print("="*70)
    print(f"\n📊 Average OOF Metrics:")
    print(f"   Accuracy: {avg_accuracy:.4f} ({avg_accuracy*100:.2f}%)")
    print(f"   LogLoss: {avg_logloss:.4f}")
    print(f"   Brier: {avg_brier:.4f}")
    
    # Interpretation
    print("\n" + "="*70)
    print("  INTERPRETATION")
    print("="*70)
    
    if 0.48 <= avg_accuracy <= 0.52:
        print("✅ Market baseline is within expected range (48-52%)")
        print("   This suggests:")
        print("   - Odds data quality is good")
        print("   - No obvious distribution skew")
        print("   - Market is reasonably calibrated")
    elif avg_accuracy < 0.48:
        print(f"⚠️  Market baseline is LOW ({avg_accuracy*100:.1f}%)")
        print("   Possible reasons:")
        print("   1. Dataset has unusual outcome distribution (more upsets)")
        print("   2. Odds normalization issues")
        print("   3. Bookmaker margin not properly handled")
        print("   4. Data quality issues in odds_real_consensus")
        print("\n   🔍 Action items:")
        print("   - Check outcome distribution (H/D/A percentages)")
        print("   - Verify odds normalization logic")
        print("   - Inspect matches with largest market errors")
    elif avg_accuracy > 0.52:
        print(f"⚠️  Market baseline is HIGH ({avg_accuracy*100:.1f}%)")
        print("   Possible reasons:")
        print("   1. DATA LEAKAGE: Using post-kickoff odds")
        print("   2. Dataset favors favorites (many mismatches)")
        print("   3. Temporal issues in odds extraction")
        print("\n   🔍 Action items:")
        print("   - CRITICAL: Verify odds_real_consensus uses pre-KO odds only")
        print("   - Check secs_to_kickoff distribution")
        print("   - Inspect matches with highest market accuracy")
    
    # Compare to model performance
    print("\n" + "="*70)
    print("  MODEL vs MARKET COMPARISON")
    print("="*70)
    print(f"\nModel OOF Accuracy: 49.51%")
    print(f"Market OOF Accuracy: {avg_accuracy*100:.2f}%")
    print(f"Model Lift: {(0.4951 - avg_accuracy)*100:+.2f}pp")
    
    if 0.4951 > avg_accuracy:
        lift_pp = (0.4951 - avg_accuracy) * 100
        print(f"\n✅ Model is beating market by {lift_pp:.2f}pp")
        print("   This is POSITIVE - model is learning signal beyond market")
    else:
        print(f"\n❌ Model is NOT beating market")
        print("   This suggests:")
        print("   - Model may not be adding value")
        print("   - Need better features or tuning")
        print("   - Consider if market baseline is accurate")
    
    # Save results
    results_df.to_csv('market_baseline_results.csv', index=False)
    print(f"\n💾 Results saved to: market_baseline_results.csv")
    
    return results_df


if __name__ == '__main__':
    validate_market_baseline()
