"""
Closing Odds Capture Job
Captures AGGREGATED closing odds within 90s window around kickoff for CLV validation
Stores consensus closing line (averaged across bookmakers) in closing_odds table
"""

import psycopg2
import logging
from datetime import datetime, timezone
from typing import Dict, Any
import os

logger = logging.getLogger(__name__)

class ClosingOddsCapture:
    """
    Captures aggregated closing odds for matches approaching/at kickoff
    Runs every 60s to catch odds right before match starts
    Stores CONSENSUS closing line (averaged across bookmakers)
    """
    
    def __init__(self):
        self.database_url = os.getenv('DATABASE_URL')
    
    def capture_closing_odds(self) -> Dict[str, Any]:
        """
        Capture AGGREGATED closing odds for matches at kickoff (within ±90s window)
        Calculates consensus closing line by averaging across all bookmakers
        Returns stats about captured odds
        """
        stats = {
            'matches_in_window': 0,
            'odds_captured': 0,
            'already_captured': 0,
            'errors': 0
        }
        
        try:
            with psycopg2.connect(self.database_url) as conn:
                cursor = conn.cursor()
                
                # Capture AGGREGATED closing odds within 90s window
                # Average across all bookmakers to get consensus closing line
                capture_query = """
                WITH kickoff_matches AS (
                    -- Find matches in kickoff window (±10 min for resilience)
                    SELECT match_id, kickoff_at
                    FROM fixtures
                    WHERE kickoff_at BETWEEN NOW() - INTERVAL '10 minutes' AND NOW() + INTERVAL '10 minutes'
                      AND status IN ('scheduled', 'live')
                ),
                latest_odds AS (
                    -- Get most recent odds snapshot for each match/book/outcome (last 30 min)
                    SELECT DISTINCT ON (os.match_id, os.book_id, os.outcome)
                        os.match_id,
                        os.book_id,
                        os.outcome,
                        os.odds_decimal,
                        os.ts_snapshot
                    FROM odds_snapshots os
                    JOIN kickoff_matches km USING(match_id)
                    WHERE os.ts_snapshot > NOW() - INTERVAL '30 minutes'
                      AND os.market = 'h2h'
                    ORDER BY os.match_id, os.book_id, os.outcome, os.ts_snapshot DESC
                ),
                aggregated_closing AS (
                    -- Aggregate across bookmakers to get consensus closing line
                    SELECT 
                        match_id,
                        AVG(CASE WHEN outcome = 'home' THEN odds_decimal END) as h_close_odds,
                        AVG(CASE WHEN outcome = 'draw' THEN odds_decimal END) as d_close_odds,
                        AVG(CASE WHEN outcome = 'away' THEN odds_decimal END) as a_close_odds,
                        MAX(ts_snapshot) as closing_time,
                        COUNT(DISTINCT book_id) as num_books,
                        COUNT(*) as samples_used
                    FROM latest_odds
                    GROUP BY match_id
                    HAVING COUNT(DISTINCT book_id) >= 3  -- Require at least 3 bookmakers for consensus
                       AND COUNT(DISTINCT outcome) = 3   -- Must have home/draw/away
                )
                INSERT INTO closing_odds (
                    match_id,
                    h_close_odds,
                    d_close_odds,
                    a_close_odds,
                    closing_time,
                    avg_books_closing,
                    method_used,
                    samples_used,
                    created_at
                )
                SELECT 
                    ac.match_id,
                    ac.h_close_odds,
                    ac.d_close_odds,
                    ac.a_close_odds,
                    ac.closing_time,
                    ac.num_books,
                    '90s_snapshot' as method_used,
                    ac.samples_used,
                    NOW() as created_at
                FROM aggregated_closing ac
                LEFT JOIN closing_odds co USING(match_id)
                WHERE co.match_id IS NULL  -- Don't re-capture
                RETURNING match_id;
                """
                
                cursor.execute(capture_query)
                captured = cursor.fetchall()
                stats['odds_captured'] = len(captured)
                conn.commit()
                
                # Count matches in window
                cursor.execute("""
                    SELECT COUNT(DISTINCT match_id)
                    FROM fixtures
                    WHERE kickoff_at BETWEEN NOW() - INTERVAL '90 seconds' AND NOW() + INTERVAL '90 seconds'
                      AND status = 'scheduled'
                """)
                result = cursor.fetchone()
                stats['matches_in_window'] = result[0] if result else 0
                
                # Count already captured
                cursor.execute("""
                    SELECT COUNT(DISTINCT co.match_id)
                    FROM closing_odds co
                    JOIN fixtures f USING(match_id)
                    WHERE f.kickoff_at BETWEEN NOW() - INTERVAL '5 minutes' AND NOW()
                """)
                result = cursor.fetchone()
                stats['already_captured'] = result[0] if result else 0
                
                if stats['odds_captured'] > 0:
                    logger.info(f"📸 Closing capture: {stats['odds_captured']} consensus lines captured for {stats['matches_in_window']} matches in KO window")
                elif stats['matches_in_window'] > 0:
                    logger.debug(f"📸 Closing capture: No new odds (already captured for {stats['already_captured']} matches)")
                
        except Exception as e:
            logger.error(f"Error capturing closing odds: {e}")
            stats['errors'] = 1
        
        return stats
    
    def update_closing_capture_rate_metric(self) -> float:
        """
        Calculate and update closing_capture_rate metric
        Returns: Percentage of fixtures with closing odds in last 24h
        """
        try:
            with psycopg2.connect(self.database_url) as conn:
                cursor = conn.cursor()
                
                # Calculate capture rate for finished matches in last 24h
                cursor.execute("""
                    SELECT 
                        COUNT(DISTINCT f.match_id) as total_finished,
                        COUNT(DISTINCT co.match_id) as with_closing
                    FROM fixtures f
                    LEFT JOIN closing_odds co USING(match_id)
                    WHERE f.kickoff_at > NOW() - INTERVAL '24 hours'
                      AND f.kickoff_at < NOW()
                      AND f.status = 'finished';
                """)
                
                result = cursor.fetchone()
                if result and result[0] > 0:
                    total, captured = result
                    capture_rate = (captured / total) * 100.0
                    
                    # Update metric if available
                    try:
                        from models.metrics import closing_capture_rate
                        closing_capture_rate.set(capture_rate)
                    except ImportError:
                        pass
                    
                    return capture_rate
                
        except Exception as e:
            logger.debug(f"Error calculating closing capture rate: {e}")
        
        return 0.0


def run_closing_capture():
    """Standalone function for scheduler integration"""
    capturer = ClosingOddsCapture()
    stats = capturer.capture_closing_odds()
    
    # Update metric every run
    capture_rate = capturer.update_closing_capture_rate_metric()
    stats['capture_rate_24h'] = capture_rate
    
    return stats
