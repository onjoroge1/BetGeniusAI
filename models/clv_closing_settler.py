"""
CLV Club Closing Settler
Computes closing odds from samples and settles alerts with realized CLV
Runs every minute to find matches that just kicked off
"""

import os
import psycopg2
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional, Tuple
import logging

logger = logging.getLogger(__name__)

class CLVClosingSettler:
    """
    Settles CLV alerts by computing closing line from samples
    Runs at T+2m or when results are ingested
    """
    
    def __init__(self):
        self.database_url = os.environ.get('DATABASE_URL')
        
        # Closing window: last 5 minutes before kickoff
        self.CLOSE_WINDOW_SEC = 300
        
        # Grace period: allow 1 minute after KO for late samples
        self.GRACE_PERIOD_SEC = 60
    
    def _get_matches_to_settle(self) -> List[Dict[str, Any]]:
        """
        Find matches that kicked off 2-10 minutes ago and haven't been settled
        
        Returns:
            List of dicts with match_id, kickoff_at
        """
        try:
            with psycopg2.connect(self.database_url) as conn:
                cursor = conn.cursor()
                
                now = datetime.now(timezone.utc)
                settle_start = now - timedelta(minutes=10)  # Up to 10 min ago
                settle_end = now - timedelta(minutes=2)     # At least 2 min ago
                
                # Find matches with alerts but no realized CLV yet
                cursor.execute("""
                    SELECT DISTINCT
                        m.match_id,
                        m.match_date_utc as kickoff_at
                    FROM matches m
                    INNER JOIN clv_alerts a ON m.match_id = a.match_id
                    LEFT JOIN clv_realized r ON a.alert_id = r.alert_id
                    WHERE m.match_date_utc >= %s
                      AND m.match_date_utc <= %s
                      AND r.alert_id IS NULL
                    ORDER BY m.match_date_utc
                """, (settle_start, settle_end))
                
                matches = []
                for row in cursor.fetchall():
                    match_id, kickoff_at = row
                    matches.append({
                        'match_id': match_id,
                        'kickoff_at': kickoff_at
                    })
                
                return matches
                
        except Exception as e:
            logger.error(f"Error fetching matches to settle: {e}")
            return []
    
    def _load_closing_samples(self, match_id: int, outcome: str, 
                             window_start: datetime, window_end: datetime) -> List[Dict[str, Any]]:
        """
        Load closing samples for a specific outcome within time window
        
        Returns:
            List of {odds_dec, volume, ts} dicts
        """
        try:
            with psycopg2.connect(self.database_url) as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT composite_odds_dec, volume, ts
                    FROM clv_closing_feed
                    WHERE match_id = %s
                      AND outcome = %s
                      AND ts >= %s
                      AND ts <= %s
                    ORDER BY ts ASC
                """, (match_id, outcome, window_start, window_end))
                
                samples = []
                for row in cursor.fetchall():
                    odds_dec, volume, ts = row
                    samples.append({
                        'odds_dec': float(odds_dec),
                        'volume': float(volume) if volume else None,
                        'ts': ts
                    })
                
                return samples
                
        except Exception as e:
            logger.error(f"Error loading closing samples: {e}")
            return []
    
    def _compute_closing_odds(self, samples: List[Dict[str, Any]]) -> Tuple[Optional[float], str, int]:
        """
        Compute closing odds from samples using LAST5_VWAP or fallback to LAST_TICK
        
        Args:
            samples: List of {odds_dec, volume, ts} dicts
            
        Returns:
            (closing_odds_dec, method_used, num_samples)
        """
        if not samples:
            return None, "NO_DATA", 0
        
        # Need at least 3 samples for LAST5_VWAP
        if len(samples) >= 3:
            # Check if we have volume data
            has_volume = any(s['volume'] is not None for s in samples)
            
            if has_volume:
                # Volume-weighted average
                numerator = sum(s['odds_dec'] * (s['volume'] or 1.0) for s in samples)
                denominator = sum((s['volume'] or 1.0) for s in samples)
                closing_odds = round(numerator / denominator, 4)
                return closing_odds, "LAST5_VWAP", len(samples)
            else:
                # Time-weighted trimmed mean (robust against spikes)
                arr = sorted(s['odds_dec'] for s in samples)
                trim_idx = max(0, int(0.1 * len(arr)))  # 10% trim each tail
                trimmed = arr[trim_idx:len(arr)-trim_idx] if trim_idx > 0 else arr
                
                if trimmed:
                    closing_odds = round(sum(trimmed) / len(trimmed), 4)
                    return closing_odds, "LAST5_VWAP", len(samples)
        
        # Fallback to last tick
        last_sample = max(samples, key=lambda s: s['ts'])
        return round(last_sample['odds_dec'], 4), "LAST_TICK", 1
    
    def _get_match_outcome(self, match_id: int) -> Optional[str]:
        """
        Get match outcome from match_results table
        
        Returns:
            'H', 'D', 'A' or None if not available
        """
        try:
            with psycopg2.connect(self.database_url) as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT outcome
                    FROM match_results
                    WHERE match_id = %s
                """, (match_id,))
                
                row = cursor.fetchone()
                return row[0] if row else None
                
        except Exception as e:
            logger.debug(f"Match {match_id} result not yet available: {e}")
            return None
    
    def _settle_alerts_for_match(self, match_id: int, kickoff_at: datetime, 
                                 realized: Dict[str, Dict[str, Any]], 
                                 match_outcome: Optional[str]) -> int:
        """
        Update clv_realized for all alerts on this match
        
        Returns:
            Number of alerts settled
        """
        try:
            with psycopg2.connect(self.database_url) as conn:
                cursor = conn.cursor()
                
                # Load alerts for this match
                cursor.execute("""
                    SELECT alert_id, outcome, best_odds_dec
                    FROM clv_alerts
                    WHERE match_id = %s
                """, (match_id,))
                
                alerts = cursor.fetchall()
                settled_count = 0
                
                for alert_id, outcome, best_odds_dec in alerts:
                    closing_data = realized.get(outcome)
                    
                    if not closing_data or closing_data['odds'] is None:
                        logger.warning(f"No closing data for alert {alert_id} outcome {outcome}")
                        continue
                    
                    closing_odds = closing_data['odds']
                    closing_method = closing_data['method']
                    closing_samples = closing_data['n']
                    
                    # Calculate realized CLV
                    realized_clv_pct = round(100.0 * (closing_odds - best_odds_dec) / best_odds_dec, 3)
                    
                    # Determine if bet won (only if we have match outcome)
                    win = (match_outcome == outcome) if match_outcome else None
                    
                    # UPSERT into clv_realized
                    if win is not None:
                        cursor.execute("""
                            INSERT INTO clv_realized (
                                alert_id, closing_odds_dec, realized_clv_pct,
                                match_outcome, win, closing_method,
                                closing_samples, closing_window_sec, settled_at
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                            ON CONFLICT (alert_id) DO UPDATE
                            SET closing_odds_dec = EXCLUDED.closing_odds_dec,
                                realized_clv_pct = EXCLUDED.realized_clv_pct,
                                match_outcome = EXCLUDED.match_outcome,
                                win = EXCLUDED.win,
                                closing_method = EXCLUDED.closing_method,
                                closing_samples = EXCLUDED.closing_samples,
                                closing_window_sec = EXCLUDED.closing_window_sec,
                                settled_at = EXCLUDED.settled_at
                        """, (
                            str(alert_id), closing_odds, realized_clv_pct,
                            match_outcome, win, closing_method,
                            closing_samples, self.CLOSE_WINDOW_SEC
                        ))
                    else:
                        # No match outcome yet - store partial data
                        cursor.execute("""
                            INSERT INTO clv_realized (
                                alert_id, closing_odds_dec, realized_clv_pct,
                                match_outcome, win, closing_method,
                                closing_samples, closing_window_sec, settled_at
                            ) VALUES (%s, %s, %s, 'U', FALSE, %s, %s, %s, NOW())
                            ON CONFLICT (alert_id) DO NOTHING
                        """, (
                            str(alert_id), closing_odds, realized_clv_pct,
                            closing_method, closing_samples, self.CLOSE_WINDOW_SEC
                        ))
                    
                    settled_count += 1
                
                conn.commit()
                return settled_count
                
        except Exception as e:
            logger.error(f"Error settling alerts for match {match_id}: {e}")
            return 0
    
    def run_cycle(self):
        """
        Main settling cycle - runs every minute
        """
        try:
            matches = self._get_matches_to_settle()
            
            if not matches:
                logger.debug("⚖️ Closing Settler: No matches to settle")
                return
            
            total_settled = 0
            
            for match in matches:
                match_id = match['match_id']
                kickoff_at = match['kickoff_at']
                
                # Define closing window: [KO - 5m, KO + 1m]
                window_start = kickoff_at - timedelta(seconds=self.CLOSE_WINDOW_SEC)
                window_end = kickoff_at + timedelta(seconds=self.GRACE_PERIOD_SEC)
                
                # Compute closing odds for each outcome
                realized = {}
                for outcome in ('H', 'D', 'A'):
                    samples = self._load_closing_samples(match_id, outcome, window_start, window_end)
                    odds, method, n = self._compute_closing_odds(samples)
                    realized[outcome] = {'odds': odds, 'method': method, 'n': n}
                
                # Get match outcome (may be None if not available yet)
                match_outcome = self._get_match_outcome(match_id)
                
                # Settle alerts
                settled = self._settle_alerts_for_match(match_id, kickoff_at, realized, match_outcome)
                total_settled += settled
                
                if settled > 0:
                    logger.info(
                        f"⚖️ Closing Settler: Match {match_id} - settled {settled} alerts, "
                        f"methods: H={realized['H']['method']}, D={realized['D']['method']}, "
                        f"A={realized['A']['method']}"
                    )
            
            if total_settled > 0:
                logger.info(f"⚖️ Closing Settler: Cycle complete - {total_settled} alerts settled")
            
        except Exception as e:
            logger.error(f"Closing settler cycle failed: {e}", exc_info=True)
