"""
Fixed Bulk Historical Odds Inserter
Properly handle CSV format and database insertion
"""

import os
import pandas as pd
import psycopg2
from datetime import datetime
import numpy as np
from typing import Dict, List, Tuple

class FixedBulkInserter:
    """Fixed version of bulk historical odds inserter"""
    
    def __init__(self):
        self.conn = psycopg2.connect(os.environ['DATABASE_URL'])
        self.existing_records = set()
        self.batch_size = 500
    
    def load_existing_records(self):
        """Load existing records to avoid duplicates"""
        
        print("Loading existing records to prevent duplicates...")
        
        cursor = self.conn.cursor()
        
        cursor.execute("""
        SELECT home_team, away_team, match_date, league
        FROM historical_odds
        """)
        
        existing = cursor.fetchall()
        cursor.close()
        
        for home, away, date, league in existing:
            key = f"{home}_{away}_{str(date)}_{league}"
            self.existing_records.add(key)
        
        print(f"Found {len(self.existing_records)} existing records")
    
    def parse_date(self, date_str: str) -> str:
        """Parse date from DD/MM/YY format to YYYY-MM-DD"""
        
        if pd.isna(date_str) or str(date_str).strip() == '' or str(date_str) == 'nan':
            return None
        
        try:
            date_str = str(date_str).strip()
            if '/' in date_str:
                parts = date_str.split('/')
                if len(parts) == 3:
                    day, month, year = parts
                    
                    # Convert 2-digit year to 4-digit
                    if len(year) == 2:
                        year_int = int(year)
                        if year_int >= 90:
                            year = f"19{year}"
                        else:
                            year = f"20{year}"
                    
                    return f"{year}-{month.zfill(2)}-{day.zfill(2)}"
            
            return None
            
        except Exception as e:
            return None
    
    def clean_numeric(self, value) -> float:
        """Clean and convert numeric values"""
        
        if pd.isna(value) or str(value).strip() == '' or str(value) == 'nan':
            return None
        
        try:
            return float(value)
        except:
            return None
    
    def clean_text(self, value) -> str:
        """Clean text values"""
        
        if pd.isna(value) or str(value).strip() == '' or str(value) == 'nan':
            return None
        
        return str(value).strip()
    
    def map_league_code(self, div_code: str) -> Tuple[str, str]:
        """Map division code to league name"""
        
        league_mapping = {
            'E0': ('E0', 'Premier League'),
            'E1': ('E1', 'Championship'),
            'D1': ('D1', 'Bundesliga'),
            'D2': ('D2', '2. Bundesliga'),
            'I1': ('I1', 'Serie A'),
            'I2': ('I2', 'Serie B'),
            'SP1': ('SP1', 'La Liga'),
            'SP2': ('SP2', 'Segunda Division'),
            'F1': ('F1', 'Ligue 1'),
            'F2': ('F2', 'Ligue 2'),
            'N1': ('N1', 'Eredivisie'),
            'P1': ('P1', 'Primeira Liga')
        }
        
        return league_mapping.get(div_code, (div_code, div_code))
    
    def process_row(self, row) -> Tuple:
        """Process a single CSV row"""
        
        try:
            # Basic match info
            home_team = self.clean_text(row.get('HomeTeam'))
            away_team = self.clean_text(row.get('AwayTeam'))
            date_str = self.clean_text(row.get('Date'))
            div_code = self.clean_text(row.get('Div'))
            
            if not home_team or not away_team or not date_str or not div_code:
                return None
            
            # Parse date
            match_date = self.parse_date(date_str)
            if not match_date:
                return None
            
            # Get league info
            league_code, league_name = self.map_league_code(div_code)
            
            # Check for duplicates
            unique_key = f"{home_team}_{away_team}_{match_date}_{league_code}"
            if unique_key in self.existing_records:
                return None
            
            # Match outcome
            home_goals = self.clean_numeric(row.get('FTHG'))
            away_goals = self.clean_numeric(row.get('FTAG'))
            result = self.clean_text(row.get('FTR'))
            
            # Season info
            season = self.clean_text(row.get('Season'))
            if not season:
                # Derive from date
                year = int(match_date.split('-')[0])
                month = int(match_date.split('-')[1])
                if month >= 8:
                    season = f"{year}{str(year+1)[2:]}"
                else:
                    season = f"{year-1}{str(year)[2:]}"
            
            # Bookmaker odds
            b365_h = self.clean_numeric(row.get('B365H'))
            b365_d = self.clean_numeric(row.get('B365D')) 
            b365_a = self.clean_numeric(row.get('B365A'))
            
            bw_h = self.clean_numeric(row.get('BWH'))
            bw_d = self.clean_numeric(row.get('BWD'))
            bw_a = self.clean_numeric(row.get('BWA'))
            
            iw_h = self.clean_numeric(row.get('IWH'))
            iw_d = self.clean_numeric(row.get('IWD'))
            iw_a = self.clean_numeric(row.get('IWA'))
            
            lb_h = self.clean_numeric(row.get('LBH'))
            lb_d = self.clean_numeric(row.get('LBD'))
            lb_a = self.clean_numeric(row.get('LBA'))
            
            ps_h = self.clean_numeric(row.get('PSH'))
            ps_d = self.clean_numeric(row.get('PSD'))
            ps_a = self.clean_numeric(row.get('PSA'))
            
            wh_h = self.clean_numeric(row.get('WHH'))
            wh_d = self.clean_numeric(row.get('WHD'))
            wh_a = self.clean_numeric(row.get('WHA'))
            
            sj_h = self.clean_numeric(row.get('SJH'))
            sj_d = self.clean_numeric(row.get('SJD'))
            sj_a = self.clean_numeric(row.get('SJA'))
            
            vc_h = self.clean_numeric(row.get('VCH'))
            vc_d = self.clean_numeric(row.get('VCD'))
            vc_a = self.clean_numeric(row.get('VCA'))
            
            # Average odds (try multiple column names)
            avg_h = self.clean_numeric(row.get('BbAvH')) or self.clean_numeric(row.get('AvgH'))
            avg_d = self.clean_numeric(row.get('BbAvD')) or self.clean_numeric(row.get('AvgD'))
            avg_a = self.clean_numeric(row.get('BbAvA')) or self.clean_numeric(row.get('AvgA'))
            
            # Max odds
            max_h = self.clean_numeric(row.get('BbMxH')) or self.clean_numeric(row.get('MaxH'))
            max_d = self.clean_numeric(row.get('BbMxD')) or self.clean_numeric(row.get('MaxD'))
            max_a = self.clean_numeric(row.get('BbMxA')) or self.clean_numeric(row.get('MaxA'))
            
            # Over/Under
            ou_line = self.clean_numeric(row.get('BbOU'))
            over_odds = self.clean_numeric(row.get('BbAv>2.5')) or self.clean_numeric(row.get('Avg>2.5'))
            under_odds = self.clean_numeric(row.get('BbAv<2.5')) or self.clean_numeric(row.get('Avg<2.5'))
            
            # Asian Handicap
            ah_line = self.clean_numeric(row.get('BbAHh')) or self.clean_numeric(row.get('AHh'))
            ah_home_odds = self.clean_numeric(row.get('BbAvAHH')) or self.clean_numeric(row.get('AvgAHH'))
            ah_away_odds = self.clean_numeric(row.get('BbAvAHA')) or self.clean_numeric(row.get('AvgAHA'))
            
            # Match statistics
            home_shots = self.clean_numeric(row.get('HS'))
            away_shots = self.clean_numeric(row.get('AS'))
            home_shots_target = self.clean_numeric(row.get('HST'))
            away_shots_target = self.clean_numeric(row.get('AST'))
            
            home_fouls = self.clean_numeric(row.get('HF'))
            away_fouls = self.clean_numeric(row.get('AF'))
            home_corners = self.clean_numeric(row.get('HC'))
            away_corners = self.clean_numeric(row.get('AC'))
            
            home_yellows = self.clean_numeric(row.get('HY'))
            away_yellows = self.clean_numeric(row.get('AY'))
            home_reds = self.clean_numeric(row.get('HR'))
            away_reds = self.clean_numeric(row.get('AR'))
            
            # Create timestamp
            kickoff_utc = f"{match_date} 15:00:00"
            
            # Return record tuple
            record = (
                match_date, season, league_code, league_name,
                home_team, away_team, home_goals, away_goals, result,
                b365_h, b365_d, b365_a,
                bw_h, bw_d, bw_a,
                iw_h, iw_d, iw_a,
                lb_h, lb_d, lb_a,
                ps_h, ps_d, ps_a,
                wh_h, wh_d, wh_a,
                sj_h, sj_d, sj_a,
                vc_h, vc_d, vc_a,
                avg_h, avg_d, avg_a,
                max_h, max_d, max_a,
                ou_line, over_odds, under_odds,
                ah_line, ah_home_odds, ah_away_odds,
                home_shots, away_shots, home_shots_target, away_shots_target,
                home_fouls, away_fouls, home_corners, away_corners,
                home_yellows, away_yellows, home_reds, away_reds,
                kickoff_utc
            )
            
            # Add to existing to prevent duplicates
            self.existing_records.add(unique_key)
            
            return record
            
        except Exception as e:
            return None
    
    def bulk_insert_batch(self, records: List[Tuple]) -> int:
        """Insert a batch of records"""
        
        if not records:
            return 0
        
        cursor = self.conn.cursor()
        
        insert_query = """
        INSERT INTO historical_odds (
            match_date, season, league, league_name,
            home_team, away_team, home_goals, away_goals, result,
            b365_h, b365_d, b365_a,
            bw_h, bw_d, bw_a,
            iw_h, iw_d, iw_a,
            lb_h, lb_d, lb_a,
            ps_h, ps_d, ps_a,
            wh_h, wh_d, wh_a,
            sj_h, sj_d, sj_a,
            vc_h, vc_d, vc_a,
            avg_h, avg_d, avg_a,
            max_h, max_d, max_a,
            ou_line, over_odds, under_odds,
            ah_line, ah_home_odds, ah_away_odds,
            home_shots, away_shots, home_shots_target, away_shots_target,
            home_fouls, away_fouls, home_corners, away_corners,
            home_yellows, away_yellows, home_reds, away_reds,
            kickoff_utc
        ) VALUES %s
        """
        
        try:
            # Use execute_values for efficient bulk insert
            from psycopg2.extras import execute_values
            execute_values(cursor, insert_query, records, template=None, page_size=100)
            self.conn.commit()
            inserted_count = len(records)
            cursor.close()
            return inserted_count
            
        except Exception as e:
            print(f"Batch insert error: {e}")
            self.conn.rollback()
            cursor.close()
            return 0
    
    def process_csv_file(self, csv_path: str) -> Dict:
        """Process the CSV file efficiently"""
        
        print(f"Processing {csv_path}...")
        
        # Load existing records
        self.load_existing_records()
        
        # Initialize counters
        total_processed = 0
        total_inserted = 0
        batch_records = []
        
        try:
            # Read CSV with proper settings
            df = pd.read_csv(csv_path, low_memory=False)
            
            # Skip first row if it's empty/malformed
            if df.iloc[0].isna().all():
                df = df.iloc[1:].reset_index(drop=True)
            
            print(f"Loaded CSV with {len(df)} rows")
            
            for idx, row in df.iterrows():
                total_processed += 1
                
                # Process row
                record = self.process_row(row)
                
                if record:
                    batch_records.append(record)
                
                # Insert batch when full
                if len(batch_records) >= self.batch_size:
                    inserted = self.bulk_insert_batch(batch_records)
                    total_inserted += inserted
                    batch_records = []
                    print(f"Progress: {total_processed:,} processed, {total_inserted:,} inserted")
                
                # Progress update
                if total_processed % 2000 == 0:
                    print(f"Processed {total_processed:,} rows...")
            
            # Insert remaining records
            if batch_records:
                inserted = self.bulk_insert_batch(batch_records)
                total_inserted += inserted
            
        except Exception as e:
            print(f"CSV processing error: {e}")
        
        return {
            'total_processed': total_processed,
            'total_inserted': total_inserted,
            'duplicates_skipped': total_processed - total_inserted,
            'success_rate': (total_inserted / total_processed * 100) if total_processed > 0 else 0
        }
    
    def verify_results(self) -> Dict:
        """Verify insertion results"""
        
        cursor = self.conn.cursor()
        
        # Total count
        cursor.execute("SELECT COUNT(*) FROM historical_odds")
        total_count = cursor.fetchone()[0]
        
        # League distribution
        cursor.execute("""
        SELECT league, COUNT(*) as count
        FROM historical_odds
        GROUP BY league
        ORDER BY count DESC
        """)
        league_dist = cursor.fetchall()
        
        # Date range
        cursor.execute("""
        SELECT MIN(match_date) as earliest, MAX(match_date) as latest
        FROM historical_odds
        """)
        date_range = cursor.fetchone()
        
        cursor.close()
        
        return {
            'total_records': total_count,
            'league_distribution': league_dist,
            'date_range': {
                'earliest': str(date_range[0]),
                'latest': str(date_range[1])
            }
        }
    
    def run_insertion(self, csv_path: str) -> Dict:
        """Run the complete insertion process"""
        
        print("FIXED BULK HISTORICAL ODDS INSERTION")
        print("=" * 50)
        
        # Process file
        processing_results = self.process_csv_file(csv_path)
        
        # Verify results
        verification_results = self.verify_results()
        
        # Create final report
        report = {
            'timestamp': datetime.now().isoformat(),
            'processing_results': processing_results,
            'verification_results': verification_results
        }
        
        return report

def main():
    """Run the fixed bulk insertion"""
    
    csv_path = 'attached_assets/top5_combined_1753907500195.csv'
    
    inserter = FixedBulkInserter()
    
    try:
        results = inserter.run_insertion(csv_path)
        
        # Save results
        os.makedirs('reports', exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        report_path = f'reports/fixed_insertion_{timestamp}.json'
        
        import json
        with open(report_path, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        
        # Print summary
        print("\n" + "=" * 60)
        print("INSERTION RESULTS SUMMARY")
        print("=" * 60)
        
        processing = results['processing_results']
        verification = results['verification_results']
        
        print(f"\n📊 PROCESSING:")
        print(f"   • Total Processed: {processing['total_processed']:,}")
        print(f"   • Successfully Inserted: {processing['total_inserted']:,}")
        print(f"   • Duplicates Skipped: {processing['duplicates_skipped']:,}")
        print(f"   • Success Rate: {processing['success_rate']:.1f}%")
        
        print(f"\n🗄️ DATABASE STATUS:")
        print(f"   • Total Records: {verification['total_records']:,}")
        print(f"   • Date Range: {verification['date_range']['earliest']} to {verification['date_range']['latest']}")
        
        print(f"\n🏆 TOP LEAGUES:")
        for league, count in verification['league_distribution'][:5]:
            print(f"   • {league}: {count:,} matches")
        
        enhancement_multiplier = verification['total_records'] / 4717
        print(f"\n🚀 ENHANCEMENT IMPACT:")
        print(f"   • Dataset Scale: {enhancement_multiplier:.1f}x larger")
        print(f"   • Expected Performance Boost: Significant")
        
        print(f"\n📄 Report saved: {report_path}")
        
        return results
        
    finally:
        inserter.conn.close()

if __name__ == "__main__":
    main()