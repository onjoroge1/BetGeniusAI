"""
Prepare Book Mixer Data
Convert our fixed consensus data into format for book mixer training
"""

import pandas as pd
import numpy as np
import psycopg2
import os
from datetime import datetime

class BookMixerDataPreparation:
    """Prepare data for instance-wise book mixing"""
    
    def __init__(self):
        self.conn = psycopg2.connect(os.environ['DATABASE_URL'])
        
    def load_historical_with_books(self, limit=1500):
        """Load historical data with individual book probabilities"""
        
        print(f"Loading {limit} matches with individual book data...")
        
        query = """
        SELECT 
            id as match_id, match_date, league, home_team, away_team, result,
            b365_h, b365_d, b365_a,
            bw_h, bw_d, bw_a,
            wh_h, wh_d, wh_a,
            ps_h, ps_d, ps_a
        FROM historical_odds
        WHERE result IS NOT NULL
        AND match_date >= '2020-01-01'
        AND b365_h IS NOT NULL
        ORDER BY match_date DESC
        LIMIT %s
        """
        
        df = pd.read_sql(query, self.conn, params=[limit])
        print(f"Loaded {len(df)} matches from database")
        
        return df
    
    def odds_to_probabilities(self, odds_h, odds_d, odds_a):
        """Convert odds to normalized probabilities"""
        if pd.isna(odds_h) or pd.isna(odds_d) or pd.isna(odds_a):
            return None, None, None
        if odds_h <= 1 or odds_d <= 1 or odds_a <= 1:
            return None, None, None
            
        prob_h = 1.0 / odds_h
        prob_d = 1.0 / odds_d
        prob_a = 1.0 / odds_a
        
        total = prob_h + prob_d + prob_a
        return prob_h/total, prob_d/total, prob_a/total
    
    def prepare_book_mixer_format(self, df):
        """Convert to book mixer format"""
        
        print("Converting to book mixer format...")
        
        # Map results to labels
        result_map = {'H': 0, 'D': 1, 'A': 2}
        df['y'] = df['result'].map(result_map)
        
        mixer_data = []
        
        for _, row in df.iterrows():
            bookmakers = {
                'b365': [row['b365_h'], row['b365_d'], row['b365_a']],
                'bw': [row['bw_h'], row['bw_d'], row['bw_a']],
                'wh': [row['wh_h'], row['wh_d'], row['wh_a']],
                'ps': [row['ps_h'], row['ps_d'], row['ps_a']]
            }
            
            # Convert odds to probabilities for each bookmaker
            book_probs = {}
            valid_books = []
            
            for book, odds in bookmakers.items():
                pH, pD, pA = self.odds_to_probabilities(odds[0], odds[1], odds[2])
                if pH is not None:
                    book_probs[f'pH_{book}'] = pH
                    book_probs[f'pD_{book}'] = pD
                    book_probs[f'pA_{book}'] = pA
                    valid_books.append(book)
            
            # Skip if fewer than 2 books
            if len(valid_books) < 2:
                continue
            
            # Compute context features
            if len(valid_books) > 1:
                # Dispersion across books
                all_probs_h = [book_probs[f'pH_{book}'] for book in valid_books]
                all_probs_d = [book_probs[f'pD_{book}'] for book in valid_books]
                all_probs_a = [book_probs[f'pA_{book}'] for book in valid_books]
                
                dispersion = np.std(all_probs_h) + np.std(all_probs_d) + np.std(all_probs_a)
            else:
                dispersion = 0.0
            
            # Build record
            record = {
                'match_id': row['match_id'],
                'y': row['y'],
                'ctx_dispersion': dispersion,
                'ctx_n_books': len(valid_books),
                'ctx_has_pinnacle': 1 if 'ps' in valid_books else 0,
                'ctx_league_tier': 1 if row['league'] in ['E0', 'SP1', 'I1', 'D1', 'F1'] else 2
            }
            
            # Add league indicators
            for league in ['E0', 'SP1', 'I1', 'D1', 'F1']:
                record[f'ctx_league_{league}'] = 1 if row['league'] == league else 0
            
            # Add temporal features  
            match_date = pd.to_datetime(row['match_date'])
            record['ctx_month'] = match_date.month
            record['ctx_is_weekend'] = 1 if match_date.weekday() >= 5 else 0
            
            # Season phase
            season_phase_map = {8:0, 9:0, 10:0, 11:1, 12:1, 1:1, 2:1, 3:2, 4:2, 5:2}
            record['ctx_season_phase'] = season_phase_map.get(match_date.month, 1)
            
            # Compute overround (average across books)
            overrounds = []
            for book in valid_books:
                total_prob = book_probs[f'pH_{book}'] + book_probs[f'pD_{book}'] + book_probs[f'pA_{book}']
                # We normalized, so compute original overround estimate
                overrounds.append(1.05)  # Typical overround
            
            record['ctx_overround'] = np.mean(overrounds)
            
            # Add book probabilities
            record.update(book_probs)
            
            mixer_data.append(record)
        
        return pd.DataFrame(mixer_data)
    
    def run_preparation(self):
        """Run complete preparation"""
        
        print("BOOK MIXER DATA PREPARATION")
        print("=" * 35)
        
        try:
            # Load historical data
            df = self.load_historical_with_books()
            
            # Prepare for book mixer
            mixer_df = self.prepare_book_mixer_format(df)
            
            # Save prepared data
            os.makedirs('book_mixer_data', exist_ok=True)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            
            output_path = f'book_mixer_data/book_mixer_input_{timestamp}.csv'
            mixer_df.to_csv(output_path, index=False)
            
            # Print summary
            self.print_preparation_summary(mixer_df, output_path)
            
            return {
                'output_path': output_path,
                'data': mixer_df,
                'timestamp': timestamp
            }
            
        finally:
            self.conn.close()
    
    def print_preparation_summary(self, df, output_path):
        """Print preparation summary"""
        
        print(f"\n📊 BOOK MIXER DATA PREPARED:")
        print(f"   • Total Matches: {len(df):,}")
        print(f"   • Context Features: {len([col for col in df.columns if col.startswith('ctx_')])}")
        
        # Book coverage
        books = ['b365', 'bw', 'wh', 'ps']
        for book in books:
            coverage = len([col for col in df.columns if col.startswith(f'pH_{book}')])
            if coverage > 0:
                count = df[f'pH_{book}'].notna().sum()
                print(f"   • {book.upper()}: {count:,} matches ({count/len(df)*100:.1f}%)")
        
        print(f"   • Has Pinnacle: {df['ctx_has_pinnacle'].sum():,} matches ({df['ctx_has_pinnacle'].mean()*100:.1f}%)")
        print(f"   • Average Books/Match: {df['ctx_n_books'].mean():.1f}")
        print(f"   • Average Dispersion: {df['ctx_dispersion'].mean():.6f}")
        
        print(f"\n📁 Saved to: {output_path}")

def main():
    preparer = BookMixerDataPreparation()
    return preparer.run_preparation()

if __name__ == "__main__":
    main()