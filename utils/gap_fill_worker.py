import os
import psycopg2
from datetime import datetime, timedelta
from typing import List, Dict, Tuple
import logging
import time
from utils.api_football_integration import ApiFootballIngestion

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv('DATABASE_URL')


class GapFillWorker:
    """
    Identifies matches without odds and fills them using API-Football.
    Handles both upcoming matches and historical backfill.
    """
    
    MIN_BOOKS_THRESHOLD = 3
    BATCH_SIZE = 200
    INTER_FIXTURE_DELAY = 0.25
    
    @staticmethod
    def find_matches_without_odds(
        time_window_hours: int = 72,
        historical: bool = False,
        limit: int = 1000
    ) -> List[Tuple[int, int, int, datetime, int]]:
        """
        Find matches that lack sufficient odds data.
        
        Args:
            time_window_hours: Look ahead/back window in hours
            historical: If True, look for historical matches; otherwise upcoming
            limit: Maximum matches to return
        
        Returns:
            List of (match_id, league_id, fixture_id, kickoff, current_n_books)
        """
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        
        if historical:
            time_condition = f"tm.match_date < NOW() - INTERVAL '{time_window_hours} hours'"
        else:
            time_condition = f"tm.match_date BETWEEN NOW() AND NOW() + INTERVAL '{time_window_hours} hours'"
        
        query = f"""
            WITH match_odds_count AS (
                SELECT 
                    tm.match_id,
                    tm.league_id,
                    tm.fixture_id,
                    tm.match_date as kickoff,
                    COUNT(DISTINCT os.book_id) as n_books
                FROM training_matches tm
                LEFT JOIN odds_snapshots os ON os.match_id = tm.match_id 
                    AND os.market = 'h2h'
                WHERE {time_condition}
                    AND tm.fixture_id IS NOT NULL
                GROUP BY tm.match_id, tm.league_id, tm.fixture_id, tm.match_date
            )
            SELECT match_id, league_id, fixture_id, kickoff, COALESCE(n_books, 0)
            FROM match_odds_count
            WHERE COALESCE(n_books, 0) < %s
            ORDER BY kickoff DESC
            LIMIT %s
        """
        
        cursor.execute(query, (GapFillWorker.MIN_BOOKS_THRESHOLD, limit))
        results = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        logger.info(
            f"Found {len(results)} matches with < {GapFillWorker.MIN_BOOKS_THRESHOLD} books "
            f"({'historical' if historical else 'upcoming'})"
        )
        
        return results
    
    @staticmethod
    def gap_fill_batch(
        matches: List[Tuple[int, int, int, datetime, int]],
        batch_delay: float = 0.25
    ) -> Dict[str, int]:
        """
        Fill odds gaps for a batch of matches.
        
        Args:
            matches: List of (match_id, league_id, fixture_id, kickoff, n_books)
            batch_delay: Delay between fixtures in seconds
        
        Returns:
            Stats dict with filled_count, rows_inserted, errors
        """
        stats = {
            'filled_fixtures': 0,
            'total_rows_inserted': 0,
            'errors': 0,
            'already_sufficient': 0
        }
        
        for match_id, league_id, fixture_id, kickoff, current_n_books in matches:
            if current_n_books >= GapFillWorker.MIN_BOOKS_THRESHOLD:
                stats['already_sufficient'] += 1
                continue
            
            try:
                rows = ApiFootballIngestion.ingest_fixture_odds(
                    fixture_id=fixture_id,
                    match_id=match_id,
                    league_id=league_id,
                    kickoff_ts=kickoff,
                    live=False
                )
                
                if rows > 0:
                    stats['filled_fixtures'] += 1
                    stats['total_rows_inserted'] += rows
                    
                    ApiFootballIngestion.refresh_consensus_for_match(match_id)
                
                time.sleep(batch_delay)
                
            except Exception as e:
                logger.error(f"Error filling match {match_id} (fixture {fixture_id}): {str(e)}")
                stats['errors'] += 1
        
        logger.info(
            f"Gap fill batch complete: {stats['filled_fixtures']} fixtures filled, "
            f"{stats['total_rows_inserted']} rows inserted, {stats['errors']} errors"
        )
        
        return stats
    
    @staticmethod
    def run_gap_fill_for_upcoming(time_window_hours: int = 72):
        """Run gap fill for upcoming matches."""
        logger.info(f"Starting gap fill for upcoming matches (T-{time_window_hours}h)")
        
        matches = GapFillWorker.find_matches_without_odds(
            time_window_hours=time_window_hours,
            historical=False,
            limit=GapFillWorker.BATCH_SIZE
        )
        
        if not matches:
            logger.info("No upcoming matches need gap filling")
            return {'filled_fixtures': 0}
        
        return GapFillWorker.gap_fill_batch(matches, GapFillWorker.INTER_FIXTURE_DELAY)
    
    @staticmethod
    def run_historical_backfill(batch_size: int = 100, time_window_hours: int = 8760):
        """
        Run historical backfill for matches without odds.
        
        Args:
            batch_size: Number of matches to process
            time_window_hours: How far back to look (default: 1 year = 8760 hours)
        """
        logger.info(f"Starting historical backfill (batch_size={batch_size})")
        
        matches = GapFillWorker.find_matches_without_odds(
            time_window_hours=time_window_hours,
            historical=True,
            limit=batch_size
        )
        
        if not matches:
            logger.info("No historical matches need backfilling")
            return {'filled_fixtures': 0}
        
        return GapFillWorker.gap_fill_batch(matches, GapFillWorker.INTER_FIXTURE_DELAY)


def create_backfill_progress_table():
    """Create table to track backfill progress (idempotent)."""
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS backfill_state (
            match_id INT PRIMARY KEY,
            fixture_id INT,
            status VARCHAR(32),
            attempts INT DEFAULT 0,
            last_error TEXT,
            last_attempt_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT NOW()
        );
        
        CREATE INDEX IF NOT EXISTS idx_backfill_status 
        ON backfill_state(status);
    """)
    
    conn.commit()
    cursor.close()
    conn.close()
    
    logger.info("Backfill progress table ready")
