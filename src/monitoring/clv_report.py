"""
CLV (Closing Line Value) Reporting for Timing Window Optimization
"""

import numpy as np
import pandas as pd
import psycopg2
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import json
import yaml
import warnings
warnings.filterwarnings('ignore')

class CLVReporter:
    """Generate CLV reports for timing window optimization"""
    
    def __init__(self, config_path: str = 'config/leagues.yml'):
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)
        
        self.euro_leagues = {
            39: 'English Premier League',
            140: 'La Liga Santander', 
            135: 'Serie A',
            78: 'Bundesliga',
            61: 'Ligue 1'
        }
        
        self.time_windows = ['24h', '12h', '6h', '3h', '1h', '30m', '5m']
    
    def get_db_connection(self):
        """Get database connection"""
        return psycopg2.connect(os.environ['DATABASE_URL'])
    
    def calculate_clv_for_window(self, predictions_df: pd.DataFrame, 
                                window: str, lookback_days: int = 14) -> Dict:
        """Calculate CLV for specific timing window"""
        
        # Filter predictions for this window
        window_preds = predictions_df[
            (predictions_df['time_bucket'] == window) &
            (predictions_df['match_date_utc'] >= datetime.now() - timedelta(days=lookback_days))
        ].copy()
        
        if len(window_preds) == 0:
            return {
                'window': window,
                'total_predictions': 0,
                'clv_available': 0,
                'avg_clv': 0.0,
                'positive_clv_rate': 0.0,
                'median_clv': 0.0,
                'clv_p25': 0.0,
                'clv_p75': 0.0,
                'volume_score': 0.0
            }
        
        # Simulate CLV calculation (in production, would use actual closing odds)
        clv_values = []
        
        for _, pred in window_preds.iterrows():
            # Get predicted outcome
            probs = [pred['consensus_h'], pred['consensus_d'], pred['consensus_a']]
            predicted_outcome = np.argmax(probs)
            predicted_prob = probs[predicted_outcome]
            
            # Simulate opening vs closing odds movement
            # In practice, this would compare prediction time odds to closing odds
            opening_implied = predicted_prob + np.random.normal(0, 0.02)  # Add noise
            closing_implied = predicted_prob + np.random.normal(0, 0.01)  # Closing is more accurate
            
            # CLV = (Opening odds - Closing odds) / Closing odds
            if closing_implied > 0.05:  # Valid probability
                opening_odds = 1 / max(opening_implied, 0.05)
                closing_odds = 1 / closing_implied
                
                clv = (opening_odds - closing_odds) / closing_odds
                clv_values.append(clv)
        
        if not clv_values:
            return {
                'window': window,
                'total_predictions': len(window_preds),
                'clv_available': 0,
                'avg_clv': 0.0,
                'positive_clv_rate': 0.0,
                'median_clv': 0.0,
                'clv_p25': 0.0,
                'clv_p75': 0.0,
                'volume_score': 0.0
            }
        
        clv_array = np.array(clv_values)
        
        return {
            'window': window,
            'total_predictions': len(window_preds),
            'clv_available': len(clv_values),
            'avg_clv': float(np.mean(clv_array)),
            'positive_clv_rate': float(np.mean(clv_array > 0)),
            'median_clv': float(np.median(clv_array)),
            'clv_p25': float(np.percentile(clv_array, 25)),
            'clv_p75': float(np.percentile(clv_array, 75)),
            'volume_score': len(clv_values) / 100.0  # Normalize volume
        }
    
    def generate_clv_report(self, windows: List[str] = None, 
                           lookback_days: int = 14) -> Dict:
        """Generate comprehensive CLV report"""
        
        if windows is None:
            windows = self.time_windows
        
        print(f"🔍 Generating CLV Report (last {lookback_days} days)")
        
        # Load consensus predictions
        conn = self.get_db_connection()
        
        query = """
        SELECT 
            cp.match_id,
            cp.time_bucket,
            cp.consensus_h,
            cp.consensus_d,
            cp.consensus_a,
            cp.dispersion_h,
            cp.dispersion_d,
            cp.dispersion_a,
            cp.n_books,
            m.league_id,
            m.match_date_utc,
            m.outcome
        FROM consensus_predictions cp
        JOIN matches m ON cp.match_id = m.match_id
        WHERE m.match_date_utc >= %s
          AND m.match_date_utc <= %s
          AND m.league_id IN (39, 140, 135, 78, 61)
          AND cp.time_bucket = ANY(%s)
        ORDER BY m.match_date_utc DESC
        """
        
        start_date = datetime.now() - timedelta(days=lookback_days)
        end_date = datetime.now()
        
        df = pd.read_sql_query(query, conn, params=[start_date, end_date, windows])
        conn.close()
        
        if len(df) == 0:
            print("No consensus predictions found for CLV analysis")
            return {'error': 'No data available'}
        
        print(f"Analyzing {len(df)} predictions across {len(windows)} windows")
        
        # Generate CLV analysis per league and window
        clv_results = {}
        
        for league_id in self.euro_leagues.keys():
            league_name = self.euro_leagues[league_id]
            league_data = df[df['league_id'] == league_id]
            
            if len(league_data) == 0:
                continue
            
            clv_results[league_id] = {
                'league_name': league_name,
                'total_matches': len(league_data),
                'windows': {}
            }
            
            for window in windows:
                clv_stats = self.calculate_clv_for_window(league_data, window, lookback_days)
                clv_results[league_id]['windows'][window] = clv_stats
            
            # Find optimal window for this league
            valid_windows = {
                w: stats for w, stats in clv_results[league_id]['windows'].items()
                if stats['clv_available'] >= 5  # Minimum sample size
            }
            
            if valid_windows:
                # Score windows by CLV * volume
                window_scores = {
                    w: stats['positive_clv_rate'] * stats['volume_score']
                    for w, stats in valid_windows.items()
                }
                
                optimal_window = max(window_scores, key=window_scores.get)
                clv_results[league_id]['optimal_window'] = optimal_window
                clv_results[league_id]['optimal_clv_rate'] = valid_windows[optimal_window]['positive_clv_rate']
            else:
                clv_results[league_id]['optimal_window'] = '24h'  # Default
                clv_results[league_id]['optimal_clv_rate'] = 0.0
        
        # Overall summary
        all_windows_summary = {}
        for window in windows:
            window_data = []
            for league_stats in clv_results.values():
                if isinstance(league_stats, dict) and window in league_stats.get('windows', {}):
                    window_stats = league_stats['windows'][window]
                    if window_stats['clv_available'] > 0:
                        window_data.append(window_stats)
            
            if window_data:
                all_windows_summary[window] = {
                    'avg_clv': np.mean([w['avg_clv'] for w in window_data]),
                    'avg_positive_rate': np.mean([w['positive_clv_rate'] for w in window_data]),
                    'total_volume': sum([w['clv_available'] for w in window_data]),
                    'leagues_with_data': len(window_data)
                }
        
        return {
            'clv_by_league': clv_results,
            'overall_summary': all_windows_summary,
            'lookback_days': lookback_days,
            'analysis_date': datetime.now().isoformat(),
            'windows_analyzed': windows
        }
    
    def generate_html_report(self, clv_data: Dict, output_path: str):
        """Generate HTML CLV report"""
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>CLV Shadow Report - BetGenius AI</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 40px; }}
                .header {{ background: #f8f9fa; padding: 20px; border-radius: 8px; margin-bottom: 30px; }}
                .league {{ margin-bottom: 30px; border: 1px solid #ddd; border-radius: 8px; padding: 20px; }}
                .optimal {{ background: #e8f5e8; }}
                .warning {{ background: #fff3cd; }}
                .danger {{ background: #f8d7da; }}
                table {{ width: 100%; border-collapse: collapse; margin-top: 15px; }}
                th, td {{ padding: 8px 12px; text-align: left; border-bottom: 1px solid #ddd; }}
                th {{ background: #f8f9fa; font-weight: bold; }}
                .metric {{ display: inline-block; margin: 10px 20px 10px 0; }}
                .metric-value {{ font-size: 24px; font-weight: bold; }}
                .metric-label {{ font-size: 12px; color: #666; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>CLV Shadow Report</h1>
                <p><strong>Generated:</strong> {clv_data.get('analysis_date', 'Unknown')}</p>
                <p><strong>Lookback Period:</strong> {clv_data.get('lookback_days', 14)} days</p>
                <p><strong>Target:</strong> CLV ≥ 55% for production launch</p>
            </div>
        """
        
        # Overall summary
        overall = clv_data.get('overall_summary', {})
        if overall:
            html_content += "<h2>Overall Summary by Window</h2><table>"
            html_content += "<tr><th>Window</th><th>Avg CLV</th><th>Positive Rate</th><th>Volume</th><th>Leagues</th><th>Status</th></tr>"
            
            for window, stats in overall.items():
                positive_rate = stats['avg_positive_rate']
                status = "✅ READY" if positive_rate >= 0.55 else "⚠️ NEEDS WORK"
                status_class = "optimal" if positive_rate >= 0.55 else "warning"
                
                html_content += f"""
                <tr class="{status_class}">
                    <td><strong>{window}</strong></td>
                    <td>{stats['avg_clv']:+.1%}</td>
                    <td>{positive_rate:.1%}</td>
                    <td>{stats['total_volume']}</td>
                    <td>{stats['leagues_with_data']}</td>
                    <td>{status}</td>
                </tr>
                """
            
            html_content += "</table>"
        
        # League-specific analysis
        html_content += "<h2>League-Specific Analysis</h2>"
        
        clv_by_league = clv_data.get('clv_by_league', {})
        for league_id, league_data in clv_by_league.items():
            if not isinstance(league_data, dict):
                continue
            
            league_name = league_data['league_name']
            optimal_window = league_data.get('optimal_window', 'Unknown')
            optimal_clv_rate = league_data.get('optimal_clv_rate', 0.0)
            
            # Determine status
            if optimal_clv_rate >= 0.55:
                status_class = "optimal"
                status_text = "✅ LAUNCH READY"
            elif optimal_clv_rate >= 0.45:
                status_class = "warning"
                status_text = "⚠️ NEEDS TUNING"
            else:
                status_class = "danger"
                status_text = "❌ NOT READY"
            
            html_content += f"""
            <div class="league {status_class}">
                <h3>{league_name}</h3>
                <div class="metric">
                    <div class="metric-value">{optimal_window}</div>
                    <div class="metric-label">Optimal Window</div>
                </div>
                <div class="metric">
                    <div class="metric-value">{optimal_clv_rate:.1%}</div>
                    <div class="metric-label">CLV Positive Rate</div>
                </div>
                <div class="metric">
                    <div class="metric-value">{status_text}</div>
                    <div class="metric-label">Launch Status</div>
                </div>
                
                <table>
                    <tr><th>Window</th><th>Volume</th><th>Avg CLV</th><th>Positive Rate</th><th>Median</th><th>P25-P75</th></tr>
            """
            
            windows_data = league_data.get('windows', {})
            for window, stats in windows_data.items():
                if stats['clv_available'] == 0:
                    continue
                
                html_content += f"""
                <tr>
                    <td>{window}</td>
                    <td>{stats['clv_available']}</td>
                    <td>{stats['avg_clv']:+.1%}</td>
                    <td>{stats['positive_clv_rate']:.1%}</td>
                    <td>{stats['median_clv']:+.1%}</td>
                    <td>{stats['clv_p25']:+.1%} to {stats['clv_p75']:+.1%}</td>
                </tr>
                """
            
            html_content += "</table></div>"
        
        html_content += """
            <div class="header" style="margin-top: 40px;">
                <h3>Launch Recommendations</h3>
                <ul>
                    <li><strong>Ready for Launch:</strong> Leagues with CLV ≥ 55% in optimal window</li>
                    <li><strong>Needs Tuning:</strong> Adjust edge thresholds or timing windows</li>
                    <li><strong>Not Ready:</strong> Insufficient volume or poor CLV performance</li>
                </ul>
                <p><em>Note: CLV values are simulated for demonstration. Production system would use actual closing odds.</em></p>
            </div>
        </body>
        </html>
        """
        
        with open(output_path, 'w') as f:
            f.write(html_content)
        
        print(f"✅ HTML CLV report saved: {output_path}")

def main():
    """Generate CLV shadow report"""
    
    reporter = CLVReporter()
    
    # Generate CLV analysis
    windows = ['24h', '12h', '6h', '3h', '1h', '30m', '5m']
    clv_data = reporter.generate_clv_report(windows, lookback_days=14)
    
    if 'error' in clv_data:
        print(f"❌ CLV Report failed: {clv_data['error']}")
        return
    
    # Create reports directory
    os.makedirs('reports', exist_ok=True)
    
    # Generate HTML report
    html_path = 'reports/CLV_SHADOW_REPORT.html'
    reporter.generate_html_report(clv_data, html_path)
    
    # Save JSON data
    json_path = 'reports/CLV_SHADOW_DATA.json'
    with open(json_path, 'w') as f:
        json.dump(clv_data, f, indent=2, default=str)
    
    # Print summary
    print("\n" + "="*60)
    print("CLV SHADOW REPORT SUMMARY")
    print("="*60)
    
    clv_by_league = clv_data.get('clv_by_league', {})
    for league_id, league_data in clv_by_league.items():
        if not isinstance(league_data, dict):
            continue
        
        league_name = league_data['league_name']
        optimal_window = league_data.get('optimal_window', 'Unknown')
        optimal_clv_rate = league_data.get('optimal_clv_rate', 0.0)
        
        status = "✅ READY" if optimal_clv_rate >= 0.55 else "⚠️ TUNE" if optimal_clv_rate >= 0.45 else "❌ NOT READY"
        
        print(f"{league_name}: {optimal_window} window, {optimal_clv_rate:.1%} CLV rate {status}")
    
    print(f"\n📊 Reports generated:")
    print(f"   HTML: {html_path}")
    print(f"   JSON: {json_path}")
    
    return clv_data

if __name__ == "__main__":
    main()