import os
import psycopg2
from datetime import datetime
from typing import List, Dict, Optional, Tuple
import logging
from utils.api_football_client import ApiFootballClient, OddsMapper

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv('DATABASE_URL')


class BookmakerCrosswalk:
    """Manages bookmaker mapping between API-Football and internal system."""
    
    @staticmethod
    def seed_from_api_football():
        """
        Fetch bookmakers from API-Football and populate bookmaker_xwalk table.
        """
        client = ApiFootballClient()
        bookmakers = client.get_bookmakers()
        
        if not bookmakers:
            logger.error("Failed to fetch bookmakers from API-Football")
            return 0
        
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        
        inserted = 0
        for book in bookmakers:
            book_id = book.get('id')
            name = book.get('name', '').strip()
            
            if not name:
                continue
            
            canonical_name = name.lower()
            desk_group = OddsMapper.canonicalize_bookmaker_name(name)
            
            try:
                cursor.execute("""
                    INSERT INTO bookmaker_xwalk 
                    (canonical_name, api_football_book_id, desk_group, is_active)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (canonical_name) 
                    DO UPDATE SET 
                        api_football_book_id = EXCLUDED.api_football_book_id,
                        desk_group = EXCLUDED.desk_group,
                        updated_at = NOW()
                """, (canonical_name, str(book_id), desk_group, True))
                inserted += 1
            except Exception as e:
                logger.error(f"Failed to insert bookmaker {name}: {str(e)}")
        
        conn.commit()
        cursor.close()
        conn.close()
        
        logger.info(f"Seeded {inserted} bookmakers into bookmaker_xwalk")
        return inserted
    
    @staticmethod
    def get_desk_group(api_football_book_id: str) -> Optional[str]:
        """Get desk_group for an API-Football bookmaker ID."""
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT desk_group FROM bookmaker_xwalk 
            WHERE api_football_book_id = %s
        """, (str(api_football_book_id),))
        
        result = cursor.fetchone()
        cursor.close()
        conn.close()
        
        return result[0] if result else None


class ApiFootballIngestion:
    """Handles odds ingestion from API-Football into odds_snapshots."""
    
    @staticmethod
    def resolve_fixture_id(
        match_id: int,
        league_id: int,
        kickoff_at: datetime,
        home_team: str = None,
        away_team: str = None
    ) -> Optional[int]:
        """
        3-step fixture ID resolver (breaks circular dependency):
        1. Check matches table (canonical source)
        2. Check odds_snapshots (fallback from TheOdds)
        3. Live API-Football search by league+date+teams (last resort)
        
        Returns fixture_id or None if not found.
        """
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        
        # Step 1: Check matches table (canonical)
        try:
            cursor.execute("""
                SELECT api_football_fixture_id 
                FROM matches 
                WHERE match_id = %s 
                  AND api_football_fixture_id IS NOT NULL
            """, (match_id,))
            result = cursor.fetchone()
            if result and result[0]:
                fixture_id = result[0]
                cursor.close()
                conn.close()
                logger.debug(f"✅ Resolver Step 1: Found fixture_id {fixture_id} in matches table")
                return fixture_id
        except Exception as e:
            logger.debug(f"Step 1 (matches table) failed: {e}")
        
        # Step 2: Check odds_snapshots (fallback from TheOdds)
        try:
            cursor.execute("""
                SELECT api_football_fixture_id 
                FROM odds_snapshots 
                WHERE match_id = %s 
                  AND source = 'theodds'
                  AND api_football_fixture_id IS NOT NULL
                ORDER BY ts_snapshot DESC 
                LIMIT 1
            """, (match_id,))
            result = cursor.fetchone()
            if result and result[0]:
                fixture_id = result[0]
                # Persist to matches table for future lookups
                try:
                    cursor.execute("""
                        UPDATE matches 
                        SET api_football_fixture_id = %s 
                        WHERE match_id = %s
                    """, (fixture_id, match_id))
                    conn.commit()
                except Exception as update_err:
                    logger.debug(f"Could not persist fixture_id to matches: {update_err}")
                
                cursor.close()
                conn.close()
                logger.debug(f"✅ Resolver Step 2: Found fixture_id {fixture_id} in odds_snapshots")
                return fixture_id
        except Exception as e:
            logger.debug(f"Step 2 (odds_snapshots) failed: {e}")
        
        cursor.close()
        conn.close()
        
        # Step 3: Live API-Football search (last resort)
        if home_team and away_team:
            try:
                client = ApiFootballClient()
                # Search within ±2 days of kickoff
                from datetime import timedelta
                date_from = (kickoff_at - timedelta(days=2)).strftime('%Y-%m-%d')
                date_to = (kickoff_at + timedelta(days=2)).strftime('%Y-%m-%d')
                season = kickoff_at.year
                
                fixtures = client.search_fixtures_by_teams(
                    home_team=home_team,
                    away_team=away_team,
                    date_from=date_from,
                    date_to=date_to,
                    league_id=league_id,
                    season=season
                )
                
                if fixtures:
                    fixture_id = fixtures[0]['fixture']['id']
                    # Persist to matches table
                    conn = psycopg2.connect(DATABASE_URL)
                    cursor = conn.cursor()
                    try:
                        cursor.execute("""
                            UPDATE matches 
                            SET api_football_fixture_id = %s 
                            WHERE match_id = %s
                        """, (fixture_id, match_id))
                        conn.commit()
                    except Exception as update_err:
                        logger.debug(f"Could not persist fixture_id to matches: {update_err}")
                    finally:
                        cursor.close()
                        conn.close()
                    
                    logger.info(f"✅ Resolver Step 3: Found fixture_id {fixture_id} via live search")
                    return fixture_id
                    
            except Exception as e:
                logger.warning(f"Step 3 (live search) failed: {e}")
        
        logger.warning(f"❌ Resolver failed: No fixture_id found for match {match_id}")
        return None
    
    @staticmethod
    def ingest_fixture_odds(
        fixture_id: int,
        match_id: int,
        league_id: int,
        kickoff_ts: datetime,
        live: bool = False
    ) -> int:
        """
        Ingest odds from API-Football for a specific fixture.
        
        Args:
            fixture_id: API-Football fixture ID
            match_id: Our internal match_id
            league_id: League ID
            kickoff_ts: Match kickoff timestamp
            live: Whether to fetch live odds
        
        Returns:
            Number of odds rows inserted
        """
        client = ApiFootballClient()
        odds_data = client.get_odds_by_fixture(fixture_id, live=live)
        
        if not odds_data:
            logger.debug(f"No odds found for fixture {fixture_id}")
            return 0
        
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        
        rows_inserted = 0
        bookmakers = odds_data.get('bookmakers', [])
        
        for bookmaker_data in bookmakers:
            bookmaker_id = bookmaker_data.get('id')
            bookmaker_name = bookmaker_data.get('name', 'Unknown')
            bets = bookmaker_data.get('bets', [])
            
            for bet in bets:
                market_name = bet.get('name', '')
                internal_market = OddsMapper.map_market(market_name)
                
                if not internal_market:
                    continue
                
                if internal_market != 'h2h':
                    continue
                
                values = bet.get('values', [])
                last_update_str = bet.get('last_update', datetime.utcnow().isoformat())
                
                try:
                    ts_snapshot = datetime.fromisoformat(last_update_str.replace('Z', '+00:00'))
                except:
                    ts_snapshot = datetime.utcnow()
                
                secs_to_kickoff = int((kickoff_ts - ts_snapshot).total_seconds())
                
                for value in values:
                    outcome_name = value.get('value', '')
                    internal_outcome = OddsMapper.map_outcome(outcome_name)
                    
                    if not internal_outcome:
                        continue
                    
                    odds_decimal = float(value.get('odd', 0))
                    if odds_decimal <= 1.0:
                        continue
                    
                    implied_prob = 1.0 / odds_decimal
                    
                    book_id = f"apif:{bookmaker_id}"
                    
                    try:
                        cursor.execute("""
                            INSERT INTO odds_snapshots 
                            (match_id, league_id, book_id, market, outcome, 
                             ts_snapshot, secs_to_kickoff, odds_decimal, implied_prob,
                             source, vendor_fixture_id, vendor_book_id)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (match_id, book_id, market, outcome)
                            DO UPDATE SET
                                ts_snapshot = EXCLUDED.ts_snapshot,
                                secs_to_kickoff = EXCLUDED.secs_to_kickoff,
                                odds_decimal = EXCLUDED.odds_decimal,
                                implied_prob = EXCLUDED.implied_prob
                            WHERE odds_snapshots.ts_snapshot < EXCLUDED.ts_snapshot
                        """, (
                            match_id, league_id, book_id, internal_market, 
                            internal_outcome, ts_snapshot, secs_to_kickoff,
                            odds_decimal, implied_prob, 'api_football',
                            fixture_id, str(bookmaker_id)
                        ))
                        rows_inserted += 1
                    except Exception as e:
                        logger.error(f"Failed to insert odds: {str(e)}")
        
        conn.commit()
        cursor.close()
        conn.close()
        
        logger.info(
            f"Ingested {rows_inserted} odds rows for fixture {fixture_id} "
            f"(match_id={match_id}) from {len(bookmakers)} bookmakers"
        )
        
        return rows_inserted
    
    @staticmethod
    def refresh_consensus_for_match(match_id: int):
        """
        Rebuild odds_consensus for a specific match using multi-source data.
        Implements desk deduplication and source_mix tracking.
        """
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        
        cursor.execute("""
            WITH latest_odds AS (
                SELECT DISTINCT ON (os.match_id, os.market, os.outcome, COALESCE(bx.desk_group, os.book_id))
                    os.match_id,
                    os.league_id,
                    os.market,
                    os.outcome,
                    os.odds_decimal,
                    os.implied_prob,
                    os.source,
                    COALESCE(bx.desk_group, os.book_id) as desk_group
                FROM odds_snapshots os
                LEFT JOIN bookmaker_xwalk bx ON os.vendor_book_id = bx.api_football_book_id
                WHERE os.match_id = %s
                    AND os.market = 'h2h'
                    AND os.outcome IN ('H', 'D', 'A')
                ORDER BY os.match_id, os.market, os.outcome, 
                         COALESCE(bx.desk_group, os.book_id), os.ts_snapshot DESC
            ),
            consensus_calc AS (
                SELECT 
                    match_id,
                    league_id,
                    market,
                    outcome,
                    COUNT(DISTINCT desk_group) as n_books,
                    AVG(odds_decimal) as avg_odds,
                    AVG(implied_prob) as avg_implied_prob,
                    jsonb_object_agg(
                        source,
                        COUNT(*)::int
                    ) as source_counts
                FROM latest_odds
                GROUP BY match_id, league_id, market, outcome
            )
            INSERT INTO odds_consensus 
            (match_id, league_id, market, outcome, consensus_odds_decimal, 
             consensus_implied_prob, n_books, source_mix, ts_computed)
            SELECT 
                match_id,
                league_id,
                market,
                outcome,
                avg_odds,
                avg_implied_prob,
                n_books,
                source_counts,
                NOW()
            FROM consensus_calc
            ON CONFLICT (match_id, market, outcome)
            DO UPDATE SET
                consensus_odds_decimal = EXCLUDED.consensus_odds_decimal,
                consensus_implied_prob = EXCLUDED.consensus_implied_prob,
                n_books = EXCLUDED.n_books,
                source_mix = EXCLUDED.source_mix,
                ts_computed = EXCLUDED.ts_computed
        """, (match_id,))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        logger.info(f"Refreshed consensus for match {match_id}")
