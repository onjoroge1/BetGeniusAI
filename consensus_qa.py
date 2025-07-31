"""
Consensus QA Tool
Validate that weighted consensus is actually different from equal weight
"""

import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime
import argparse
from typing import Dict, List, Tuple

class ConsensusQA:
    """Quality assurance for weighted vs equal consensus"""
    
    def __init__(self, outdir: str = "./consensus_qa_artifacts"):
        self.outdir = outdir
        os.makedirs(outdir, exist_ok=True)
    
    def load_or_generate_data(self, data_path: str = None) -> pd.DataFrame:
        """Load consensus data or generate synthetic for testing"""
        
        if data_path and os.path.exists(data_path):
            print(f"Loading consensus data from {data_path}")
            return pd.read_csv(data_path)
        else:
            print("Generating synthetic consensus data for testing...")
            np.random.seed(42)
            
            n_samples = 1000
            
            # Generate synthetic data
            leagues = np.random.choice(['E0', 'SP1', 'I1', 'D1', 'F1'], n_samples, p=[0.3, 0.2, 0.2, 0.15, 0.15])
            n_books = np.random.choice([2, 3, 4, 5, 6], n_samples, p=[0.1, 0.2, 0.3, 0.3, 0.1])
            has_pinnacle = np.random.choice([0, 1], n_samples, p=[0.3, 0.7])
            
            # Generate equal weight consensus (base probabilities)
            home_base = np.random.uniform(0.2, 0.7, n_samples)
            draw_base = np.random.uniform(0.15, 0.35, n_samples)
            away_base = 1.0 - home_base - draw_base
            away_base = np.clip(away_base, 0.05, 0.8)
            
            # Normalize
            total = home_base + draw_base + away_base
            pH_equal = home_base / total
            pD_equal = draw_base / total
            pA_equal = away_base / total
            
            # Generate weighted consensus with some differences
            # Differences should be more pronounced when:
            # 1. More books available
            # 2. Sharp books (Pinnacle) present
            # 3. Certain leagues
            
            adjustment_factor = np.zeros(n_samples)
            
            # More books = more potential for weighting differences
            adjustment_factor += (n_books - 3) * 0.002
            
            # Pinnacle presence increases differences
            adjustment_factor += has_pinnacle * 0.003
            
            # League-specific differences
            league_adjustments = {'E0': 0.002, 'SP1': 0.0015, 'I1': 0.001, 'D1': 0.0008, 'F1': 0.001}
            for i, league in enumerate(leagues):
                adjustment_factor[i] += league_adjustments.get(league, 0)
            
            # Apply random noise and adjustments to create weighted differences
            pH_weighted = pH_equal + np.random.normal(0, np.maximum(adjustment_factor, 1e-6)) * np.random.choice([-1, 1], n_samples)
            pD_weighted = pD_equal + np.random.normal(0, np.maximum(adjustment_factor * 0.5, 1e-6)) * np.random.choice([-1, 1], n_samples)
            pA_weighted = pA_equal + np.random.normal(0, np.maximum(adjustment_factor, 1e-6)) * np.random.choice([-1, 1], n_samples)
            
            # Normalize weighted probabilities
            total_weighted = pH_weighted + pD_weighted + pA_weighted
            pH_weighted = np.clip(pH_weighted / total_weighted, 0.01, 0.99)
            pD_weighted = np.clip(pD_weighted / total_weighted, 0.01, 0.99)
            pA_weighted = np.clip(pA_weighted / total_weighted, 0.01, 0.99)
            
            # For some matches, make weighted identical to equal (simulating fallback cases)
            identical_mask = np.random.random(n_samples) < 0.15  # 15% identical
            pH_weighted[identical_mask] = pH_equal[identical_mask]
            pD_weighted[identical_mask] = pD_equal[identical_mask]
            pA_weighted[identical_mask] = pA_equal[identical_mask]
            
            # Create DataFrame
            df = pd.DataFrame({
                'league': leagues,
                'n_books': n_books,
                'has_pinnacle': has_pinnacle,
                'pH_equal': pH_equal,
                'pD_equal': pD_equal,
                'pA_equal': pA_equal,
                'pH_weighted': pH_weighted,
                'pD_weighted': pD_weighted,
                'pA_weighted': pA_weighted
            })
            
            return df
    
    def compute_consensus_differences(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute differences between weighted and equal consensus"""
        
        # Absolute differences per outcome
        df['diff_H'] = np.abs(df['pH_weighted'] - df['pH_equal'])
        df['diff_D'] = np.abs(df['pD_weighted'] - df['pD_equal'])
        df['diff_A'] = np.abs(df['pA_weighted'] - df['pA_equal'])
        
        # Mean absolute difference across outcomes
        df['mean_abs_diff'] = (df['diff_H'] + df['diff_D'] + df['diff_A']) / 3
        
        # Maximum difference across outcomes
        df['max_abs_diff'] = np.maximum.reduce([df['diff_H'], df['diff_D'], df['diff_A']])
        
        # Check if triplets are identical (within small tolerance)
        tolerance = 1e-6
        df['identical_triplet'] = (
            (df['diff_H'] < tolerance) & 
            (df['diff_D'] < tolerance) & 
            (df['diff_A'] < tolerance)
        )
        
        return df
    
    def generate_summary_statistics(self, df: pd.DataFrame) -> Dict:
        """Generate comprehensive summary statistics"""
        
        summary = {}
        
        # Overall statistics
        summary['total_matches'] = len(df)
        summary['identical_triplet_count'] = df['identical_triplet'].sum()
        summary['identical_triplet_pct'] = (df['identical_triplet'].sum() / len(df)) * 100
        
        # Difference statistics
        summary['mean_abs_diff_overall'] = df['mean_abs_diff'].mean()
        summary['median_abs_diff_overall'] = df['mean_abs_diff'].median()
        summary['max_abs_diff_overall'] = df['max_abs_diff'].max()
        summary['std_abs_diff_overall'] = df['mean_abs_diff'].std()
        
        # By number of books
        summary['by_n_books'] = {}
        for n_books in sorted(df['n_books'].unique()):
            subset = df[df['n_books'] == n_books]
            summary['by_n_books'][int(n_books)] = {
                'count': len(subset),
                'identical_pct': (subset['identical_triplet'].sum() / len(subset)) * 100 if len(subset) > 0 else 0,
                'mean_abs_diff': subset['mean_abs_diff'].mean() if len(subset) > 0 else 0,
                'max_abs_diff': subset['max_abs_diff'].max() if len(subset) > 0 else 0
            }
        
        # By league
        summary['by_league'] = {}
        for league in sorted(df['league'].unique()):
            subset = df[df['league'] == league]
            summary['by_league'][league] = {
                'count': len(subset),
                'identical_pct': (subset['identical_triplet'].sum() / len(subset)) * 100 if len(subset) > 0 else 0,
                'mean_abs_diff': subset['mean_abs_diff'].mean() if len(subset) > 0 else 0,
                'max_abs_diff': subset['max_abs_diff'].max() if len(subset) > 0 else 0
            }
        
        # Sharp book split (if has_pinnacle column exists)
        if 'has_pinnacle' in df.columns:
            summary['by_sharp_book'] = {}
            for has_sharp in [0, 1]:
                subset = df[df['has_pinnacle'] == has_sharp]
                sharp_label = 'with_pinnacle' if has_sharp else 'without_pinnacle'
                summary['by_sharp_book'][sharp_label] = {
                    'count': len(subset),
                    'identical_pct': (subset['identical_triplet'].sum() / len(subset)) * 100 if len(subset) > 0 else 0,
                    'mean_abs_diff': subset['mean_abs_diff'].mean() if len(subset) > 0 else 0,
                    'max_abs_diff': subset['max_abs_diff'].max() if len(subset) > 0 else 0
                }
        
        # Multi-book analysis (where weighting should matter most)
        multi_book_subset = df[df['n_books'] >= 3]
        if len(multi_book_subset) > 0:
            summary['multi_book_analysis'] = {
                'count': len(multi_book_subset),
                'identical_pct': (multi_book_subset['identical_triplet'].sum() / len(multi_book_subset)) * 100,
                'mean_abs_diff': multi_book_subset['mean_abs_diff'].mean(),
                'should_show_differences': multi_book_subset['mean_abs_diff'].mean() > 0.001
            }
        
        return summary
    
    def create_visualizations(self, df: pd.DataFrame, timestamp: str):
        """Create diagnostic visualizations"""
        
        plt.style.use('default')
        
        # 1. Distribution of mean absolute differences
        plt.figure(figsize=(12, 8))
        
        plt.subplot(2, 2, 1)
        plt.hist(df['mean_abs_diff'], bins=50, alpha=0.7, edgecolor='black')
        plt.xlabel('Mean Absolute Difference')
        plt.ylabel('Frequency')
        plt.title('Distribution of Consensus Differences')
        plt.axvline(df['mean_abs_diff'].mean(), color='red', linestyle='--', label=f'Mean: {df["mean_abs_diff"].mean():.4f}')
        plt.legend()
        
        # 2. Number of books histogram
        plt.subplot(2, 2, 2)
        n_books_counts = df['n_books'].value_counts().sort_index()
        plt.bar(n_books_counts.index, n_books_counts.values, alpha=0.7, edgecolor='black')
        plt.xlabel('Number of Books')
        plt.ylabel('Frequency')
        plt.title('Distribution of Book Coverage')
        
        # 3. Differences by number of books
        plt.subplot(2, 2, 3)
        n_books_groups = df.groupby('n_books')['mean_abs_diff'].mean()
        plt.bar(n_books_groups.index, n_books_groups.values, alpha=0.7, edgecolor='black')
        plt.xlabel('Number of Books')
        plt.ylabel('Mean Absolute Difference')
        plt.title('Consensus Differences by Book Coverage')
        
        # 4. Sharp book comparison (if available)
        plt.subplot(2, 2, 4)
        if 'has_pinnacle' in df.columns:
            sharp_comparison = df.groupby('has_pinnacle')['mean_abs_diff'].mean()
            labels = ['Without Pinnacle', 'With Pinnacle']
            plt.bar(labels, sharp_comparison.values, alpha=0.7, edgecolor='black')
            plt.ylabel('Mean Absolute Difference')
            plt.title('Consensus Differences: Sharp Book Impact')
        else:
            plt.text(0.5, 0.5, 'Sharp book data\nnot available', ha='center', va='center', transform=plt.gca().transAxes)
            plt.title('Sharp Book Analysis (N/A)')
        
        plt.tight_layout()
        plt.savefig(os.path.join(self.outdir, f'consensus_analysis_{timestamp}.png'), dpi=150, bbox_inches='tight')
        plt.close()
        
        # 5. Detailed difference distribution by outcome
        plt.figure(figsize=(15, 5))
        
        outcomes = ['H', 'D', 'A']
        for i, outcome in enumerate(outcomes):
            plt.subplot(1, 3, i + 1)
            diff_col = f'diff_{outcome}'
            plt.hist(df[diff_col], bins=50, alpha=0.7, edgecolor='black')
            plt.xlabel(f'Absolute Difference ({outcome})')
            plt.ylabel('Frequency')
            plt.title(f'{outcome} Outcome Differences')
            plt.axvline(df[diff_col].mean(), color='red', linestyle='--', label=f'Mean: {df[diff_col].mean():.4f}')
            plt.legend()
        
        plt.tight_layout()
        plt.savefig(os.path.join(self.outdir, f'outcome_differences_{timestamp}.png'), dpi=150, bbox_inches='tight')
        plt.close()
    
    def run_qa_analysis(self, data_path: str = None) -> Dict:
        """Run complete consensus QA analysis"""
        
        print("CONSENSUS QA ANALYSIS")
        print("=" * 30)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # Load data
        df = self.load_or_generate_data(data_path)
        print(f"Loaded {len(df)} matches for analysis")
        
        # Compute differences
        df = self.compute_consensus_differences(df)
        
        # Generate summary statistics
        summary = self.generate_summary_statistics(df)
        
        # Create visualizations
        self.create_visualizations(df, timestamp)
        
        # Save detailed results
        df.to_csv(os.path.join(self.outdir, f'detailed_analysis_{timestamp}.csv'), index=False)
        
        # Save summary
        summary_df = pd.DataFrame([
            {'metric': 'total_matches', 'value': summary['total_matches']},
            {'metric': 'identical_triplet_pct', 'value': f"{summary['identical_triplet_pct']:.2f}%"},
            {'metric': 'mean_abs_diff', 'value': f"{summary['mean_abs_diff_overall']:.6f}"},
            {'metric': 'max_abs_diff', 'value': f"{summary['max_abs_diff_overall']:.6f}"}
        ])
        summary_df.to_csv(os.path.join(self.outdir, f'summary_{timestamp}.csv'), index=False)
        
        # Save by-league analysis
        league_data = []
        for league, stats in summary['by_league'].items():
            league_data.append({
                'league': league,
                'count': stats['count'],
                'identical_pct': f"{stats['identical_pct']:.2f}%",
                'mean_abs_diff': f"{stats['mean_abs_diff']:.6f}",
                'max_abs_diff': f"{stats['max_abs_diff']:.6f}"
            })
        
        league_df = pd.DataFrame(league_data)
        league_df.to_csv(os.path.join(self.outdir, f'by_league_{timestamp}.csv'), index=False)
        
        # Save sharp book split if available
        if 'by_sharp_book' in summary:
            sharp_data = []
            for sharp_status, stats in summary['by_sharp_book'].items():
                sharp_data.append({
                    'sharp_book_present': sharp_status,
                    'count': stats['count'],
                    'identical_pct': f"{stats['identical_pct']:.2f}%",
                    'mean_abs_diff': f"{stats['mean_abs_diff']:.6f}",
                    'max_abs_diff': f"{stats['max_abs_diff']:.6f}"
                })
            
            sharp_df = pd.DataFrame(sharp_data)
            sharp_df.to_csv(os.path.join(self.outdir, f'sharp_split_{timestamp}.csv'), index=False)
        
        # Print summary
        self.print_qa_summary(summary)
        
        print(f"\nFiles saved to {self.outdir}:")
        print(f"  • Summary: summary_{timestamp}.csv")
        print(f"  • By League: by_league_{timestamp}.csv")
        print(f"  • Detailed: detailed_analysis_{timestamp}.csv")
        print(f"  • Visualizations: consensus_analysis_{timestamp}.png")
        
        return summary
    
    def print_qa_summary(self, summary: Dict):
        """Print comprehensive QA summary"""
        
        print(f"\n🔍 CONSENSUS QA RESULTS:")
        print(f"   • Total Matches: {summary['total_matches']:,}")
        print(f"   • Identical Triplets: {summary['identical_triplet_pct']:.1f}%")
        print(f"   • Mean Absolute Difference: {summary['mean_abs_diff_overall']:.6f}")
        print(f"   • Max Absolute Difference: {summary['max_abs_diff_overall']:.6f}")
        
        print(f"\n📊 BY NUMBER OF BOOKS:")
        for n_books, stats in summary['by_n_books'].items():
            print(f"   • {n_books} books: {stats['identical_pct']:.1f}% identical, "
                  f"{stats['mean_abs_diff']:.6f} mean diff ({stats['count']} matches)")
        
        print(f"\n🏆 BY LEAGUE:")
        for league, stats in summary['by_league'].items():
            print(f"   • {league}: {stats['identical_pct']:.1f}% identical, "
                  f"{stats['mean_abs_diff']:.6f} mean diff ({stats['count']} matches)")
        
        if 'by_sharp_book' in summary:
            print(f"\n📈 SHARP BOOK IMPACT:")
            for sharp_status, stats in summary['by_sharp_book'].items():
                print(f"   • {sharp_status.replace('_', ' ')}: {stats['identical_pct']:.1f}% identical, "
                      f"{stats['mean_abs_diff']:.6f} mean diff ({stats['count']} matches)")
        
        if 'multi_book_analysis' in summary:
            multi_stats = summary['multi_book_analysis']
            print(f"\n🎯 MULTI-BOOK ANALYSIS (≥3 books):")
            print(f"   • Matches: {multi_stats['count']:,}")
            print(f"   • Identical: {multi_stats['identical_pct']:.1f}%")
            print(f"   • Mean Difference: {multi_stats['mean_abs_diff']:.6f}")
            print(f"   • Shows Differences: {'✅ Yes' if multi_stats['should_show_differences'] else '❌ No'}")
        
        # Diagnostic recommendations
        print(f"\n💡 DIAGNOSTIC ASSESSMENT:")
        
        if summary['identical_triplet_pct'] > 40:
            print(f"   ⚠️  HIGH IDENTICAL RATE ({summary['identical_triplet_pct']:.1f}%) - possible issues:")
            print(f"      • Weights not actually applied (median fallback?)")
            print(f"      • Coverage forcing equal-weight fallback")
            print(f"      • Weight differences too small to matter")
        elif summary['identical_triplet_pct'] > 20:
            print(f"   📊 MODERATE IDENTICAL RATE ({summary['identical_triplet_pct']:.1f}%) - acceptable but check:")
            print(f"      • Coverage patterns and sharp book availability")
        else:
            print(f"   ✅ LOW IDENTICAL RATE ({summary['identical_triplet_pct']:.1f}%) - weights likely working")
        
        if summary['mean_abs_diff_overall'] < 0.001:
            print(f"   ⚠️  VERY SMALL DIFFERENCES ({summary['mean_abs_diff_overall']:.6f}) - may not impact performance")
        elif summary['mean_abs_diff_overall'] < 0.005:
            print(f"   📊 SMALL BUT MEANINGFUL DIFFERENCES ({summary['mean_abs_diff_overall']:.6f}) - should help slightly")
        else:
            print(f"   ✅ SUBSTANTIAL DIFFERENCES ({summary['mean_abs_diff_overall']:.6f}) - should improve performance")

def main():
    parser = argparse.ArgumentParser(description='Consensus QA Analysis')
    parser.add_argument('--data', type=str, help='Path to consensus data CSV')
    parser.add_argument('--outdir', type=str, default='./consensus_qa_artifacts', help='Output directory')
    
    args = parser.parse_args()
    
    qa = ConsensusQA(outdir=args.outdir)
    results = qa.run_qa_analysis(args.data)
    
    return results

if __name__ == "__main__":
    main()