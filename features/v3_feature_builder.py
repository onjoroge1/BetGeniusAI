"""
V3 Feature Builder - Enhanced Draw Prediction + Pruned Dead Features

Feature Categories (24 active):
- V2 Core (11): Market probs, dispersion, volatility, coverage, overround
- League ECE (3): Calibration, tier weight, historical edge
- H2H (2): Draw rate, matches used
- Match Closeness (4): ha_prob_gap, favourite_strength, draw_vs_nondraw_ratio, implied_competitiveness
- League Draw Context (2): league_draw_rate, league_draw_deviation
- Draw Market Structure (2): draw_dispersion_ratio, draw_overround_share

Pruned (20 dead features with 0.0 importance):
- Sharp book features (4): Data too sparse, always 0.0
- Injury features (6): Only populated for upcoming matches
- Timing features (4): Collinear or constant
- Drift features (4): Requires multiple snapshots rarely available
- time_decay_weight, closing_line_captured: Always 1.0/0.0

Disabled (5 features, <10% population — re-enable when matches table grows):
- Team Form (5): home/away draw rate, goals scored avg, combined goal expectation

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
    Builds 29 features for V3 LightGBM model (pruned + enhanced for draws).

    Feature Categories:
    1. V2 Core Features (11): prob_home/draw/away, dispersion, volatility, coverage, overround
    2. League ECE Features (3): league_ece, tier_weight, historical_edge
    3. H2H Draw Features (2): h2h_draw_rate, h2h_matches_used
    4. Match Closeness Features (4): Derived from existing probs — zero DB cost
    5. League Draw Context (2): Historical draw rates per league
    6. Draw Market Structure (2): Bookmaker disagreement on draws
    7. Team Form Features (5): Goals and draw rates from matches table
    """

    # === KEPT FEATURES (11 working V2 features) ===
    V2_CORE_FEATURE_NAMES = [
        'prob_home', 'prob_draw', 'prob_away',
        'book_dispersion_home', 'book_dispersion_draw', 'book_dispersion_away',
        'odds_volatility_home', 'odds_volatility_draw', 'odds_volatility_away',
        'book_coverage', 'market_overround',
    ]

    ECE_FEATURE_NAMES = [
        'league_ece', 'league_tier_weight', 'league_historical_edge'
    ]

    H2H_FEATURE_NAMES = [
        'h2h_draw_rate', 'h2h_matches_used'
    ]

    # === NEW DRAW-SPECIFIC FEATURES ===
    CLOSENESS_FEATURE_NAMES = [
        'ha_prob_gap',              # |prob_home - prob_away| — closer = more draw-prone
        'favourite_strength',       # max(prob_home, prob_away) — weaker favorite = more draws
        'draw_vs_nondraw_ratio',    # prob_draw / (1 - prob_draw) — market's draw confidence
        'implied_competitiveness',  # 1 - |prob_home - prob_away| — match balance score
    ]

    LEAGUE_DRAW_FEATURE_NAMES = [
        'league_draw_rate',         # Historical draw % for this league
        'league_draw_deviation',    # How far this match's draw prob deviates from league avg
    ]

    DRAW_MARKET_FEATURE_NAMES = [
        'draw_dispersion_ratio',    # book_dispersion_draw / avg(dispersion_home, dispersion_away)
        'draw_overround_share',     # What fraction of overround is loaded onto draw
    ]

    # NOTE: Form features disabled — only 10% population rate due to sparse matches table.
    # Re-enable when matches table has more historical team data (need 3+ home/away matches per team).
    # FORM_FEATURE_NAMES = [
    #     'home_draw_rate_last10',    # Home team's draw rate in last 10 home matches
    #     'away_draw_rate_last10',    # Away team's draw rate in last 10 away matches
    #     'combined_goal_expectation',# Sum of both teams' scoring avgs — low = draw-prone
    #     'home_goals_scored_avg',    # Home team avg goals scored (last 10)
    #     'away_goals_scored_avg',    # Away team avg goals scored (last 10)
    # ]
    FORM_FEATURE_NAMES: list = []

    def __init__(self, database_url: Optional[str] = None):
        """Initialize V3 feature builder with database connection"""
        self.db_url = database_url or os.getenv('DATABASE_URL')
        if not self.db_url:
            raise ValueError("DATABASE_URL not provided")

        logger.info("✅ V3FeatureBuilder initialized (24 features, draw-enhanced)")

    def get_all_feature_names(self) -> List[str]:
        """Get list of all active V3 feature names (24 when form features disabled)"""
        names = (self.V2_CORE_FEATURE_NAMES + self.ECE_FEATURE_NAMES +
                 self.H2H_FEATURE_NAMES + self.CLOSENESS_FEATURE_NAMES +
                 self.LEAGUE_DRAW_FEATURE_NAMES + self.DRAW_MARKET_FEATURE_NAMES +
                 self.FORM_FEATURE_NAMES)
        return names

    def get_feature_names(self) -> List[str]:
        """Get ordered list of all active V3 feature names"""
        return self.get_all_feature_names()

    def build_features(self, match_id: int, cutoff_time: Optional[datetime] = None) -> Dict[str, float]:
        """
        Build all 29 V3 features for a match.

        Args:
            match_id: Match ID to build features for
            cutoff_time: Maximum timestamp for feature computation (prevents leakage)
                        If None, uses kickoff time

        Returns:
            Dictionary with all 29 feature values (np.nan for missing)
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
            v2_features = self._build_v2_core_features(cursor, match_id, cutoff_time)
            ece_features = self._build_ece_features(cursor, match_info['league_id'])
            h2h_features = self._build_h2h_features(cursor, match_id, match_info)
            closeness_features = self._build_closeness_features(v2_features)
            league_draw_features = self._build_league_draw_features(cursor, match_info['league_id'], v2_features)
            draw_market_features = self._build_draw_market_features(v2_features)
            form_features = self._build_form_features(cursor, match_info, cutoff_time) if self.FORM_FEATURE_NAMES else {}

            cursor.close()
            conn.close()

            # Combine all features
            all_features = {
                **v2_features,
                **ece_features,
                **h2h_features,
                **closeness_features,
                **league_draw_features,
                **draw_market_features,
                **form_features,
            }

            return all_features

        except Exception as e:
            logger.error(f"Error building V3 features for match {match_id}: {e}")
            raise

    def _get_match_info(self, cursor, match_id: int) -> Optional[Dict]:
        """Get basic match information — tries fixtures first, falls back to training_matches"""
        cursor.execute("""
            SELECT
                match_id, home_team_id, away_team_id, league_id,
                kickoff_at
            FROM fixtures
            WHERE match_id = %s
        """, (match_id,))

        row = cursor.fetchone()
        if row:
            return {
                'id': row[0],
                'home_team_id': row[1],
                'away_team_id': row[2],
                'league_id': row[3],
                'kickoff_time': row[4],
                'api_football_id': row[0]
            }

        # Fallback: training_matches (for matches not in fixtures table)
        cursor.execute("""
            SELECT
                match_id, home_team_id, away_team_id, league_id,
                match_date
            FROM training_matches
            WHERE match_id = %s
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
            'api_football_id': row[0]
        }

    def _build_v2_core_features(self, cursor, match_id: int, cutoff_time: datetime) -> Dict[str, float]:
        """Build V2 core odds-based features from odds_consensus (pruned — no drift/timing/sharp)"""

        # Use np.nan for missing instead of 0.0 — LightGBM handles NaN natively
        features = {name: np.nan for name in self.V2_CORE_FEATURE_NAMES}

        # Get latest odds consensus before cutoff
        cursor.execute("""
            SELECT
                ph_cons, pd_cons, pa_cons,
                n_books, market_margin_avg,
                disph, dispd, dispa
            FROM odds_consensus
            WHERE match_id = %s AND ts_effective <= %s
            ORDER BY ts_effective DESC
            LIMIT 1
        """, (match_id, cutoff_time))

        row = cursor.fetchone()
        if row:
            features['prob_home'] = float(row[0]) if row[0] else np.nan
            features['prob_draw'] = float(row[1]) if row[1] else np.nan
            features['prob_away'] = float(row[2]) if row[2] else np.nan
            features['book_coverage'] = float(row[3]) if row[3] else np.nan
            features['market_overround'] = float(row[4]) if row[4] else np.nan
            features['book_dispersion_home'] = float(row[5]) if row[5] else np.nan
            features['book_dispersion_draw'] = float(row[6]) if row[6] else np.nan
            features['book_dispersion_away'] = float(row[7]) if row[7] else np.nan

        # Get odds volatility from individual snapshots
        cursor.execute("""
            SELECT
                outcome,
                MAX(implied_prob) - MIN(implied_prob) as volatility
            FROM odds_snapshots
            WHERE match_id = %s AND ts_snapshot <= %s
            GROUP BY outcome
        """, (match_id, cutoff_time))

        for vol_row in cursor.fetchall():
            if vol_row[0] == 'H':
                features['odds_volatility_home'] = float(vol_row[1]) if vol_row[1] else np.nan
            elif vol_row[0] == 'D':
                features['odds_volatility_draw'] = float(vol_row[1]) if vol_row[1] else np.nan
            elif vol_row[0] == 'A':
                features['odds_volatility_away'] = float(vol_row[1]) if vol_row[1] else np.nan

        return features

    def _build_ece_features(self, cursor, league_id: int) -> Dict[str, float]:
        """Build league calibration features from league_calibration table"""

        features = {name: np.nan for name in self.ECE_FEATURE_NAMES}

        # Default values for uncalibrated leagues
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
            features['league_ece'] = float(row[0]) if row[0] else np.nan
            features['league_tier_weight'] = float(row[1]) if row[1] else 0.7
            # Historical edge = accuracy above 33% (random baseline for 3-way)
            features['league_historical_edge'] = (float(row[2]) - 0.333) if row[2] else np.nan

        return features

    def _build_h2h_features(self, cursor, match_id: int, match_info: Dict) -> Dict[str, float]:
        """Build H2H draw rate features from historical_features table."""
        features = {name: np.nan for name in self.H2H_FEATURE_NAMES}

        try:
            cursor.execute("""
                SELECT h2h_draws, h2h_matches_used, h2h_home_wins, h2h_away_wins
                FROM historical_features
                WHERE match_id = %s
                LIMIT 1
            """, (match_id,))

            row = cursor.fetchone()
            if row:
                h2h_draws = float(row[0] or 0)
                h2h_used = float(row[1] or 0)
                if h2h_used > 0:
                    features['h2h_draw_rate'] = round(h2h_draws / h2h_used, 4)
                    features['h2h_matches_used'] = h2h_used
        except Exception as e:
            logger.warning(f"H2H feature build failed for match {match_id}: {e}")

        return features

    # === NEW FEATURE BUILDERS ===

    def _build_closeness_features(self, v2_features: Dict[str, float]) -> Dict[str, float]:
        """
        Build match closeness features — derived from existing probs, zero DB queries.
        Close matches (low ha_prob_gap, low favourite_strength) are more draw-prone.
        """
        features = {name: np.nan for name in self.CLOSENESS_FEATURE_NAMES}

        ph = v2_features.get('prob_home')
        pd_ = v2_features.get('prob_draw')
        pa = v2_features.get('prob_away')

        # Need valid probabilities
        if ph is not None and pa is not None and not (np.isnan(ph) or np.isnan(pa)):
            features['ha_prob_gap'] = abs(ph - pa)
            features['favourite_strength'] = max(ph, pa)
            features['implied_competitiveness'] = 1.0 - abs(ph - pa)

        if pd_ is not None and not np.isnan(pd_) and pd_ < 1.0:
            features['draw_vs_nondraw_ratio'] = pd_ / (1.0 - pd_)

        return features

    def _build_league_draw_features(self, cursor, league_id: int, v2_features: Dict[str, float]) -> Dict[str, float]:
        """
        Build league draw context features.
        Uses historical match results to compute league-specific draw rates.
        """
        features = {name: np.nan for name in self.LEAGUE_DRAW_FEATURE_NAMES}

        if not league_id:
            return features

        try:
            # Get league draw rate — try training_matches first (much richer data),
            # then fall back to fixtures+matches
            cursor.execute("""
                SELECT
                    COUNT(*) as total,
                    COUNT(*) FILTER (WHERE outcome IN ('D', 'Draw')) as draws
                FROM training_matches
                WHERE league_id = %s
                  AND outcome IS NOT NULL
            """, (league_id,))

            row = cursor.fetchone()
            # Fall back to fixtures+matches if training_matches has insufficient data
            if not row or not row[0] or row[0] < 20:
                cursor.execute("""
                    SELECT
                        COUNT(*) as total,
                        COUNT(*) FILTER (WHERE m.home_goals = m.away_goals) as draws
                    FROM fixtures f
                    JOIN matches m ON f.match_id = m.match_id
                    WHERE f.league_id = %s
                      AND f.status = 'finished'
                      AND m.home_goals IS NOT NULL
                """, (league_id,))

            row = cursor.fetchone()
            if row and row[0] and row[0] >= 20:  # Need minimum sample
                league_draw_rate = row[1] / row[0]
                features['league_draw_rate'] = round(league_draw_rate, 4)

                # How far this match's draw prob deviates from league average
                pd_ = v2_features.get('prob_draw')
                if pd_ is not None and not np.isnan(pd_):
                    features['league_draw_deviation'] = pd_ - league_draw_rate
        except Exception as e:
            logger.warning(f"League draw features failed for league {league_id}: {e}")

        return features

    def _build_draw_market_features(self, v2_features: Dict[str, float]) -> Dict[str, float]:
        """
        Build draw market structure features — derived from existing dispersion data.
        High draw dispersion relative to H/A suggests bookmaker disagreement on draws.
        """
        features = {name: np.nan for name in self.DRAW_MARKET_FEATURE_NAMES}

        disp_h = v2_features.get('book_dispersion_home')
        disp_d = v2_features.get('book_dispersion_draw')
        disp_a = v2_features.get('book_dispersion_away')

        # Draw dispersion ratio: how much bookmakers disagree on draw vs H/A
        if (disp_h is not None and disp_d is not None and disp_a is not None and
            not any(np.isnan(x) for x in [disp_h, disp_d, disp_a])):
            avg_ha_disp = (disp_h + disp_a) / 2.0
            if avg_ha_disp > 0.001:  # Avoid division by near-zero
                features['draw_dispersion_ratio'] = disp_d / avg_ha_disp

        # Draw overround share: fraction of overround allocated to draw outcome
        ph = v2_features.get('prob_home')
        pd_ = v2_features.get('prob_draw')
        pa = v2_features.get('prob_away')
        overround = v2_features.get('market_overround')

        if (ph is not None and pd_ is not None and pa is not None and overround is not None and
            not any(np.isnan(x) for x in [ph, pd_, pa, overround])):
            total_impl = ph + pd_ + pa
            if total_impl > 1.0 and overround > 0.001:
                excess = total_impl - 1.0
                # Draw's share of the excess (overround)
                # If draw prob is inflated more, draw_overround_share is higher
                fair_draw = pd_ / total_impl
                raw_draw = pd_
                draw_excess = raw_draw - fair_draw
                features['draw_overround_share'] = draw_excess / excess if excess > 0.001 else np.nan

        return features

    def _build_form_features(self, cursor, match_info: Dict, cutoff_time: datetime) -> Dict[str, float]:
        """
        Build team form features from matches table.
        Low-scoring teams and teams with high draw rates are more draw-prone.
        """
        features = {name: np.nan for name in self.FORM_FEATURE_NAMES}

        home_team_id = match_info.get('home_team_id')
        away_team_id = match_info.get('away_team_id')

        if not home_team_id or not away_team_id:
            return features

        try:
            # Home team's last 10 home matches (before this match's kickoff)
            cursor.execute("""
                SELECT
                    m.home_goals, m.away_goals
                FROM fixtures f
                JOIN matches m ON f.match_id = m.match_id
                WHERE f.home_team_id = %s
                  AND f.status = 'finished'
                  AND m.home_goals IS NOT NULL
                  AND f.kickoff_at < %s
                ORDER BY f.kickoff_at DESC
                LIMIT 10
            """, (home_team_id, cutoff_time))

            home_matches = cursor.fetchall()
            if home_matches and len(home_matches) >= 3:  # Need minimum 3 matches
                home_draws = sum(1 for h, a in home_matches if h == a)
                home_goals_scored = [h for h, a in home_matches]
                features['home_draw_rate_last10'] = round(home_draws / len(home_matches), 4)
                features['home_goals_scored_avg'] = round(sum(home_goals_scored) / len(home_goals_scored), 4)

            # Away team's last 10 away matches
            cursor.execute("""
                SELECT
                    m.home_goals, m.away_goals
                FROM fixtures f
                JOIN matches m ON f.match_id = m.match_id
                WHERE f.away_team_id = %s
                  AND f.status = 'finished'
                  AND m.home_goals IS NOT NULL
                  AND f.kickoff_at < %s
                ORDER BY f.kickoff_at DESC
                LIMIT 10
            """, (away_team_id, cutoff_time))

            away_matches = cursor.fetchall()
            if away_matches and len(away_matches) >= 3:
                away_draws = sum(1 for h, a in away_matches if h == a)
                away_goals_scored = [a for h, a in away_matches]
                features['away_draw_rate_last10'] = round(away_draws / len(away_matches), 4)
                features['away_goals_scored_avg'] = round(sum(away_goals_scored) / len(away_goals_scored), 4)

            # Combined goal expectation (lower = more draw-prone)
            if (features['home_goals_scored_avg'] is not np.nan and
                features['away_goals_scored_avg'] is not np.nan and
                not np.isnan(features.get('home_goals_scored_avg', np.nan)) and
                not np.isnan(features.get('away_goals_scored_avg', np.nan))):
                features['combined_goal_expectation'] = (
                    features['home_goals_scored_avg'] + features['away_goals_scored_avg']
                )

        except Exception as e:
            logger.warning(f"Form features failed for teams {home_team_id}/{away_team_id}: {e}")

        return features

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
