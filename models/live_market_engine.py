import os
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import json
import time

logger = logging.getLogger(__name__)


class LiveMarketEngine:
    """
    Phase 2 Live Market Engine
    
    Generates in-play market predictions for:
    - Win/Draw/Win (1X2 live)
    - Over/Under live line
    - Next Goal (home/none/away)
    
    Uses time-aware blending:
    - Early game: Market heavier (α=0.5)
    - Late game: Live stats heavier (α→0.8)
    - Momentum differential as transient boost (±5 p.p. cap)
    """
    
    def __init__(self):
        self.db_url = os.getenv("DATABASE_URL")
        
        # Time-aware decay parameters
        self.alpha_min = 0.5  # Early game: trust market more
        self.alpha_max = 0.8  # Late game: trust live stats more
        
        # Momentum influence caps
        self.momentum_cap_pp = 5.0  # Max ±5 percentage points from momentum
    
    def get_time_decay_alpha(self, minutes_elapsed: float) -> float:
        """
        Calculate time-aware blending parameter α
        Early game (0-30 min): α = 0.5 (market heavy)
        Mid game (30-60 min): α = 0.65 (balanced)
        Late game (60-90+ min): α = 0.8 (live stats heavy)
        """
        if minutes_elapsed < 30:
            return self.alpha_min
        elif minutes_elapsed < 60:
            # Linear interpolation
            return self.alpha_min + (self.alpha_max - self.alpha_min) * (minutes_elapsed - 30) / 30
        else:
            return self.alpha_max
    
    def normalize_probs(self, probs: Dict[str, float]) -> Dict[str, float]:
        """Normalize probabilities to sum to 1.0"""
        total = sum(probs.values())
        if total == 0:
            return probs
        # Ensure all values are float, not Decimal
        return {k: float(v / total) for k, v in probs.items()}
    
    def get_current_market_probs(self, match_id: int) -> Optional[Dict[str, float]]:
        """Get current no-vig market probabilities from latest odds snapshot"""
        with psycopg2.connect(self.db_url) as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            # Get latest odds for H/D/A outcomes (table is in long format)
            # Use 7-day window to capture pre-match odds for live matches
            cursor.execute("""
                WITH latest_snapshot AS (
                    SELECT MAX(ts_snapshot) as max_ts
                    FROM odds_snapshots
                    WHERE match_id = %s
                      AND ts_snapshot > NOW() - INTERVAL '7 days'
                )
                SELECT 
                    outcome,
                    AVG(odds_decimal) as avg_odds
                FROM odds_snapshots
                WHERE match_id = %s
                  AND ts_snapshot = (SELECT max_ts FROM latest_snapshot)
                  AND market = 'h2h'
                  AND outcome IN ('H', 'D', 'A')
                GROUP BY outcome
            """, (match_id, match_id))
            
            rows = cursor.fetchall()
            if not rows:
                return None
            
            # Build odds dict (convert Decimal to float)
            odds = {}
            for row in rows:
                odds[row['outcome']] = float(row['avg_odds'])
            
            # Convert odds to implied probabilities (remove vig)
            home_prob = 1.0 / odds.get('H', 3.0)
            draw_prob = 1.0 / odds.get('D', 3.5)
            away_prob = 1.0 / odds.get('A', 3.0)
            
            # Normalize to remove vig
            return self.normalize_probs({
                'home': home_prob,
                'draw': draw_prob,
                'away': away_prob
            })
    
    def get_prematch_probs(self, match_id: int) -> Optional[Dict[str, float]]:
        """Get pre-match model probabilities from consensus predictions"""
        with psycopg2.connect(self.db_url) as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            cursor.execute("""
                SELECT 
                    consensus_h,
                    consensus_d,
                    consensus_a
                FROM consensus_predictions
                WHERE match_id = %s
                LIMIT 1
            """, (match_id,))
            
            row = cursor.fetchone()
            if not row:
                # Fallback to market if no pre-match model
                return self.get_current_market_probs(match_id)
            
            # Convert Decimal to float
            return {
                'home': float(row['consensus_h']) if row['consensus_h'] is not None else 0.33,
                'draw': float(row['consensus_d']) if row['consensus_d'] is not None else 0.27,
                'away': float(row['consensus_a']) if row['consensus_a'] is not None else 0.40
            }
    
    def get_momentum_adjustment(self, match_id: int) -> Tuple[float, float]:
        """
        Get momentum-based adjustment in percentage points
        Returns: (home_adjustment, away_adjustment) in range [-5, +5]
        """
        with psycopg2.connect(self.db_url) as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            cursor.execute("""
                SELECT 
                    momentum_home,
                    momentum_away
                FROM live_momentum
                WHERE match_id = %s
                  AND updated_at > NOW() - INTERVAL '5 minutes'
                LIMIT 1
            """, (match_id,))
            
            row = cursor.fetchone()
            if not row:
                return 0.0, 0.0
            
            # Convert 0-100 momentum to -50 to +50 differential (convert Decimal to float)
            mom_home = (float(row['momentum_home']) if row['momentum_home'] is not None else 50) - 50
            mom_away = (float(row['momentum_away']) if row['momentum_away'] is not None else 50) - 50
            
            # Scale to percentage points (±5 max)
            # Differential of +30 momentum → +3 p.p. boost
            home_adj = max(-self.momentum_cap_pp, min(self.momentum_cap_pp, mom_home * 0.1))
            away_adj = max(-self.momentum_cap_pp, min(self.momentum_cap_pp, mom_away * 0.1))
            
            return home_adj, away_adj
    
    def compute_live_wdw(self, match_id: int, minutes_elapsed: float) -> Optional[Dict[str, float]]:
        """
        Compute live Win/Draw/Win probabilities
        
        Blends:
        1. Current market implied probs (novig)
        2. Pre-match model probs
        3. Momentum adjustment (transient boost)
        
        α(t) = time-aware weight (early game → market, late game → live)
        """
        market_probs = self.get_current_market_probs(match_id)
        prematch_probs = self.get_prematch_probs(match_id)
        
        if not market_probs or not prematch_probs:
            logger.warning(f"Missing probabilities for match {match_id}")
            return None
        
        # Get time-aware blending parameter
        alpha = self.get_time_decay_alpha(minutes_elapsed)
        
        # Blend market and pre-match model
        # live_prob = α * market + (1-α) * prematch
        blended = {
            'home': alpha * market_probs['home'] + (1 - alpha) * prematch_probs['home'],
            'draw': alpha * market_probs['draw'] + (1 - alpha) * prematch_probs['draw'],
            'away': alpha * market_probs['away'] + (1 - alpha) * prematch_probs['away']
        }
        
        # Get momentum adjustment (percentage points)
        home_adj, away_adj = self.get_momentum_adjustment(match_id)
        
        # Apply momentum boost (convert p.p. to probability shift)
        blended['home'] += home_adj / 100.0
        blended['away'] += away_adj / 100.0
        
        # Reduce draw probability proportionally
        draw_reduction = (abs(home_adj) + abs(away_adj)) / 100.0
        blended['draw'] -= draw_reduction * 0.5  # Draw suffers from momentum swings
        
        # Re-normalize to ensure sum = 1.0
        return self.normalize_probs(blended)
    
    def compute_over_under(self, match_id: int, minutes_elapsed: float) -> Dict[str, float]:
        """
        Compute live Over/Under 2.5 probabilities
        
        Uses simple heuristic based on:
        - Current score
        - Minutes remaining
        - Goal rate (goals per minute)
        """
        with psycopg2.connect(self.db_url) as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            # Get latest score
            cursor.execute("""
                SELECT home_score, away_score
                FROM live_match_stats
                WHERE match_id = %s
                ORDER BY timestamp DESC
                LIMIT 1
            """, (match_id,))
            
            row = cursor.fetchone()
            if not row:
                # Default: 50/50
                return {'line': 2.5, 'over': 0.50, 'under': 0.50}
            
            # Convert Decimal to float
            home_score = float(row['home_score']) if row['home_score'] is not None else 0
            away_score = float(row['away_score']) if row['away_score'] is not None else 0
            current_total = home_score + away_score
            minutes_remaining = max(0, 90 - minutes_elapsed)
            
            # If already over 2.5, probability is 100%
            if current_total > 2.5:
                return {'line': 2.5, 'over': 1.0, 'under': 0.0}
            
            # Calculate goals needed
            goals_needed = 2.5 - current_total
            
            # Estimate goal rate (average ~2.7 goals per 90 min)
            avg_goal_rate = 2.7 / 90.0  # ~0.03 goals per minute
            expected_goals_remaining = avg_goal_rate * minutes_remaining
            
            # Simple Poisson-like approximation
            # P(over) ≈ 1 - exp(-λ) where λ = expected goals / goals needed
            if goals_needed <= 0:
                over_prob = 1.0
            else:
                # Heuristic: if expected = needed, prob ~60%
                # Scale based on ratio
                ratio = expected_goals_remaining / goals_needed
                over_prob = min(0.95, max(0.05, 0.3 + ratio * 0.4))
            
            return {
                'line': 2.5,
                'over': over_prob,
                'under': 1.0 - over_prob
            }
    
    def compute_next_goal(self, match_id: int, minutes_elapsed: float) -> Dict[str, float]:
        """
        Compute Next Goal probabilities (home/none/away)
        
        Based on:
        - Current WDW live probabilities
        - Minutes remaining (less time → higher chance of 'none')
        - Momentum differential
        """
        wdw = self.compute_live_wdw(match_id, minutes_elapsed)
        if not wdw:
            return {'home': 0.40, 'none': 0.20, 'away': 0.40}
        
        minutes_remaining = max(0, 90 - minutes_elapsed)
        
        # Base next goal probabilities on WDW (teams with higher win prob score more)
        # Home team more likely to win → more likely to score next
        home_base = wdw['home'] * 0.6 + wdw['draw'] * 0.3
        away_base = wdw['away'] * 0.6 + wdw['draw'] * 0.3
        
        # Probability of no more goals increases as time runs out
        if minutes_remaining < 10:
            none_prob = 0.25 + (10 - minutes_remaining) * 0.02  # Up to 45% if <10 min
        elif minutes_remaining < 20:
            none_prob = 0.15 + (20 - minutes_remaining) * 0.01
        else:
            none_prob = 0.10
        
        # Normalize
        home_prob = home_base * (1 - none_prob)
        away_prob = away_base * (1 - none_prob)
        
        return self.normalize_probs({
            'home': home_prob,
            'none': none_prob,
            'away': away_prob
        })
    
    def compute_live_markets(self, match_id: int, minutes_elapsed: float) -> Dict:
        """
        Compute all live market predictions for a match
        
        Returns: {
            'updated_at': timestamp,
            'win_draw_win': {home, draw, away},
            'over_under': {line, over, under},
            'next_goal': {home, none, away}
        }
        """
        wdw = self.compute_live_wdw(match_id, minutes_elapsed)
        ou = self.compute_over_under(match_id, minutes_elapsed)
        ng = self.compute_next_goal(match_id, minutes_elapsed)
        
        if not wdw:
            return None
        
        return {
            'updated_at': datetime.utcnow().isoformat() + 'Z',
            'win_draw_win': wdw,
            'over_under': ou,
            'next_goal': ng
        }
    
    def save_live_markets(self, match_id: int, markets: Dict):
        """Save live market predictions to database cache"""
        with psycopg2.connect(self.db_url) as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO live_model_markets (
                    match_id, updated_at, wdw, ou, next_goal
                ) VALUES (%s, NOW(), %s, %s, %s)
                ON CONFLICT (match_id) DO UPDATE SET
                    updated_at = NOW(),
                    wdw = EXCLUDED.wdw,
                    ou = EXCLUDED.ou,
                    next_goal = EXCLUDED.next_goal
            """, (
                match_id,
                json.dumps(markets['win_draw_win']),
                json.dumps(markets['over_under']),
                json.dumps(markets['next_goal'])
            ))
            
            conn.commit()
    
    def get_live_matches(self) -> List[Dict]:
        """Get currently live matches (excludes TBD fixtures)"""
        with psycopg2.connect(self.db_url) as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            cursor.execute("""
                SELECT 
                    f.match_id,
                    f.home_team,
                    f.away_team,
                    f.kickoff_at,
                    EXTRACT(EPOCH FROM (NOW() - f.kickoff_at)) / 60 AS minutes_elapsed
                FROM fixtures f
                WHERE f.status = 'scheduled'
                  AND f.kickoff_at <= NOW()
                  AND f.kickoff_at > NOW() - INTERVAL '3 hours'
                  AND f.home_team != 'TBD'
                  AND f.away_team != 'TBD'
            """)
            
            return cursor.fetchall()
    
    def run(self):
        """Main job: compute live markets for all live matches"""
        from models.metrics import (
            live_market_generations_total,
            live_market_generation_duration
        )
        
        start_time = time.time()
        
        try:
            live_matches = self.get_live_matches()
            
            if not live_matches:
                logger.info("No live matches for market engine")
                return
            
            logger.info(f"Computing live markets for {len(live_matches)} matches")
            
            for match in live_matches:
                match_id = match['match_id']
                # Convert Decimal to float
                minutes_elapsed = float(match['minutes_elapsed']) if match['minutes_elapsed'] is not None else 0.0
                match_start = time.time()
                status = "unknown"
                
                try:
                    markets = self.compute_live_markets(match_id, minutes_elapsed)
                    
                    if markets:
                        self.save_live_markets(match_id, markets)
                        
                        status = "success"
                        
                        logger.info(
                            f"✅ {match['home_team']} vs {match['away_team']}: "
                            f"WDW: {markets['win_draw_win']['home']:.2f}/"
                            f"{markets['win_draw_win']['draw']:.2f}/"
                            f"{markets['win_draw_win']['away']:.2f}, "
                            f"O/U 2.5: {markets['over_under']['over']:.2f}"
                        )
                    else:
                        status = "no_data"
                
                except Exception as e:
                    status = "error"
                    logger.error(f"❌ Error computing markets for {match_id}: {e}")
                
                finally:
                    live_market_generations_total.labels(status=status).inc()
                    live_market_generation_duration.observe(time.time() - match_start)
            
            logger.info(f"Live market generation cycle completed in {time.time() - start_time:.2f}s")
        
        except Exception as e:
            live_market_generations_total.labels(status="fatal_error").inc()
            logger.error(f"❌ Live market engine error: {e}")


def compute_live_markets():
    """Entry point for scheduler"""
    engine = LiveMarketEngine()
    engine.run()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    compute_live_markets()
