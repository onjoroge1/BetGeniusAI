"""
Multisport Team Stats Collector

Two-source strategy:
  NHL: API-Sports standings endpoint (league 57, season 2024)
  NBA: Computed in-house from multisport_training match results
       (API-Sports free plan doesn't expose current NBA standings)

Runs daily. Populates multisport_team_stats for use by MultisportFeatureBuilder.

Run:
    python jobs/collect_multisport_team_stats.py
"""

import os
import sys
import json
import logging
import psycopg2
import requests
from datetime import date, datetime, timezone
from typing import Dict, List, Optional, Tuple

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

API_KEY = os.getenv('API_SPORTS_KEY') or os.getenv('RAPIDAPI_KEY')

NHL_CONFIG = {
    'sport_key': 'icehockey_nhl',
    'base_url':  'https://v1.hockey.api-sports.io',
    'league_id': 57,
    'season':    2024,
}

NBA_COMPUTE_CONFIG = {
    'sport_key':  'basketball_nba',
    'season':     '2025-26',
    'start_date': '2025-10-01',  # NBA season start
}


# ── Utilities ────────────────────────────────────────────────────────────────

def parse_record(record_str: Optional[str]) -> Tuple[int, int]:
    """Parse a 'W-L' record string like '24-10' → (24, 10). Returns (0, 0) on any error."""
    if not record_str:
        return (0, 0)
    try:
        parts = str(record_str).split('-')
        if len(parts) == 2:
            return (int(parts[0]), int(parts[1]))
    except (ValueError, AttributeError):
        pass
    return (0, 0)


# ── Helpers ───────────────────────────────────────────────────────────────────

def add_unique_constraint_if_missing(conn) -> None:
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT 1 FROM information_schema.table_constraints
            WHERE table_name = 'multisport_team_stats'
              AND constraint_type = 'UNIQUE'
              AND constraint_name = 'uq_team_stats_sport_team_season_date'
        """)
        if not cursor.fetchone():
            cursor.execute("""
                ALTER TABLE multisport_team_stats
                ADD CONSTRAINT uq_team_stats_sport_team_season_date
                UNIQUE (sport_key, team_id, season, stat_date)
            """)
            conn.commit()
            logger.info("Added unique constraint on multisport_team_stats")
    except Exception as e:
        conn.rollback()
        logger.debug(f"Constraint add skipped (may exist): {e}")
    finally:
        cursor.close()


def upsert_rows(conn, rows: List[Dict]) -> int:
    cursor = conn.cursor()
    saved = 0
    for row in rows:
        try:
            cursor.execute("""
                INSERT INTO multisport_team_stats
                    (sport_key, team_id, team_name, season, stat_date,
                     wins, losses, ties,
                     points_for, points_against,
                     home_record, away_record,
                     streak, conference, playoff_position,
                     stats_json, created_at, updated_at)
                VALUES (%s,%s,%s,%s,%s, %s,%s,%s, %s,%s, %s,%s, %s,%s,%s, %s, NOW(), NOW())
                ON CONFLICT (sport_key, team_id, season, stat_date) DO UPDATE SET
                    wins             = EXCLUDED.wins,
                    losses           = EXCLUDED.losses,
                    ties             = EXCLUDED.ties,
                    points_for       = EXCLUDED.points_for,
                    points_against   = EXCLUDED.points_against,
                    home_record      = EXCLUDED.home_record,
                    away_record      = EXCLUDED.away_record,
                    streak           = EXCLUDED.streak,
                    conference       = EXCLUDED.conference,
                    playoff_position = EXCLUDED.playoff_position,
                    stats_json       = EXCLUDED.stats_json,
                    updated_at       = NOW()
            """, (
                row['sport_key'], row['team_id'], row['team_name'],
                row['season'], row['stat_date'],
                row['wins'], row['losses'], row.get('ties', 0),
                row['points_for'], row['points_against'],
                row['home_record'], row['away_record'],
                row.get('streak', ''), row.get('conference', ''),
                row.get('position', 0),
                json.dumps(row['stats_json']),
            ))
            saved += 1
        except Exception as e:
            logger.warning(f"Upsert failed for {row.get('team_name')}: {e}")
            conn.rollback()
    conn.commit()
    cursor.close()
    return saved


# ── NHL — API-Sports ──────────────────────────────────────────────────────────

def collect_nhl_standings(conn) -> int:
    if not API_KEY:
        logger.warning("No API_SPORTS_KEY — skipping NHL API collection")
        return 0

    try:
        resp = requests.get(
            f"{NHL_CONFIG['base_url']}/standings",
            params={'league': NHL_CONFIG['league_id'], 'season': NHL_CONFIG['season']},
            headers={'x-apisports-key': API_KEY},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.error(f"NHL API request failed: {e}")
        return 0

    if data.get('errors'):
        logger.error(f"NHL API errors: {data['errors']}")
        return 0

    # Response is list of conference-lists
    raw_entries: List[Dict] = []
    for group in data.get('response', []):
        if isinstance(group, list):
            raw_entries.extend(group)

    if not raw_entries:
        logger.warning("No NHL standings entries in response")
        return 0

    today  = date.today().isoformat()
    season = str(NHL_CONFIG['season'])
    rows   = []

    for entry in raw_entries:
        try:
            team       = entry.get('team', {})
            team_id    = str(team.get('id', ''))
            team_name  = team.get('name', '')
            if not team_name:
                continue

            games      = entry.get('games', {})
            win_obj    = games.get('win', {})
            win_ot_obj = games.get('win_overtime', {})
            lose_obj   = games.get('lose', {})
            lose_ot    = games.get('lose_overtime', {})

            total_w   = int(win_obj.get('total', 0) or 0)
            total_wot = int(win_ot_obj.get('total', 0) or 0)
            total_l   = int(lose_obj.get('total', 0) or 0)
            total_lot = int(lose_ot.get('total', 0) or 0)

            goals      = entry.get('goals', {})
            pts_for    = float(goals.get('for', 0) or 0)
            pts_against = float(goals.get('against', 0) or 0)

            # NHL points (regulation wins = 2pts, OT wins = 2pts, OT losses = 1pt)
            nhl_pts = int(entry.get('points', 0) or 0)

            form_str = entry.get('form', '') or ''
            if form_str:
                streak_char = form_str[-1]
                streak_len  = len(form_str) - len(form_str.rstrip(streak_char))
                streak      = f"{streak_char}{streak_len}"
            else:
                streak = ''

            conf       = ''
            grp        = entry.get('group', {})
            if isinstance(grp, dict):
                conf = grp.get('name', '')

            gp = total_w + total_wot + total_l + total_lot
            rows.append({
                'sport_key':    NHL_CONFIG['sport_key'],
                'team_id':      team_id,
                'team_name':    team_name,
                'season':       season,
                'stat_date':    today,
                'wins':         total_w + total_wot,
                'losses':       total_l + total_lot,
                'ties':         0,
                'points_for':   pts_for,
                'points_against': pts_against,
                'home_record':  '',
                'away_record':  '',
                'streak':       streak,
                'conference':   conf,
                'position':     int(entry.get('position', 0) or 0),
                'stats_json': {
                    'regulation_wins': total_w,
                    'ot_wins':         total_wot,
                    'regulation_losses': total_l,
                    'ot_losses':        total_lot,
                    'games_played':     gp,
                    'nhl_points':       nhl_pts,
                    'win_pct':          round((total_w + total_wot) / max(gp, 1), 4),
                    'goals_for':        pts_for,
                    'goals_against':    pts_against,
                    'goal_diff':        pts_for - pts_against,
                },
            })
        except Exception as e:
            logger.warning(f"Parse error for {entry.get('team', {}).get('name', '?')}: {e}")

    saved = upsert_rows(conn, rows)
    logger.info(f"NHL: {len(raw_entries)} entries → {saved} saved")
    return saved


# ── NBA — Computed from multisport_training ───────────────────────────────────

def compute_nba_standings(conn) -> int:
    """
    Derive current-season team records from multisport_training.
    This is equivalent to official standings and avoids API plan restrictions.
    """
    cursor = conn.cursor()

    cfg       = NBA_COMPUTE_CONFIG
    sport_key = cfg['sport_key']
    season    = cfg['season']
    today     = date.today().isoformat()

    cursor.execute("""
        SELECT home_team, away_team, outcome, home_score, away_score, match_date
        FROM multisport_training
        WHERE sport_key = %s
          AND match_date >= %s
          AND outcome IN ('H','A')
          AND home_score IS NOT NULL
        ORDER BY match_date ASC
    """, (sport_key, cfg['start_date']))
    games = cursor.fetchall()
    cursor.close()

    if not games:
        logger.warning("No NBA game data to compute standings")
        return 0

    # Accumulate per-team stats
    stats: Dict[str, Dict] = {}

    def init_team(name: str):
        if name not in stats:
            stats[name] = {
                'wins': 0, 'losses': 0,
                'home_wins': 0, 'home_losses': 0,
                'away_wins': 0, 'away_losses': 0,
                'pts_for': 0.0, 'pts_against': 0.0,
                'last_results': [],   # 'W' or 'L', most recent last
            }

    for home, away, outcome, hs, as_, gdate in games:
        init_team(home)
        init_team(away)
        home_won = (outcome == 'H')
        # home
        if home_won:
            stats[home]['wins']       += 1
            stats[home]['home_wins']  += 1
            stats[away]['losses']     += 1
            stats[away]['away_losses'] += 1
            stats[home]['last_results'].append('W')
            stats[away]['last_results'].append('L')
        else:
            stats[home]['losses']     += 1
            stats[home]['home_losses'] += 1
            stats[away]['wins']       += 1
            stats[away]['away_wins']  += 1
            stats[home]['last_results'].append('L')
            stats[away]['last_results'].append('W')
        stats[home]['pts_for']      += float(hs or 0)
        stats[home]['pts_against']  += float(as_ or 0)
        stats[away]['pts_for']      += float(as_ or 0)
        stats[away]['pts_against']  += float(hs or 0)

    rows = []
    for i, (team_name, s) in enumerate(sorted(stats.items(),
                                               key=lambda x: -x[1]['wins']), 1):
        gp = s['wins'] + s['losses']
        if gp == 0:
            continue
        last10 = s['last_results'][-10:]
        streak_char = last10[-1] if last10 else 'W'
        streak_len  = len(last10) - len(''.join(last10).rstrip(streak_char))
        streak      = f"{streak_char}{streak_len}"

        rows.append({
            'sport_key':    sport_key,
            'team_id':      team_name.lower().replace(' ', '_'),
            'team_name':    team_name,
            'season':       season,
            'stat_date':    today,
            'wins':         s['wins'],
            'losses':       s['losses'],
            'ties':         0,
            'points_for':   round(s['pts_for'], 1),
            'points_against': round(s['pts_against'], 1),
            'home_record':  f"{s['home_wins']}-{s['home_losses']}",
            'away_record':  f"{s['away_wins']}-{s['away_losses']}",
            'streak':       streak,
            'conference':   '',
            'position':     i,
            'stats_json': {
                'games_played':  gp,
                'wins':          s['wins'],
                'losses':        s['losses'],
                'win_pct':       round(s['wins'] / gp, 4),
                'home_wins':     s['home_wins'],
                'home_losses':   s['home_losses'],
                'home_win_pct':  round(s['home_wins'] / max(s['home_wins'] + s['home_losses'], 1), 4),
                'away_wins':     s['away_wins'],
                'away_losses':   s['away_losses'],
                'away_win_pct':  round(s['away_wins'] / max(s['away_wins'] + s['away_losses'], 1), 4),
                'pts_per_game':  round(s['pts_for'] / gp, 2),
                'pts_against_per_game': round(s['pts_against'] / gp, 2),
                'net_pts':       round((s['pts_for'] - s['pts_against']) / gp, 2),
                'last_10':       ''.join(last10[-10:]),
            },
        })

    saved = upsert_rows(conn, rows)
    logger.info(f"NBA: computed {len(rows)} team records → {saved} saved")
    return saved


# ── Main ──────────────────────────────────────────────────────────────────────

def run_collection() -> Dict:
    db_url = os.getenv('DATABASE_URL')
    if not db_url:
        raise RuntimeError("DATABASE_URL not set")

    conn = psycopg2.connect(db_url)
    add_unique_constraint_if_missing(conn)

    nhl_saved = collect_nhl_standings(conn)
    nba_saved = compute_nba_standings(conn)

    conn.close()
    return {
        'icehockey_nhl':  {'saved': nhl_saved},
        'basketball_nba': {'saved': nba_saved},
    }


if __name__ == '__main__':
    result = run_collection()
    logger.info(f"Collection complete: {result}")
