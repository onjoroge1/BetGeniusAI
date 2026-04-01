"""
CLV Club Closing Sampler
Collects composite odds samples near kickoff for closing line computation
Runs every 30-60 seconds in the T-6m to T+2m window
"""

import os
import psycopg2
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional, Tuple
import logging

from models.clv_club import CLVClubEngine, BookOdds

logger = logging.getLogger(__name__)

class CLVClosingSampler:
    """
    Samples composite odds near kickoff for closing line calculation
    Does NOT emit alerts - only records data for later settling
    """
    
    def __init__(self):
        self.engine = CLVClubEngine()
        self.database_url = os.environ.get('DATABASE_URL')
        
        # Sampling window: 20 minutes before KO to 5 minutes after
        # Wider window is more forgiving of server restarts and sparse data
        self.PRE_KO_MINUTES = 20
        self.POST_KO_MINUTES = 5
    
    def _get_fixtures_near_kickoff(self) -> List[Dict[str, Any]]:
        """
        Get fixtures in sampling window (T-6m to T+2m)
        Uses canonical fixtures table (not matches) for reliability
        
        Returns:
            List of dicts with match_id, league, kickoff_time
        """
        try:
            with psycopg2.connect(self.database_url) as conn:
                cursor = conn.cursor()
                
                now = datetime.now(timezone.utc)
                
                # Proper BETWEEN window: now - 2min to now + 6min
                # This captures fixtures that are finishing or about to finish
                cursor.execute("""
                    SELECT 
                        f.match_id,
                        COALESCE(f.league_name, CAST(f.league_id AS text)) as league_name,
                        f.kickoff_at
                    FROM fixtures f
                    WHERE f.kickoff_at BETWEEN %s AND %s
                      AND f.status IN ('scheduled', 'live')
                    ORDER BY f.kickoff_at
                """, (
                    now - timedelta(minutes=self.POST_KO_MINUTES),  # T-2m
                    now + timedelta(minutes=self.PRE_KO_MINUTES)    # T+6m
                ))
                
                fixtures = []
                for row in cursor.fetchall():
                    match_id, league, kickoff_at = row
                    fixtures.append({
                        'match_id': match_id,
                        'league': league or 'Unknown',
                        'kickoff_at': kickoff_at
                    })
                
                
                # Observability: log window info if candidates found
                if fixtures:
                    logger.info(f"📊 Closing Sampler: Found {len(fixtures)} fixtures in window")
                
                return fixtures
                
        except Exception as e:
            logger.error(f"Error fetching fixtures near kickoff: {e}")
            return []
    
    def _check_zero_candidate_alert(self):
        """
        Alert if we have 0 candidates but upcoming fixtures exist
        Prevents silent failure when data integrity issues occur
        """
        try:
            with psycopg2.connect(self.database_url) as conn:
                cursor = conn.cursor()
                
                # Check if we have any fixtures in next 24h
                cursor.execute("""
                    SELECT COUNT(*) FROM fixtures
                    WHERE kickoff_at BETWEEN now() AND now() + INTERVAL '24 hours'
                """)
                
                upcoming_count = cursor.fetchone()[0]
                
                if upcoming_count > 0:
                    # We have upcoming fixtures but found none in window - this is expected
                    # Only alert if we're missing fixtures that should be in window
                    now = datetime.now(timezone.utc)
                    window_start = now - timedelta(minutes=self.POST_KO_MINUTES)
                    window_end = now + timedelta(minutes=self.PRE_KO_MINUTES)
                    
                    logger.debug(
                        f"📊 Closing Sampler: 0 candidates in window ({window_start.strftime('%H:%M:%S')} to {window_end.strftime('%H:%M:%S')}), "
                        f"but {upcoming_count} fixtures scheduled in next 24h"
                    )
                    
                    # Check for orphaned odds (data integrity)
                    cursor.execute("""
                        SELECT COUNT(*) FROM odds_snapshots s
                        LEFT JOIN fixtures f ON f.match_id = s.match_id
                        WHERE f.match_id IS NULL
                          AND s.ts_snapshot > now() - INTERVAL '24 hours'
                    """)
                    
                    orphans = cursor.fetchone()[0]
                    if orphans > 0:
                        logger.error(
                            f"🚨 DATA INTEGRITY ALERT: {orphans} orphaned odds_snapshots in last 24h "
                            f"(match_ids not in fixtures table)"
                        )
                
        except Exception as e:
            logger.warning(f"Zero-candidate check failed: {e}")
    
    def _gather_fresh_odds(self, match_id: int, staleness_sec: int = 120) -> Dict[str, List[BookOdds]]:
        """
        Gather fresh odds from odds_snapshots, grouped by outcome
        Uses same de-juicing and desk-group dedup as alert producer
        
        Returns:
            {"H": [BookOdds, ...], "D": [...], "A": [...]}
        """
        try:
            with psycopg2.connect(self.database_url) as conn:
                cursor = conn.cursor()
                
                now = datetime.now(timezone.utc)
                cutoff = now - timedelta(seconds=staleness_sec)
                
                # Fetch fresh odds with desk group deduplication
                cursor.execute("""
                    SELECT DISTINCT ON (os.outcome, COALESCE(b.desk_group, os.book_id))
                        os.outcome,
                        os.book_id,
                        os.odds_dec,
                        COALESCE(b.desk_group, os.book_id) as desk_group,
                        os.ts_snapshot
                    FROM odds_snapshots os
                    LEFT JOIN bookmakers b ON (
                        -- Handle both numeric book_ids and text format "apif:13"
                        CASE 
                            WHEN os.book_id ~ '^[0-9]+$' THEN os.book_id::INTEGER = b.bookmaker_id
                            WHEN os.book_id LIKE 'apif:%' THEN split_part(os.book_id, ':', 2)::INTEGER = b.bookmaker_id
                            ELSE FALSE
                        END
                    )
                    WHERE os.match_id = %s
                      AND os.ts_snapshot > %s
                    ORDER BY os.outcome, COALESCE(b.desk_group, os.book_id), os.ts_snapshot DESC
                """, (match_id, cutoff))
                
                # Group by outcome
                odds_by_outcome = {"H": [], "D": [], "A": []}
                
                for row in cursor.fetchall():
                    outcome, book_id, odds_dec, desk_group, ts = row
                    
                    if outcome in odds_by_outcome:
                        odds_by_outcome[outcome].append(
                            BookOdds(
                                book_id=book_id,
                                odds_dec=float(odds_dec),
                                desk_group=desk_group or f"book_{book_id}"
                            )
                        )
                
                return odds_by_outcome
                
        except Exception as e:
            logger.error(f"Error gathering odds for match {match_id}: {e}")
            return {"H": [], "D": [], "A": []}
    
    def _build_composite_probs(self, odds_by_outcome: Dict[str, List[BookOdds]]) -> Optional[Dict[str, Any]]:
        """
        Build de-juiced, trimmed consensus probabilities for all outcomes
        
        Returns:
            {"H": pH, "D": pD, "A": pA, "books_used": n} or None
        """
        # Need at least 3 independent books for each outcome
        min_books = 3
        if any(len(odds_by_outcome[k]) < min_books for k in ("H", "D", "A")):
            return None
        
        # De-juice each bookmaker's line
        probs_h_list = []
        probs_d_list = []
        probs_a_list = []
        
        # Build matrix: for each book, de-juice their H/D/A line
        books_seen = set()
        
        for outcome in ("H", "D", "A"):
            for book_odds in odds_by_outcome[outcome]:
                books_seen.add(book_odds.desk_group)
        
        # For simplicity, take the first odds from each desk group
        for desk_group in books_seen:
            try:
                odds_h = next((b.odds_dec for b in odds_by_outcome["H"] if b.desk_group == desk_group), None)
                odds_d = next((b.odds_dec for b in odds_by_outcome["D"] if b.desk_group == desk_group), None)
                odds_a = next((b.odds_dec for b in odds_by_outcome["A"] if b.desk_group == desk_group), None)
                
                if odds_h and odds_d and odds_a:
                    pH, pD, pA = self.engine.dejuice_three_way(odds_h, odds_d, odds_a)
                    probs_h_list.append(pH)
                    probs_d_list.append(pD)
                    probs_a_list.append(pA)
            except Exception as e:
                logger.warning(f"Failed to de-juice for desk {desk_group}: {e}")
                continue
        
        if len(probs_h_list) < min_books:
            return None
        
        # Trimmed mean consensus
        pH = self.engine.robust_consensus(probs_h_list)
        pD = self.engine.robust_consensus(probs_d_list)
        pA = self.engine.robust_consensus(probs_a_list)
        
        if pH is None or pD is None or pA is None:
            return None
        
        return {
            "H": pH,
            "D": pD,
            "A": pA,
            "books_used": len(probs_h_list)
        }
    
    def _store_closing_sample(self, match_id: int, now_utc: datetime, 
                             composite: Dict[str, Any]) -> int:
        """
        Store one sample (3 rows: H/D/A) in clv_closing_feed
        
        Returns:
            Number of rows inserted (0 or 3)
        """
        try:
            with psycopg2.connect(self.database_url) as conn:
                cursor = conn.cursor()
                
                # Convert probs to decimal odds
                odds_h = 1.0 / max(1e-12, composite["H"])
                odds_d = 1.0 / max(1e-12, composite["D"])
                odds_a = 1.0 / max(1e-12, composite["A"])
                
                books_used = composite["books_used"]
                
                # Insert 3 rows (one per outcome)
                for outcome, odds_dec in [("H", odds_h), ("D", odds_d), ("A", odds_a)]:
                    cursor.execute("""
                        INSERT INTO clv_closing_feed (
                            match_id, ts, outcome, composite_odds_dec,
                            volume, books_used, desk_groups
                        ) VALUES (%s, %s, %s, %s, NULL, %s, %s)
                        ON CONFLICT (match_id, ts, outcome) DO UPDATE
                        SET composite_odds_dec = EXCLUDED.composite_odds_dec,
                            books_used = EXCLUDED.books_used,
                            desk_groups = EXCLUDED.desk_groups
                    """, (match_id, now_utc, outcome, round(odds_dec, 4), books_used, books_used))
                
                conn.commit()
                return 3
                
        except Exception as e:
            logger.error(f"Error storing closing sample for match {match_id}: {e}")
            return 0
    
    def run_cycle(self):
        """
        Main sampling cycle - runs every 30-60 seconds
        """
        try:
            fixtures = self._get_fixtures_near_kickoff()
            
            # Zero-candidate alerting: If we have upcoming fixtures but find none in window
            if not fixtures:
                self._check_zero_candidate_alert()
                logger.debug("📊 Closing Sampler: No fixtures in window (T-6m to T+2m)")
                return
            
            now_utc = datetime.now(timezone.utc)
            samples_stored = 0
            
            for fx in fixtures:
                match_id = fx['match_id']
                league = fx['league']
                
                # Gather fresh odds
                odds_by_outcome = self._gather_fresh_odds(match_id, staleness_sec=120)
                
                # Build composite
                composite = self._build_composite_probs(odds_by_outcome)
                
                if not composite:
                    logger.debug(f"📊 Closing Sampler: Match {match_id} - insufficient data")
                    continue
                
                # Store sample
                stored = self._store_closing_sample(match_id, now_utc, composite)
                samples_stored += stored
                
                if stored > 0:
                    logger.info(
                        f"📊 Closing Sampler: Match {match_id} ({league}) - "
                        f"stored 3 samples, {composite['books_used']} books"
                    )
            
            if samples_stored > 0:
                logger.info(f"📊 Closing Sampler: Cycle complete - {samples_stored} samples stored")
            
        except Exception as e:
            logger.error(f"Closing sampler cycle failed: {e}", exc_info=True)
