#!/usr/bin/env python3
"""
Backfill Historical Odds Data from API-Football

This script backfills pre-kickoff odds snapshots from API-Football to expand
the training dataset from 1,236 to 3,000-5,000 clean matches.

Strategy:
1. Find matches in training_matches that lack odds_snapshots coverage
2. Fetch historical odds from API-Football for those matches
3. Insert into odds_snapshots table
4. Refresh odds_real_consensus materialized view
5. Track progress and estimate data expansion

Usage:
    python scripts/backfill_odds_api_football.py --start-date 2023-01-01 --end-date 2025-08-18 --batch-size 100
    
    # Dry run (no inserts)
    python scripts/backfill_odds_api_football.py --start-date 2023-01-01 --dry-run
    
    # Specific league
    python scripts/backfill_odds_api_football.py --league-id 39 --start-date 2024-01-01
"""

import os
import sys
import time
import argparse
import requests
import pandas as pd
from datetime import datetime, timedelta
from sqlalchemy import create_engine, text
from typing import List, Dict, Optional
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class OddsBackfiller:
    """Backfill historical odds from API-Football"""
    
    def __init__(self, api_key: Optional[str] = None, dry_run: bool = False):
        self.api_key = api_key or os.getenv('RAPIDAPI_KEY')
        if not self.api_key:
            raise ValueError("RAPIDAPI_KEY not found in environment")
        
        self.database_url = os.getenv('DATABASE_URL')
        if not self.database_url:
            raise ValueError("DATABASE_URL not found in environment")
        
        self.engine = create_engine(self.database_url)
        self.dry_run = dry_run
        
        self.base_url = "https://api-football-v1.p.rapidapi.com/v3"
        self.headers = {
            "X-RapidAPI-Key": self.api_key,
            "X-RapidAPI-Host": "api-football-v1.p.rapidapi.com"
        }
        
        # Rate limiting (500 requests/day on free tier)
        self.requests_made = 0
        self.daily_limit = 500
        self.request_interval = 1.0  # 1 second between requests
        
        logger.info(f"🔧 OddsBackfiller initialized (dry_run={dry_run})")
    
    def find_matches_needing_odds(self, start_date: str, end_date: str, 
                                  league_id: Optional[int] = None, 
                                  limit: Optional[int] = None) -> pd.DataFrame:
        """
        Find matches in training_matches that lack odds_snapshots coverage
        
        FIXED (Nov 9): Changed INNER JOIN to LEFT JOIN on fixtures to avoid filtering out
        historical matches. Use match_date as fallback for kickoff_at.
        
        Returns:
            DataFrame with columns: match_id, kickoff_at, league_id, home_team, away_team
        """
        league_filter = f"AND tm.league_id = {league_id}" if league_id else ""
        limit_clause = f"LIMIT {limit}" if limit else ""
        
        query = text(f"""
            SELECT 
                tm.match_id,
                COALESCE(f.kickoff_at, tm.match_date) as kickoff_at,
                tm.league_id,
                tm.home_team,
                tm.away_team,
                tm.match_date
            FROM training_matches tm
            LEFT JOIN fixtures f ON tm.match_id = f.match_id
            LEFT JOIN odds_snapshots os ON tm.match_id = os.match_id
            WHERE tm.match_date >= :start_date
              AND tm.match_date < :end_date
              AND tm.match_date IS NOT NULL
              AND tm.outcome IS NOT NULL
              AND tm.match_id IS NOT NULL  -- Must have valid match_id (which IS the API-Football ID)
              AND os.match_id IS NULL  -- No odds snapshots yet
            {league_filter}
            ORDER BY tm.match_date DESC
            {limit_clause}
        """)
        
        with self.engine.connect() as conn:
            df = pd.read_sql(
                query, 
                conn, 
                params={"start_date": start_date, "end_date": end_date}
            )
        
        logger.info(f"📊 Found {len(df)} matches needing odds backfill")
        if len(df) > 0:
            logger.info(f"   Date range: {df['match_date'].min()} to {df['match_date'].max()}")
            logger.info(f"   Leagues: {df['league_id'].nunique()} unique leagues")
        
        return df
    
    def fetch_odds_for_fixture(self, fixture_id: int) -> Optional[List[Dict]]:
        """
        Fetch pre-match odds from API-Football for a specific fixture
        
        Args:
            fixture_id: The fixture ID (same as match_id in our database)
        
        Returns:
            List of bookmaker odds or None if unavailable
        """
        if self.requests_made >= self.daily_limit:
            logger.warning(f"⚠️  Daily API limit reached ({self.daily_limit} requests)")
            return None
        
        url = f"{self.base_url}/odds"
        params = {
            "fixture": fixture_id,
            "bet": 1  # 1X2 match winner market
        }
        
        try:
            time.sleep(self.request_interval)  # Rate limiting
            response = requests.get(url, headers=self.headers, params=params, timeout=10)
            self.requests_made += 1
            
            if response.status_code == 200:
                data = response.json()
                if data.get('response') and len(data['response']) > 0:
                    return data['response'][0].get('bookmakers', [])
                else:
                    logger.debug(f"   No odds data for fixture {fixture_id}")
                    return None
            elif response.status_code == 429:
                logger.warning(f"⚠️  Rate limited by API-Football (429), waiting 60s...")
                time.sleep(60)
                return self.fetch_odds_for_fixture(fixture_id)  # Retry once
            else:
                logger.warning(f"   API error {response.status_code} for fixture {fixture_id}")
                return None
        
        except requests.RequestException as e:
            logger.error(f"   Request failed for fixture {fixture_id}: {e}")
            return None
    
    def parse_bookmaker_odds(self, bookmakers: List[Dict], match_id: int, 
                            kickoff_at: datetime) -> List[Dict]:
        """
        Parse bookmaker odds into odds_snapshots format
        
        Returns:
            List of dicts with: match_id, book_id, outcome, odds, implied_prob, ts_effective
        """
        snapshots = []
        
        for bookmaker in bookmakers:
            book_name = bookmaker.get('name', 'Unknown')
            bets = bookmaker.get('bets', [])
            
            if not bets:
                continue
            
            # Find 1X2 market (Match Winner)
            match_winner_bet = None
            for bet in bets:
                if bet.get('name') == 'Match Winner':
                    match_winner_bet = bet
                    break
            
            if not match_winner_bet:
                continue
            
            values = match_winner_bet.get('values', [])
            if len(values) != 3:
                continue
            
            # Parse odds for Home, Draw, Away
            odds_map = {}
            for value in values:
                outcome_label = value.get('value')  # 'Home', 'Draw', 'Away'
                odd = value.get('odd')
                
                if outcome_label and odd:
                    try:
                        odds_map[outcome_label.lower()] = float(odd)
                    except (ValueError, TypeError):
                        continue
            
            if len(odds_map) != 3:
                continue
            
            # Calculate implied probabilities
            home_prob = 1.0 / odds_map['home'] if odds_map.get('home') else 0
            draw_prob = 1.0 / odds_map['draw'] if odds_map.get('draw') else 0
            away_prob = 1.0 / odds_map['away'] if odds_map.get('away') else 0
            
            # Use earliest possible timestamp (assume 24h before kickoff for historical data)
            # This is conservative - real opening odds could be earlier
            ts_effective = kickoff_at - timedelta(hours=24)
            secs_to_kickoff = 24 * 3600
            
            snapshots.extend([
                {
                    'match_id': match_id,
                    'book_id': book_name,
                    'outcome': 'H',
                    'odds': odds_map['home'],
                    'implied_prob': home_prob,
                    'ts_snapshot': ts_effective,
                    'secs_to_kickoff': secs_to_kickoff,
                    'market': 'h2h'
                },
                {
                    'match_id': match_id,
                    'book_id': book_name,
                    'outcome': 'D',
                    'odds': odds_map['draw'],
                    'implied_prob': draw_prob,
                    'ts_snapshot': ts_effective,
                    'secs_to_kickoff': secs_to_kickoff,
                    'market': 'h2h'
                },
                {
                    'match_id': match_id,
                    'book_id': book_name,
                    'outcome': 'A',
                    'odds': odds_map['away'],
                    'implied_prob': away_prob,
                    'ts_snapshot': ts_effective,
                    'secs_to_kickoff': secs_to_kickoff,
                    'market': 'h2h'
                }
            ])
        
        return snapshots
    
    def insert_odds_snapshots(self, snapshots: List[Dict]) -> int:
        """
        Insert odds snapshots into database
        
        Returns:
            Number of rows inserted
        """
        if not snapshots:
            return 0
        
        if self.dry_run:
            logger.info(f"   [DRY RUN] Would insert {len(snapshots)} snapshot rows")
            return len(snapshots)
        
        df = pd.DataFrame(snapshots)
        
        try:
            with self.engine.begin() as conn:
                df.to_sql(
                    'odds_snapshots',
                    conn,
                    if_exists='append',
                    index=False,
                    method='multi'
                )
            return len(snapshots)
        except Exception as e:
            logger.error(f"   Failed to insert snapshots: {e}")
            return 0
    
    def refresh_materialized_views(self):
        """Refresh odds_real_consensus and related views"""
        if self.dry_run:
            logger.info("[DRY RUN] Would refresh materialized views")
            return
        
        views = ['odds_real_consensus', 'odds_real_latest', 'odds_real_opening']
        
        with self.engine.begin() as conn:
            for view in views:
                try:
                    logger.info(f"🔄 Refreshing {view}...")
                    conn.execute(text(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {view}"))
                    logger.info(f"   ✅ {view} refreshed")
                except Exception as e:
                    logger.warning(f"   ⚠️  Could not refresh {view}: {e}")
    
    def backfill(self, start_date: str, end_date: str, 
                 league_id: Optional[int] = None,
                 batch_size: int = 100,
                 max_matches: Optional[int] = None):
        """
        Main backfill orchestrator
        
        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            league_id: Optional specific league to backfill
            batch_size: Number of matches to process per batch
            max_matches: Maximum total matches to process
        """
        logger.info("="*70)
        logger.info("  ODDS BACKFILL - API-FOOTBALL")
        logger.info("="*70)
        logger.info(f"📅 Date range: {start_date} to {end_date}")
        if league_id:
            logger.info(f"🏆 League filter: {league_id}")
        logger.info(f"📦 Batch size: {batch_size}")
        logger.info(f"🔒 Dry run: {self.dry_run}")
        logger.info("")
        
        # Find matches needing odds
        matches = self.find_matches_needing_odds(start_date, end_date, league_id, max_matches)
        
        if len(matches) == 0:
            logger.info("✅ No matches need backfilling!")
            return
        
        total_matches = len(matches)
        total_snapshots_inserted = 0
        matches_with_odds = 0
        matches_without_odds = 0
        
        # Process in batches
        for batch_start in range(0, total_matches, batch_size):
            batch_end = min(batch_start + batch_size, total_matches)
            batch = matches.iloc[batch_start:batch_end]
            
            logger.info(f"\n📦 Processing batch {batch_start//batch_size + 1}: "
                       f"matches {batch_start+1}-{batch_end} of {total_matches}")
            
            for idx, row in batch.iterrows():
                match_id = row['match_id']
                kickoff_at = pd.to_datetime(row['kickoff_at'])
                
                logger.info(f"   🎯 Match {match_id} - "
                           f"{row['home_team']} vs {row['away_team']}")
                
                # Fetch odds from API (match_id IS the API-Football fixture ID)
                bookmakers = self.fetch_odds_for_fixture(match_id)
                
                if bookmakers:
                    # Parse and insert
                    snapshots = self.parse_bookmaker_odds(bookmakers, match_id, kickoff_at)
                    
                    if snapshots:
                        n_books = len(set(s['book_id'] for s in snapshots)) 
                        inserted = self.insert_odds_snapshots(snapshots)
                        total_snapshots_inserted += inserted
                        matches_with_odds += 1
                        
                        logger.info(f"      ✅ Inserted {inserted} snapshots "
                                   f"({n_books} bookmakers)")
                    else:
                        logger.warning(f"      ⚠️  No valid odds parsed")
                        matches_without_odds += 1
                else:
                    logger.warning(f"      ⚠️  No odds data available")
                    matches_without_odds += 1
                
                # Progress update
                progress = ((batch_start + idx + 1) / total_matches) * 100
                logger.info(f"      Progress: {progress:.1f}% | "
                           f"Requests: {self.requests_made}/{self.daily_limit}")
                
                # Check if we hit API limit
                if self.requests_made >= self.daily_limit:
                    logger.warning(f"\n⚠️  Reached daily API limit ({self.daily_limit})")
                    logger.info(f"   Processed {matches_with_odds + matches_without_odds} matches")
                    break
            
            # Refresh views after each batch
            if not self.dry_run and total_snapshots_inserted > 0:
                logger.info("\n🔄 Refreshing materialized views after batch...")
                self.refresh_materialized_views()
        
        # Final summary
        logger.info("\n" + "="*70)
        logger.info("  BACKFILL SUMMARY")
        logger.info("="*70)
        logger.info(f"✅ Matches with odds found: {matches_with_odds}")
        logger.info(f"⚠️  Matches without odds: {matches_without_odds}")
        logger.info(f"📊 Total snapshots inserted: {total_snapshots_inserted}")
        logger.info(f"🌐 API requests made: {self.requests_made}")
        logger.info("")
        
        if not self.dry_run:
            # Check new coverage
            with self.engine.connect() as conn:
                result = conn.execute(text("""
                    SELECT COUNT(DISTINCT match_id) as count 
                    FROM odds_real_consensus
                """)).fetchone()
                logger.info(f"📈 Total matches in odds_real_consensus: {result[0]}")
                logger.info(f"   Previous: 1,236")
                logger.info(f"   New: {result[0]}")
                logger.info(f"   Gain: +{result[0] - 1236}")


def main():
    parser = argparse.ArgumentParser(description='Backfill odds data from API-Football')
    parser.add_argument('--start-date', type=str, required=True, 
                       help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, default='2025-08-18',
                       help='End date (YYYY-MM-DD), default: 2025-08-18')
    parser.add_argument('--league-id', type=int, default=None,
                       help='Optional: Filter to specific league')
    parser.add_argument('--batch-size', type=int, default=100,
                       help='Matches to process per batch (default: 100)')
    parser.add_argument('--max-matches', type=int, default=None,
                       help='Maximum matches to process (default: all)')
    parser.add_argument('--dry-run', action='store_true',
                       help='Run without inserting data (test mode)')
    
    args = parser.parse_args()
    
    # Initialize backfiller
    backfiller = OddsBackfiller(dry_run=args.dry_run)
    
    # Run backfill
    backfiller.backfill(
        start_date=args.start_date,
        end_date=args.end_date,
        league_id=args.league_id,
        batch_size=args.batch_size,
        max_matches=args.max_matches
    )


if __name__ == '__main__':
    main()
