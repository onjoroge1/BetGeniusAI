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

async def comprehensive_accuracy_test():
    """Comprehensive accuracy test using all available authentic data"""
    print("🎯 COMPREHENSIVE ACCURACY TEST - BetGenius AI")
    print("=" * 60)
    print("Testing prediction accuracy using authentic bookmaker odds data")
    
    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        print("❌ DATABASE_URL is not set.")
        return
    
    # Stable, repeatable simulations during development
    np.random.seed(42)
    
    try:
        with psycopg2.connect(database_url) as conn:
            cursor = conn.cursor()
            
            # 1. Test 1: Current Authentic Odds from odds_snapshots
            print("\n📊 TEST 1: Current Authentic Odds (odds_snapshots)")
            print("-" * 40)
            
            # One row per match: use the most recent snapshot timestamp for each match
            cursor.execute("""
                WITH last_ts AS (
                  SELECT match_id, MAX(created_at) AS created_at
                  FROM odds_snapshots
                  GROUP BY match_id
                )
                SELECT 
                    s.match_id,
                    COUNT(DISTINCT s.book_id) AS bookmakers,
                    AVG(CASE WHEN s.outcome = 'H' THEN s.implied_prob END) AS avg_home_prob,
                    AVG(CASE WHEN s.outcome = 'D' THEN s.implied_prob END) AS avg_draw_prob,
                    AVG(CASE WHEN s.outcome = 'A' THEN s.implied_prob END) AS avg_away_prob,
                    MAX(s.created_at) AS collection_time
                FROM odds_snapshots s
                JOIN last_ts t 
                  ON t.match_id = s.match_id
                 AND t.created_at = s.created_at
                GROUP BY s.match_id
                ORDER BY collection_time DESC
            """)
            
            current_odds = cursor.fetchall()
            print(f"Found {len(current_odds)} matches with current authentic odds")
            
            current_results = []
            for match in current_odds:
                match_id, bookmakers, home_prob, draw_prob, away_prob, collection_time = match
                
                if all(p is not None for p in [home_prob, draw_prob, away_prob]):
                    # Normalize probabilities
                    total = home_prob + draw_prob + away_prob
                    if total > 0:
                        norm_probs = {
                            'H': home_prob / total,
                            'D': draw_prob / total,
                            'A': away_prob / total
                        }
                        
                        predicted = max(norm_probs, key=norm_probs.get)
                        max_prob = max(norm_probs.values())
                        
                        current_results.append({
                            'match_id': match_id,
                            'bookmakers': bookmakers,
                            'predicted_outcome': predicted,
                            'probabilities': norm_probs,
                            'confidence': max_prob,
                            'data_source': 'odds_snapshots'
                        })
                        
                        print(f"   Match {match_id}: {bookmakers} bookmakers, predicted {predicted} ({max_prob:.3f})")
            
            # 2. Test 2: Historical Consensus Data
            print(f"\n📊 TEST 2: Historical Consensus (odds_consensus)")
            print("-" * 40)
            
            cursor.execute("""
                SELECT 
                    oc.match_id,
                    oc.ph_cons as home_prob,
                    oc.pd_cons as draw_prob,
                    oc.pa_cons as away_prob,
                    oc.horizon_hours,
                    oc.n_books as bookmaker_count,
                    oc.created_at
                FROM odds_consensus oc
                WHERE oc.ph_cons IS NOT NULL 
                  AND oc.pd_cons IS NOT NULL 
                  AND oc.pa_cons IS NOT NULL
                  AND oc.ph_cons > 0 
                  AND oc.pd_cons > 0 
                  AND oc.pa_cons > 0
                ORDER BY oc.created_at DESC
                LIMIT 20
            """)
            
            consensus_data = cursor.fetchall()
            print(f"Found {len(consensus_data)} matches with consensus probabilities")
            
            consensus_results = []
            for match in consensus_data:
                match_id, home_prob, draw_prob, away_prob, horizon_hours, bookmaker_count, created_at = match
                
                # Normalize probabilities
                total = home_prob + draw_prob + away_prob
                if total > 0:
                    norm_probs = {
                        'H': home_prob / total,
                        'D': draw_prob / total,
                        'A': away_prob / total
                    }
                    
                    predicted = max(norm_probs, key=norm_probs.get)
                    max_prob = max(norm_probs.values())
                    
                    consensus_results.append({
                        'match_id': match_id,
                        'bookmakers': bookmaker_count,
                        'predicted_outcome': predicted,
                        'probabilities': norm_probs,
                        'confidence': max_prob,
                        'horizon_hours': horizon_hours,
                        'data_source': 'odds_consensus'
                    })
                    
                    print(f"   Match {match_id}: T-{horizon_hours}h, {bookmaker_count} books, predicted {predicted} ({max_prob:.3f})")
            
            # 3. Real Accuracy Test (No Simulation)
            print(f"\n📊 TEST 3: Real Match Results (odds_accuracy_evaluation)")
            print("-" * 40)
            
            # Query the unified view for matches with actual results
            cursor.execute("""
                SELECT 
                    match_id,
                    n_books,
                    ph_snapshot,
                    pd_snapshot,
                    pa_snapshot,
                    ph_close,
                    pd_close,
                    pa_close,
                    actual_outcome,
                    home_goals,
                    away_goals,
                    has_closing_odds,
                    league
                FROM odds_accuracy_evaluation
                WHERE has_result = TRUE
                ORDER BY match_id
            """)
            
            real_matches = cursor.fetchall()
            
            if len(real_matches) == 0:
                print("⚠️  No matches with results found yet - using simulated outcomes for testing")
                print("   (Real accuracy testing will activate once Oct 3-4 matches complete)")
                
                # Fallback to simulation for current development
                all_results = current_results + consensus_results
                if len(all_results) == 0:
                    print("No prediction data available for testing")
                    return
                
                test_results = []
                for result in all_results:
                    probs = result['probabilities']
                    rand = np.random.random()
                    if rand < probs['H']:
                        actual_outcome = 'H'
                    elif rand < probs['H'] + probs['D']:
                        actual_outcome = 'D'
                    else:
                        actual_outcome = 'A'
                    
                    predicted_outcome = result['predicted_outcome']
                    accuracy = 1.0 if predicted_outcome == actual_outcome else 0.0
                    true_vector = np.array([1.0 if outcome == actual_outcome else 0.0 for outcome in ['H', 'D', 'A']])
                    pred_vector = np.array([probs['H'], probs['D'], probs['A']])
                    brier_score = np.mean((pred_vector - true_vector) ** 2)
                    actual_prob = probs[actual_outcome]
                    log_loss = -np.log(max(actual_prob, 1e-15))
                    
                    test_results.append({
                        'match_id': result['match_id'],
                        'data_source': 'simulated',
                        'bookmakers': result['bookmakers'],
                        'predicted_outcome': predicted_outcome,
                        'actual_outcome': actual_outcome,
                        'accuracy': accuracy,
                        'brier_score': brier_score,
                        'log_loss': log_loss,
                        'confidence': result['confidence'],
                        'probabilities': probs,
                        'clv': None
                    })
            else:
                print(f"✅ Found {len(real_matches)} matches with real results!")
                
                test_results = []
                
                for match in real_matches:
                    match_id, n_books, ph, pd_snap, pa, ph_close, pd_close, pa_close, actual_outcome, home_goals, away_goals, has_closing, league = match
                    
                    # Normalize probabilities
                    total = ph + pd_snap + pa
                    if total > 0:
                        norm_probs = {
                            'H': ph / total,
                            'D': pd_snap / total,
                            'A': pa / total
                        }
                        
                        predicted_outcome = max(norm_probs, key=norm_probs.get)
                        max_prob = max(norm_probs.values())
                        
                        # Calculate metrics
                        accuracy = 1.0 if predicted_outcome == actual_outcome else 0.0
                        
                        # Brier Score
                        true_vector = np.array([1.0 if outcome == actual_outcome else 0.0 for outcome in ['H', 'D', 'A']])
                        pred_vector = np.array([norm_probs['H'], norm_probs['D'], norm_probs['A']])
                        brier_score = np.mean((pred_vector - true_vector) ** 2)
                        
                        # Log Loss
                        actual_prob = norm_probs[actual_outcome]
                        log_loss = -np.log(max(actual_prob, 1e-15))
                        
                        # CLV (if closing odds available)
                        clv = None
                        if has_closing and all(x is not None for x in [ph_close, pd_close, pa_close]):
                            close_total = ph_close + pd_close + pa_close
                            if close_total > 0:
                                norm_close = {
                                    'H': ph_close / close_total,
                                    'D': pd_close / close_total,
                                    'A': pa_close / close_total
                                }
                                # CLV = closing prob - snapshot prob for actual outcome
                                clv = (norm_close[actual_outcome] - norm_probs[actual_outcome]) * 100
                        
                        test_results.append({
                            'match_id': match_id,
                            'data_source': 'real_results',
                            'bookmakers': n_books,
                            'predicted_outcome': predicted_outcome,
                            'actual_outcome': actual_outcome,
                            'accuracy': accuracy,
                            'brier_score': brier_score,
                            'log_loss': log_loss,
                            'confidence': max_prob,
                            'probabilities': norm_probs,
                            'clv': clv,
                            'league': league,
                            'score': f"{home_goals}-{away_goals}"
                        })
                        
                        clv_str = f", CLV: {clv:+.1f}%" if clv is not None else ""
                        result_emoji = "✅" if accuracy == 1.0 else "❌"
                        print(f"   {result_emoji} Match {match_id}: {home_goals}-{away_goals} (actual: {actual_outcome}, pred: {predicted_outcome}){clv_str}")
            
            # 4. Calculate Performance Metrics
            print(f"\n📈 PERFORMANCE ANALYSIS")
            print("=" * 60)
            
            df = pd.DataFrame(test_results)
            
            # Overall metrics
            overall_accuracy = df['accuracy'].mean()
            overall_brier = df['brier_score'].mean()
            overall_logloss = df['log_loss'].mean()
            overall_confidence = df['confidence'].mean()
            
            print(f"\n🎯 Overall Results ({len(test_results)} predictions):")
            print(f"   • 3-way Accuracy: {overall_accuracy:.3f} ({overall_accuracy*100:.1f}%)")
            print(f"   • Brier Score: {overall_brier:.6f}")
            print(f"   • Log Loss: {overall_logloss:.6f}")
            print(f"   • Average Confidence: {overall_confidence:.3f}")
            
            # Model grading
            if overall_brier <= 0.15:
                grade = "A+ (Excellent)"
                score = 9.5
            elif overall_brier <= 0.18:
                grade = "A (Very Good)"
                score = 8.5
            elif overall_brier <= 0.191:  # Current production baseline
                grade = "A- (Good)"
                score = 8.0
            elif overall_brier <= 0.20:
                grade = "B+ (Above Average)"
                score = 7.5
            elif overall_brier <= 0.25:
                grade = "B (Average)"
                score = 6.5
            elif overall_brier <= 0.30:
                grade = "C (Below Average)"
                score = 5.5
            else:
                grade = "D (Poor)"
                score = 4.0
            
            print(f"   • Model Grade: {grade}")
            print(f"   • Model Score: {score:.1f}/10")
            
            # Breakdown by data source
            print(f"\n📊 Data Source:")
            is_real = df['data_source'].iloc[0] == 'real_results' if len(df) > 0 else False
            if is_real:
                print(f"   ✅ REAL MATCH RESULTS (No simulation)")
                print(f"   • {len(df)} matches with actual outcomes")
                print(f"   • {df['bookmakers'].mean():.1f} avg bookmakers per match")
                
                # CLV Analysis (if available)
                clv_data = df[df['clv'].notna()]
                if len(clv_data) > 0:
                    avg_clv = clv_data['clv'].mean()
                    print(f"\n💰 Closing Line Value (CLV):")
                    print(f"   • {len(clv_data)} matches with closing odds")
                    print(f"   • Average CLV: {avg_clv:+.2f}%")
                    positive_clv = len(clv_data[clv_data['clv'] > 0])
                    print(f"   • Positive CLV: {positive_clv}/{len(clv_data)} ({positive_clv/len(clv_data)*100:.1f}%)")
            else:
                print(f"   ⚠️  SIMULATED OUTCOMES (No real results yet)")
                for source in ['odds_snapshots', 'odds_consensus']:
                    source_data = df[df['data_source'] == source]
                    if len(source_data) > 0:
                        source_accuracy = source_data['accuracy'].mean()
                        source_brier = source_data['brier_score'].mean()
                        source_count = len(source_data)
                        avg_books = source_data['bookmakers'].mean()
                        print(f"   • {source} ({source_count} matches, {avg_books:.1f} avg bookmakers):")
                        print(f"     Accuracy: {source_accuracy*100:.1f}%, Brier: {source_brier:.4f}")
            
            # Confidence analysis
            print(f"\n🎯 Confidence Analysis:")
            high_conf = df[df['confidence'] > 0.6]
            med_conf = df[(df['confidence'] > 0.4) & (df['confidence'] <= 0.6)]
            low_conf = df[df['confidence'] <= 0.4]
            
            for conf_df, conf_label, conf_key in [
                (high_conf, "High (>60%)", "high"),
                (med_conf,  "Medium (40-60%)", "medium"), 
                (low_conf,  "Low (≤40%)", "low"),
            ]:
                if len(conf_df) > 0:
                    conf_accuracy = conf_df['accuracy'].mean()
                    conf_brier    = conf_df['brier_score'].mean()
                    conf_count    = len(conf_df)
                    avg_conf      = conf_df['confidence'].mean()
                    print(f"   • {conf_label} confidence ({conf_count} matches, avg {avg_conf:.3f}):")
                    print(f"     Accuracy: {conf_accuracy*100:.1f}%, Brier: {conf_brier:.4f}")
            
            # 5. Compare with Production Baseline
            print(f"\n📊 COMPARISON WITH PRODUCTION MODEL")
            print("=" * 60)
            print("Current Production Baseline (from replit.md):")
            print("   • LogLoss: 0.963475")
            print("   • Brier Score: 0.191")
            print("   • 3-way Accuracy: 54.3%")
            print("   • Rating: 6.3/10 (B Grade)")
            
            print(f"\nAuthentic Data Test Results:")
            print(f"   • LogLoss: {overall_logloss:.6f}")
            print(f"   • Brier Score: {overall_brier:.6f}")
            print(f"   • 3-way Accuracy: {overall_accuracy*100:.1f}%")
            print(f"   • Rating: {score:.1f}/10")
            
            # Performance deltas
            logloss_delta = overall_logloss - 0.963475
            brier_delta = overall_brier - 0.191
            accuracy_delta = (overall_accuracy * 100) - 54.3
            
            print(f"\nPerformance vs Production:")
            print(f"   • LogLoss Δ: {logloss_delta:+.6f} ({'better' if logloss_delta < 0 else 'worse'})")
            print(f"   • Brier Δ: {brier_delta:+.6f} ({'better' if brier_delta < 0 else 'worse'})")
            print(f"   • Accuracy Δ: {accuracy_delta:+.1f}% ({'better' if accuracy_delta > 0 else 'worse'})")
            
            improvement_status = "IMPROVED" if (logloss_delta < 0 and brier_delta < 0) else "MIXED" if (logloss_delta < 0 or brier_delta < 0) else "NEEDS WORK"
            print(f"   • Overall Assessment: {improvement_status}")
            
            # 6. Save Results
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            results_file = f"comprehensive_accuracy_test_{timestamp}.json"
            
            summary = {
                'test_timestamp': timestamp,
                'test_type': 'comprehensive_authentic_data',
                'predictions_tested': len(test_results),
                'data_sources': {
                    'odds_snapshots': len(current_results),
                    'odds_consensus': len(consensus_results)
                },
                'overall_metrics': {
                    'accuracy_3way': float(overall_accuracy),
                    'brier_score': float(overall_brier),
                    'log_loss': float(overall_logloss),
                    'model_score': float(score),
                    'model_grade': grade
                },
                'vs_production': {
                    'logloss_delta': float(logloss_delta),
                    'brier_delta': float(brier_delta),
                    'accuracy_delta': float(accuracy_delta),
                    'assessment': improvement_status
                },
                'confidence_breakdown': {
                    'high_confidence': {
                        'count': len(high_conf),
                        'accuracy': float(high_conf['accuracy'].mean()) if len(high_conf) > 0 else 0,
                        'brier': float(high_conf['brier_score'].mean()) if len(high_conf) > 0 else 0
                    },
                    'medium_confidence': {
                        'count': len(med_conf),
                        'accuracy': float(med_conf['accuracy'].mean()) if len(med_conf) > 0 else 0,
                        'brier': float(med_conf['brier_score'].mean()) if len(med_conf) > 0 else 0
                    },
                    'low_confidence': {
                        'count': len(low_conf),
                        'accuracy': float(low_conf['accuracy'].mean()) if len(low_conf) > 0 else 0,
                        'brier': float(low_conf['brier_score'].mean()) if len(low_conf) > 0 else 0
                    }
                },
                'detailed_results': test_results
            }
            
            # Keep numpy numerics as real numbers in JSON
            def _py(v):
                if isinstance(v, (np.floating, np.float32, np.float64)): return float(v)
                if isinstance(v, (np.integer,  np.int32,   np.int64)):   return int(v)
                return v
            summary['detailed_results'] = [{k: _py(v) for k, v in r.items()} for r in test_results]
            
            with open(results_file, 'w') as f:
                json.dump(summary, f, indent=2, default=str)
            
            print(f"\n💾 Detailed results saved to: {results_file}")
            print(f"✅ Comprehensive accuracy test completed!")
            print(f"\n🔍 Key Insights:")
            print(f"   • Using authentic bookmaker data from {len(set([r['data_source'] for r in test_results]))} sources")
            print(f"   • Average {df['bookmakers'].mean():.1f} bookmakers per prediction")
            print(f"   • {improvement_status.lower()} performance vs production baseline")
            if overall_brier < 0.191:
                print(f"   • Model shows potential for production deployment")
            
    except Exception as e:
        print(f"❌ Error during comprehensive accuracy testing: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(comprehensive_accuracy_test())