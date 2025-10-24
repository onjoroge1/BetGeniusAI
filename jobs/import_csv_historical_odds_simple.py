"""
Simple CSV importer for historical_odds table from football-data.co.uk files
"""

import os
import sys
import pandas as pd
import psycopg2
from datetime import datetime
from pathlib import Path

DATABASE_URL = os.getenv('DATABASE_URL')

LEAGUE_MAPPING = {
    'SC0': 'Scottish Premiership', 'SC1': 'Scottish Championship', 'SC2': 'Scottish League One', 'SC3': 'Scottish League Two',
    'E0': 'Premier League', 'E1': 'Championship', 'E2': 'League One', 'E3': 'League Two',
    'SP1': 'La Liga', 'SP2': 'La Liga 2', 'I1': 'Serie A', 'I2': 'Serie B',
    'D1': 'Bundesliga', 'D2': 'Bundesliga 2', 'F1': 'Ligue 1', 'F2': 'Ligue 2',
    'N1': 'Eredivisie', 'B1': 'Jupiler League', 'P1': 'Primeira Liga', 'T1': 'Super Lig',
}

def parse_date(s):
    try:
        return datetime.strptime(s, '%d/%m/%Y')
    except:
        try:
            return datetime.strptime(s, '%d/%m/%y')
        except:
            return None

def get_season(date):
    return date.year if date.month >= 8 else date.year - 1

def safe_float(v):
    try:
        return float(v) if pd.notna(v) else None
    except:
        return None

def safe_int(v):
    try:
        return int(v) if pd.notna(v) else None
    except:
        return None

def import_csv(csv_path):
    print(f"\n📁 {Path(csv_path).name}")
    
    df = pd.read_csv(csv_path)
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    
    inserted = 0
    for _, row in df.iterrows():
        try:
            date = parse_date(row['Date'])
            if not date or pd.isna(row['HomeTeam']) or pd.isna(row['AwayTeam']):
                continue
            
            league_code = row['Div']
            cur.execute("""
                INSERT INTO historical_odds (
                    match_date, season, league, league_name,
                    home_team, away_team, home_goals, away_goals, result,
                    b365_h, b365_d, b365_a, bw_h, bw_d, bw_a,
                    iw_h, iw_d, iw_a, ps_h, ps_d, ps_a,
                    wh_h, wh_d, wh_a, vc_h, vc_d, vc_a,
                    avg_h, avg_d, avg_a, max_h, max_d, max_a,
                    home_shots, away_shots, home_shots_target, away_shots_target,
                    home_fouls, away_fouls, home_corners, away_corners,
                    home_yellows, away_yellows, home_reds, away_reds
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                date, str(get_season(date)), league_code, LEAGUE_MAPPING.get(league_code, league_code),
                str(row['HomeTeam']).strip(), str(row['AwayTeam']).strip(),
                safe_int(row.get('FTHG')), safe_int(row.get('FTAG')), row.get('FTR'),
                safe_float(row.get('B365H')), safe_float(row.get('B365D')), safe_float(row.get('B365A')),
                safe_float(row.get('BWH')), safe_float(row.get('BWD')), safe_float(row.get('BWA')),
                safe_float(row.get('IWH')), safe_float(row.get('IWD')), safe_float(row.get('IWA')),
                safe_float(row.get('PSH')), safe_float(row.get('PSD')), safe_float(row.get('PSA')),
                safe_float(row.get('WHH')), safe_float(row.get('WHD')), safe_float(row.get('WHA')),
                safe_float(row.get('VCH')), safe_float(row.get('VCD')), safe_float(row.get('VCA')),
                safe_float(row.get('AvgH')), safe_float(row.get('AvgD')), safe_float(row.get('AvgA')),
                safe_float(row.get('MaxH')), safe_float(row.get('MaxD')), safe_float(row.get('MaxA')),
                safe_int(row.get('HS')), safe_int(row.get('AS')), safe_int(row.get('HST')), safe_int(row.get('AST')),
                safe_int(row.get('HF')), safe_int(row.get('AF')), safe_int(row.get('HC')), safe_int(row.get('AC')),
                safe_int(row.get('HY')), safe_int(row.get('AY')), safe_int(row.get('HR')), safe_int(row.get('AR'))
            ))
            inserted += 1
        except Exception as e:
            continue
    
    conn.commit()
    cur.close()
    conn.close()
    print(f"   ✅ Inserted {inserted} matches")
    return inserted

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python import_csv_historical_odds_simple.py <directory>")
        sys.exit(1)
    
    directory = sys.argv[1]
    csv_files = list(Path(directory).glob('*.csv'))
    
    print(f"\n{'='*60}")
    print(f"Found {len(csv_files)} CSV files")
    print('='*60)
    
    total = 0
    for csv in sorted(csv_files):
        total += import_csv(str(csv))
    
    print(f"\n{'='*60}")
    print(f"✅ TOTAL: {total} matches imported")
    print('='*60)
