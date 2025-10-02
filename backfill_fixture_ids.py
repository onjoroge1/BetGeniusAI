#!/usr/bin/env python3
"""
Backfill fixture_id for training_matches using enhanced TeamMatcher.

Key changes:
- Auto-discovers ALL leagues present in training_matches for the date window.
- Infers season logic per league ('year_start' vs 'calendar') from match-date distribution.
- Optional per-league overrides if you need to force a season logic.
- Keeps batching, throttling, diagnostics, and cache seeding.
"""

import os
import psycopg2
from datetime import datetime
from utils.api_football_client import ApiFootballClient
from utils.team_matcher import TeamMatcher
import logging
import time
from typing import Dict, List, Set, Tuple

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("backfill_fixture_ids")

DATABASE_URL = os.getenv('DATABASE_URL')

# ✳️ Date window to process
DATE_MIN = '2024-08-01'
DATE_MAX = '2025-05-31'

# ✳️ (Optional) Force season logic for specific leagues if you want to override inference:
# Example: {253: 'calendar', 39: 'year_start'}
FORCE_SEASON_LOGIC: Dict[int, str] = {}

# ✳️ Inference thresholds
# If ≥60% of matches (in the window) are in Aug–Dec, we assume 'year_start' (Euro-style).
YEAR_START_THRESHOLD = 0.60
AUG_DEC = {8, 9, 10, 11, 12}


def get_season_from_date(match_date: datetime,
                         season_logic: str = 'year_start') -> int:
    """
    'year_start' (typical Europe, Aug–May):
      - Aug–Dec → season = match_date.year
      - Jan–Jul → season = match_date.year - 1

    'calendar' (e.g., MLS, many leagues within a single calendar year):
      - season = match_date.year
    """
    if season_logic == 'calendar':
        return match_date.year
    # default: 'year_start'
    return match_date.year if match_date.month >= 8 else match_date.year - 1


def fetch_present_leagues(conn) -> Set[int]:
    """Leagues that have matches missing fixture_id within the date window."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT DISTINCT league_id
            FROM training_matches
            WHERE fixture_id IS NULL
              AND match_date IS NOT NULL
              AND match_date BETWEEN %s AND %s
        """, (DATE_MIN, DATE_MAX))
        return {row[0] for row in cursor.fetchall()}


def infer_season_logic_from_data(conn, league_id: int) -> str:
    """
    Infer season logic based on distribution of match months in the window.
    Heuristic:
      - If >= YEAR_START_THRESHOLD of matches are in Aug–Dec → 'year_start'
      - Else → 'calendar'
    You can override any result via FORCE_SEASON_LOGIC.
    """
    if league_id in FORCE_SEASON_LOGIC:
        return FORCE_SEASON_LOGIC[league_id]

    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT EXTRACT(MONTH FROM match_date)::INT AS m, COUNT(*)
            FROM training_matches
            WHERE fixture_id IS NULL
              AND match_date IS NOT NULL
              AND match_date BETWEEN %s AND %s
              AND league_id = %s
            GROUP BY 1
        """, (DATE_MIN, DATE_MAX, league_id))
        rows = cursor.fetchall()

    if not rows:
        # Fallback safe default
        return 'year_start'

    total = sum(c for _, c in rows)
    aug_dec = sum(c for m, c in rows if m in AUG_DEC)
    share = aug_dec / total if total else 0.0

    season_logic = 'year_start' if share >= YEAR_START_THRESHOLD else 'calendar'
    logger.info(
        f"Inferred season_logic for league {league_id}: {season_logic} "
        f"(Aug–Dec share={share:.1%}, total={total})")
    return season_logic


def build_dynamic_mapping(conn) -> Dict[int, Dict[str, str]]:
    """
    Build mapping for ALL present leagues:
      { league_id: {'api_football_id': league_id, 'name': f'League {league_id}', 'season_logic': ... } }
    We assume DB league_id == API-Football league id (matches your current usage).
    Name is a placeholder unless you want to look it up; not required for functionality.
    """
    present = fetch_present_leagues(conn)
    mapping: Dict[int, Dict[str, str]] = {}

    logger.info("\n" + "=" * 80)
    logger.info("BUILDING LEAGUE MAPPING (AUTO)")
    logger.info("=" * 80)
    logger.info(
        f"Leagues present in window {DATE_MIN} → {DATE_MAX}: {sorted(present)}"
    )

    for lid in sorted(present):
        season_logic = infer_season_logic_from_data(conn, lid)
        mapping[lid] = {
            'api_football_id': lid,
            'name': f'League {lid}',
            'season_logic': season_logic
        }
    logger.info(
        f"✅ Built mapping for {len(mapping)} leagues (all present in DB for the window)."
    )
    return mapping


def seed_team_cache(conn, matcher: TeamMatcher,
                    league_mapping: Dict[int, Dict[str, str]]):
    """
    Pre-seed team cache for all (league,year) combos inferred from data.
    For 'year_start' we cache [year, year-1]; for 'calendar' just [year].
    """
    logger.info("\n" + "=" * 80)
    logger.info("SEEDING TEAM CACHE")
    logger.info("=" * 80)

    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT DISTINCT league_id, EXTRACT(YEAR FROM match_date)::INT AS year
            FROM training_matches
            WHERE fixture_id IS NULL
              AND match_date IS NOT NULL
              AND match_date BETWEEN %s AND %s
            ORDER BY year DESC, league_id
        """, (DATE_MIN, DATE_MAX))
        combinations = cursor.fetchall()

    logger.info(
        f"Found {len(combinations)} unique league/year combos in window {DATE_MIN} → {DATE_MAX}"
    )

    total_cached = 0
    for league_id, year in combinations:
        if league_id not in league_mapping:
            # Shouldn’t happen, but be defensive
            logger.warning(
                f"Skipping team cache for league {league_id} (not in dynamic mapping)"
            )
            continue

        league_info = league_mapping[league_id]
        season_logic = league_info['season_logic']

        seasons_to_cache: List[int] = [int(year)
                                       ] if season_logic == 'calendar' else [
                                           int(year), int(year) - 1
                                       ]

        for season in seasons_to_cache:
            if season < 2020:
                continue
            try:
                count = matcher.ensure_team_cache(league_id, season)
                if count > 0:
                    total_cached += count
                    logger.info(
                        f"✅ Cached {count} teams for {league_info['name']} season {season}"
                    )
                time.sleep(0.5)  # gentle rate limit
            except Exception as e:
                logger.warning(
                    f"Failed to cache {league_info['name']} {season}: {e}")

    logger.info(f"\n✅ Team cache seeded: {total_cached} total teams cached")


def backfill_fixtures_for_matches(batch_size: int = 100,
                                  max_batches: int = 10,
                                  sleep_ms: int = 1200,
                                  seed_cache_flag: bool = True):
    """
    Backfill fixture_id for training_matches using TeamMatcher.
    """
    client = ApiFootballClient()
    conn = psycopg2.connect(DATABASE_URL)
    matcher = TeamMatcher(conn, client)

    # Build mapping for ALL leagues present in data window
    league_mapping = build_dynamic_mapping(conn)

    # Pre-seed team cache for better matching
    if seed_cache_flag:
        seed_team_cache(conn, matcher, league_mapping)

    stats = {
        'processed': 0,
        'matched': 0,
        'ambiguous': 0,
        'no_candidates': 0,
        'errors': 0,
        'rate_limit_429s': 0,
        'last_100_calls': []
    }

    current_sleep = sleep_ms
    current_batch_size = batch_size

    cursor = conn.cursor()

    for batch_num in range(max_batches):
        logger.info(f"\n{'='*80}")
        logger.info(f"BATCH {batch_num + 1}/{max_batches}")
        logger.info(
            f"Settings: batch_size={current_batch_size}, sleep={current_sleep}ms"
        )
        logger.info(f"{'='*80}")

        cursor.execute(
            """
            SELECT match_id, league_id, home_team, away_team, match_date
            FROM training_matches
            WHERE fixture_id IS NULL
              AND match_date IS NOT NULL
              AND match_date BETWEEN %s AND %s
            ORDER BY match_date DESC
            LIMIT %s
        """, (DATE_MIN, DATE_MAX, current_batch_size))

        matches = cursor.fetchall()
        if not matches:
            logger.info("No more matches to process in the selected window.")
            break

        logger.info(f"Processing {len(matches)} matches...")

        for match_id, league_id, home_team, away_team, match_date in matches:
            stats['processed'] += 1

            if league_id not in league_mapping:
                logger.warning(
                    f"Skipping match {match_id} in league {league_id} (not in dynamic mapping)"
                )
                time.sleep(0.05)
                continue

            league_info = league_mapping[league_id]
            api_league_id = league_info['api_football_id']
            season_logic = league_info['season_logic']
            season = get_season_from_date(match_date, season_logic)

            try:
                fixture_id, diag = matcher.match_fixture(
                    league_id=api_league_id,
                    season=season,
                    kickoff_date=match_date,
                    home_name=home_team,
                    away_name=away_team)

                call_success = True

                if fixture_id:
                    cursor.execute(
                        """
                        UPDATE training_matches
                           SET fixture_id = %s
                         WHERE match_id = %s
                    """, (fixture_id, match_id))

                    matcher.record_success(match_id, fixture_id, diag)
                    stats['matched'] += 1

                    score = diag.get('top_score')
                    score_str = f"{score:.3f}" if isinstance(
                        score, (float, int)) else "n/a"
                    logger.info(f"✅ {match_id}: {home_team} vs {away_team} "
                                f"→ fixture {fixture_id} (score={score_str})")
                else:
                    matcher.record_failure(match_id, diag)
                    status = diag.get('status', 'error')
                    msg = diag.get('message', 'no message')

                    if status == 'ambiguous_top2':
                        stats['ambiguous'] += 1
                        logger.warning(f"⚠️  {match_id}: Ambiguous - {msg}")
                    elif status == 'no_candidates':
                        stats['no_candidates'] += 1
                        logger.debug(f"❌ {match_id}: No candidates - {msg}")
                    else:
                        stats['errors'] += 1
                        logger.error(f"❌ {match_id}: Error - {msg}")

                stats['last_100_calls'].append(call_success)
                if len(stats['last_100_calls']) > 100:
                    stats['last_100_calls'].pop(0)

                time.sleep(current_sleep / 1000.0)

            except Exception as e:
                es = str(e)
                if '429' in es or 'rate limit' in es.lower():
                    stats['rate_limit_429s'] += 1
                    stats['last_100_calls'].append(False)
                    if len(stats['last_100_calls']) > 100:
                        stats['last_100_calls'].pop(0)
                    logger.warning(
                        f"⚠️  Rate limit hit on match {match_id}, backing off..."
                    )
                    time.sleep(4)
                else:
                    stats['errors'] += 1
                    logger.error(f"Error processing match {match_id}: {es}")

        conn.commit()

        # Auto-throttle
        if len(stats['last_100_calls']) >= 50:
            recent_failures = stats['last_100_calls'].count(False)
            failure_rate = recent_failures / len(stats['last_100_calls'])

            if failure_rate >= 0.05:
                current_sleep = 2500
                current_batch_size = max(50, current_batch_size // 2)
                logger.warning(
                    f"⚠️  High 429 rate ({failure_rate:.1%}) → sleep={current_sleep}ms, batch_size={current_batch_size}"
                )
            elif failure_rate >= 0.02:
                current_sleep = 1800
                logger.warning(
                    f"⚠️  Elevated 429 rate ({failure_rate:.1%}) → sleep={current_sleep}ms"
                )
            elif failure_rate == 0 and batch_num >= 1:
                current_sleep = max(1000, current_sleep - 100)
                logger.info(f"✅ Clean batch → sleep={current_sleep}ms")

        logger.info(
            f"\nBatch {batch_num + 1} complete: "
            f"{stats['matched']} matched, {stats['ambiguous']} ambiguous, "
            f"{stats['no_candidates']} no candidates, {stats['errors']} errors, "
            f"{stats['rate_limit_429s']} rate limits")

    cursor.close()
    conn.close()

    # Final statistics
    logger.info(f"\n{'='*80}")
    logger.info("BACKFILL COMPLETE")
    logger.info(f"{'='*80}")
    logger.info(f"Total processed: {stats['processed']}")
    logger.info(f"✅ Matched: {stats['matched']}")
    logger.info(f"⚠️  Ambiguous: {stats['ambiguous']}")
    logger.info(f"❌ No candidates: {stats['no_candidates']}")
    logger.info(f"⚠️  Errors: {stats['errors']}")
    logger.info(f"🚦 Rate limit hits (429s): {stats['rate_limit_429s']}")

    if stats['processed'] > 0:
        match_rate = (stats['matched'] /
                      stats['processed']) * 100 if stats['processed'] else 0.0
        logger.info(f"\n📊 Match rate: {match_rate:.1f}%")

        if stats['matched'] > 0:
            logger.info(
                f"\n✅ Next step: Run gap fill worker to fetch odds for {stats['matched']} matches"
            )

        if stats['ambiguous'] > 0:
            logger.info(
                f"\n⚠️  {stats['ambiguous']} ambiguous matches logged in fixture_map_state table"
                f"\n   Query: SELECT * FROM fixture_map_state WHERE status = 'ambiguous_top2';"
            )


if __name__ == '__main__':
    logger.info("Starting fixture ID backfill with TeamMatcher...")
    logger.info("Features: Accent normalization, team aliases, fuzzy matching")
    logger.info("Scope: ALL leagues present in training_matches (auto)")
    logger.info(f"Date range: {DATE_MIN} - {DATE_MAX}")
    logger.info("\nConservative settings:")
    logger.info("  Batch size: 100 matches")
    logger.info("  Max batches: 10 (1,000 matches per run)")
    logger.info("  Sleep: 1200ms between matches (~0.8 req/sec)")
    logger.info("  Auto-throttle: Enabled\n")

    backfill_fixtures_for_matches(batch_size=100,
                                  max_batches=10,
                                  sleep_ms=1200,
                                  seed_cache_flag=True)
