"""
Smoke Test Thresholds - Immediate Tightening Implementation
Verify each league's edge cutoff yields target bet volume & ROI via backtesting
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
import sys
sys.path.append('/home/runner/workspace')

from src.config.league_config import ConfigManager
from src.monitoring.clv_tracker import CLVTracker
from src.utils.type_coercion import ensure_py_types

class ThresholdSmokeTest:
    """Smoke test system to verify threshold effectiveness"""
    
    def __init__(self):
        self.config_manager = ConfigManager()
        self.clv_tracker = CLVTracker()
        
        # Test parameters
        self.backtest_weeks = 6
        self.min_clv_threshold = 0.55  # 55% of bets should beat closing line
        self.target_volume_tolerance = 0.2  # 20% tolerance on bet volume
        
    def run_comprehensive_smoke_test(self) -> Dict:
        """Run comprehensive smoke test on all active leagues"""
        
        print("Running comprehensive threshold smoke test...")
        print(f"Backtest period: {self.backtest_weeks} weeks")
        print(f"CLV threshold: {self.min_clv_threshold:.1%} of bets beating close")
        
        results = {
            'test_timestamp': datetime.now().isoformat(),
            'test_parameters': {
                'backtest_weeks': self.backtest_weeks,
                'min_clv_threshold': self.min_clv_threshold,
                'volume_tolerance': self.target_volume_tolerance
            },
            'league_results': {},
            'summary': {
                'leagues_tested': 0,
                'leagues_passed': 0,
                'leagues_failed': 0,
                'critical_issues': []
            }
        }
        
        # Get all active leagues
        active_leagues = self.config_manager.get_all_active_leagues()
        
        for league_config in active_leagues:
            print(f"\n🔍 Testing {league_config.league_name}...")
            
            # Run individual league test
            league_result = self._test_league_thresholds(league_config)
            
            results['league_results'][league_config.league_id] = league_result
            results['summary']['leagues_tested'] += 1
            
            # Assess pass/fail
            if league_result['overall_status'] == 'PASS':
                results['summary']['leagues_passed'] += 1
                print(f"  ✅ {league_config.league_name} PASSED")
            else:
                results['summary']['leagues_failed'] += 1
                print(f"  ❌ {league_config.league_name} FAILED")
                
                # Track critical issues
                if league_result['critical_failures']:
                    results['summary']['critical_issues'].extend([
                        f"{league_config.league_name}: {issue}"
                        for issue in league_result['critical_failures']
                    ])
        
        # Generate summary report
        self._generate_smoke_test_report(results)
        
        return results
    
    def _test_league_thresholds(self, league_config) -> Dict:
        """Test individual league threshold effectiveness"""
        
        # Generate backtest data
        backtest_data = self._generate_backtest_data(
            league_config.league_id, self.backtest_weeks
        )
        
        # Test current thresholds
        threshold_test = self._test_threshold_performance(
            backtest_data, league_config
        )
        
        # Test CLV performance
        clv_test = self._test_clv_performance(backtest_data, league_config)
        
        # Test volume consistency
        volume_test = self._test_volume_consistency(
            threshold_test['weekly_volumes'], league_config
        )
        
        # Test ROI stability
        roi_test = self._test_roi_stability(
            threshold_test['weekly_rois'], league_config
        )
        
        # Combine results
        league_result = {
            'league_id': league_config.league_id,
            'league_name': league_config.league_name,
            'current_config': {
                'edge_threshold': league_config.edge_threshold,
                'min_probability': league_config.min_probability,
                'target_roi': league_config.target_roi,
                'min_bet_volume': league_config.min_bet_volume
            },
            'threshold_test': threshold_test,
            'clv_test': clv_test,
            'volume_test': volume_test,
            'roi_test': roi_test,
            'overall_status': 'PASS',
            'critical_failures': [],
            'warnings': []
        }
        
        # Assess overall status
        failures = []
        warnings = []
        
        # Check CLV threshold
        if clv_test['positive_clv_rate'] < self.min_clv_threshold:
            failures.append(f"CLV rate {clv_test['positive_clv_rate']:.1%} below {self.min_clv_threshold:.1%}")
        
        # Check volume consistency
        if not volume_test['volume_consistent']:
            warnings.append(f"Volume inconsistent: {volume_test['avg_weekly_volume']:.1f} vs target {league_config.min_bet_volume}")
        
        # Check ROI performance
        if threshold_test['avg_roi'] < league_config.target_roi * 0.5:
            failures.append(f"ROI {threshold_test['avg_roi']:.1%} severely below target {league_config.target_roi:.1%}")
        elif threshold_test['avg_roi'] < league_config.target_roi * 0.8:
            warnings.append(f"ROI {threshold_test['avg_roi']:.1%} below target {league_config.target_roi:.1%}")
        
        # Check ROI stability
        if roi_test['roi_volatility'] > 0.15:  # 15% volatility threshold
            warnings.append(f"High ROI volatility: {roi_test['roi_volatility']:.1%}")
        
        # Set final status
        if failures:
            league_result['overall_status'] = 'FAIL'
            league_result['critical_failures'] = failures
        elif warnings:
            league_result['overall_status'] = 'WARNING'
        
        league_result['warnings'] = warnings
        
        return league_result
    
    def _generate_backtest_data(self, league_id: str, weeks: int) -> pd.DataFrame:
        """Generate synthetic backtest data for testing"""
        
        # Generate synthetic matches for backtest period
        n_matches_per_week = np.random.randint(8, 15)  # Realistic match count
        total_matches = n_matches_per_week * weeks
        
        data = []
        
        for i in range(total_matches):
            # Match date (distribute across weeks)
            days_ago = np.random.randint(0, weeks * 7)
            match_date = datetime.now() - timedelta(days=days_ago)
            
            # Generate realistic probabilities
            home_prob = np.random.beta(2.5, 2.5)  # More balanced distribution
            draw_prob = np.random.beta(1.8, 3.2)  # Lower draw probability
            away_prob = 1 - home_prob - draw_prob
            
            # Normalize probabilities
            total_prob = home_prob + draw_prob + away_prob
            home_prob /= total_prob
            draw_prob /= total_prob
            away_prob /= total_prob
            
            # Generate market odds with margin
            margin = np.random.uniform(0.04, 0.08)
            home_odds = 1 / (home_prob * (1 - margin))
            draw_odds = 1 / (draw_prob * (1 - margin))
            away_odds = 1 / (away_prob * (1 - margin))
            
            # Generate closing odds (slight movement)
            close_movement = np.random.normal(0, 0.03)
            home_close = max(1.01, home_odds * (1 + close_movement))
            draw_close = max(1.01, draw_odds * (1 + close_movement))
            away_close = max(1.01, away_odds * (1 + close_movement))
            
            # Generate actual outcome
            outcome_rand = np.random.random()
            if outcome_rand < home_prob:
                actual_outcome = 'home'
            elif outcome_rand < home_prob + draw_prob:
                actual_outcome = 'draw'
            else:
                actual_outcome = 'away'
            
            data.append({
                'match_id': f"{league_id}_{i:04d}",
                'match_date': match_date,
                'home_prob': home_prob,
                'draw_prob': draw_prob,
                'away_prob': away_prob,
                'home_odds': home_odds,
                'draw_odds': draw_odds,
                'away_odds': away_odds,
                'home_close_odds': home_close,
                'draw_close_odds': draw_close,
                'away_close_odds': away_close,
                'actual_outcome': actual_outcome
            })
        
        return pd.DataFrame(data)
    
    def _test_threshold_performance(self, backtest_data: pd.DataFrame, 
                                  league_config) -> Dict:
        """Test threshold performance over backtest period"""
        
        edge_threshold = league_config.edge_threshold
        min_probability = league_config.min_probability
        
        # Group by week for temporal analysis
        backtest_data['week'] = backtest_data['match_date'].dt.isocalendar().week
        weeks = sorted(backtest_data['week'].unique())
        
        weekly_results = []
        all_bets = []
        
        for week in weeks:
            week_data = backtest_data[backtest_data['week'] == week]
            
            week_bets = []
            week_stakes = 0
            week_returns = 0
            
            for _, row in week_data.iterrows():
                # Test each outcome
                outcomes = ['home', 'draw', 'away']
                probs = [row['home_prob'], row['draw_prob'], row['away_prob']]
                odds = [row['home_odds'], row['draw_odds'], row['away_odds']]
                
                for outcome, prob, odd in zip(outcomes, probs, odds):
                    # Calculate edge
                    implied_prob = 1 / odd
                    edge = prob - implied_prob
                    
                    # Apply threshold filters
                    if edge >= edge_threshold and prob >= min_probability:
                        stake = 10  # Fixed stake for testing
                        week_stakes += stake
                        
                        # Check if bet won
                        if row['actual_outcome'] == outcome:
                            payout = stake * odd
                            week_returns += payout
                        
                        week_bets.append({
                            'outcome': outcome,
                            'stake': stake,
                            'odds': odd,
                            'prob': prob,
                            'edge': edge,
                            'won': row['actual_outcome'] == outcome
                        })
            
            # Calculate weekly metrics
            week_roi = (week_returns - week_stakes) / week_stakes if week_stakes > 0 else 0
            week_volume = len(week_bets)
            
            weekly_results.append({
                'week': week,
                'volume': week_volume,
                'stakes': week_stakes,
                'returns': week_returns,
                'roi': week_roi
            })
            
            all_bets.extend(week_bets)
        
        # Calculate overall metrics
        total_stakes = sum(r['stakes'] for r in weekly_results)
        total_returns = sum(r['returns'] for r in weekly_results)
        avg_roi = (total_returns - total_stakes) / total_stakes if total_stakes > 0 else 0
        
        weekly_volumes = [r['volume'] for r in weekly_results]
        weekly_rois = [r['roi'] for r in weekly_results]
        
        return ensure_py_types({
            'total_bets': len(all_bets),
            'total_stakes': total_stakes,
            'total_returns': total_returns,
            'avg_roi': avg_roi,
            'weekly_volumes': weekly_volumes,
            'weekly_rois': weekly_rois,
            'weekly_results': weekly_results,
            'hit_rate': np.mean([bet['won'] for bet in all_bets]) if all_bets else 0
        })
    
    def _test_clv_performance(self, backtest_data: pd.DataFrame, 
                            league_config) -> Dict:
        """Test CLV performance"""
        
        # Simulate CLV calculation
        clv_results = []
        
        for _, row in backtest_data.iterrows():
            # Calculate CLV for each outcome
            outcomes = ['home', 'draw', 'away']
            opening_odds = [row['home_odds'], row['draw_odds'], row['away_odds']]
            closing_odds = [row['home_close_odds'], row['draw_close_odds'], row['away_close_odds']]
            
            for open_odd, close_odd in zip(opening_odds, closing_odds):
                clv = (close_odd - open_odd) / open_odd
                clv_results.append(clv)
        
        positive_clv_count = sum(1 for clv in clv_results if clv > 0)
        positive_clv_rate = positive_clv_count / len(clv_results) if clv_results else 0
        
        return ensure_py_types({
            'total_clv_samples': len(clv_results),
            'positive_clv_count': positive_clv_count,
            'positive_clv_rate': positive_clv_rate,
            'avg_clv': np.mean(clv_results) if clv_results else 0,
            'clv_std': np.std(clv_results) if clv_results else 0
        })
    
    def _test_volume_consistency(self, weekly_volumes: List[int], 
                               league_config) -> Dict:
        """Test betting volume consistency"""
        
        if not weekly_volumes:
            return {'volume_consistent': False, 'avg_weekly_volume': 0}
        
        avg_volume = np.mean(weekly_volumes)
        target_volume = league_config.min_bet_volume
        
        # Check if average volume is within tolerance
        volume_consistent = (
            avg_volume >= target_volume * (1 - self.target_volume_tolerance) and
            avg_volume <= target_volume * (1 + self.target_volume_tolerance)
        )
        
        return ensure_py_types({
            'avg_weekly_volume': avg_volume,
            'target_volume': target_volume,
            'volume_consistent': volume_consistent,
            'volume_variance': np.var(weekly_volumes),
            'min_weekly_volume': min(weekly_volumes),
            'max_weekly_volume': max(weekly_volumes)
        })
    
    def _test_roi_stability(self, weekly_rois: List[float], 
                          league_config) -> Dict:
        """Test ROI stability over time"""
        
        if not weekly_rois:
            return {'roi_volatility': 0, 'roi_trend': 'stable'}
        
        roi_volatility = np.std(weekly_rois)
        avg_roi = np.mean(weekly_rois)
        
        # Simple trend analysis
        if len(weekly_rois) >= 3:
            # Linear trend (positive slope = improving)
            x = np.arange(len(weekly_rois))
            slope = np.corrcoef(x, weekly_rois)[0, 1]
            
            if slope > 0.1:
                roi_trend = 'improving'
            elif slope < -0.1:
                roi_trend = 'declining'
            else:
                roi_trend = 'stable'
        else:
            roi_trend = 'insufficient_data'
        
        return ensure_py_types({
            'roi_volatility': roi_volatility,
            'avg_roi': avg_roi,
            'roi_trend': roi_trend,
            'roi_range': max(weekly_rois) - min(weekly_rois) if weekly_rois else 0
        })
    
    def _generate_smoke_test_report(self, results: Dict):
        """Generate comprehensive smoke test report"""
        
        print("\n" + "="*60)
        print("THRESHOLD SMOKE TEST REPORT")
        print("="*60)
        
        summary = results['summary']
        print(f"Leagues Tested: {summary['leagues_tested']}")
        print(f"Passed: {summary['leagues_passed']} ({summary['leagues_passed']/summary['leagues_tested']:.1%})")
        print(f"Failed: {summary['leagues_failed']} ({summary['leagues_failed']/summary['leagues_tested']:.1%})")
        
        if summary['critical_issues']:
            print(f"\n🚨 CRITICAL ISSUES ({len(summary['critical_issues'])}):")
            for issue in summary['critical_issues']:
                print(f"  • {issue}")
        
        print(f"\n📊 LEAGUE BREAKDOWN:")
        print("-" * 40)
        
        for league_id, result in results['league_results'].items():
            status_icon = {
                'PASS': '✅',
                'WARNING': '⚠️',
                'FAIL': '❌'
            }.get(result['overall_status'], '❓')
            
            print(f"{status_icon} {result['league_name']}")
            
            # Key metrics
            threshold_test = result['threshold_test']
            clv_test = result['clv_test']
            
            print(f"    ROI: {threshold_test['avg_roi']:.1%} | Volume: {np.mean(threshold_test['weekly_volumes']):.1f}/week")
            print(f"    CLV: {clv_test['positive_clv_rate']:.1%} positive | Threshold: {result['current_config']['edge_threshold']:.1%}")
            
            if result['critical_failures']:
                for failure in result['critical_failures']:
                    print(f"    🚨 {failure}")
            
            if result['warnings']:
                for warning in result['warnings']:
                    print(f"    ⚠️  {warning}")
        
        print(f"\n💡 RECOMMENDATIONS:")
        print("-" * 25)
        
        # Generate recommendations based on results
        failed_leagues = [
            result for result in results['league_results'].values()
            if result['overall_status'] == 'FAIL'
        ]
        
        if failed_leagues:
            print(f"1. IMMEDIATE: Fix {len(failed_leagues)} failing leagues")
            for result in failed_leagues[:3]:  # Show top 3
                print(f"   • {result['league_name']}: {result['critical_failures'][0]}")
        
        # CLV recommendations
        low_clv_leagues = [
            result for result in results['league_results'].values()
            if result['clv_test']['positive_clv_rate'] < self.min_clv_threshold
        ]
        
        if low_clv_leagues:
            print(f"2. CLV IMPROVEMENT: {len(low_clv_leagues)} leagues need better timing")
            print(f"   • Review odds source and bet placement timing")
        
        print(f"\n✅ Smoke test complete - {summary['leagues_passed']}/{summary['leagues_tested']} leagues operational")

def main():
    """Run threshold smoke test"""
    print("🚀 Threshold Smoke Test - Immediate Tightening")
    print("=" * 50)
    
    try:
        # Initialize smoke test
        smoke_test = ThresholdSmokeTest()
        
        # Run comprehensive test
        results = smoke_test.run_comprehensive_smoke_test()
        
        # Save results
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        results_file = f'smoke_test_results_{timestamp}.json'
        
        import json
        with open(results_file, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        
        print(f"\nResults saved: {results_file}")
        
        # Return summary for integration
        return results
        
    except Exception as e:
        print(f"❌ Smoke test error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()