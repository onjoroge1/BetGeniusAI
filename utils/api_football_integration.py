import os
import psycopg2
from datetime import datetime
from typing import List, Dict, Optional, Tuple
import logging
from utils.api_football_client import ApiFootballClient, OddsMapper

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv('DATABASE_URL')


def compute_market_margin(prices: List[Optional[float]]) -> Optional[float]:
    """
    Calculate market overround/margin: sum(1/price) - 1
    Returns None if insufficient valid prices (need at least 2 outcomes)
    """
    inv_sum = 0.0
    count = 0
    for p in prices:
        if p and p > 0:
            inv_sum += 1.0 / p
            count += 1
    # Need at least two valid outcomes to call this a market
    return max(inv_sum - 1.0, 0.0) if count >= 2 else None


def implied_prob(price: Optional[float]) -> Optional[float]:
    """Convert decimal odds to implied probability"""
    return (1.0 / price) if price and price > 0 else None


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
                
                # Calculate correct season: European seasons run July-June
                # Jan-June belongs to previous year's season (e.g. Feb 2025 = 2024 season)
                season = kickoff_at.year if kickoff_at.month >= 7 else kickoff_at.year - 1
                
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
        skipped_no_margin = 0
        bookmakers = odds_data.get('bookmakers', [])
        
        # Group odds by (bookmaker, market) to compute margin per market
        from collections import defaultdict
        market_groups = defaultdict(list)
        
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
                
                # Collect all outcomes for this market
                market_key = (bookmaker_id, internal_market)
                for value in values:
                    outcome_name = value.get('value', '')
                    internal_outcome = OddsMapper.map_outcome(outcome_name)
                    
                    if not internal_outcome:
                        continue
                    
                    odds_decimal = float(value.get('odd', 0))
                    if odds_decimal <= 1.0:
                        continue
                    
                    market_groups[market_key].append({
                        'outcome': internal_outcome,
                        'price': odds_decimal,
                        'ts_snapshot': ts_snapshot,
                        'secs_to_kickoff': secs_to_kickoff,
                        'bookmaker_id': bookmaker_id,
                        'market': internal_market
                    })
        
        # FIRST: Upsert fixture metadata (canonical source of truth)
        try:
            cursor.execute("""
                INSERT INTO fixtures (
                    match_id, league_id, home_team, away_team, 
                    kickoff_at, season, status, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, now())
                ON CONFLICT (match_id) DO UPDATE SET
                    league_id = EXCLUDED.league_id,
                    kickoff_at = EXCLUDED.kickoff_at,
                    status = CASE
                        WHEN EXCLUDED.kickoff_at < now() THEN 'finished'
                        ELSE 'scheduled'
                    END,
                    updated_at = now()
            """, (
                match_id,
                league_id,
                'TBD',  # Team names not available in odds data
                'TBD',
                kickoff_ts.replace(tzinfo=None) if kickoff_ts.tzinfo else kickoff_ts,
                2024,
                'finished' if kickoff_ts < datetime.now(timezone.utc) else 'scheduled'
            ))
        except Exception as fixture_err:
            logger.warning(f"Failed to upsert fixture {match_id}: {fixture_err}")
        
        # SECOND: Process each market group: compute margin and insert
        for (bookmaker_id, market), selections in market_groups.items():
            # Compute market margin from all prices
            prices = [s['price'] for s in selections]
            margin = compute_market_margin(prices)
            
            if margin is None:
                logger.warning(
                    f"Skipping market with insufficient prices "
                    f"(fixture={fixture_id}, bookmaker={bookmaker_id}, market={market})"
                )
                skipped_no_margin += len(selections)
                continue
            
            # Insert each selection with the computed margin
            for s in selections:
                book_id = f"apif:{s['bookmaker_id']}"
                prob = implied_prob(s['price'])
                
                # Use SAVEPOINT to isolate row failures
                cursor.execute("SAVEPOINT sp_insert_odds")
                try:
                    cursor.execute("""
                        INSERT INTO odds_snapshots 
                        (match_id, league_id, book_id, market, outcome, 
                         ts_snapshot, secs_to_kickoff, odds_decimal, implied_prob,
                         market_margin, source, api_football_fixture_id, vendor_book_id)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (match_id, book_id, market, outcome)
                        DO UPDATE SET
                            ts_snapshot = EXCLUDED.ts_snapshot,
                            secs_to_kickoff = EXCLUDED.secs_to_kickoff,
                            odds_decimal = EXCLUDED.odds_decimal,
                            implied_prob = EXCLUDED.implied_prob,
                            market_margin = EXCLUDED.market_margin
                        WHERE odds_snapshots.ts_snapshot < EXCLUDED.ts_snapshot
                    """, (
                        match_id, league_id, book_id, s['market'], 
                        s['outcome'], s['ts_snapshot'], s['secs_to_kickoff'],
                        s['price'], prob, margin, 'api_football',
                        fixture_id, str(s['bookmaker_id'])
                    ))
                    cursor.execute("RELEASE SAVEPOINT sp_insert_odds")
                    rows_inserted += 1
                except Exception as e:
                    logger.error(f"Row insert failed, rolling back savepoint: {e}")
                    cursor.execute("ROLLBACK TO SAVEPOINT sp_insert_odds")
                    cursor.execute("RELEASE SAVEPOINT sp_insert_odds")
        
        conn.commit()
        cursor.close()
        conn.close()
        
        if skipped_no_margin > 0:
            logger.info(f"Skipped {skipped_no_margin} rows with insufficient market prices")
        
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
            source_counts AS (
                SELECT 
                    match_id,
                    league_id,
                    market,
                    outcome,
                    source,
                    COUNT(*) as n
                FROM latest_odds
                GROUP BY match_id, league_id, market, outcome, source
            ),
            consensus_calc AS (
                SELECT 
                    lo.match_id,
                    lo.league_id,
                    lo.market,
                    lo.outcome,
                    COUNT(DISTINCT lo.desk_group) as n_books,
                    AVG(lo.odds_decimal) as avg_odds,
                    AVG(lo.implied_prob) as avg_implied_prob,
                    (SELECT jsonb_object_agg(sc.source, sc.n)
                     FROM source_counts sc
                     WHERE sc.match_id = lo.match_id
                       AND sc.market = lo.market
                       AND sc.outcome = lo.outcome
                    ) as source_counts
                FROM latest_odds lo
                GROUP BY lo.match_id, lo.league_id, lo.market, lo.outcome
            )
            -- DISABLED: odds_consensus table has different schema (match-level probabilities)
            -- Consensus is now calculated from odds_snapshots when needed
            -- INSERT INTO odds_consensus 
            -- (match_id, league_id, market, outcome, consensus_odds_decimal, 
            --  consensus_implied_prob, n_books, source_mix, ts_computed)
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
            -- ON CONFLICT (match_id, market, outcome)
            -- DO UPDATE SET
            --     consensus_odds_decimal = EXCLUDED.consensus_odds_decimal,
            --     consensus_implied_prob = EXCLUDED.consensus_implied_prob,
            --     n_books = EXCLUDED.n_books,
            --     source_mix = EXCLUDED.source_mix,
            --     ts_computed = EXCLUDED.ts_computed
        """, (match_id,))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        logger.info(f"Refreshed consensus for match {match_id}")
