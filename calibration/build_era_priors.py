"""
Era and Season Priors Builder
Extract league-specific priors by era and implement season-phase shrinkage
"""

import os
import pandas as pd
import numpy as np
import psycopg2
import json
from datetime import datetime
from typing import Dict, List, Tuple

class EraPriorsBuilder:
    """Build era-specific priors and season-phase calibration"""
    
    def __init__(self):
        self.conn = psycopg2.connect(os.environ['DATABASE_URL'])
        self.min_sample_size = 100  # Minimum matches for stable priors
    
    def load_historical_data(self) -> pd.DataFrame:
        """Load historical match results"""
        
        print("Loading historical match data for prior extraction...")
        
        query = """
        SELECT 
            match_date, season, league, home_team, away_team, result,
            home_goals, away_goals
        FROM historical_odds
        WHERE result IS NOT NULL
        AND home_goals IS NOT NULL 
        AND away_goals IS NOT NULL
        ORDER BY match_date
        """
        
        df = pd.read_sql(query, self.conn)
        print(f"Loaded {len(df):,} historical matches")
        
        return df
    
    def create_era_bins(self, df: pd.DataFrame) -> pd.DataFrame:
        """Create era bins for temporal analysis"""
        
        df['match_date'] = pd.to_datetime(df['match_date'])
        df['year'] = df['match_date'].dt.year
        
        # Create 5-year era bins
        def assign_era(year):
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
        
        df['era'] = df['year'].apply(assign_era)
        
        print("Era distribution:")
        print(df['era'].value_counts().sort_index())
        
        return df
    
    def add_season_phase(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add season phase information"""
        
        df['match_date'] = pd.to_datetime(df['match_date'])
        df['month'] = df['match_date'].dt.month
        
        def assign_season_phase(month):
            if month in [8, 9, 10]:  # August-October
                return 'early'
            elif month in [11, 12, 1, 2]:  # November-February
                return 'mid'
            else:  # March-May
                return 'late'
        
        df['season_phase'] = df['month'].apply(assign_season_phase)
        
        return df
    
    def calculate_outcome_rates(self, df: pd.DataFrame, league: str, era: str) -> Dict:
        """Calculate home/draw/away rates for a league/era"""
        
        subset = df[(df['league'] == league) & (df['era'] == era)]
        
        if len(subset) < self.min_sample_size:
            return None
        
        # Calculate outcome rates
        total_matches = len(subset)
        home_wins = len(subset[subset['result'] == 'H'])
        draws = len(subset[subset['result'] == 'D'])
        away_wins = len(subset[subset['result'] == 'A'])
        
        home_rate = home_wins / total_matches
        draw_rate = draws / total_matches
        away_rate = away_wins / total_matches
        
        # Calculate home advantage
        home_advantage = home_rate - away_rate
        
        # Calculate average goals
        avg_home_goals = subset['home_goals'].mean()
        avg_away_goals = subset['away_goals'].mean()
        avg_total_goals = avg_home_goals + avg_away_goals
        
        return {
            'league': league,
            'era': era,
            'sample_size': total_matches,
            'home_rate': home_rate,
            'draw_rate': draw_rate,
            'away_rate': away_rate,
            'home_advantage': home_advantage,
            'avg_home_goals': avg_home_goals,
            'avg_away_goals': avg_away_goals,
            'avg_total_goals': avg_total_goals
        }
    
    def calculate_season_phase_priors(self, df: pd.DataFrame, league: str, era: str) -> Dict:
        """Calculate priors by season phase within league/era"""
        
        subset = df[(df['league'] == league) & (df['era'] == era)]
        
        if len(subset) < self.min_sample_size:
            return None
        
        phase_priors = {}
        
        for phase in ['early', 'mid', 'late']:
            phase_subset = subset[subset['season_phase'] == phase]
            
            if len(phase_subset) >= 20:  # Minimum for phase-specific prior
                total = len(phase_subset)
                home_rate = len(phase_subset[phase_subset['result'] == 'H']) / total
                draw_rate = len(phase_subset[phase_subset['result'] == 'D']) / total
                away_rate = len(phase_subset[phase_subset['result'] == 'A']) / total
                
                phase_priors[phase] = {
                    'sample_size': total,
                    'home_rate': home_rate,
                    'draw_rate': draw_rate,
                    'away_rate': away_rate,
                    'avg_home_goals': phase_subset['home_goals'].mean(),
                    'avg_away_goals': phase_subset['away_goals'].mean(),
                    'avg_total_goals': phase_subset['home_goals'].mean() + phase_subset['away_goals'].mean()
                }
        
        return phase_priors
    
    def build_shrinkage_parameters(self, df: pd.DataFrame) -> Dict:
        """Build parameters for early season shrinkage"""
        
        print("Building shrinkage parameters...")
        
        # Analyze how outcome rates stabilize over the season
        df = df.copy()
        df['match_date'] = pd.to_datetime(df['match_date'])
        
        # Group by season and calculate cumulative rates
        shrinkage_analysis = {}
        
        for league in df['league'].unique():
            league_df = df[df['league'] == league]
            
            if len(league_df) < 500:  # Need sufficient data
                continue
            
            # Calculate how home advantage stabilizes
            season_evolution = []
            
            for season in league_df['season'].unique():
                season_df = league_df[league_df['season'] == season].sort_values('match_date')
                
                if len(season_df) < 20:
                    continue
                
                # Calculate cumulative home advantage over season
                cumulative_home_advantage = []
                
                for i in range(10, len(season_df), 5):  # Every 5 matches after first 10
                    subset = season_df.iloc[:i]
                    home_rate = len(subset[subset['result'] == 'H']) / len(subset)
                    away_rate = len(subset[subset['result'] == 'A']) / len(subset)
                    home_adv = home_rate - away_rate
                    
                    cumulative_home_advantage.append({
                        'matches_played': i,
                        'home_advantage': home_adv,
                        'sample_size': len(subset)
                    })
                
                if cumulative_home_advantage:
                    season_evolution.extend(cumulative_home_advantage)
            
            if season_evolution:
                evolution_df = pd.DataFrame(season_evolution)
                
                # Find stabilization point (where variance reduces significantly)
                stability_analysis = evolution_df.groupby('matches_played').agg({
                    'home_advantage': ['mean', 'std'],
                    'sample_size': 'mean'
                }).round(4)
                
                shrinkage_analysis[league] = {
                    'evolution': evolution_df.to_dict('records'),
                    'stability_analysis': stability_analysis.to_dict(),
                    'recommended_shrinkage_matches': 15  # Conservative default
                }
        
        return shrinkage_analysis
    
    def extract_all_priors(self) -> Dict:
        """Extract all era and season priors"""
        
        print("EXTRACTING ERA AND SEASON PRIORS")
        print("=" * 50)
        
        # Load and prepare data
        df = self.load_historical_data()
        df = self.create_era_bins(df)
        df = self.add_season_phase(df)
        
        # Get unique league/era combinations
        combinations = df.groupby(['league', 'era']).size().reset_index(name='count')
        combinations = combinations[combinations['count'] >= self.min_sample_size]
        
        print(f"\nExtracting priors for {len(combinations)} league/era combinations...")
        
        # Extract era priors
        era_priors = {}
        season_phase_priors = {}
        
        for _, row in combinations.iterrows():
            league = row['league']
            era = row['era']
            
            # Calculate base era priors
            era_prior = self.calculate_outcome_rates(df, league, era)
            if era_prior:
                key = f"{league}_{era}"
                era_priors[key] = era_prior
            
            # Calculate season phase priors
            phase_priors = self.calculate_season_phase_priors(df, league, era)
            if phase_priors:
                season_phase_priors[key] = phase_priors
        
        # Build shrinkage parameters
        shrinkage_params = self.build_shrinkage_parameters(df)
        
        # Create summary statistics
        summary_stats = self.create_summary_statistics(era_priors, season_phase_priors)
        
        return {
            'era_priors': era_priors,
            'season_phase_priors': season_phase_priors,
            'shrinkage_parameters': shrinkage_params,
            'summary_statistics': summary_stats,
            'metadata': {
                'total_matches': len(df),
                'leagues_analyzed': df['league'].nunique(),
                'eras_covered': df['era'].nunique(),
                'extraction_timestamp': datetime.now().isoformat(),
                'min_sample_size': self.min_sample_size
            }
        }
    
    def create_summary_statistics(self, era_priors: Dict, season_phase_priors: Dict) -> Dict:
        """Create summary statistics for extracted priors"""
        
        # Convert to DataFrame for analysis
        era_df = pd.DataFrame([prior for prior in era_priors.values()])
        
        if len(era_df) == 0:
            return {}
        
        # Overall statistics
        overall_stats = {
            'avg_home_rate': era_df['home_rate'].mean(),
            'avg_draw_rate': era_df['draw_rate'].mean(),
            'avg_away_rate': era_df['away_rate'].mean(),
            'avg_home_advantage': era_df['home_advantage'].mean(),
            'avg_total_goals': era_df['avg_total_goals'].mean(),
            'home_rate_std': era_df['home_rate'].std(),
            'draw_rate_std': era_df['draw_rate'].std(),
            'home_advantage_std': era_df['home_advantage'].std()
        }
        
        # League-specific analysis
        league_stats = {}
        for league in era_df['league'].unique():
            league_subset = era_df[era_df['league'] == league]
            
            league_stats[league] = {
                'sample_size': league_subset['sample_size'].sum(),
                'eras_covered': len(league_subset),
                'avg_home_rate': league_subset['home_rate'].mean(),
                'avg_draw_rate': league_subset['draw_rate'].mean(),
                'avg_home_advantage': league_subset['home_advantage'].mean(),
                'home_advantage_evolution': league_subset.sort_values('era')[['era', 'home_advantage']].to_dict('records')
            }
        
        # Era evolution analysis
        era_evolution = {}
        for era in era_df['era'].unique():
            era_subset = era_df[era_df['era'] == era]
            
            era_evolution[era] = {
                'leagues_covered': len(era_subset),
                'avg_home_rate': era_subset['home_rate'].mean(),
                'avg_draw_rate': era_subset['draw_rate'].mean(),
                'avg_home_advantage': era_subset['home_advantage'].mean(),
                'avg_total_goals': era_subset['avg_total_goals'].mean()
            }
        
        return {
            'overall': overall_stats,
            'by_league': league_stats,
            'by_era': era_evolution
        }
    
    def save_priors(self, priors_data: Dict) -> Dict:
        """Save extracted priors to files"""
        
        os.makedirs('calibration/priors', exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # Save complete priors data
        main_path = f'calibration/priors/era_priors_{timestamp}.json'
        with open(main_path, 'w') as f:
            json.dump(priors_data, f, indent=2, default=str)
        
        # Save individual prior files for easy lookup
        for key, prior in priors_data['era_priors'].items():
            league = prior['league']
            era = prior['era'].replace('-', '_')
            
            prior_file = f'calibration/priors/PRIOR_{league}_{era}.json'
            with open(prior_file, 'w') as f:
                json.dump(prior, f, indent=2, default=str)
        
        # Save summary CSV
        if priors_data['era_priors']:
            era_df = pd.DataFrame([prior for prior in priors_data['era_priors'].values()])
            summary_path = f'calibration/priors/priors_summary_{timestamp}.csv'
            era_df.to_csv(summary_path, index=False)
        
        return {
            'main_path': main_path,
            'summary_path': summary_path if 'summary_path' in locals() else None
        }
    
    def run_prior_extraction(self) -> Dict:
        """Run complete prior extraction process"""
        
        try:
            # Extract priors
            priors_data = self.extract_all_priors()
            
            # Save results
            file_paths = self.save_priors(priors_data)
            
            # Print comprehensive summary
            print("\n" + "=" * 60)
            print("ERA AND SEASON PRIORS EXTRACTION COMPLETE")
            print("=" * 60)
            
            metadata = priors_data['metadata']
            summary = priors_data['summary_statistics']
            
            print(f"\n📊 EXTRACTION SUMMARY:")
            print(f"   • Total Matches Analyzed: {metadata['total_matches']:,}")
            print(f"   • Leagues Covered: {metadata['leagues_analyzed']}")
            print(f"   • Eras Analyzed: {metadata['eras_covered']}")
            print(f"   • Prior Combinations: {len(priors_data['era_priors'])}")
            
            if 'overall' in summary:
                overall = summary['overall']
                print(f"\n🏈 OVERALL FOOTBALL PATTERNS:")
                print(f"   • Average Home Win Rate: {overall['avg_home_rate']:.3f}")
                print(f"   • Average Draw Rate: {overall['avg_draw_rate']:.3f}")
                print(f"   • Average Away Win Rate: {overall['avg_away_rate']:.3f}")
                print(f"   • Average Home Advantage: {overall['avg_home_advantage']:.3f}")
                print(f"   • Average Goals per Game: {overall['avg_total_goals']:.2f}")
            
            if 'by_league' in summary:
                print(f"\n🏆 LEAGUE-SPECIFIC PATTERNS:")
                for league, stats in summary['by_league'].items():
                    print(f"   • {league}: {stats['avg_home_advantage']:.3f} home advantage ({stats['sample_size']:,} matches)")
            
            if 'by_era' in summary:
                print(f"\n📈 ERA EVOLUTION:")
                for era, stats in sorted(summary['by_era'].items()):
                    print(f"   • {era}: {stats['avg_home_advantage']:.3f} home adv, {stats['avg_total_goals']:.2f} goals/game")
            
            print(f"\n🔧 SHRINKAGE PARAMETERS:")
            shrinkage = priors_data['shrinkage_parameters']
            print(f"   • Leagues with shrinkage analysis: {len(shrinkage)}")
            if shrinkage:
                avg_shrinkage = np.mean([data['recommended_shrinkage_matches'] for data in shrinkage.values()])
                print(f"   • Average recommended shrinkage: {avg_shrinkage:.0f} matches")
            
            print(f"\n📄 Files saved:")
            print(f"   • Main priors: {file_paths['main_path']}")
            if file_paths['summary_path']:
                print(f"   • Summary CSV: {file_paths['summary_path']}")
            
            return priors_data
            
        finally:
            self.conn.close()

def main():
    """Run era priors extraction"""
    
    builder = EraPriorsBuilder()
    results = builder.run_prior_extraction()
    
    return results

if __name__ == "__main__":
    main()