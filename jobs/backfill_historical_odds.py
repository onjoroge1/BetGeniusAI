"""
Historical Odds Backfill System

Backfills odds snapshots for historical matches (12-18 months)
Collects opening + closing odds from The Odds API
Supports multi-league coverage for LightGBM training data

Author: BetGenius AI Team
Date: Oct 2025
"""

import os
import sys
import asyncio
import aiohttp
import psycopg2
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
import logging

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from models.database import DatabaseManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ODDS_API_KEY = os.getenv('ODDS_API_KEY', '')
ODDS_API_BASE = "https://api.the-odds-api.com/v4"

TARGET_LEAGUES = [
    ('soccer_epl', 'Premier League'),
    ('soccer_spain_la_liga', 'La Liga'),
    ('soccer_italy_serie_a', 'Serie A'),
    ('soccer_germany_bundesliga', 'Bundesliga'),
    ('soccer_france_ligue_one', 'Ligue 1'),
    ('soccer_usa_mls', 'MLS'),
    ('soccer_mexico_ligamx', 'Liga MX'),
    ('soccer_netherlands_eredivisie', 'Eredivisie'),
    ('soccer_portugal_primeira_liga', 'Primeira Liga'),
    ('soccer_brazil_campeonato', 'Brasileirão'),
]


class HistoricalOddsBackfiller:
    """Backfill historical odds snapshots for training data expansion"""
    
    def __init__(self):
        self.db_manager = DatabaseManager()
        self.api_key = ODDS_API_KEY
        self.base_url = ODDS_API_BASE
        
    async def backfill_league(self, sport_key: str, league_name: str, months_back: int = 18) -> Dict[str, Any]:
        """
        Backfill historical odds for a single league
        
        Args:
            sport_key: The Odds API sport identifier
            league_name: Human-readable league name
            months_back: How many months of history to collect
        """
        logger.info(f"\n{'='*70}")
        logger.info(f"🔄 Backfilling {league_name} ({sport_key})")
        logger.info(f"   Target: Last {months_back} months")
        logger.info(f"{'='*70}\n")
        
        try:
            end_date = datetime.now(timezone.utc)
            start_date = end_date - timedelta(days=months_back * 30)
            
            total_collected = 0
            total_snapshots = 0
            
            async with aiohttp.ClientSession() as session:
                current_date = start_date
                
                while current_date < end_date:
                    window_end = min(current_date + timedelta(days=30), end_date)
                    
                    logger.info(f"📅 Window: {current_date.date()} → {window_end.date()}")
                    
                    url = f"{self.base_url}/sports/{sport_key}/odds-history"
                    params = {
                        'apiKey': self.api_key,
                        'regions': 'us,uk,eu',
                        'markets': 'h2h',
                        'oddsFormat': 'decimal',
                        'dateFormat': 'iso',
                        'date': current_date.strftime('%Y-%m-%dT%H:%M:%SZ')
                    }
                    
                    try:
                        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                fixtures = data.get('data', [])
                                
                                for fixture in fixtures:
                                    snapshots = await self._process_fixture_snapshots(fixture, sport_key, league_name)
                                    total_snapshots += snapshots
                                
                                total_collected += len(fixtures)
                                logger.info(f"   ✅ {len(fixtures)} fixtures, {total_snapshots} snapshots")
                            
                            elif resp.status == 429:
                                logger.warning("   ⚠️ Rate limit hit, pausing...")
                                await asyncio.sleep(60)
                                continue
                            
                            else:
                                logger.warning(f"   ⚠️ API returned {resp.status}")
                    
                    except asyncio.TimeoutError:
                        logger.warning(f"   ⏱️ Timeout, skipping window")
                    
                    except Exception as e:
                        logger.error(f"   ❌ Error: {e}")
                    
                    current_date = window_end
                    await asyncio.sleep(2)
            
            logger.info(f"\n✅ {league_name} Complete:")
            logger.info(f"   Fixtures: {total_collected}")
            logger.info(f"   Snapshots: {total_snapshots}")
            
            return {
                'league': league_name,
                'sport_key': sport_key,
                'fixtures': total_collected,
                'snapshots': total_snapshots,
                'success': True
            }
        
        except Exception as e:
            logger.error(f"❌ Failed backfilling {league_name}: {e}")
            return {
                'league': league_name,
                'sport_key': sport_key,
                'fixtures': 0,
                'snapshots': 0,
                'success': False,
                'error': str(e)
            }
    
    async def _process_fixture_snapshots(self, fixture: Dict, sport_key: str, league_name: str) -> int:
        """
        Process all snapshots for a single fixture
        Returns number of snapshots saved
        """
        try:
            fixture_id = fixture.get('id')
            commence_time = datetime.fromisoformat(fixture.get('commence_time').replace('Z', '+00:00'))
            home_team = fixture.get('home_team', '')
            away_team = fixture.get('away_team', '')
            
            if not all([fixture_id, home_team, away_team]):
                return 0
            
            conn = psycopg2.connect(os.getenv('DATABASE_URL'))
            cursor = conn.cursor()
            
            try:
                cursor.execute("""
                    INSERT INTO fixtures (match_id, league_name, home_team, away_team, kickoff_at, status)
                    VALUES (%s, %s, %s, %s, %s, 'FT')
                    ON CONFLICT (match_id) DO UPDATE SET
                        league_name = EXCLUDED.league_name,
                        home_team = EXCLUDED.home_team,
                        away_team = EXCLUDED.away_team
                    RETURNING match_id
                """, (fixture_id, league_name, home_team, away_team, commence_time))
                
                match_id = cursor.fetchone()[0]
                
                bookmakers = fixture.get('bookmakers', [])
                snapshot_count = 0
                
                for bookmaker in bookmakers:
                    book_name = bookmaker.get('key', '')
                    book_id = f"odds:{book_name}"
                    
                    markets = bookmaker.get('markets', [])
                    for market in markets:
                        if market.get('key') != 'h2h':
                            continue
                        
                        outcomes = market.get('outcomes', [])
                        odds_map = {}
                        
                        for outcome in outcomes:
                            name = outcome.get('name', '')
                            price = outcome.get('price', 0)
                            
                            if name == home_team:
                                odds_map['H'] = price
                            elif name == away_team:
                                odds_map['A'] = price
                            else:
                                odds_map['D'] = price
                        
                        if len(odds_map) == 3:
                            for outcome_code, odds in odds_map.items():
                                implied = 1.0 / odds if odds > 1.0 else 0.0
                                secs_to_kick = int((commence_time - datetime.now(timezone.utc)).total_seconds())
                                
                                cursor.execute("""
                                    INSERT INTO odds_snapshots 
                                    (match_id, league_id, book_id, market, ts_snapshot, secs_to_kickoff, outcome, odds_decimal, implied_prob, market_margin, source)
                                    VALUES (%s, 0, %s, 'h2h', %s, %s, %s, %s, %s, 0.0, 'odds_api_backfill')
                                    ON CONFLICT (match_id, ts_snapshot, book_id, outcome) 
                                    DO NOTHING
                                """, (match_id, book_id, commence_time - timedelta(hours=24), secs_to_kick, outcome_code, odds, implied, ))
                                
                                snapshot_count += 1
                
                conn.commit()
                return snapshot_count
            
            finally:
                cursor.close()
                conn.close()
        
        except Exception as e:
            logger.error(f"Error processing fixture {fixture.get('id')}: {e}")
            return 0
    
    async def run_full_backfill(self, months_back: int = 18) -> Dict[str, Any]:
        """Run backfill across all target leagues"""
        logger.info(f"\n{'='*70}")
        logger.info(f"🚀 HISTORICAL ODDS BACKFILL - {months_back} MONTHS")
        logger.info(f"{'='*70}\n")
        
        results = []
        
        for sport_key, league_name in TARGET_LEAGUES:
            result = await self.backfill_league(sport_key, league_name, months_back)
            results.append(result)
            
            await asyncio.sleep(5)
        
        summary = {
            'total_leagues': len(results),
            'successful': sum(1 for r in results if r.get('success')),
            'total_fixtures': sum(r.get('fixtures', 0) for r in results),
            'total_snapshots': sum(r.get('snapshots', 0) for r in results),
            'results': results
        }
        
        logger.info(f"\n{'='*70}")
        logger.info(f"📊 BACKFILL SUMMARY")
        logger.info(f"{'='*70}")
        logger.info(f"Leagues processed: {summary['successful']}/{summary['total_leagues']}")
        logger.info(f"Total fixtures: {summary['total_fixtures']}")
        logger.info(f"Total snapshots: {summary['total_snapshots']}")
        logger.info(f"{'='*70}\n")
        
        return summary


async def main():
    """Main entry point"""
    backfiller = HistoricalOddsBackfiller()
    
    months = int(sys.argv[1]) if len(sys.argv) > 1 else 18
    
    summary = await backfiller.run_full_backfill(months_back=months)
    
    print(f"\n✅ Backfill complete!")
    print(f"   Fixtures: {summary['total_fixtures']}")
    print(f"   Snapshots: {summary['total_snapshots']}")


if __name__ == "__main__":
    asyncio.run(main())
