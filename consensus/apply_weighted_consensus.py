"""
Apply Weighted Consensus Builder
Build T-72h weighted consensus with dispersion metrics and book intelligence
"""

import os
import pandas as pd
import numpy as np
import psycopg2
import json
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional

class WeightedConsensusApplier:
    """Apply quality-weighted consensus using book intelligence"""
    
    def __init__(self):
        self.conn = psycopg2.connect(os.environ['DATABASE_URL'])
        self.bookmakers = ['b365', 'bw', 'iw', 'lb', 'ps', 'wh', 'sj', 'vc']
        self.quality_weights_cache = {}
        
    def load_quality_weights(self) -> Dict:
        """Load bookmaker quality weights from analysis"""
        
        # Find most recent quality analysis
        quality_dir = 'meta/book_quality'
        if os.path.exists(quality_dir):
            weight_files = [f for f in os.listdir(quality_dir) if f.startswith('quality_weights_')]
            if weight_files:
                latest_file = sorted(weight_files)[-1]
                weights_path = os.path.join(quality_dir, latest_file)
                
                with open(weights_path, 'r') as f:
                    quality_weights = json.load(f)
                
                print(f"Loaded quality weights from {weights_path}")
                return quality_weights
        
        print("No quality weights found, will use equal weights")
        return {}
    
    def get_quality_weights_for_context(self, league: str, era_bin: str) -> Dict[str, float]:
        """Get quality weights for specific league/era context"""
        
        if not hasattr(self, 'quality_weights'):
            self.quality_weights = self.load_quality_weights()
        
        # Try exact match first
        key = f"{league}_{era_bin}"
        if key in self.quality_weights:
            return self.quality_weights[key].get('quality_weights', {})
        
        # Fallback to same league, different era
        for fallback_key, weight_data in self.quality_weights.items():
            if fallback_key.startswith(f"{league}_"):
                return weight_data.get('quality_weights', {})
        
        # Final fallback: equal weights
        return {bm: 1.0 / len(self.bookmakers) for bm in self.bookmakers}
    
    def determine_era_bin(self, match_date: str) -> str:
        """Determine era bin from match date"""
        
        if isinstance(match_date, str):
            year = int(match_date.split('-')[0])
        else:
            year = match_date.year
        
        if year <= 2002:
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
    
    def convert_odds_to_probabilities(self, odds_h: float, odds_d: float, odds_a: float) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
        """Convert odds to margin-adjusted probabilities with overround"""
        
        if pd.isna(odds_h) or pd.isna(odds_d) or pd.isna(odds_a):
            return None, None, None, None
        
        if odds_h <= 1.0 or odds_d <= 1.0 or odds_a <= 1.0:
            return None, None, None, None
        
        # Raw implied probabilities
        raw_prob_h = 1.0 / odds_h
        raw_prob_d = 1.0 / odds_d
        raw_prob_a = 1.0 / odds_a
        
        # Overround
        overround = raw_prob_h + raw_prob_d + raw_prob_a
        
        # Margin-adjusted probabilities
        prob_h = raw_prob_h / overround
        prob_d = raw_prob_d / overround
        prob_a = raw_prob_a / overround
        
        return prob_h, prob_d, prob_a, overround
    
    def calculate_consensus_and_dispersion(self, match_data: Dict, league: str, era_bin: str) -> Dict:
        """Calculate weighted consensus with comprehensive dispersion metrics"""
        
        # Get quality weights for context
        weights = self.get_quality_weights_for_context(league, era_bin)
        
        # Collect valid probabilities, weights, and metadata
        valid_probs = []
        valid_weights = []
        valid_overrounds = []
        bookmaker_data = {}
        
        for bookmaker in self.bookmakers:
            odds_h = match_data.get(f"{bookmaker}_h")
            odds_d = match_data.get(f"{bookmaker}_d")
            odds_a = match_data.get(f"{bookmaker}_a")
            
            prob_h, prob_d, prob_a, overround = self.convert_odds_to_probabilities(
                odds_h, odds_d, odds_a
            )
            
            if prob_h is not None:
                probs = [prob_h, prob_d, prob_a]
                valid_probs.append(probs)
                valid_weights.append(weights.get(bookmaker, 0.0))
                valid_overrounds.append(overround)
                
                bookmaker_data[bookmaker] = {
                    'probs': probs,
                    'overround': overround,
                    'weight': weights.get(bookmaker, 0.0)
                }
        
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
        
        # Calculate equal weight consensus for comparison
        equal_consensus = np.mean(valid_probs, axis=0)
        
        # Calculate dispersion metrics
        dispersion_metrics = self.calculate_dispersion_metrics(valid_probs, valid_overrounds)
        
        # Calculate disagreement metrics
        disagreement_metrics = self.calculate_disagreement_metrics(
            valid_probs, weighted_consensus
        )
        
        return {
            'weighted_consensus': {
                'pH_cons_w': float(weighted_consensus[0]),
                'pD_cons_w': float(weighted_consensus[1]),
                'pA_cons_w': float(weighted_consensus[2])
            },
            'equal_consensus': {
                'pH_cons_e': float(equal_consensus[0]),
                'pD_cons_e': float(equal_consensus[1]),
                'pA_cons_e': float(equal_consensus[2])
            },
            'dispersion': dispersion_metrics,
            'disagreement': disagreement_metrics,
            'bookmaker_data': bookmaker_data,
            'n_books': len(valid_probs),
            'avg_overround': float(np.mean(valid_overrounds)),
            'weights_used': {bm: float(w) for bm, w in zip([bm for bm in self.bookmakers if bm in bookmaker_data], valid_weights)}
        }
    
    def calculate_dispersion_metrics(self, probs: np.ndarray, overrounds: List[float]) -> Dict:
        """Calculate comprehensive dispersion metrics"""
        
        if len(probs) < 2:
            return {
                'dispH': 0.0,
                'dispD': 0.0,
                'dispA': 0.0,
                'avg_dispersion': 0.0,
                'max_dispersion': 0.0,
                'overround_std': 0.0
            }
        
        # Standard deviation for each outcome
        disp_h = float(np.std(probs[:, 0]))
        disp_d = float(np.std(probs[:, 1]))
        disp_a = float(np.std(probs[:, 2]))
        
        avg_dispersion = np.mean([disp_h, disp_d, disp_a])
        max_dispersion = np.max([disp_h, disp_d, disp_a])
        
        # Overround dispersion
        overround_std = float(np.std(overrounds))
        
        return {
            'dispH': disp_h,
            'dispD': disp_d,
            'dispA': disp_a,
            'avg_dispersion': float(avg_dispersion),
            'max_dispersion': float(max_dispersion),
            'overround_std': overround_std
        }
    
    def calculate_disagreement_metrics(self, probs: np.ndarray, consensus: np.ndarray) -> Dict:
        """Calculate disagreement metrics using Jensen-Shannon divergence"""
        
        if len(probs) < 2:
            return {
                'disagree_js': 0.0,
                'max_kl_div': 0.0,
                'avg_kl_div': 0.0
            }
        
        # Jensen-Shannon divergence between each bookmaker and consensus
        js_divergences = []
        kl_divergences = []
        
        for prob in probs:
            # Ensure valid probability distributions
            prob = np.clip(prob, 1e-15, 1 - 1e-15)
            consensus_clipped = np.clip(consensus, 1e-15, 1 - 1e-15)
            
            # Calculate KL divergence: KL(prob || consensus)
            kl_div = np.sum(prob * np.log(prob / consensus_clipped))
            kl_divergences.append(kl_div)
            
            # Calculate Jensen-Shannon divergence
            m = 0.5 * (prob + consensus_clipped)
            js_div = 0.5 * np.sum(prob * np.log(prob / m)) + 0.5 * np.sum(consensus_clipped * np.log(consensus_clipped / m))
            js_divergences.append(js_div)
        
        return {
            'disagree_js': float(np.mean(js_divergences)),
            'max_kl_div': float(np.max(kl_divergences)),
            'avg_kl_div': float(np.mean(kl_divergences))
        }
    
    def process_historical_matches(self, limit: int = 10000) -> pd.DataFrame:
        """Process historical matches to build weighted consensus dataset"""
        
        print(f"Building weighted consensus for up to {limit:,} historical matches...")
        
        # Load historical data (focus on recent matches for efficiency)
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
        AND match_date >= '2020-01-01'
        ORDER BY match_date DESC
        """
        
        if limit:
            query += f" LIMIT {limit}"
        
        df = pd.read_sql(query, self.conn)
        print(f"Processing {len(df):,} matches...")
        
        # Process each match
        consensus_results = []
        
        for idx, row in df.iterrows():
            # Determine era and context
            era_bin = self.determine_era_bin(row['match_date'])
            
            # Build consensus
            match_data = row.to_dict()
            consensus_data = self.calculate_consensus_and_dispersion(
                match_data, row['league'], era_bin
            )
            
            if consensus_data:
                # Create record with all consensus information
                result_record = {
                    'match_id': row['id'],
                    'match_date': row['match_date'],
                    'league': row['league'],
                    'era_bin': era_bin,
                    'home_team': row['home_team'],
                    'away_team': row['away_team'],
                    'result': row['result'],
                    
                    # Weighted consensus (T-72h equivalent)
                    'pH_cons_w': consensus_data['weighted_consensus']['pH_cons_w'],
                    'pD_cons_w': consensus_data['weighted_consensus']['pD_cons_w'],
                    'pA_cons_w': consensus_data['weighted_consensus']['pA_cons_w'],
                    
                    # Equal weight consensus for comparison
                    'pH_cons_e': consensus_data['equal_consensus']['pH_cons_e'],
                    'pD_cons_e': consensus_data['equal_consensus']['pD_cons_e'],
                    'pA_cons_e': consensus_data['equal_consensus']['pA_cons_e'],
                    
                    # Dispersion metrics
                    'dispH': consensus_data['dispersion']['dispH'],
                    'dispD': consensus_data['dispersion']['dispD'],
                    'dispA': consensus_data['dispersion']['dispA'],
                    'avg_dispersion': consensus_data['dispersion']['avg_dispersion'],
                    'max_dispersion': consensus_data['dispersion']['max_dispersion'],
                    
                    # Market metadata
                    'n_books': consensus_data['n_books'],
                    'avg_overround': consensus_data['avg_overround'],
                    'overround_std': consensus_data['dispersion']['overround_std'],
                    
                    # Disagreement metrics
                    'disagree_js': consensus_data['disagreement']['disagree_js'],
                    'max_kl_div': consensus_data['disagreement']['max_kl_div'],
                    'avg_kl_div': consensus_data['disagreement']['avg_kl_div']
                }
                
                consensus_results.append(result_record)
            
            if (idx + 1) % 1000 == 0:
                print(f"Processed {idx + 1:,} matches...")
        
        consensus_df = pd.DataFrame(consensus_results)
        print(f"Built weighted consensus for {len(consensus_df):,} matches")
        
        return consensus_df
    
    def evaluate_consensus_performance(self, consensus_df: pd.DataFrame) -> Dict:
        """Evaluate weighted vs equal consensus performance"""
        
        print("Evaluating weighted consensus performance...")
        
        # Convert results to one-hot encoding
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
        weighted_probs = valid_df[['pH_cons_w', 'pD_cons_w', 'pA_cons_w']].values
        weighted_probs = np.clip(weighted_probs, 1e-15, 1 - 1e-15)
        actuals = np.vstack(valid_df['actual'].values)
        
        weighted_logloss = -np.mean(np.sum(actuals * np.log(weighted_probs), axis=1))
        
        # Calculate LogLoss for equal consensus
        equal_probs = valid_df[['pH_cons_e', 'pD_cons_e', 'pA_cons_e']].values
        equal_probs = np.clip(equal_probs, 1e-15, 1 - 1e-15)
        
        equal_logloss = -np.mean(np.sum(actuals * np.log(equal_probs), axis=1))
        
        # Calculate Brier scores
        weighted_brier = np.mean(np.sum((weighted_probs - actuals) ** 2, axis=1))
        equal_brier = np.mean(np.sum((equal_probs - actuals) ** 2, axis=1))
        
        # Per-league analysis
        league_performance = []
        for league in valid_df['league'].unique():
            league_df = valid_df[valid_df['league'] == league]
            
            if len(league_df) >= 100:  # Minimum sample size
                league_weighted_probs = league_df[['pH_cons_w', 'pD_cons_w', 'pA_cons_w']].values
                league_weighted_probs = np.clip(league_weighted_probs, 1e-15, 1 - 1e-15)
                league_actuals = np.vstack(league_df['actual'].values)
                
                league_equal_probs = league_df[['pH_cons_e', 'pD_cons_e', 'pA_cons_e']].values
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
                    'avg_dispersion': league_df['avg_dispersion'].mean(),
                    'avg_disagreement': league_df['disagree_js'].mean()
                })
        
        return {
            'overall': {
                'sample_size': len(valid_df),
                'weighted_logloss': weighted_logloss,
                'equal_logloss': equal_logloss,
                'logloss_improvement': equal_logloss - weighted_logloss,
                'weighted_brier': weighted_brier,
                'equal_brier': equal_brier,
                'brier_improvement': equal_brier - weighted_brier,
                'avg_n_books': valid_df['n_books'].mean(),
                'avg_dispersion': valid_df['avg_dispersion'].mean(),
                'avg_disagreement': valid_df['disagree_js'].mean()
            },
            'by_league': league_performance
        }
    
    def run_weighted_consensus_application(self, limit: int = 10000) -> Dict:
        """Run complete weighted consensus application"""
        
        print("WEIGHTED CONSENSUS APPLICATION - WEEK 2")
        print("=" * 50)
        print("Applying quality-weighted consensus with book intelligence...")
        
        try:
            # Process matches
            consensus_df = self.process_historical_matches(limit)
            
            # Evaluate performance
            performance = self.evaluate_consensus_performance(consensus_df)
            
            # Save results
            os.makedirs('consensus/weighted', exist_ok=True)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            
            # Save consensus dataset
            consensus_path = f'consensus/weighted/weighted_consensus_t72_{timestamp}.csv'
            consensus_df.to_csv(consensus_path, index=False)
            
            # Save performance analysis
            performance_path = f'consensus/weighted/consensus_performance_{timestamp}.json'
            with open(performance_path, 'w') as f:
                json.dump(performance, f, indent=2, default=str)
            
            # Compile results
            results = {
                'timestamp': datetime.now().isoformat(),
                'consensus_df': consensus_df,
                'performance': performance,
                'files': {
                    'consensus_path': consensus_path,
                    'performance_path': performance_path
                }
            }
            
            # Print comprehensive summary
            self.print_consensus_summary(results)
            
            return results
            
        finally:
            self.conn.close()
    
    def print_consensus_summary(self, results: Dict):
        """Print comprehensive consensus application summary"""
        
        print("\n" + "=" * 60)
        print("WEIGHTED CONSENSUS APPLICATION COMPLETE")
        print("=" * 60)
        
        performance = results['performance']
        overall = performance['overall']
        
        print(f"\n📊 CONSENSUS PERFORMANCE:")
        print(f"   • Sample Size: {overall['sample_size']:,} matches")
        print(f"   • Weighted LogLoss: {overall['weighted_logloss']:.4f}")
        print(f"   • Equal Weight LogLoss: {overall['equal_logloss']:.4f}")
        print(f"   • LogLoss Improvement: {overall['logloss_improvement']:.4f}")
        print(f"   • Weighted Brier: {overall['weighted_brier']:.4f}")
        print(f"   • Equal Brier: {overall['equal_brier']:.4f}")
        print(f"   • Brier Improvement: {overall['brier_improvement']:.4f}")
        
        print(f"\n📈 MARKET INTELLIGENCE:")
        print(f"   • Average Books per Match: {overall['avg_n_books']:.1f}")
        print(f"   • Average Dispersion: {overall['avg_dispersion']:.4f}")
        print(f"   • Average Disagreement (JS): {overall['avg_disagreement']:.4f}")
        
        print(f"\n🏆 LEAGUE PERFORMANCE:")
        league_perf = sorted(performance['by_league'], key=lambda x: x['improvement'], reverse=True)
        for league_data in league_perf[:5]:
            print(f"   • {league_data['league']}: {league_data['improvement']:.4f} improvement ({league_data['sample_size']} matches)")
        
        if overall['logloss_improvement'] > 0:
            print(f"\n✅ QUALITY-WEIGHTED CONSENSUS OUTPERFORMS EQUAL WEIGHTS")
            print(f"   Production gain: {overall['logloss_improvement']:.4f} LogLoss")
        else:
            print(f"\n⚠️  Equal weights still competitive ({abs(overall['logloss_improvement']):.4f} difference)")
        
        print(f"\n🎯 WEEK 2 READINESS:")
        print(f"   • T-72h weighted consensus: Ready")
        print(f"   • Dispersion metrics: Complete")
        print(f"   • Disagreement features: Available")
        print(f"   • Next: Train residual-on-market head with book features")
        
        print(f"\n📄 Files saved:")
        for name, path in results['files'].items():
            print(f"   • {name}: {path}")

def main():
    """Run weighted consensus application"""
    
    applier = WeightedConsensusApplier()
    results = applier.run_weighted_consensus_application()
    
    return results

if __name__ == "__main__":
    main()