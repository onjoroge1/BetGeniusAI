"""
Fix Weighted Consensus Implementation
Implement actual per-match weighted consensus using quality weights
"""

import os
import pandas as pd
import numpy as np
import psycopg2
from datetime import datetime
import json
from typing import Dict, List, Tuple, Optional

class WeightedConsensusFixed:
    """Properly implement weighted consensus using quality weights"""
    
    def __init__(self):
        self.conn = psycopg2.connect(os.environ['DATABASE_URL'])
        self.bookmaker_weights = self.load_quality_weights()
        
    def load_quality_weights(self) -> Dict:
        """Load bookmaker quality weights from Week 2 analysis"""
        
        # Load quality weights from Week 2 analysis
        quality_dir = 'meta/book_quality'
        if os.path.exists(quality_dir):
            quality_files = [f for f in os.listdir(quality_dir) if f.startswith('book_quality_by_era_') and f.endswith('.json')]
            if quality_files:
                latest_file = sorted(quality_files)[-1]
                quality_path = os.path.join(quality_dir, latest_file)
                
                with open(quality_path, 'r') as f:
                    quality_data = json.load(f)
                
                print(f"Loaded quality weights from {quality_path}")
                return quality_data
        
        # Fallback weights based on Week 2 findings
        print("Using fallback weights based on Week 2 analysis")
        return {
            'default_weights': {
                'ps': 0.30,  # Pinnacle - sharp leader (0.9620 LogLoss)
                'b365': 0.25,  # Bet365
                'bw': 0.22,   # Betway  
                'wh': 0.18,   # William Hill
                'vc': 0.05    # Victor Chandler (limited coverage)
            }
        }
    
    def get_bookmaker_weights(self, league: str, era: str = 'recent') -> Dict[str, float]:
        """Get quality weights for specific league and era"""
        
        # Try to get era-specific weights
        if 'by_era' in self.bookmaker_weights:
            era_key = f"{league}_{era}"
            if era_key in self.bookmaker_weights['by_era']:
                return self.bookmaker_weights['by_era'][era_key]['weights']
        
        # Try league-specific weights
        if 'by_league' in self.bookmaker_weights:
            if league in self.bookmaker_weights['by_league']:
                return self.bookmaker_weights['by_league'][league]['weights']
        
        # Fall back to default weights
        return self.bookmaker_weights.get('default_weights', {})
    
    def odds_to_probabilities(self, odds_h: float, odds_d: float, odds_a: float, 
                            remove_margin: bool = True) -> Optional[Tuple[float, float, float]]:
        """Convert decimal odds to probabilities with margin removal"""
        
        if not all(pd.notna([odds_h, odds_d, odds_a])) or not all(o > 1.0 for o in [odds_h, odds_d, odds_a]):
            return None
        
        # Convert to implied probabilities
        prob_h = 1.0 / odds_h
        prob_d = 1.0 / odds_d  
        prob_a = 1.0 / odds_a
        
        if remove_margin:
            # Remove margin by normalizing to sum to 1
            total = prob_h + prob_d + prob_a
            if total > 0:
                prob_h /= total
                prob_d /= total
                prob_a /= total
        
        return prob_h, prob_d, prob_a
    
    def compute_weighted_consensus(self, match_odds: Dict, league: str) -> Dict:
        """Compute weighted consensus for a single match"""
        
        bookmaker_mapping = {
            'b365': ['b365_h', 'b365_d', 'b365_a'],
            'bw': ['bw_h', 'bw_d', 'bw_a'],
            'wh': ['wh_h', 'wh_d', 'wh_a'],
            'ps': ['ps_h', 'ps_d', 'ps_a'],
            'vc': ['vc_h', 'vc_d', 'vc_a']
        }
        
        # Get quality weights for this league
        quality_weights = self.get_bookmaker_weights(league)
        
        valid_probs = []
        valid_weights = []
        used_books = []
        
        # Extract probabilities from each available bookmaker
        for book_code, odds_cols in bookmaker_mapping.items():
            odds_h = match_odds.get(odds_cols[0])
            odds_d = match_odds.get(odds_cols[1])
            odds_a = match_odds.get(odds_cols[2])
            
            probs = self.odds_to_probabilities(odds_h, odds_d, odds_a)
            if probs is not None:
                valid_probs.append(probs)
                weight = quality_weights.get(book_code, 0.2)  # Default weight if not found
                valid_weights.append(weight)
                used_books.append(book_code)
        
        n_books_available = len(valid_probs)
        
        if n_books_available == 0:
            return self._fallback_consensus()
        
        if n_books_available == 1:
            # Single book - use as is
            prob_h, prob_d, prob_a = valid_probs[0]
            return {
                'pH_cons_w': prob_h,
                'pD_cons_w': prob_d,
                'pA_cons_w': prob_a,
                'consensus_method': 'single_book',
                'weights_applied_json': json.dumps({used_books[0]: 1.0}),
                'consensus_fallback': 0,
                'n_books_used': 1
            }
        
        # Multiple books - compute weighted consensus
        valid_probs = np.array(valid_probs)
        valid_weights = np.array(valid_weights)
        
        # Normalize weights to sum to 1
        valid_weights = valid_weights / np.sum(valid_weights)
        
        # Compute weighted average
        weighted_consensus = np.average(valid_probs, axis=0, weights=valid_weights)
        
        # Ensure probabilities sum to 1 (should already be close)
        weighted_consensus = weighted_consensus / np.sum(weighted_consensus)
        
        # Create weights applied dictionary
        weights_applied = dict(zip(used_books, valid_weights.tolist()))
        
        return {
            'pH_cons_w': weighted_consensus[0],
            'pD_cons_w': weighted_consensus[1], 
            'pA_cons_w': weighted_consensus[2],
            'consensus_method': 'weighted_v1',
            'weights_applied_json': json.dumps(weights_applied),
            'consensus_fallback': 0,
            'n_books_used': n_books_available
        }
    
    def compute_equal_weight_consensus(self, match_odds: Dict) -> Dict:
        """Compute equal weight consensus for comparison"""
        
        bookmaker_mapping = {
            'b365': ['b365_h', 'b365_d', 'b365_a'],
            'bw': ['bw_h', 'bw_d', 'bw_a'], 
            'wh': ['wh_h', 'wh_d', 'wh_a'],
            'ps': ['ps_h', 'ps_d', 'ps_a'],
            'vc': ['vc_h', 'vc_d', 'vc_a']
        }
        
        valid_probs = []
        used_books = []
        
        for book_code, odds_cols in bookmaker_mapping.items():
            odds_h = match_odds.get(odds_cols[0])
            odds_d = match_odds.get(odds_cols[1])
            odds_a = match_odds.get(odds_cols[2])
            
            probs = self.odds_to_probabilities(odds_h, odds_d, odds_a)
            if probs is not None:
                valid_probs.append(probs)
                used_books.append(book_code)
        
        if len(valid_probs) == 0:
            return self._fallback_consensus()
        
        # Equal weight average
        equal_consensus = np.mean(valid_probs, axis=0)
        equal_consensus = equal_consensus / np.sum(equal_consensus)
        
        return {
            'pH_equal': equal_consensus[0],
            'pD_equal': equal_consensus[1],
            'pA_equal': equal_consensus[2],
            'n_books_equal': len(valid_probs)
        }
    
    def _fallback_consensus(self) -> Dict:
        """Fallback consensus when no valid odds available"""
        return {
            'pH_cons_w': 1/3,
            'pD_cons_w': 1/3,
            'pA_cons_w': 1/3,
            'consensus_method': 'fallback_uniform',
            'weights_applied_json': json.dumps({}),
            'consensus_fallback': 1,
            'n_books_used': 0
        }
    
    def process_historical_odds(self, limit: int = 2000) -> pd.DataFrame:
        """Process historical odds to create proper weighted consensus"""
        
        print("Processing historical odds for weighted consensus...")
        
        query = """
        SELECT 
            id, match_date, league, home_team, away_team, result,
            b365_h, b365_d, b365_a,
            bw_h, bw_d, bw_a,
            wh_h, wh_d, wh_a,
            ps_h, ps_d, ps_a,
            vc_h, vc_d, vc_a
        FROM historical_odds
        WHERE result IS NOT NULL
        AND match_date >= '2020-01-01'
        AND b365_h IS NOT NULL
        ORDER BY match_date DESC
        LIMIT %s
        """
        
        df = pd.read_sql(query, self.conn, params=[limit])
        print(f"Loaded {len(df)} matches from historical odds")
        
        # Process each match
        consensus_results = []
        equal_results = []
        
        for _, row in df.iterrows():
            match_odds = row.to_dict()
            
            # Compute weighted consensus
            weighted_result = self.compute_weighted_consensus(match_odds, row['league'])
            weighted_result.update({
                'match_id': row['id'],
                'match_date': row['match_date'],
                'league': row['league'],
                'home_team': row['home_team'],
                'away_team': row['away_team'],
                'result': row['result']
            })
            consensus_results.append(weighted_result)
            
            # Compute equal weight consensus for comparison
            equal_result = self.compute_equal_weight_consensus(match_odds)
            equal_result.update({
                'match_id': row['id'],
                'match_date': row['match_date'],
                'league': row['league'],
                'home_team': row['home_team'],
                'away_team': row['away_team'],
                'result': row['result']
            })
            equal_results.append(equal_result)
        
        # Combine results
        consensus_df = pd.DataFrame(consensus_results)
        equal_df = pd.DataFrame(equal_results)
        
        # Merge to create comparison dataset
        merged_df = consensus_df.merge(
            equal_df[['match_id', 'pH_equal', 'pD_equal', 'pA_equal', 'n_books_equal']],
            on='match_id'
        )
        
        # Add dispersion metrics
        merged_df = self.add_dispersion_metrics(merged_df)
        
        # Add sharp book indicators
        merged_df['has_pinnacle'] = merged_df['weights_applied_json'].str.contains('ps').fillna(False).astype(int)
        
        return merged_df
    
    def add_dispersion_metrics(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add dispersion metrics by recomputing from individual book probabilities"""
        
        print("Computing dispersion metrics...")
        
        # Initialize dispersion columns
        df['dispH'] = 0.0
        df['dispD'] = 0.0  
        df['dispA'] = 0.0
        df['disagree_js'] = 0.0
        
        # For matches with >1 book, compute actual dispersion
        query = """
        SELECT 
            id,
            b365_h, b365_d, b365_a,
            bw_h, bw_d, bw_a,
            wh_h, wh_d, wh_a,
            ps_h, ps_d, ps_a,
            vc_h, vc_d, vc_a
        FROM historical_odds
        WHERE id = ANY(%s)
        """
        
        match_ids = df['match_id'].tolist()
        odds_df = pd.read_sql(query, self.conn, params=[match_ids])
        
        bookmaker_mapping = {
            'b365': ['b365_h', 'b365_d', 'b365_a'],
            'bw': ['bw_h', 'bw_d', 'bw_a'],
            'wh': ['wh_h', 'wh_d', 'wh_a'],
            'ps': ['ps_h', 'ps_d', 'ps_a'],
            'vc': ['vc_h', 'vc_d', 'vc_a']
        }
        
        for idx, row in odds_df.iterrows():
            match_id = row['id']
            
            valid_probs = []
            for book_code, odds_cols in bookmaker_mapping.items():
                odds_h = row[odds_cols[0]]
                odds_d = row[odds_cols[1]]
                odds_a = row[odds_cols[2]]
                
                probs = self.odds_to_probabilities(odds_h, odds_d, odds_a)
                if probs is not None:
                    valid_probs.append(probs)
            
            if len(valid_probs) > 1:
                valid_probs = np.array(valid_probs)
                
                # Standard deviation across books for each outcome
                disp_h = np.std(valid_probs[:, 0])
                disp_d = np.std(valid_probs[:, 1])
                disp_a = np.std(valid_probs[:, 2])
                
                # Overall disagreement (mean std across outcomes)
                disagree_js = np.mean([disp_h, disp_d, disp_a])
                
                # Update DataFrame
                mask = df['match_id'] == match_id
                df.loc[mask, 'dispH'] = disp_h
                df.loc[mask, 'dispD'] = disp_d
                df.loc[mask, 'dispA'] = disp_a
                df.loc[mask, 'disagree_js'] = disagree_js
        
        return df
    
    def run_weighted_consensus_fix(self) -> Dict:
        """Run complete weighted consensus fix"""
        
        print("WEIGHTED CONSENSUS FIX")
        print("=" * 30)
        
        try:
            # Process historical odds with proper weighted consensus
            df = self.process_historical_odds(limit=2000)
            
            # Save fixed consensus data
            os.makedirs('consensus/fixed', exist_ok=True)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            
            fixed_consensus_path = f'consensus/fixed/fixed_weighted_consensus_{timestamp}.csv'
            df.to_csv(fixed_consensus_path, index=False)
            
            print(f"Fixed consensus saved to {fixed_consensus_path}")
            
            # Compute summary statistics
            summary_stats = self.compute_fix_summary(df)
            
            # Save summary
            summary_path = f'consensus/fixed/fix_summary_{timestamp}.json'
            with open(summary_path, 'w') as f:
                json.dump(summary_stats, f, indent=2, default=str)
            
            print(f"Fix summary saved to {summary_path}")
            
            self.print_fix_summary(summary_stats)
            
            return {
                'fixed_consensus_path': fixed_consensus_path,
                'summary_path': summary_path,
                'summary_stats': summary_stats,
                'timestamp': timestamp
            }
            
        finally:
            self.conn.close()
    
    def compute_fix_summary(self, df: pd.DataFrame) -> Dict:
        """Compute summary statistics for the fix"""
        
        # Compute differences between weighted and equal
        df['diff_H'] = np.abs(df['pH_cons_w'] - df['pH_equal'])
        df['diff_D'] = np.abs(df['pD_cons_w'] - df['pD_equal'])
        df['diff_A'] = np.abs(df['pA_cons_w'] - df['pA_equal'])
        df['mean_abs_diff'] = (df['diff_H'] + df['diff_D'] + df['diff_A']) / 3
        
        # Check identical triplets
        tolerance = 1e-6
        df['identical_triplet'] = (
            (df['diff_H'] < tolerance) & 
            (df['diff_D'] < tolerance) & 
            (df['diff_A'] < tolerance)
        )
        
        summary = {
            'total_matches': len(df),
            'identical_triplet_count': int(df['identical_triplet'].sum()),
            'identical_triplet_pct': float((df['identical_triplet'].sum() / len(df)) * 100),
            'mean_abs_diff_overall': float(df['mean_abs_diff'].mean()),
            'max_abs_diff_overall': float(df['mean_abs_diff'].max()),
            'by_league': {},
            'by_n_books': {},
            'by_sharp_book': {},
            'consensus_methods': df['consensus_method'].value_counts().to_dict()
        }
        
        # By league analysis
        for league in df['league'].unique():
            subset = df[df['league'] == league]
            summary['by_league'][league] = {
                'count': len(subset),
                'identical_pct': float((subset['identical_triplet'].sum() / len(subset)) * 100),
                'mean_abs_diff': float(subset['mean_abs_diff'].mean()),
                'max_abs_diff': float(subset['mean_abs_diff'].max())
            }
        
        # By number of books
        for n_books in df['n_books_used'].unique():
            subset = df[df['n_books_used'] == n_books]
            summary['by_n_books'][int(n_books)] = {
                'count': len(subset),
                'identical_pct': float((subset['identical_triplet'].sum() / len(subset)) * 100),
                'mean_abs_diff': float(subset['mean_abs_diff'].mean())
            }
        
        # By sharp book presence
        for has_sharp in [0, 1]:
            subset = df[df['has_pinnacle'] == has_sharp]
            sharp_label = 'with_pinnacle' if has_sharp else 'without_pinnacle'
            summary['by_sharp_book'][sharp_label] = {
                'count': len(subset),
                'identical_pct': float((subset['identical_triplet'].sum() / len(subset)) * 100),
                'mean_abs_diff': float(subset['mean_abs_diff'].mean())
            }
        
        return summary
    
    def print_fix_summary(self, summary: Dict):
        """Print comprehensive fix summary"""
        
        print("\n" + "=" * 60)
        print("WEIGHTED CONSENSUS FIX COMPLETE")
        print("=" * 60)
        
        print(f"\n🔧 FIX RESULTS:")
        print(f"   • Total Matches: {summary['total_matches']:,}")
        print(f"   • Identical Triplets: {summary['identical_triplet_pct']:.1f}% (was 100%)")
        print(f"   • Mean Absolute Difference: {summary['mean_abs_diff_overall']:.6f} (was 0.000000)")
        print(f"   • Max Absolute Difference: {summary['max_abs_diff_overall']:.6f}")
        
        print(f"\n📊 BY LEAGUE:")
        for league, stats in summary['by_league'].items():
            print(f"   • {league}: {stats['identical_pct']:.1f}% identical, "
                  f"{stats['mean_abs_diff']:.6f} mean diff ({stats['count']} matches)")
        
        print(f"\n📈 BY NUMBER OF BOOKS:")
        for n_books, stats in summary['by_n_books'].items():
            print(f"   • {n_books} books: {stats['identical_pct']:.1f}% identical, "
                  f"{stats['mean_abs_diff']:.6f} mean diff ({stats['count']} matches)")
        
        print(f"\n🎯 SHARP BOOK IMPACT:")
        for sharp_status, stats in summary['by_sharp_book'].items():
            print(f"   • {sharp_status.replace('_', ' ')}: {stats['identical_pct']:.1f}% identical, "
                  f"{stats['mean_abs_diff']:.6f} mean diff ({stats['count']} matches)")
        
        print(f"\n⚙️  CONSENSUS METHODS USED:")
        for method, count in summary['consensus_methods'].items():
            print(f"   • {method}: {count:,} matches")
        
        # Assessment
        if summary['identical_triplet_pct'] < 10:
            print(f"\n✅ WEIGHTED CONSENSUS FIX SUCCESSFUL:")
            print(f"   • Identical rate dropped from 100% to {summary['identical_triplet_pct']:.1f}%")
            print(f"   • Mean differences now {summary['mean_abs_diff_overall']:.6f} (meaningful)")
            print(f"   • Ready for residual model retraining")
        else:
            print(f"\n⚠️  PARTIAL SUCCESS - NEEDS INVESTIGATION:")
            print(f"   • Identical rate: {summary['identical_triplet_pct']:.1f}% (target: <10%)")
            print(f"   • May need further weight tuning or coverage improvements")

def main():
    """Run weighted consensus fix"""
    
    fixer = WeightedConsensusFixed()
    results = fixer.run_weighted_consensus_fix()
    
    return results

if __name__ == "__main__":
    main()