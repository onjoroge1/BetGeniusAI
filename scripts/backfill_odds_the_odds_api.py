#!/usr/bin/env python3
"""
Backfill Historical Odds from The Odds API

Uses The Odds API's historical endpoint to backfill pre-match odds
for training matches that lack odds data.

The Odds API provides historical snapshots dating back to June 2020.

Usage:
    python scripts/backfill_odds_the_odds_api.py --days-back 60 --limit 10 --dry-run
    python scripts/backfill_odds_the_odds_api.py --days-back 180 --limit 500
"""

import os
import sys
import argparse
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional
import requests
import time
import psycopg2

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class TheOddsAPIBackfiller:
    """Backfill historical odds using The Odds API"""
    
    # Map our league IDs to The Odds API sport keys
    LEAGUE_MAPPING = {
        # Top 5 European Leagues
        39: 'soccer_epl',              # Premier League
        140: 'soccer_spain_la_liga',   # La Liga
        135: 'soccer_italy_serie_a',   # Serie A
        78: 'soccer_germany_bundesliga',  # Bundesliga
        61: 'soccer_france_ligue_one', # Ligue 1
        
        # Other Major Leagues
        88: 'soccer_germany_bundesliga2',  # Bundesliga 2
        94: 'soccer_portugal_primeira_liga',  # Primeira Liga
        203: 'soccer_turkey_super_league',  # Süper Lig
        262: 'soccer_brazil_campeonato',    # Brasileirão
        
        # Additional European Leagues (887 matches available!)
        2: 'soccer_uefa_champs_league',    # UEFA Champions League (269 matches)
        119: 'soccer_denmark_superliga',   # Superliga (193 matches)
        207: 'soccer_switzerland_superleague',  # Swiss Super League (230 matches)
        218: 'soccer_austria_bundesliga',  # Austrian Bundesliga (195 matches)
    }
    
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.api_key = os.getenv('ODDS_API_KEY')
        if not self.api_key:
            raise ValueError("ODDS_API_KEY not found in environment")
        
        self.database_url = os.getenv('DATABASE_URL')
        if not self.database_url:
            raise ValueError("DATABASE_URL not found in environment")
        
        self.base_url = "https://api.the-odds-api.com/v4"
        logger.info(f"Initialized TheOddsAPIBackfiller (dry_run={dry_run})")
    
    def get_training_matches_needing_odds(self, days_back: int, limit: int) -> List[Dict]:
        """Find training matches from recent history that need odds"""
        
        conn = psycopg2.connect(self.database_url)
        cursor = conn.cursor()
        
        # Look for matches from last N days that have no odds_snapshots
        start_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')
        
        query = """
            SELECT DISTINCT
                tm.match_id,
                tm.match_date,
                tm.home_team,
                tm.away_team,
                tm.league_id,
                tm.outcome,
                lm.league_name,
                COALESCE(f.kickoff_at, tm.match_date::timestamp) as kickoff_at
            FROM training_matches tm
            LEFT JOIN league_map lm ON tm.league_id = lm.league_id
            LEFT JOIN fixtures f ON tm.match_id = f.match_id
            LEFT JOIN odds_snapshots os ON tm.match_id = os.match_id
            WHERE tm.match_date >= %s
              AND tm.outcome IN ('H', 'D', 'A', 'Home', 'Draw', 'Away')
              AND os.match_id IS NULL
              AND tm.league_id IN (39, 140, 135, 78, 61, 88, 94, 203, 262, 2, 119, 207, 218)
            ORDER BY tm.match_date DESC
            LIMIT %s
        """
        
        cursor.execute(query, (start_date, limit))
        matches = cursor.fetchall()
        
        result = []
        for row in matches:
            result.append({
                'match_id': row[0],
                'match_date': row[1],
                'home_team': row[2],
                'away_team': row[3],
                'league_id': row[4],
                'outcome': row[5],
                'league_name': row[6],
                'kickoff_at': row[7],
                'sport_key': self.LEAGUE_MAPPING.get(row[4], 'unknown')
            })
        
        cursor.close()
        conn.close()
        
        logger.info(f"Found {len(result)} matches needing odds")
        return result
    
    def fetch_historical_odds(self, match_date: datetime, sport_key: str) -> Optional[Dict]:
        """Fetch historical odds from The Odds API for a specific date"""
        
        if sport_key == 'unknown':
            logger.warning(f"Unknown sport key, skipping")
            return None
        
        # The Odds API expects ISO format date (24h before match for pre-match odds)
        query_date = (match_date - timedelta(hours=24)).strftime('%Y-%m-%dT%H:%M:%SZ')
        
        url = f"{self.base_url}/historical/sports/{sport_key}/odds"
        params = {
            'apiKey': self.api_key,
            'regions': 'eu,uk',
            'markets': 'h2h',
            'oddsFormat': 'decimal',
            'date': query_date
        }
        
        try:
            response = requests.get(url, params=params, timeout=15)
            
            if response.status_code == 200:
                data = response.json()
                return data
            
            elif response.status_code == 429:
                logger.warning("Rate limited, waiting 60s...")
                time.sleep(60)
                return self.fetch_historical_odds(match_date, sport_key)
            
            else:
                logger.error(f"API returned {response.status_code}: {response.text[:200]}")
                return None
                
        except Exception as e:
            logger.error(f"Error fetching odds: {e}")
            return None
    
    def find_matching_fixture(self, api_data: Dict, home_team: str, away_team: str, match_date: datetime) -> Optional[Dict]:
        """Find fixture in API response that matches our match"""
        
        fixtures = api_data.get('data', [])
        
        # Normalize team names for matching
        def normalize(name: str) -> str:
            return name.lower().replace(' ', '').replace('-', '')
        
        home_norm = normalize(home_team)
        away_norm = normalize(away_team)
        
        for fixture in fixtures:
            api_home = normalize(fixture.get('home_team', ''))
            api_away = normalize(fixture.get('away_team', ''))
            
            # Check if teams match
            if api_home in home_norm or home_norm in api_home:
                if api_away in away_norm or away_norm in api_away:
                    return fixture
        
        return None
    
    def insert_odds_snapshots(self, match_id: int, league_id: int, kickoff_at: datetime, fixture_data: Dict) -> int:
        """Insert odds snapshots from fixture data"""
        
        bookmakers = fixture_data.get('bookmakers', [])
        if not bookmakers:
            return 0
        
        if self.dry_run:
            logger.info(f"   [DRY RUN] Would insert {len(bookmakers)} bookmakers x 3 outcomes = {len(bookmakers) * 3} rows")
            return len(bookmakers) * 3
        
        conn = psycopg2.connect(self.database_url)
        conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
        cursor = conn.cursor()
        
        inserted = 0
        
        # Set snapshot time 24h before kickoff
        ts_snapshot = kickoff_at - timedelta(hours=24)
        secs_to_kickoff = 24 * 3600
        
        for bookmaker in bookmakers:
            book_id = bookmaker.get('key', 'unknown')
            
            markets = bookmaker.get('markets', [])
            for market in markets:
                if market.get('key') != 'h2h':
                    continue
                
                outcomes = market.get('outcomes', [])
                
                # Extract odds for Home/Draw/Away
                odds_map = {}
                for outcome in outcomes:
                    name = outcome.get('name', '')
                    price = outcome.get('price', 0)
                    
                    if 'draw' in name.lower():
                        odds_map['D'] = price
                    elif name == fixture_data.get('home_team'):
                        odds_map['H'] = price
                    elif name == fixture_data.get('away_team'):
                        odds_map['A'] = price
                
                # Calculate market margin
                if len(odds_map) == 3:
                    ph = 1.0 / odds_map['H'] if odds_map['H'] > 0 else 0
                    pd = 1.0 / odds_map['D'] if odds_map['D'] > 0 else 0
                    pa = 1.0 / odds_map['A'] if odds_map['A'] > 0 else 0
                    market_margin = (ph + pd + pa) - 1.0
                    
                    # Insert all three outcomes
                    for outcome_code, decimal_odds in odds_map.items():
                        implied_prob = 1.0 / decimal_odds if decimal_odds > 0 else 0
                        
                        try:
                            cursor.execute("""
                                INSERT INTO odds_snapshots 
                                (match_id, league_id, book_id, market, outcome, 
                                 odds_decimal, implied_prob, market_margin, 
                                 ts_snapshot, secs_to_kickoff, created_at, source)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), 'theodds')
                                ON CONFLICT (match_id, book_id, market, outcome) 
                                DO UPDATE SET
                                    odds_decimal = EXCLUDED.odds_decimal,
                                    implied_prob = EXCLUDED.implied_prob,
                                    market_margin = EXCLUDED.market_margin,
                                    ts_snapshot = EXCLUDED.ts_snapshot,
                                    secs_to_kickoff = EXCLUDED.secs_to_kickoff
                            """, (
                                match_id,
                                league_id,
                                book_id,
                                'h2h',
                                outcome_code,
                                decimal_odds,
                                implied_prob,
                                market_margin,
                                ts_snapshot,
                                secs_to_kickoff
                            ))
                            inserted += cursor.rowcount
                        except Exception as e:
                            logger.error(f"Error inserting odds: {e}")
                            continue
        
        # No need to commit with autocommit mode
        cursor.close()
        conn.close()
        
        return inserted
    
    def run_backfill(self, days_back: int, limit: int):
        """Main backfill process"""
        
        logger.info("="*80)
        logger.info("THE ODDS API HISTORICAL BACKFILL")
        logger.info(f"Days back: {days_back}")
        logger.info(f"Limit: {limit} matches")
        logger.info(f"Dry run: {self.dry_run}")
        logger.info("="*80)
        
        # Get matches needing odds
        matches = self.get_training_matches_needing_odds(days_back, limit)
        
        if not matches:
            logger.info("✅ No matches found needing backfill")
            return
        
        logger.info(f"\n📋 Processing {len(matches)} matches...\n")
        
        success_count = 0
        failed_count = 0
        skipped_count = 0
        total_snapshots = 0
        
        for i, match in enumerate(matches, 1):
            logger.info(f"[{i}/{len(matches)}] {match['home_team']} vs {match['away_team']}")
            logger.info(f"   Date: {match['match_date']} | League: {match['league_name']} | Outcome: {match['outcome']}")
            
            # Fetch historical odds
            api_data = self.fetch_historical_odds(match['kickoff_at'], match['sport_key'])
            
            if not api_data:
                logger.warning(f"   ⚠️ No API data returned")
                skipped_count += 1
                continue
            
            # Find matching fixture
            fixture = self.find_matching_fixture(
                api_data,
                match['home_team'],
                match['away_team'],
                match['match_date']
            )
            
            if not fixture:
                logger.warning(f"   ⚠️ No matching fixture found in API response")
                skipped_count += 1
                continue
            
            # Insert odds
            inserted = self.insert_odds_snapshots(
                match['match_id'],
                match['league_id'],
                match['kickoff_at'],
                fixture
            )
            
            if inserted > 0:
                logger.info(f"   ✅ Inserted {inserted} odds snapshots")
                success_count += 1
                total_snapshots += inserted
            else:
                logger.warning(f"   ⚠️ No odds inserted")
                failed_count += 1
            
            # Rate limiting (don't hammer the API)
            if i < len(matches):
                time.sleep(2)
        
        logger.info("\n" + "="*80)
        logger.info("BACKFILL SUMMARY")
        logger.info("="*80)
        logger.info(f"Total processed:  {len(matches)}")
        logger.info(f"✅ Success:       {success_count}")
        logger.info(f"❌ Failed:        {failed_count}")
        logger.info(f"⚠️  Skipped:       {skipped_count}")
        logger.info(f"📊 Snapshots:     {total_snapshots}")
        
        if self.dry_run:
            logger.info("\n💡 This was a DRY RUN - no data was stored")
            logger.info("   Remove --dry-run to perform actual backfill")
        else:
            logger.info("\n🔄 Refreshing odds_real_consensus materialized view...")
            conn = psycopg2.connect(self.database_url)
            cursor = conn.cursor()
            cursor.execute("REFRESH MATERIALIZED VIEW odds_real_consensus")
            conn.commit()
            cursor.close()
            conn.close()
            logger.info("✅ Materialized view refreshed!")

def main():
    parser = argparse.ArgumentParser(description="Backfill historical odds from The Odds API")
    parser.add_argument(
        "--days-back",
        type=int,
        default=60,
        help="Look for matches from last N days (default: 60)"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum matches to backfill (default: 100)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Test without inserting data"
    )
    
    args = parser.parse_args()
    
    backfiller = TheOddsAPIBackfiller(dry_run=args.dry_run)
    backfiller.run_backfill(args.days_back, args.limit)

if __name__ == "__main__":
    main()
