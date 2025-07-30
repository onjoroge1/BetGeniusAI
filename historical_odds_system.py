"""
40-Year Historical Odds System - Rich Data Integration
Process comprehensive historical odds data for enhanced baselines
"""

import os
import json
import pandas as pd
import numpy as np
import psycopg2
from datetime import datetime, timedelta
import joblib
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import StratifiedKFold
from sklearn.metrics import log_loss, accuracy_score
from typing import Dict, List, Tuple, Optional

class HistoricalOddsSystem:
    """Complete 40-year historical odds integration system"""
    
    def __init__(self):
        self.conn = psycopg2.connect(os.environ['DATABASE_URL'])
        
    def analyze_historical_data_structure(self, csv_path: str) -> Dict:
        """Analyze the structure of historical odds data"""
        
        print("ANALYZING HISTORICAL ODDS DATA STRUCTURE")
        print("=" * 50)
        
        # Load sample of data
        df = pd.read_csv(csv_path, nrows=1000)
        
        print(f"Dataset shape: {df.shape}")
        # Handle date conversion safely
        df['Date'] = pd.to_datetime(df['Date'], format='%d/%m/%y', errors='coerce')
        valid_dates = df['Date'].dropna()
        
        print(f"Date range: {valid_dates.min()} to {valid_dates.max()}")
        print(f"Leagues: {df['League'].unique()}")
        print(f"Seasons: {sorted(df['Season'].unique())}")
        
        # Identify odds columns
        odds_columns = []
        bookmaker_columns = {}
        
        for col in df.columns:
            if any(bookie in col for bookie in ['B365', 'BW', 'IW', 'LB', 'PS', 'WH', 'SJ', 'VC', 'GB', 'SB', 'BS', 'SO']):
                odds_columns.append(col)
                
                # Extract bookmaker and market type
                for bookie in ['B365', 'BW', 'IW', 'LB', 'PS', 'WH', 'SJ', 'VC', 'GB', 'SB', 'BS', 'SO']:
                    if col.startswith(bookie):
                        if bookie not in bookmaker_columns:
                            bookmaker_columns[bookie] = []
                        bookmaker_columns[bookie].append(col)
        
        # Identify 3-way odds (H/D/A)
        three_way_bookies = []
        for bookie, cols in bookmaker_columns.items():
            h_col = f"{bookie}H"
            d_col = f"{bookie}D" 
            a_col = f"{bookie}A"
            
            if all(col in cols for col in [h_col, d_col, a_col]):
                three_way_bookies.append(bookie)
        
        # Calculate data completeness
        completeness = {}
        for bookie in three_way_bookies:
            h_col = f"{bookie}H"
            completeness[bookie] = {
                'total_matches': len(df),
                'available_odds': df[h_col].notna().sum(),
                'completeness_pct': (df[h_col].notna().sum() / len(df)) * 100
            }
        
        analysis = {
            'total_matches': len(df),
            'date_range': {
                'start': df['Date'].min(),
                'end': df['Date'].max()
            },
            'leagues': df['League'].unique().tolist(),
            'seasons': sorted(df['Season'].unique().tolist()),
            'bookmakers': {
                'total_identified': len(bookmaker_columns),
                'three_way_available': three_way_bookies,
                'completeness': completeness
            },
            'key_columns': {
                'match_info': ['Date', 'HomeTeam', 'AwayTeam', 'FTR', 'FTHG', 'FTAG'],
                'three_way_odds': [f"{b}{t}" for b in three_way_bookies for t in ['H', 'D', 'A']],
                'additional_markets': [col for col in odds_columns if not any(f"{b}{t}" in col for b in three_way_bookies for t in ['H', 'D', 'A'])]
            }
        }
        
        print(f"✅ Found {len(three_way_bookies)} bookmakers with 3-way odds")
        print(f"✅ Best coverage: {max(completeness.values(), key=lambda x: x['completeness_pct'])}")
        print(f"✅ {len(analysis['leagues'])} leagues identified")
        
        return analysis
    
    def create_historical_odds_schema(self):
        """Create enhanced schema for 40-year historical odds"""
        
        print("Creating enhanced historical odds schema...")
        
        cursor = self.conn.cursor()
        
        # Historical odds table (much richer than current synthetic data)
        cursor.execute("""
        DROP TABLE IF EXISTS historical_odds CASCADE;
        CREATE TABLE historical_odds (
            id SERIAL PRIMARY KEY,
            match_date DATE NOT NULL,
            season VARCHAR(10) NOT NULL,
            league VARCHAR(10) NOT NULL,
            league_name VARCHAR(50),
            home_team VARCHAR(100) NOT NULL,
            away_team VARCHAR(100) NOT NULL,
            home_goals INT NOT NULL,
            away_goals INT NOT NULL,
            result CHAR(1) CHECK (result IN ('H','D','A')) NOT NULL,
            
            -- Multiple bookmaker odds for consensus building
            b365_h FLOAT, b365_d FLOAT, b365_a FLOAT,
            bw_h FLOAT, bw_d FLOAT, bw_a FLOAT,
            iw_h FLOAT, iw_d FLOAT, iw_a FLOAT,
            lb_h FLOAT, lb_d FLOAT, lb_a FLOAT,
            ps_h FLOAT, ps_d FLOAT, ps_a FLOAT,
            wh_h FLOAT, wh_d FLOAT, wh_a FLOAT,
            sj_h FLOAT, sj_d FLOAT, sj_a FLOAT,
            vc_h FLOAT, vc_d FLOAT, vc_a FLOAT,
            
            -- Additional market data
            avg_h FLOAT, avg_d FLOAT, avg_a FLOAT,
            max_h FLOAT, max_d FLOAT, max_a FLOAT,
            
            -- Over/Under markets
            ou_line FLOAT,
            over_odds FLOAT,
            under_odds FLOAT,
            
            -- Asian Handicap
            ah_line FLOAT,
            ah_home_odds FLOAT,
            ah_away_odds FLOAT,
            
            -- Match statistics
            home_shots INT,
            away_shots INT,
            home_shots_target INT,
            away_shots_target INT,
            home_fouls INT,
            away_fouls INT,
            home_corners INT,
            away_corners INT,
            home_yellows INT,
            away_yellows INT,
            home_reds INT,
            away_reds INT,
            
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            
            -- Indexes for performance
            UNIQUE(match_date, home_team, away_team, league)
        );
        
        CREATE INDEX idx_historical_odds_date ON historical_odds(match_date);
        CREATE INDEX idx_historical_odds_league ON historical_odds(league);
        CREATE INDEX idx_historical_odds_season ON historical_odds(season);
        CREATE INDEX idx_historical_odds_teams ON historical_odds(home_team, away_team);
        """)
        
        # Enhanced consensus table combining historical + current data
        cursor.execute("""
        DROP TABLE IF EXISTS enhanced_consensus CASCADE;
        CREATE TABLE enhanced_consensus (
            match_id BIGINT,
            historical_match_id BIGINT,
            consensus_type VARCHAR(20) CHECK (consensus_type IN ('historical', 'current', 'hybrid')),
            
            -- Consensus probabilities
            pH_consensus FLOAT NOT NULL,
            pD_consensus FLOAT NOT NULL,
            pA_consensus FLOAT NOT NULL,
            
            -- Consensus metadata
            n_bookmakers INT NOT NULL,
            consensus_method VARCHAR(20) DEFAULT 'median',
            market_efficiency FLOAT, -- Measure of market agreement
            
            -- Historical context
            data_vintage VARCHAR(20), -- e.g., 'T-72h', 'T-0h', 'historical'
            match_date DATE,
            league VARCHAR(10),
            
            -- Quality metrics
            coverage_score FLOAT, -- How many bookmakers had odds
            dispersion_score FLOAT, -- How much bookmakers disagreed
            
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            
            PRIMARY KEY (match_id, consensus_type)
        );
        """)
        
        # Market features table enhanced with historical depth
        cursor.execute("""
        DROP TABLE IF EXISTS enhanced_market_features CASCADE;
        CREATE TABLE enhanced_market_features (
            match_id BIGINT PRIMARY KEY,
            
            -- Market probability features
            market_pH FLOAT NOT NULL,
            market_pD FLOAT NOT NULL,
            market_pA FLOAT NOT NULL,
            
            -- Market logits (for residual modeling)
            market_logit_H FLOAT NOT NULL,
            market_logit_D FLOAT DEFAULT 0.0,
            market_logit_A FLOAT NOT NULL,
            
            -- Market uncertainty measures
            market_entropy FLOAT NOT NULL,
            market_dispersion FLOAT NOT NULL,
            market_efficiency FLOAT,
            
            -- Historical context features
            historical_h2h_home_wins INT DEFAULT 0,
            historical_h2h_draws INT DEFAULT 0,
            historical_h2h_away_wins INT DEFAULT 0,
            
            -- Season context
            home_form_last5 FLOAT DEFAULT 0,
            away_form_last5 FLOAT DEFAULT 0,
            
            -- League context
            league_home_advantage FLOAT DEFAULT 0,
            league_competitiveness FLOAT DEFAULT 0,
            
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        
        self.conn.commit()
        cursor.close()
        
        print("✅ Enhanced historical odds schema created")
    
    def process_historical_odds_file(self, csv_path: str, batch_size: int = 1000) -> Dict:
        """Process the 40-year historical odds CSV file"""
        
        print(f"Processing historical odds file: {csv_path}")
        
        # Read file in chunks for memory efficiency
        chunk_iter = pd.read_csv(csv_path, chunksize=batch_size)
        
        total_processed = 0
        total_inserted = 0
        league_stats = {}
        
        cursor = self.conn.cursor()
        
        for chunk_num, chunk in enumerate(chunk_iter):
            print(f"Processing chunk {chunk_num + 1} ({len(chunk)} matches)...")
            
            # Prepare batch insert data
            batch_data = []
            
            for _, row in chunk.iterrows():
                try:
                    # Parse date
                    match_date = pd.to_datetime(row['Date'], format='%d/%m/%y')
                    
                    # Map result
                    result_map = {'H': 'H', 'D': 'D', 'A': 'A'}
                    result = result_map.get(row['FTR'])
                    
                    if result is None:
                        continue
                    
                    # Extract odds (handle NaN values)
                    def safe_float(val):
                        try:
                            return float(val) if pd.notna(val) else None
                        except:
                            return None
                    
                    # Core match data
                    match_data = {
                        'match_date': match_date.date(),
                        'season': str(int(row['Season'])),
                        'league': row.get('Div', row.get('LeagueCode', 'UNK')),
                        'league_name': row.get('League', 'Unknown'),
                        'home_team': row['HomeTeam'],
                        'away_team': row['AwayTeam'],
                        'home_goals': int(row['FTHG']),
                        'away_goals': int(row['FTAG']),
                        'result': result,
                        
                        # Bookmaker odds
                        'b365_h': safe_float(row.get('B365H')),
                        'b365_d': safe_float(row.get('B365D')),
                        'b365_a': safe_float(row.get('B365A')),
                        'bw_h': safe_float(row.get('BWH')),
                        'bw_d': safe_float(row.get('BWD')),
                        'bw_a': safe_float(row.get('BWA')),
                        'iw_h': safe_float(row.get('IWH')),
                        'iw_d': safe_float(row.get('IWD')),
                        'iw_a': safe_float(row.get('IWA')),
                        'lb_h': safe_float(row.get('LBH')),
                        'lb_d': safe_float(row.get('LBD')),
                        'lb_a': safe_float(row.get('LBA')),
                        'ps_h': safe_float(row.get('PSH')),
                        'ps_d': safe_float(row.get('PSD')),
                        'ps_a': safe_float(row.get('PSA')),
                        'wh_h': safe_float(row.get('WHH')),
                        'wh_d': safe_float(row.get('WHD')),
                        'wh_a': safe_float(row.get('WHA')),
                        'sj_h': safe_float(row.get('SJH')),
                        'sj_d': safe_float(row.get('SJD')),
                        'sj_a': safe_float(row.get('SJA')),
                        'vc_h': safe_float(row.get('VCH')),
                        'vc_d': safe_float(row.get('VCD')),
                        'vc_a': safe_float(row.get('VCA')),
                        
                        # Additional markets
                        'avg_h': safe_float(row.get('BbAvH')),
                        'avg_d': safe_float(row.get('BbAvD')),
                        'avg_a': safe_float(row.get('BbAvA')),
                        'max_h': safe_float(row.get('BbMxH')),
                        'max_d': safe_float(row.get('BbMxD')),
                        'max_a': safe_float(row.get('BbMxA')),
                        
                        # Over/Under
                        'over_odds': safe_float(row.get('BbAv>2.5')),
                        'under_odds': safe_float(row.get('BbAv<2.5')),
                        
                        # Asian Handicap
                        'ah_line': safe_float(row.get('BbAHh')),
                        'ah_home_odds': safe_float(row.get('BbAvAHH')),
                        'ah_away_odds': safe_float(row.get('BbAvAHA')),
                        
                        # Match statistics
                        'home_shots': int(row.get('HS', 0)) if pd.notna(row.get('HS')) else None,
                        'away_shots': int(row.get('AS', 0)) if pd.notna(row.get('AS')) else None,
                        'home_shots_target': int(row.get('HST', 0)) if pd.notna(row.get('HST')) else None,
                        'away_shots_target': int(row.get('AST', 0)) if pd.notna(row.get('AST')) else None,
                        'home_fouls': int(row.get('HF', 0)) if pd.notna(row.get('HF')) else None,
                        'away_fouls': int(row.get('AF', 0)) if pd.notna(row.get('AF')) else None,
                        'home_corners': int(row.get('HC', 0)) if pd.notna(row.get('HC')) else None,
                        'away_corners': int(row.get('AC', 0)) if pd.notna(row.get('AC')) else None,
                        'home_yellows': int(row.get('HY', 0)) if pd.notna(row.get('HY')) else None,
                        'away_yellows': int(row.get('AY', 0)) if pd.notna(row.get('AY')) else None,
                        'home_reds': int(row.get('HR', 0)) if pd.notna(row.get('HR')) else None,
                        'away_reds': int(row.get('AR', 0)) if pd.notna(row.get('AR')) else None
                    }
                    
                    batch_data.append(match_data)
                    
                    # Track league statistics
                    league = match_data['league']
                    if league not in league_stats:
                        league_stats[league] = {'matches': 0, 'seasons': set()}
                    league_stats[league]['matches'] += 1
                    league_stats[league]['seasons'].add(match_data['season'])
                    
                except Exception as e:
                    print(f"Error processing row: {e}")
                    continue
            
            # Batch insert
            if batch_data:
                insert_sql = """
                INSERT INTO historical_odds (
                    match_date, season, league, league_name, home_team, away_team,
                    home_goals, away_goals, result,
                    b365_h, b365_d, b365_a, bw_h, bw_d, bw_a,
                    iw_h, iw_d, iw_a, lb_h, lb_d, lb_a,
                    ps_h, ps_d, ps_a, wh_h, wh_d, wh_a,
                    sj_h, sj_d, sj_a, vc_h, vc_d, vc_a,
                    avg_h, avg_d, avg_a, max_h, max_d, max_a,
                    over_odds, under_odds, ah_line, ah_home_odds, ah_away_odds,
                    home_shots, away_shots, home_shots_target, away_shots_target,
                    home_fouls, away_fouls, home_corners, away_corners,
                    home_yellows, away_yellows, home_reds, away_reds
                ) VALUES (
                    %(match_date)s, %(season)s, %(league)s, %(league_name)s, 
                    %(home_team)s, %(away_team)s, %(home_goals)s, %(away_goals)s, %(result)s,
                    %(b365_h)s, %(b365_d)s, %(b365_a)s, %(bw_h)s, %(bw_d)s, %(bw_a)s,
                    %(iw_h)s, %(iw_d)s, %(iw_a)s, %(lb_h)s, %(lb_d)s, %(lb_a)s,
                    %(ps_h)s, %(ps_d)s, %(ps_a)s, %(wh_h)s, %(wh_d)s, %(wh_a)s,
                    %(sj_h)s, %(sj_d)s, %(sj_a)s, %(vc_h)s, %(vc_d)s, %(vc_a)s,
                    %(avg_h)s, %(avg_d)s, %(avg_a)s, %(max_h)s, %(max_d)s, %(max_a)s,
                    %(over_odds)s, %(under_odds)s, %(ah_line)s, %(ah_home_odds)s, %(ah_away_odds)s,
                    %(home_shots)s, %(away_shots)s, %(home_shots_target)s, %(away_shots_target)s,
                    %(home_fouls)s, %(away_fouls)s, %(home_corners)s, %(away_corners)s,
                    %(home_yellows)s, %(away_yellows)s, %(home_reds)s, %(away_reds)s
                ) ON CONFLICT (match_date, home_team, away_team, league) DO NOTHING
                """
                
                cursor.executemany(insert_sql, batch_data)
                self.conn.commit()
                
                total_inserted += len(batch_data)
            
            total_processed += len(chunk)
            
            if chunk_num % 5 == 0:  # Progress update every 5 chunks
                print(f"✅ Processed {total_processed} matches, inserted {total_inserted}")
        
        cursor.close()
        
        # Convert sets to lists for JSON serialization
        for league in league_stats:
            league_stats[league]['seasons'] = sorted(list(league_stats[league]['seasons']))
        
        processing_summary = {
            'total_processed': total_processed,
            'total_inserted': total_inserted,
            'league_statistics': league_stats,
            'processing_date': datetime.now().isoformat()
        }
        
        print(f"✅ Historical odds processing complete:")
        print(f"   Total processed: {total_processed}")
        print(f"   Total inserted: {total_inserted}")
        print(f"   Leagues: {len(league_stats)}")
        
        return processing_summary
    
    def generate_enhanced_consensus(self, min_bookmakers: int = 3) -> Dict:
        """Generate enhanced consensus from historical odds"""
        
        print("Generating enhanced consensus from historical data...")
        
        cursor = self.conn.cursor()
        
        # Get historical matches with sufficient odds coverage
        cursor.execute("""
        SELECT id, match_date, league, home_team, away_team, result,
               b365_h, b365_d, b365_a, bw_h, bw_d, bw_a,
               iw_h, iw_d, iw_a, lb_h, lb_d, lb_a,
               ps_h, ps_d, ps_a, wh_h, wh_d, wh_a,
               sj_h, sj_d, sj_a, vc_h, vc_d, vc_a
        FROM historical_odds
        WHERE match_date >= '2010-01-01'  -- Focus on recent data for better quality
        ORDER BY match_date DESC
        LIMIT 10000  -- Process subset for demonstration
        """)
        
        matches = cursor.fetchall()
        
        consensus_entries = []
        feature_entries = []
        
        for match in matches:
            (match_id, match_date, league, home_team, away_team, result,
             b365_h, b365_d, b365_a, bw_h, bw_d, bw_a,
             iw_h, iw_d, iw_a, lb_h, lb_d, lb_a,
             ps_h, ps_d, ps_a, wh_h, wh_d, wh_a,
             sj_h, sj_d, sj_a, vc_h, vc_d, vc_a) = match
            
            # Collect available bookmaker odds
            bookmaker_odds = []
            bookmaker_names = []
            
            odds_sets = [
                ('B365', b365_h, b365_d, b365_a),
                ('BW', bw_h, bw_d, bw_a),
                ('IW', iw_h, iw_d, iw_a),
                ('LB', lb_h, lb_d, lb_a),
                ('PS', ps_h, ps_d, ps_a),
                ('WH', wh_h, wh_d, wh_a),
                ('SJ', sj_h, sj_d, sj_a),
                ('VC', vc_h, vc_d, vc_a)
            ]
            
            for name, h_odds, d_odds, a_odds in odds_sets:
                if all(x is not None and x > 0 for x in [h_odds, d_odds, a_odds]):
                    # Convert odds to probabilities
                    prob_h = 1.0 / h_odds
                    prob_d = 1.0 / d_odds
                    prob_a = 1.0 / a_odds
                    
                    # Normalize to remove overround
                    total = prob_h + prob_d + prob_a
                    prob_h /= total
                    prob_d /= total
                    prob_a /= total
                    
                    bookmaker_odds.append([prob_h, prob_d, prob_a])
                    bookmaker_names.append(name)
            
            # Skip if insufficient coverage
            if len(bookmaker_odds) < min_bookmakers:
                continue
            
            # Calculate consensus (median)
            odds_array = np.array(bookmaker_odds)
            consensus_probs = np.median(odds_array, axis=0)
            
            # Calculate market efficiency metrics
            dispersion = np.std(odds_array, axis=0).mean()
            market_efficiency = 1.0 - dispersion  # Lower dispersion = higher efficiency
            
            # Market features
            market_entropy = -sum(p * np.log(p) for p in consensus_probs if p > 0)
            market_logits = {
                'H': np.log(consensus_probs[0] / consensus_probs[1]),
                'A': np.log(consensus_probs[2] / consensus_probs[1])
            }
            
            # Store consensus
            consensus_entries.append({
                'match_id': match_id,
                'historical_match_id': match_id,
                'consensus_type': 'historical',
                'pH_consensus': float(consensus_probs[0]),
                'pD_consensus': float(consensus_probs[1]),
                'pA_consensus': float(consensus_probs[2]),
                'n_bookmakers': len(bookmaker_odds),
                'market_efficiency': float(market_efficiency),
                'coverage_score': float(len(bookmaker_odds) / 8.0),  # Out of 8 potential bookmakers
                'dispersion_score': float(dispersion),
                'match_date': match_date,
                'league': league
            })
            
            # Store enhanced features
            feature_entries.append({
                'match_id': match_id,
                'market_pH': float(consensus_probs[0]),
                'market_pD': float(consensus_probs[1]),
                'market_pA': float(consensus_probs[2]),
                'market_logit_H': float(market_logits['H']),
                'market_logit_A': float(market_logits['A']),
                'market_entropy': float(market_entropy),
                'market_dispersion': float(dispersion),
                'market_efficiency': float(market_efficiency)
            })
        
        # Batch insert consensus data
        if consensus_entries:
            consensus_sql = """
            INSERT INTO enhanced_consensus 
            (match_id, historical_match_id, consensus_type, pH_consensus, pD_consensus, pA_consensus,
             n_bookmakers, market_efficiency, coverage_score, dispersion_score, match_date, league)
            VALUES (%(match_id)s, %(historical_match_id)s, %(consensus_type)s, 
                    %(pH_consensus)s, %(pD_consensus)s, %(pA_consensus)s,
                    %(n_bookmakers)s, %(market_efficiency)s, %(coverage_score)s, 
                    %(dispersion_score)s, %(match_date)s, %(league)s)
            ON CONFLICT (match_id, consensus_type) DO UPDATE SET
            pH_consensus = EXCLUDED.pH_consensus
            """
            cursor.executemany(consensus_sql, consensus_entries)
        
        # Batch insert features
        if feature_entries:
            features_sql = """
            INSERT INTO enhanced_market_features 
            (match_id, market_pH, market_pD, market_pA, market_logit_H, market_logit_A,
             market_entropy, market_dispersion, market_efficiency)
            VALUES (%(match_id)s, %(market_pH)s, %(market_pD)s, %(market_pA)s,
                    %(market_logit_H)s, %(market_logit_A)s, %(market_entropy)s,
                    %(market_dispersion)s, %(market_efficiency)s)
            ON CONFLICT (match_id) DO UPDATE SET
            market_pH = EXCLUDED.market_pH
            """
            cursor.executemany(features_sql, feature_entries)
        
        self.conn.commit()
        cursor.close()
        
        results = {
            'consensus_entries': len(consensus_entries),
            'feature_entries': len(feature_entries),
            'bookmaker_coverage': {
                'min': min(entry['n_bookmakers'] for entry in consensus_entries) if consensus_entries else 0,
                'max': max(entry['n_bookmakers'] for entry in consensus_entries) if consensus_entries else 0,
                'avg': np.mean([entry['n_bookmakers'] for entry in consensus_entries]) if consensus_entries else 0
            }
        }
        
        print(f"✅ Generated {len(consensus_entries)} consensus entries")
        print(f"✅ Created {len(feature_entries)} enhanced features")
        print(f"✅ Average bookmaker coverage: {results['bookmaker_coverage']['avg']:.1f}")
        
        return results

def main():
    """Run 40-year historical odds analysis"""
    
    historical_system = HistoricalOddsSystem()
    
    # File path
    csv_path = "attached_assets/top5_combined_1753901202416.csv"
    
    try:
        # Step 1: Analyze data structure
        print("STEP 1: ANALYZING DATA STRUCTURE")
        analysis = historical_system.analyze_historical_data_structure(csv_path)
        
        # Step 2: Create enhanced schema
        print("\nSTEP 2: CREATING ENHANCED SCHEMA")
        historical_system.create_historical_odds_schema()
        
        # Step 3: Process historical file (sample for demonstration)
        print("\nSTEP 3: PROCESSING HISTORICAL DATA")
        processing_results = historical_system.process_historical_odds_file(csv_path, batch_size=500)
        
        # Step 4: Generate enhanced consensus
        print("\nSTEP 4: GENERATING ENHANCED CONSENSUS")
        consensus_results = historical_system.generate_enhanced_consensus()
        
        # Final summary
        print(f"\n" + "=" * 60)
        print("40-YEAR HISTORICAL ODDS SYSTEM - COMPLETE")
        print("=" * 60)
        print(f"✅ Data structure analyzed: {len(analysis['bookmakers']['three_way_available'])} bookmakers")
        print(f"✅ Historical matches processed: {processing_results['total_inserted']}")
        print(f"✅ Enhanced consensus generated: {consensus_results['consensus_entries']}")
        print(f"✅ Rich features created: {consensus_results['feature_entries']}")
        print(f"✅ Average bookmaker coverage: {consensus_results['bookmaker_coverage']['avg']:.1f}/8")
        
        return {
            'analysis': analysis,
            'processing': processing_results,
            'consensus': consensus_results
        }
        
    finally:
        historical_system.conn.close()

if __name__ == "__main__":
    main()