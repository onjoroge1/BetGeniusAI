#!/usr/bin/env python3
"""
Backfill Odds Snapshots from The Odds API

Purpose: Scale training data from 648 to 2,000+ matches by backfilling
historical odds snapshots into the odds_snapshots table.

Strategy:
1. Find completed matches from Oct 2024 onwards with no odds data
2. Fetch historical odds from The Odds API
3. Insert into odds_snapshots table
4. Refresh odds_real_consensus materialized view

Target: 2,000-5,000 historical matches for 52-54% accuracy

Usage:
    python scripts/backfill_odds_snapshots_the_odds_api.py --start-date 2024-10-01 --limit 100 --dry-run
    python scripts/backfill_odds_snapshots_the_odds_api.py --start-date 2024-10-01 --limit 2000
"""

import os
import sys
import argparse
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import requests
import time

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class OddsSnapshotsBackfill:
    """Backfill historical odds from The Odds API"""
    
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.api_key = os.getenv('ODDS_API_KEY')
        if not self.api_key:
            raise ValueError("ODDS_API_KEY not found in environment")
        
        self.database_url = os.getenv('DATABASE_URL')
        if not self.database_url:
            raise ValueError("DATABASE_URL not found in environment")
        
        self.engine = create_engine(self.database_url)
        self.base_url = "https://api.the-odds-api.com/v4"
        
        logger.info(f"Initialized OddsSnapshotsBackfill (dry_run={dry_run})")
    
    def get_matches_without_odds(self, start_date: str, limit: int) -> pd.DataFrame:
        """Find completed matches with no odds snapshots"""
        query = text("""
            SELECT DISTINCT
                tm.match_id,
                tm.match_date,
                tm.home_team,
                tm.away_team,
                tm.league_id,
                tm.outcome
            FROM training_matches tm
            LEFT JOIN odds_snapshots os ON tm.match_id = os.match_id
            WHERE tm.match_date >= :start_date
              AND tm.match_date < CURRENT_DATE
              AND tm.outcome IN ('Home', 'Draw', 'Away')
              AND os.match_id IS NULL
            ORDER BY tm.match_date DESC
            LIMIT :limit
        """)
        
        with self.engine.connect() as conn:
            df = pd.read_sql(query, conn, params={
                "start_date": start_date,
                "limit": limit
            })
        
        logger.info(f"Found {len(df)} matches without odds data")
        return df
    
    def fetch_historical_odds(self, match_date: datetime, sport: str = "soccer") -> Optional[Dict]:
        """
        Fetch historical odds from The Odds API
        
        Note: The Odds API typically only provides odds for UPCOMING matches.
        For historical data, you may need:
        1. A paid historical data package
        2. OR use pre-saved odds snapshots from when matches were upcoming
        3. OR alternative data sources
        
        This is a TEMPLATE - you'll need to adapt based on available API endpoints.
        """
        # The Odds API endpoint for historical data (if available)
        # THIS IS A PLACEHOLDER - check The Odds API docs for actual historical endpoint
        endpoint = f"{self.base_url}/sports/{sport}/odds"
        
        params = {
            "apiKey": self.api_key,
            "regions": "eu",  # European bookmakers
            "markets": "h2h",  # Head-to-head (1X2)
            "dateFormat": "iso",
            # Note: Most likely need to specify match or date here
        }
        
        try:
            response = requests.get(endpoint, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"API request failed: {e}")
            return None
    
    def insert_odds_snapshot(self, match_id: int, odds_data: Dict) -> int:
        """Insert odds snapshot into database"""
        if self.dry_run:
            logger.info(f"[DRY RUN] Would insert odds for match {match_id}")
            return 1
        
        # Parse odds data and insert
        # This depends on The Odds API response format
        insert_query = text("""
            INSERT INTO odds_snapshots (
                match_id,
                book_id,
                market,
                outcome,
                odds_decimal,
                implied_prob,
                secs_to_kickoff,
                created_at
            ) VALUES (
                :match_id,
                :book_id,
                :market,
                :outcome,
                :odds_decimal,
                :implied_prob,
                :secs_to_kickoff,
                :created_at
            )
            ON CONFLICT (match_id, book_id, market, outcome, created_at) DO NOTHING
        """)
        
        inserted = 0
        # TODO: Parse odds_data and insert each bookmaker's odds
        # This requires knowing The Odds API response structure
        
        return inserted
    
    def refresh_materialized_view(self):
        """Refresh odds_real_consensus after backfill"""
        if self.dry_run:
            logger.info("[DRY RUN] Would refresh odds_real_consensus")
            return
        
        logger.info("Refreshing odds_real_consensus materialized view...")
        with self.engine.connect() as conn:
            conn.execute(text("REFRESH MATERIALIZED VIEW odds_real_consensus"))
            conn.commit()
        
        logger.info("✅ Materialized view refreshed")
    
    def run_backfill(self, start_date: str, limit: int):
        """Run the backfill process"""
        logger.info("="*80)
        logger.info("ODDS SNAPSHOTS BACKFILL - The Odds API")
        logger.info(f"Start date: {start_date}")
        logger.info(f"Limit: {limit} matches")
        logger.info(f"Dry run: {self.dry_run}")
        logger.info("="*80)
        
        # Get matches without odds
        matches_df = self.get_matches_without_odds(start_date, limit)
        
        if len(matches_df) == 0:
            logger.info("No matches found - all have odds data already")
            return
        
        logger.info(f"Processing {len(matches_df)} matches...")
        
        total_inserted = 0
        for i, row in matches_df.iterrows():
            match_id = row['match_id']
            match_date = row['match_date']
            
            if (i + 1) % 10 == 0:
                logger.info(f"Progress: {i+1}/{len(matches_df)}")
            
            # Fetch historical odds
            # NOTE: This may not work with standard The Odds API
            # You likely need historical data access or pre-saved snapshots
            odds_data = self.fetch_historical_odds(match_date)
            
            if odds_data:
                inserted = self.insert_odds_snapshot(match_id, odds_data)
                total_inserted += inserted
            
            # Rate limiting (The Odds API has strict limits)
            time.sleep(1)  # 1 second between requests
        
        logger.info("="*80)
        logger.info(f"BACKFILL COMPLETE")
        logger.info(f"Processed: {len(matches_df)} matches")
        logger.info(f"Odds inserted: {total_inserted} rows")
        logger.info("="*80)
        
        if total_inserted > 0 and not self.dry_run:
            self.refresh_materialized_view()

def main():
    parser = argparse.ArgumentParser(description="Backfill odds snapshots from The Odds API")
    parser.add_argument(
        "--start-date",
        type=str,
        default="2024-10-01",
        help="Start date for backfill (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum number of matches to backfill"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run in dry-run mode (no database changes)"
    )
    
    args = parser.parse_args()
    
    backfill = OddsSnapshotsBackfill(dry_run=args.dry_run)
    backfill.run_backfill(args.start_date, args.limit)

if __name__ == "__main__":
    main()
