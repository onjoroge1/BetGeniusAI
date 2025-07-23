"""
Odds Processing and Betting Layer - Phase 3 Implementation
Ingests betting odds, calculates expected value, and optimizes bet selection
"""

import numpy as np
import pandas as pd
import requests
import os
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
import warnings
warnings.filterwarnings('ignore')

class OddsProcessor:
    """
    Processes betting odds and calculates expected value for profitable betting
    """
    
    def __init__(self):
        self.rapidapi_key = os.environ.get('RAPIDAPI_KEY')
        self.base_url = "https://api-football-v1.p.rapidapi.com/v3/odds"
        self.headers = {
            "X-RapidAPI-Key": self.rapidapi_key,
            "X-RapidAPI-Host": "api-football-v1.p.rapidapi.com"
        }
        
    def fetch_odds(self, fixture_id: int, bookmaker: str = "Bet365") -> Optional[Dict]:
        """
        Fetch betting odds for a specific fixture
        
        Args:
            fixture_id: Fixture ID from RapidAPI
            bookmaker: Preferred bookmaker (default: Bet365)
            
        Returns:
            Dict with odds data or None if not available
        """
        try:
            url = f"{self.base_url}"
            params = {
                "fixture": fixture_id,
                "bookmaker": bookmaker
            }
            
            response = requests.get(url, headers=self.headers, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get('response') and len(data['response']) > 0:
                    odds_data = data['response'][0]
                    return self._parse_odds_data(odds_data)
                else:
                    print(f"⚠️ No odds available for fixture {fixture_id}")
                    return None
            else:
                print(f"❌ Error fetching odds: {response.status_code}")
                return None
                
        except Exception as e:
            print(f"❌ Error fetching odds for fixture {fixture_id}: {e}")
            return None
    
    def _parse_odds_data(self, odds_data: Dict) -> Dict:
        """Parse raw odds data into standardized format"""
        try:
            bookmakers = odds_data.get('bookmakers', [])
            
            if not bookmakers:
                return None
            
            # Get first bookmaker's odds
            bookmaker_data = bookmakers[0]
            bets = bookmaker_data.get('bets', [])
            
            # Find match winner odds
            match_winner_odds = None
            for bet in bets:
                if bet.get('name') == 'Match Winner':
                    match_winner_odds = bet
                    break
            
            if not match_winner_odds:
                return None
            
            # Extract odds values
            values = match_winner_odds.get('values', [])
            odds_dict = {}
            
            for value in values:
                outcome = value.get('value')
                odd = float(value.get('odd', 0))
                
                if outcome == 'Home':
                    odds_dict['home_odds'] = odd
                elif outcome == 'Draw':
                    odds_dict['draw_odds'] = odd
                elif outcome == 'Away':
                    odds_dict['away_odds'] = odd
            
            # Calculate implied probabilities (with margin)
            implied_probs = self._calculate_implied_probabilities(odds_dict)
            
            result = {
                'fixture_id': odds_data.get('fixture', {}).get('id'),
                'bookmaker': bookmaker_data.get('name'),
                'last_update': odds_data.get('update'),
                **odds_dict,
                **implied_probs
            }
            
            return result
            
        except Exception as e:
            print(f"❌ Error parsing odds data: {e}")
            return None
    
    def _calculate_implied_probabilities(self, odds_dict: Dict) -> Dict:
        """
        Calculate margin-adjusted implied probabilities from odds
        
        Args:
            odds_dict: Dict with home_odds, draw_odds, away_odds
            
        Returns:
            Dict with implied probabilities
        """
        try:
            home_odds = odds_dict.get('home_odds', 0)
            draw_odds = odds_dict.get('draw_odds', 0) 
            away_odds = odds_dict.get('away_odds', 0)
            
            if any(odd <= 1 for odd in [home_odds, draw_odds, away_odds]):
                return {}
            
            # Raw implied probabilities
            home_implied = 1 / home_odds
            draw_implied = 1 / draw_odds
            away_implied = 1 / away_odds
            
            # Calculate bookmaker margin
            total_implied = home_implied + draw_implied + away_implied
            margin = total_implied - 1.0
            
            # Margin-adjusted probabilities (fair odds)
            home_fair = home_implied / total_implied
            draw_fair = draw_implied / total_implied
            away_fair = away_implied / total_implied
            
            return {
                'home_implied': home_implied,
                'draw_implied': draw_implied,
                'away_implied': away_implied,
                'margin': margin,
                'home_fair': home_fair,
                'draw_fair': draw_fair,
                'away_fair': away_fair
            }
            
        except Exception as e:
            print(f"❌ Error calculating implied probabilities: {e}")
            return {}
    
    def calculate_expected_value(self, model_probs: np.ndarray, odds_data: Dict) -> Dict:
        """
        Calculate expected value for each betting outcome
        
        Args:
            model_probs: Model probabilities [home, draw, away]
            odds_data: Odds data with fair probabilities
            
        Returns:
            Dict with EV calculations for each outcome
        """
        try:
            home_prob, draw_prob, away_prob = model_probs
            
            home_odds = odds_data.get('home_odds', 0)
            draw_odds = odds_data.get('draw_odds', 0)
            away_odds = odds_data.get('away_odds', 0)
            
            home_fair = odds_data.get('home_fair', 0)
            draw_fair = odds_data.get('draw_fair', 0)
            away_fair = odds_data.get('away_fair', 0)
            
            if any(odd <= 1 for odd in [home_odds, draw_odds, away_odds]):
                return {}
            
            # Expected Value = (Model_Prob * Payout) - Stake
            # Where Payout = Stake * Odds, so EV = (Model_Prob * Odds - 1)
            home_ev = (home_prob * home_odds) - 1
            draw_ev = (draw_prob * draw_odds) - 1
            away_ev = (away_prob * away_odds) - 1
            
            # Edge = Model_Prob - Fair_Prob (margin-adjusted market probability)
            home_edge = home_prob - home_fair
            draw_edge = draw_prob - draw_fair
            away_edge = away_prob - away_fair
            
            ev_results = {
                'home': {
                    'model_prob': home_prob,
                    'fair_prob': home_fair,
                    'odds': home_odds,
                    'edge': home_edge,
                    'expected_value': home_ev,
                    'kelly_fraction': max(0, home_edge / (home_odds - 1)) if home_odds > 1 else 0
                },
                'draw': {
                    'model_prob': draw_prob,
                    'fair_prob': draw_fair,
                    'odds': draw_odds,
                    'edge': draw_edge,
                    'expected_value': draw_ev,
                    'kelly_fraction': max(0, draw_edge / (draw_odds - 1)) if draw_odds > 1 else 0
                },
                'away': {
                    'model_prob': away_prob,
                    'fair_prob': away_fair,
                    'odds': away_odds,
                    'edge': away_edge,
                    'expected_value': away_ev,
                    'kelly_fraction': max(0, away_edge / (away_odds - 1)) if away_odds > 1 else 0
                }
            }
            
            return ev_results
            
        except Exception as e:
            print(f"❌ Error calculating expected value: {e}")
            return {}
    
    def filter_profitable_bets(self, ev_results: Dict, edge_threshold: float = 0.03, 
                             min_probability: float = 0.15, min_ev: float = 0.05) -> List[Dict]:
        """
        Filter bets based on profitability criteria
        
        Args:
            ev_results: Expected value calculations
            edge_threshold: Minimum edge required (default: 3%)
            min_probability: Minimum model probability (default: 15%)
            min_ev: Minimum expected value (default: 5%)
            
        Returns:
            List of profitable betting opportunities
        """
        profitable_bets = []
        
        for outcome, data in ev_results.items():
            edge = data.get('edge', 0)
            model_prob = data.get('model_prob', 0)
            expected_value = data.get('expected_value', 0)
            
            # Apply filters
            if (edge >= edge_threshold and 
                model_prob >= min_probability and 
                expected_value >= min_ev):
                
                bet_info = {
                    'outcome': outcome,
                    'edge': edge,
                    'expected_value': expected_value,
                    'model_probability': model_prob,
                    'odds': data.get('odds', 0),
                    'kelly_fraction': data.get('kelly_fraction', 0),
                    'confidence': 'High' if edge >= 0.05 else 'Medium'
                }
                
                profitable_bets.append(bet_info)
        
        # Sort by expected value (descending)
        profitable_bets.sort(key=lambda x: x['expected_value'], reverse=True)
        
        return profitable_bets

class BettingOptimizer:
    """
    Optimizes betting thresholds and analyzes profitability
    """
    
    def __init__(self):
        self.odds_processor = OddsProcessor()
    
    def run_threshold_sweep(self, predictions_df: pd.DataFrame, 
                           edge_thresholds: List[float] = None,
                           min_prob_thresholds: List[float] = None) -> pd.DataFrame:
        """
        Run threshold sweep to find optimal betting parameters
        
        Args:
            predictions_df: DataFrame with model predictions and actual outcomes
            edge_thresholds: List of edge thresholds to test
            min_prob_thresholds: List of minimum probability thresholds to test
            
        Returns:
            DataFrame with sweep results
        """
        if edge_thresholds is None:
            edge_thresholds = [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.09, 0.10]
        
        if min_prob_thresholds is None:
            min_prob_thresholds = [0.10, 0.15, 0.20, 0.25, 0.30]
        
        sweep_results = []
        
        for edge_thresh in edge_thresholds:
            for prob_thresh in min_prob_thresholds:
                
                # Simulate betting with these thresholds
                result = self._simulate_betting(
                    predictions_df, 
                    edge_threshold=edge_thresh,
                    min_probability=prob_thresh
                )
                
                result.update({
                    'edge_threshold': edge_thresh,
                    'min_probability': prob_thresh
                })
                
                sweep_results.append(result)
        
        sweep_df = pd.DataFrame(sweep_results)
        
        # Find optimal combination
        if len(sweep_df) > 0:
            # Optimize for ROI with minimum bet volume
            sweep_df['score'] = sweep_df['roi'] * np.log(sweep_df['num_bets'] + 1)
            optimal_idx = sweep_df['score'].idxmax()
            optimal_params = sweep_df.iloc[optimal_idx]
            
            print(f"🎯 Optimal betting parameters found:")
            print(f"  Edge threshold: {optimal_params['edge_threshold']:.1%}")
            print(f"  Min probability: {optimal_params['min_probability']:.1%}")
            print(f"  Expected ROI: {optimal_params['roi']:.1%}")
            print(f"  Bets per period: {optimal_params['num_bets']}")
        
        return sweep_df
    
    def _simulate_betting(self, predictions_df: pd.DataFrame, 
                         edge_threshold: float, min_probability: float) -> Dict:
        """Simulate betting with given thresholds"""
        
        total_stake = 0
        total_return = 0
        num_bets = 0
        wins = 0
        
        for _, row in predictions_df.iterrows():
            # Get model probabilities
            model_probs = np.array([row['home_prob'], row['draw_prob'], row['away_prob']])
            
            # Simulate odds (placeholder - would be real odds in production)
            simulated_odds = self._simulate_odds_from_probs(model_probs)
            
            # Calculate EV
            ev_results = self.odds_processor.calculate_expected_value(model_probs, simulated_odds)
            
            # Filter profitable bets
            profitable_bets = self.odds_processor.filter_profitable_bets(
                ev_results, edge_threshold, min_probability
            )
            
            # Place bets
            for bet in profitable_bets:
                stake = 10  # Fixed stake for simulation
                total_stake += stake
                num_bets += 1
                
                # Check if bet won
                actual_outcome = row['actual_outcome']
                if bet['outcome'] == actual_outcome.lower():
                    payout = stake * bet['odds']
                    total_return += payout
                    wins += 1
                else:
                    # Lost bet, no return
                    pass
        
        # Calculate metrics
        roi = ((total_return - total_stake) / total_stake) if total_stake > 0 else 0
        hit_rate = (wins / num_bets) if num_bets > 0 else 0
        avg_ev = np.mean([sum(self.odds_processor.calculate_expected_value(
            np.array([row['home_prob'], row['draw_prob'], row['away_prob']]),
            self._simulate_odds_from_probs(np.array([row['home_prob'], row['draw_prob'], row['away_prob']]))
        ).get(outcome, {}).get('expected_value', 0) for outcome in ['home', 'draw', 'away']) 
        for _, row in predictions_df.iterrows()]) if len(predictions_df) > 0 else 0
        
        return {
            'roi': roi,
            'hit_rate': hit_rate,
            'num_bets': num_bets,
            'total_stake': total_stake,
            'total_return': total_return,
            'avg_ev': avg_ev
        }
    
    def _simulate_odds_from_probs(self, model_probs: np.ndarray) -> Dict:
        """Simulate realistic betting odds from model probabilities"""
        # Add typical bookmaker margin (5-8%)
        margin = 0.06
        
        # Convert probabilities to odds with margin
        fair_odds = 1 / model_probs
        margin_adjusted_probs = model_probs / (1 + margin)
        bookmaker_odds = 1 / margin_adjusted_probs
        
        # Add some noise to make realistic
        noise = np.random.normal(0, 0.05, 3)
        bookmaker_odds = bookmaker_odds * (1 + noise)
        bookmaker_odds = np.maximum(bookmaker_odds, 1.01)  # Minimum odds
        
        return {
            'home_odds': bookmaker_odds[0],
            'draw_odds': bookmaker_odds[1], 
            'away_odds': bookmaker_odds[2],
            'home_fair': model_probs[0],
            'draw_fair': model_probs[1],
            'away_fair': model_probs[2]
        }

def main():
    """Test betting system with sample data"""
    print("🚀 Phase 3: Betting Layer Implementation")
    print("=" * 45)
    
    try:
        # Initialize betting components
        odds_processor = OddsProcessor()
        betting_optimizer = BettingOptimizer()
        
        # Test with sample predictions (placeholder)
        sample_predictions = pd.DataFrame({
            'home_prob': [0.45, 0.30, 0.60, 0.25, 0.40],
            'draw_prob': [0.25, 0.35, 0.20, 0.25, 0.30],
            'away_prob': [0.30, 0.35, 0.20, 0.50, 0.30],
            'actual_outcome': ['Home', 'Away', 'Home', 'Away', 'Draw']
        })
        
        print("📊 Testing EV calculation with sample data...")
        
        # Test EV calculation
        for i, row in sample_predictions.iterrows():
            model_probs = np.array([row['home_prob'], row['draw_prob'], row['away_prob']])
            
            # Simulate odds
            simulated_odds = betting_optimizer._simulate_odds_from_probs(model_probs)
            
            # Calculate EV
            ev_results = odds_processor.calculate_expected_value(model_probs, simulated_odds)
            
            # Filter profitable bets
            profitable_bets = odds_processor.filter_profitable_bets(ev_results, edge_threshold=0.03)
            
            print(f"\n  Match {i+1}:")
            print(f"    Model: H{model_probs[0]:.2f}, D{model_probs[1]:.2f}, A{model_probs[2]:.2f}")
            print(f"    Odds: H{simulated_odds['home_odds']:.2f}, D{simulated_odds['draw_odds']:.2f}, A{simulated_odds['away_odds']:.2f}")
            
            if profitable_bets:
                best_bet = profitable_bets[0]
                print(f"    📈 Best bet: {best_bet['outcome'].upper()} (Edge: {best_bet['edge']:.1%}, EV: {best_bet['expected_value']:.1%})")
            else:
                print(f"    ⚠️ No profitable bets found")
        
        # Run threshold sweep
        print(f"\n🔍 Running threshold optimization...")
        sweep_results = betting_optimizer.run_threshold_sweep(sample_predictions)
        
        if len(sweep_results) > 0:
            print(f"\n📊 Threshold sweep complete:")
            print(f"  Tested {len(sweep_results)} parameter combinations")
            print(f"  Best ROI: {sweep_results['roi'].max():.1%}")
            print(f"  ROI range: {sweep_results['roi'].min():.1%} to {sweep_results['roi'].max():.1%}")
        
        print(f"\n✅ Betting layer ready for integration!")
        print(f"🎯 Next: Monitor production performance and refine thresholds")
        
    except Exception as e:
        print(f"❌ Betting system error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()