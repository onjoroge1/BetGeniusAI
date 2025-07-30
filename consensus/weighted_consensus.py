"""
Weighted Consensus Builder
Apply learned bookmaker weights to build superior market consensus
"""

import os
import pandas as pd
import numpy as np
import psycopg2
import json
from datetime import datetime
from typing import Dict, List, Tuple, Optional

class WeightedConsensusBuilder:
    """Build weighted consensus using learned bookmaker weights"""
    
    def __init__(self):
        self.conn = psycopg2.connect(os.environ['DATABASE_URL'])
        self.bookmakers = ['b365', 'bw', 'iw', 'lb', 'ps', 'wh', 'sj', 'vc']
        self.weights_cache = {}
        
    def load_learned_weights(self, weights_path: str = None) -> Dict:
        """Load learned bookmaker weights"""
        
        if weights_path is None:
            # Find most recent weights file
            weights_dir = 'train/weights'
            if os.path.exists(weights_dir):
                weight_files = [f for f in os.listdir(weights_dir) if f.startswith('bookmaker_weights_')]
                if weight_files:
                    latest_file = sorted(weight_files)[-1]
                    weights_path = os.path.join(weights_dir, latest_file)
        
        if weights_path and os.path.exists(weights_path):
            with open(weights_path, 'r') as f:
                weights_data = json.load(f)
            
            print(f"Loaded weights from {weights_path}")
            return weights_data['learned_weights']
        else:
            print("No weights file found, using equal weights")
            return {}
    
    def get_weights_for_context(self, league: str, era: str) -> Dict[str, float]:
        """Get weights for a specific league/era context"""
        
        key = f"{league}_{era}"
        
        if key in self.weights_cache:
            return self.weights_cache[key]
        
        # Try to find exact match
        learned_weights = self.load_learned_weights()
        
        if key in learned_weights:
            weights = learned_weights[key]['weights']
            self.weights_cache[key] = weights
            return weights
        
        # Fallback: try same league, different era
        for fallback_key, weight_data in learned_weights.items():
            if weight_data['league'] == league:
                weights = weight_data['weights']
                self.weights_cache[key] = weights
                return weights
        
        # Final fallback: equal weights
        equal_weights = {bm: 1.0 / len(self.bookmakers) for bm in self.bookmakers}
        self.weights_cache[key] = equal_weights
        return equal_weights
    
    def convert_odds_to_probabilities(self, odds_h: float, odds_d: float, odds_a: float) -> Tuple[Optional[float], Optional[float], Optional[float]]:
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
    
    def calculate_dispersion_metrics(self, probabilities: List[Tuple[float, float, float]]) -> Dict:
        """Calculate dispersion metrics across bookmaker probabilities"""
        
        if len(probabilities) < 2:
            return {
                'home_std': 0.0,
                'draw_std': 0.0,
                'away_std': 0.0,
                'avg_std': 0.0,
                'entropy': 0.0,
                'n_books': len(probabilities)
            }
        
        probs_array = np.array(probabilities)
        
        # Standard deviation for each outcome
        home_std = np.std(probs_array[:, 0])
        draw_std = np.std(probs_array[:, 1])
        away_std = np.std(probs_array[:, 2])
        avg_std = np.mean([home_std, draw_std, away_std])
        
        # Entropy of average probabilities
        avg_probs = np.mean(probs_array, axis=0)
        avg_probs = np.clip(avg_probs, 1e-15, 1 - 1e-15)
        entropy = -np.sum(avg_probs * np.log(avg_probs))
        
        return {
            'home_std': float(home_std),
            'draw_std': float(draw_std),
            'away_std': float(away_std),
            'avg_std': float(avg_std),
            'entropy': float(entropy),
            'n_books': len(probabilities)
        }
    
    def build_weighted_consensus(self, match_data: Dict, league: str, era: str) -> Dict:
        """Build weighted consensus for a single match"""
        
        # Get weights for this context
        weights = self.get_weights_for_context(league, era)
        
        # Collect valid probabilities and weights
        valid_probs = []
        valid_weights = []
        bookmaker_probs = {}
        
        for bookmaker in self.bookmakers:
            odds_h = match_data.get(f"{bookmaker}_h")
            odds_d = match_data.get(f"{bookmaker}_d")
            odds_a = match_data.get(f"{bookmaker}_a")
            
            prob_h, prob_d, prob_a = self.convert_odds_to_probabilities(odds_h, odds_d, odds_a)
            
            if prob_h is not None:
                probs = [prob_h, prob_d, prob_a]
                valid_probs.append(probs)
                valid_weights.append(weights.get(bookmaker, 0.0))
                bookmaker_probs[bookmaker] = probs
        
        if len(valid_probs) == 0:
            return None
        
        # Normalize weights
        valid_weights = np.array(valid_weights)
        if np.sum(valid_weights) > 0:
            valid_weights = valid_weights / np.sum(valid_weights)
        else:
            valid_weights = np.ones(len(valid_weights)) / len(valid_weights)
        
        # Calculate weighted consensus
        valid_probs = np.array(valid_probs)
        weighted_consensus = np.average(valid_probs, axis=0, weights=valid_weights)
        
        # Calculate dispersion metrics
        dispersion = self.calculate_dispersion_metrics(valid_probs)
        
        # Calculate equal-weight consensus for comparison
        equal_consensus = np.mean(valid_probs, axis=0)
        
        return {
            'weighted_consensus': {
                'home': float(weighted_consensus[0]),
                'draw': float(weighted_consensus[1]),
                'away': float(weighted_consensus[2])
            },
            'equal_consensus': {
                'home': float(equal_consensus[0]),
                'draw': float(equal_consensus[1]),
                'away': float(equal_consensus[2])
            },
            'dispersion': dispersion,
            'bookmaker_probs': bookmaker_probs,
            'weights_used': {bm: float(w) for bm, w in zip([bm for bm in self.bookmakers if bm in bookmaker_probs], valid_weights)}
        }
    
    def determine_era_from_date(self, match_date: str) -> str:
        """Determine era bin from match date"""
        
        if isinstance(match_date, str):
            year = int(match_date.split('-')[0])
        else:
            year = match_date.year
        
        if year <= 1997:
            return '1993-1997'
        elif year <= 2002:
            return '1998-2002'
        elif year <= 2007:
            return '2003-2007'
        elif year <= 2012:
            return '2008-2012'
        elif year <= 2017:
            return '2013-2017'
        elif year <= 2022:
            return '2018-2022'
        else:
            return '2023-2024'
    
    def process_historical_matches(self, limit: int = None) -> pd.DataFrame:
        """Process historical matches to build weighted consensus dataset"""
        
        print("Building weighted consensus for historical matches...")
        
        # Load historical data
        query = """
        SELECT 
            id, match_date, season, league, home_team, away_team, result,
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
        ORDER BY match_date DESC
        """
        
        if limit:
            query += f" LIMIT {limit}"
        
        df = pd.read_sql(query, self.conn)
        print(f"Processing {len(df):,} matches...")
        
        # Process each match
        consensus_results = []
        
        for idx, row in df.iterrows():
            # Determine era
            era = self.determine_era_from_date(row['match_date'])
            
            # Build consensus
            match_data = row.to_dict()
            consensus = self.build_weighted_consensus(match_data, row['league'], era)
            
            if consensus:
                result_record = {
                    'match_id': row['id'],
                    'match_date': row['match_date'],
                    'league': row['league'],
                    'era': era,
                    'home_team': row['home_team'],
                    'away_team': row['away_team'],
                    'result': row['result'],
                    
                    # Weighted consensus
                    'weighted_home': consensus['weighted_consensus']['home'],
                    'weighted_draw': consensus['weighted_consensus']['draw'],
                    'weighted_away': consensus['weighted_consensus']['away'],
                    
                    # Equal weight comparison
                    'equal_home': consensus['equal_consensus']['home'],
                    'equal_draw': consensus['equal_consensus']['draw'],
                    'equal_away': consensus['equal_consensus']['away'],
                    
                    # Dispersion metrics
                    'home_std': consensus['dispersion']['home_std'],
                    'draw_std': consensus['dispersion']['draw_std'],
                    'away_std': consensus['dispersion']['away_std'],
                    'avg_std': consensus['dispersion']['avg_std'],
                    'entropy': consensus['dispersion']['entropy'],
                    'n_books': consensus['dispersion']['n_books']
                }
                
                consensus_results.append(result_record)
            
            if (idx + 1) % 1000 == 0:
                print(f"Processed {idx + 1:,} matches...")
        
        consensus_df = pd.DataFrame(consensus_results)
        print(f"Built consensus for {len(consensus_df):,} matches")
        
        return consensus_df
    
    def evaluate_consensus_performance(self, consensus_df: pd.DataFrame) -> Dict:
        """Evaluate weighted vs equal consensus performance"""
        
        print("Evaluating consensus performance...")
        
        # Convert results to one-hot
        def result_to_onehot(result):
            if result == 'H':
                return [1, 0, 0]
            elif result == 'D':
                return [0, 1, 0]
            elif result == 'A':
                return [0, 0, 1]
            return None
        
        consensus_df['actual'] = consensus_df['result'].apply(result_to_onehot)
        valid_df = consensus_df[consensus_df['actual'].notna()].copy()
        
        # Calculate LogLoss for weighted consensus
        weighted_probs = valid_df[['weighted_home', 'weighted_draw', 'weighted_away']].values
        weighted_probs = np.clip(weighted_probs, 1e-15, 1 - 1e-15)
        actuals = np.vstack(valid_df['actual'].values)
        
        weighted_logloss = -np.mean(np.sum(actuals * np.log(weighted_probs), axis=1))
        
        # Calculate LogLoss for equal consensus
        equal_probs = valid_df[['equal_home', 'equal_draw', 'equal_away']].values
        equal_probs = np.clip(equal_probs, 1e-15, 1 - 1e-15)
        
        equal_logloss = -np.mean(np.sum(actuals * np.log(equal_probs), axis=1))
        
        # Per-league analysis
        league_performance = []
        for league in valid_df['league'].unique():
            league_df = valid_df[valid_df['league'] == league]
            
            if len(league_df) > 50:  # Minimum sample size
                league_weighted_probs = league_df[['weighted_home', 'weighted_draw', 'weighted_away']].values
                league_weighted_probs = np.clip(league_weighted_probs, 1e-15, 1 - 1e-15)
                league_actuals = np.vstack(league_df['actual'].values)
                
                league_equal_probs = league_df[['equal_home', 'equal_draw', 'equal_away']].values
                league_equal_probs = np.clip(league_equal_probs, 1e-15, 1 - 1e-15)
                
                league_weighted_ll = -np.mean(np.sum(league_actuals * np.log(league_weighted_probs), axis=1))
                league_equal_ll = -np.mean(np.sum(league_actuals * np.log(league_equal_probs), axis=1))
                
                league_performance.append({
                    'league': league,
                    'sample_size': len(league_df),
                    'weighted_logloss': league_weighted_ll,
                    'equal_logloss': league_equal_ll,
                    'improvement': league_equal_ll - league_weighted_ll,
                    'avg_n_books': league_df['n_books'].mean(),
                    'avg_dispersion': league_df['avg_std'].mean()
                })
        
        return {
            'overall': {
                'sample_size': len(valid_df),
                'weighted_logloss': weighted_logloss,
                'equal_logloss': equal_logloss,
                'improvement': equal_logloss - weighted_logloss,
                'avg_n_books': valid_df['n_books'].mean(),
                'avg_dispersion': valid_df['avg_std'].mean()
            },
            'by_league': league_performance
        }
    
    def run_consensus_building(self, limit: int = 5000) -> Dict:
        """Run complete weighted consensus building process"""
        
        print("WEIGHTED CONSENSUS BUILDING")
        print("=" * 50)
        
        try:
            # Load learned weights
            self.load_learned_weights()
            
            # Process matches
            consensus_df = self.process_historical_matches(limit)
            
            # Evaluate performance
            performance = self.evaluate_consensus_performance(consensus_df)
            
            # Save results
            os.makedirs('consensus/results', exist_ok=True)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            
            # Save consensus dataset
            consensus_path = f'consensus/results/weighted_consensus_{timestamp}.csv'
            consensus_df.to_csv(consensus_path, index=False)
            
            # Save performance results
            performance_path = f'consensus/results/consensus_performance_{timestamp}.json'
            with open(performance_path, 'w') as f:
                json.dump(performance, f, indent=2, default=str)
            
            # Print results
            print("\n" + "=" * 60)
            print("WEIGHTED CONSENSUS RESULTS")
            print("=" * 60)
            
            overall = performance['overall']
            print(f"\n📊 OVERALL PERFORMANCE:")
            print(f"   • Sample Size: {overall['sample_size']:,} matches")
            print(f"   • Weighted LogLoss: {overall['weighted_logloss']:.4f}")
            print(f"   • Equal Weight LogLoss: {overall['equal_logloss']:.4f}")
            print(f"   • Improvement: {overall['improvement']:.4f}")
            print(f"   • Average Books per Match: {overall['avg_n_books']:.1f}")
            print(f"   • Average Dispersion: {overall['avg_dispersion']:.4f}")
            
            print(f"\n🏆 LEAGUE PERFORMANCE:")
            league_perf = sorted(performance['by_league'], key=lambda x: x['improvement'], reverse=True)
            for league_data in league_perf[:5]:
                print(f"   • {league_data['league']}: {league_data['improvement']:.4f} improvement ({league_data['sample_size']} matches)")
            
            if overall['improvement'] > 0:
                print(f"\n✅ WEIGHTED CONSENSUS OUTPERFORMS EQUAL WEIGHTS")
                print(f"   Expected production gain: {overall['improvement']:.4f} LogLoss")
            else:
                print(f"\n⚠️  Equal weights perform better by {abs(overall['improvement']):.4f}")
            
            print(f"\n📄 Results saved:")
            print(f"   • Consensus data: {consensus_path}")
            print(f"   • Performance: {performance_path}")
            
            return {
                'consensus_df': consensus_df,
                'performance': performance,
                'files': {
                    'consensus_path': consensus_path,
                    'performance_path': performance_path
                }
            }
            
        finally:
            self.conn.close()

def main():
    """Run weighted consensus building"""
    
    builder = WeightedConsensusBuilder()
    results = builder.run_consensus_building()
    
    return results

if __name__ == "__main__":
    main()