"""
Import historical match data from football-data.co.uk CSV files into historical_odds table.

CSV Format (football-data.co.uk):
- Div: Division/League code (e.g., SC1, E0, SP1)
- Date: DD/MM/YYYY
- HomeTeam, AwayTeam: Team names
- FTHG, FTAG: Full-time goals
- FTR: Full-time result (H/D/A)
- B365H, B365D, B365A: Bet365 odds
- HS, AS: Home/Away shots
- HC, AC: Corners
- HY, AY: Yellow cards
"""

import os
import sys
import pandas as pd
import psycopg2
from datetime import datetime
from pathlib import Path

DATABASE_URL = os.getenv('DATABASE_URL')

# League code mapping (CSV code -> Full league name)
LEAGUE_MAPPING = {
    'SC0': 'Scottish Premiership',
    'SC1': 'Scottish Championship',
    'SC2': 'Scottish League Two',
    'SC3': 'Scottish League Three',
    'E0': 'Premier League',
    'E1': 'Championship',
    'E2': 'League One',
    'E3': 'League Two',
    'EC': 'Conference',
    'SP1': 'La Liga',
    'SP2': 'La Liga 2',
    'I1': 'Serie A',
    'I2': 'Serie B',
    'D1': 'Bundesliga',
    'D2': 'Bundesliga 2',
    'F1': 'Ligue 1',
    'F2': 'Ligue 2',
    'N1': 'Eredivisie',
    'B1': 'Jupiler League',
    'P1': 'Primeira Liga',
    'T1': 'Super Lig',
    'G1': 'Super League Greece',
}

def parse_date(date_str):
    """Parse DD/MM/YYYY format to datetime"""
    try:
        return datetime.strptime(date_str, '%d/%m/%Y')
    except:
        try:
            return datetime.strptime(date_str, '%d/%m/%y')
        except:
            return None

def extract_season_from_date(date):
    """Extract season from date (e.g., 2020-10-16 -> 2020)"""
    if date.month >= 8:  # Season starts in August
        return date.year
    else:
        return date.year - 1

def safe_float(value):
    """Safely convert to float, return None if invalid"""
    try:
        return float(value) if pd.notna(value) else None
    except:
        return None

def safe_int(value):
    """Safely convert to int, return None if invalid"""
    try:
        return int(value) if pd.notna(value) else None
    except:
        return None

def import_csv_file(csv_path, conn):
    """Import a single CSV file into historical_odds table"""
    
    print(f"\n{'='*80}")
    print(f"Processing: {Path(csv_path).name}")
    print('='*80)
    
    # Read CSV
    try:
        df = pd.read_csv(csv_path)
    except Exception as e:
        print(f"❌ Error reading CSV: {e}")
        return 0
    
    print(f"  Rows in CSV: {len(df)}")
    
    # Required columns check
    required = ['Div', 'Date', 'HomeTeam', 'AwayTeam', 'FTHG', 'FTAG', 'FTR']
    missing = [col for col in required if col not in df.columns]
    if missing:
        print(f"❌ Missing required columns: {missing}")
        return 0
    
    inserted_count = 0
    skipped_count = 0
    
    cur = conn.cursor()
    
    for idx, row in df.iterrows():
        try:
            # Parse basic match info
            league_code = row['Div']
            league_name = LEAGUE_MAPPING.get(league_code, league_code)
            
            date = parse_date(row['Date'])
            if not date:
                skipped_count += 1
                continue
            
            season = extract_season_from_date(date)
            
            home_team = str(row['HomeTeam']).strip()
            away_team = str(row['AwayTeam']).strip()
            home_goals = safe_int(row['FTHG'])
            away_goals = safe_int(row['FTAG'])
            result = row['FTR'] if pd.notna(row['FTR']) else None
            
            # Skip if missing critical data
            if not all([home_team, away_team, home_goals is not None, away_goals is not None, result]):
                skipped_count += 1
                continue
            
            # Extract odds for each bookmaker
            odds_data = {
                'b365_h': safe_float(row.get('B365H')),
                'b365_d': safe_float(row.get('B365D')),
                'b365_a': safe_float(row.get('B365A')),
                'bw_h': safe_float(row.get('BWH')),
                'bw_d': safe_float(row.get('BWD')),
                'bw_a': safe_float(row.get('BWA')),
                'iw_h': safe_float(row.get('IWH')),
                'iw_d': safe_float(row.get('IWD')),
                'iw_a': safe_float(row.get('IWA')),
                'ps_h': safe_float(row.get('PSH')),
                'ps_d': safe_float(row.get('PSD')),
                'ps_a': safe_float(row.get('PSA')),
                'wh_h': safe_float(row.get('WHH')),
                'wh_d': safe_float(row.get('WHD')),
                'wh_a': safe_float(row.get('WHA')),
                'vc_h': safe_float(row.get('VCH')),
                'vc_d': safe_float(row.get('VCD')),
                'vc_a': safe_float(row.get('VCA')),
                'avg_h': safe_float(row.get('AvgH')),
                'avg_d': safe_float(row.get('AvgD')),
                'avg_a': safe_float(row.get('AvgA')),
                'max_h': safe_float(row.get('MaxH')),
                'max_d': safe_float(row.get('MaxD')),
                'max_a': safe_float(row.get('MaxA')),
            }
            
            # Extract match statistics
            stats = {
                'home_shots': safe_int(row.get('HS')),
                'away_shots': safe_int(row.get('AS')),
                'home_shots_target': safe_int(row.get('HST')),
                'away_shots_target': safe_int(row.get('AST')),
                'home_fouls': safe_int(row.get('HF')),
                'away_fouls': safe_int(row.get('AF')),
                'home_corners': safe_int(row.get('HC')),
                'away_corners': safe_int(row.get('AC')),
                'home_yellows': safe_int(row.get('HY')),
                'away_yellows': safe_int(row.get('AY')),
                'home_reds': safe_int(row.get('HR')),
                'away_reds': safe_int(row.get('AR')),
            }
            
            # Insert row
            cur.execute("""
                INSERT INTO historical_odds (
                    match_date, season, league, league_name,
                    home_team, away_team, home_goals, away_goals, result,
                    b365_h, b365_d, b365_a,
                    bw_h, bw_d, bw_a,
                    iw_h, iw_d, iw_a,
                    ps_h, ps_d, ps_a,
                    wh_h, wh_d, wh_a,
                    vc_h, vc_d, vc_a,
                    avg_h, avg_d, avg_a,
                    max_h, max_d, max_a,
                    home_shots, away_shots,
                    home_shots_target, away_shots_target,
                    home_fouls, away_fouls,
                    home_corners, away_corners,
                    home_yellows, away_yellows,
                    home_reds, away_reds
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                ON CONFLICT (match_date, home_team, away_team) DO UPDATE SET
                    b365_h = COALESCE(EXCLUDED.b365_h, historical_odds.b365_h),
                    b365_d = COALESCE(EXCLUDED.b365_d, historical_odds.b365_d),
                    b365_a = COALESCE(EXCLUDED.b365_a, historical_odds.b365_a),
                    bw_h = COALESCE(EXCLUDED.bw_h, historical_odds.bw_h),
                    bw_d = COALESCE(EXCLUDED.bw_d, historical_odds.bw_d),
                    bw_a = COALESCE(EXCLUDED.bw_a, historical_odds.bw_a),
                    iw_h = COALESCE(EXCLUDED.iw_h, historical_odds.iw_h),
                    iw_d = COALESCE(EXCLUDED.iw_d, historical_odds.iw_d),
                    iw_a = COALESCE(EXCLUDED.iw_a, historical_odds.iw_a),
                    ps_h = COALESCE(EXCLUDED.ps_h, historical_odds.ps_h),
                    ps_d = COALESCE(EXCLUDED.ps_d, historical_odds.ps_d),
                    ps_a = COALESCE(EXCLUDED.ps_a, historical_odds.ps_a),
                    wh_h = COALESCE(EXCLUDED.wh_h, historical_odds.wh_h),
                    wh_d = COALESCE(EXCLUDED.wh_d, historical_odds.wh_d),
                    wh_a = COALESCE(EXCLUDED.wh_a, historical_odds.wh_a),
                    vc_h = COALESCE(EXCLUDED.vc_h, historical_odds.vc_h),
                    vc_d = COALESCE(EXCLUDED.vc_d, historical_odds.vc_d),
                    vc_a = COALESCE(EXCLUDED.vc_a, historical_odds.vc_a),
                    home_shots = COALESCE(EXCLUDED.home_shots, historical_odds.home_shots),
                    away_shots = COALESCE(EXCLUDED.away_shots, historical_odds.away_shots),
                    home_corners = COALESCE(EXCLUDED.home_corners, historical_odds.home_corners),
                    away_corners = COALESCE(EXCLUDED.away_corners, historical_odds.away_corners),
                    home_yellows = COALESCE(EXCLUDED.home_yellows, historical_odds.home_yellows),
                    away_yellows = COALESCE(EXCLUDED.away_yellows, historical_odds.away_yellows),
                    home_reds = COALESCE(EXCLUDED.home_reds, historical_odds.home_reds),
                    away_reds = COALESCE(EXCLUDED.away_reds, historical_odds.away_reds)
            """, (
                date, str(season), league_code, league_name,
                home_team, away_team, home_goals, away_goals, result,
                odds_data['b365_h'], odds_data['b365_d'], odds_data['b365_a'],
                odds_data['bw_h'], odds_data['bw_d'], odds_data['bw_a'],
                odds_data['iw_h'], odds_data['iw_d'], odds_data['iw_a'],
                odds_data['ps_h'], odds_data['ps_d'], odds_data['ps_a'],
                odds_data['wh_h'], odds_data['wh_d'], odds_data['wh_a'],
                odds_data['vc_h'], odds_data['vc_d'], odds_data['vc_a'],
                odds_data['avg_h'], odds_data['avg_d'], odds_data['avg_a'],
                odds_data['max_h'], odds_data['max_d'], odds_data['max_a'],
                stats['home_shots'], stats['away_shots'],
                stats['home_shots_target'], stats['away_shots_target'],
                stats['home_fouls'], stats['away_fouls'],
                stats['home_corners'], stats['away_corners'],
                stats['home_yellows'], stats['away_yellows'],
                stats['home_reds'], stats['away_reds']
            ))
            
            inserted_count += 1
            
        except Exception as e:
            print(f"  ⚠️  Row {idx}: {e}")
            skipped_count += 1
            continue
    
    conn.commit()
    cur.close()
    
    print(f"  ✅ Inserted/Updated: {inserted_count} matches")
    if skipped_count > 0:
        print(f"  ⚠️  Skipped: {skipped_count} rows")
    
    return inserted_count

def import_directory(directory_path):
    """Import all CSV files from a directory"""
    
    conn = psycopg2.connect(DATABASE_URL)
    
    # Find all CSV files
    csv_files = list(Path(directory_path).glob('*.csv'))
    
    if not csv_files:
        print(f"❌ No CSV files found in {directory_path}")
        return
    
    print(f"\n{'='*80}")
    print(f"Found {len(csv_files)} CSV files to import")
    print('='*80)
    
    total_inserted = 0
    
    for csv_file in sorted(csv_files):
        inserted = import_csv_file(str(csv_file), conn)
        total_inserted += inserted
    
    conn.close()
    
    print(f"\n{'='*80}")
    print(f"IMPORT COMPLETE")
    print('='*80)
    print(f"  Total matches inserted/updated: {total_inserted}")
    
    # Show summary statistics
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    
    cur.execute("""
        SELECT 
            COUNT(*) as matches,
            COUNT(DISTINCT league_name) as leagues,
            MIN(match_date) as earliest,
            MAX(match_date) as latest
        FROM historical_odds
    """)
    
    stats = cur.fetchone()
    
    print(f"\n  Database Summary:")
    print(f"    Total matches: {stats[0]:,}")
    print(f"    Leagues: {stats[1]}")
    print(f"    Date range: {stats[2]} → {stats[3]}")
    
    cur.close()
    conn.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python import_csv_historical_odds.py <directory_path>")
        print("Example: python import_csv_historical_odds.py attached_assets/")
        sys.exit(1)
    
    directory = sys.argv[1]
    
    if not os.path.exists(directory):
        print(f"❌ Directory not found: {directory}")
        sys.exit(1)
    
    import_directory(directory)
