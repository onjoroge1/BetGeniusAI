#!/usr/bin/env python3
"""
Backfill Historical Odds for Training Matches

Fetches historical odds from API-Football for matches in training_matches table
that have results but no odds data. This enables accurate backtesting.

Usage:
    python scripts/backfill_historical_odds.py --limit 100 --dry-run
    python scripts/backfill_historical_odds.py --start-date 2024-01-01 --end-date 2024-12-31
"""

import os
import sys
import time
import argparse
import psycopg2
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import requests

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.database import DatabaseManager

class HistoricalOddsBackfiller:
    """Backfills historical odds for training matches"""
    
    def __init__(self, dry_run: bool = False):
        self.rapidapi_key = os.environ.get('RAPIDAPI_KEY')
        if not self.rapidapi_key:
            raise ValueError("RAPIDAPI_KEY environment variable required")
        
        self.db_url = os.environ.get('DATABASE_URL')
        if not self.db_url:
            raise ValueError("DATABASE_URL environment variable required")
        
        self.dry_run = dry_run
        self.headers = {
            'X-RapidAPI-Key': self.rapidapi_key,
            'X-RapidAPI-Host': 'api-football-v1.p.rapidapi.com'
        }
        
        print(f"🔧 Backfiller initialized (dry_run={dry_run})")
    
    def get_matches_needing_odds(
        self, 
        limit: int = 100,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> List[Dict]:
        """Get matches from training_matches that need odds backfill"""
        
        conn = psycopg2.connect(self.db_url)
        cursor = conn.cursor()
        
        # Find matches with results but no odds - include league_id and kickoff_at
        query = """
            SELECT 
                tm.match_id,
                tm.fixture_id,
                tm.match_date,
                tm.home_team,
                tm.away_team,
                tm.outcome,
                tm.home_goals,
                tm.away_goals,
                lm.league_name,
                tm.league_id,
                COALESCE(f.kickoff_at, tm.match_date::timestamp) as kickoff_at
            FROM training_matches tm
            LEFT JOIN league_map lm ON tm.league_id = lm.league_id
            LEFT JOIN fixtures f ON tm.match_id = f.match_id
            LEFT JOIN odds_snapshots os ON tm.match_id = os.match_id
            WHERE tm.outcome IN ('H', 'D', 'A')
              AND tm.home_goals IS NOT NULL
              AND os.match_id IS NULL  -- No odds collected yet
              AND tm.fixture_id IS NOT NULL  -- Has API-Football ID
              AND tm.league_id IS NOT NULL  -- Required field
        """
        
        conditions = []
        params = []
        
        if start_date:
            conditions.append("tm.match_date >= %s")
            params.append(start_date)
        
        if end_date:
            conditions.append("tm.match_date <= %s")
            params.append(end_date)
        
        if conditions:
            query += " AND " + " AND ".join(conditions)
        
        query += " ORDER BY tm.match_date DESC LIMIT %s"
        params.append(limit)
        
        cursor.execute(query, params)
        matches = cursor.fetchall()
        
        result = []
        for row in matches:
            result.append({
                'match_id': row[0],
                'fixture_id': row[1],
                'match_date': row[2],
                'home_team': row[3],
                'away_team': row[4],
                'outcome': row[5],
                'home_goals': row[6],
                'away_goals': row[7],
                'league': row[8] or 'Unknown',
                'league_id': row[9],
                'kickoff_at': row[10]
            })
        
        cursor.close()
        conn.close()
        
        return result
    
    def fetch_historical_odds(self, fixture_id: int) -> Optional[Dict]:
        """Fetch historical odds from API-Football for a specific fixture"""
        
        url = "https://api-football-v1.p.rapidapi.com/v3/odds"
        params = {
            'fixture': fixture_id,
            'bookmaker': 8  # Bet365 as primary source
        }
        
        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=15)
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get('response') and len(data['response']) > 0:
                    odds_data = data['response'][0]
                    bookmakers = odds_data.get('bookmakers', [])
                    
                    if bookmakers:
                        # Extract 1X2 odds
                        for bookmaker in bookmakers:
                            bets = bookmaker.get('bets', [])
                            for bet in bets:
                                if bet.get('name') == 'Match Winner':
                                    values = bet.get('values', [])
                                    
                                    odds_dict = {}
                                    for val in values:
                                        odds_dict[val['value']] = float(val['odd'])
                                    
                                    # Convert to implied probabilities
                                    h_odds = odds_dict.get('Home', 0)
                                    d_odds = odds_dict.get('Draw', 0)
                                    a_odds = odds_dict.get('Away', 0)
                                    
                                    if h_odds > 0 and d_odds > 0 and a_odds > 0:
                                        return {
                                            'bookmaker': bookmaker.get('name', 'Unknown'),
                                            'bookmaker_id': bookmaker.get('id'),
                                            'h_odds': h_odds,
                                            'd_odds': d_odds,
                                            'a_odds': a_odds,
                                            'ph_implied': 1.0 / h_odds,
                                            'pd_implied': 1.0 / d_odds,
                                            'pa_implied': 1.0 / a_odds,
                                            'overround': (1.0/h_odds) + (1.0/d_odds) + (1.0/a_odds)
                                        }
            
            elif response.status_code == 429:
                print("⚠️  Rate limited, waiting 60s...")
                time.sleep(60)
                return self.fetch_historical_odds(fixture_id)
            
            return None
            
        except Exception as e:
            print(f"❌ Error fetching odds for fixture {fixture_id}: {e}")
            return None
    
    def store_historical_odds(self, match_id: int, fixture_id: int, odds: Dict, league_id: int, kickoff_at: datetime) -> bool:
        """Store historical odds in odds_snapshots table with all required fields"""
        
        # Calculate market_margin from overround
        market_margin = odds['overround'] - 1.0
        
        # Set ts_snapshot to 24h before kickoff for historical data
        horizon_hours = 24
        secs_to_kickoff = horizon_hours * 3600
        ts_snapshot = kickoff_at - timedelta(hours=horizon_hours)
        
        # Map API-Football bookmaker ID to internal book_id (Bet365 = 777)
        api_bookmaker_id = odds.get('bookmaker_id', 8)
        book_id = '777' if api_bookmaker_id == 8 else str(api_bookmaker_id)
        
        if self.dry_run:
            print(f"   [DRY RUN] Would store odds: H={odds['h_odds']:.2f} D={odds['d_odds']:.2f} A={odds['a_odds']:.2f}")
            print(f"   [DRY RUN] league_id={league_id}, ts_snapshot={ts_snapshot}, margin={market_margin:.4f}")
            return True
        
        try:
            conn = psycopg2.connect(self.db_url)
            cursor = conn.cursor()
            
            # Insert three rows (H, D, A) for this match with all required fields
            for outcome, prob, decimal_odds in [
                ('H', odds['ph_implied'], odds['h_odds']),
                ('D', odds['pd_implied'], odds['d_odds']),
                ('A', odds['pa_implied'], odds['a_odds'])
            ]:
                cursor.execute("""
                    INSERT INTO odds_snapshots 
                    (match_id, league_id, book_id, market, outcome, 
                     odds_decimal, implied_prob, market_margin, 
                     ts_snapshot, secs_to_kickoff, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (match_id, book_id, market, outcome, ts_snapshot) 
                    DO NOTHING
                """, (
                    match_id,
                    league_id,
                    book_id,
                    'h2h',
                    outcome,
                    decimal_odds,
                    prob,
                    market_margin,
                    ts_snapshot,
                    secs_to_kickoff
                ))
            
            conn.commit()
            cursor.close()
            conn.close()
            
            return True
            
        except Exception as e:
            print(f"❌ Error storing odds for match {match_id}: {e}")
            return False
    
    def run_backfill(
        self,
        limit: int = 100,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        delay_seconds: float = 1.0
    ):
        """Main backfill process"""
        
        print("\n" + "=" * 70)
        print("📊 HISTORICAL ODDS BACKFILL - BetGenius AI")
        print("=" * 70)
        
        # Get matches needing odds
        print(f"\n🔍 Finding matches needing odds backfill...")
        matches = self.get_matches_needing_odds(limit, start_date, end_date)
        
        if not matches:
            print("✅ No matches found needing backfill!")
            return
        
        print(f"📋 Found {len(matches)} matches needing odds")
        
        if start_date or end_date:
            print(f"   Date range: {start_date or 'earliest'} to {end_date or 'latest'}")
        
        # Process each match
        success_count = 0
        failed_count = 0
        skipped_count = 0
        
        for i, match in enumerate(matches, 1):
            print(f"\n[{i}/{len(matches)}] {match['home_team']} vs {match['away_team']}")
            print(f"   Match ID: {match['match_id']} | Fixture: {match['fixture_id']}")
            print(f"   Date: {match['match_date']} | Result: {match['outcome']} ({match['home_goals']}-{match['away_goals']})")
            
            # Fetch historical odds
            print(f"   Fetching historical odds from API-Football...")
            odds = self.fetch_historical_odds(match['fixture_id'])
            
            if odds:
                print(f"   ✅ Found odds: H={odds['h_odds']:.2f} D={odds['d_odds']:.2f} A={odds['a_odds']:.2f}")
                print(f"      Implied: H={odds['ph_implied']:.3f} D={odds['pd_implied']:.3f} A={odds['pa_implied']:.3f}")
                print(f"      Overround: {odds['overround']:.3f}")
                
                # Store odds
                if self.store_historical_odds(match["match_id"], match["fixture_id"], odds, match["league_id"], match["kickoff_at"]):
                    success_count += 1
                else:
                    failed_count += 1
            else:
                print(f"   ⚠️  No odds available for this match")
                skipped_count += 1
            
            # Rate limiting
            if i < len(matches):
                time.sleep(delay_seconds)
        
        # Summary
        print("\n" + "=" * 70)
        print("📊 BACKFILL SUMMARY")
        print("=" * 70)
        print(f"Total processed:  {len(matches)}")
        print(f"✅ Success:       {success_count}")
        print(f"❌ Failed:        {failed_count}")
        print(f"⚠️  Skipped:       {skipped_count}")
        
        if self.dry_run:
            print("\n💡 This was a DRY RUN - no data was actually stored")
            print("   Remove --dry-run flag to perform actual backfill")
        else:
            print(f"\n✅ Backfill complete! {success_count} matches now have odds data")


def main():
    parser = argparse.ArgumentParser(description='Backfill historical odds for training matches')
    parser.add_argument('--limit', type=int, default=100, help='Maximum matches to process')
    parser.add_argument('--start-date', type=str, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, help='End date (YYYY-MM-DD)')
    parser.add_argument('--delay', type=float, default=1.0, help='Delay between API calls (seconds)')
    parser.add_argument('--dry-run', action='store_true', help='Test without storing data')
    
    args = parser.parse_args()
    
    try:
        backfiller = HistoricalOddsBackfiller(dry_run=args.dry_run)
        backfiller.run_backfill(
            limit=args.limit,
            start_date=args.start_date,
            end_date=args.end_date,
            delay_seconds=args.delay
        )
    except Exception as e:
        print(f"\n❌ Backfill failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
