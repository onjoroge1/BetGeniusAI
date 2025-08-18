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

async def test_historical_consensus_accuracy():
    """Test consensus model accuracy using historical data from odds_consensus table"""
    print("🎯 HISTORICAL CONSENSUS ACCURACY TEST")
    print("=" * 50)
    print("Testing prediction accuracy using historical odds_consensus data with known outcomes")
    
    database_url = os.environ.get('DATABASE_URL')
    
    try:
        with psycopg2.connect(database_url) as conn:
            cursor = conn.cursor()
            
            # 1. Get historical matches with consensus odds and known outcomes
            print("\n📊 Collecting historical matches with consensus odds...")
            cursor.execute("""
                SELECT 
                    oc.match_id,
                    oc.home_team,
                    oc.away_team,
                    oc.league_id,
                    oc.consensus_home_prob,
                    oc.consensus_draw_prob,
                    oc.consensus_away_prob,
                    oc.final_result,
                    oc.created_at
                FROM odds_consensus oc
                WHERE 
                    oc.final_result IS NOT NULL 
                    AND oc.consensus_home_prob IS NOT NULL
                    AND oc.consensus_draw_prob IS NOT NULL
                    AND oc.consensus_away_prob IS NOT NULL
                ORDER BY oc.created_at DESC
                LIMIT 50
            """)
            
            historical_matches = cursor.fetchall()
            print(f"   📈 Found {len(historical_matches)} historical matches with complete data")
            
            if len(historical_matches) == 0:
                print("❌ No historical matches with consensus odds found")
                return
            
            # 2. Calculate accuracy metrics for each match
            print(f"\n🧮 Calculating accuracy metrics...")
            
            results = []
            
            for match in historical_matches:
                (match_id, home_team, away_team, league_id, 
                 home_prob, draw_prob, away_prob, final_result, created_at) = match
                
                # Normalize probabilities (ensure they sum to 1.0)
                total_prob = home_prob + draw_prob + away_prob
                if total_prob > 0:
                    norm_home = home_prob / total_prob
                    norm_draw = draw_prob / total_prob
                    norm_away = away_prob / total_prob
                else:
                    continue
                
                probs = {'H': norm_home, 'D': norm_draw, 'A': norm_away}
                
                # Determine predicted outcome (highest probability)
                predicted_outcome = max(probs, key=probs.get)
                
                # Map final_result to our outcome format
                if final_result == 'H':
                    actual_outcome = 'H'
                elif final_result == 'D':
                    actual_outcome = 'D'
                elif final_result == 'A':
                    actual_outcome = 'A'
                else:
                    continue  # Skip if outcome format is unclear
                
                # Calculate metrics
                accuracy = 1.0 if predicted_outcome == actual_outcome else 0.0
                
                # Brier Score
                true_vector = np.array([1.0 if outcome == actual_outcome else 0.0 for outcome in ['H', 'D', 'A']])
                pred_vector = np.array([norm_home, norm_draw, norm_away])
                brier_score = np.mean((pred_vector - true_vector) ** 2)
                
                # Log Loss
                actual_prob = probs[actual_outcome]
                log_loss = -np.log(max(actual_prob, 1e-15))  # Avoid log(0)
                
                # Confidence level
                max_prob = max(probs.values())
                confidence = "High" if max_prob > 0.6 else "Medium" if max_prob > 0.4 else "Low"
                
                results.append({
                    'match_id': match_id,
                    'home_team': home_team,
                    'away_team': away_team,
                    'league_id': league_id,
                    'predicted_outcome': predicted_outcome,
                    'actual_outcome': actual_outcome,
                    'accuracy': accuracy,
                    'brier_score': brier_score,
                    'log_loss': log_loss,
                    'max_probability': max_prob,
                    'confidence_level': confidence,
                    'predicted_probs': probs,
                    'actual_prob': actual_prob,
                    'created_at': created_at
                })
                
                print(f"   • Match {match_id}: {home_team} vs {away_team}")
                print(f"     Predicted: {predicted_outcome} ({max_prob:.3f}), Actual: {actual_outcome}")
                print(f"     Accuracy: {'✓' if accuracy == 1.0 else '✗'}, Brier: {brier_score:.4f}, LogLoss: {log_loss:.4f}")
            
            if len(results) == 0:
                print("❌ No valid results calculated")
                return
            
            # 3. Calculate aggregate metrics
            print(f"\n📈 AGGREGATE PERFORMANCE METRICS")
            print("=" * 50)
            
            df = pd.DataFrame(results)
            
            # Overall metrics
            overall_accuracy = df['accuracy'].mean()
            overall_brier = df['brier_score'].mean()
            overall_logloss = df['log_loss'].mean()
            
            print(f"Overall Results ({len(results)} matches):")
            print(f"   • 3-way Accuracy: {overall_accuracy:.3f} ({overall_accuracy*100:.1f}%)")
            print(f"   • Brier Score: {overall_brier:.6f}")
            print(f"   • Log Loss: {overall_logloss:.6f}")
            
            # Model rating
            if overall_brier <= 0.15:
                rating = "A+ (Excellent)"
                grade = 9.0
            elif overall_brier <= 0.191:  # Our current production baseline
                rating = "A (Very Good)"
                grade = 8.0
            elif overall_brier <= 0.20:
                rating = "B+ (Good)"
                grade = 7.0
            elif overall_brier <= 0.25:
                rating = "B (Average)"
                grade = 6.0
            elif overall_brier <= 0.30:
                rating = "C (Below Average)"
                grade = 5.0
            else:
                rating = "D (Poor)"
                grade = 4.0
                
            print(f"   • Model Rating: {rating} ({grade}/10)")
            
            # Confidence-based breakdown
            print(f"\nBreakdown by Confidence Level:")
            for confidence in ['High', 'Medium', 'Low']:
                conf_data = df[df['confidence_level'] == confidence]
                if len(conf_data) > 0:
                    conf_accuracy = conf_data['accuracy'].mean()
                    conf_count = len(conf_data)
                    avg_prob = conf_data['max_probability'].mean()
                    print(f"   • {confidence} Confidence ({conf_count} matches, avg prob {avg_prob:.3f}): {conf_accuracy*100:.1f}% accuracy")
            
            # League-based breakdown
            print(f"\nBreakdown by League:")
            for league_id in sorted(df['league_id'].unique()):
                league_data = df[df['league_id'] == league_id]
                league_accuracy = league_data['accuracy'].mean()
                league_count = len(league_data)
                league_brier = league_data['brier_score'].mean()
                print(f"   • League {league_id} ({league_count} matches): {league_accuracy*100:.1f}% accuracy, {league_brier:.4f} Brier")
            
            # 4. Compare with production baseline
            print(f"\n📊 COMPARISON WITH PRODUCTION BASELINE")
            print("=" * 50)
            print("Production Model (from replit.md):")
            print("   • LogLoss: 0.963475")
            print("   • Brier Score: 0.191 (corrected)")
            print("   • Rating: 6.3/10 (B Grade)")
            print("   • 3-way Accuracy: 54.3%")
            
            print(f"\nHistorical Test Results:")
            print(f"   • LogLoss: {overall_logloss:.6f}")
            print(f"   • Brier Score: {overall_brier:.6f}")
            print(f"   • 3-way Accuracy: {overall_accuracy*100:.1f}%")
            print(f"   • Rating: {grade:.1f}/10")
            
            # Performance comparison
            logloss_diff = overall_logloss - 0.963475
            brier_diff = overall_brier - 0.191
            accuracy_diff = (overall_accuracy * 100) - 54.3
            
            print(f"\nPerformance vs Production:")
            print(f"   • LogLoss Δ: {logloss_diff:+.6f} ({'worse' if logloss_diff > 0 else 'better'})")
            print(f"   • Brier Δ: {brier_diff:+.6f} ({'worse' if brier_diff > 0 else 'better'})")
            print(f"   • Accuracy Δ: {accuracy_diff:+.1f}% ({'worse' if accuracy_diff < 0 else 'better'})")
            
            # 5. Calculate 2-way accuracy (Home/Away only, excluding draws)
            non_draw_results = df[df['actual_outcome'] != 'D']
            if len(non_draw_results) > 0:
                # For 2-way accuracy, we need to re-normalize probabilities excluding draw
                two_way_accuracy = 0
                two_way_count = 0
                
                for _, row in non_draw_results.iterrows():
                    home_prob = row['predicted_probs']['H']
                    away_prob = row['predicted_probs']['A']
                    total_non_draw = home_prob + away_prob
                    
                    if total_non_draw > 0:
                        norm_home = home_prob / total_non_draw
                        norm_away = away_prob / total_non_draw
                        
                        predicted_2way = 'H' if norm_home > norm_away else 'A'
                        actual_2way = row['actual_outcome']
                        
                        if predicted_2way == actual_2way:
                            two_way_accuracy += 1
                        two_way_count += 1
                
                if two_way_count > 0:
                    two_way_acc_pct = (two_way_accuracy / two_way_count) * 100
                    print(f"   • 2-way Accuracy: {two_way_acc_pct:.1f}% ({two_way_accuracy}/{two_way_count} non-draw matches)")
            
            # 6. Save detailed results
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            results_file = f"historical_consensus_accuracy_test_{timestamp}.json"
            
            summary = {
                'test_timestamp': timestamp,
                'matches_tested': len(results),
                'data_source': 'odds_consensus table (historical)',
                'overall_metrics': {
                    'accuracy_3way': float(overall_accuracy),
                    'brier_score': float(overall_brier),
                    'log_loss': float(overall_logloss),
                    'model_rating': f"{grade}/10",
                    'model_grade': rating
                },
                'comparison_vs_production': {
                    'logloss_delta': float(logloss_diff),
                    'brier_delta': float(brier_diff),
                    'accuracy_delta': float(accuracy_diff)
                },
                'detailed_results': results
            }
            
            with open(results_file, 'w') as f:
                json.dump(summary, f, indent=2, default=str)
            
            print(f"\n💾 Detailed results saved to: {results_file}")
            print(f"✅ Historical consensus accuracy test completed!")
            
    except Exception as e:
        print(f"❌ Error during historical accuracy testing: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_historical_consensus_accuracy())