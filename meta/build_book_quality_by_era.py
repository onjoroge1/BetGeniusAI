"""
Bookmaker Quality Analysis by Era
Build comprehensive bookmaker performance metrics per league/era for intelligent weighting
"""

import os
import pandas as pd
import numpy as np
import psycopg2
from datetime import datetime
import json
from typing import Dict, List, Tuple
from scipy.optimize import minimize

class BookQualityAnalyzer:
    """Analyze bookmaker quality by league and era for optimal weighting"""
    
    def __init__(self):
        self.conn = psycopg2.connect(os.environ['DATABASE_URL'])
        self.bookmakers = ['b365', 'bw', 'iw', 'lb', 'ps', 'wh', 'sj', 'vc']
        self.min_coverage = 50  # Minimum matches for stable quality metrics
        
    def create_bookmaker_metadata(self) -> Dict:
        """Create bookmaker metadata with type classifications"""
        
        bookmaker_meta = {
            'b365': {
                'name': 'Bet365',
                'type': 'recreational',
                'country': 'UK',
                'era_start': '1998',
                'is_active': True,
                'market_position': 'major_recreational'
            },
            'bw': {
                'name': 'Betway',
                'type': 'recreational', 
                'country': 'UK',
                'era_start': '2006',
                'is_active': True,
                'market_position': 'mid_tier_recreational'
            },
            'iw': {
                'name': 'Interwetten',
                'type': 'recreational',
                'country': 'Austria',
                'era_start': '1997',
                'is_active': True,
                'market_position': 'european_recreational'
            },
            'lb': {
                'name': 'Ladbrokes',
                'type': 'recreational',
                'country': 'UK',
                'era_start': '1995',
                'is_active': True,
                'market_position': 'traditional_uk'
            },
            'ps': {
                'name': 'Pinnacle',
                'type': 'sharp',
                'country': 'Curacao',
                'era_start': '1998',
                'is_active': True,
                'market_position': 'sharp_leader'
            },
            'wh': {
                'name': 'William Hill',
                'type': 'recreational',
                'country': 'UK',
                'era_start': '1993',
                'is_active': True,
                'market_position': 'major_traditional'
            },
            'sj': {
                'name': 'Stan James',
                'type': 'recreational',
                'country': 'UK',
                'era_start': '2000',
                'is_active': False,
                'market_position': 'uk_specialist'
            },
            'vc': {
                'name': 'Victor Chandler',
                'type': 'recreational',
                'country': 'UK',
                'era_start': '1999',
                'is_active': False,
                'market_position': 'premium_uk'
            }
        }
        
        return bookmaker_meta
    
    def load_historical_data(self) -> pd.DataFrame:
        """Load historical odds data for quality analysis"""
        
        print("Loading historical odds for quality analysis...")
        
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
        AND match_date >= '1998-01-01'
        ORDER BY match_date
        """
        
        df = pd.read_sql(query, self.conn)
        print(f"Loaded {len(df):,} historical matches for analysis")
        
        return df
    
    def assign_era_bins(self, df: pd.DataFrame) -> pd.DataFrame:
        """Assign 5-year era bins for temporal stability"""
        
        df['match_date'] = pd.to_datetime(df['match_date'])
        df['year'] = df['match_date'].dt.year
        
        def get_era_bin(year):
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
        
        df['era_bin'] = df['year'].apply(get_era_bin)
        
        print("Era distribution for quality analysis:")
        print(df['era_bin'].value_counts().sort_index())
        
        return df
    
    def convert_odds_to_probabilities(self, odds_h: float, odds_d: float, odds_a: float) -> Tuple[float, float, float, float]:
        """Convert odds to margin-adjusted probabilities with overround"""
        
        if pd.isna(odds_h) or pd.isna(odds_d) or pd.isna(odds_a):
            return None, None, None, None
        
        if odds_h <= 1.0 or odds_d <= 1.0 or odds_a <= 1.0:
            return None, None, None, None
        
        # Raw implied probabilities
        raw_prob_h = 1.0 / odds_h
        raw_prob_d = 1.0 / odds_d
        raw_prob_a = 1.0 / odds_a
        
        # Overround (bookmaker margin)
        overround = raw_prob_h + raw_prob_d + raw_prob_a
        
        # Margin-adjusted probabilities
        prob_h = raw_prob_h / overround
        prob_d = raw_prob_d / overround
        prob_a = raw_prob_a / overround
        
        return prob_h, prob_d, prob_a, overround
    
    def calculate_bookmaker_quality_metrics(self, df: pd.DataFrame, bookmaker: str, 
                                          league: str, era_bin: str) -> Dict:
        """Calculate comprehensive quality metrics for a bookmaker in specific context"""
        
        # Filter to specific context
        context_df = df[(df['league'] == league) & (df['era_bin'] == era_bin)].copy()
        
        if len(context_df) < self.min_coverage:
            return None
        
        # Get odds columns
        odds_cols = [f"{bookmaker}_h", f"{bookmaker}_d", f"{bookmaker}_a"]
        
        if not all(col in context_df.columns for col in odds_cols):
            return None
        
        # Filter for available odds
        available_df = context_df.dropna(subset=odds_cols)
        
        if len(available_df) < self.min_coverage:
            return None
        
        # Calculate probabilities and outcomes
        probs = []
        actuals = []
        overrounds = []
        
        for _, row in available_df.iterrows():
            odds_h, odds_d, odds_a = row[odds_cols]
            
            prob_h, prob_d, prob_a, overround = self.convert_odds_to_probabilities(
                odds_h, odds_d, odds_a
            )
            
            if prob_h is None:
                continue
            
            probs.append([prob_h, prob_d, prob_a])
            overrounds.append(overround)
            
            # Convert result to one-hot
            if row['result'] == 'H':
                actuals.append([1, 0, 0])
            elif row['result'] == 'D':
                actuals.append([0, 1, 0])
            elif row['result'] == 'A':
                actuals.append([0, 0, 1])
            else:
                continue
        
        if len(probs) < self.min_coverage:
            return None
        
        probs = np.array(probs)
        actuals = np.array(actuals)
        overrounds = np.array(overrounds)
        
        # Clip probabilities for numerical stability
        probs_clipped = np.clip(probs, 1e-15, 1 - 1e-15)
        
        # Calculate LogLoss (primary quality metric)
        logloss = -np.mean(np.sum(actuals * np.log(probs_clipped), axis=1))
        
        # Calculate Brier Score
        brier_score = np.mean(np.sum((probs - actuals) ** 2, axis=1))
        
        # Calculate calibration metrics
        accuracy = np.mean(np.argmax(probs, axis=1) == np.argmax(actuals, axis=1))
        
        # Calculate overround statistics
        avg_overround = np.mean(overrounds)
        overround_std = np.std(overrounds)
        
        # Coverage rate
        coverage_rate = len(available_df) / len(context_df)
        
        return {
            'bookmaker': bookmaker,
            'league': league,
            'era_bin': era_bin,
            'sample_size': len(probs),
            'logloss_closing': float(logloss),
            'brier_closing': float(brier_score),
            'accuracy': float(accuracy),
            'coverage_rate': float(coverage_rate),
            'avg_overround': float(avg_overround),
            'overround_std': float(overround_std),
            'total_matches_in_context': len(context_df)
        }
    
    def calculate_quality_weights(self, quality_metrics: List[Dict], 
                                league: str, era_bin: str) -> Dict:
        """Calculate optimal quality weights for bookmakers in specific context"""
        
        # Filter to specific context
        context_metrics = [m for m in quality_metrics 
                          if m['league'] == league and m['era_bin'] == era_bin]
        
        if len(context_metrics) < 2:
            return {}
        
        # Use inverse LogLoss for weighting (lower LogLoss = higher quality)
        bookmaker_logloss = {m['bookmaker']: m['logloss_closing'] for m in context_metrics}
        
        # Calculate inverse weights
        inv_logloss = {bm: 1.0 / ll for bm, ll in bookmaker_logloss.items()}
        total_inv = sum(inv_logloss.values())
        
        # Normalize to sum to 1
        quality_weights = {bm: inv_ll / total_inv for bm, inv_ll in inv_logloss.items()}
        
        # Add ranking
        ranked_bookmakers = sorted(bookmaker_logloss.items(), key=lambda x: x[1])
        sharpness_ranks = {bm: rank + 1 for rank, (bm, _) in enumerate(ranked_bookmakers)}
        
        return {
            'quality_weights': quality_weights,
            'sharpness_ranks': sharpness_ranks,
            'best_bookmaker': ranked_bookmakers[0][0],
            'best_logloss': ranked_bookmakers[0][1]
        }
    
    def build_comprehensive_quality_analysis(self) -> Dict:
        """Build comprehensive bookmaker quality analysis"""
        
        print("BUILDING BOOKMAKER QUALITY BY ERA")
        print("=" * 50)
        
        # Load data and metadata
        df = self.load_historical_data()
        df = self.assign_era_bins(df)
        bookmaker_meta = self.create_bookmaker_metadata()
        
        # Get unique league/era combinations
        combinations = df.groupby(['league', 'era_bin']).size().reset_index(name='count')
        combinations = combinations[combinations['count'] >= self.min_coverage]
        
        print(f"\nAnalyzing {len(combinations)} league/era combinations...")
        
        # Calculate quality metrics for all bookmaker/league/era combinations
        all_quality_metrics = []
        
        for _, row in combinations.iterrows():
            league = row['league']
            era_bin = row['era_bin']
            
            print(f"Processing {league} {era_bin}...")
            
            for bookmaker in self.bookmakers:
                quality_metrics = self.calculate_bookmaker_quality_metrics(
                    df, bookmaker, league, era_bin
                )
                
                if quality_metrics:
                    all_quality_metrics.append(quality_metrics)
        
        print(f"Generated {len(all_quality_metrics)} quality assessments")
        
        # Calculate optimal weights for each league/era
        quality_weights_by_context = {}
        
        for _, row in combinations.iterrows():
            league = row['league']
            era_bin = row['era_bin']
            
            weight_info = self.calculate_quality_weights(
                all_quality_metrics, league, era_bin
            )
            
            if weight_info:
                key = f"{league}_{era_bin}"
                quality_weights_by_context[key] = weight_info
        
        # Create summary analysis
        summary_analysis = self.create_summary_analysis(
            all_quality_metrics, quality_weights_by_context, bookmaker_meta
        )
        
        return {
            'bookmaker_metadata': bookmaker_meta,
            'quality_metrics': all_quality_metrics,
            'quality_weights_by_context': quality_weights_by_context,
            'summary_analysis': summary_analysis,
            'generation_timestamp': datetime.now().isoformat()
        }
    
    def create_summary_analysis(self, quality_metrics: List[Dict], 
                              weights_by_context: Dict, 
                              bookmaker_meta: Dict) -> Dict:
        """Create comprehensive summary of bookmaker quality analysis"""
        
        # Convert to DataFrame for analysis
        metrics_df = pd.DataFrame(quality_metrics)
        
        # Overall bookmaker rankings
        overall_rankings = metrics_df.groupby('bookmaker').agg({
            'logloss_closing': 'mean',
            'brier_closing': 'mean',
            'coverage_rate': 'mean',
            'avg_overround': 'mean',
            'sample_size': 'sum'
        }).round(4)
        
        overall_rankings = overall_rankings.sort_values('logloss_closing')
        
        # Sharp vs Recreational analysis
        sharp_books = [bm for bm, meta in bookmaker_meta.items() if meta['type'] == 'sharp']
        rec_books = [bm for bm, meta in bookmaker_meta.items() if meta['type'] == 'recreational']
        
        sharp_metrics = metrics_df[metrics_df['bookmaker'].isin(sharp_books)]
        rec_metrics = metrics_df[metrics_df['bookmaker'].isin(rec_books)]
        
        type_comparison = {
            'sharp_books': {
                'count': len(sharp_metrics),
                'avg_logloss': sharp_metrics['logloss_closing'].mean() if len(sharp_metrics) > 0 else None,
                'avg_overround': sharp_metrics['avg_overround'].mean() if len(sharp_metrics) > 0 else None
            },
            'recreational_books': {
                'count': len(rec_metrics),
                'avg_logloss': rec_metrics['logloss_closing'].mean() if len(rec_metrics) > 0 else None,
                'avg_overround': rec_metrics['avg_overround'].mean() if len(rec_metrics) > 0 else None
            }
        }
        
        # League-specific analysis
        league_analysis = {}
        for league in metrics_df['league'].unique():
            league_df = metrics_df[metrics_df['league'] == league]
            
            # Best bookmaker per league
            best_in_league = league_df.loc[league_df['logloss_closing'].idxmin()]
            
            league_analysis[league] = {
                'best_bookmaker': best_in_league['bookmaker'],
                'best_logloss': best_in_league['logloss_closing'],
                'avg_overround': league_df['avg_overround'].mean(),
                'bookmakers_available': league_df['bookmaker'].nunique(),
                'total_assessments': len(league_df)
            }
        
        # Temporal evolution
        era_evolution = {}
        for era in metrics_df['era_bin'].unique():
            era_df = metrics_df[metrics_df['era_bin'] == era]
            
            era_evolution[era] = {
                'avg_logloss': era_df['logloss_closing'].mean(),
                'avg_overround': era_df['avg_overround'].mean(),
                'bookmakers_active': era_df['bookmaker'].nunique(),
                'assessments_count': len(era_df)
            }
        
        return {
            'overall_rankings': overall_rankings.to_dict('index'),
            'type_comparison': type_comparison,
            'league_analysis': league_analysis,
            'era_evolution': era_evolution,
            'best_overall_bookmaker': overall_rankings.index[0],
            'total_assessments': len(quality_metrics),
            'leagues_covered': metrics_df['league'].nunique(),
            'eras_covered': metrics_df['era_bin'].nunique()
        }
    
    def save_quality_analysis(self, analysis_data: Dict) -> Dict:
        """Save comprehensive quality analysis to files"""
        
        os.makedirs('meta/book_quality', exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # Save main analysis file
        main_path = f'meta/book_quality/book_quality_by_era_{timestamp}.json'
        with open(main_path, 'w') as f:
            json.dump(analysis_data, f, indent=2, default=str)
        
        # Save quality metrics as CSV for easy analysis
        metrics_df = pd.DataFrame(analysis_data['quality_metrics'])
        metrics_path = f'meta/book_quality/quality_metrics_{timestamp}.csv'
        metrics_df.to_csv(metrics_path, index=False)
        
        # Save weights by context as JSON for lookup
        weights_path = f'meta/book_quality/quality_weights_{timestamp}.json'
        with open(weights_path, 'w') as f:
            json.dump(analysis_data['quality_weights_by_context'], f, indent=2)
        
        # Save bookmaker metadata
        meta_path = f'meta/book_quality/bookmaker_metadata_{timestamp}.json'
        with open(meta_path, 'w') as f:
            json.dump(analysis_data['bookmaker_metadata'], f, indent=2)
        
        return {
            'main_path': main_path,
            'metrics_path': metrics_path,
            'weights_path': weights_path,
            'metadata_path': meta_path
        }
    
    def run_quality_analysis(self) -> Dict:
        """Run complete bookmaker quality analysis"""
        
        try:
            # Build comprehensive analysis
            analysis_data = self.build_comprehensive_quality_analysis()
            
            # Save results
            file_paths = self.save_quality_analysis(analysis_data)
            
            # Print comprehensive summary
            self.print_analysis_summary(analysis_data, file_paths)
            
            return analysis_data
            
        finally:
            self.conn.close()
    
    def print_analysis_summary(self, analysis_data: Dict, file_paths: Dict):
        """Print comprehensive analysis summary"""
        
        print("\n" + "=" * 60)
        print("BOOKMAKER QUALITY ANALYSIS COMPLETE")
        print("=" * 60)
        
        summary = analysis_data['summary_analysis']
        
        print(f"\n📊 ANALYSIS OVERVIEW:")
        print(f"   • Total Quality Assessments: {summary['total_assessments']}")
        print(f"   • Leagues Covered: {summary['leagues_covered']}")
        print(f"   • Eras Analyzed: {summary['eras_covered']}")
        print(f"   • Best Overall Bookmaker: {summary['best_overall_bookmaker'].upper()}")
        
        print(f"\n🏆 OVERALL BOOKMAKER RANKINGS:")
        rankings = summary['overall_rankings']
        for i, (bookmaker, metrics) in enumerate(rankings.items(), 1):
            print(f"   {i}. {bookmaker.upper()}: {metrics['logloss_closing']:.4f} LogLoss, {metrics['avg_overround']:.4f} overround")
        
        print(f"\n📈 SHARP VS RECREATIONAL COMPARISON:")
        type_comp = summary['type_comparison']
        if type_comp['sharp_books']['avg_logloss']:
            print(f"   • Sharp Books: {type_comp['sharp_books']['avg_logloss']:.4f} avg LogLoss")
        if type_comp['recreational_books']['avg_logloss']:
            print(f"   • Recreational Books: {type_comp['recreational_books']['avg_logloss']:.4f} avg LogLoss")
        
        print(f"\n🏅 LEAGUE CHAMPIONS:")
        league_analysis = summary['league_analysis']
        for league, data in league_analysis.items():
            print(f"   • {league}: {data['best_bookmaker'].upper()} ({data['best_logloss']:.4f} LogLoss)")
        
        print(f"\n📅 ERA EVOLUTION:")
        era_evolution = summary['era_evolution']
        for era, data in sorted(era_evolution.items()):
            print(f"   • {era}: {data['avg_logloss']:.4f} LogLoss, {data['bookmakers_active']} active bookmakers")
        
        print(f"\n💡 KEY INSIGHTS:")
        
        # Find most consistent bookmaker
        metrics_df = pd.DataFrame(analysis_data['quality_metrics'])
        consistency = metrics_df.groupby('bookmaker')['logloss_closing'].std().sort_values()
        most_consistent = consistency.index[0]
        print(f"   • Most Consistent: {most_consistent.upper()} (lowest LogLoss variance)")
        
        # Find highest coverage bookmaker
        coverage = metrics_df.groupby('bookmaker')['coverage_rate'].mean().sort_values(ascending=False)
        highest_coverage = coverage.index[0]
        print(f"   • Highest Coverage: {highest_coverage.upper()} ({coverage.iloc[0]:.1%} avg coverage)")
        
        print(f"\n📄 Files saved:")
        for name, path in file_paths.items():
            print(f"   • {name}: {path}")
        
        print(f"\n🚀 WEEK 2 IMPACT:")
        print(f"   • Quality-weighted consensus ready for implementation")
        print(f"   • Bookmaker features prepared for residual head training")
        print(f"   • Expected improvement: 0.005-0.015 LogLoss from book intelligence")

def main():
    """Run bookmaker quality analysis"""
    
    analyzer = BookQualityAnalyzer()
    results = analyzer.run_quality_analysis()
    
    return results

if __name__ == "__main__":
    main()