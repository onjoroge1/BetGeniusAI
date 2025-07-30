"""
Historical Odds Integration System
Using The Odds API for horizon-aligned market snapshots (T-72h/T-120h)
Goal: Add market baselines and residual-on-market modeling for improved LogLoss/Brier/Top-2
"""

import os
import json
import requests
import psycopg2
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import time
from typing import Dict, List, Tuple, Optional
import hashlib

class OddsIntegrationSystem:
    """Complete odds integration system for BetGenius AI"""
    
    def __init__(self):
        self.conn = psycopg2.connect(os.environ['DATABASE_URL'])
        self.odds_api_key = os.environ.get('ODDS_API_KEY')
        self.api_base_url = "https://api.the-odds-api.com/v4"
        
        # League mapping: The Odds API sport keys to our league IDs
        self.league_mapping = {
            'soccer_epl': 39,           # Premier League
            'soccer_spain_la_liga': 140, # La Liga
            'soccer_italy_serie_a': 135, # Serie A
            'soccer_germany_bundesliga': 78, # Bundesliga
            'soccer_france_ligue_one': 61,   # Ligue 1
            'soccer_netherlands_eredivisie': 88, # Eredivisie
        }
        
        # Team name crosswalk for matching
        self.team_name_variations = {}
        
    def create_odds_tables(self):
        """Create database tables for odds storage"""
        
        print("CREATING ODDS INTEGRATION TABLES")
        print("=" * 40)
        
        cursor = self.conn.cursor()
        
        # League mapping table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS league_map (
            theodds_sport_key VARCHAR(64) PRIMARY KEY,
            league_id INT NOT NULL,
            league_name VARCHAR(128),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        
        # Team name crosswalk table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS team_name_xwalk (
            id SERIAL PRIMARY KEY,
            provider_name VARCHAR(128) NOT NULL,
            canonical_team_name VARCHAR(128) NOT NULL,
            league_id INT NOT NULL,
            season VARCHAR(16),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(provider_name, league_id, season)
        );
        """)
        
        # Time-stamped 3-way odds snapshots
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS odds_snapshots (
            match_id BIGINT,
            league_id INT,
            book_id VARCHAR(64),
            market VARCHAR(32),
            ts_snapshot TIMESTAMP,
            secs_to_kickoff INT,
            outcome CHAR(1) CHECK (outcome IN ('H','D','A')),
            odds_decimal DOUBLE PRECISION,
            implied_prob DOUBLE PRECISION,
            market_margin DOUBLE PRECISION,
            raw_data JSONB,
            PRIMARY KEY(match_id, book_id, ts_snapshot, outcome)
        );
        """)
        
        # Daily consensus per horizon window
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS odds_consensus (
            match_id BIGINT,
            horizon_hours INT,
            ts_effective TIMESTAMP,
            pH_cons DOUBLE PRECISION,
            pD_cons DOUBLE PRECISION,
            pA_cons DOUBLE PRECISION,
            dispH DOUBLE PRECISION,
            dispD DOUBLE PRECISION,
            dispA DOUBLE PRECISION,
            n_books INT,
            market_margin_avg DOUBLE PRECISION,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (match_id, horizon_hours)
        );
        """)
        
        # Populate league mapping
        for sport_key, league_id in self.league_mapping.items():
            cursor.execute("""
            INSERT INTO league_map (theodds_sport_key, league_id, league_name)
            VALUES (%s, %s, %s)
            ON CONFLICT (theodds_sport_key) DO NOTHING
            """, (sport_key, league_id, f'League {league_id}'))
        
        self.conn.commit()
        cursor.close()
        
        print("✅ Odds tables created successfully")
        print(f"✅ {len(self.league_mapping)} league mappings added")
    
    def fetch_odds_data(self, sport_key: str, date_from: str = None, date_to: str = None) -> List[Dict]:
        """Fetch odds data from The Odds API"""
        
        print(f"Fetching odds for {sport_key}...")
        
        # Try current odds first (historical might need premium plan)
        url = f"{self.api_base_url}/sports/{sport_key}/odds"
        
        params = {
            'api_key': self.odds_api_key,
            'regions': 'uk,eu,us',  # Major bookmakers
            'markets': 'h2h',       # Head-to-head (3-way including draw)
            'oddsFormat': 'decimal',
            'dateFormat': 'iso'
        }
        
        # First try current odds
        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            current_data = response.json()
            
            if current_data:
                print(f"✅ Fetched {len(current_data)} current matches for {sport_key}")
                
                # Log API usage
                remaining_requests = response.headers.get('x-requests-remaining', 'Unknown')
                print(f"API requests remaining: {remaining_requests}")
                
                return current_data
            
        except requests.exceptions.RequestException as e:
            print(f"Current odds failed: {e}")
        
        # Try historical endpoint as fallback
        if date_from:
            historical_url = f"{self.api_base_url}/historical/sports/{sport_key}/odds"
            params['date'] = date_from
        
            try:
                response = requests.get(historical_url, params=params)
                response.raise_for_status()
                
                data = response.json()
                print(f"✅ Fetched {len(data)} historical matches for {sport_key}")
                
                # Log API usage
                remaining_requests = response.headers.get('x-requests-remaining', 'Unknown')
                print(f"API requests remaining: {remaining_requests}")
                
                return data
                
            except requests.exceptions.RequestException as e:
                print(f"❌ Historical odds also failed for {sport_key}: {e}")
                return []
        
        return []
    
    def process_odds_data(self, odds_data: List[Dict], league_id: int) -> List[Dict]:
        """Process raw odds data into structured format"""
        
        processed_matches = []
        
        for match_data in odds_data:
            try:
                # Extract match info
                home_team = match_data.get('home_team', '')
                away_team = match_data.get('away_team', '')
                commence_time = datetime.fromisoformat(match_data['commence_time'].replace('Z', '+00:00'))
                
                # Find matching training match
                match_id = self.find_matching_training_match(
                    home_team, away_team, commence_time, league_id
                )
                
                if not match_id:
                    continue
                
                # Process bookmaker odds
                for bookmaker in match_data.get('bookmakers', []):
                    book_id = bookmaker['key']
                    last_update = datetime.fromisoformat(bookmaker['last_update'].replace('Z', '+00:00'))
                    
                    # Calculate seconds to kickoff
                    secs_to_kickoff = int((commence_time - last_update).total_seconds())
                    
                    # Find h2h market (3-way)
                    h2h_market = None
                    for market in bookmaker.get('markets', []):
                        if market['key'] == 'h2h':
                            h2h_market = market
                            break
                    
                    if not h2h_market:
                        continue
                    
                    # Extract odds for each outcome
                    odds_dict = {}
                    for outcome in h2h_market.get('outcomes', []):
                        outcome_name = outcome['name']
                        odds_decimal = float(outcome['price'])
                        
                        # Map outcome names to H/D/A
                        if outcome_name == home_team:
                            odds_dict['H'] = odds_decimal
                        elif outcome_name == away_team:
                            odds_dict['A'] = odds_decimal
                        elif outcome_name == 'Draw':
                            odds_dict['D'] = odds_decimal
                    
                    # Only process if we have all three outcomes
                    if len(odds_dict) == 3:
                        # Calculate implied probabilities and margin
                        implied_probs = {k: 1/v for k, v in odds_dict.items()}
                        total_prob = sum(implied_probs.values())
                        market_margin = total_prob - 1.0
                        
                        # Normalize probabilities (remove margin)
                        normalized_probs = {k: v/total_prob for k, v in implied_probs.values()}
                        
                        # Create snapshot entries
                        for outcome_key, odds_decimal in odds_dict.items():
                            processed_matches.append({
                                'match_id': match_id,
                                'league_id': league_id,
                                'book_id': book_id,
                                'market': 'h2h',
                                'ts_snapshot': last_update,
                                'secs_to_kickoff': secs_to_kickoff,
                                'outcome': outcome_key,
                                'odds_decimal': odds_decimal,
                                'implied_prob': normalized_probs[outcome_key],
                                'market_margin': market_margin,
                                'raw_data': json.dumps(bookmaker)
                            })
                
            except Exception as e:
                print(f"Error processing match: {e}")
                continue
        
        print(f"✅ Processed {len(processed_matches)} odds snapshots")
        return processed_matches
    
    def find_matching_training_match(self, home_team: str, away_team: str, 
                                   commence_time: datetime, league_id: int) -> Optional[int]:
        """Find matching training match by team names and date"""
        
        cursor = self.conn.cursor()
        
        # Query for matches on the same date (+/- 1 day tolerance)
        query = """
        SELECT match_id, home_team, away_team, match_date 
        FROM training_matches 
        WHERE league_id = %s 
        AND match_date BETWEEN %s AND %s
        """
        
        date_start = commence_time.date() - timedelta(days=1)
        date_end = commence_time.date() + timedelta(days=1)
        
        cursor.execute(query, (league_id, date_start, date_end))
        matches = cursor.fetchall()
        
        # Try exact name matching first
        for match_id, db_home, db_away, match_date in matches:
            if (self.normalize_team_name(home_team) == self.normalize_team_name(db_home) and
                self.normalize_team_name(away_team) == self.normalize_team_name(db_away)):
                cursor.close()
                return match_id
        
        # Try fuzzy matching with common variations
        for match_id, db_home, db_away, match_date in matches:
            if (self.fuzzy_team_match(home_team, db_home) and
                self.fuzzy_team_match(away_team, db_away)):
                cursor.close()
                return match_id
        
        cursor.close()
        return None
    
    def normalize_team_name(self, name: str) -> str:
        """Normalize team name for matching"""
        return name.lower().strip().replace('.', '').replace('-', ' ')
    
    def fuzzy_team_match(self, api_name: str, db_name: str) -> bool:
        """Check if team names match with common variations"""
        
        api_norm = self.normalize_team_name(api_name)
        db_norm = self.normalize_team_name(db_name)
        
        # Direct match
        if api_norm == db_norm:
            return True
        
        # Common variations
        variations = {
            'manchester city': ['man city', 'city'],
            'manchester united': ['man united', 'man utd'],
            'tottenham': ['tottenham hotspur', 'spurs'],
            'atletico madrid': ['atletico', 'atl madrid'],
            'real madrid': ['madrid'],
            'barcelona': ['barca'],
            'bayern munich': ['bayern', 'fc bayern'],
            'borussia dortmund': ['dortmund', 'bvb'],
            'paris saint germain': ['psg', 'paris sg'],
            'ac milan': ['milan'],
            'inter milan': ['inter', 'internazionale'],
            'juventus': ['juve']
        }
        
        # Check both directions
        for canonical, vars_list in variations.items():
            if canonical in [api_norm, db_norm]:
                other_name = db_norm if canonical == api_norm else api_norm
                if any(var in other_name for var in vars_list):
                    return True
        
        return False
    
    def store_odds_snapshots(self, snapshots: List[Dict]):
        """Store odds snapshots in database"""
        
        if not snapshots:
            return
        
        cursor = self.conn.cursor()
        
        insert_query = """
        INSERT INTO odds_snapshots 
        (match_id, league_id, book_id, market, ts_snapshot, secs_to_kickoff, 
         outcome, odds_decimal, implied_prob, market_margin, raw_data)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (match_id, book_id, ts_snapshot, outcome) DO NOTHING
        """
        
        data_tuples = [
            (s['match_id'], s['league_id'], s['book_id'], s['market'], 
             s['ts_snapshot'], s['secs_to_kickoff'], s['outcome'], 
             s['odds_decimal'], s['implied_prob'], s['market_margin'], s['raw_data'])
            for s in snapshots
        ]
        
        cursor.executemany(insert_query, data_tuples)
        self.conn.commit()
        cursor.close()
        
        print(f"✅ Stored {len(snapshots)} odds snapshots")
    
    def compute_odds_consensus(self, horizon_hours: int = 72):
        """Compute odds consensus for specified horizon"""
        
        print(f"Computing odds consensus for T-{horizon_hours}h horizon...")
        
        cursor = self.conn.cursor()
        
        # Get all matches with odds data
        cursor.execute("""
        SELECT DISTINCT match_id, league_id 
        FROM odds_snapshots 
        WHERE match_id IS NOT NULL
        """)
        
        matches = cursor.fetchall()
        
        consensus_data = []
        
        for match_id, league_id in matches:
            # Find best snapshot for this horizon
            cursor.execute("""
            SELECT ts_snapshot, book_id, outcome, implied_prob, market_margin
            FROM odds_snapshots 
            WHERE match_id = %s 
            AND secs_to_kickoff >= %s
            ORDER BY secs_to_kickoff ASC
            """, (match_id, horizon_hours * 3600))
            
            horizon_data = cursor.fetchall()
            
            if not horizon_data:
                # Fallback to nearest earlier snapshot
                cursor.execute("""
                SELECT ts_snapshot, book_id, outcome, implied_prob, market_margin
                FROM odds_snapshots 
                WHERE match_id = %s 
                ORDER BY secs_to_kickoff DESC
                LIMIT 100
                """, (match_id,))
                horizon_data = cursor.fetchall()
            
            if not horizon_data:
                continue
            
            # Group by outcome and compute consensus
            outcomes_data = {'H': [], 'D': [], 'A': []}
            margins = []
            books = set()
            ts_effective = None
            
            for ts_snapshot, book_id, outcome, prob, margin in horizon_data:
                outcomes_data[outcome].append(prob)
                margins.append(margin)
                books.add(book_id)
                if not ts_effective:
                    ts_effective = ts_snapshot
            
            # Compute consensus probabilities (median)
            if all(len(outcomes_data[outcome]) > 0 for outcome in ['H', 'D', 'A']):
                pH_cons = np.median(outcomes_data['H'])
                pD_cons = np.median(outcomes_data['D'])
                pA_cons = np.median(outcomes_data['A'])
                
                # Renormalize to sum to 1
                total = pH_cons + pD_cons + pA_cons
                pH_cons /= total
                pD_cons /= total
                pA_cons /= total
                
                # Compute dispersion (IQR)
                dispH = np.percentile(outcomes_data['H'], 75) - np.percentile(outcomes_data['H'], 25)
                dispD = np.percentile(outcomes_data['D'], 75) - np.percentile(outcomes_data['D'], 25)
                dispA = np.percentile(outcomes_data['A'], 75) - np.percentile(outcomes_data['A'], 25)
                
                consensus_data.append({
                    'match_id': match_id,
                    'horizon_hours': horizon_hours,
                    'ts_effective': ts_effective,
                    'pH_cons': pH_cons,
                    'pD_cons': pD_cons,
                    'pA_cons': pA_cons,
                    'dispH': dispH,
                    'dispD': dispD,
                    'dispA': dispA,
                    'n_books': len(books),
                    'market_margin_avg': np.mean(margins)
                })
        
        # Store consensus data
        if consensus_data:
            insert_query = """
            INSERT INTO odds_consensus 
            (match_id, horizon_hours, ts_effective, pH_cons, pD_cons, pA_cons,
             dispH, dispD, dispA, n_books, market_margin_avg)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (match_id, horizon_hours) DO UPDATE SET
            ts_effective = EXCLUDED.ts_effective,
            pH_cons = EXCLUDED.pH_cons,
            pD_cons = EXCLUDED.pD_cons,
            pA_cons = EXCLUDED.pA_cons,
            dispH = EXCLUDED.dispH,
            dispD = EXCLUDED.dispD,
            dispA = EXCLUDED.dispA,
            n_books = EXCLUDED.n_books,
            market_margin_avg = EXCLUDED.market_margin_avg
            """
            
            data_tuples = [
                (c['match_id'], c['horizon_hours'], c['ts_effective'], 
                 c['pH_cons'], c['pD_cons'], c['pA_cons'],
                 c['dispH'], c['dispD'], c['dispA'], 
                 c['n_books'], c['market_margin_avg'])
                for c in consensus_data
            ]
            
            cursor.executemany(insert_query, data_tuples)
            self.conn.commit()
        
        cursor.close()
        
        print(f"✅ Computed consensus for {len(consensus_data)} matches")
        return len(consensus_data)
    
    def fetch_current_odds_for_demo(self):
        """Fetch current odds for demonstration and table setup"""
        
        print("FETCHING CURRENT ODDS FOR DEMO")
        print("=" * 35)
        
        # Create tables first
        self.create_odds_tables()
        
        total_processed = 0
        
        for sport_key, league_id in self.league_mapping.items():
            print(f"\nFetching current odds for {sport_key} (League {league_id})...")
            
            # Fetch current odds (no date parameter)
            odds_data = self.fetch_odds_data(sport_key)
            
            if odds_data:
                # Process and store current odds
                processed_snapshots = self.process_odds_data(odds_data, league_id)
                self.store_odds_snapshots(processed_snapshots)
                total_processed += len(processed_snapshots)
                
                # Rate limiting
                time.sleep(1)  # Respect API limits
            
            # Stop after EPL to preserve API calls
            if sport_key == 'soccer_epl':
                break
        
        # Compute consensus for T-72h horizon
        consensus_count = self.compute_odds_consensus(72)
        
        print(f"\nCURRENT ODDS DEMO COMPLETE")
        print("=" * 30)
        print(f"✅ Total odds snapshots: {total_processed}")
        print(f"✅ Consensus computed: {consensus_count} matches")
        
        return {
            'total_snapshots': total_processed,
            'consensus_matches': consensus_count,
            'leagues_processed': 1  # Just EPL for demo
        }
    
    def backfill_historical_odds(self, days_back: int = 90):
        """Backfill historical odds for training matches"""
        
        print("STARTING HISTORICAL ODDS BACKFILL")
        print("=" * 40)
        print(f"Backfilling last {days_back} days of odds data")
        
        # Create tables first
        self.create_odds_tables()
        
        total_processed = 0
        
        for sport_key, league_id in self.league_mapping.items():
            print(f"\nProcessing {sport_key} (League {league_id})...")
            
            # Calculate date range
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days_back)
            
            # Fetch odds data
            odds_data = self.fetch_odds_data(
                sport_key, 
                start_date.strftime('%Y-%m-%d'),
                end_date.strftime('%Y-%m-%d')
            )
            
            if odds_data:
                # Process and store
                processed_snapshots = self.process_odds_data(odds_data, league_id)
                self.store_odds_snapshots(processed_snapshots)
                total_processed += len(processed_snapshots)
                
                # Rate limiting
                time.sleep(1)  # Respect API limits
        
        # Compute consensus for T-72h horizon
        consensus_count = self.compute_odds_consensus(72)
        
        print(f"\nBACKFILL COMPLETE")
        print("=" * 20)
        print(f"✅ Total odds snapshots: {total_processed}")
        print(f"✅ Consensus computed: {consensus_count} matches")
        
        return {
            'total_snapshots': total_processed,
            'consensus_matches': consensus_count,
            'leagues_processed': len(self.league_mapping)
        }
    
    def get_odds_statistics(self) -> Dict:
        """Get statistics about stored odds data"""
        
        cursor = self.conn.cursor()
        
        # Snapshots statistics
        cursor.execute("""
        SELECT 
            COUNT(*) as total_snapshots,
            COUNT(DISTINCT match_id) as unique_matches,
            COUNT(DISTINCT book_id) as unique_books,
            MIN(ts_snapshot) as earliest_snapshot,
            MAX(ts_snapshot) as latest_snapshot
        FROM odds_snapshots
        """)
        
        snapshot_stats = cursor.fetchone()
        
        # Consensus statistics  
        cursor.execute("""
        SELECT 
            horizon_hours,
            COUNT(*) as matches_count,
            AVG(n_books) as avg_books_per_match,
            AVG(market_margin_avg) as avg_market_margin
        FROM odds_consensus
        GROUP BY horizon_hours
        ORDER BY horizon_hours
        """)
        
        consensus_stats = cursor.fetchall()
        
        # League breakdown
        cursor.execute("""
        SELECT 
            l.league_id,
            l.theodds_sport_key,
            COUNT(DISTINCT o.match_id) as matches_with_odds
        FROM league_map l
        LEFT JOIN odds_snapshots o ON l.league_id = o.league_id
        GROUP BY l.league_id, l.theodds_sport_key
        ORDER BY matches_with_odds DESC
        """)
        
        league_stats = cursor.fetchall()
        
        cursor.close()
        
        return {
            'snapshots': {
                'total': snapshot_stats[0],
                'unique_matches': snapshot_stats[1],
                'unique_books': snapshot_stats[2],
                'date_range': (snapshot_stats[3], snapshot_stats[4])
            },
            'consensus': [
                {
                    'horizon_hours': row[0],
                    'matches': row[1],
                    'avg_books': row[2],
                    'avg_margin': row[3]
                } for row in consensus_stats
            ],
            'leagues': [
                {
                    'league_id': row[0],
                    'sport_key': row[1],
                    'matches_with_odds': row[2]
                } for row in league_stats
            ]
        }

def main():
    """Run odds integration system"""
    
    print("ODDS INTEGRATION SYSTEM")
    print("=" * 30)
    print("Implementing The Odds API integration for market-aligned baselines")
    
    odds_system = OddsIntegrationSystem()
    
    try:
        # First try current odds for demo (historical needs premium plan)
        results = odds_system.fetch_current_odds_for_demo()
        
        # Get statistics
        stats = odds_system.get_odds_statistics()
        
        print(f"\nODDS INTEGRATION RESULTS")
        print("=" * 30)
        print(f"Snapshots stored: {stats['snapshots']['total']}")
        print(f"Matches with odds: {stats['snapshots']['unique_matches']}")
        print(f"Unique bookmakers: {stats['snapshots']['unique_books']}")
        print(f"Date range: {stats['snapshots']['date_range'][0]} to {stats['snapshots']['date_range'][1]}")
        
        for consensus in stats['consensus']:
            print(f"T-{consensus['horizon_hours']}h consensus: {consensus['matches']} matches, {consensus['avg_books']:.1f} avg books")
        
        print(f"\nLeague coverage:")
        for league in stats['leagues']:
            print(f"  {league['sport_key']}: {league['matches_with_odds']} matches")
        
        return results
        
    finally:
        odds_system.conn.close()

if __name__ == "__main__":
    main()