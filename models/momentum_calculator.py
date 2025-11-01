import os
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from math import exp
import json

logger = logging.getLogger(__name__)


class MomentumCalculator:
    """
    Phase 2 Momentum Engine
    
    Calculates rolling 0-100 momentum scores for live matches based on:
    - Shots on target (weighted 0.35)
    - Dangerous attacks (weighted 0.20)
    - Possession differential (weighted 0.10)
    - xG differential (weighted 0.20)
    - Odds velocity (weighted 0.15)
    - Discipline modifiers (red cards)
    
    Uses exponential decay (half-life 6 minutes) to emphasize recent events
    """
    
    def __init__(self):
        self.db_url = os.getenv("DATABASE_URL")
        
        # Momentum weights (must sum to 1.0)
        self.w_shots = 0.35
        self.w_dang_att = 0.20
        self.w_poss = 0.10
        self.w_xg = 0.20
        self.w_odds_vel = 0.15
        
        # Exponential decay parameters
        self.half_life_minutes = 6.0  # Recent events matter most
        self.window_minutes = 12  # Look back 12 minutes
        
        # Scaling factors (empirical calibration)
        self.scale_shots = 1.5
        self.scale_dang_att = 6.0
        self.scale_poss = 0.25
        self.scale_xg = 0.6
        self.scale_odds_vel = 0.06
        
        # Red card momentum boost
        self.red_card_boost = 0.9
    
    def exp_decay(self, minutes_ago: float) -> float:
        """
        Exponential decay function
        half_life 6 minutes → recent events have 2x weight vs 6min ago
        """
        return exp(-0.693 * minutes_ago / self.half_life_minutes)
    
    def bounded(self, x: float, lo: float = -2.5, hi: float = 2.5) -> float:
        """Clamp value to range"""
        return max(lo, min(hi, x))
    
    def to_0_100(self, x: float, lo: float = -3.0, hi: float = 3.0) -> int:
        """Convert z-score to 0-100 scale"""
        x = max(lo, min(hi, x))
        return round((x - lo) * 100.0 / (hi - lo))
    
    def get_live_matches(self) -> List[Dict]:
        """Get currently live matches with API-Football IDs"""
        with psycopg2.connect(self.db_url) as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            cursor.execute("""
                SELECT 
                    f.match_id,
                    f.home_team,
                    f.away_team,
                    f.kickoff_at,
                    m.api_football_fixture_id,
                    EXTRACT(EPOCH FROM (NOW() - f.kickoff_at)) / 60 AS minutes_elapsed
                FROM fixtures f
                JOIN matches m ON f.match_id = m.match_id
                WHERE f.status = 'scheduled'
                  AND f.kickoff_at <= NOW()
                  AND f.kickoff_at > NOW() - INTERVAL '3 hours'
                  AND m.api_football_fixture_id IS NOT NULL
            """)
            
            return cursor.fetchall()
    
    def get_stats_window(self, match_id: int, window_minutes: int = 12) -> List[Dict]:
        """
        Get live stats snapshots from the last N minutes
        Returns chronological list (oldest first)
        """
        with psycopg2.connect(self.db_url) as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            cursor.execute("""
                SELECT 
                    match_id,
                    timestamp,
                    minute,
                    home_score,
                    away_score,
                    home_shots_on_target,
                    away_shots_on_target,
                    home_possession,
                    away_possession,
                    EXTRACT(EPOCH FROM (NOW() - timestamp)) / 60 AS minutes_ago
                FROM live_match_stats
                WHERE match_id = %s
                  AND timestamp > NOW() - INTERVAL '%s minutes'
                ORDER BY timestamp ASC
            """, (match_id, window_minutes))
            
            return cursor.fetchall()
    
    def get_odds_velocity_window(self, match_id: int, window_minutes: int = 12) -> List[Dict]:
        """Get odds velocity snapshots from the last N minutes"""
        with psycopg2.connect(self.db_url) as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            cursor.execute("""
                SELECT 
                    match_id,
                    timestamp,
                    velocity_home_win,
                    velocity_draw,
                    velocity_away_win,
                    EXTRACT(EPOCH FROM (NOW() - timestamp)) / 60 AS minutes_ago
                FROM odds_velocity
                WHERE match_id = %s
                  AND timestamp > NOW() - INTERVAL '%s minutes'
                ORDER BY timestamp ASC
            """, (match_id, window_minutes))
            
            return cursor.fetchall()
    
    def get_match_events(self, match_id: int) -> Dict:
        """Get match events (red cards, etc.)"""
        with psycopg2.connect(self.db_url) as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            cursor.execute("""
                SELECT events
                FROM live_match_events
                WHERE match_id = %s
                ORDER BY timestamp DESC
                LIMIT 1
            """, (match_id,))
            
            row = cursor.fetchone()
            if row and row['events']:
                return row['events']
            return {}
    
    def compute_momentum(self, match_id: int) -> Optional[Tuple[int, int, Dict]]:
        """
        Compute momentum scores for a match
        
        Returns: (momentum_home, momentum_away, driver_summary)
        """
        stats_window = self.get_stats_window(match_id, self.window_minutes)
        odds_window = self.get_odds_velocity_window(match_id, self.window_minutes)
        
        if not stats_window:
            logger.warning(f"No stats data for match {match_id}")
            return None
        
        # Build decayed aggregates
        agg = {
            "shots_on_tgt_home": 0.0,
            "shots_on_tgt_away": 0.0,
            "dang_att_home": 0.0,
            "dang_att_away": 0.0,
            "poss_home": 0.0,
            "poss_away": 0.0,
            "xg_home": 0.0,
            "xg_away": 0.0,
            "prob_move_home": 0.0,
            "prob_move_draw": 0.0,
            "prob_move_away": 0.0,
            "w": 0.0
        }
        
        # Process stats with exponential decay
        for snap in reversed(stats_window):  # Most recent first for indexing
            minutes_ago = snap['minutes_ago'] or 0
            w = self.exp_decay(minutes_ago)
            agg["w"] += w
            
            # Shots on target differential
            sot_home = snap.get('home_shots_on_target') or 0
            sot_away = snap.get('away_shots_on_target') or 0
            agg["shots_on_tgt_home"] += sot_home * w
            agg["shots_on_tgt_away"] += sot_away * w
            
            # Possession
            poss_home = snap.get('home_possession') or 0
            poss_away = snap.get('away_possession') or 0
            agg["poss_home"] += poss_home * w
            agg["poss_away"] += poss_away * w
        
        # Process odds velocity
        odds_map = {snap['timestamp']: snap for snap in odds_window}
        for snap in reversed(stats_window):
            minutes_ago = snap['minutes_ago'] or 0
            w = self.exp_decay(minutes_ago)
            
            # Find matching odds snapshot (within 2 minutes)
            closest_odds = None
            for odds_snap in odds_window:
                if abs((snap['timestamp'] - odds_snap['timestamp']).total_seconds()) < 120:
                    closest_odds = odds_snap
                    break
            
            if closest_odds:
                agg["prob_move_home"] += (closest_odds.get('velocity_home_win') or 0) * w
                agg["prob_move_draw"] += (closest_odds.get('velocity_draw') or 0) * w
                agg["prob_move_away"] += (closest_odds.get('velocity_away_win') or 0) * w
        
        # Normalize by total weight
        if agg["w"] > 0:
            for k in list(agg.keys()):
                if k != "w":
                    agg[k] /= agg["w"]
        
        # Build differentials
        shot_diff = agg["shots_on_tgt_home"] - agg["shots_on_tgt_away"]
        dang_diff = 0  # Not available yet - placeholder
        poss_diff = (agg["poss_home"] - agg["poss_away"]) / 100.0
        xg_diff = 0  # Not available yet - placeholder
        odds_bias = agg["prob_move_home"] - agg["prob_move_away"]
        
        # Scale to pseudo-z ranges
        z_shot = self.bounded(shot_diff / self.scale_shots)
        z_dang = self.bounded(dang_diff / self.scale_dang_att)
        z_poss = self.bounded(poss_diff / self.scale_poss)
        z_xg = self.bounded(xg_diff / self.scale_xg)
        z_odds = self.bounded(odds_bias / self.scale_odds_vel)
        
        # Weighted sum
        score_home = (
            self.w_shots * z_shot +
            self.w_dang_att * z_dang +
            self.w_poss * z_poss +
            self.w_xg * z_xg +
            self.w_odds_vel * z_odds
        )
        score_away = -score_home  # Symmetric
        
        # Red card modifier
        events = self.get_match_events(match_id)
        red_home = False
        red_away = False
        
        if events:
            for event in events.get('events', []):
                if event.get('type') == 'Card' and event.get('detail') == 'Red Card':
                    if event.get('team') == 'home':
                        red_home = True
                    elif event.get('team') == 'away':
                        red_away = True
        
        if red_home and not red_away:
            score_away += self.red_card_boost
        if red_away and not red_home:
            score_home += self.red_card_boost
        
        # Convert to 0-100
        momentum_home = self.to_0_100(score_home)
        momentum_away = self.to_0_100(score_away)
        
        # Determine drivers
        driver_summary = self._identify_drivers(
            z_shot, z_poss, z_odds, red_home, red_away
        )
        
        return momentum_home, momentum_away, driver_summary
    
    def _identify_drivers(self, z_shot: float, z_poss: float, z_odds: float,
                          red_home: bool, red_away: bool) -> Dict:
        """Identify what's driving momentum"""
        drivers = {}
        
        # Shots
        if abs(z_shot) > 0.5:
            drivers["shots_on_target"] = "home" if z_shot > 0 else "away"
        
        # Possession
        if abs(z_poss) > 0.5:
            drivers["possession"] = "home" if z_poss > 0 else "away"
        
        # Odds
        if abs(z_odds) > 0.3:
            if z_odds > 0:
                drivers["odds"] = "home_tightening"
            else:
                drivers["odds"] = "away_tightening"
        
        # Red cards
        if red_home and not red_away:
            drivers["red_card"] = "home"
        elif red_away and not red_home:
            drivers["red_card"] = "away"
        else:
            drivers["red_card"] = None
        
        return drivers
    
    def save_momentum(self, match_id: int, home_score: int, away_score: int,
                     minute: int, momentum_home: int, momentum_away: int,
                     driver_summary: Dict):
        """Save momentum scores to database"""
        with psycopg2.connect(self.db_url) as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO live_momentum (
                    match_id, updated_at, home_score, away_score, minute,
                    momentum_home, momentum_away, driver_summary
                ) VALUES (%s, NOW(), %s, %s, %s, %s, %s, %s)
                ON CONFLICT (match_id) DO UPDATE SET
                    updated_at = NOW(),
                    home_score = EXCLUDED.home_score,
                    away_score = EXCLUDED.away_score,
                    minute = EXCLUDED.minute,
                    momentum_home = EXCLUDED.momentum_home,
                    momentum_away = EXCLUDED.momentum_away,
                    driver_summary = EXCLUDED.driver_summary
            """, (match_id, home_score, away_score, minute,
                  momentum_home, momentum_away, json.dumps(driver_summary)))
            
            conn.commit()
    
    def run(self):
        """Main job: calculate momentum for all live matches"""
        try:
            live_matches = self.get_live_matches()
            
            if not live_matches:
                logger.info("No live matches for momentum calculation")
                return
            
            logger.info(f"Calculating momentum for {len(live_matches)} live matches")
            
            for match in live_matches:
                match_id = match['match_id']
                
                try:
                    result = self.compute_momentum(match_id)
                    
                    if result:
                        momentum_home, momentum_away, drivers = result
                        
                        # Get latest stats for minute/score
                        stats = self.get_stats_window(match_id, window_minutes=1)
                        if stats:
                            latest = stats[-1]
                            minute = latest.get('minute') or 0
                            home_score = latest.get('home_score') or 0
                            away_score = latest.get('away_score') or 0
                        else:
                            minute = int(match['minutes_elapsed'])
                            home_score = 0
                            away_score = 0
                        
                        self.save_momentum(
                            match_id, home_score, away_score, minute,
                            momentum_home, momentum_away, drivers
                        )
                        
                        logger.info(
                            f"✅ {match['home_team']} vs {match['away_team']}: "
                            f"Momentum {momentum_home}-{momentum_away} "
                            f"(drivers: {drivers})"
                        )
                    
                except Exception as e:
                    logger.error(f"❌ Error calculating momentum for {match_id}: {e}")
                    continue
        
        except Exception as e:
            logger.error(f"❌ Momentum calculator error: {e}")


def calculate_momentum():
    """Entry point for scheduler"""
    calculator = MomentumCalculator()
    calculator.run()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    calculate_momentum()
