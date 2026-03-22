"""
MultisportFeatureBuilder — NBA / NHL V3 Feature Engineering

46 features across 7 groups designed to be future-proof and gap-free:

  Group 1  ODDS          (13)  Consensus market probabilities, drift, volatility
  Group 2  SPREAD_TOTALS (10)  Point spread and over/under market signals
  Group 3  REST_SCHEDULE  (6)  Back-to-back detection and rest-day advantage
  Group 4  TEAM_FORM      (9)  Rolling win rates, home/away splits, points diff
  Group 5  ELO            (4)  Per-sport ELO ratings and win-probability
  Group 6  H2H            (2)  Head-to-head win rate and sample size
  Group 7  SEASON         (2)  Season progress and hours-to-game timing

Total: 46 features per match (2-outcome: H/A — no draw in NBA/NHL)
"""

import os
import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import psycopg2

logger = logging.getLogger(__name__)

# ── Season boundaries ──────────────────────────────────────────────────────────
# Used to compute season_progress (0.0 at start → 1.0 at end of regular season)
SEASON_INFO = {
    'basketball_nba': {
        'start': (10, 22),   # Oct 22
        'end':   (4, 15),    # Apr 15
        'total_games': 82,
    },
    'basketball_ncaab': {
        'start': (11, 4),    # Nov 4 (typical D1 season open)
        'end':   (4, 7),     # Apr 7 (NCAA Championship game)
        'total_games': 35,   # ~30-35 regular season + conf tournament
    },
    'icehockey_nhl': {
        'start': (10, 8),    # Oct 8
        'end':   (4, 18),    # Apr 18
        'total_games': 82,
    },
    'basketball_euroleague': {
        'start': (10, 1),
        'end':   (4, 30),
        'total_games': 34,
    },
    'americanfootball_nfl': {
        'start': (9, 7),     # Sept 7 (typical Thursday kickoff)
        'end':   (2, 12),    # Feb 12 (Super Bowl)
        'total_games': 17,   # 17 regular-season games per team
    },
}

# ELO parameters
ELO_K        = 20
ELO_START    = 1500
ELO_HOME_ADV = 35    # default home-court advantage in Elo points

# Sport-specific home court advantage (college has much stronger home advantage than NBA)
ELO_HOME_ADV_BY_SPORT = {
    'basketball_nba':       35,
    'basketball_ncaab':     70,   # college home crowds much louder; travel harder
    'basketball_euroleague': 40,
    'icehockey_nhl':        25,
}

# B2B threshold
B2B_HOURS = 26       # within 26 hours = back-to-back


class MultisportFeatureBuilder:

    ODDS_FEATURE_NAMES = [
        'prob_home', 'prob_away',
        'open_home_prob', 'open_away_prob',
        'home_prob_drift', 'away_prob_drift',
        'home_odds_volatility',
        'overround', 'n_bookmakers', 'n_snapshots',
        'odds_diff', 'prob_diff',
        'home_is_favorite',
    ]  # 13

    SPREAD_FEATURE_NAMES = [
        'spread_line', 'spread_drift',
        'home_spread_odds', 'away_spread_odds',
        'open_spread',
        'total_line', 'total_drift',
        'over_odds', 'under_odds',
        'open_total',
    ]  # 10

    REST_FEATURE_NAMES = [
        'home_rest_days', 'away_rest_days',
        'home_is_b2b', 'away_is_b2b',
        'rest_advantage',
        'b2b_disadvantage',
    ]  # 6

    FORM_FEATURE_NAMES = [
        'home_win_rate_l10', 'away_win_rate_l10',
        'home_season_win_rate', 'away_season_win_rate',
        'home_home_win_rate', 'away_away_win_rate',
        'home_pts_diff_avg', 'away_pts_diff_avg',
        'form_advantage',
    ]  # 9

    ELO_FEATURE_NAMES = [
        'home_elo', 'away_elo',
        'elo_diff', 'elo_home_win_prob',
    ]  # 4

    H2H_FEATURE_NAMES = [
        'h2h_home_win_rate',
        'h2h_matches_used',
    ]  # 2

    SEASON_FEATURE_NAMES = [
        'season_progress',
        'time_to_game_hours',
    ]  # 2

    # Total = 46
    ALL_FEATURE_NAMES = (
        ODDS_FEATURE_NAMES +
        SPREAD_FEATURE_NAMES +
        REST_FEATURE_NAMES +
        FORM_FEATURE_NAMES +
        ELO_FEATURE_NAMES +
        H2H_FEATURE_NAMES +
        SEASON_FEATURE_NAMES
    )

    def __init__(self, db_url: str):
        self.db_url = db_url
        self._elo_cache: Dict[str, Dict[str, float]] = {}   # sport_key → {team → elo}
        self._elo_built_for: Dict[str, Optional[str]] = {}  # sport_key → cutoff date

    @classmethod
    def get_feature_names(cls) -> List[str]:
        return cls.ALL_FEATURE_NAMES

    # ──────────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────────

    def build_features(
        self,
        sport_key: str,
        event_id: str,
        home_team: str,
        away_team: str,
        game_date,          # date or datetime
        cutoff_dt: Optional[datetime] = None,
    ) -> Dict[str, float]:
        """
        Build all 46 features for one match.

        cutoff_dt: upper bound for all historical queries (prevents data leakage).
        If None, uses game_date as the cutoff.
        """
        if cutoff_dt is None:
            if hasattr(game_date, 'date'):
                cutoff_dt = game_date
            else:
                cutoff_dt = datetime.combine(game_date, datetime.min.time()).replace(
                    tzinfo=timezone.utc
                )

        conn = psycopg2.connect(self.db_url)
        conn.autocommit = True
        try:
            cursor = conn.cursor()
            feats: Dict[str, float] = {}

            feats.update(self._build_odds_features(cursor, sport_key, event_id))
            feats.update(self._build_rest_features(cursor, sport_key, home_team, away_team, cutoff_dt))
            feats.update(self._build_form_features(cursor, sport_key, home_team, away_team, cutoff_dt))
            feats.update(self._build_elo_features(cursor, sport_key, home_team, away_team, cutoff_dt))
            feats.update(self._build_h2h_features(cursor, sport_key, home_team, away_team, cutoff_dt))
            feats.update(self._build_season_features(sport_key, game_date, cutoff_dt))

            cursor.close()
            return feats
        finally:
            conn.close()

    # ──────────────────────────────────────────────────────────────────────────
    # Group 1 + 2 — Odds & Spread/Totals
    # ──────────────────────────────────────────────────────────────────────────

    def _build_odds_features(
        self,
        cursor,
        sport_key: str,
        event_id: str,
    ) -> Dict[str, float]:
        zeros = {k: 0.0 for k in self.ODDS_FEATURE_NAMES + self.SPREAD_FEATURE_NAMES}

        try:
            cursor.execute("""
                SELECT
                    -- consensus (closing)
                    MAX(CASE WHEN is_consensus THEN home_prob  END) AS prob_home,
                    MAX(CASE WHEN is_consensus THEN away_prob  END) AS prob_away,
                    MAX(CASE WHEN is_consensus THEN overround  END) AS overround,
                    MAX(CASE WHEN is_consensus THEN n_bookmakers END) AS n_books,
                    MAX(CASE WHEN is_consensus THEN home_spread END) AS spread_line,
                    MAX(CASE WHEN is_consensus THEN total_line  END) AS total_line,
                    MAX(CASE WHEN is_consensus THEN home_spread_odds END) AS home_spread_odds,
                    MAX(CASE WHEN is_consensus THEN away_spread_odds END) AS away_spread_odds,
                    MAX(CASE WHEN is_consensus THEN over_odds  END) AS over_odds,
                    MAX(CASE WHEN is_consensus THEN under_odds END) AS under_odds,
                    -- opening (earliest snapshot)
                    (ARRAY_AGG(home_prob ORDER BY ts_recorded ASC))[1]   AS open_home_prob,
                    (ARRAY_AGG(away_prob ORDER BY ts_recorded ASC))[1]   AS open_away_prob,
                    (ARRAY_AGG(home_spread ORDER BY ts_recorded ASC))[1] AS open_spread,
                    (ARRAY_AGG(total_line ORDER BY ts_recorded ASC))[1]  AS open_total,
                    -- volatility
                    STDDEV(home_prob) AS home_odds_volatility,
                    COUNT(*)          AS n_snapshots
                FROM multisport_odds_snapshots
                WHERE event_id = %s AND sport_key = %s
            """, (event_id, sport_key))
            row = cursor.fetchone()
        except Exception as e:
            logger.warning(f"Odds query failed for {event_id}: {e}")
            return zeros

        if not row or row[0] is None:
            return zeros

        (prob_home, prob_away, overround, n_books, spread_line, total_line,
         home_spread_odds, away_spread_odds, over_odds, under_odds,
         open_home_prob, open_away_prob, open_spread, open_total,
         home_odds_volatility, n_snapshots) = row

        prob_home  = float(prob_home  or 0.5)
        prob_away  = float(prob_away  or 0.5)
        open_hp    = float(open_home_prob or prob_home)
        open_ap    = float(open_away_prob or prob_away)
        overround  = float(overround or 1.0)
        n_books    = float(n_books or 1)
        n_snapshots = float(n_snapshots or 0)
        home_odds_volatility = float(home_odds_volatility or 0.0)

        spread_line = float(spread_line or 0.0)
        total_line  = float(total_line  or 0.0)
        home_spread_odds = float(home_spread_odds or 0.0)
        away_spread_odds = float(away_spread_odds or 0.0)
        over_odds   = float(over_odds  or 0.0)
        under_odds  = float(under_odds or 0.0)
        open_spread = float(open_spread or spread_line)
        open_total  = float(open_total  or total_line)

        home_prob_drift = prob_home - open_hp
        away_prob_drift = prob_away - open_ap
        spread_drift    = spread_line - open_spread
        total_drift     = total_line  - open_total

        feats = {
            # Odds group
            'prob_home':          prob_home,
            'prob_away':          prob_away,
            'open_home_prob':     open_hp,
            'open_away_prob':     open_ap,
            'home_prob_drift':    home_prob_drift,
            'away_prob_drift':    away_prob_drift,
            'home_odds_volatility': home_odds_volatility,
            'overround':          overround,
            'n_bookmakers':       n_books,
            'n_snapshots':        n_snapshots,
            'odds_diff':          spread_line,         # re-use spread as odds_diff proxy
            'prob_diff':          prob_home - prob_away,
            'home_is_favorite':   1.0 if prob_home > 0.5 else 0.0,
            # Spread/Totals group
            'spread_line':        spread_line,
            'spread_drift':       spread_drift,
            'home_spread_odds':   home_spread_odds,
            'away_spread_odds':   away_spread_odds,
            'open_spread':        open_spread,
            'total_line':         total_line,
            'total_drift':        total_drift,
            'over_odds':          over_odds,
            'under_odds':         under_odds,
            'open_total':         open_total,
        }
        return feats

    # ──────────────────────────────────────────────────────────────────────────
    # Group 3 — Rest / Schedule
    # ──────────────────────────────────────────────────────────────────────────

    def _build_rest_features(
        self,
        cursor,
        sport_key: str,
        home_team: str,
        away_team: str,
        cutoff_dt: datetime,
    ) -> Dict[str, float]:
        zeros = {k: 0.0 for k in self.REST_FEATURE_NAMES}

        def last_game_dt(team: str) -> Optional[datetime]:
            try:
                cursor.execute("""
                    SELECT MAX(commence_time)
                    FROM multisport_fixtures
                    WHERE sport_key = %s
                      AND (home_team = %s OR away_team = %s)
                      AND status = 'finished'
                      AND commence_time < %s
                """, (sport_key, team, team, cutoff_dt))
                row = cursor.fetchone()
                return row[0] if row and row[0] else None
            except Exception:
                return None

        home_last = last_game_dt(home_team)
        away_last = last_game_dt(away_team)

        # normalise cutoff_dt to tz-aware
        if isinstance(cutoff_dt, datetime) and cutoff_dt.tzinfo is None:
            cutoff_dt = cutoff_dt.replace(tzinfo=timezone.utc)

        def rest_hours(last_dt: Optional[datetime]) -> float:
            if last_dt is None:
                return 240.0   # unknown → generous default (10 days)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            return max((cutoff_dt - last_dt).total_seconds() / 3600, 0.0)

        home_h = rest_hours(home_last)
        away_h = rest_hours(away_last)

        home_rest_days = min(home_h / 24, 14.0)
        away_rest_days = min(away_h / 24, 14.0)
        home_b2b = 1.0 if home_h <= B2B_HOURS else 0.0
        away_b2b = 1.0 if away_h <= B2B_HOURS else 0.0

        return {
            'home_rest_days':   home_rest_days,
            'away_rest_days':   away_rest_days,
            'home_is_b2b':      home_b2b,
            'away_is_b2b':      away_b2b,
            'rest_advantage':   home_rest_days - away_rest_days,
            'b2b_disadvantage': away_b2b - home_b2b,
        }

    # ──────────────────────────────────────────────────────────────────────────
    # Group 4 — Team Form
    # ──────────────────────────────────────────────────────────────────────────

    def _build_form_features(
        self,
        cursor,
        sport_key: str,
        home_team: str,
        away_team: str,
        cutoff_dt: datetime,
    ) -> Dict[str, float]:
        zeros = {k: 0.0 for k in self.FORM_FEATURE_NAMES}

        cutoff_date = cutoff_dt.date() if hasattr(cutoff_dt, 'date') else cutoff_dt

        def team_form(team: str, as_home: bool = False, n_games: int = 10):
            """Returns (win_rate, avg_pts_diff) for last n_games."""
            try:
                if as_home:
                    cursor.execute("""
                        SELECT outcome, home_score, away_score
                        FROM multisport_training
                        WHERE sport_key = %s AND home_team = %s AND match_date < %s
                          AND outcome IS NOT NULL AND home_score IS NOT NULL
                        ORDER BY match_date DESC LIMIT %s
                    """, (sport_key, team, cutoff_date, n_games))
                else:
                    cursor.execute("""
                        SELECT
                            CASE WHEN home_team = %s THEN outcome
                                 WHEN outcome = 'H' THEN 'A'
                                 WHEN outcome = 'A' THEN 'H'
                                 ELSE outcome END AS adj_outcome,
                            CASE WHEN home_team = %s THEN home_score - away_score
                                 ELSE away_score - home_score END AS pts_diff
                        FROM multisport_training
                        WHERE sport_key = %s
                          AND (home_team = %s OR away_team = %s)
                          AND match_date < %s
                          AND outcome IS NOT NULL AND home_score IS NOT NULL
                        ORDER BY match_date DESC LIMIT %s
                    """, (team, team, sport_key, team, team, cutoff_date, n_games))
                rows = cursor.fetchall()
                if not rows:
                    return 0.5, 0.0
                wins = sum(1 for r in rows if r[0] == 'H')
                pts_diffs = [float(r[1]) for r in rows if r[1] is not None]
                return wins / len(rows), (sum(pts_diffs) / len(pts_diffs) if pts_diffs else 0.0)
            except Exception as e:
                logger.debug(f"form query error: {e}")
                return 0.5, 0.0

        def season_win_rate(team: str) -> float:
            try:
                cursor.execute("""
                    SELECT COUNT(*) AS n,
                           SUM(CASE
                               WHEN home_team = %s AND outcome = 'H' THEN 1
                               WHEN away_team = %s AND outcome = 'A' THEN 1
                               ELSE 0 END) AS wins
                    FROM multisport_training
                    WHERE sport_key = %s
                      AND (home_team = %s OR away_team = %s)
                      AND match_date < %s
                      AND outcome IS NOT NULL
                """, (team, team, sport_key, team, team, cutoff_date))
                row = cursor.fetchone()
                if not row or not row[0]:
                    return 0.5
                return float(row[1]) / float(row[0]) if row[0] > 0 else 0.5
            except Exception:
                return 0.5

        home_wr_l10, home_pts = team_form(home_team, n_games=10)
        away_wr_l10, away_pts = team_form(away_team, n_games=10)
        home_home_wr, _ = team_form(home_team, as_home=True, n_games=20)
        away_away_wr, _ = team_form(away_team, as_home=False, n_games=20)
        home_szn = season_win_rate(home_team)
        away_szn = season_win_rate(away_team)

        return {
            'home_win_rate_l10':   home_wr_l10,
            'away_win_rate_l10':   away_wr_l10,
            'home_season_win_rate': home_szn,
            'away_season_win_rate': away_szn,
            'home_home_win_rate':  home_home_wr,
            'away_away_win_rate':  away_away_wr,
            'home_pts_diff_avg':   max(min(home_pts, 30.0), -30.0),
            'away_pts_diff_avg':   max(min(away_pts, 30.0), -30.0),
            'form_advantage':      home_wr_l10 - away_wr_l10,
        }

    # ──────────────────────────────────────────────────────────────────────────
    # Group 5 — ELO Ratings
    # ──────────────────────────────────────────────────────────────────────────

    def _build_elo_features(
        self,
        cursor,
        sport_key: str,
        home_team: str,
        away_team: str,
        cutoff_dt: datetime,
    ) -> Dict[str, float]:
        zeros = {k: 0.0 for k in self.ELO_FEATURE_NAMES}
        # Replace 0 defaults with neutral values
        zeros['home_elo'] = ELO_START
        zeros['away_elo'] = ELO_START
        zeros['elo_home_win_prob'] = 0.5

        try:
            elo_map = self._get_elo_at_cutoff(cursor, sport_key, cutoff_dt)
        except Exception as e:
            logger.warning(f"ELO computation failed: {e}")
            return zeros

        home_elo = elo_map.get(home_team, ELO_START)
        away_elo = elo_map.get(away_team, ELO_START)
        sport_home_adv = ELO_HOME_ADV_BY_SPORT.get(sport_key, ELO_HOME_ADV)
        diff = home_elo + sport_home_adv - away_elo
        win_prob = 1.0 / (1.0 + 10 ** (-diff / 400))

        return {
            'home_elo':         home_elo,
            'away_elo':         away_elo,
            'elo_diff':         diff,
            'elo_home_win_prob': win_prob,
        }

    def _get_elo_at_cutoff(
        self,
        cursor,
        sport_key: str,
        cutoff_dt: datetime,
    ) -> Dict[str, float]:
        """
        Build ELO ratings for all teams up to (but not including) cutoff_dt.
        Results are NOT cached across calls to ensure correct temporal isolation.
        """
        cutoff_date = cutoff_dt.date() if hasattr(cutoff_dt, 'date') else cutoff_dt

        cursor.execute("""
            SELECT home_team, away_team, outcome, match_date
            FROM multisport_training
            WHERE sport_key = %s AND outcome IS NOT NULL
              AND match_date < %s
            ORDER BY match_date ASC
        """, (sport_key, cutoff_date))
        rows = cursor.fetchall()

        ratings: Dict[str, float] = {}
        for home, away, outcome, _ in rows:
            hr = ratings.get(home, float(ELO_START))
            ar = ratings.get(away, float(ELO_START))
            expected_h = 1.0 / (1.0 + 10 ** ((ar - hr) / 400))
            actual_h   = 1.0 if outcome == 'H' else (0.5 if outcome == 'D' else 0.0)
            ratings[home] = hr + ELO_K * (actual_h       - expected_h)
            ratings[away] = ar + ELO_K * ((1 - actual_h) - (1 - expected_h))

        return ratings

    # ──────────────────────────────────────────────────────────────────────────
    # Group 6 — H2H
    # ──────────────────────────────────────────────────────────────────────────

    def _build_h2h_features(
        self,
        cursor,
        sport_key: str,
        home_team: str,
        away_team: str,
        cutoff_dt: datetime,
    ) -> Dict[str, float]:
        zeros = {'h2h_home_win_rate': 0.5, 'h2h_matches_used': 0.0}
        cutoff_date = cutoff_dt.date() if hasattr(cutoff_dt, 'date') else cutoff_dt
        try:
            cursor.execute("""
                SELECT outcome, home_team
                FROM multisport_training
                WHERE sport_key = %s
                  AND ((home_team = %s AND away_team = %s)
                    OR (home_team = %s AND away_team = %s))
                  AND match_date < %s
                  AND outcome IS NOT NULL
                ORDER BY match_date DESC
                LIMIT 15
            """, (sport_key, home_team, away_team, away_team, home_team, cutoff_date))
            rows = cursor.fetchall()
        except Exception:
            return zeros

        if not rows:
            return zeros

        total = len(rows)
        home_wins = sum(
            1 for outcome, ht in rows
            if (ht == home_team and outcome == 'H') or (ht == away_team and outcome == 'A')
        )
        return {
            'h2h_home_win_rate': home_wins / total,
            'h2h_matches_used':  float(total),
        }

    # ──────────────────────────────────────────────────────────────────────────
    # Group 7 — Season Context
    # ──────────────────────────────────────────────────────────────────────────

    def _build_season_features(
        self,
        sport_key: str,
        game_date,
        cutoff_dt: datetime,
    ) -> Dict[str, float]:
        if hasattr(game_date, 'date'):
            gd = game_date.date()
        elif hasattr(game_date, 'year'):
            gd = game_date
        else:
            return {'season_progress': 0.5, 'time_to_game_hours': 0.0}

        season_info = SEASON_INFO.get(sport_key, {'start': (10, 1), 'end': (4, 30)})
        start_m, start_d = season_info['start']
        end_m,   end_d   = season_info['end']

        year = gd.year
        # NBA/NHL cross calendar year
        if gd.month >= start_m:
            start = datetime(year,     start_m, start_d).date()
            end   = datetime(year + 1, end_m,   end_d).date()
        else:
            start = datetime(year - 1, start_m, start_d).date()
            end   = datetime(year,     end_m,   end_d).date()

        total_days   = max((end - start).days, 1)
        elapsed_days = max((gd - start).days, 0)
        season_progress = min(elapsed_days / total_days, 1.0)

        # Hours to game from now (or 0 if past)
        if isinstance(cutoff_dt, datetime):
            now = datetime.now(timezone.utc)
            if cutoff_dt.tzinfo is None:
                cutoff_dt = cutoff_dt.replace(tzinfo=timezone.utc)
            hours = max((cutoff_dt - now).total_seconds() / 3600, 0.0)
        else:
            hours = 0.0

        return {
            'season_progress':  season_progress,
            'time_to_game_hours': min(hours, 168.0),  # cap at 1 week
        }

    # ──────────────────────────────────────────────────────────────────────────
    # Batch build — used by backfill and training scripts
    # ──────────────────────────────────────────────────────────────────────────

    def build_features_batch(
        self,
        sport_key: str,
        records: List[Dict],
        progress_every: int = 50,
    ) -> Tuple[List[Dict], List[str]]:
        """
        Build features for a list of records.
        Each record must have: event_id, home_team, away_team, match_date.
        Returns (features_list, error_list).
        """
        results, errors = [], []
        for i, rec in enumerate(records, 1):
            if i % progress_every == 0:
                logger.info(f"  {i}/{len(records)} built (errors: {len(errors)})")
            try:
                gd = rec['match_date']
                if hasattr(gd, 'isoformat'):
                    cutoff_dt = datetime.combine(gd, datetime.min.time()).replace(tzinfo=timezone.utc)
                else:
                    cutoff_dt = None
                feats = self.build_features(
                    sport_key=sport_key,
                    event_id=rec['event_id'],
                    home_team=rec['home_team'],
                    away_team=rec['away_team'],
                    game_date=gd,
                    cutoff_dt=cutoff_dt,
                )
                results.append({'event_id': rec['event_id'], 'features': feats})
            except Exception as e:
                logger.error(f"Error building features for {rec.get('event_id')}: {e}")
                errors.append(rec['event_id'])
        return results, errors
