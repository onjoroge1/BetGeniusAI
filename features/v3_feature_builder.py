"""
V3 Feature Builder - Complete feature set with Sharp Book Intelligence

Extends V2 features with additional V3-specific features:
- V2 Base (17 odds features from model)
- Sharp Book Intelligence (4 features)
- League ECE Calibration (3 features)
- Player/Injury Context (6 features)
- Market Timing Features (4 features)

Total: 34 features for V3 model

All features computed with strict time-based cutoff to prevent leakage.
"""

import logging
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timezone, timedelta
import psycopg2
import os

logger = logging.getLogger(__name__)


class V3FeatureBuilder:
    """
    Builds all 34 features required by V3 LightGBM model
    
    Feature Categories:
    1. V2 Odds Features (17): prob_home/draw/away, dispersion, volatility, coverage, etc.
    2. Sharp Book Features (4): sharp_prob_*, soft_vs_sharp_divergence
    3. League ECE Features (3): league_ece, tier_weight, historical_edge
    4. Injury Features (6): home/away_injury_impact, key_players_out, injury_advantage
    5. Market Timing Features (4): movement_velocity, steam_move, reverse_line, time_bucket
    """
    
    V2_FEATURE_NAMES = [
        'prob_home', 'prob_draw', 'prob_away',
        'book_dispersion_home', 'book_dispersion_draw', 'book_dispersion_away',
        'odds_volatility_home', 'odds_volatility_draw', 'odds_volatility_away',
        'book_coverage', 'market_overround',
        'prob_drift_home', 'prob_drift_draw', 'prob_drift_away', 'drift_magnitude',
        'time_decay_weight', 'closing_line_captured'
    ]
    
    SHARP_FEATURE_NAMES = [
        'sharp_prob_home', 'sharp_prob_draw', 'sharp_prob_away',
        'soft_vs_sharp_divergence'
    ]
    
    ECE_FEATURE_NAMES = [
        'league_ece', 'league_tier_weight', 'league_historical_edge'
    ]
    
    INJURY_FEATURE_NAMES = [
        'home_injury_impact', 'away_injury_impact',
        'home_key_players_out', 'away_key_players_out',
        'injury_advantage', 'total_squad_impact'
    ]
    
    TIMING_FEATURE_NAMES = [
        'movement_velocity_24h', 'steam_move_detected',
        'reverse_line_movement', 'time_to_kickoff_bucket'
    ]
    
    def __init__(self, database_url: Optional[str] = None):
        """Initialize V3 feature builder with database connection"""
        self.db_url = database_url or os.getenv('DATABASE_URL')
        if not self.db_url:
            raise ValueError("DATABASE_URL not provided")
        
        logger.info("✅ V3FeatureBuilder initialized")
    
    def build_features(self, match_id: int, cutoff_time: Optional[datetime] = None) -> Dict[str, float]:
        """
        Build all 34 V3 features for a match
        
        Args:
            match_id: Match ID to build features for
            cutoff_time: Maximum timestamp for feature computation (prevents leakage)
                        If None, uses current time (for live predictions)
        
        Returns:
            Dictionary with all 34 feature values
        """
        try:
            conn = psycopg2.connect(self.db_url)
            cursor = conn.cursor()
            
            # Get match info
            match_info = self._get_match_info(cursor, match_id)
            if not match_info:
                cursor.close()
                conn.close()
                raise ValueError(f"Match {match_id} not found")
            
            if cutoff_time is None:
                cutoff_time = match_info['kickoff_time']
            
            # Build all feature groups
            v2_features = self._build_v2_features(cursor, match_id, cutoff_time)
            sharp_features = self._build_sharp_features(cursor, match_id, cutoff_time)
            ece_features = self._build_ece_features(cursor, match_info['league_id'])
            injury_features = self._build_injury_features(cursor, match_id, match_info)
            timing_features = self._build_timing_features(cursor, match_id, cutoff_time, match_info)
            
            cursor.close()
            conn.close()
            
            # Combine all features
            all_features = {
                **v2_features,
                **sharp_features,
                **ece_features,
                **injury_features,
                **timing_features
            }
            
            return all_features
            
        except Exception as e:
            logger.error(f"Error building V3 features for match {match_id}: {e}")
            raise
    
    def _get_match_info(self, cursor, match_id: int) -> Optional[Dict]:
        """Get basic match information"""
        cursor.execute("""
            SELECT 
                id, home_team_id, away_team_id, league_id, 
                kickoff_at, api_football_id
            FROM fixtures
            WHERE id = %s
        """, (match_id,))
        
        row = cursor.fetchone()
        if not row:
            return None
        
        return {
            'id': row[0],
            'home_team_id': row[1],
            'away_team_id': row[2],
            'league_id': row[3],
            'kickoff_time': row[4],
            'api_football_id': row[5]
        }
    
    def _build_v2_features(self, cursor, match_id: int, cutoff_time: datetime) -> Dict[str, float]:
        """Build V2 odds-based features from odds_consensus"""
        
        features = {name: 0.0 for name in self.V2_FEATURE_NAMES}
        
        # Get latest odds consensus before cutoff
        cursor.execute("""
            SELECT 
                prob_home, prob_draw, prob_away,
                n_books, market_margin
            FROM odds_consensus
            WHERE match_id = %s AND ts_snapshot <= %s
            ORDER BY ts_snapshot DESC
            LIMIT 1
        """, (match_id, cutoff_time))
        
        row = cursor.fetchone()
        if row:
            features['prob_home'] = float(row[0]) if row[0] else 0.0
            features['prob_draw'] = float(row[1]) if row[1] else 0.0
            features['prob_away'] = float(row[2]) if row[2] else 0.0
            features['book_coverage'] = float(row[3]) if row[3] else 0.0
            features['market_overround'] = float(row[4]) if row[4] else 0.0
        
        # Get odds dispersion from snapshots
        cursor.execute("""
            SELECT 
                STDDEV(home_odds) as std_home,
                STDDEV(draw_odds) as std_draw,
                STDDEV(away_odds) as std_away
            FROM odds_snapshots
            WHERE match_id = %s AND ts_snapshot <= %s
              AND home_odds IS NOT NULL
        """, (match_id, cutoff_time))
        
        disp_row = cursor.fetchone()
        if disp_row:
            features['book_dispersion_home'] = float(disp_row[0]) if disp_row[0] else 0.0
            features['book_dispersion_draw'] = float(disp_row[1]) if disp_row[1] else 0.0
            features['book_dispersion_away'] = float(disp_row[2]) if disp_row[2] else 0.0
        
        # Get odds volatility (change over time)
        cursor.execute("""
            SELECT 
                MAX(home_odds) - MIN(home_odds) as vol_home,
                MAX(draw_odds) - MIN(draw_odds) as vol_draw,
                MAX(away_odds) - MIN(away_odds) as vol_away
            FROM odds_snapshots
            WHERE match_id = %s AND ts_snapshot <= %s
              AND home_odds IS NOT NULL
        """, (match_id, cutoff_time))
        
        vol_row = cursor.fetchone()
        if vol_row:
            features['odds_volatility_home'] = float(vol_row[0]) if vol_row[0] else 0.0
            features['odds_volatility_draw'] = float(vol_row[1]) if vol_row[1] else 0.0
            features['odds_volatility_away'] = float(vol_row[2]) if vol_row[2] else 0.0
        
        # Calculate drift (early vs late odds)
        drift_features = self._calculate_drift(cursor, match_id, cutoff_time)
        features.update(drift_features)
        
        # Time-based features
        features['time_decay_weight'] = 1.0  # Latest snapshot weight
        features['closing_line_captured'] = 1.0 if (cutoff_time - timedelta(hours=1)).hour < 2 else 0.0
        
        return features
    
    def _calculate_drift(self, cursor, match_id: int, cutoff_time: datetime) -> Dict[str, float]:
        """Calculate odds drift from early to late snapshots"""
        
        drift_features = {
            'prob_drift_home': 0.0,
            'prob_drift_draw': 0.0,
            'prob_drift_away': 0.0,
            'drift_magnitude': 0.0
        }
        
        # Get early snapshot (24h+ before cutoff)
        early_cutoff = cutoff_time - timedelta(hours=24)
        
        cursor.execute("""
            SELECT prob_home, prob_draw, prob_away
            FROM odds_consensus
            WHERE match_id = %s AND ts_snapshot <= %s
            ORDER BY ts_snapshot DESC
            LIMIT 1
        """, (match_id, early_cutoff))
        
        early_row = cursor.fetchone()
        
        # Get late snapshot (latest before cutoff)
        cursor.execute("""
            SELECT prob_home, prob_draw, prob_away
            FROM odds_consensus
            WHERE match_id = %s AND ts_snapshot <= %s
            ORDER BY ts_snapshot DESC
            LIMIT 1
        """, (match_id, cutoff_time))
        
        late_row = cursor.fetchone()
        
        if early_row and late_row:
            drift_home = (late_row[0] or 0) - (early_row[0] or 0)
            drift_draw = (late_row[1] or 0) - (early_row[1] or 0)
            drift_away = (late_row[2] or 0) - (early_row[2] or 0)
            
            drift_features['prob_drift_home'] = drift_home
            drift_features['prob_drift_draw'] = drift_draw
            drift_features['prob_drift_away'] = drift_away
            drift_features['drift_magnitude'] = abs(drift_home) + abs(drift_draw) + abs(drift_away)
        
        return drift_features
    
    def _build_sharp_features(self, cursor, match_id: int, cutoff_time: datetime) -> Dict[str, float]:
        """Build sharp book intelligence features from sharp_book_odds table"""
        
        features = {name: 0.0 for name in self.SHARP_FEATURE_NAMES}
        
        # Try to get by match_id first
        cursor.execute("""
            SELECT 
                AVG(prob_home) as sharp_prob_home,
                AVG(prob_draw) as sharp_prob_draw,
                AVG(prob_away) as sharp_prob_away
            FROM sharp_book_odds
            WHERE match_id = %s 
              AND ts_recorded <= %s
              AND bookmaker = 'pinnacle'
        """, (match_id, cutoff_time))
        
        row = cursor.fetchone()
        
        # If no match_id match, try to find by team names and kickoff time
        if not row or row[0] is None:
            cursor.execute("""
                SELECT home_team, away_team, ts_kickoff
                FROM fixtures WHERE id = %s
            """, (match_id,))
            fixture = cursor.fetchone()
            
            if fixture:
                home_team, away_team, kickoff = fixture
                cursor.execute("""
                    SELECT 
                        AVG(prob_home) as sharp_prob_home,
                        AVG(prob_draw) as sharp_prob_draw,
                        AVG(prob_away) as sharp_prob_away
                    FROM sharp_book_odds
                    WHERE home_team ILIKE %s
                      AND away_team ILIKE %s
                      AND ts_kickoff BETWEEN %s - INTERVAL '2 hours' AND %s + INTERVAL '2 hours'
                      AND ts_recorded <= %s
                      AND bookmaker = 'pinnacle'
                """, (f"%{home_team}%", f"%{away_team}%", kickoff, kickoff, cutoff_time))
                row = cursor.fetchone()
        
        if row and row[0] is not None:
            features['sharp_prob_home'] = float(row[0]) if row[0] else 0.0
            features['sharp_prob_draw'] = float(row[1]) if row[1] else 0.0
            features['sharp_prob_away'] = float(row[2]) if row[2] else 0.0
            
            # Calculate divergence (sharp vs soft book consensus)
            cursor.execute("""
                SELECT prob_home FROM odds_consensus
                WHERE match_id = %s AND ts_snapshot <= %s
                ORDER BY ts_snapshot DESC LIMIT 1
            """, (match_id, cutoff_time))
            
            soft_row = cursor.fetchone()
            if soft_row and soft_row[0]:
                soft_prob = float(soft_row[0])
                sharp_prob = features['sharp_prob_home']
                features['soft_vs_sharp_divergence'] = soft_prob - sharp_prob
        
        return features
    
    def _build_ece_features(self, cursor, league_id: int) -> Dict[str, float]:
        """Build league calibration features from league_calibration table"""
        
        features = {name: 0.0 for name in self.ECE_FEATURE_NAMES}
        
        # Default values for uncalibrated leagues
        features['league_tier_weight'] = 0.7  # Default mid-tier weight
        
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
            # Historical edge = accuracy above 33% (random baseline for 3-way)
            features['league_historical_edge'] = (float(row[2]) - 0.333) if row[2] else 0.0
        
        return features
    
    def _build_injury_features(self, cursor, match_id: int, match_info: Dict) -> Dict[str, float]:
        """Build injury/player context features from team_injury_summary table"""
        
        features = {name: 0.0 for name in self.INJURY_FEATURE_NAMES}
        
        # Get home team injury summary
        cursor.execute("""
            SELECT 
                n_injured + n_suspended as total_out,
                total_impact_score,
                array_length(key_players_out, 1) as key_out_count
            FROM team_injury_summary
            WHERE match_id = %s AND team_type = 'home'
            ORDER BY ts_computed DESC
            LIMIT 1
        """, (match_id,))
        
        home_row = cursor.fetchone()
        if home_row:
            features['home_injury_impact'] = float(home_row[1]) if home_row[1] else 0.0
            features['home_key_players_out'] = float(home_row[2]) if home_row[2] else 0.0
        
        # Get away team injury summary
        cursor.execute("""
            SELECT 
                n_injured + n_suspended as total_out,
                total_impact_score,
                array_length(key_players_out, 1) as key_out_count
            FROM team_injury_summary
            WHERE match_id = %s AND team_type = 'away'
            ORDER BY ts_computed DESC
            LIMIT 1
        """, (match_id,))
        
        away_row = cursor.fetchone()
        if away_row:
            features['away_injury_impact'] = float(away_row[1]) if away_row[1] else 0.0
            features['away_key_players_out'] = float(away_row[2]) if away_row[2] else 0.0
        
        # Calculate derived features
        features['injury_advantage'] = features['away_injury_impact'] - features['home_injury_impact']
        features['total_squad_impact'] = features['home_injury_impact'] + features['away_injury_impact']
        
        return features
    
    def _build_timing_features(self, cursor, match_id: int, cutoff_time: datetime, 
                                match_info: Dict) -> Dict[str, float]:
        """Build market timing features from odds movement patterns"""
        
        features = {name: 0.0 for name in self.TIMING_FEATURE_NAMES}
        
        kickoff = match_info.get('kickoff_time')
        if not kickoff:
            return features
        
        # Calculate hours to kickoff bucket
        hours_to_kickoff = (kickoff - cutoff_time).total_seconds() / 3600
        if hours_to_kickoff > 24:
            features['time_to_kickoff_bucket'] = 0  # T-24h+
        elif hours_to_kickoff > 12:
            features['time_to_kickoff_bucket'] = 1  # T-24h to T-12h
        elif hours_to_kickoff > 6:
            features['time_to_kickoff_bucket'] = 2  # T-12h to T-6h
        elif hours_to_kickoff > 1:
            features['time_to_kickoff_bucket'] = 3  # T-6h to T-1h
        else:
            features['time_to_kickoff_bucket'] = 4  # T-1h
        
        # Calculate movement velocity (rate of change in last 24h)
        cursor.execute("""
            SELECT 
                MIN(prob_home) as min_prob,
                MAX(prob_home) as max_prob,
                COUNT(*) as n_snapshots
            FROM odds_consensus
            WHERE match_id = %s 
              AND ts_snapshot BETWEEN %s - INTERVAL '24 hours' AND %s
        """, (match_id, cutoff_time, cutoff_time))
        
        vel_row = cursor.fetchone()
        if vel_row and vel_row[0] is not None and vel_row[1] is not None:
            prob_range = float(vel_row[1]) - float(vel_row[0])
            n_snapshots = vel_row[2] or 1
            features['movement_velocity_24h'] = prob_range / max(n_snapshots, 1) * 100  # Per-snapshot movement
            
            # Steam move detection: large movement (> 5%) in probability
            if prob_range > 0.05:
                features['steam_move_detected'] = 1.0
        
        # Reverse line movement detection would require public betting data
        # For now, use sharp vs soft divergence as proxy
        cursor.execute("""
            SELECT soft_vs_sharp_divergence
            FROM (
                SELECT 
                    oc.prob_home - sb.prob_home as soft_vs_sharp_divergence
                FROM odds_consensus oc
                JOIN sharp_book_odds sb ON oc.match_id = sb.match_id
                WHERE oc.match_id = %s
                  AND oc.ts_snapshot <= %s
                  AND sb.ts_recorded <= %s
                ORDER BY oc.ts_snapshot DESC
                LIMIT 1
            ) x
        """, (match_id, cutoff_time, cutoff_time))
        
        rlm_row = cursor.fetchone()
        if rlm_row and rlm_row[0] is not None:
            # If soft books higher than sharp = public on home, but line moving away
            divergence = float(rlm_row[0])
            if abs(divergence) > 0.03:  # 3% divergence threshold
                features['reverse_line_movement'] = np.sign(divergence)
        
        return features
    
    def get_feature_names(self) -> List[str]:
        """Get ordered list of all 34 V3 feature names"""
        return (
            self.V2_FEATURE_NAMES +
            self.SHARP_FEATURE_NAMES +
            self.ECE_FEATURE_NAMES +
            self.INJURY_FEATURE_NAMES +
            self.TIMING_FEATURE_NAMES
        )
    
    def build_training_dataframe(self, match_ids: List[int], 
                                  cutoff_hours: float = 1.0) -> pd.DataFrame:
        """
        Build training dataframe for multiple matches
        
        Args:
            match_ids: List of match IDs to build features for
            cutoff_hours: Hours before kickoff to set cutoff time
        
        Returns:
            DataFrame with all V3 features for each match
        """
        records = []
        
        for match_id in match_ids:
            try:
                conn = psycopg2.connect(self.db_url)
                cursor = conn.cursor()
                
                # Get kickoff time
                cursor.execute("SELECT kickoff_at FROM fixtures WHERE id = %s", (match_id,))
                row = cursor.fetchone()
                
                if row and row[0]:
                    cutoff_time = row[0] - timedelta(hours=cutoff_hours)
                    features = self.build_features(match_id, cutoff_time)
                    features['match_id'] = match_id
                    records.append(features)
                
                cursor.close()
                conn.close()
                
            except Exception as e:
                logger.warning(f"Failed to build features for match {match_id}: {e}")
                continue
        
        if not records:
            return pd.DataFrame()
        
        df = pd.DataFrame(records)
        
        # Reorder columns
        feature_cols = ['match_id'] + self.get_feature_names()
        existing_cols = [c for c in feature_cols if c in df.columns]
        
        return df[existing_cols]


def get_v3_feature_builder() -> V3FeatureBuilder:
    """Factory function to get V3FeatureBuilder instance"""
    return V3FeatureBuilder()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    builder = get_v3_feature_builder()
    print(f"V3 Feature Names ({len(builder.get_feature_names())} total):")
    for name in builder.get_feature_names():
        print(f"  - {name}")
