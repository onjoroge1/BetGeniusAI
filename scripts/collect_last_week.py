#!/usr/bin/env python3
"""
Manual Data Collection Script - Last 7 Days
Collects finished matches from the past week and adds them to historical_odds table

Usage:
    python scripts/collect_last_week.py [--days 7] [--leagues 39,140,135]
    
Examples:
    # Collect last 7 days from all Tier 1 leagues
    python scripts/collect_last_week.py
    
    # Collect last 14 days
    python scripts/collect_last_week.py --days 14
    
    # Collect from specific leagues only
    python scripts/collect_last_week.py --leagues 39,140,135
"""

import os
import sys
import argparse
import psycopg2
import requests
from datetime import datetime, timedelta
from typing import List, Dict, Optional

# Configuration
DATABASE_URL = os.getenv('DATABASE_URL')
RAPIDAPI_KEY = os.getenv('RAPIDAPI_KEY')

# Tier 1 Leagues (Priority for V2 training)
TIER1_LEAGUES = [
    39,   # Premier League
    140,  # La Liga
    135,  # Serie A
    78,   # Bundesliga
    61,   # Ligue 1
    94,   # Primeira Liga
    203,  # Super Lig
    88,   # Eredivisie
]

# API-Football endpoints
RAPIDAPI_HOST = "api-football-v1.p.rapidapi.com"
RAPIDAPI_BASE_URL = f"https://{RAPIDAPI_HOST}/v3"


class WeeklyDataCollector:
    def __init__(self, database_url: str, rapidapi_key: str):
        self.database_url = database_url
        self.rapidapi_key = rapidapi_key
        self.headers = {
            "X-RapidAPI-Key": rapidapi_key,
            "X-RapidAPI-Host": RAPIDAPI_HOST
        }
        
        self.stats = {
            'leagues_processed': 0,
            'matches_found': 0,
            'matches_with_odds': 0,
            'matches_inserted': 0,
            'matches_skipped': 0,
            'errors': 0
        }
    
    def fetch_finished_matches(self, league_id: int, date_from: str, date_to: str) -> List[Dict]:
        """Fetch finished matches for a league in date range"""
        url = f"{RAPIDAPI_BASE_URL}/fixtures"
        params = {
            'league': league_id,
            'season': 2024,  # Current season
            'status': 'FT',  # Finished matches only
            'from': date_from,
            'to': date_to
        }
        
        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data.get('response'):
                return data['response']
            return []
            
        except Exception as e:
            print(f"❌ Error fetching matches for league {league_id}: {e}")
            self.stats['errors'] += 1
            return []
    
    def fetch_odds_for_match(self, fixture_id: int) -> Optional[Dict]:
        """Fetch odds for a specific match"""
        url = f"{RAPIDAPI_BASE_URL}/odds"
        params = {
            'fixture': fixture_id,
            'bookmaker': 8,  # Bet365
        }
        
        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data.get('response') and len(data['response']) > 0:
                return data['response'][0]
            return None
            
        except Exception as e:
            print(f"⚠️  Error fetching odds for fixture {fixture_id}: {e}")
            return None
    
    def extract_h2h_odds(self, odds_data: Dict) -> Optional[Dict]:
        """Extract H/D/A odds from API response"""
        if not odds_data or 'bookmakers' not in odds_data:
            return None
        
        for bookmaker in odds_data['bookmakers']:
            for bet in bookmaker.get('bets', []):
                if bet['name'] == 'Match Winner':
                    values = bet.get('values', [])
                    if len(values) >= 3:
                        return {
                            'home': float(values[0]['odd']),
                            'draw': float(values[1]['odd']),
                            'away': float(values[2]['odd']),
                            'bookmaker': bookmaker['name']
                        }
        return None
    
    def insert_to_historical_odds(self, conn, match_data: Dict, odds: Dict) -> bool:
        """Insert match into historical_odds table"""
        cursor = conn.cursor()
        
        try:
            # Extract match details
            fixture = match_data['fixture']
            teams = match_data['teams']
            league = match_data['league']
            goals = match_data['goals']
            
            # Determine outcome
            if goals['home'] > goals['away']:
                outcome = 'H'
            elif goals['home'] < goals['away']:
                outcome = 'A'
            else:
                outcome = 'D'
            
            # Check if already exists
            cursor.execute(
                "SELECT 1 FROM historical_odds WHERE fixture_id = %s",
                (fixture['id'],)
            )
            if cursor.fetchone():
                print(f"   ⏭️  Match {fixture['id']} already in database")
                self.stats['matches_skipped'] += 1
                return False
            
            # Insert into historical_odds
            insert_query = """
                INSERT INTO historical_odds (
                    fixture_id, league_id, league_name, season,
                    match_date, home_team, away_team,
                    home_goals, away_goals, actual_outcome,
                    h_odds_consensus, d_odds_consensus, a_odds_consensus,
                    bookmaker_count, created_at
                ) VALUES (
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, NOW()
                )
            """
            
            cursor.execute(insert_query, (
                fixture['id'],
                league['id'],
                league['name'],
                league['season'],
                fixture['date'],
                teams['home']['name'],
                teams['away']['name'],
                goals['home'],
                goals['away'],
                outcome,
                odds['home'],
                odds['draw'],
                odds['away'],
                1  # Single bookmaker for now
            ))
            
            conn.commit()
            print(f"   ✅ Inserted: {teams['home']['name']} vs {teams['away']['name']} ({outcome})")
            self.stats['matches_inserted'] += 1
            return True
            
        except Exception as e:
            print(f"   ❌ Error inserting match: {e}")
            conn.rollback()
            self.stats['errors'] += 1
            return False
    
    def collect_league_week(self, league_id: int, date_from: str, date_to: str):
        """Collect all finished matches for a league in the past week"""
        print(f"\n📊 Processing League ID: {league_id}")
        print(f"   Date range: {date_from} to {date_to}")
        
        # Fetch finished matches
        matches = self.fetch_finished_matches(league_id, date_from, date_to)
        
        if not matches:
            print(f"   ℹ️  No finished matches found")
            return
        
        print(f"   Found {len(matches)} finished matches")
        self.stats['matches_found'] += len(matches)
        
        # Connect to database
        conn = psycopg2.connect(self.database_url)
        
        try:
            for match in matches:
                fixture = match['fixture']
                teams = match['teams']
                
                print(f"\n   🏟️  {teams['home']['name']} vs {teams['away']['name']}")
                print(f"      Fixture ID: {fixture['id']}, Date: {fixture['date']}")
                
                # Fetch odds
                odds_data = self.fetch_odds_for_match(fixture['id'])
                
                if not odds_data:
                    print(f"      ⚠️  No odds data available - skipping")
                    self.stats['matches_skipped'] += 1
                    continue
                
                # Extract H/D/A odds
                odds = self.extract_h2h_odds(odds_data)
                
                if not odds:
                    print(f"      ⚠️  Could not extract H/D/A odds - skipping")
                    self.stats['matches_skipped'] += 1
                    continue
                
                print(f"      📊 Odds: H={odds['home']:.2f}, D={odds['draw']:.2f}, A={odds['away']:.2f}")
                self.stats['matches_with_odds'] += 1
                
                # Insert to database
                self.insert_to_historical_odds(conn, match, odds)
                
        finally:
            conn.close()
        
        self.stats['leagues_processed'] += 1
    
    def run(self, leagues: List[int], days: int = 7):
        """Run collection for specified leagues and days"""
        print("\n" + "="*60)
        print("📥 MANUAL DATA COLLECTION - LAST WEEK")
        print("="*60)
        
        # Calculate date range
        today = datetime.now()
        date_to = today.strftime('%Y-%m-%d')
        date_from = (today - timedelta(days=days)).strftime('%Y-%m-%d')
        
        print(f"\n📅 Date Range: {date_from} to {date_to} ({days} days)")
        print(f"🎯 Leagues: {len(leagues)} leagues")
        print(f"🗄️  Database: {self.database_url[:30]}...")
        print(f"🔑 API Key: {self.rapidapi_key[:10]}...")
        
        # Process each league
        for league_id in leagues:
            self.collect_league_week(league_id, date_from, date_to)
        
        # Print summary
        self.print_summary()
    
    def print_summary(self):
        """Print collection summary"""
        print("\n" + "="*60)
        print("📊 COLLECTION SUMMARY")
        print("="*60)
        print(f"Leagues processed:     {self.stats['leagues_processed']}")
        print(f"Matches found:         {self.stats['matches_found']}")
        print(f"Matches with odds:     {self.stats['matches_with_odds']}")
        print(f"Matches inserted:      {self.stats['matches_inserted']}")
        print(f"Matches skipped:       {self.stats['matches_skipped']}")
        print(f"Errors:                {self.stats['errors']}")
        print("="*60)
        
        if self.stats['matches_inserted'] > 0:
            print(f"\n✅ SUCCESS: Added {self.stats['matches_inserted']} new matches to historical_odds")
            print(f"💡 Next step: Run model retraining with updated dataset")
        else:
            print(f"\n⚠️  No new matches added (all may already be in database)")
        print()


def main():
    parser = argparse.ArgumentParser(description='Collect last week of match data for training')
    parser.add_argument(
        '--days',
        type=int,
        default=7,
        help='Number of days to look back (default: 7)'
    )
    parser.add_argument(
        '--leagues',
        type=str,
        default=None,
        help='Comma-separated league IDs (default: all Tier 1 leagues)'
    )
    
    args = parser.parse_args()
    
    # Validate environment variables
    if not DATABASE_URL:
        print("❌ ERROR: DATABASE_URL environment variable not set")
        sys.exit(1)
    
    if not RAPIDAPI_KEY:
        print("❌ ERROR: RAPIDAPI_KEY environment variable not set")
        sys.exit(1)
    
    # Parse leagues
    if args.leagues:
        leagues = [int(lid.strip()) for lid in args.leagues.split(',')]
    else:
        leagues = TIER1_LEAGUES
    
    # Run collection
    collector = WeeklyDataCollector(DATABASE_URL, RAPIDAPI_KEY)
    collector.run(leagues, args.days)


if __name__ == '__main__':
    main()
