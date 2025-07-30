"""
Historical Bookmaker Weight Learning
Extract optimal bookmaker weights per league × era for consensus building
"""

import os
import pandas as pd
import numpy as np
import psycopg2
from datetime import datetime
from typing import Dict, List, Tuple
from scipy.optimize import minimize
import json

class BookmakerWeightLearner:
    """Learn optimal bookmaker weights from historical performance"""
    
    def __init__(self):
        self.conn = psycopg2.connect(os.environ['DATABASE_URL'])
        self.bookmakers = ['b365', 'bw', 'iw', 'lb', 'ps', 'wh', 'sj', 'vc']
        self.min_coverage_threshold = 50  # Minimum matches for weight learning
        
    def load_historical_odds(self) -> pd.DataFrame:
        """Load historical odds data for weight learning"""
        
        print("Loading historical odds data...")
        
        query = """
        SELECT 
            match_date, season, league, home_team, away_team, result,
            b365_h, b365_d, b365_a,
            bw_h, bw_d, bw_a,
            iw_h, iw_d, iw_a,
            lb_h, lb_d, lb_a,
            ps_h, ps_d, ps_a,
            wh_h, wh_d, wh_a,
            sj_h, sj_d, sj_a,
            vc_h, vc_d, vc_a
        FROM historical_odds
        WHERE result IS NOT NULL
        AND match_date >= '1993-01-01'
        ORDER BY match_date
        """
        
        df = pd.read_sql(query, self.conn)
        print(f"Loaded {len(df):,} historical matches with odds")
        
        return df
    
    def create_era_bins(self, df: pd.DataFrame) -> pd.DataFrame:
        """Create 5-year era bins for temporal analysis"""
        
        df['match_date'] = pd.to_datetime(df['match_date'])
        df['year'] = df['match_date'].dt.year
        
        # Create 5-year era bins
        era_bins = []
        for year in df['year']:
            if year <= 1997:
                era_bins.append('1993-1997')
            elif year <= 2002:
                era_bins.append('1998-2002')
            elif year <= 2007:
                era_bins.append('2003-2007')
            elif year <= 2012:
                era_bins.append('2008-2012')
            elif year <= 2017:
                era_bins.append('2013-2017')
            elif year <= 2022:
                era_bins.append('2018-2022')
            else:
                era_bins.append('2023-2024')
        
        df['era'] = era_bins
        
        print("Era distribution:")
        print(df['era'].value_counts().sort_index())
        
        return df
    
    def convert_odds_to_probabilities(self, odds_h: float, odds_d: float, odds_a: float) -> Tuple[float, float, float]:
        """Convert odds to margin-adjusted probabilities"""
        
        if pd.isna(odds_h) or pd.isna(odds_d) or pd.isna(odds_a):
            return None, None, None
        
        if odds_h <= 1.0 or odds_d <= 1.0 or odds_a <= 1.0:
            return None, None, None
        
        # Convert to implied probabilities
        prob_h = 1.0 / odds_h
        prob_d = 1.0 / odds_d
        prob_a = 1.0 / odds_a
        
        # Remove margin (normalize)
        total = prob_h + prob_d + prob_a
        if total <= 0:
            return None, None, None
        
        prob_h_norm = prob_h / total
        prob_d_norm = prob_d / total
        prob_a_norm = prob_a / total
        
        return prob_h_norm, prob_d_norm, prob_a_norm
    
    def calculate_bookmaker_logloss(self, df: pd.DataFrame, bookmaker: str, league: str, era: str) -> float:
        """Calculate LogLoss for a specific bookmaker in a league/era"""
        
        # Filter data
        subset = df[(df['league'] == league) & (df['era'] == era)].copy()
        
        if len(subset) < self.min_coverage_threshold:
            return None
        
        # Get odds columns
        odds_h_col = f"{bookmaker}_h"
        odds_d_col = f"{bookmaker}_d"
        odds_a_col = f"{bookmaker}_a"
        
        if odds_h_col not in subset.columns:
            return None
        
        # Convert odds to probabilities
        probs = []
        actuals = []
        
        for idx, row in subset.iterrows():
            prob_h, prob_d, prob_a = self.convert_odds_to_probabilities(
                row[odds_h_col], row[odds_d_col], row[odds_a_col]
            )
            
            if prob_h is None:
                continue
            
            probs.append([prob_h, prob_d, prob_a])
            
            # Convert result to one-hot
            if row['result'] == 'H':
                actuals.append([1, 0, 0])
            elif row['result'] == 'D':
                actuals.append([0, 1, 0])
            elif row['result'] == 'A':
                actuals.append([0, 0, 1])
            else:
                continue
        
        if len(probs) < self.min_coverage_threshold:
            return None
        
        # Calculate LogLoss
        probs = np.array(probs)
        actuals = np.array(actuals)
        
        # Clip probabilities to avoid log(0)
        probs = np.clip(probs, 1e-15, 1 - 1e-15)
        
        # Calculate cross-entropy loss
        log_loss = -np.mean(np.sum(actuals * np.log(probs), axis=1))
        
        return log_loss
    
    def learn_optimal_weights(self, df: pd.DataFrame, league: str, era: str) -> Dict:
        """Learn optimal bookmaker weights for a league/era combination"""
        
        print(f"Learning weights for {league} in {era}...")
        
        # Calculate individual bookmaker performance
        bookmaker_performance = {}
        valid_bookmakers = []
        
        for bookmaker in self.bookmakers:
            logloss = self.calculate_bookmaker_logloss(df, bookmaker, league, era)
            if logloss is not None:
                bookmaker_performance[bookmaker] = logloss
                valid_bookmakers.append(bookmaker)
        
        if len(valid_bookmakers) < 2:
            print(f"  Insufficient bookmaker coverage for {league} {era}")
            return None
        
        print(f"  Valid bookmakers: {valid_bookmakers}")
        print(f"  Individual LogLoss: {bookmaker_performance}")
        
        # Optimize weights to minimize weighted consensus LogLoss
        def objective(weights):
            return self.evaluate_weighted_consensus(df, league, era, valid_bookmakers, weights)
        
        # Constraints: weights sum to 1, all non-negative
        constraints = [{'type': 'eq', 'fun': lambda w: np.sum(w) - 1.0}]
        bounds = [(0.0, 1.0) for _ in valid_bookmakers]
        
        # Initial guess: inverse of LogLoss (better performers get higher weight)
        inv_logloss = [1.0 / bookmaker_performance[bm] for bm in valid_bookmakers]
        initial_weights = np.array(inv_logloss) / np.sum(inv_logloss)
        
        # Optimize
        result = minimize(
            objective, 
            initial_weights,
            method='SLSQP',
            bounds=bounds,
            constraints=constraints,
            options={'maxiter': 1000}
        )
        
        if result.success:
            optimal_weights = result.x
            optimal_logloss = result.fun
            
            # Create weight mapping
            weight_mapping = {bm: float(w) for bm, w in zip(valid_bookmakers, optimal_weights)}
            
            # Add equal-weight baseline for comparison
            equal_weights = [1.0 / len(valid_bookmakers)] * len(valid_bookmakers)
            equal_logloss = self.evaluate_weighted_consensus(df, league, era, valid_bookmakers, equal_weights)
            
            return {
                'league': league,
                'era': era,
                'valid_bookmakers': valid_bookmakers,
                'weights': weight_mapping,
                'optimal_logloss': optimal_logloss,
                'equal_weight_logloss': equal_logloss,
                'improvement': equal_logloss - optimal_logloss,
                'sample_size': len(df[(df['league'] == league) & (df['era'] == era)]),
                'individual_performance': bookmaker_performance
            }
        else:
            print(f"  Optimization failed for {league} {era}")
            return None
    
    def evaluate_weighted_consensus(self, df: pd.DataFrame, league: str, era: str, 
                                   bookmakers: List[str], weights: np.ndarray) -> float:
        """Evaluate LogLoss of weighted consensus"""
        
        subset = df[(df['league'] == league) & (df['era'] == era)].copy()
        
        consensus_probs = []
        actuals = []
        
        for idx, row in subset.iterrows():
            # Collect valid probabilities from all bookmakers
            valid_probs = []
            valid_weights = []
            
            for i, bookmaker in enumerate(bookmakers):
                prob_h, prob_d, prob_a = self.convert_odds_to_probabilities(
                    row[f"{bookmaker}_h"], row[f"{bookmaker}_d"], row[f"{bookmaker}_a"]
                )
                
                if prob_h is not None:
                    valid_probs.append([prob_h, prob_d, prob_a])
                    valid_weights.append(weights[i])
            
            if len(valid_probs) == 0:
                continue
            
            # Calculate weighted consensus
            valid_probs = np.array(valid_probs)
            valid_weights = np.array(valid_weights)
            
            # Normalize weights
            if np.sum(valid_weights) > 0:
                valid_weights = valid_weights / np.sum(valid_weights)
                
                # Weighted average
                consensus_prob = np.average(valid_probs, axis=0, weights=valid_weights)
                consensus_probs.append(consensus_prob)
                
                # Actual outcome
                if row['result'] == 'H':
                    actuals.append([1, 0, 0])
                elif row['result'] == 'D':
                    actuals.append([0, 1, 0])
                elif row['result'] == 'A':
                    actuals.append([0, 0, 1])
                else:
                    continue
        
        if len(consensus_probs) == 0:
            return float('inf')
        
        # Calculate LogLoss
        consensus_probs = np.array(consensus_probs)
        actuals = np.array(actuals)
        
        # Clip probabilities
        consensus_probs = np.clip(consensus_probs, 1e-15, 1 - 1e-15)
        
        log_loss = -np.mean(np.sum(actuals * np.log(consensus_probs), axis=1))
        
        return log_loss
    
    def learn_all_weights(self) -> Dict:
        """Learn weights for all league/era combinations"""
        
        print("LEARNING BOOKMAKER WEIGHTS")
        print("=" * 50)
        
        # Load data
        df = self.load_historical_odds()
        df = self.create_era_bins(df)
        
        # Get unique league/era combinations
        combinations = df.groupby(['league', 'era']).size().reset_index(name='count')
        combinations = combinations[combinations['count'] >= self.min_coverage_threshold]
        
        print(f"\nLearning weights for {len(combinations)} league/era combinations...")
        
        # Learn weights for each combination
        all_weights = {}
        results_summary = []
        
        for _, row in combinations.iterrows():
            league = row['league']
            era = row['era']
            
            weight_result = self.learn_optimal_weights(df, league, era)
            
            if weight_result:
                key = f"{league}_{era}"
                all_weights[key] = weight_result
                results_summary.append({
                    'league': league,
                    'era': era,
                    'sample_size': weight_result['sample_size'],
                    'optimal_logloss': weight_result['optimal_logloss'],
                    'equal_weight_logloss': weight_result['equal_weight_logloss'],
                    'improvement': weight_result['improvement'],
                    'best_bookmaker': max(weight_result['weights'], key=weight_result['weights'].get),
                    'best_weight': max(weight_result['weights'].values())
                })
        
        return {
            'learned_weights': all_weights,
            'summary': results_summary,
            'metadata': {
                'total_combinations': len(combinations),
                'successful_combinations': len(all_weights),
                'bookmakers_analyzed': self.bookmakers,
                'min_coverage_threshold': self.min_coverage_threshold,
                'learning_timestamp': datetime.now().isoformat()
            }
        }
    
    def save_weights(self, weights_data: Dict) -> str:
        """Save learned weights to files"""
        
        os.makedirs('train/weights', exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # Save complete weights data
        weights_path = f'train/weights/bookmaker_weights_{timestamp}.json'
        with open(weights_path, 'w') as f:
            json.dump(weights_data, f, indent=2, default=str)
        
        # Save CSV summary for easy analysis
        summary_df = pd.DataFrame(weights_data['summary'])
        summary_path = f'train/weights/weights_summary_{timestamp}.csv'
        summary_df.to_csv(summary_path, index=False)
        
        # Save individual weight files per league/era
        for key, weight_info in weights_data['learned_weights'].items():
            league = weight_info['league']
            era = weight_info['era']
            
            weight_file = f'train/weights/BOOK_WEIGHTS_{league}_{era.replace("-", "_")}.csv'
            
            # Create CSV with bookmaker weights
            weights_df = pd.DataFrame([
                {'bookmaker': bm, 'weight': weight} 
                for bm, weight in weight_info['weights'].items()
            ])
            weights_df.to_csv(weight_file, index=False)
        
        return weights_path
    
    def run_weight_learning(self) -> Dict:
        """Run complete weight learning process"""
        
        try:
            # Learn weights
            weights_data = self.learn_all_weights()
            
            # Save results
            weights_path = self.save_weights(weights_data)
            
            # Print summary
            print("\n" + "=" * 60)
            print("BOOKMAKER WEIGHT LEARNING COMPLETE")
            print("=" * 60)
            
            summary = weights_data['summary']
            if summary:
                summary_df = pd.DataFrame(summary)
                
                print(f"\n📊 LEARNING SUMMARY:")
                print(f"   • Combinations Analyzed: {len(summary)}")
                print(f"   • Total Improvement: {summary_df['improvement'].sum():.4f} LogLoss")
                print(f"   • Average Improvement: {summary_df['improvement'].mean():.4f} LogLoss")
                print(f"   • Best Single Improvement: {summary_df['improvement'].max():.4f} LogLoss")
                
                print(f"\n🏆 TOP PERFORMING BOOKMAKERS:")
                best_bookmakers = summary_df.groupby('best_bookmaker').agg({
                    'improvement': 'sum',
                    'league': 'count'
                }).sort_values('improvement', ascending=False)
                
                for bookmaker, data in best_bookmakers.head(5).iterrows():
                    print(f"   • {bookmaker}: {data['improvement']:.4f} total improvement ({data['league']} combinations)")
                
                print(f"\n📈 LEAGUE ANALYSIS:")
                league_summary = summary_df.groupby('league').agg({
                    'improvement': 'mean',
                    'sample_size': 'sum'
                }).sort_values('improvement', ascending=False)
                
                for league, data in league_summary.iterrows():
                    print(f"   • {league}: {data['improvement']:.4f} avg improvement ({data['sample_size']} total matches)")
            
            print(f"\n📄 Results saved: {weights_path}")
            
            return weights_data
            
        finally:
            self.conn.close()

def main():
    """Run bookmaker weight learning"""
    
    learner = BookmakerWeightLearner()
    results = learner.run_weight_learning()
    
    return results

if __name__ == "__main__":
    main()