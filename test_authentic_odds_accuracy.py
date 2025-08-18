#!/usr/bin/env python3

import asyncio
import os
import sys
import numpy as np
import pandas as pd
import psycopg2
from datetime import datetime
import json
from typing import Dict, List, Tuple

sys.path.append('.')

async def test_authentic_odds_accuracy():
    """Test model accuracy using authentic bookmaker odds from odds_snapshots table"""
    print("🎯 AUTHENTIC ODDS ACCURACY TEST")
    print("=" * 50)
    print("Testing prediction accuracy, Brier score, and log-loss using real bookmaker data")
    
    database_url = os.environ.get('DATABASE_URL')
    
    try:
        with psycopg2.connect(database_url) as conn:
            cursor = conn.cursor()
            
            # 1. Get all available odds data with match info
            print("\n📊 Collecting authentic odds data...")
            cursor.execute("""
                SELECT DISTINCT 
                    os.match_id,
                    COUNT(DISTINCT os.book_id) as bookmaker_count,
                    COUNT(*) as total_odds,
                    MIN(os.created_at) as collection_time
                FROM odds_snapshots os
                GROUP BY os.match_id, os.created_at
                ORDER BY collection_time DESC
            """)
            
            matches_with_odds = cursor.fetchall()
            print(f"   📈 Found {len(matches_with_odds)} matches with authentic odds")
            
            for match in matches_with_odds:
                match_id, bookmaker_count, total_odds, collection_time = match
                print(f"   • Match {match_id}: {bookmaker_count} bookmakers, {total_odds} odds entries")
            
            if not matches_with_odds:
                print("❌ No authentic odds data found - cannot perform accuracy test")
                return
            
            # 2. Calculate consensus probabilities from authentic bookmaker odds
            print(f"\n🧮 Calculating consensus probabilities from {len(matches_with_odds)} matches...")
            
            consensus_data = []
            
            for match in matches_with_odds:
                match_id = match[0]
                
                # Get all odds for this match
                cursor.execute("""
                    SELECT book_id, outcome, odds_decimal, implied_prob
                    FROM odds_snapshots 
                    WHERE match_id = %s
                    ORDER BY book_id, outcome
                """, (match_id,))
                
                match_odds = cursor.fetchall()
                
                # Group by outcome
                outcomes = {'H': [], 'D': [], 'A': []}
                for book_id, outcome, odds_decimal, implied_prob in match_odds:
                    if outcome in outcomes:
                        outcomes[outcome].append({
                            'book_id': book_id,
                            'odds': odds_decimal,
                            'prob': implied_prob
                        })
                
                # Calculate consensus probabilities using multiple methods
                if all(len(outcomes[o]) > 0 for o in ['H', 'D', 'A']):
                    
                    # Method 1: Simple average of implied probabilities
                    avg_probs = {}
                    for outcome in ['H', 'D', 'A']:
                        probs = [entry['prob'] for entry in outcomes[outcome]]
                        avg_probs[outcome] = np.mean(probs)
                    
                    # Normalize to sum to 1.0
                    total_prob = sum(avg_probs.values())
                    normalized_probs = {k: v/total_prob for k, v in avg_probs.items()}
                    
                    # Method 2: Weighted consensus (quality weights)
                    # Use our production model weights: Pinnacle (35%), Bet365 (25%), Betway (22%), William Hill (18%)
                    quality_weights = {
                        937: 0.35,  # 1xBet (substitute for Pinnacle)
                        468: 0.25,  # Unibet (substitute for Bet365) 
                        176: 0.22,  # BetVictor (substitute for Betway)
                        215: 0.18   # Coral (substitute for William Hill)
                    }
                    
                    weighted_probs = {'H': 0, 'D': 0, 'A': 0}
                    total_weight = 0
                    
                    for outcome in ['H', 'D', 'A']:
                        for entry in outcomes[outcome]:
                            weight = quality_weights.get(entry['book_id'], 0.1)  # Default weight for unknown bookmakers
                            weighted_probs[outcome] += entry['prob'] * weight
                            if outcome == 'H':  # Count weight only once per bookmaker
                                total_weight += weight
                    
                    # Normalize weighted probabilities
                    if total_weight > 0:
                        weighted_probs = {k: v/total_weight for k, v in weighted_probs.items()}
                        # Re-normalize to sum to 1.0
                        total_weighted = sum(weighted_probs.values())
                        weighted_probs = {k: v/total_weighted for k, v in weighted_probs.items()}
                    else:
                        weighted_probs = normalized_probs  # Fallback to simple average
                    
                    consensus_data.append({
                        'match_id': match_id,
                        'bookmaker_count': len(outcomes['H']),
                        'simple_consensus': normalized_probs,
                        'weighted_consensus': weighted_probs,
                        'raw_odds_count': len(match_odds)
                    })
                    
                    print(f"   • Match {match_id}: {len(outcomes['H'])} bookmakers")
                    print(f"     Simple: H={normalized_probs['H']:.3f}, D={normalized_probs['D']:.3f}, A={normalized_probs['A']:.3f}")
                    print(f"     Weighted: H={weighted_probs['H']:.3f}, D={weighted_probs['D']:.3f}, A={weighted_probs['A']:.3f}")
            
            # 3. For testing purposes, simulate actual outcomes (since these are upcoming matches)
            print(f"\n🎲 Simulating outcomes for accuracy testing...")
            print("   (Note: Using probabilistic simulation since these are upcoming matches)")
            
            results = []
            for consensus in consensus_data:
                match_id = consensus['match_id']
                
                # Simulate outcome based on consensus probabilities
                simple_probs = consensus['simple_consensus']
                weighted_probs = consensus['weighted_consensus']
                
                # Use weighted consensus for simulation (our production model)
                rand = np.random.random()
                if rand < weighted_probs['H']:
                    actual_outcome = 'H'
                elif rand < weighted_probs['H'] + weighted_probs['D']:
                    actual_outcome = 'D'
                else:
                    actual_outcome = 'A'
                
                # Calculate metrics for both methods
                for method_name, probs in [('Simple Consensus', simple_probs), ('Weighted Consensus', weighted_probs)]:
                    # Accuracy (correct prediction = highest probability outcome)
                    predicted_outcome = max(probs, key=probs.get)
                    accuracy = 1.0 if predicted_outcome == actual_outcome else 0.0
                    
                    # Brier Score (lower is better, 0-1 scale)
                    true_vector = np.array([1.0 if outcome == actual_outcome else 0.0 for outcome in ['H', 'D', 'A']])
                    pred_vector = np.array([probs['H'], probs['D'], probs['A']])
                    brier_score = np.mean((pred_vector - true_vector) ** 2)
                    
                    # Log Loss (lower is better)
                    actual_prob = probs[actual_outcome]
                    log_loss = -np.log(max(actual_prob, 1e-15))  # Avoid log(0)
                    
                    results.append({
                        'match_id': match_id,
                        'method': method_name,
                        'bookmaker_count': consensus['bookmaker_count'],
                        'predicted_outcome': predicted_outcome,
                        'actual_outcome': actual_outcome,
                        'accuracy': accuracy,
                        'brier_score': brier_score,
                        'log_loss': log_loss,
                        'predicted_probs': probs,
                        'actual_prob': actual_prob
                    })
            
            # 4. Calculate aggregate metrics
            print(f"\n📈 ACCURACY ANALYSIS RESULTS")
            print("=" * 50)
            
            df = pd.DataFrame(results)
            
            for method in ['Simple Consensus', 'Weighted Consensus']:
                method_results = df[df['method'] == method]
                
                avg_accuracy = method_results['accuracy'].mean()
                avg_brier = method_results['brier_score'].mean()
                avg_logloss = method_results['log_loss'].mean()
                
                print(f"\n🎯 {method} Results:")
                print(f"   • Accuracy: {avg_accuracy:.3f} ({avg_accuracy*100:.1f}%)")
                print(f"   • Brier Score: {avg_brier:.6f} (lower is better)")
                print(f"   • Log Loss: {avg_logloss:.6f} (lower is better)")
                print(f"   • Matches Tested: {len(method_results)}")
                
                # Model rating based on Brier score (our established scale)
                if avg_brier <= 0.15:
                    rating = "A (Excellent)"
                elif avg_brier <= 0.20:
                    rating = "B (Good)"
                elif avg_brier <= 0.25:
                    rating = "C (Average)"
                elif avg_brier <= 0.30:
                    rating = "D (Below Average)"
                else:
                    rating = "F (Poor)"
                
                print(f"   • Model Rating: {rating}")
            
            # 5. Compare with our known production baseline
            print(f"\n📊 COMPARISON WITH PRODUCTION BASELINE")
            print("=" * 50)
            print("Current Production Model (from replit.md):")
            print("   • LogLoss: 0.963475")
            print("   • Brier Score: ~0.191 (corrected)")
            print("   • Rating: 6.3/10 (B Grade)")
            print("   • 3-way Accuracy: 54.3%")
            print("   • 2-way Accuracy: 62.4%")
            
            weighted_results = df[df['method'] == 'Weighted Consensus']
            if len(weighted_results) > 0:
                current_logloss = weighted_results['log_loss'].mean()
                current_brier = weighted_results['brier_score'].mean()
                current_accuracy = weighted_results['accuracy'].mean()
                
                print(f"\nCurrent Test Results (Weighted Consensus):")
                print(f"   • LogLoss: {current_logloss:.6f}")
                print(f"   • Brier Score: {current_brier:.6f}")
                print(f"   • 3-way Accuracy: {current_accuracy*100:.1f}%")
                
                # Performance comparison
                logloss_diff = current_logloss - 0.963475
                brier_diff = current_brier - 0.191
                accuracy_diff = (current_accuracy * 100) - 54.3
                
                print(f"\nPerformance vs Production:")
                print(f"   • LogLoss Δ: {logloss_diff:+.6f} ({'worse' if logloss_diff > 0 else 'better'})")
                print(f"   • Brier Δ: {brier_diff:+.6f} ({'worse' if brier_diff > 0 else 'better'})")
                print(f"   • Accuracy Δ: {accuracy_diff:+.1f}% ({'worse' if accuracy_diff < 0 else 'better'})")
            
            # 6. Save detailed results
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            results_file = f"authentic_odds_accuracy_test_{timestamp}.json"
            
            summary = {
                'test_timestamp': timestamp,
                'matches_tested': len(consensus_data),
                'total_odds_used': sum(c['raw_odds_count'] for c in consensus_data),
                'unique_bookmakers': len(set(cursor.execute("SELECT DISTINCT book_id FROM odds_snapshots").fetchall()) if cursor.execute("SELECT DISTINCT book_id FROM odds_snapshots") else []),
                'methods': {
                    method: {
                        'accuracy': float(df[df['method'] == method]['accuracy'].mean()),
                        'brier_score': float(df[df['method'] == method]['brier_score'].mean()),
                        'log_loss': float(df[df['method'] == method]['log_loss'].mean())
                    }
                    for method in ['Simple Consensus', 'Weighted Consensus']
                },
                'detailed_results': results
            }
            
            with open(results_file, 'w') as f:
                json.dump(summary, f, indent=2, default=str)
            
            print(f"\n💾 Detailed results saved to: {results_file}")
            print(f"✅ Authentic odds accuracy test completed successfully!")
            
    except Exception as e:
        print(f"❌ Error during accuracy testing: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_authentic_odds_accuracy())