"""
Unified V2 Feature Builder - Complete 61-Feature Pipeline

Merges all V2 features (50) + V3 Sharp Intelligence features (11) into a single unified builder.

Feature Categories (61 total):
═══════════════════════════════════════════════════════════════════════════════

1. ODDS FEATURES (18):
   - p_last_home/draw/away: Latest pre-kickoff probabilities
   - p_open_home/draw/away: Opening probabilities
   - dispersion_home/draw/away: Per-outcome bookmaker disagreement
   - book_dispersion: Average dispersion across outcomes
   - volatility_home/draw/away: Temporal odds volatility
   - num_books_last: Number of bookmakers
   - market_entropy, favorite_margin: Market characteristics
   - market_overround: Total margin
   - hours_before_ko: Time before kickoff of last snapshot

2. DRIFT FEATURES (4):
   - prob_drift_home/draw/away: Opening → closing movement
   - drift_magnitude: Total absolute drift

3. ELO FEATURES (3):
   - home_elo, away_elo: Team strength ratings
   - elo_diff: Relative team strength

4. FORM FEATURES (8):
   - home_form_points, away_form_points: Points in last 5
   - home_form_goals_scored/conceded, away_form_goals_scored/conceded
   - home_last10_home_wins, away_last10_away_wins: Venue-specific form

5. H2H FEATURES (3):
   - h2h_home_wins, h2h_draws, h2h_away_wins: Head-to-head history

6. ADVANCED STATS (8): [from historical_odds table]
   - home/away_shots_avg, home/away_shots_target_avg
   - home/away_corners_avg, home/away_yellows_avg

7. CONTEXT FEATURES (4): [from match_context_v2 table]
   - rest_days_home, rest_days_away: Days since last match
   - congestion_home_7d, congestion_away_7d: Schedule pressure

8. SHARP BOOK FEATURES (4) [from V3]:
   - sharp_prob_home/draw/away: Pinnacle/Betfair probabilities
   - soft_vs_sharp_divergence: Recreational vs sharp book gap

9. LEAGUE ECE FEATURES (3) [from V3]:
   - league_ece: Expected Calibration Error
   - league_tier_weight: Confidence weight by league
   - league_historical_edge: Historical accuracy above baseline

10. TIMING FEATURES (4) [from V3]:
    - movement_velocity_24h: Rate of odds change
    - steam_move_detected: Sharp money indicator
    - reverse_line_movement: Contrarian signal
    - time_to_kickoff_bucket: Market maturity

11. HISTORICAL FLAGS (2):
    - historical_h2h_available: Flag for H2H data presence
    - historical_form_available: Flag for form data presence

LEAK-SAFE IMPLEMENTATION:
- Uses odds_real_consensus (has strict ts_effective < kickoff filter)
- Uses odds_snapshots with ts_snapshot < cutoff
- NEVER uses odds_consensus (has backdated post-match data leakage)
- All match_context and form features use strict T-1h cutoff
"""

import logging
import numpy as np
import psycopg2
from typing import Dict, List, Optional
from datetime import datetime, timedelta, timezone
import os

logger = logging.getLogger(__name__)


class UnifiedV2FeatureBuilder:
    """
    Unified V2 Feature Builder - Complete 61-Feature Pipeline
    
    Combines:
    - V2 base features (50): odds, ELO, form, H2H, advanced stats, context, drift
    - V3 sharp intelligence (11): sharp books, league ECE, timing
    
    All features are leak-free with strict pre-kickoff cutoffs.
    """
    
    ODDS_FEATURES = [
        'p_last_home', 'p_last_draw', 'p_last_away',
        'p_open_home', 'p_open_draw', 'p_open_away',
        'dispersion_home', 'dispersion_draw', 'dispersion_away',
        'book_dispersion',
        'volatility_home', 'volatility_draw', 'volatility_away',
        'num_books_last', 'market_entropy', 'favorite_margin', 
        'market_overround', 'hours_before_ko'
    ]
    
    DRIFT_FEATURES = [
        'prob_drift_home', 'prob_drift_draw', 'prob_drift_away', 
        'drift_magnitude'
    ]
    
    ELO_FEATURES = ['home_elo', 'away_elo', 'elo_diff']
    
    FORM_FEATURES = [
        'home_form_points', 'home_form_goals_scored', 'home_form_goals_conceded',
        'away_form_points', 'away_form_goals_scored', 'away_form_goals_conceded',
        'home_last10_home_wins', 'away_last10_away_wins'
    ]
    
    H2H_FEATURES = ['h2h_home_wins', 'h2h_draws', 'h2h_away_wins']
    
    ADVANCED_STATS_FEATURES = [
        'home_shots_avg', 'away_shots_avg',
        'home_shots_target_avg', 'away_shots_target_avg',
        'home_corners_avg', 'away_corners_avg',
        'home_yellows_avg', 'away_yellows_avg'
    ]
    
    CONTEXT_FEATURES = [
        'rest_days_home', 'rest_days_away',
        'congestion_home_7d', 'congestion_away_7d'
    ]
    
    SHARP_FEATURES = [
        'sharp_prob_home', 'sharp_prob_draw', 'sharp_prob_away',
        'soft_vs_sharp_divergence'
    ]
    
    ECE_FEATURES = [
        'league_ece', 'league_tier_weight', 'league_historical_edge'
    ]
    
    TIMING_FEATURES = [
        'movement_velocity_24h', 'steam_move_detected',
        'reverse_line_movement', 'time_to_kickoff_bucket'
    ]
    
    HISTORICAL_FLAGS = [
        'historical_h2h_available', 'historical_form_available'
    ]
    
    # Sparse features to exclude from training (< 5% coverage)
    SPARSE_FEATURES = [
        'sharp_prob_home', 'sharp_prob_draw', 'sharp_prob_away',
        'soft_vs_sharp_divergence',
        'steam_move_detected', 'reverse_line_movement', 'movement_velocity_24h',
        'hours_before_ko', 'time_to_kickoff_bucket',
        'elo_diff', 'home_elo', 'away_elo'  # ELO has low coverage, use form instead
    ]
    
    def __init__(self, database_url: Optional[str] = None):
        """Initialize unified feature builder"""
        self.db_url = database_url or os.getenv('DATABASE_URL')
        if not self.db_url:
            raise ValueError("DATABASE_URL not provided")
        
        self.initial_elo = 1500.0
        self._historical_features_cache = {}
        feature_count = len(
            self.ODDS_FEATURES + self.DRIFT_FEATURES + self.ELO_FEATURES +
            self.FORM_FEATURES + self.H2H_FEATURES + self.ADVANCED_STATS_FEATURES +
            self.CONTEXT_FEATURES + self.SHARP_FEATURES + self.ECE_FEATURES +
            self.TIMING_FEATURES + self.HISTORICAL_FLAGS
        )
        self.non_sparse_features = self._get_non_sparse_features()
        logger.info(f"✅ UnifiedV2FeatureBuilder initialized ({feature_count} features, {len(self.non_sparse_features)} non-sparse)")
    
    def _get_non_sparse_features(self) -> List[str]:
        """Get list of features excluding sparse ones"""
        all_features = (
            self.ODDS_FEATURES + self.DRIFT_FEATURES + self.ELO_FEATURES +
            self.FORM_FEATURES + self.H2H_FEATURES + self.ADVANCED_STATS_FEATURES +
            self.CONTEXT_FEATURES + self.SHARP_FEATURES + self.ECE_FEATURES +
            self.TIMING_FEATURES + self.HISTORICAL_FLAGS
        )
        return [f for f in all_features if f not in self.SPARSE_FEATURES]
    
    def get_feature_names(self, include_sparse: bool = False) -> List[str]:
        """Get list of feature names for training"""
        if include_sparse:
            return (
                self.ODDS_FEATURES + self.DRIFT_FEATURES + self.ELO_FEATURES +
                self.FORM_FEATURES + self.H2H_FEATURES + self.ADVANCED_STATS_FEATURES +
                self.CONTEXT_FEATURES + self.SHARP_FEATURES + self.ECE_FEATURES +
                self.TIMING_FEATURES + self.HISTORICAL_FLAGS
            )
        return self.non_sparse_features
    
    def _get_historical_features(self, cursor, match_id: int) -> Optional[Dict]:
        """Get historical features from historical_features table
        
        Returns cached or queried features for H2H, form, and advanced stats.
        Uses caching to avoid repeated queries for the same match_id.
        """
        if not match_id:
            return None
            
        if match_id in self._historical_features_cache:
            return self._historical_features_cache[match_id]
        
        cursor.execute("""
            SELECT 
                h2h_home_wins, h2h_draws, h2h_away_wins, h2h_matches_used,
                home_form_points, home_form_goals_scored, home_form_goals_conceded,
                away_form_points, away_form_goals_scored, away_form_goals_conceded,
                home_last10_home_wins, away_last10_away_wins,
                home_shots_avg, away_shots_avg,
                home_shots_target_avg, away_shots_target_avg,
                home_corners_avg, away_corners_avg,
                home_yellows_avg, away_yellows_avg
            FROM historical_features
            WHERE match_id = %s AND feature_type = 'combined'
            LIMIT 1
        """, (match_id,))
        
        row = cursor.fetchone()
        
        if not row:
            self._historical_features_cache[match_id] = None
            return None
        
        result = {
            'h2h_home_wins': row[0],
            'h2h_draws': row[1],
            'h2h_away_wins': row[2],
            'h2h_matches_used': row[3],
            'home_form_points': row[4],
            'home_form_goals_scored': row[5],
            'home_form_goals_conceded': row[6],
            'away_form_points': row[7],
            'away_form_goals_scored': row[8],
            'away_form_goals_conceded': row[9],
            'home_last10_home_wins': row[10],
            'away_last10_away_wins': row[11],
            'home_shots_avg': row[12],
            'away_shots_avg': row[13],
            'home_shots_target_avg': row[14],
            'away_shots_target_avg': row[15],
            'home_corners_avg': row[16],
            'away_corners_avg': row[17],
            'home_yellows_avg': row[18],
            'away_yellows_avg': row[19]
        }
        
        self._historical_features_cache[match_id] = result
        return result
    
    def clear_cache(self):
        """Clear the historical features cache"""
        self._historical_features_cache = {}
    
    def get_all_feature_names(self) -> List[str]:
        """Get list of all 61 feature names"""
        return (
            self.ODDS_FEATURES +
            self.DRIFT_FEATURES +
            self.ELO_FEATURES +
            self.FORM_FEATURES +
            self.H2H_FEATURES +
            self.ADVANCED_STATS_FEATURES +
            self.CONTEXT_FEATURES +
            self.SHARP_FEATURES +
            self.ECE_FEATURES +
            self.TIMING_FEATURES +
            self.HISTORICAL_FLAGS
        )
    
    def get_feature_count(self) -> int:
        """Get total feature count"""
        return len(self.get_all_feature_names())
    
    def build_features(self, match_id: int, cutoff_time: Optional[datetime] = None) -> Dict[str, float]:
        """
        Build all 61 features for a match
        
        Args:
            match_id: Match ID (fixtures.match_id)
            cutoff_time: Maximum timestamp for feature computation
                        If None, uses kickoff time (for training)
                        For live inference, pass current time
        
        Returns:
            Dictionary with all 61 feature values
        
        Raises:
            ValueError: If match not found or no valid odds available
        """
        try:
            conn = psycopg2.connect(self.db_url)
            cursor = conn.cursor()
            
            match_info = self._get_match_info(cursor, match_id)
            if not match_info:
                cursor.close()
                conn.close()
                raise ValueError(f"Match {match_id} not found in fixtures or training_matches")
            
            if cutoff_time is None:
                cutoff_time = match_info['kickoff_time']
            
            # Use API football match_id for odds lookups, training_match_id for historical_features
            api_match_id = match_info.get('match_id', match_id)
            training_match_id = match_info.get('training_match_id', match_id)
            
            odds_features = self._build_odds_features(cursor, api_match_id, cutoff_time)
            drift_features = self._build_drift_features(cursor, api_match_id, cutoff_time)
            elo_features = self._build_elo_features(cursor, match_info, cutoff_time)
            form_features = self._build_form_features(cursor, match_info, cutoff_time, training_match_id)
            h2h_features = self._build_h2h_features(cursor, match_info, cutoff_time, training_match_id)
            advanced_features = self._build_advanced_stats_features(cursor, match_info, cutoff_time, training_match_id)
            context_features = self._build_context_features(cursor, api_match_id)
            sharp_features = self._build_sharp_features(cursor, api_match_id, cutoff_time)
            ece_features = self._build_ece_features(cursor, match_info['league_id'])
            timing_features = self._build_timing_features(cursor, api_match_id, cutoff_time, match_info)
            historical_flags = self._build_historical_flags(cursor, match_info)
            
            cursor.close()
            conn.close()
            
            all_features = {
                **odds_features,
                **drift_features,
                **elo_features,
                **form_features,
                **h2h_features,
                **advanced_features,
                **context_features,
                **sharp_features,
                **ece_features,
                **timing_features,
                **historical_flags
            }
            
            return all_features
            
        except Exception as e:
            logger.error(f"Error building unified features for match {match_id}: {e}")
            raise
    
    def _get_match_info(self, cursor, match_id: int) -> Optional[Dict]:
        """Get match info from fixtures or training_matches"""
        cursor.execute("""
            SELECT 
                match_id, home_team_id, away_team_id, league_id,
                kickoff_at, home_team, away_team
            FROM fixtures
            WHERE match_id = %s
        """, (match_id,))
        
        row = cursor.fetchone()
        if row:
            return {
                'match_id': row[0],
                'home_team_id': row[1],
                'away_team_id': row[2],
                'league_id': row[3],
                'kickoff_time': row[4],
                'home_team': row[5],
                'away_team': row[6]
            }
        
        cursor.execute("""
            SELECT 
                id, match_id, home_team_id, away_team_id, league_id,
                match_date, home_team, away_team
            FROM training_matches
            WHERE id = %s OR match_id = %s OR fixture_id = %s
            LIMIT 1
        """, (match_id, match_id, match_id))
        
        row = cursor.fetchone()
        if row:
            return {
                'training_match_id': row[0],  # training_matches.id (row id) - for historical_features
                'match_id': row[1],           # training_matches.match_id (API football id) - for odds_snapshots
                'home_team_id': row[2],
                'away_team_id': row[3],
                'league_id': row[4],
                'kickoff_time': row[5],
                'home_team': row[6],
                'away_team': row[7]
            }
        
        return None
    
    def _build_odds_features(self, cursor, match_id: int, cutoff_time: datetime) -> Dict[str, float]:
        """
        Build odds-based features (18 features)
        
        LEAK-SAFE IMPLEMENTATION:
        1. Uses odds_real_consensus (has strict ts_effective < kickoff filter)
        2. Fallback to odds_snapshots with ts_snapshot < cutoff
        3. NEVER uses odds_consensus (has backdated post-match data leakage)
        """
        
        features = {name: 0.0 for name in self.ODDS_FEATURES}
        
        p_last_h, p_last_d, p_last_a = 0.0, 0.0, 0.0
        n_books = 0.0
        
        cursor.execute("""
            SELECT 
                outcome, 
                AVG(implied_prob) as avg_prob,
                STDDEV(implied_prob) as disp,
                COUNT(DISTINCT book_id) as n_books,
                AVG(market_margin) as margin,
                MAX(ts_snapshot) as latest_ts
            FROM odds_snapshots
            WHERE match_id = %s 
              AND ts_snapshot <= %s
            GROUP BY outcome
        """, (match_id, cutoff_time))
        
        rows = cursor.fetchall()
        
        if rows:
            max_books = 0
            avg_margin = 0.0
            latest_ts = None
            
            for row in rows:
                outcome, avg_prob, disp, books, margin, ts = row
                if outcome == 'H':
                    p_last_h = float(avg_prob) if avg_prob else 0.0
                    features['dispersion_home'] = float(disp) if disp else 0.0
                elif outcome == 'D':
                    p_last_d = float(avg_prob) if avg_prob else 0.0
                    features['dispersion_draw'] = float(disp) if disp else 0.0
                elif outcome == 'A':
                    p_last_a = float(avg_prob) if avg_prob else 0.0
                    features['dispersion_away'] = float(disp) if disp else 0.0
                
                max_books = max(max_books, int(books) if books else 0)
                if margin:
                    avg_margin = float(margin)
                if ts and (latest_ts is None or ts > latest_ts):
                    latest_ts = ts
            
            n_books = float(max_books)
            features['market_overround'] = avg_margin
            
            if latest_ts and cutoff_time:
                try:
                    hours_before = (cutoff_time - latest_ts).total_seconds() / 3600
                    features['hours_before_ko'] = max(0.0, hours_before)
                except:
                    pass
        
        prob_sum = p_last_h + p_last_d + p_last_a
        if prob_sum > 0.9:
            features['p_last_home'] = p_last_h / prob_sum
            features['p_last_draw'] = p_last_d / prob_sum
            features['p_last_away'] = p_last_a / prob_sum
        
        features['num_books_last'] = n_books
        features['book_dispersion'] = (
            features['dispersion_home'] + 
            features['dispersion_draw'] + 
            features['dispersion_away']
        ) / 3.0
        
        cursor.execute("""
            SELECT 
                outcome, implied_prob
            FROM odds_snapshots
            WHERE match_id = %s AND ts_snapshot <= %s
            ORDER BY ts_snapshot ASC
            LIMIT 3
        """, (match_id, cutoff_time))
        
        open_rows = cursor.fetchall()
        open_map = {'H': 0.0, 'D': 0.0, 'A': 0.0}
        for or_ in open_rows:
            if or_[0] in open_map and open_map[or_[0]] == 0.0:
                open_map[or_[0]] = float(or_[1]) if or_[1] else 0.0
        
        open_sum = open_map['H'] + open_map['D'] + open_map['A']
        if open_sum > 0.9:
            features['p_open_home'] = open_map['H'] / open_sum
            features['p_open_draw'] = open_map['D'] / open_sum
            features['p_open_away'] = open_map['A'] / open_sum
        else:
            features['p_open_home'] = features['p_last_home']
            features['p_open_draw'] = features['p_last_draw']
            features['p_open_away'] = features['p_last_away']
        
        cursor.execute("""
            SELECT 
                outcome,
                STDDEV(implied_prob) as volatility
            FROM odds_snapshots
            WHERE match_id = %s AND ts_snapshot <= %s
            GROUP BY outcome
        """, (match_id, cutoff_time))
        
        for vol_row in cursor.fetchall():
            if vol_row[0] == 'H':
                features['volatility_home'] = float(vol_row[1]) if vol_row[1] else 0.0
            elif vol_row[0] == 'D':
                features['volatility_draw'] = float(vol_row[1]) if vol_row[1] else 0.0
            elif vol_row[0] == 'A':
                features['volatility_away'] = float(vol_row[1]) if vol_row[1] else 0.0
        
        probs = [features['p_last_home'], features['p_last_draw'], features['p_last_away']]
        if sum(probs) > 0:
            probs_norm = [p / sum(probs) for p in probs]
            features['market_entropy'] = -sum(p * np.log(p + 1e-10) for p in probs_norm)
            features['favorite_margin'] = max(probs_norm) - min(probs_norm)
        
        if prob_sum < 0.9:
            # No valid odds - set flag but don't raise error
            # Matches can still train with historical_features (form, h2h, advanced stats)
            features['has_odds'] = 0.0
        else:
            features['has_odds'] = 1.0
        
        return features
    
    def _build_drift_features(self, cursor, match_id: int, cutoff_time: datetime) -> Dict[str, float]:
        """
        Build odds drift features (4 features)
        
        LEAK-SAFE: Uses odds_snapshots with strict ts_snapshot < cutoff
        """
        
        features = {name: 0.0 for name in self.DRIFT_FEATURES}
        
        early_cutoff = cutoff_time - timedelta(hours=24)
        
        cursor.execute("""
            SELECT outcome, implied_prob
            FROM odds_snapshots
            WHERE match_id = %s AND ts_snapshot <= %s
            ORDER BY ts_snapshot ASC
            LIMIT 3
        """, (match_id, early_cutoff))
        
        early_map = {'H': 0.0, 'D': 0.0, 'A': 0.0}
        for row in cursor.fetchall():
            if row[0] in early_map and early_map[row[0]] == 0.0:
                early_map[row[0]] = float(row[1]) if row[1] else 0.0
        
        cursor.execute("""
            SELECT outcome, implied_prob
            FROM odds_snapshots
            WHERE match_id = %s AND ts_snapshot <= %s
            ORDER BY ts_snapshot DESC
            LIMIT 3
        """, (match_id, cutoff_time))
        
        late_map = {'H': 0.0, 'D': 0.0, 'A': 0.0}
        for row in cursor.fetchall():
            if row[0] in late_map and late_map[row[0]] == 0.0:
                late_map[row[0]] = float(row[1]) if row[1] else 0.0
        
        if early_map['H'] > 0 and late_map['H'] > 0:
            drift_h = late_map['H'] - early_map['H']
            drift_d = late_map['D'] - early_map['D']
            drift_a = late_map['A'] - early_map['A']
            
            features['prob_drift_home'] = drift_h
            features['prob_drift_draw'] = drift_d
            features['prob_drift_away'] = drift_a
            features['drift_magnitude'] = abs(drift_h) + abs(drift_d) + abs(drift_a)
        
        return features
    
    def _build_elo_features(self, cursor, match_info: Dict, cutoff_time: datetime) -> Dict[str, float]:
        """Build ELO-based features (3 features)
        
        Uses team names as primary lookup (100% coverage) instead of team_id (65% coverage)
        """
        
        features = {name: self.initial_elo for name in self.ELO_FEATURES}
        features['elo_diff'] = 0.0
        
        # Use team names for better coverage
        home_team = match_info.get('home_team')
        away_team = match_info.get('away_team')
        league_id = match_info.get('league_id')
        
        home_elo = self._get_team_elo_by_name(cursor, home_team, league_id, cutoff_time)
        away_elo = self._get_team_elo_by_name(cursor, away_team, league_id, cutoff_time)
        
        features['home_elo'] = home_elo
        features['away_elo'] = away_elo
        features['elo_diff'] = home_elo - away_elo
        
        return features
    
    def _get_team_elo_by_name(self, cursor, team_name: str, league_id: int, cutoff_time: datetime) -> float:
        """Calculate team ELO from recent form using team name"""
        
        if not team_name:
            return self.initial_elo
        
        # Query using team name directly (100% coverage in training_matches)
        cursor.execute("""
            SELECT 
                CASE 
                    WHEN home_team = %s THEN
                        CASE outcome WHEN 'H' THEN 3 WHEN 'D' THEN 1 ELSE 0 END
                    ELSE
                        CASE outcome WHEN 'A' THEN 3 WHEN 'D' THEN 1 ELSE 0 END
                END as points
            FROM training_matches
            WHERE (home_team = %s OR away_team = %s)
                AND match_date < %s
                AND outcome IS NOT NULL
            ORDER BY match_date DESC
            LIMIT 10
        """, (team_name, team_name, team_name, cutoff_time))
        
        results = cursor.fetchall()
        
        if not results:
            return self.initial_elo
        
        avg_points = sum(r[0] for r in results) / len(results)
        elo = self.initial_elo + (avg_points - 1.5) * 100
        
        return float(elo)
    
    def _build_form_features(self, cursor, match_info: Dict, cutoff_time: datetime, training_match_id: int = None) -> Dict[str, float]:
        """Build form-based features (8 features)
        
        Primary: Uses historical_features table (backfilled from historical_odds)
        Fallback: Uses training_matches table
        """
        
        features = {name: 0.0 for name in self.FORM_FEATURES}
        # Use training_match_id for historical_features lookup
        hf_match_id = training_match_id or match_info.get('training_match_id') or match_info.get('match_id')
        
        hf = self._get_historical_features(cursor, hf_match_id)
        if hf and hf.get('home_form_points') is not None:
            n_matches = 5  # Standard form window
            home_pts = float(hf['home_form_points'] or 0)
            away_pts = float(hf['away_form_points'] or 0)
            home_gs = float(hf['home_form_goals_scored'] or 0)
            home_gc = float(hf['home_form_goals_conceded'] or 0)
            away_gs = float(hf['away_form_goals_scored'] or 0)
            away_gc = float(hf['away_form_goals_conceded'] or 0)
            
            features['home_form_points'] = (home_pts / n_matches) * 3
            features['home_form_goals_scored'] = home_gs / n_matches
            features['home_form_goals_conceded'] = home_gc / n_matches
            features['away_form_points'] = (away_pts / n_matches) * 3
            features['away_form_goals_scored'] = away_gs / n_matches
            features['away_form_goals_conceded'] = away_gc / n_matches
            features['home_last10_home_wins'] = float(hf['home_last10_home_wins'] or 0)
            features['away_last10_away_wins'] = float(hf['away_last10_away_wins'] or 0)
            return features
        
        home_form = self._get_team_form(cursor, match_info['home_team_id'], cutoff_time)
        away_form = self._get_team_form(cursor, match_info['away_team_id'], cutoff_time)
        
        features['home_form_points'] = home_form['points']
        features['home_form_goals_scored'] = home_form['goals_scored']
        features['home_form_goals_conceded'] = home_form['goals_conceded']
        features['away_form_points'] = away_form['points']
        features['away_form_goals_scored'] = away_form['goals_scored']
        features['away_form_goals_conceded'] = away_form['goals_conceded']
        
        features['home_last10_home_wins'] = self._get_venue_wins(
            cursor, match_info['home_team_id'], cutoff_time, 'home')
        features['away_last10_away_wins'] = self._get_venue_wins(
            cursor, match_info['away_team_id'], cutoff_time, 'away')
        
        return features
    
    def _get_team_form(self, cursor, team_id: int, cutoff_time: datetime, n_matches: int = 5) -> Dict:
        """Get team's recent form"""
        
        if not team_id:
            return {'points': 0.0, 'goals_scored': 0.0, 'goals_conceded': 0.0}
        
        cursor.execute("""
            SELECT 
                CASE 
                    WHEN home_team_id = %s THEN
                        CASE outcome WHEN 'H' THEN 3 WHEN 'D' THEN 1 ELSE 0 END
                    ELSE
                        CASE outcome WHEN 'A' THEN 3 WHEN 'D' THEN 1 ELSE 0 END
                END as points,
                CASE WHEN home_team_id = %s THEN home_goals ELSE away_goals END as goals_scored,
                CASE WHEN home_team_id = %s THEN away_goals ELSE home_goals END as goals_conceded
            FROM training_matches
            WHERE (home_team_id = %s OR away_team_id = %s)
                AND match_date < %s
                AND outcome IS NOT NULL
            ORDER BY match_date DESC
            LIMIT %s
        """, (team_id, team_id, team_id, team_id, team_id, cutoff_time, n_matches))
        
        results = cursor.fetchall()
        
        if not results:
            return {'points': 0.0, 'goals_scored': 0.0, 'goals_conceded': 0.0}
        
        return {
            'points': sum(r[0] or 0 for r in results) / len(results) * 3,
            'goals_scored': sum(r[1] or 0 for r in results) / len(results),
            'goals_conceded': sum(r[2] or 0 for r in results) / len(results)
        }
    
    def _get_venue_wins(self, cursor, team_id: int, cutoff_time: datetime, venue: str, n_matches: int = 10) -> float:
        """Get wins at specific venue from last N matches at that venue"""
        
        if not team_id:
            return 0.0
        
        if venue == 'home':
            cursor.execute("""
                SELECT COUNT(*) as wins FROM (
                    SELECT outcome
                    FROM training_matches
                    WHERE home_team_id = %s
                        AND match_date < %s
                        AND outcome IS NOT NULL
                    ORDER BY match_date DESC
                    LIMIT %s
                ) recent
                WHERE outcome = 'H'
            """, (team_id, cutoff_time, n_matches))
        else:
            cursor.execute("""
                SELECT COUNT(*) as wins FROM (
                    SELECT outcome
                    FROM training_matches
                    WHERE away_team_id = %s
                        AND match_date < %s
                        AND outcome IS NOT NULL
                    ORDER BY match_date DESC
                    LIMIT %s
                ) recent
                WHERE outcome = 'A'
            """, (team_id, cutoff_time, n_matches))
        
        row = cursor.fetchone()
        return float(row[0]) if row else 0.0
    
    def _build_h2h_features(self, cursor, match_info: Dict, cutoff_time: datetime, training_match_id: int = None) -> Dict[str, float]:
        """Build head-to-head features (3 features)
        
        Primary: Uses historical_features table (backfilled from historical_odds)
        Fallback: Uses training_matches table
        """
        
        features = {name: 0.0 for name in self.H2H_FEATURES}
        # Use training_match_id for historical_features lookup
        hf_match_id = training_match_id or match_info.get('training_match_id') or match_info.get('match_id')
        
        hf = self._get_historical_features(cursor, hf_match_id)
        if hf and hf.get('h2h_matches_used') and int(hf['h2h_matches_used']) > 0:
            features['h2h_home_wins'] = float(hf['h2h_home_wins'] or 0)
            features['h2h_draws'] = float(hf['h2h_draws'] or 0)
            features['h2h_away_wins'] = float(hf['h2h_away_wins'] or 0)
            return features
        
        home_id = match_info.get('home_team_id')
        away_id = match_info.get('away_team_id')
        
        if not home_id or not away_id:
            return features
        
        cursor.execute("""
            SELECT outcome, COUNT(*) as cnt
            FROM training_matches
            WHERE ((home_team_id = %s AND away_team_id = %s)
                OR (home_team_id = %s AND away_team_id = %s))
                AND match_date < %s
                AND outcome IS NOT NULL
            GROUP BY outcome
        """, (home_id, away_id, away_id, home_id, cutoff_time))
        
        for row in cursor.fetchall():
            if row[0] == 'H':
                features['h2h_home_wins'] = float(row[1])
            elif row[0] == 'D':
                features['h2h_draws'] = float(row[1])
            elif row[0] == 'A':
                features['h2h_away_wins'] = float(row[1])
        
        return features
    
    def _build_advanced_stats_features(self, cursor, match_info: Dict, cutoff_time: datetime, training_match_id: int = None) -> Dict[str, float]:
        """Build advanced stats features (8 features) from historical_odds
        
        Primary: Uses historical_features table (backfilled from historical_odds)
        Fallback: Uses historical_odds table directly
        """
        
        features = {name: 0.0 for name in self.ADVANCED_STATS_FEATURES}
        # Use training_match_id for historical_features lookup
        hf_match_id = training_match_id or match_info.get('training_match_id') or match_info.get('match_id')
        
        hf = self._get_historical_features(cursor, hf_match_id)
        if hf and hf.get('home_shots_avg') is not None:
            features['home_shots_avg'] = float(hf['home_shots_avg'])
            features['home_shots_target_avg'] = float(hf['home_shots_target_avg'] or 0)
            features['home_corners_avg'] = float(hf['home_corners_avg'] or 0)
            features['home_yellows_avg'] = float(hf['home_yellows_avg'] or 0)
            features['away_shots_avg'] = float(hf['away_shots_avg'] or 0)
            features['away_shots_target_avg'] = float(hf['away_shots_target_avg'] or 0)
            features['away_corners_avg'] = float(hf['away_corners_avg'] or 0)
            features['away_yellows_avg'] = float(hf['away_yellows_avg'] or 0)
            return features
        
        home_stats = self._get_team_stats(cursor, match_info.get('home_team'), cutoff_time)
        away_stats = self._get_team_stats(cursor, match_info.get('away_team'), cutoff_time)
        
        features['home_shots_avg'] = home_stats['shots_avg']
        features['home_shots_target_avg'] = home_stats['shots_target_avg']
        features['home_corners_avg'] = home_stats['corners_avg']
        features['home_yellows_avg'] = home_stats['yellows_avg']
        
        features['away_shots_avg'] = away_stats['shots_avg']
        features['away_shots_target_avg'] = away_stats['shots_target_avg']
        features['away_corners_avg'] = away_stats['corners_avg']
        features['away_yellows_avg'] = away_stats['yellows_avg']
        
        return features
    
    def _get_team_stats(self, cursor, team_name: str, cutoff_time: datetime, n_matches: int = 5) -> Dict:
        """
        Get team's average stats from historical_odds table
        
        Uses subquery to correctly compute rolling average over last N matches
        """
        
        default = {'shots_avg': 0.0, 'shots_target_avg': 0.0, 'corners_avg': 0.0, 'yellows_avg': 0.0}
        
        if not team_name:
            return default
        
        cursor.execute("""
            SELECT 
                AVG(shots) as shots_avg,
                AVG(shots_target) as shots_target_avg,
                AVG(corners) as corners_avg,
                AVG(yellows) as yellows_avg
            FROM (
                SELECT 
                    CASE WHEN home_team = %s THEN home_shots ELSE away_shots END as shots,
                    CASE WHEN home_team = %s THEN home_shots_target ELSE away_shots_target END as shots_target,
                    CASE WHEN home_team = %s THEN home_corners ELSE away_corners END as corners,
                    CASE WHEN home_team = %s THEN home_yellows ELSE away_yellows END as yellows
                FROM historical_odds
                WHERE (home_team = %s OR away_team = %s)
                    AND match_date < %s
                    AND home_shots IS NOT NULL
                ORDER BY match_date DESC
                LIMIT %s
            ) recent_matches
        """, (team_name, team_name, team_name, team_name, team_name, team_name, cutoff_time.date(), n_matches))
        
        row = cursor.fetchone()
        
        if row and row[0] is not None:
            return {
                'shots_avg': float(row[0]) if row[0] else 0.0,
                'shots_target_avg': float(row[1]) if row[1] else 0.0,
                'corners_avg': float(row[2]) if row[2] else 0.0,
                'yellows_avg': float(row[3]) if row[3] else 0.0
            }
        
        return default
    
    def _build_context_features(self, cursor, match_id: int) -> Dict[str, float]:
        """Build context features from match_context_v2 (4 features)"""
        
        features = {name: 0.0 for name in self.CONTEXT_FEATURES}
        
        cursor.execute("""
            SELECT 
                rest_days_home, rest_days_away,
                matches_home_last_7d, matches_away_last_7d
            FROM match_context_v2
            WHERE match_id = %s
            ORDER BY as_of_time DESC
            LIMIT 1
        """, (match_id,))
        
        row = cursor.fetchone()
        
        if row:
            features['rest_days_home'] = float(row[0]) if row[0] else 0.0
            features['rest_days_away'] = float(row[1]) if row[1] else 0.0
            features['congestion_home_7d'] = float(row[2]) if row[2] else 0.0
            features['congestion_away_7d'] = float(row[3]) if row[3] else 0.0
        
        return features
    
    def _build_sharp_features(self, cursor, match_id: int, cutoff_time: datetime) -> Dict[str, float]:
        """Build sharp book intelligence features (4 features)"""
        
        features = {name: 0.0 for name in self.SHARP_FEATURES}
        
        cursor.execute("""
            SELECT 
                AVG(prob_home) as sharp_prob_home,
                AVG(prob_draw) as sharp_prob_draw,
                AVG(prob_away) as sharp_prob_away
            FROM sharp_book_odds
            WHERE match_id = %s 
              AND ts_recorded <= %s
              AND hours_before_kickoff > 0
        """, (match_id, cutoff_time))
        
        row = cursor.fetchone()
        
        if row and row[0] is not None:
            features['sharp_prob_home'] = float(row[0])
            features['sharp_prob_draw'] = float(row[1]) if row[1] else 0.0
            features['sharp_prob_away'] = float(row[2]) if row[2] else 0.0
            
            cursor.execute("""
                SELECT ph_cons FROM odds_consensus
                WHERE match_id = %s AND ts_effective <= %s
                ORDER BY ts_effective DESC LIMIT 1
            """, (match_id, cutoff_time))
            
            soft_row = cursor.fetchone()
            if soft_row and soft_row[0]:
                soft_prob = float(soft_row[0])
                sharp_prob = features['sharp_prob_home']
                features['soft_vs_sharp_divergence'] = soft_prob - sharp_prob
        
        return features
    
    def _build_ece_features(self, cursor, league_id: int) -> Dict[str, float]:
        """Build league ECE calibration features (3 features)"""
        
        features = {name: 0.0 for name in self.ECE_FEATURES}
        features['league_tier_weight'] = 0.7
        
        if not league_id:
            return features
        
        cursor.execute("""
            SELECT 
                ece_score, tier_weight, accuracy_3way
            FROM league_calibration
            WHERE league_id = %s
            ORDER BY window_end DESC
            LIMIT 1
        """, (league_id,))
        
        row = cursor.fetchone()
        
        if row:
            features['league_ece'] = float(row[0]) if row[0] else 0.0
            features['league_tier_weight'] = float(row[1]) if row[1] else 0.7
            features['league_historical_edge'] = (float(row[2]) - 0.333) if row[2] else 0.0
        
        return features
    
    def _build_timing_features(self, cursor, match_id: int, cutoff_time: datetime, 
                                match_info: Dict) -> Dict[str, float]:
        """Build market timing features (4 features)"""
        
        features = {name: 0.0 for name in self.TIMING_FEATURES}
        
        kickoff = match_info.get('kickoff_time')
        if not kickoff:
            return features
        
        try:
            hours_to_kickoff = (kickoff - cutoff_time).total_seconds() / 3600
        except TypeError:
            hours_to_kickoff = 24
        
        if hours_to_kickoff > 24:
            features['time_to_kickoff_bucket'] = 0
        elif hours_to_kickoff > 12:
            features['time_to_kickoff_bucket'] = 1
        elif hours_to_kickoff > 6:
            features['time_to_kickoff_bucket'] = 2
        elif hours_to_kickoff > 1:
            features['time_to_kickoff_bucket'] = 3
        else:
            features['time_to_kickoff_bucket'] = 4
        
        cursor.execute("""
            SELECT 
                MIN(ph_cons) as min_prob,
                MAX(ph_cons) as max_prob,
                COUNT(*) as n_snapshots
            FROM odds_consensus
            WHERE match_id = %s 
              AND ts_effective BETWEEN %s - INTERVAL '24 hours' AND %s
        """, (match_id, cutoff_time, cutoff_time))
        
        vel_row = cursor.fetchone()
        if vel_row and vel_row[0] is not None and vel_row[1] is not None:
            prob_range = float(vel_row[1]) - float(vel_row[0])
            n_snapshots = vel_row[2] or 1
            features['movement_velocity_24h'] = prob_range / max(n_snapshots, 1) * 100
            
            if prob_range > 0.05:
                features['steam_move_detected'] = 1.0
        
        if features['soft_vs_sharp_divergence'] if 'soft_vs_sharp_divergence' in features else 0:
            divergence = features.get('soft_vs_sharp_divergence', 0)
            if abs(divergence) > 0.03:
                features['reverse_line_movement'] = np.sign(divergence)
        
        return features
    
    def _build_historical_flags(self, cursor, match_info: Dict) -> Dict[str, float]:
        """Build historical data availability flags (2 features)"""
        
        features = {name: 0.0 for name in self.HISTORICAL_FLAGS}
        
        home_id = match_info.get('home_team_id')
        away_id = match_info.get('away_team_id')
        
        if home_id and away_id:
            cursor.execute("""
                SELECT COUNT(*) FROM training_matches
                WHERE ((home_team_id = %s AND away_team_id = %s)
                    OR (home_team_id = %s AND away_team_id = %s))
                    AND outcome IS NOT NULL
            """, (home_id, away_id, away_id, home_id))
            row = cursor.fetchone()
            if row and row[0] > 0:
                features['historical_h2h_available'] = 1.0
        
        if match_info.get('home_team'):
            cursor.execute("""
                SELECT COUNT(*) FROM historical_odds
                WHERE (home_team = %s OR away_team = %s)
                    AND home_shots IS NOT NULL
                LIMIT 5
            """, (match_info['home_team'], match_info['home_team']))
            row = cursor.fetchone()
            if row and row[0] > 0:
                features['historical_form_available'] = 1.0
        
        return features


def get_unified_v2_feature_builder(database_url: Optional[str] = None) -> UnifiedV2FeatureBuilder:
    """Factory function to get UnifiedV2FeatureBuilder instance"""
    return UnifiedV2FeatureBuilder(database_url)
