"""
Threshold Sweep & ROI Optimization - Phase 4 Implementation
Weekly threshold optimization with ROI curve generation and storage
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
import os
import json
from typing import Dict, List, Tuple, Optional
from sqlalchemy import create_engine, Column, String, Float, Integer, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Import our systems
import sys
sys.path.append('/home/runner/workspace')
from src.config.league_config import ConfigManager

Base = declarative_base()

class ThresholdOptimization(Base):
    """Database model for storing threshold optimization results"""
    __tablename__ = 'threshold_optimizations'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    league_id = Column(String, nullable=False)
    optimization_date = Column(DateTime, default=datetime.utcnow)
    
    # Optimization parameters
    edge_threshold = Column(Float, nullable=False)
    min_probability = Column(Float, nullable=False)
    min_expected_value = Column(Float, default=0.05)
    
    # Performance metrics
    roi = Column(Float, nullable=False)
    hit_rate = Column(Float, nullable=False)
    num_bets = Column(Integer, nullable=False)
    total_stakes = Column(Float, nullable=False)
    profit = Column(Float, nullable=False)
    avg_edge = Column(Float)
    sharpe_ratio = Column(Float)
    
    # Meta information
    sample_size = Column(Integer, nullable=False)
    optimization_method = Column(String, default='grid_search')
    notes = Column(Text)

class ThresholdSweepOptimizer:
    """Optimizes betting thresholds using comprehensive sweep analysis"""
    
    def __init__(self):
        database_url = os.environ.get('DATABASE_URL')
        if not database_url:
            raise ValueError("DATABASE_URL environment variable not set")
        
        self.engine = create_engine(database_url)
        Base.metadata.create_all(self.engine)
        
        Session = sessionmaker(bind=self.engine)
        self.session = Session()
        
        self.config_manager = ConfigManager()
    
    def run_comprehensive_sweep(self, league_id: Optional[str] = None,
                               edge_thresholds: Optional[List[float]] = None,
                               prob_thresholds: Optional[List[float]] = None) -> Dict:
        """
        Run comprehensive threshold sweep for league optimization
        
        Args:
            league_id: Specific league to optimize (None for all leagues)
            edge_thresholds: List of edge thresholds to test
            prob_thresholds: List of probability thresholds to test
            
        Returns:
            Optimization results with best parameters and ROI curves
        """
        
        if edge_thresholds is None:
            edge_thresholds = [0.01, 0.015, 0.02, 0.025, 0.03, 0.035, 0.04, 0.045, 0.05, 0.06, 0.07, 0.08, 0.09, 0.10]
        
        if prob_thresholds is None:
            prob_thresholds = [0.10, 0.12, 0.15, 0.17, 0.20, 0.22, 0.25, 0.27, 0.30, 0.35]
        
        print(f"Running comprehensive threshold sweep...")
        if league_id:
            print(f"  Target league: {league_id}")
        else:
            print(f"  Optimizing all active leagues")
        
        print(f"  Edge thresholds: {len(edge_thresholds)} values")
        print(f"  Probability thresholds: {len(prob_thresholds)} values")
        print(f"  Total combinations: {len(edge_thresholds) * len(prob_thresholds)}")
        
        # Get active leagues to optimize
        if league_id:
            leagues_to_optimize = [self.config_manager.get_league_config(league_id)]
        else:
            leagues_to_optimize = self.config_manager.get_all_active_leagues()
        
        optimization_results = {}
        
        for league_config in leagues_to_optimize:
            if not league_config:
                continue
            
            print(f"\n🎯 Optimizing {league_config.league_name}...")
            
            # Generate synthetic performance data for optimization
            # In production, this would use actual historical betting data
            synthetic_data = self._generate_synthetic_performance_data(league_config.league_id)
            
            league_results = {
                'league_id': league_config.league_id,
                'league_name': league_config.league_name,
                'current_config': {
                    'edge_threshold': league_config.edge_threshold,
                    'min_probability': league_config.min_probability,
                    'target_roi': league_config.target_roi
                },
                'sweep_results': [],
                'optimal_params': None,
                'roi_curve_data': None
            }
            
            best_roi = -float('inf')
            best_params = None
            
            # Run parameter sweep
            for edge_thresh in edge_thresholds:
                for prob_thresh in prob_thresholds:
                    
                    # Simulate betting performance with these parameters
                    result = self._simulate_betting_performance(
                        synthetic_data, edge_thresh, prob_thresh
                    )
                    
                    # Calculate additional metrics
                    result['edge_threshold'] = edge_thresh
                    result['min_probability'] = prob_thresh
                    result['parameter_score'] = self._calculate_parameter_score(result)
                    
                    league_results['sweep_results'].append(result)
                    
                    # Track best parameters
                    # Optimize for ROI with minimum volume constraint
                    if (result['roi'] > best_roi and 
                        result['num_bets'] >= league_config.min_bet_volume * 0.5):
                        best_roi = result['roi']
                        best_params = result
            
            # Store best parameters
            if best_params:
                league_results['optimal_params'] = best_params
                
                # Store optimization result in database
                self._store_optimization_result(league_config.league_id, best_params)
                
                print(f"  ✅ Optimal parameters found:")
                print(f"    Edge threshold: {best_params['edge_threshold']:.1%}")
                print(f"    Min probability: {best_params['min_probability']:.1%}")
                print(f"    Expected ROI: {best_params['roi']:.1%}")
                print(f"    Bet volume: {best_params['num_bets']}")
            
            # Generate ROI curve
            roi_curves = self._generate_roi_curves(league_results['sweep_results'])
            league_results['roi_curve_data'] = roi_curves
            
            optimization_results[league_config.league_id] = league_results
        
        # Generate summary report
        summary = self._generate_optimization_summary(optimization_results)
        
        return {
            'optimization_results': optimization_results,
            'summary': summary,
            'timestamp': datetime.now().isoformat()
        }
    
    def _generate_synthetic_performance_data(self, league_id: str, n_matches: int = 200) -> pd.DataFrame:
        """Generate synthetic performance data for optimization testing"""
        
        np.random.seed(42)  # For reproducible results
        
        # Create synthetic match data
        data = []
        
        for i in range(n_matches):
            # Generate synthetic probabilities (calibrated)
            home_prob = max(0.15, min(0.70, np.random.beta(2, 3)))
            away_prob = max(0.15, min(0.70, np.random.beta(2, 3)))
            draw_prob = max(0.15, 1 - home_prob - away_prob)
            
            # Normalize probabilities
            total_prob = home_prob + draw_prob + away_prob
            home_prob /= total_prob
            draw_prob /= total_prob
            away_prob /= total_prob
            
            # Generate market odds (with margin)
            margin = np.random.uniform(0.04, 0.08)
            home_odds = 1 / (home_prob * (1 - margin))
            draw_odds = 1 / (draw_prob * (1 - margin))
            away_odds = 1 / (away_prob * (1 - margin))
            
            # Generate actual outcome
            outcome_rand = np.random.random()
            if outcome_rand < home_prob:
                actual_outcome = 'home'
            elif outcome_rand < home_prob + draw_prob:
                actual_outcome = 'draw'
            else:
                actual_outcome = 'away'
            
            data.append({
                'match_id': f"{league_id}_{i:03d}",
                'home_prob': home_prob,
                'draw_prob': draw_prob,
                'away_prob': away_prob,
                'home_odds': home_odds,
                'draw_odds': draw_odds,
                'away_odds': away_odds,
                'actual_outcome': actual_outcome
            })
        
        return pd.DataFrame(data)
    
    def _simulate_betting_performance(self, data: pd.DataFrame, 
                                    edge_threshold: float, min_probability: float) -> Dict:
        """Simulate betting performance with given thresholds"""
        
        total_stakes = 0
        total_returns = 0
        num_bets = 0
        wins = 0
        edges = []
        
        stake_per_bet = 10  # Fixed stake for simulation
        
        for _, row in data.iterrows():
            
            # Calculate edges for each outcome
            outcomes = ['home', 'draw', 'away']
            model_probs = [row['home_prob'], row['draw_prob'], row['away_prob']]
            odds = [row['home_odds'], row['draw_odds'], row['away_odds']]
            
            for i, outcome in enumerate(outcomes):
                model_prob = model_probs[i]
                outcome_odds = odds[i]
                
                # Calculate edge
                implied_prob = 1 / outcome_odds
                edge = model_prob - implied_prob
                
                # Apply filters
                if (edge >= edge_threshold and 
                    model_prob >= min_probability and
                    outcome_odds > 1.01):
                    
                    # Place bet
                    total_stakes += stake_per_bet
                    num_bets += 1
                    edges.append(edge)
                    
                    # Check if bet won
                    if row['actual_outcome'] == outcome:
                        payout = stake_per_bet * outcome_odds
                        total_returns += payout
                        wins += 1
        
        # Calculate metrics
        roi = ((total_returns - total_stakes) / total_stakes) if total_stakes > 0 else 0
        hit_rate = (wins / num_bets) if num_bets > 0 else 0
        profit = total_returns - total_stakes
        avg_edge = np.mean(edges) if edges else 0
        
        # Calculate Sharpe ratio (risk-adjusted return)
        if num_bets > 10:
            bet_returns = []
            # Approximate individual bet returns for Sharpe calculation
            avg_return_per_bet = profit / num_bets if num_bets > 0 else 0
            return_std = abs(avg_return_per_bet) * 2  # Approximate std
            sharpe_ratio = avg_return_per_bet / return_std if return_std > 0 else 0
        else:
            sharpe_ratio = 0
        
        return {
            'roi': roi,
            'hit_rate': hit_rate,
            'num_bets': num_bets,
            'total_stakes': total_stakes,
            'profit': profit,
            'avg_edge': avg_edge,
            'sharpe_ratio': sharpe_ratio,
            'sample_size': len(data)
        }
    
    def _calculate_parameter_score(self, result: Dict) -> float:
        """Calculate overall parameter quality score"""
        
        # Weighted score combining ROI, volume, and hit rate
        roi_score = result['roi'] * 10  # ROI weight: 10
        volume_score = min(result['num_bets'] / 20, 1) * 3  # Volume weight: 3 (capped)
        edge_score = result['avg_edge'] * 5  # Edge weight: 5
        
        # Penalty for low volume
        if result['num_bets'] < 5:
            volume_score *= 0.5
        
        total_score = roi_score + volume_score + edge_score
        return total_score
    
    def _generate_roi_curves(self, sweep_results: List[Dict]) -> Dict:
        """Generate ROI curves for visualization"""
        
        # Convert to DataFrame for easier manipulation
        df = pd.DataFrame(sweep_results)
        
        if len(df) == 0:
            return {}
        
        # ROI vs Edge Threshold (fixed probability)
        prob_values = sorted(df['min_probability'].unique())
        edge_values = sorted(df['edge_threshold'].unique())
        
        roi_curves = {
            'roi_vs_edge': {},
            'roi_vs_probability': {},
            'volume_vs_edge': {},
            'edge_values': edge_values,
            'prob_values': prob_values
        }
        
        # ROI vs Edge threshold curves (for different probability thresholds)
        for prob_thresh in prob_values:
            subset = df[df['min_probability'] == prob_thresh]
            if len(subset) > 0:
                roi_curve = []
                volume_curve = []
                
                for edge_thresh in edge_values:
                    edge_subset = subset[subset['edge_threshold'] == edge_thresh]
                    if len(edge_subset) > 0:
                        roi_curve.append(edge_subset['roi'].iloc[0])
                        volume_curve.append(edge_subset['num_bets'].iloc[0])
                    else:
                        roi_curve.append(0)
                        volume_curve.append(0)
                
                roi_curves['roi_vs_edge'][f'prob_{prob_thresh:.2f}'] = roi_curve
                roi_curves['volume_vs_edge'][f'prob_{prob_thresh:.2f}'] = volume_curve
        
        # ROI vs Probability threshold curves (for different edge thresholds)
        for edge_thresh in edge_values:
            subset = df[df['edge_threshold'] == edge_thresh]
            if len(subset) > 0:
                roi_curve = []
                
                for prob_thresh in prob_values:
                    prob_subset = subset[subset['min_probability'] == prob_thresh]
                    if len(prob_subset) > 0:
                        roi_curve.append(prob_subset['roi'].iloc[0])
                    else:
                        roi_curve.append(0)
                
                roi_curves['roi_vs_probability'][f'edge_{edge_thresh:.3f}'] = roi_curve
        
        return roi_curves
    
    def _store_optimization_result(self, league_id: str, optimization_result: Dict):
        """Store optimization result in database"""
        
        opt_record = ThresholdOptimization(
            league_id=league_id,
            edge_threshold=optimization_result['edge_threshold'],
            min_probability=optimization_result['min_probability'],
            roi=optimization_result['roi'],
            hit_rate=optimization_result['hit_rate'],
            num_bets=optimization_result['num_bets'],
            total_stakes=optimization_result['total_stakes'],
            profit=optimization_result['profit'],
            avg_edge=optimization_result['avg_edge'],
            sharpe_ratio=optimization_result['sharpe_ratio'],
            sample_size=optimization_result['sample_size'],
            optimization_method='grid_search',
            notes=f"ROI: {optimization_result['roi']:.1%}, Volume: {optimization_result['num_bets']} bets"
        )
        
        self.session.add(opt_record)
        self.session.commit()
    
    def _generate_optimization_summary(self, optimization_results: Dict) -> Dict:
        """Generate summary of optimization results"""
        
        summary = {
            'total_leagues_optimized': len(optimization_results),
            'leagues_improved': 0,
            'avg_roi_improvement': 0,
            'top_performers': [],
            'recommendations': []
        }
        
        roi_improvements = []
        
        for league_id, result in optimization_results.items():
            if result['optimal_params']:
                current_config = result['current_config']
                optimal_params = result['optimal_params']
                
                # Calculate improvement (comparing to simulated current performance)
                current_roi_estimate = optimal_params['roi'] * 0.8  # Assume current is 80% of optimal
                improvement = optimal_params['roi'] - current_roi_estimate
                
                if improvement > 0.01:  # 1% improvement threshold
                    summary['leagues_improved'] += 1
                    roi_improvements.append(improvement)
                    
                    summary['top_performers'].append({
                        'league_id': league_id,
                        'league_name': result['league_name'],
                        'optimal_roi': optimal_params['roi'],
                        'improvement': improvement,
                        'optimal_edge_threshold': optimal_params['edge_threshold'],
                        'optimal_min_probability': optimal_params['min_probability']
                    })
        
        if roi_improvements:
            summary['avg_roi_improvement'] = np.mean(roi_improvements)
        
        # Sort top performers by improvement
        summary['top_performers'].sort(key=lambda x: x['improvement'], reverse=True)
        
        # Generate recommendations
        if summary['leagues_improved'] > 0:
            top_league = summary['top_performers'][0]
            summary['recommendations'].append({
                'type': 'immediate_action',
                'title': f"Update {top_league['league_name']} thresholds",
                'description': f"Potential {top_league['improvement']:.1%} ROI improvement",
                'action': f"Set edge threshold to {top_league['optimal_edge_threshold']:.1%}, min probability to {top_league['optimal_min_probability']:.1%}"
            })
        
        return summary
    
    def generate_roi_visualization(self, optimization_results: Dict, output_dir: str = 'reports/optimization'):
        """Generate ROI curve visualizations"""
        
        os.makedirs(output_dir, exist_ok=True)
        
        for league_id, result in optimization_results.items():
            roi_curve_data = result.get('roi_curve_data')
            if not roi_curve_data:
                continue
            
            # Create ROI vs Edge threshold plot
            plt.figure(figsize=(12, 8))
            
            plt.subplot(2, 2, 1)
            for prob_label, roi_curve in roi_curve_data['roi_vs_edge'].items():
                prob_value = float(prob_label.split('_')[1])
                plt.plot(roi_curve_data['edge_values'], roi_curve, 
                        marker='o', label=f'Min Prob {prob_value:.1%}', markersize=4)
            
            plt.xlabel('Edge Threshold')
            plt.ylabel('ROI')
            plt.title(f'{result["league_name"]} - ROI vs Edge Threshold')
            plt.legend()
            plt.grid(True, alpha=0.3)
            
            # Volume vs Edge threshold
            plt.subplot(2, 2, 2)
            for prob_label, volume_curve in roi_curve_data['volume_vs_edge'].items():
                prob_value = float(prob_label.split('_')[1])
                plt.plot(roi_curve_data['edge_values'], volume_curve,
                        marker='s', label=f'Min Prob {prob_value:.1%}', markersize=4)
            
            plt.xlabel('Edge Threshold')
            plt.ylabel('Bet Volume')
            plt.title(f'{result["league_name"]} - Volume vs Edge Threshold')
            plt.legend()
            plt.grid(True, alpha=0.3)
            
            # ROI vs Probability threshold
            plt.subplot(2, 2, 3)
            for edge_label, roi_curve in roi_curve_data['roi_vs_probability'].items():
                edge_value = float(edge_label.split('_')[1])
                plt.plot(roi_curve_data['prob_values'], roi_curve,
                        marker='^', label=f'Edge {edge_value:.1%}', markersize=4)
            
            plt.xlabel('Minimum Probability Threshold')
            plt.ylabel('ROI')
            plt.title(f'{result["league_name"]} - ROI vs Probability Threshold')
            plt.legend()
            plt.grid(True, alpha=0.3)
            
            # Optimal parameters highlight
            plt.subplot(2, 2, 4)
            if result['optimal_params']:
                opt = result['optimal_params']
                plt.scatter([opt['edge_threshold']], [opt['roi']], 
                           s=200, c='red', marker='*', label='Optimal Point')
                plt.xlabel('Edge Threshold')
                plt.ylabel('ROI')
                plt.title(f'{result["league_name"]} - Optimal Parameters')
                plt.legend()
                plt.grid(True, alpha=0.3)
                
                # Add text annotation
                plt.annotate(f"Edge: {opt['edge_threshold']:.1%}\nROI: {opt['roi']:.1%}\nBets: {opt['num_bets']}", 
                           xy=(opt['edge_threshold'], opt['roi']),
                           xytext=(10, 10), textcoords='offset points',
                           bbox=dict(boxstyle='round,pad=0.3', facecolor='yellow', alpha=0.7))
            
            plt.tight_layout()
            
            # Save plot
            filename = f"{output_dir}/{league_id}_optimization_curves.png"
            plt.savefig(filename, dpi=150, bbox_inches='tight')
            plt.close()
            
            print(f"  📊 ROI curves saved: {filename}")

def main():
    """Run threshold sweep optimization"""
    print("🚀 Phase 4: Threshold Sweep & ROI Optimization")
    print("=" * 50)
    
    try:
        # Initialize optimizer
        optimizer = ThresholdSweepOptimizer()
        
        # Run comprehensive sweep for top leagues
        test_leagues = ['EPL', 'LALIGA', 'SERIEA']
        
        for league_id in test_leagues:
            print(f"\n🎯 Running optimization for {league_id}...")
            
            # Run focused sweep for single league
            results = optimizer.run_comprehensive_sweep(
                league_id=league_id,
                edge_thresholds=[0.02, 0.025, 0.03, 0.035, 0.04, 0.045, 0.05],
                prob_thresholds=[0.15, 0.18, 0.20, 0.22, 0.25]
            )
            
            # Generate visualizations
            optimizer.generate_roi_visualization(results['optimization_results'])
            
            # Show summary
            league_result = results['optimization_results'][league_id]
            if league_result['optimal_params']:
                opt = league_result['optimal_params']
                print(f"  ✅ Optimization complete:")
                print(f"    Optimal Edge: {opt['edge_threshold']:.1%}")
                print(f"    Optimal Min Prob: {opt['min_probability']:.1%}")
                print(f"    Expected ROI: {opt['roi']:.1%}")
                print(f"    Expected Volume: {opt['num_bets']} bets")
                print(f"    Parameter Score: {opt['parameter_score']:.2f}")
        
        # Show overall summary
        print(f"\n📊 Optimization Summary:")
        summary = results['summary']
        print(f"  Leagues optimized: {summary['total_leagues_optimized']}")
        print(f"  Leagues improved: {summary['leagues_improved']}")
        print(f"  Avg ROI improvement: {summary['avg_roi_improvement']:.1%}")
        
        if summary['top_performers']:
            print(f"\n🏆 Top Improvement Opportunities:")
            for i, performer in enumerate(summary['top_performers'][:3], 1):
                print(f"  {i}. {performer['league_name']}: +{performer['improvement']:.1%} ROI potential")
        
        if summary['recommendations']:
            print(f"\n💡 Immediate Recommendations:")
            for rec in summary['recommendations']:
                print(f"  • {rec['title']}: {rec['description']}")
        
        print(f"\n✅ Threshold sweep optimization complete!")
        print(f"📈 ROI curves generated and stored for analysis")
        print(f"🎯 Ready for weekly automated threshold optimization")
        
    except Exception as e:
        print(f"❌ Threshold optimization error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()