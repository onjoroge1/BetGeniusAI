#!/usr/bin/env python3

import asyncio
import os
import sys
import numpy as np
import pandas as pd
import psycopg2
from datetime import datetime, timedelta
import json
from typing import Dict, List, Tuple

sys.path.append('.')

async def clv_analysis_system():
    """Analyze CLV (Closing Line Value) opportunities from authentic odds data"""
    print("📈 CLV (CLOSING LINE VALUE) ANALYSIS SYSTEM")
    print("=" * 50)
    print("Analyzing opportunities to improve CLV using authentic bookmaker data")
    
    database_url = os.environ.get('DATABASE_URL')
    
    try:
        with psycopg2.connect(database_url) as conn:
            cursor = conn.cursor()
            
            # 1. Current odds data analysis for CLV opportunities
            print("\n🎯 CURRENT ODDS DATA ANALYSIS")
            print("-" * 30)
            
            # Get authentic odds with timing information
            cursor.execute("""
                SELECT 
                    os.match_id,
                    os.book_id,
                    os.outcome,
                    os.odds_decimal,
                    os.implied_prob,
                    os.secs_to_kickoff,
                    os.created_at,
                    CASE 
                        WHEN os.secs_to_kickoff BETWEEN 3600 AND 7200 THEN 'T-1to2h'
                        WHEN os.secs_to_kickoff BETWEEN 7200 AND 14400 THEN 'T-2to4h' 
                        WHEN os.secs_to_kickoff BETWEEN 14400 AND 43200 THEN 'T-4to12h'
                        WHEN os.secs_to_kickoff BETWEEN 43200 AND 86400 THEN 'T-12to24h'
                        WHEN os.secs_to_kickoff BETWEEN 86400 AND 172800 THEN 'T-24to48h'
                        WHEN os.secs_to_kickoff BETWEEN 172800 AND 259200 THEN 'T-48to72h'
                        ELSE 'Other'
                    END as timing_window
                FROM odds_snapshots os
                WHERE os.created_at > NOW() - INTERVAL '7 days'
                ORDER BY os.match_id, os.book_id, os.outcome
            """)
            
            odds_data = cursor.fetchall()
            print(f"Found {len(odds_data)} odds entries from last 7 days")
            
            if len(odds_data) == 0:
                print("No recent odds data for CLV analysis")
                return
            
            # Convert to DataFrame for analysis
            df = pd.DataFrame(odds_data, columns=[
                'match_id', 'book_id', 'outcome', 'odds_decimal', 'implied_prob', 
                'secs_to_kickoff', 'created_at', 'timing_window'
            ])
            
            # 2. CLV Analysis by Timing Windows
            print(f"\n📊 CLV ANALYSIS BY TIMING WINDOWS")
            print("-" * 40)
            
            timing_analysis = df.groupby('timing_window').agg({
                'odds_decimal': ['mean', 'std', 'min', 'max'],
                'implied_prob': ['mean', 'std'],
                'match_id': 'nunique',
                'book_id': 'nunique'
            }).round(4)
            
            print("Timing window analysis:")
            for window in timing_analysis.index:
                if window != 'Other':
                    window_data = timing_analysis.loc[window]
                    avg_odds = window_data[('odds_decimal', 'mean')]
                    std_odds = window_data[('odds_decimal', 'std')]
                    matches = window_data[('match_id', 'nunique')]
                    bookmakers = window_data[('book_id', 'nunique')]
                    
                    print(f"   • {window}: {matches} matches, {bookmakers} bookmakers")
                    print(f"     Avg odds: {avg_odds:.3f} ± {std_odds:.3f}")
            
            # 3. Bookmaker Efficiency Analysis for CLV
            print(f"\n💰 BOOKMAKER EFFICIENCY FOR CLV")
            print("-" * 35)
            
            # Calculate bookmaker-specific metrics
            bookmaker_analysis = df.groupby('book_id').agg({
                'odds_decimal': ['mean', 'std', 'count'],
                'implied_prob': 'mean',
                'match_id': 'nunique'
            }).round(4)
            
            # Sort by volume (count of odds offered)
            bookmaker_analysis = bookmaker_analysis.sort_values(('odds_decimal', 'count'), ascending=False)
            
            print("Top bookmakers by volume (CLV opportunities):")
            top_bookmakers = bookmaker_analysis.head(10)
            
            for book_id in top_bookmakers.index:
                book_data = top_bookmakers.loc[book_id]
                avg_odds = book_data[('odds_decimal', 'mean')]
                std_odds = book_data[('odds_decimal', 'std')]
                count = book_data[('odds_decimal', 'count')]
                matches = book_data[('match_id', 'nunique')]
                
                print(f"   • Bookmaker {book_id}: {count} odds, {matches} matches")
                print(f"     Avg odds: {avg_odds:.3f} ± {std_odds:.3f}")
            
            # 4. Odds Movement Analysis for CLV Timing
            print(f"\n⏰ ODDS MOVEMENT ANALYSIS")
            print("-" * 30)
            
            # Group by match and outcome to track movement
            match_outcomes = df.groupby(['match_id', 'outcome'])
            
            movements = []
            for (match_id, outcome), group in match_outcomes:
                if len(group) > 1:
                    # Sort by timing (furthest to closest to kickoff)
                    group_sorted = group.sort_values('secs_to_kickoff', ascending=False)
                    
                    early_odds = group_sorted.iloc[0]['odds_decimal']
                    late_odds = group_sorted.iloc[-1]['odds_decimal']
                    
                    if early_odds > 0 and late_odds > 0:
                        movement = (late_odds - early_odds) / early_odds * 100
                        
                        movements.append({
                            'match_id': match_id,
                            'outcome': outcome,
                            'early_odds': early_odds,
                            'late_odds': late_odds,
                            'movement_pct': movement,
                            'early_timing': group_sorted.iloc[0]['timing_window'],
                            'late_timing': group_sorted.iloc[-1]['timing_window']
                        })
            
            if movements:
                movement_df = pd.DataFrame(movements)
                
                print(f"Analyzed {len(movements)} odds movements:")
                print(f"   • Average movement: {movement_df['movement_pct'].mean():.2f}%")
                print(f"   • Positive movements: {(movement_df['movement_pct'] > 0).sum()}")
                print(f"   • Negative movements: {(movement_df['movement_pct'] < 0).sum()}")
                
                # Find best CLV opportunities
                significant_movements = movement_df[abs(movement_df['movement_pct']) > 5]
                print(f"   • Significant movements (>5%): {len(significant_movements)}")
                
                if len(significant_movements) > 0:
                    print("\nTop CLV opportunities:")
                    top_movements = significant_movements.nlargest(5, 'movement_pct')
                    for _, row in top_movements.iterrows():
                        print(f"   • Match {row['match_id']} {row['outcome']}: {row['early_odds']:.3f} → {row['late_odds']:.3f} ({row['movement_pct']:+.1f}%)")
            
            # 5. CLV Strategy Recommendations
            print(f"\n🎯 CLV IMPROVEMENT STRATEGIES")
            print("=" * 40)
            
            print("Based on authentic odds data analysis:")
            
            # Strategy 1: Optimal timing windows
            if not df.empty:
                timing_variance = df.groupby('timing_window')['odds_decimal'].std()
                best_timing = timing_variance.idxmax() if len(timing_variance) > 0 else 'T-48to72h'
                
                print(f"1. **Optimal Timing Window**: {best_timing}")
                print(f"   • Highest odds variance indicates best CLV opportunities")
                print(f"   • Target early positions in this window")
            
            # Strategy 2: Bookmaker selection
            if not bookmaker_analysis.empty:
                # Find bookmakers with highest average odds (potential +CLV)
                high_odds_books = bookmaker_analysis.nlargest(3, ('odds_decimal', 'mean'))
                
                print(f"\n2. **High-Value Bookmakers** (potential +CLV):")
                for book_id in high_odds_books.index:
                    avg_odds = high_odds_books.loc[book_id, ('odds_decimal', 'mean')]
                    print(f"   • Bookmaker {book_id}: {avg_odds:.3f} average odds")
            
            # Strategy 3: Market efficiency patterns
            print(f"\n3. **Market Efficiency Patterns**:")
            print(f"   • Monitor T-48h to T-24h window for sharp money")
            print(f"   • Early T-72h positions often offer better CLV")
            print(f"   • Track closing line vs opening line differentials")
            
            # 6. CLV Tracking System Design
            print(f"\n🔧 CLV TRACKING SYSTEM DESIGN")
            print("-" * 35)
            
            clv_system_design = {
                "data_collection": {
                    "timing_windows": ["T-72h", "T-48h", "T-24h", "T-4h", "T-1h"],
                    "key_bookmakers": list(top_bookmakers.index[:5]) if not top_bookmakers.empty else [],
                    "update_frequency": "Every 4 hours"
                },
                "clv_calculation": {
                    "formula": "(Your_Odds - Closing_Line) / Closing_Line * 100",
                    "benchmark": "Pinnacle closing line (when available)",
                    "threshold": "+2% CLV for actionable opportunities"
                },
                "tracking_metrics": [
                    "Average CLV per bet",
                    "CLV by timing window",
                    "CLV by bookmaker",
                    "CLV by league",
                    "Monthly CLV trend"
                ]
            }
            
            print("Recommended CLV tracking system:")
            print(f"   • Timing windows: {clv_system_design['data_collection']['timing_windows']}")
            print(f"   • Key bookmakers: {len(clv_system_design['data_collection']['key_bookmakers'])} identified")
            print(f"   • CLV threshold: {clv_system_design['clv_calculation']['threshold']}")
            
            # 7. Implementation with current data
            print(f"\n🚀 IMPLEMENTATION WITH CURRENT DATA")
            print("-" * 40)
            
            current_capabilities = {
                "authentic_odds": len(odds_data),
                "timing_windows": len(df['timing_window'].unique()),
                "bookmakers": len(df['book_id'].unique()),
                "matches_tracked": len(df['match_id'].unique()),
                "data_freshness": "Last 7 days"
            }
            
            print("Current CLV analysis capabilities:")
            for key, value in current_capabilities.items():
                print(f"   • {key.replace('_', ' ').title()}: {value}")
            
            # 8. Real-time CLV monitoring recommendations
            print(f"\n📡 REAL-TIME CLV MONITORING")
            print("-" * 35)
            
            print("Implement real-time CLV monitoring:")
            print("1. **Automated Alerts**: Notify when CLV > +3%")
            print("2. **Bookmaker Comparison**: Real-time odds comparison across all sources")
            print("3. **Movement Tracking**: Alert on significant line movements (>5%)")
            print("4. **Historical CLV**: Track your historical CLV performance")
            print("5. **Market Timing**: Optimize bet placement timing based on CLV patterns")
            
            # 9. Save CLV analysis results
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            clv_results_file = f"clv_analysis_results_{timestamp}.json"
            
            clv_analysis_results = {
                'analysis_timestamp': timestamp,
                'data_period': 'Last 7 days',
                'total_odds_analyzed': len(odds_data),
                'timing_windows_available': df['timing_window'].unique().tolist() if not df.empty else [],
                'bookmakers_analyzed': df['book_id'].nunique() if not df.empty else 0,
                'matches_analyzed': df['match_id'].nunique() if not df.empty else 0,
                'movements_detected': len(movements) if movements else 0,
                'clv_system_design': clv_system_design,
                'current_capabilities': current_capabilities,
                'next_steps': [
                    'Implement real-time CLV tracking',
                    'Set up automated alerts for +CLV opportunities',
                    'Optimize bet timing based on movement patterns',
                    'Track historical CLV performance'
                ]
            }
            
            with open(clv_results_file, 'w') as f:
                json.dump(clv_analysis_results, f, indent=2, default=str)
            
            print(f"\n💾 CLV analysis results saved to: {clv_results_file}")
            print(f"✅ CLV analysis completed!")
            
            # 10. Actionable CLV improvements
            print(f"\n🎯 ACTIONABLE CLV IMPROVEMENTS")
            print("=" * 40)
            
            print("Immediate improvements you can implement:")
            print("1. **Early Line Shopping**: Place bets in T-72h to T-48h window")
            print("2. **Multi-Book Strategy**: Compare odds across your top bookmakers")
            print("3. **Movement Alerts**: Set up notifications for favorable line movements")
            print("4. **Closing Line Tracking**: Record closing lines to calculate actual CLV")
            print("5. **League Specialization**: Focus on leagues with highest CLV opportunities")
            
            if movements:
                avg_positive_movement = movement_df[movement_df['movement_pct'] > 0]['movement_pct'].mean()
                print(f"\nPotential CLV gain: {avg_positive_movement:.2f}% average on positive movements")
            
    except Exception as e:
        print(f"❌ Error during CLV analysis: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(clv_analysis_system())