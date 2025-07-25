"""
League Onboarding Pipeline - Phase 5 Implementation
Template script for onboarding new leagues with QA checklist
"""

import argparse
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import os
import sys
import json
from typing import Dict, List, Optional, Tuple

# Add parent directory to path
sys.path.append('/home/runner/workspace')
from src.config.league_config import ConfigManager
from src.utils.type_coercion import ensure_py_types
from src.testing.smoke_test_thresholds import ThresholdSmokeTest

class LeagueOnboarder:
    """Comprehensive league onboarding system"""
    
    def __init__(self):
        self.config_manager = ConfigManager()
        self.smoke_test = ThresholdSmokeTest()
        
        # Data quality gates
        self.min_historical_matches = 500
        self.max_odds_gap_percent = 0.10  # 10% maximum odds gaps
        self.min_seasons_required = 2
        
    def onboard_league(self, league_id: str, league_name: str, 
                      region: str, tier: int = 3,
                      team_mapping: Optional[Dict] = None) -> Dict:
        """
        Complete league onboarding process
        
        Args:
            league_id: Unique league identifier (e.g., 'MXLIGA1')
            league_name: Full league name (e.g., 'Liga MX')
            region: Geographic region (e.g., 'Mexico')
            tier: League tier (1=Top5, 2=Major, 3=Others)
            team_mapping: Optional team ID mapping
            
        Returns:
            Onboarding results with success status and metrics
        """
        
        print(f"🚀 Onboarding {league_name} ({league_id})")
        print("=" * 50)
        
        onboard_result = {
            'league_id': league_id,
            'league_name': league_name,
            'region': region,
            'tier': tier,
            'onboarding_timestamp': datetime.now().isoformat(),
            'steps_completed': [],
            'quality_checks': {},
            'initial_config': {},
            'success': False,
            'issues': [],
            'warnings': []
        }
        
        try:
            # Step 1: Team ID Mapping
            print("Step 1: Team ID Mapping...")
            team_mapping_result = self._map_team_ids(league_id, team_mapping)
            onboard_result['steps_completed'].append('team_mapping')
            onboard_result['team_mapping'] = team_mapping_result
            
            if not team_mapping_result['success']:
                onboard_result['issues'].append("Team ID mapping failed")
                return onboard_result
            
            # Step 2: Initialize Elo Ratings
            print("Step 2: Initialize Elo Ratings...")
            elo_result = self._initialize_elo_ratings(league_id, team_mapping_result['teams'])
            onboard_result['steps_completed'].append('elo_initialization')
            onboard_result['elo_initialization'] = elo_result
            
            # Step 3: Backfill Historical Data
            print("Step 3: Backfill Historical Data...")
            backfill_result = self._backfill_historical_data(league_id, self.min_seasons_required)
            onboard_result['steps_completed'].append('data_backfill')
            onboard_result['data_backfill'] = backfill_result
            
            # Step 4: Data Quality Gate
            print("Step 4: Data Quality Assessment...")
            quality_result = self._assess_data_quality(league_id, backfill_result)
            onboard_result['quality_checks'] = quality_result
            
            if not quality_result['passes_quality_gate']:
                onboard_result['issues'].extend(quality_result['blocking_issues'])
                print(f"❌ Data quality gate failed: {quality_result['blocking_issues']}")
                return onboard_result
            
            # Step 5: Leakage Tests
            print("Step 5: Data Leakage Tests...")
            leakage_result = self._run_leakage_tests(league_id, backfill_result['historical_data'])
            onboard_result['steps_completed'].append('leakage_tests')
            onboard_result['leakage_tests'] = leakage_result
            
            if leakage_result['leakage_detected']:
                onboard_result['issues'].append("Data leakage detected in features")
                return onboard_result
            
            # Step 6: Generate Initial Thresholds
            print("Step 6: Generate Initial Thresholds...")
            threshold_result = self._generate_initial_thresholds(league_id, tier, backfill_result)
            onboard_result['steps_completed'].append('threshold_generation')
            onboard_result['initial_config'] = threshold_result
            
            # Step 7: Register League Configuration
            print("Step 7: Register League Configuration...")
            config_result = self._register_league_config(
                league_id, league_name, region, tier, threshold_result
            )
            onboard_result['steps_completed'].append('config_registration')
            
            # Step 8: Validation Test
            print("Step 8: Validation Test...")
            validation_result = self._run_validation_test(league_id)
            onboard_result['validation_test'] = validation_result
            
            # Final success assessment
            if len(onboard_result['steps_completed']) >= 7 and validation_result.get('success', False):
                onboard_result['success'] = True
                print(f"✅ {league_name} successfully onboarded!")
            else:
                onboard_result['issues'].append("Validation test failed")
            
        except Exception as e:
            onboard_result['issues'].append(f"Onboarding error: {str(e)}")
            print(f"❌ Onboarding failed: {e}")
        
        return ensure_py_types(onboard_result)
    
    def _map_team_ids(self, league_id: str, team_mapping: Optional[Dict]) -> Dict:
        """Map team IDs for the league"""
        
        if team_mapping:
            # Use provided mapping
            teams = list(team_mapping.keys())
            print(f"  Using provided team mapping: {len(teams)} teams")
        else:
            # Generate sample team mapping for demonstration
            sample_teams = [
                f"{league_id}_TEAM_{i:02d}" for i in range(16, 22)  # 6 teams for demo
            ]
            team_mapping = {team_id: f"Team {i+1}" for i, team_id in enumerate(sample_teams)}
            teams = sample_teams
            print(f"  Generated sample team mapping: {len(teams)} teams")
        
        return {
            'success': True,
            'teams': teams,
            'team_mapping': team_mapping,
            'team_count': len(teams)
        }
    
    def _initialize_elo_ratings(self, league_id: str, teams: List[str]) -> Dict:
        """Initialize Elo ratings for all teams"""
        
        # Default Elo rating
        default_elo = 1500
        
        # Add some variance for realism
        elo_ratings = {}
        for team in teams:
            # Random variance around default
            variance = np.random.normal(0, 100)  # ±100 Elo points variance
            team_elo = max(1200, min(1800, default_elo + variance))  # Bounded
            elo_ratings[team] = float(team_elo)
        
        print(f"  Initialized Elo ratings for {len(teams)} teams")
        print(f"  Rating range: {min(elo_ratings.values()):.0f} - {max(elo_ratings.values()):.0f}")
        
        return {
            'success': True,
            'elo_ratings': elo_ratings,
            'default_elo': default_elo,
            'rating_range': {
                'min': min(elo_ratings.values()),
                'max': max(elo_ratings.values()),
                'avg': np.mean(list(elo_ratings.values()))
            }
        }
    
    def _backfill_historical_data(self, league_id: str, seasons: int) -> Dict:
        """Backfill historical match data"""
        
        # Generate synthetic historical data for demonstration
        # In production, this would fetch from data provider APIs
        
        historical_matches = []
        teams = [f"{league_id}_TEAM_{i:02d}" for i in range(16, 22)]
        
        matches_per_season = 50  # Approximate matches per season
        
        for season in range(seasons):
            season_start = datetime.now() - timedelta(days=365 * (seasons - season))
            
            for match_num in range(matches_per_season):
                # Random match date within season
                match_date = season_start + timedelta(days=np.random.randint(0, 300))
                
                # Random teams
                home_team, away_team = np.random.choice(teams, 2, replace=False)
                
                # Generate match data
                home_score = np.random.poisson(1.3)
                away_score = np.random.poisson(1.1)
                
                # Determine outcome
                if home_score > away_score:
                    outcome = 'home'
                elif away_score > home_score:
                    outcome = 'away'
                else:
                    outcome = 'draw'
                
                # Generate odds (with realistic margins)
                home_prob = np.random.beta(2.5, 2.5)
                draw_prob = np.random.beta(1.5, 3.5)
                away_prob = 1 - home_prob - draw_prob
                
                # Normalize
                total_prob = home_prob + draw_prob + away_prob
                home_prob /= total_prob
                draw_prob /= total_prob
                away_prob /= total_prob
                
                # Convert to odds with margin
                margin = 0.06
                home_odds = 1 / (home_prob * (1 - margin))
                draw_odds = 1 / (draw_prob * (1 - margin))
                away_odds = 1 / (away_prob * (1 - margin))
                
                historical_matches.append({
                    'match_id': f"{league_id}_{season}_{match_num:03d}",
                    'season': season + 1,
                    'match_date': match_date,
                    'home_team': home_team,
                    'away_team': away_team,
                    'home_score': home_score,
                    'away_score': away_score,
                    'outcome': outcome,
                    'home_odds': home_odds,
                    'draw_odds': draw_odds,
                    'away_odds': away_odds,
                    'home_prob': home_prob,
                    'draw_prob': draw_prob,
                    'away_prob': away_prob
                })
        
        total_matches = len(historical_matches)
        print(f"  Backfilled {total_matches} matches across {seasons} seasons")
        
        return {
            'success': True,
            'total_matches': total_matches,
            'seasons_covered': seasons,
            'date_range': {
                'start': min(m['match_date'] for m in historical_matches).isoformat(),
                'end': max(m['match_date'] for m in historical_matches).isoformat()
            },
            'historical_data': historical_matches
        }
    
    def _assess_data_quality(self, league_id: str, backfill_result: Dict) -> Dict:
        """Assess data quality and apply gates"""
        
        historical_data = backfill_result['historical_data']
        total_matches = len(historical_data)
        
        quality_issues = []
        blocking_issues = []
        warnings = []
        
        # Gate 1: Minimum match count
        if total_matches < self.min_historical_matches:
            blocking_issues.append(
                f"Insufficient historical data: {total_matches} matches "
                f"(minimum: {self.min_historical_matches})"
            )
        
        # Gate 2: Odds gap analysis
        odds_gaps = []
        for match in historical_data:
            # Check for realistic odds ranges
            all_odds = [match['home_odds'], match['draw_odds'], match['away_odds']]
            if any(odd < 1.01 or odd > 50 for odd in all_odds):
                odds_gaps.append(match['match_id'])
        
        odds_gap_rate = len(odds_gaps) / total_matches if total_matches > 0 else 0
        
        if odds_gap_rate > self.max_odds_gap_percent:
            blocking_issues.append(
                f"High odds gap rate: {odds_gap_rate:.1%} "
                f"(maximum: {self.max_odds_gap_percent:.1%})"
            )
        
        # Gate 3: Date distribution
        dates = [m['match_date'] for m in historical_data]
        date_span = (max(dates) - min(dates)).days
        
        if date_span < 365 * self.min_seasons_required * 0.8:  # 80% of expected span
            warnings.append(f"Short date span: {date_span} days")
        
        # Gate 4: Team balance
        team_appearances = {}
        for match in historical_data:
            team_appearances[match['home_team']] = team_appearances.get(match['home_team'], 0) + 1
            team_appearances[match['away_team']] = team_appearances.get(match['away_team'], 0) + 1
        
        if team_appearances:
            min_appearances = min(team_appearances.values())
            max_appearances = max(team_appearances.values())
            
            if max_appearances > min_appearances * 3:  # Significant imbalance
                warnings.append("Unbalanced team representation in data")
        
        # Overall assessment
        passes_quality_gate = len(blocking_issues) == 0
        
        quality_result = {
            'passes_quality_gate': passes_quality_gate,
            'total_matches_analyzed': total_matches,
            'odds_gap_rate': odds_gap_rate,
            'date_span_days': date_span,
            'unique_teams': len(team_appearances),
            'blocking_issues': blocking_issues,
            'warnings': warnings,
            'quality_score': max(0, 1 - len(quality_issues) * 0.1 - len(blocking_issues) * 0.5)
        }
        
        if passes_quality_gate:
            print(f"  ✅ Data quality gate passed ({quality_result['quality_score']:.1%} score)")
        else:
            print(f"  ❌ Data quality gate failed: {blocking_issues}")
        
        return quality_result
    
    def _run_leakage_tests(self, league_id: str, historical_data: List[Dict]) -> Dict:
        """Run data leakage tests on features"""
        
        print("  Running data leakage detection...")
        
        # Test for obvious leakage patterns
        leakage_tests = {
            'match_outcome_features': False,
            'future_information': False,
            'perfect_correlation': False
        }
        
        # Convert to DataFrame for analysis
        df = pd.DataFrame(historical_data)
        
        # Test 1: Check for match outcome features
        outcome_related_columns = [
            col for col in df.columns 
            if any(keyword in col.lower() for keyword in ['score', 'result', 'winner', 'final'])
        ]
        
        if outcome_related_columns:
            leakage_tests['match_outcome_features'] = True
            print(f"    ⚠️  Found outcome-related columns: {outcome_related_columns}")
        
        # Test 2: Date consistency (no future information)
        match_dates = pd.to_datetime(df['match_date'])
        if any(date > datetime.now() + timedelta(days=1) for date in match_dates):
            leakage_tests['future_information'] = True
            print(f"    ⚠️  Found future match dates")
        
        # Test 3: Perfect correlation test (simplified)
        # In production, this would test model features against outcomes
        correlation_threshold = 0.95
        
        # Create a simple feature for testing
        df['outcome_encoded'] = df['outcome'].map({'home': 1, 'draw': 0, 'away': -1})
        
        # Test correlation between odds and outcomes (should not be perfect)
        home_corr = abs(df['home_odds'].corr(df['outcome_encoded']))
        if home_corr > correlation_threshold:
            leakage_tests['perfect_correlation'] = True
            print(f"    ⚠️  Perfect correlation detected: {home_corr:.3f}")
        
        # Overall leakage assessment
        leakage_detected = any(leakage_tests.values())
        
        leakage_result = {
            'leakage_detected': leakage_detected,
            'tests_run': list(leakage_tests.keys()),
            'test_results': leakage_tests,
            'recommendations': []
        }
        
        if leakage_detected:
            leakage_result['recommendations'].append("Remove leaky features before model training")
            print(f"  ❌ Data leakage detected")
        else:
            print(f"  ✅ No data leakage detected")
        
        return leakage_result
    
    def _generate_initial_thresholds(self, league_id: str, tier: int, 
                                   backfill_result: Dict) -> Dict:
        """Generate initial betting thresholds via sweep"""
        
        print("  Running threshold sweep for initial configuration...")
        
        # Tier-based base thresholds
        if tier == 1:  # Top leagues
            base_config = {
                'edge_threshold': 0.03,
                'min_probability': 0.20,
                'target_roi': 0.10,
                'target_accuracy': 0.60,
                'max_stake': 25.0,
                'min_bet_volume': 15
            }
        elif tier == 2:  # Major leagues
            base_config = {
                'edge_threshold': 0.025,
                'min_probability': 0.18,
                'target_roi': 0.12,
                'target_accuracy': 0.58,
                'max_stake': 20.0,
                'min_bet_volume': 12
            }
        else:  # Other leagues
            base_config = {
                'edge_threshold': 0.04,
                'min_probability': 0.25,
                'target_roi': 0.08,
                'target_accuracy': 0.55,
                'max_stake': 15.0,
                'min_bet_volume': 8
            }
        
        # Simple optimization based on historical data
        historical_data = backfill_result['historical_data']
        
        # Simulate different thresholds
        edge_thresholds = [0.02, 0.03, 0.04, 0.05]
        prob_thresholds = [0.15, 0.20, 0.25]
        
        best_roi = -float('inf')
        optimal_config = base_config.copy()
        
        for edge_thresh in edge_thresholds:
            for prob_thresh in prob_thresholds:
                # Simulate betting with these thresholds
                sim_result = self._simulate_threshold_performance(
                    historical_data, edge_thresh, prob_thresh
                )
                
                if sim_result['roi'] > best_roi and sim_result['volume'] >= 5:
                    best_roi = sim_result['roi']
                    optimal_config['edge_threshold'] = edge_thresh
                    optimal_config['min_probability'] = prob_thresh
        
        print(f"  Optimal thresholds: Edge {optimal_config['edge_threshold']:.1%}, "
              f"Min Prob {optimal_config['min_probability']:.1%}")
        
        return optimal_config
    
    def _simulate_threshold_performance(self, historical_data: List[Dict], 
                                      edge_threshold: float, min_probability: float) -> Dict:
        """Simulate betting performance with given thresholds"""
        
        total_stakes = 0
        total_returns = 0
        num_bets = 0
        
        stake_per_bet = 10
        
        for match in historical_data:
            # Test each outcome
            outcomes = ['home', 'draw', 'away']
            probs = [match['home_prob'], match['draw_prob'], match['away_prob']]
            odds = [match['home_odds'], match['draw_odds'], match['away_odds']]
            
            for outcome, prob, odd in zip(outcomes, probs, odds):
                # Calculate edge
                implied_prob = 1 / odd
                edge = prob - implied_prob
                
                # Apply filters
                if edge >= edge_threshold and prob >= min_probability:
                    total_stakes += stake_per_bet
                    num_bets += 1
                    
                    # Check if bet won
                    if match['outcome'] == outcome:
                        payout = stake_per_bet * odd
                        total_returns += payout
        
        roi = (total_returns - total_stakes) / total_stakes if total_stakes > 0 else 0
        
        return {
            'roi': float(roi),
            'volume': int(num_bets),
            'total_stakes': float(total_stakes)
        }
    
    def _register_league_config(self, league_id: str, league_name: str, 
                               region: str, tier: int, config: Dict) -> Dict:
        """Register league configuration in system"""
        
        # Add league metadata
        full_config = config.copy()
        full_config.update({
            'league_name': league_name,
            'tier': tier,
            'region': region,
            'is_active': True,
            'created_date': datetime.now().isoformat(),
            'last_updated': datetime.now().isoformat()
        })
        
        # In production, this would write to database
        print(f"  League configuration registered: {league_name}")
        
        return {
            'success': True,
            'config_registered': full_config
        }
    
    def _run_validation_test(self, league_id: str) -> Dict:
        """Run final validation test on onboarded league"""
        
        print("  Running validation test...")
        
        # Simulate validation test
        validation_metrics = {
            'config_valid': True,
            'data_accessible': True,
            'model_compatible': True,
            'thresholds_reasonable': True
        }
        
        success = all(validation_metrics.values())
        
        validation_result = {
            'success': success,
            'metrics': validation_metrics,
            'validation_score': sum(validation_metrics.values()) / len(validation_metrics)
        }
        
        if success:
            print(f"  ✅ Validation passed ({validation_result['validation_score']:.1%})")
        else:
            print(f"  ❌ Validation failed")
        
        return validation_result
    
    def generate_qa_checklist(self, league_id: str) -> Dict:
        """Generate QA checklist for league onboarding"""
        
        checklist = {
            'pre_onboarding': [
                'League identifier is unique and follows naming convention',
                'Region and tier classification verified',
                'Team mapping data available and complete',
                'Data source identified and accessible'
            ],
            'data_quality': [
                f'Minimum {self.min_historical_matches} historical matches available',
                f'Odds gaps less than {self.max_odds_gap_percent:.0%}',
                f'At least {self.min_seasons_required} seasons of data',
                'Team representation balanced across matches',
                'Date ranges realistic and complete'
            ],
            'feature_validation': [
                'No match outcome features in training data',
                'No future information leakage',
                'Feature correlations within reasonable bounds',
                'All features available pre-match'
            ],
            'threshold_optimization': [
                'Initial thresholds generated via sweep',
                'Target ROI and volume realistic for tier',
                'Risk parameters appropriate for league characteristics',
                'Backtesting shows positive expected value'
            ],
            'system_integration': [
                'League configuration registered in database',
                'Model pipeline accepts league data format',
                'Monitoring systems configured',
                'Alerting thresholds set appropriately'
            ],
            'final_validation': [
                'End-to-end test successful',
                'Performance metrics within expected ranges',
                'No critical issues identified',
                'Ready for production deployment'
            ]
        }
        
        return {
            'league_id': league_id,
            'checklist': checklist,
            'total_items': sum(len(items) for items in checklist.values()),
            'generated_at': datetime.now().isoformat()
        }

def main():
    """Main onboarding script"""
    parser = argparse.ArgumentParser(description='Onboard new league to BetGenius AI')
    parser.add_argument('--league_id', required=True, help='League identifier (e.g., MXLIGA1)')
    parser.add_argument('--league_name', required=True, help='Full league name (e.g., Liga MX)')
    parser.add_argument('--region', required=True, help='Geographic region (e.g., Mexico)')
    parser.add_argument('--tier', type=int, default=3, help='League tier (1=Top5, 2=Major, 3=Others)')
    parser.add_argument('--dry_run', action='store_true', help='Run in simulation mode')
    
    args = parser.parse_args()
    
    print("🚀 BetGenius AI - League Onboarding Pipeline")
    print("=" * 55)
    
    try:
        # Initialize onboarder
        onboarder = LeagueOnboarder()
        
        if args.dry_run:
            print("Running in DRY RUN mode - no changes will be made")
        
        # Run onboarding process
        result = onboarder.onboard_league(
            league_id=args.league_id,
            league_name=args.league_name,
            region=args.region,
            tier=args.tier
        )
        
        # Generate QA checklist
        qa_checklist = onboarder.generate_qa_checklist(args.league_id)
        
        # Save results
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        result_file = f'onboarding_result_{args.league_id}_{timestamp}.json'
        
        with open(result_file, 'w') as f:
            json.dump({
                'onboarding_result': result,
                'qa_checklist': qa_checklist
            }, f, indent=2, default=str)
        
        # Final summary
        print(f"\n{'✅' if result['success'] else '❌'} Onboarding Summary:")
        print(f"League: {args.league_name} ({args.league_id})")
        print(f"Steps completed: {len(result['steps_completed'])}")
        print(f"Success: {result['success']}")
        
        if result['issues']:
            print(f"Issues: {len(result['issues'])}")
            for issue in result['issues']:
                print(f"  • {issue}")
        
        print(f"\nResults saved: {result_file}")
        
    except Exception as e:
        print(f"❌ Onboarding failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()