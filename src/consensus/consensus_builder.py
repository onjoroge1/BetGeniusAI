"""
Calibrated-Consensus Forecaster v1
Multi-book implied probabilities → vig removal → robust average → per-league calibration
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional
import psycopg2
import os
from datetime import datetime, timedelta
import json
import warnings
warnings.filterwarnings('ignore')

class ConsensusBuilder:
    """Build consensus forecasts from multi-book odds snapshots"""
    
    def __init__(self):
        self.supported_books = {
            'pinnacle': {'margin_typical': 0.02, 'weight': 1.0},
            'bet365': {'margin_typical': 0.05, 'weight': 0.9},
            'williamhill': {'margin_typical': 0.06, 'weight': 0.8},
            'betfair': {'margin_typical': 0.02, 'weight': 1.0},
            'sbobet': {'margin_typical': 0.03, 'weight': 0.9}
        }
        
        self.time_buckets = {
            'open': {'min_hours': 168, 'max_hours': None},  # 7 days+
            '48h': {'min_hours': 36, 'max_hours': 60},
            '24h': {'min_hours': 18, 'max_hours': 30},
            '12h': {'min_hours': 6, 'max_hours': 18},
            '6h': {'min_hours': 3, 'max_hours': 9},
            '3h': {'min_hours': 1.5, 'max_hours': 4.5},
            '1h': {'min_hours': 0.5, 'max_hours': 1.5},
            '30m': {'min_hours': 0.1, 'max_hours': 0.8},
            'close': {'min_hours': 0, 'max_hours': 0.1}
        }
    
    def get_db_connection(self):
        """Get database connection"""
        return psycopg2.connect(os.environ['DATABASE_URL'])
    
    def remove_vig(self, odds_h: float, odds_d: float, odds_a: float, 
                   method: str = 'proportional') -> Tuple[float, float, float]:
        """Remove vig from decimal odds to get true probabilities"""
        
        # Convert to implied probabilities
        impl_h = 1.0 / odds_h if odds_h > 1.0 else 0.01
        impl_d = 1.0 / odds_d if odds_d > 1.0 else 0.01
        impl_a = 1.0 / odds_a if odds_a > 1.0 else 0.01
        
        total_impl = impl_h + impl_d + impl_a
        margin = total_impl - 1.0
        
        if method == 'proportional':
            # Proportional removal (most common)
            true_h = impl_h / total_impl
            true_d = impl_d / total_impl
            true_a = impl_a / total_impl
            
        elif method == 'additive':
            # Additive removal (subtract margin equally)
            margin_per_outcome = margin / 3
            true_h = impl_h - margin_per_outcome
            true_d = impl_d - margin_per_outcome
            true_a = impl_a - margin_per_outcome
            
        elif method == 'power':
            # Power method (Shin approach)
            alpha = 1.0 - margin / total_impl
            true_h = (impl_h ** alpha) / ((impl_h ** alpha) + (impl_d ** alpha) + (impl_a ** alpha))
            true_d = (impl_d ** alpha) / ((impl_h ** alpha) + (impl_d ** alpha) + (impl_a ** alpha))
            true_a = (impl_a ** alpha) / ((impl_h ** alpha) + (impl_d ** alpha) + (impl_a ** alpha))
        
        else:
            raise ValueError(f"Unknown vig removal method: {method}")
        
        # Ensure probabilities are valid
        total = true_h + true_d + true_a
        if total > 0:
            return true_h / total, true_d / total, true_a / total
        else:
            return 1/3, 1/3, 1/3
    
    def get_odds_snapshots(self, match_ids: List[int], time_bucket: str) -> pd.DataFrame:
        """Get odds snapshots for matches in specific time bucket"""
        
        bucket_config = self.time_buckets[time_bucket]
        min_hours = bucket_config['min_hours']
        max_hours = bucket_config['max_hours']
        
        conn = self.get_db_connection()
        
        # Build time window conditions
        time_conditions = []
        if min_hours is not None:
            time_conditions.append(f"secs_to_kickoff >= {min_hours * 3600}")
        if max_hours is not None:
            time_conditions.append(f"secs_to_kickoff <= {max_hours * 3600}")
        
        time_filter = " AND ".join(time_conditions) if time_conditions else "TRUE"
        
        query = f"""
        SELECT 
            match_id,
            book_id,
            ts_snapshot,
            secs_to_kickoff,
            outcome,
            odds_decimal,
            implied_prob,
            market_margin
        FROM odds_snapshots
        WHERE match_id = ANY(%s)
          AND {time_filter}
          AND odds_decimal > 1.0
        ORDER BY match_id, book_id, ts_snapshot DESC
        """
        
        df = pd.read_sql_query(query, conn, params=[match_ids])
        conn.close()
        
        return df
    
    def build_consensus_for_bucket(self, match_ids: List[int], time_bucket: str,
                                 consensus_method: str = 'median') -> pd.DataFrame:
        """Build consensus probabilities for matches in time bucket"""
        
        print(f"Building consensus for {len(match_ids)} matches in {time_bucket} bucket...")
        
        # Get odds snapshots
        odds_df = self.get_odds_snapshots(match_ids, time_bucket)
        
        if len(odds_df) == 0:
            print(f"   No odds data found for {time_bucket} bucket")
            return pd.DataFrame()
        
        consensus_results = []
        
        for match_id in match_ids:
            match_odds = odds_df[odds_df['match_id'] == match_id]
            
            if len(match_odds) == 0:
                continue
            
            # Get latest snapshot per book
            latest_odds = match_odds.groupby(['book_id']).first().reset_index()
            
            # Convert to wide format (H/D/A columns)
            wide_odds = latest_odds.pivot(index=['match_id', 'book_id'], 
                                        columns='outcome', 
                                        values='odds_decimal').reset_index()
            
            # Ensure we have H/D/A columns
            for outcome in ['H', 'D', 'A']:
                if outcome not in wide_odds.columns:
                    wide_odds[outcome] = np.nan
            
            # Remove vig for each book
            book_probs = []
            dispersion_data = {'H': [], 'D': [], 'A': []}
            
            for _, row in wide_odds.iterrows():
                book_id = row['book_id']
                odds_h, odds_d, odds_a = row['H'], row['D'], row['A']
                
                # Skip if any odds missing
                if pd.isna(odds_h) or pd.isna(odds_d) or pd.isna(odds_a):
                    continue
                
                # Remove vig
                prob_h, prob_d, prob_a = self.remove_vig(odds_h, odds_d, odds_a)
                
                # Weight by book quality
                weight = self.supported_books.get(book_id, {'weight': 0.5})['weight']
                
                book_probs.append({
                    'book_id': book_id,
                    'prob_h': prob_h,
                    'prob_d': prob_d,
                    'prob_a': prob_a,
                    'weight': weight
                })
                
                # Track for dispersion
                dispersion_data['H'].append(prob_h)
                dispersion_data['D'].append(prob_d)
                dispersion_data['A'].append(prob_a)
            
            if len(book_probs) == 0:
                continue
            
            # Build consensus
            book_df = pd.DataFrame(book_probs)
            
            if consensus_method == 'median':
                consensus_h = np.median(book_df['prob_h'])
                consensus_d = np.median(book_df['prob_d'])
                consensus_a = np.median(book_df['prob_a'])
                
            elif consensus_method == 'weighted_mean':
                total_weight = book_df['weight'].sum()
                consensus_h = (book_df['prob_h'] * book_df['weight']).sum() / total_weight
                consensus_d = (book_df['prob_d'] * book_df['weight']).sum() / total_weight
                consensus_a = (book_df['prob_a'] * book_df['weight']).sum() / total_weight
                
            elif consensus_method == 'trimmed_mean':
                # Remove top/bottom 20% then average
                trim_pct = 0.2
                consensus_h = self._trimmed_mean(book_df['prob_h'], trim_pct)
                consensus_d = self._trimmed_mean(book_df['prob_d'], trim_pct)
                consensus_a = self._trimmed_mean(book_df['prob_a'], trim_pct)
            
            else:
                raise ValueError(f"Unknown consensus method: {consensus_method}")
            
            # Normalize to ensure sum = 1
            total = consensus_h + consensus_d + consensus_a
            consensus_h /= total
            consensus_d /= total
            consensus_a /= total
            
            # Calculate dispersion (uncertainty measure)
            disp_h = np.std(dispersion_data['H']) if len(dispersion_data['H']) > 1 else 0.0
            disp_d = np.std(dispersion_data['D']) if len(dispersion_data['D']) > 1 else 0.0
            disp_a = np.std(dispersion_data['A']) if len(dispersion_data['A']) > 1 else 0.0
            
            consensus_results.append({
                'match_id': match_id,
                'time_bucket': time_bucket,
                'consensus_h': consensus_h,
                'consensus_d': consensus_d,
                'consensus_a': consensus_a,
                'dispersion_h': disp_h,
                'dispersion_d': disp_d,
                'dispersion_a': disp_a,
                'n_books': len(book_probs),
                'consensus_method': consensus_method,
                'created_at': datetime.now()
            })
        
        consensus_df = pd.DataFrame(consensus_results)
        print(f"   Built consensus for {len(consensus_df)} matches")
        
        return consensus_df
    
    def _trimmed_mean(self, values: pd.Series, trim_pct: float) -> float:
        """Calculate trimmed mean"""
        if len(values) <= 2:
            return values.mean()
        
        sorted_vals = values.sort_values()
        n_trim = max(1, int(len(values) * trim_pct))
        
        trimmed = sorted_vals.iloc[n_trim:-n_trim] if n_trim > 0 else sorted_vals
        return trimmed.mean()
    
    def save_consensus_predictions(self, consensus_df: pd.DataFrame):
        """Save consensus predictions to database"""
        
        if len(consensus_df) == 0:
            return
        
        conn = self.get_db_connection()
        cursor = conn.cursor()
        
        # Create table if not exists
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS consensus_predictions (
            match_id BIGINT,
            time_bucket VARCHAR(16),
            consensus_h DOUBLE PRECISION,
            consensus_d DOUBLE PRECISION,
            consensus_a DOUBLE PRECISION,
            dispersion_h DOUBLE PRECISION,
            dispersion_d DOUBLE PRECISION,
            dispersion_a DOUBLE PRECISION,
            n_books INT,
            consensus_method VARCHAR(32),
            created_at TIMESTAMP,
            PRIMARY KEY(match_id, time_bucket)
        );
        """
        cursor.execute(create_table_sql)
        
        # Insert predictions
        insert_sql = """
        INSERT INTO consensus_predictions 
        (match_id, time_bucket, consensus_h, consensus_d, consensus_a,
         dispersion_h, dispersion_d, dispersion_a, n_books, consensus_method, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (match_id, time_bucket) 
        DO UPDATE SET 
            consensus_h = EXCLUDED.consensus_h,
            consensus_d = EXCLUDED.consensus_d,
            consensus_a = EXCLUDED.consensus_a,
            dispersion_h = EXCLUDED.dispersion_h,
            dispersion_d = EXCLUDED.dispersion_d,
            dispersion_a = EXCLUDED.dispersion_a,
            n_books = EXCLUDED.n_books,
            consensus_method = EXCLUDED.consensus_method,
            created_at = EXCLUDED.created_at
        """
        
        for _, row in consensus_df.iterrows():
            cursor.execute(insert_sql, (
                int(row['match_id']), row['time_bucket'],
                float(row['consensus_h']), float(row['consensus_d']), float(row['consensus_a']),
                float(row['dispersion_h']), float(row['dispersion_d']), float(row['dispersion_a']),
                int(row['n_books']), row['consensus_method'], row['created_at']
            ))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        print(f"Saved {len(consensus_df)} consensus predictions to database")

def main():
    """Build consensus for upcoming matches"""
    
    builder = ConsensusBuilder()
    
    # Get upcoming matches (example)
    conn = builder.get_db_connection()
    
    query = """
    SELECT match_id, league_id, match_date_utc
    FROM matches 
    WHERE match_date_utc > NOW() 
      AND match_date_utc < NOW() + INTERVAL '7 days'
      AND league_id IN (39, 140, 135, 78, 61)
    ORDER BY match_date_utc
    LIMIT 50
    """
    
    matches_df = pd.read_sql_query(query, conn)
    conn.close()
    
    if len(matches_df) == 0:
        print("No upcoming matches found")
        return
    
    print(f"Building consensus for {len(matches_df)} upcoming matches...")
    
    match_ids = matches_df['match_id'].tolist()
    
    # Build consensus for each time bucket
    for bucket in ['24h', '6h', '1h']:
        print(f"\nProcessing {bucket} bucket...")
        
        consensus_df = builder.build_consensus_for_bucket(
            match_ids, bucket, consensus_method='median'
        )
        
        if len(consensus_df) > 0:
            builder.save_consensus_predictions(consensus_df)
    
    print(f"\n✅ Consensus building complete!")

if __name__ == "__main__":
    main()