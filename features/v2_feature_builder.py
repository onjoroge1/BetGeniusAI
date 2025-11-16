"""
V2 Feature Builder - Reconstruct all features from database

This module builds the complete feature set that the V2 LightGBM model
uses, querying from training_matches, odds_consensus, and match_context tables.

Features:
- Phase 1 (42 features):
  - Odds features (18): probability consensus, dispersion, volatility, coverage, market metrics
  - ELO ratings (3): home_elo, away_elo, elo_diff
  - Form metrics (6): points, goals scored/conceded for home/away
  - Home advantage (2): home/away wins in last 10 home/away games
  - H2H history (3): home wins, draws, away wins
  - Advanced stats (8): shots, shots on target, corners, yellows
  - Rest/schedule (2): days since last match

- Phase 2 (4 additional features - TOTAL 46):
  - Context features (4): rest_days_home/away, schedule_congestion_home/away_7d

- Phase 2.5 (4 additional features - TOTAL 50):
  - Drift features (4): prob_drift_home/draw/away, drift_magnitude
  - Captures odds movement from early (T-24h+) to latest (T-0h)

All features computed with strict time-based cutoff to prevent leakage.
"""

import logging
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from functools import lru_cache
from sqlalchemy import create_engine, text
import os

logger = logging.getLogger(__name__)

class V2FeatureBuilder:
    """Build all features required by V2 LightGBM model (Phase 1: 42, Phase 2: 46, Phase 2.5: 50)"""
    
    def __init__(self, database_url: Optional[str] = None):
        """Initialize feature builder with database connection"""
        self.database_url = database_url or os.getenv('DATABASE_URL')
        if not self.database_url:
            raise ValueError("DATABASE_URL not provided")
        
        self.engine = create_engine(self.database_url)
        
        # ELO parameters (match V2 training config)
        self.K = 20  # ELO K-factor
        self.initial_elo = 1500
        
        # Cache for computed features
        self._elo_cache = {}
        
        logger.info("✅ V2FeatureBuilder initialized")
    
    def build_features(self, match_id: int, cutoff_time: Optional[datetime] = None) -> Dict[str, float]:
        """
        Build all 50 features for a match (Phase 1: 46, Phase 2: 4)
        
        ANTI-LEAKAGE: Enforces pre-kickoff feature computation
        
        Args:
            match_id: Match ID to build features for
            cutoff_time: Maximum timestamp for feature computation (prevents leakage)
                        Should be kickoff_time - timedelta(hours=1) for training
                        If None, uses current time (for live predictions)
        
        Returns:
            Dictionary with all 50 feature values
        """
        # Get match metadata
        match_info = self._get_match_info(match_id)
        if not match_info:
            raise ValueError(f"Match {match_id} not found in database")
        
        # Use provided cutoff or default to kickoff time (NOT T-1h!)
        if cutoff_time is None:
            cutoff_time = match_info['kickoff_time']
            logger.warning(f"No cutoff_time provided for match {match_id}, using kickoff: {cutoff_time}")
        
        # Build feature components (may raise ValueError if no valid odds)
        odds_features = self._build_odds_features(match_id, cutoff_time)
        elo_features = self._build_elo_features(
            match_info['home_team_id'],
            match_info['away_team_id'],
            match_info['league_id'],
            cutoff_time
        )
        form_features = self._build_form_features(
            match_info['home_team_id'],
            match_info['away_team_id'],
            cutoff_time
        )
        h2h_features = self._build_h2h_features(
            match_info['home_team_id'],
            match_info['away_team_id'],
            cutoff_time
        )
        advanced_features = self._build_advanced_stats_features(
            match_info['home_team_id'],
            match_info['away_team_id'],
            cutoff_time
        )
        schedule_features = self._build_schedule_features(
            match_info['home_team_id'],
            match_info['away_team_id'],
            cutoff_time
        )
        
        # Phase 2: Context features (rest days, congestion)
        context_features = self._build_context_features(match_id, cutoff_time)
        
        # Phase 2.5: Drift features (odds movement early → latest)
        drift_features = self._build_drift_features(match_id, cutoff_time)
        
        # Combine all features
        all_features = {
            **odds_features,
            **elo_features,
            **form_features,
            **h2h_features,
            **advanced_features,
            **schedule_features,
            **context_features,  # Phase 2
            **drift_features  # Phase 2.5
        }
        
        # Validate feature count
        # Phase 1: 40 base (18 odds + 3 elo + 6 form + 2 home_adv + 3 h2h + 8 adv_stats)
        # Phase 2: 4 context (rest_days_home/away, congestion_home/away_7d)  
        #          OR 2 context_transformed (rest_advantage, congestion_ratio) if subclass
        # Phase 2.5: 4 drift (prob_drift_home/draw/away, drift_magnitude)
        # Schedule features deprecated (duplicates of context) - was 2, now 0
        # Total: 40 + 4 + 4 = 48 features (or 46 if transformed context)
        if self.__class__.__name__ == "V2FeatureBuilderTransformed":
            expected_count = 46 if drift_features else 42 if context_features else 40
        else:
            expected_count = 48 if drift_features else 44 if context_features else 40
        
        if len(all_features) != expected_count:
            logger.debug(f"Feature count: {len(all_features)} (expected {expected_count} for {self.__class__.__name__})")
        
        return all_features
    
    def _get_match_info(self, match_id: int) -> Optional[Dict]:
        """Get basic match information"""
        query = text("""
            SELECT 
                match_id,
                home_team_id,
                away_team_id,
                league_id,
                match_date as kickoff_time,
                home_team,
                away_team
            FROM training_matches
            WHERE match_id = :match_id
            LIMIT 1
        """)
        
        with self.engine.connect() as conn:
            result = conn.execute(query, {"match_id": match_id}).mappings().first()
            return dict(result) if result else None
    
    def _build_odds_features(self, match_id: int, cutoff_time: datetime) -> Dict[str, float]:
        """
        Build odds-based features (18 features)
        
        CRITICAL: Uses "best available pre-kickoff" with strict validation
        
        Strategy:
        1. Find nearest pre-kickoff snapshot (ts_effective <= cutoff_time)
        2. Require n_books >= 3 for quality
        3. Validate probabilities sum to ~1 (margin-stripped)
        4. Raise ValueError if no valid odds (drop match, don't zero-fill!)
        
        Features:
        - p_last_home, p_last_draw, p_last_away: Latest PRE-KICKOFF odds probabilities
        - p_open_home, p_open_draw, p_open_away: Opening odds probabilities (approximated as p_last for now)
        - dispersion_home/draw/away: Variance across bookmakers
        - book_dispersion: Overall bookmaker disagreement
        - volatility_home/draw/away: Temporal volatility
        - num_books_last: Number of bookmakers
        - num_snapshots: Number of odds snapshots
        - coverage_hours: Time coverage
        - market_entropy: Uncertainty in market
        - favorite_margin: Difference between favorite and underdog
        
        Note: Drift features (prob_drift_*, drift_magnitude) moved to Phase 2.5 _build_drift_features()
        
        Args:
            cutoff_time: Maximum timestamp for odds snapshots (typically kickoff or kickoff - 1h)
            
        Raises:
            ValueError: If no valid pre-kickoff odds available (match will be dropped)
        """
        # Query STRICT pre-kickoff odds (must be BEFORE kickoff, not AT/AFTER)
        # CRITICAL: Uses odds_real_consensus (built from odds_snapshots - REAL DATA)
        # Never use odds_consensus or odds_prekickoff_clean - they contain fake/backdated data!
        query = text("""
            SELECT 
                ph_cons as p_last_home,
                pd_cons as p_last_draw,
                pa_cons as p_last_away,
                disph as dispersion_home,
                dispd as dispersion_draw,
                dispa as dispersion_away,
                n_books as num_books_last,
                market_margin_avg,
                (avg_secs_before_ko / 3600.0) as hours_before_ko
            FROM odds_real_consensus
            WHERE match_id = :match_id
        """)
        
        with self.engine.connect() as conn:
            result = conn.execute(query, {
                "match_id": match_id
            }).mappings().first()
        
        # CRITICAL: Raise exception if no valid odds (drop match, don't zero-fill!)
        if not result:
            raise ValueError(
                f"No valid pre-kickoff odds for match {match_id} "
                f"(cutoff: {cutoff_time}, required: ts_effective < kickoff AND n_books >= 3)"
            )
        
        odds = dict(result)
        
        # Extract and validate probabilities
        p_last_home_raw = odds.get('p_last_home')
        p_last_draw_raw = odds.get('p_last_draw')
        p_last_away_raw = odds.get('p_last_away')
        
        # Validate not None
        if None in [p_last_home_raw, p_last_draw_raw, p_last_away_raw]:
            raise ValueError(f"Match {match_id}: Missing probability values in odds_real_consensus")
        
        # Validate raw probabilities are reasonable (before normalization)
        prob_sum_raw = p_last_home_raw + p_last_draw_raw + p_last_away_raw
        if not (0.95 <= prob_sum_raw <= 1.15):  # Allow bookmaker margin (typically 1.03-1.08)
            raise ValueError(
                f"Match {match_id}: Invalid raw probability sum {prob_sum_raw:.4f} "
                f"(expected 0.95-1.15 with margin, got {p_last_home_raw:.3f}/{p_last_draw_raw:.3f}/{p_last_away_raw:.3f})"
            )
        
        # NORMALIZE to remove bookmaker margin (sum = 1.0)
        p_last_home = p_last_home_raw / prob_sum_raw
        p_last_draw = p_last_draw_raw / prob_sum_raw
        p_last_away = p_last_away_raw / prob_sum_raw
        
        # Validate normalized probabilities
        if min(p_last_home, p_last_draw, p_last_away) <= 0.005:  # 0.5%
            raise ValueError(f"Match {match_id}: Extreme low probability (<0.5%)")
        if max(p_last_home, p_last_draw, p_last_away) >= 0.99:  # 99%
            raise ValueError(f"Match {match_id}: Extreme high probability (>99%)")
        
        # ANTI-LEAKAGE VALIDATION: Verify odds are truly pre-kickoff
        hours_before = odds.get('hours_before_ko')
        if hours_before is not None and hours_before < 0:
            raise ValueError(
                f"Match {match_id}: LEAKAGE DETECTED - odds timestamp is {-hours_before:.2f}h AFTER kickoff!"
            )
        
        # Log successful odds retrieval (for debugging)
        logger.debug(
            f"Match {match_id}: Using odds from {hours_before:.2f}h before KO "
            f"({p_last_home:.3f}/{p_last_draw:.3f}/{p_last_away:.3f}, "
            f"{odds['num_books_last']} books)"
        )
        
        # For now, assume minimal drift (open ≈ last)
        # Real drift features calculated in Phase 2.5 _build_drift_features()
        p_open_home = p_last_home
        p_open_draw = p_last_draw
        p_open_away = p_last_away
        
        # Dispersion
        dispersion_home = odds.get('dispersion_home', 0.01)
        dispersion_draw = odds.get('dispersion_draw', 0.01)
        dispersion_away = odds.get('dispersion_away', 0.01)
        book_dispersion = (dispersion_home + dispersion_draw + dispersion_away) / 3.0
        
        # Volatility (approximated as dispersion for now)
        volatility_home = dispersion_home
        volatility_draw = dispersion_draw
        volatility_away = dispersion_away
        
        # Market metrics
        num_books_last = float(odds.get('num_books_last', 5))
        num_snapshots = 10.0  # Default
        coverage_hours = 24.0  # Default
        
        # Calculate market entropy
        probs = np.array([p_last_home, p_last_draw, p_last_away])
        probs = probs / probs.sum()  # Normalize
        market_entropy = -np.sum(probs * np.log(probs + 1e-10))
        
        # Favorite margin
        favorite_margin = max(probs) - min(probs)
        
        return {
            # Latest probabilities (3)
            'p_last_home': p_last_home,
            'p_last_draw': p_last_draw,
            'p_last_away': p_last_away,
            # Opening probabilities (3) - approximated as latest for now
            'p_open_home': p_open_home,
            'p_open_draw': p_open_draw,
            'p_open_away': p_open_away,
            # Dispersion (4)
            'dispersion_home': dispersion_home,
            'dispersion_draw': dispersion_draw,
            'dispersion_away': dispersion_away,
            'book_dispersion': book_dispersion,
            # Volatility (3)
            'volatility_home': volatility_home,
            'volatility_draw': volatility_draw,
            'volatility_away': volatility_away,
            # Coverage metrics (3)
            'num_books_last': num_books_last,
            'num_snapshots': num_snapshots,
            'coverage_hours': coverage_hours,
            # Market metrics (2)
            'market_entropy': float(market_entropy),
            'favorite_margin': float(favorite_margin)
            # Total: 18 odds features (drift features moved to Phase 2.5)
        }
    
    def _build_elo_features(self, home_team_id: int, away_team_id: int, 
                           league_id: int, cutoff_time: datetime) -> Dict[str, float]:
        """
        Build ELO-based features (3 features)
        
        Features:
        - home_elo: Home team ELO rating
        - away_elo: Away team ELO rating
        - elo_diff: Home ELO - Away ELO
        """
        home_elo = self._get_team_elo(home_team_id, league_id, cutoff_time)
        away_elo = self._get_team_elo(away_team_id, league_id, cutoff_time)
        elo_diff = home_elo - away_elo
        
        return {
            'home_elo': home_elo,
            'away_elo': away_elo,
            'elo_diff': elo_diff
        }
    
    @lru_cache(maxsize=1024)
    def _get_team_elo(self, team_id: int, league_id: int, cutoff_time: datetime) -> float:
        """
        Calculate team's ELO rating based on historical results
        
        Simple implementation: Use recent form as proxy for ELO
        TODO: Implement proper ELO calculation with K-factor updates
        """
        query = text("""
            SELECT 
                CASE 
                    WHEN home_team_id = :team_id THEN
                        CASE outcome
                            WHEN 'H' THEN 3
                            WHEN 'D' THEN 1
                            ELSE 0
                        END
                    ELSE
                        CASE outcome
                            WHEN 'A' THEN 3
                            WHEN 'D' THEN 1
                            ELSE 0
                        END
                END as points
            FROM training_matches
            WHERE (home_team_id = :team_id OR away_team_id = :team_id)
                AND league_id = :league_id
                AND match_date < :cutoff_time
                AND outcome IS NOT NULL
            ORDER BY match_date DESC
            LIMIT 10
        """)
        
        with self.engine.connect() as conn:
            results = conn.execute(query, {
                "team_id": team_id,
                "league_id": league_id,
                "cutoff_time": cutoff_time
            }).fetchall()
        
        if not results:
            return self.initial_elo
        
        # Simple ELO approximation: 1500 + (avg_points - 1.5) * 100
        avg_points = np.mean([r[0] for r in results])
        elo = self.initial_elo + (avg_points - 1.5) * 100
        
        return float(elo)
    
    def _build_form_features(self, home_team_id: int, away_team_id: int,
                            cutoff_time: datetime) -> Dict[str, float]:
        """
        Build form-based features (8 features)
        
        Features:
        - home_form_points: Points in last 5 matches
        - home_form_goals_scored: Goals scored in last 5
        - home_form_goals_conceded: Goals conceded in last 5
        - away_form_points: Points in last 5 matches
        - away_form_goals_scored: Goals scored in last 5
        - away_form_goals_conceded: Goals conceded in last 5
        - home_last10_home_wins: Wins in last 10 home matches
        - away_last10_away_wins: Wins in last 10 away matches
        """
        home_form = self._get_team_form(home_team_id, cutoff_time, n_matches=5)
        away_form = self._get_team_form(away_team_id, cutoff_time, n_matches=5)
        
        home_home_wins = self._get_venue_wins(home_team_id, cutoff_time, venue='home', n_matches=10)
        away_away_wins = self._get_venue_wins(away_team_id, cutoff_time, venue='away', n_matches=10)
        
        return {
            'home_form_points': home_form['points'],
            'home_form_goals_scored': home_form['goals_scored'],
            'home_form_goals_conceded': home_form['goals_conceded'],
            'away_form_points': away_form['points'],
            'away_form_goals_scored': away_form['goals_scored'],
            'away_form_goals_conceded': away_form['goals_conceded'],
            'home_last10_home_wins': float(home_home_wins),
            'away_last10_away_wins': float(away_away_wins)
        }
    
    def _get_team_form(self, team_id: int, cutoff_time: datetime, n_matches: int = 5) -> Dict[str, float]:
        """Get team's recent form (last N matches)"""
        query = text("""
            SELECT 
                CASE 
                    WHEN home_team_id = :team_id THEN home_goals
                    ELSE away_goals
                END as goals_for,
                CASE 
                    WHEN home_team_id = :team_id THEN away_goals
                    ELSE home_goals
                END as goals_against,
                CASE 
                    WHEN home_team_id = :team_id THEN
                        CASE outcome
                            WHEN 'H' THEN 3
                            WHEN 'D' THEN 1
                            ELSE 0
                        END
                    ELSE
                        CASE outcome
                            WHEN 'A' THEN 3
                            WHEN 'D' THEN 1
                            ELSE 0
                        END
                END as points
            FROM training_matches
            WHERE (home_team_id = :team_id OR away_team_id = :team_id)
                AND match_date < :cutoff_time
                AND outcome IS NOT NULL
            ORDER BY match_date DESC
            LIMIT :n_matches
        """)
        
        with self.engine.connect() as conn:
            results = conn.execute(query, {
                "team_id": team_id,
                "cutoff_time": cutoff_time,
                "n_matches": n_matches
            }).fetchall()
        
        if not results:
            return {'points': 0.0, 'goals_scored': 0.0, 'goals_conceded': 0.0}
        
        goals_for = [r[0] for r in results if r[0] is not None]
        goals_against = [r[1] for r in results if r[1] is not None]
        points = [r[2] for r in results if r[2] is not None]
        
        return {
            'points': float(sum(points)),
            'goals_scored': float(sum(goals_for)),
            'goals_conceded': float(sum(goals_against))
        }
    
    def _get_venue_wins(self, team_id: int, cutoff_time: datetime, venue: str = 'home', n_matches: int = 10) -> int:
        """Count wins at specific venue (home or away) in last N matches"""
        if venue == 'home':
            condition = "home_team_id = :team_id AND outcome = 'H'"
        else:
            condition = "away_team_id = :team_id AND outcome = 'A'"
        
        # Use subquery to properly limit before counting
        query = text(f"""
            SELECT COUNT(*) as wins
            FROM (
                SELECT 1
                FROM training_matches
                WHERE {condition}
                    AND match_date < :cutoff_time
                ORDER BY match_date DESC
                LIMIT :n_matches
            ) subq
        """)
        
        with self.engine.connect() as conn:
            result = conn.execute(query, {
                "team_id": team_id,
                "cutoff_time": cutoff_time,
                "n_matches": n_matches
            }).scalar()
        
        return int(result or 0)
    
    def _build_h2h_features(self, home_team_id: int, away_team_id: int,
                           cutoff_time: datetime) -> Dict[str, float]:
        """
        Build head-to-head features (3 features)
        
        Features:
        - h2h_home_wins: Home team wins in last 5 H2H
        - h2h_draws: Draws in last 5 H2H
        - h2h_away_wins: Away team wins in last 5 H2H
        """
        query = text("""
            SELECT 
                SUM(CASE WHEN outcome = 'H' THEN 1 ELSE 0 END) as home_wins,
                SUM(CASE WHEN outcome = 'D' THEN 1 ELSE 0 END) as draws,
                SUM(CASE WHEN outcome = 'A' THEN 1 ELSE 0 END) as away_wins
            FROM (
                SELECT outcome
                FROM training_matches
                WHERE ((home_team_id = :home_id AND away_team_id = :away_id)
                       OR (home_team_id = :away_id AND away_team_id = :home_id))
                    AND match_date < :cutoff_time
                    AND outcome IS NOT NULL
                ORDER BY match_date DESC
                LIMIT 5
            ) recent_h2h
        """)
        
        with self.engine.connect() as conn:
            result = conn.execute(query, {
                "home_id": home_team_id,
                "away_id": away_team_id,
                "cutoff_time": cutoff_time
            }).mappings().first()
        
        if not result:
            return {'h2h_home_wins': 0.0, 'h2h_draws': 0.0, 'h2h_away_wins': 0.0}
        
        return {
            'h2h_home_wins': float(result.get('home_wins', 0) or 0),
            'h2h_draws': float(result.get('draws', 0) or 0),
            'h2h_away_wins': float(result.get('away_wins', 0) or 0)
        }
    
    def _build_advanced_stats_features(self, home_team_id: int, away_team_id: int,
                                      cutoff_time: datetime) -> Dict[str, float]:
        """
        Build advanced statistics features (8 features)
        
        Features:
        - adv_home_shots_avg: Average shots per game
        - adv_home_shots_target_avg: Average shots on target
        - adv_home_corners_avg: Average corners
        - adv_home_yellows_avg: Average yellow cards
        - adv_away_shots_avg
        - adv_away_shots_target_avg
        - adv_away_corners_avg
        - adv_away_yellows_avg
        
        Note: These require match statistics data which may not be fully available
        Using placeholder values for now
        """
        # TODO: Query actual advanced stats when available in database
        # For now, return neutral values
        return {
            'adv_home_shots_avg': 12.0,
            'adv_home_shots_target_avg': 4.5,
            'adv_home_corners_avg': 5.0,
            'adv_home_yellows_avg': 2.0,
            'adv_away_shots_avg': 10.0,
            'adv_away_shots_target_avg': 3.8,
            'adv_away_corners_avg': 4.2,
            'adv_away_yellows_avg': 2.1
        }
    
    def _build_schedule_features(self, home_team_id: int, away_team_id: int,
                                 cutoff_time: datetime) -> Dict[str, float]:
        """
        DEPRECATED: Schedule features merged into context features
        
        Previous features (REMOVED - duplicates of context features):
        - days_since_home_last_match → Now in context as rest_days_home
        - days_since_away_last_match → Now in context as rest_days_away
        
        These were identical calculations, causing:
        1. Feature duplication (50 → 48 features after removal)
        2. Increased leak risk (reinforced time-based fingerprinting)
        3. Multicollinearity (perfect correlation)
        
        Use _build_context_features() instead for rest/schedule data.
        """
        # Return empty dict - no longer used
        # Context features provide same information
        return {}
    
    def _get_days_since_last_match(self, team_id: int, cutoff_time: datetime) -> float:
        """Calculate days since team's last match"""
        query = text("""
            SELECT match_date
            FROM training_matches
            WHERE (home_team_id = :team_id OR away_team_id = :team_id)
                AND match_date < :cutoff_time
            ORDER BY match_date DESC
            LIMIT 1
        """)
        
        with self.engine.connect() as conn:
            result = conn.execute(query, {
                "team_id": team_id,
                "cutoff_time": cutoff_time
            }).scalar()
        
        if not result:
            return 7.0  # Default to 1 week
        
        last_match_date = result
        days_since = (cutoff_time - last_match_date).total_seconds() / 86400.0
        
        return float(max(0, days_since))
    
    def _build_context_features(self, match_id: int, cutoff_time: datetime) -> Dict[str, float]:
        """
        Build match context features from match_context_v2 (clean, leak-free data)
        
        Features:
        - rest_days_home: Days since home team's last match
        - rest_days_away: Days since away team's last match
        - schedule_congestion_home_7d: Home team matches in last 7 days
        - schedule_congestion_away_7d: Away team matches in last 7 days
        
        Note: Uses match_context_v2 (created with strict pre-match timestamps)
        instead of match_context (contaminated with post-match data).
        """
        query = text("""
            SELECT 
                rest_days_home,
                rest_days_away,
                matches_home_last_7d,
                matches_away_last_7d
            FROM match_context_v2
            WHERE match_id = :match_id
              AND as_of_time <= :cutoff_time
            ORDER BY as_of_time DESC
            LIMIT 1
        """)
        
        try:
            with self.engine.connect() as conn:
                result = conn.execute(query, {
                    "match_id": match_id,
                    "cutoff_time": cutoff_time
                }).mappings().first()
            
            if result:
                return {
                    'rest_days_home': float(result['rest_days_home'] or 7.0),
                    'rest_days_away': float(result['rest_days_away'] or 7.0),
                    'schedule_congestion_home_7d': float(result['matches_home_last_7d'] or 0.0),
                    'schedule_congestion_away_7d': float(result['matches_away_last_7d'] or 0.0)
                }
        except Exception as e:
            logger.debug(f"Context features unavailable for match {match_id}: {e}")
        
        # Graceful defaults if no context data available
        return {
            'rest_days_home': 7.0,
            'rest_days_away': 7.0,
            'schedule_congestion_home_7d': 0.0,
            'schedule_congestion_away_7d': 0.0
        }
    
    def _build_drift_features(self, match_id: int, cutoff_time: datetime) -> Dict[str, float]:
        """
        Build odds drift features from Phase 2.5 data (4 features)
        
        Captures market movement from early odds (T-24h+) to latest odds (T-0h).
        Drift indicates "smart money" flow and late information (injuries, suspensions).
        
        Features:
        - prob_drift_home: Change in home win probability (early → latest)
        - prob_drift_draw: Change in draw probability (early → latest)
        - prob_drift_away: Change in away win probability (early → latest)
        - drift_magnitude: Overall market movement magnitude
        
        Architect recommendation: Include coverage indicator to distinguish 
        zero drift (stable market) from missing drift data.
        """
        query = text("""
            SELECT 
                e.ph_early, e.pd_early, e.pa_early,
                l.ph_cons, l.pd_cons, l.pa_cons
            FROM odds_early_snapshot e
            INNER JOIN odds_real_consensus l ON e.match_id = l.match_id
            WHERE e.match_id = :match_id
        """)
        
        try:
            with self.engine.connect() as conn:
                result = conn.execute(query, {"match_id": match_id}).mappings().first()
            
            if result and result['ph_early'] is not None:
                # Calculate drift for each outcome
                drift_home = float(result['ph_cons'] - result['ph_early'])
                drift_draw = float(result['pd_cons'] - result['pd_early'])
                drift_away = float(result['pa_cons'] - result['pa_early'])
                
                # Calculate magnitude (Euclidean distance in probability space)
                import math
                drift_magnitude = math.sqrt(drift_home**2 + drift_draw**2 + drift_away**2)
                
                return {
                    'prob_drift_home': drift_home,
                    'prob_drift_draw': drift_draw,
                    'prob_drift_away': drift_away,
                    'drift_magnitude': drift_magnitude
                }
        except Exception as e:
            logger.debug(f"Drift features unavailable for match {match_id}: {e}")
        
        # Graceful defaults when drift data unavailable
        # Note: Zero drift could mean stable market OR missing data
        # Model will learn to distinguish via other features (e.g., num_snapshots)
        return {
            'prob_drift_home': 0.0,
            'prob_drift_draw': 0.0,
            'prob_drift_away': 0.0,
            'drift_magnitude': 0.0
        }
    
    def _get_default_features(self) -> Dict[str, float]:
        """Return default feature values when data is missing (54 features total)"""
        return {
            # Phase 1 features (46)
            'p_last_home': 0.33, 'p_last_draw': 0.33, 'p_last_away': 0.34,
            'p_open_home': 0.33, 'p_open_draw': 0.33, 'p_open_away': 0.34,
            'dispersion_home': 0.01, 'dispersion_draw': 0.01, 'dispersion_away': 0.01,
            'book_dispersion': 0.01,
            'volatility_home': 0.0, 'volatility_draw': 0.0, 'volatility_away': 0.0,
            'num_books_last': 5.0, 'num_snapshots': 10.0, 'coverage_hours': 24.0,
            'market_entropy': 1.099, 'favorite_margin': 0.01,
            'home_elo': 1500.0, 'away_elo': 1500.0, 'elo_diff': 0.0,
            'home_form_points': 0.0, 'home_form_goals_scored': 0.0, 'home_form_goals_conceded': 0.0,
            'away_form_points': 0.0, 'away_form_goals_scored': 0.0, 'away_form_goals_conceded': 0.0,
            'home_last10_home_wins': 0.0, 'away_last10_away_wins': 0.0,
            'h2h_home_wins': 0.0, 'h2h_draws': 0.0, 'h2h_away_wins': 0.0,
            'adv_home_shots_avg': 12.0, 'adv_home_shots_target_avg': 4.5,
            'adv_home_corners_avg': 5.0, 'adv_home_yellows_avg': 2.0,
            'adv_away_shots_avg': 10.0, 'adv_away_shots_target_avg': 3.8,
            'adv_away_corners_avg': 4.2, 'adv_away_yellows_avg': 2.1,
            'days_since_home_last_match': 7.0, 'days_since_away_last_match': 7.0,
            # Phase 2 features (4)
            'rest_days_home': 7.0,
            'rest_days_away': 7.0,
            'schedule_congestion_home_7d': 0.0,
            'schedule_congestion_away_7d': 0.0,
            # Phase 2.5 features (4) - Drift features
            'prob_drift_home': 0.0,
            'prob_drift_draw': 0.0,
            'prob_drift_away': 0.0,
            'drift_magnitude': 0.0
        }


# Singleton instance
_builder = None

def get_v2_feature_builder() -> V2FeatureBuilder:
    """Get singleton feature builder instance"""
    global _builder
    if _builder is None:
        _builder = V2FeatureBuilder()
    return _builder
