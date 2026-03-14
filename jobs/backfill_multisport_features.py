"""
Backfill multisport_training.features for NBA and NHL records that have
outcomes + odds but no features JSON.

Uses a fast batch approach:
  - Processes records in chronological order
  - Maintains running ELO state (O(n) vs naive O(n^2))
  - Single DB connection with pre-loaded lookups for form and rest

Run:
    python jobs/backfill_multisport_features.py [--sport basketball_nba|icehockey_nhl]
"""

import os
import sys
import json
import logging
import argparse
import psycopg2
from collections import defaultdict
from datetime import datetime, date, timedelta, timezone
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, '.')
from features.multisport_feature_builder import (
    MultisportFeatureBuilder, ELO_K, ELO_START, ELO_HOME_ADV,
    B2B_HOURS, SEASON_INFO
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

TARGET_SPORTS = ['basketball_nba', 'icehockey_nhl']


# ── Fast In-Memory Feature Computation ───────────────────────────────────────

class FastBatchBuilder:
    """
    Builds features for all records in a single sport in one pass.
    Pre-loads all historical data into memory to avoid N^2 queries.
    """

    def __init__(self, sport_key: str, db_url: str):
        self.sport_key = sport_key
        self.db_url    = db_url

    def build_all(self, records: List[Dict]) -> Tuple[List[Dict], int]:
        """Returns (enriched_records_with_features, error_count)."""
        if not records:
            return [], 0

        conn = psycopg2.connect(self.db_url)
        conn.autocommit = True
        cursor = conn.cursor()

        # Pre-load ALL training history for this sport (for form + ELO + H2H)
        cursor.execute("""
            SELECT home_team, away_team, outcome, home_score, away_score, match_date
            FROM multisport_training
            WHERE sport_key = %s AND outcome IN ('H','A')
              AND home_score IS NOT NULL
            ORDER BY match_date ASC
        """, (self.sport_key,))
        all_history = cursor.fetchall()

        # Pre-load ALL fixture data (for rest days)
        cursor.execute("""
            SELECT home_team, away_team, commence_time, status
            FROM multisport_fixtures
            WHERE sport_key = %s AND status = 'finished'
            ORDER BY commence_time ASC
        """, (self.sport_key,))
        all_fixtures = cursor.fetchall()

        # Pre-load odds for all target event_ids
        event_ids = [r['event_id'] for r in records]
        cursor.execute("""
            SELECT event_id,
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
                (ARRAY_AGG(home_prob ORDER BY ts_recorded ASC))[1] AS open_home_prob,
                (ARRAY_AGG(away_prob ORDER BY ts_recorded ASC))[1] AS open_away_prob,
                (ARRAY_AGG(home_spread ORDER BY ts_recorded ASC))[1] AS open_spread,
                (ARRAY_AGG(total_line ORDER BY ts_recorded ASC))[1] AS open_total,
                STDDEV(home_prob) AS home_odds_vol,
                COUNT(*) AS n_snapshots
            FROM multisport_odds_snapshots
            WHERE event_id = ANY(%s) AND sport_key = %s
            GROUP BY event_id
        """, (event_ids, self.sport_key))
        odds_map = {row[0]: row[1:] for row in cursor.fetchall()}

        cursor.close()
        conn.close()

        # Build lookups
        history_by_date = sorted(all_history, key=lambda x: x[5])  # already sorted
        fixture_lookup  = self._build_fixture_lookup(all_fixtures)

        # Sort records chronologically
        sorted_recs = sorted(records, key=lambda x: x['match_date'])

        # Walk forward: maintain running state
        elo_state: Dict[str, float] = {}
        results  = []
        errors   = 0

        # Pre-index history for fast lookups
        history_before: Dict[str, List] = defaultdict(list)  # team → games

        # We'll build history_before incrementally as we process records
        history_idx = 0   # pointer into history_by_date

        for rec in sorted_recs:
            cutoff = rec['match_date']
            if isinstance(cutoff, str):
                cutoff = datetime.strptime(cutoff, '%Y-%m-%d').date()

            # Advance history index up to cutoff (exclusive)
            while history_idx < len(history_by_date):
                row = history_by_date[history_idx]
                row_date = row[5] if isinstance(row[5], date) else row[5].date() if hasattr(row[5], 'date') else row[5]
                if row_date >= cutoff:
                    break
                home, away, outcome, hs, as_, gdate = row
                history_before[home].append(row)
                history_before[away].append(row)
                # Update ELO
                hr = elo_state.get(home, float(ELO_START))
                ar = elo_state.get(away, float(ELO_START))
                expected_h = 1.0 / (1.0 + 10 ** ((ar - hr) / 400))
                actual_h   = 1.0 if outcome == 'H' else 0.0
                elo_state[home] = hr + ELO_K * (actual_h       - expected_h)
                elo_state[away] = ar + ELO_K * ((1 - actual_h) - (1 - expected_h))
                history_idx += 1

            try:
                feats = self._compute_features(
                    rec=rec,
                    cutoff=cutoff,
                    odds_row=odds_map.get(rec['event_id']),
                    elo_state=elo_state,
                    team_history=history_before,
                    fixture_lookup=fixture_lookup,
                )
                results.append({'event_id': rec['event_id'], 'features': feats})
            except Exception as e:
                logger.debug(f"Feature error for {rec['event_id']}: {e}")
                errors += 1

        return results, errors

    def _build_fixture_lookup(self, all_fixtures) -> Dict[str, List]:
        """Build {team → sorted list of (commence_time,)} for rest day queries."""
        lookup: Dict[str, List] = defaultdict(list)
        for home, away, ct, status in all_fixtures:
            if ct:
                if hasattr(ct, 'replace'):
                    if ct.tzinfo is None:
                        ct = ct.replace(tzinfo=timezone.utc)
                lookup[home].append(ct)
                lookup[away].append(ct)
        # Sort each team's games
        for team in lookup:
            lookup[team].sort()
        return lookup

    def _compute_features(
        self,
        rec: Dict,
        cutoff,        # date
        odds_row,      # tuple from odds_map or None
        elo_state: Dict[str, float],
        team_history: Dict[str, List],
        fixture_lookup: Dict[str, List],
    ) -> Dict[str, float]:

        home = rec['home_team']
        away = rec['away_team']
        gd   = rec['match_date']

        # ── Odds + Spread/Totals ──────────────────────────────────────────────
        if odds_row:
            (prob_home, prob_away, overround, n_books, spread_line, total_line,
             home_spread_odds, away_spread_odds, over_odds, under_odds,
             open_hp, open_ap, open_spread, open_total, home_odds_vol, n_snaps) = odds_row

            prob_home  = float(prob_home  or 0.5)
            prob_away  = float(prob_away  or 0.5)
            open_hp    = float(open_hp    or prob_home)
            open_ap    = float(open_ap    or prob_away)
            spread_line = float(spread_line or 0.0)
            total_line  = float(total_line  or 0.0)
            open_spread = float(open_spread or spread_line)
            open_total  = float(open_total  or total_line)
        else:
            prob_home = 0.5; prob_away = 0.5
            open_hp = 0.5;   open_ap  = 0.5
            overround = 1.0; n_books  = 1.0; n_snaps = 0.0
            home_odds_vol = 0.0
            spread_line = 0.0; open_spread = 0.0
            total_line  = 0.0; open_total  = 0.0
            home_spread_odds = 0.0; away_spread_odds = 0.0
            over_odds = 0.0;   under_odds   = 0.0

        feats: Dict[str, float] = {
            'prob_home':          prob_home,
            'prob_away':          prob_away,
            'open_home_prob':     float(open_hp),
            'open_away_prob':     float(open_ap),
            'home_prob_drift':    prob_home - float(open_hp),
            'away_prob_drift':    prob_away - float(open_ap),
            'home_odds_volatility': float(home_odds_vol or 0.0),
            'overround':          float(overround or 1.0),
            'n_bookmakers':       float(n_books or 1),
            'n_snapshots':        float(n_snaps or 0),
            'odds_diff':          float(spread_line),
            'prob_diff':          prob_home - prob_away,
            'home_is_favorite':   1.0 if prob_home > 0.5 else 0.0,
            'spread_line':        float(spread_line),
            'spread_drift':       float(spread_line) - float(open_spread),
            'home_spread_odds':   float(home_spread_odds or 0.0),
            'away_spread_odds':   float(away_spread_odds or 0.0),
            'open_spread':        float(open_spread),
            'total_line':         float(total_line),
            'total_drift':        float(total_line) - float(open_total),
            'over_odds':          float(over_odds or 0.0),
            'under_odds':         float(under_odds or 0.0),
            'open_total':         float(open_total),
        }

        # ── Rest / Schedule ───────────────────────────────────────────────────
        cutoff_dt = datetime.combine(
            cutoff if isinstance(cutoff, date) else cutoff.date(),
            datetime.min.time()
        ).replace(tzinfo=timezone.utc)

        def rest_info(team: str) -> Tuple[float, float]:
            games = fixture_lookup.get(team, [])
            prev  = [g for g in games if g < cutoff_dt]
            if not prev:
                return 10.0, 0.0   # (rest_days, is_b2b)
            last  = prev[-1]
            hours = (cutoff_dt - last).total_seconds() / 3600
            return min(hours / 24, 14.0), (1.0 if hours <= B2B_HOURS else 0.0)

        hr_days, h_b2b = rest_info(home)
        ar_days, a_b2b = rest_info(away)

        feats.update({
            'home_rest_days': hr_days,
            'away_rest_days': ar_days,
            'home_is_b2b':    h_b2b,
            'away_is_b2b':    a_b2b,
            'rest_advantage': hr_days - ar_days,
            'b2b_disadvantage': a_b2b - h_b2b,
        })

        # ── Team Form ─────────────────────────────────────────────────────────
        def compute_form(team: str, last_n: int = 10) -> Tuple[float, float, float]:
            """Returns (wr_all, wr_home_only, avg_pts_diff)"""
            games = list(reversed(team_history.get(team, [])))[:last_n]
            if not games:
                return 0.5, 0.5, 0.0
            wins_all = 0; wins_home = 0; n_home = 0; pts_diffs = []
            for ht, at, outcome, hs, as_, gdate in games:
                is_home = (ht == team)
                won = (outcome == 'H' and is_home) or (outcome == 'A' and not is_home)
                if won:
                    wins_all += 1
                if is_home:
                    n_home += 1
                    if won:
                        wins_home += 1
                pd = float(hs or 0) - float(as_ or 0) if is_home else float(as_ or 0) - float(hs or 0)
                pts_diffs.append(pd)
            wr_all  = wins_all / len(games)
            wr_home = wins_home / n_home if n_home > 0 else 0.5
            pts_d   = sum(pts_diffs) / len(pts_diffs) if pts_diffs else 0.0
            return wr_all, wr_home, pts_d

        def season_wr(team: str) -> float:
            games = team_history.get(team, [])
            if not games:
                return 0.5
            wins = sum(
                1 for ht, at, outcome, _, _, _ in games
                if (ht == team and outcome == 'H') or (at == team and outcome == 'A')
            )
            return wins / len(games)

        h_wr, h_home_wr, h_pts = compute_form(home, 10)
        a_wr, a_away_wr, a_pts = compute_form(away, 10)

        feats.update({
            'home_win_rate_l10':    h_wr,
            'away_win_rate_l10':    a_wr,
            'home_season_win_rate': season_wr(home),
            'away_season_win_rate': season_wr(away),
            'home_home_win_rate':   h_home_wr,
            'away_away_win_rate':   a_away_wr,
            'home_pts_diff_avg':    max(min(h_pts, 30.0), -30.0),
            'away_pts_diff_avg':    max(min(a_pts, 30.0), -30.0),
            'form_advantage':       h_wr - a_wr,
        })

        # ── ELO ───────────────────────────────────────────────────────────────
        h_elo = elo_state.get(home, float(ELO_START))
        a_elo = elo_state.get(away, float(ELO_START))
        diff  = h_elo + ELO_HOME_ADV - a_elo
        win_prob = 1.0 / (1.0 + 10 ** (-diff / 400))

        feats.update({
            'home_elo':          h_elo,
            'away_elo':          a_elo,
            'elo_diff':          diff,
            'elo_home_win_prob': win_prob,
        })

        # ── H2H ───────────────────────────────────────────────────────────────
        h2h = [
            row for row in (team_history.get(home, []) + team_history.get(away, []))
            if ({row[0], row[1]} == {home, away})
        ]
        # deduplicate
        seen = set()
        h2h_dedup = []
        for row in h2h:
            key = (row[0], row[1], str(row[5]))
            if key not in seen:
                seen.add(key)
                h2h_dedup.append(row)
        h2h_dedup = sorted(h2h_dedup, key=lambda x: x[5], reverse=True)[:15]

        if h2h_dedup:
            h2h_home_wins = sum(
                1 for ht, at, outcome, _, _, _ in h2h_dedup
                if (ht == home and outcome == 'H') or (at == home and outcome == 'A')
            )
            feats.update({
                'h2h_home_win_rate': h2h_home_wins / len(h2h_dedup),
                'h2h_matches_used':  float(len(h2h_dedup)),
            })
        else:
            feats.update({'h2h_home_win_rate': 0.5, 'h2h_matches_used': 0.0})

        # ── Season Context ────────────────────────────────────────────────────
        if isinstance(gd, date):
            gdate = gd
        elif hasattr(gd, 'date'):
            gdate = gd.date()
        else:
            gdate = date.today()

        si   = SEASON_INFO.get(self.sport_key, {'start': (10, 1), 'end': (4, 30)})
        sm, sd = si['start']
        em, ed = si['end']
        yr   = gdate.year
        if gdate.month >= sm:
            season_start = date(yr,     sm, sd)
            season_end   = date(yr + 1, em, ed)
        else:
            season_start = date(yr - 1, sm, sd)
            season_end   = date(yr,     em, ed)

        total_d   = max((season_end - season_start).days, 1)
        elapsed_d = max((gdate - season_start).days, 0)
        feats.update({
            'season_progress':   min(elapsed_d / total_d, 1.0),
            'time_to_game_hours': 0.0,   # historical — no upcoming hours
        })

        return feats


# ── DB helpers ────────────────────────────────────────────────────────────────

def get_unfeaturised_records(conn, sport_key: str) -> List[Dict]:
    cursor = conn.cursor()
    cursor.execute("""
        SELECT event_id, home_team, away_team, match_date
        FROM multisport_training
        WHERE sport_key = %s
          AND outcome IS NOT NULL
          AND consensus_home_prob IS NOT NULL
          AND (features IS NULL OR features::text = 'null' OR features::text = '{}')
        ORDER BY match_date ASC
    """, (sport_key,))
    rows = cursor.fetchall()
    cursor.close()
    return [{'event_id': r[0], 'home_team': r[1], 'away_team': r[2], 'match_date': r[3]}
            for r in rows]


def save_features_batch(conn, sport_key: str, results: List[Dict]) -> int:
    cursor = conn.cursor()
    saved  = 0
    CHUNK  = 100
    for i in range(0, len(results), CHUNK):
        chunk = results[i:i + CHUNK]
        for item in chunk:
            try:
                cursor.execute("""
                    UPDATE multisport_training
                    SET features = %s
                    WHERE event_id = %s AND sport_key = %s
                """, (json.dumps(item['features']), item['event_id'], sport_key))
                saved += 1
            except Exception as e:
                logger.warning(f"Save error for {item['event_id']}: {e}")
        conn.commit()
    cursor.close()
    return saved


# ── Main ──────────────────────────────────────────────────────────────────────

def run_backfill(sport_key: str) -> Dict:
    db_url = os.getenv('DATABASE_URL')
    if not db_url:
        raise RuntimeError("DATABASE_URL not set")

    conn    = psycopg2.connect(db_url)
    records = get_unfeaturised_records(conn, sport_key)
    logger.info(f"{sport_key}: {len(records)} records need features")

    if not records:
        conn.close()
        return {'sport_key': sport_key, 'processed': 0, 'errors': 0}

    builder = FastBatchBuilder(sport_key, db_url)
    built, errors = builder.build_all(records)

    saved = save_features_batch(conn, sport_key, built)
    conn.close()

    logger.info(f"{sport_key}: {saved} features saved, {errors} errors")
    return {'sport_key': sport_key, 'processed': saved, 'errors': errors}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--sport', choices=TARGET_SPORTS + ['all'], default='all')
    args = parser.parse_args()
    sports = TARGET_SPORTS if args.sport == 'all' else [args.sport]
    for sport in sports:
        result = run_backfill(sport)
        logger.info(f"Result: {result}")


if __name__ == '__main__':
    main()
