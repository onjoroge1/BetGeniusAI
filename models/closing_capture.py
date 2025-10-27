"""
Closing Odds Capture Job
Captures closing odds within 90s window around kickoff for CLV validation
"""

import psycopg2
import logging
from datetime import datetime, timezone
from typing import Dict, Any
import os

logger = logging.getLogger(__name__)

class ClosingOddsCapture:
    """
    Captures closing odds for matches approaching/at kickoff
    Runs every 60s to catch odds right before match starts
    """
    
    def __init__(self):
        self.database_url = os.getenv('DATABASE_URL')
    
    def capture_closing_odds(self) -> Dict[str, Any]:
        """
        Capture closing odds for matches at kickoff (within ±90s window)
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
                
                # Capture closing odds within 90s window
                # Uses most recent snapshot per (match_id, bookmaker_id, market)
                capture_query = """
                WITH recent_snapshots AS (
                    SELECT DISTINCT ON (os.match_id, os.bookmaker, os.market)
                        os.match_id,
                        os.bookmaker,
                        os.market,
                        os.h_odds_dec,
                        os.d_odds_dec,
                        os.a_odds_dec,
                        os.ts_snapshot,
                        f.kickoff_at
                    FROM odds_snapshots os
                    JOIN fixtures f USING(match_id)
                    WHERE os.ts_snapshot > NOW() - INTERVAL '5 minutes'
                      AND f.kickoff_at BETWEEN NOW() - INTERVAL '90 seconds' AND NOW() + INTERVAL '90 seconds'
                      AND f.status = 'scheduled'
                    ORDER BY os.match_id, os.bookmaker, os.market, os.ts_snapshot DESC
                )
                INSERT INTO closing_odds (
                    match_id, bookmaker_id, market,
                    h_odds_dec, d_odds_dec, a_odds_dec,
                    ts_closing, created_at
                )
                SELECT 
                    rs.match_id,
                    rs.bookmaker as bookmaker_id,
                    rs.market,
                    rs.h_odds_dec,
                    rs.d_odds_dec,
                    rs.a_odds_dec,
                    rs.ts_snapshot as ts_closing,
                    NOW() as created_at
                FROM recent_snapshots rs
                LEFT JOIN closing_odds co ON rs.match_id = co.match_id 
                    AND rs.bookmaker = co.bookmaker_id 
                    AND rs.market = co.market
                WHERE co.match_id IS NULL
                ON CONFLICT (match_id, bookmaker_id, market) DO NOTHING
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
                    logger.info(f"📸 Closing capture: {stats['odds_captured']} odds captured for {stats['matches_in_window']} matches in KO window")
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
