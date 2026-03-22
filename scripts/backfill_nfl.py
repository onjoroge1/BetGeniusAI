"""
NFL Season Backfill Script

Pulls all available NFL game data using The Odds API scores endpoint.

The Odds API /scores endpoint accepts a `daysFrom` parameter.  The maximum
supported value depends on your plan.  This script tries the largest window
first and steps down until it finds a window the API accepts.

Progressive fallback strategy (requested -> accepted):
    90 days -> 60 -> 30 -> 14 -> 7 -> 3 -> 2 -> 1

Usage:
    python scripts/backfill_nfl.py
    python scripts/backfill_nfl.py --days 90    # attempt full season
    python scripts/backfill_nfl.py --dry-run    # check API without writing
"""

import os
import sys
import argparse
import logging
import requests
import psycopg2
from datetime import datetime, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

SPORT_KEY = "americanfootball_nfl"
SPORT     = "american-football"
BASE_URL  = "https://api.the-odds-api.com/v4"

# NFL 2025-26 season start (first Thursday of September)
SEASON_START = datetime(2025, 9, 4, tzinfo=timezone.utc)

WINDOW_FALLBACKS = [90, 60, 30, 14, 7, 3, 2, 1]


def fetch_scores(api_key: str, requested_days: int) -> tuple[list, int]:
    """
    Fetch completed NFL game scores.

    Attempts `requested_days` first; if the API returns 422 (quota/plan
    restriction), steps down through WINDOW_FALLBACKS until a window
    succeeds or all fail.

    Returns (games_list, actual_days_used).
    """
    url = f"{BASE_URL}/sports/{SPORT_KEY}/scores"

    candidates = [d for d in WINDOW_FALLBACKS if d <= requested_days]
    if requested_days not in candidates:
        candidates = [requested_days] + candidates
    candidates = sorted(set(candidates), reverse=True)

    for attempt_days in candidates:
        params = {"apiKey": api_key, "daysFrom": attempt_days}
        logger.info(f"Fetching NFL scores: daysFrom={attempt_days} ...")
        try:
            resp = requests.get(url, params=params, timeout=30)
        except requests.RequestException as exc:
            logger.warning(f"  Network error: {exc} -- skipping window {attempt_days}")
            continue

        remaining = resp.headers.get("x-requests-remaining", "?")
        used      = resp.headers.get("x-requests-used", "?")
        logger.info(f"  API quota -> used={used}, remaining={remaining}")

        if resp.status_code == 422:
            logger.warning(
                f"  422 Unprocessable Entity for daysFrom={attempt_days} "
                f"(plan limit exceeded) -- trying smaller window"
            )
            continue
        if resp.status_code == 404:
            logger.warning("  404 -- no NFL data (sport may be off-season)")
            return [], 0
        if resp.status_code == 401:
            logger.error("  401 Unauthorized -- check ODDS_API_KEY")
            return [], 0
        resp.raise_for_status()
        games = resp.json()
        logger.info(
            f"  Received {len(games)} game records with daysFrom={attempt_days}"
        )
        return games, attempt_days

    logger.error(
        "  All window sizes failed -- NFL scores endpoint unavailable on this plan. "
        "Upgrade your Odds API subscription to access historical game data."
    )
    return [], 0


def log_coverage_gap(db_url: str, actual_days: int):
    """
    Report the oldest NFL game_date in multisport_match_results and whether
    the current season start is covered.
    """
    if not db_url:
        return
    try:
        conn = psycopg2.connect(db_url)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT MIN(game_date), MAX(game_date), COUNT(*)
            FROM multisport_match_results
            WHERE sport_key = %s
        """, (SPORT_KEY,))
        row = cursor.fetchone()
        cursor.close()
        conn.close()

        min_date, max_date, total = row
        if total == 0:
            logger.warning(
                "  Coverage check: 0 completed NFL results in DB. "
                "No historical coverage achieved with this API plan."
            )
            return

        logger.info(f"  Coverage check: {total} completed games in DB")
        logger.info(f"  Earliest game : {min_date}")
        logger.info(f"  Latest game   : {max_date}")

        if min_date and min_date.tzinfo is None:
            min_date = min_date.replace(tzinfo=timezone.utc)

        if min_date and min_date > SEASON_START:
            gap_days = (min_date - SEASON_START).days
            logger.warning(
                f"  COVERAGE GAP: Season starts {SEASON_START.date()} but "
                f"earliest result is {min_date.date()} -- {gap_days} days uncovered. "
                f"The Odds API accepted daysFrom={actual_days}. "
                f"To fill the gap, upgrade your API plan to allow larger daysFrom values."
            )
        else:
            logger.info(f"  Full season coverage achieved from {SEASON_START.date()} onwards.")
    except Exception as exc:
        logger.warning(f"  Coverage check failed: {exc}")


def fetch_upcoming_odds(api_key: str) -> list:
    """Fetch upcoming NFL odds (fixtures + odds snapshots)."""
    url = f"{BASE_URL}/sports/{SPORT_KEY}/odds"
    params = {
        "apiKey": api_key,
        "regions": "us",
        "markets": "h2h,spreads,totals",
        "oddsFormat": "decimal",
    }
    logger.info("Fetching upcoming NFL odds ...")
    try:
        resp = requests.get(url, params=params, timeout=30)
    except requests.RequestException as exc:
        logger.warning(f"  Network error fetching odds: {exc}")
        return []

    remaining = resp.headers.get("x-requests-remaining", "?")
    used      = resp.headers.get("x-requests-used", "?")
    logger.info(f"  API quota -> used={used}, remaining={remaining}")

    if resp.status_code == 404:
        logger.warning("  404 -- no upcoming NFL games (off-season)")
        return []
    resp.raise_for_status()
    events = resp.json()
    logger.info(f"  Received {len(events)} upcoming game records")
    return events


def store_scores(db_url: str, games: list, dry_run: bool = False) -> dict:
    if not games:
        return {"fixtures": 0, "results": 0, "schedule": 0}

    if dry_run:
        completed = sum(1 for g in games if g.get("completed"))
        logger.info(f"[DRY RUN] Would store {len(games)} games ({completed} completed)")
        return {"fixtures": len(games), "results": completed, "schedule": len(games)}

    conn = psycopg2.connect(db_url)
    cursor = conn.cursor()
    now = datetime.now(timezone.utc)
    fixtures_stored = results_stored = schedule_stored = 0

    for game in games:
        try:
            event_id   = game.get("id")
            home_team  = game.get("home_team")
            away_team  = game.get("away_team")
            commence   = game.get("commence_time")
            completed  = game.get("completed", False)

            if not all([event_id, home_team, away_team, commence]):
                continue

            try:
                game_dt = datetime.fromisoformat(commence.replace("Z", "+00:00"))
            except Exception:
                game_dt = now

            home_score = away_score = None
            for entry in game.get("scores") or []:
                if entry.get("name") == home_team:
                    try:
                        home_score = int(entry["score"])
                    except (TypeError, ValueError):
                        pass
                elif entry.get("name") == away_team:
                    try:
                        away_score = int(entry["score"])
                    except (TypeError, ValueError):
                        pass

            result = None
            if completed and home_score is not None and away_score is not None:
                result = "H" if home_score > away_score else "A"
            status = "final" if completed else ("in_progress" if game.get("scores") else "scheduled")

            cursor.execute("""
                INSERT INTO multisport_fixtures (
                    sport, sport_key, event_id,
                    home_team, away_team, commence_time,
                    status, home_score, away_score, outcome, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (sport, event_id) DO UPDATE SET
                    home_score  = EXCLUDED.home_score,
                    away_score  = EXCLUDED.away_score,
                    outcome     = EXCLUDED.outcome,
                    status      = EXCLUDED.status,
                    updated_at  = NOW()
                RETURNING (xmax = 0) AS inserted
            """, (SPORT, SPORT_KEY, event_id, home_team, away_team, game_dt,
                  status, home_score, away_score, result))
            row = cursor.fetchone()
            if row and row[0]:
                fixtures_stored += 1

            cursor.execute("""
                INSERT INTO multisport_schedule (
                    sport_key, event_id, home_team, away_team,
                    commence_time, status, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (sport_key, event_id) DO UPDATE SET
                    status = EXCLUDED.status, updated_at = NOW()
            """, (SPORT_KEY, event_id, home_team, away_team, game_dt, status))
            schedule_stored += 1

            if completed and home_score is not None:
                cursor.execute("""
                    INSERT INTO multisport_match_results (
                        sport_key, event_id, game_date,
                        home_team, away_team,
                        home_score, away_score, result,
                        status, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (sport_key, event_id) DO UPDATE SET
                        home_score = EXCLUDED.home_score,
                        away_score = EXCLUDED.away_score,
                        result     = EXCLUDED.result,
                        status     = EXCLUDED.status,
                        updated_at = NOW()
                """, (SPORT_KEY, event_id, game_dt, home_team, away_team,
                      home_score, away_score, result, status))
                results_stored += 1

        except Exception as exc:
            logger.warning(f"  Error storing game {game.get('id')}: {exc}")
            continue

    conn.commit()
    cursor.close()
    conn.close()
    return {"fixtures": fixtures_stored, "results": results_stored, "schedule": schedule_stored}


def store_odds(db_url: str, events: list, dry_run: bool = False) -> int:
    if not events:
        return 0
    if dry_run:
        logger.info(f"[DRY RUN] Would store odds for {len(events)} upcoming NFL games")
        return 0

    conn = psycopg2.connect(db_url)
    cursor = conn.cursor()
    now = datetime.now(timezone.utc)
    stored = 0

    for event in events:
        event_id    = event.get("id")
        home_team   = event.get("home_team")
        away_team   = event.get("away_team")
        commence    = event.get("commence_time")

        try:
            commence_dt = datetime.fromisoformat(commence.replace("Z", "+00:00"))
        except Exception:
            commence_dt = None

        if all([event_id, home_team, away_team, commence_dt]):
            cursor.execute("""
                INSERT INTO multisport_fixtures (
                    sport, sport_key, event_id,
                    home_team, away_team, commence_time,
                    status, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, 'scheduled', NOW())
                ON CONFLICT (sport, event_id) DO UPDATE SET
                    home_team     = EXCLUDED.home_team,
                    away_team     = EXCLUDED.away_team,
                    commence_time = EXCLUDED.commence_time,
                    updated_at    = NOW()
            """, (SPORT, SPORT_KEY, event_id, home_team, away_team, commence_dt))

        bookmakers = event.get("bookmakers", [])
        home_probs, away_probs, spreads, totals = [], [], [], []

        for bm in bookmakers:
            bm_key = bm.get("key")
            h_odds = a_odds = None
            spread = s_h_odds = s_a_odds = None
            total  = o_odds = u_odds = None

            for market in bm.get("markets", []):
                mk       = market.get("key")
                outcomes = {o["name"]: o for o in market.get("outcomes", [])}
                if mk == "h2h":
                    if home_team in outcomes and away_team in outcomes:
                        h_odds = outcomes[home_team]["price"]
                        a_odds = outcomes[away_team]["price"]
                elif mk == "spreads":
                    if home_team in outcomes:
                        spread   = outcomes[home_team].get("point")
                        s_h_odds = outcomes[home_team]["price"]
                        s_a_odds = outcomes[away_team]["price"] if away_team in outcomes else None
                elif mk == "totals":
                    if "Over" in outcomes:
                        total  = outcomes["Over"].get("point")
                        o_odds = outcomes["Over"]["price"]
                        u_odds = outcomes["Under"]["price"] if "Under" in outcomes else None

            if h_odds and a_odds:
                hp = 1 / h_odds
                ap = 1 / a_odds
                overround  = hp + ap
                hp_norm    = hp / overround
                ap_norm    = ap / overround
                home_probs.append(hp_norm)
                away_probs.append(ap_norm)
                if spread is not None:
                    spreads.append((spread, s_h_odds, s_a_odds))
                if total is not None:
                    totals.append((total, o_odds, u_odds))

                try:
                    cursor.execute("""
                        INSERT INTO multisport_odds_snapshots (
                            sport, sport_key, event_id,
                            home_team, away_team, commence_time,
                            home_odds, away_odds, home_prob, away_prob,
                            home_spread, home_spread_odds, away_spread_odds,
                            total_line, over_odds, under_odds,
                            overround, n_bookmakers,
                            bookmaker, is_consensus, ts_recorded
                        ) VALUES (
                            %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                            %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
                        ) ON CONFLICT (event_id, bookmaker, ts_recorded) DO NOTHING
                    """, (
                        SPORT, SPORT_KEY, event_id, home_team, away_team, commence_dt,
                        h_odds, a_odds, hp_norm, ap_norm,
                        spread, s_h_odds, s_a_odds,
                        total, o_odds, u_odds,
                        round(overround, 4), 1,
                        bm_key, False, now,
                    ))
                    stored += 1
                except Exception as exc:
                    logger.debug(
                        f"  Odds insert failed event={event_id} bm={bm_key}: {exc}"
                    )

        if home_probs and away_probs:
            avg_hp      = sum(home_probs) / len(home_probs)
            avg_ap      = sum(away_probs) / len(away_probs)
            cons_spread = spreads[-1] if spreads else (None, None, None)
            cons_total  = totals[-1]  if totals  else (None, None, None)
            try:
                cursor.execute("""
                    INSERT INTO multisport_odds_snapshots (
                        sport, sport_key, event_id,
                        home_team, away_team, commence_time,
                        home_prob, away_prob,
                        home_spread, home_spread_odds, away_spread_odds,
                        total_line, over_odds, under_odds,
                        overround, n_bookmakers,
                        bookmaker, is_consensus, ts_recorded
                    ) VALUES (
                        %s,%s,%s,%s,%s,%s,%s,%s,
                        %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
                    ) ON CONFLICT (event_id, bookmaker, ts_recorded) DO NOTHING
                """, (
                    SPORT, SPORT_KEY, event_id, home_team, away_team, commence_dt,
                    round(avg_hp, 4), round(avg_ap, 4),
                    cons_spread[0], cons_spread[1], cons_spread[2],
                    cons_total[0], cons_total[1], cons_total[2],
                    round(avg_hp + avg_ap, 4), len(bookmakers),
                    "consensus", True, now,
                ))
                stored += 1
            except Exception as exc:
                logger.debug(
                    f"  Consensus odds insert failed event={event_id}: {exc}"
                )

    conn.commit()
    cursor.close()
    conn.close()
    return stored


def print_summary(db_url: str):
    conn = psycopg2.connect(db_url)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM multisport_fixtures WHERE sport_key = %s", (SPORT_KEY,))
    total_fixtures = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*) FROM multisport_fixtures
        WHERE sport_key = %s AND outcome IS NOT NULL
    """, (SPORT_KEY,))
    completed = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM multisport_odds_snapshots WHERE sport_key = %s", (SPORT_KEY,))
    total_odds = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(DISTINCT bookmaker)
        FROM multisport_odds_snapshots WHERE sport_key = %s
    """, (SPORT_KEY,))
    bookmakers = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM multisport_training WHERE sport_key = %s", (SPORT_KEY,))
    training = cursor.fetchone()[0]

    cursor.close()
    conn.close()

    logger.info("=" * 60)
    logger.info("  NFL Data Collection Summary")
    logger.info("=" * 60)
    logger.info(f"  Fixtures total       : {total_fixtures}")
    logger.info(f"  Completed with result: {completed}")
    logger.info(f"  Odds snapshots       : {total_odds}")
    logger.info(f"  Unique bookmakers    : {bookmakers}")
    logger.info(f"  Training rows        : {training}")
    logger.info("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Backfill NFL data from The Odds API")
    parser.add_argument(
        "--days", type=int, default=90,
        help=(
            "Desired days back to fetch (default: 90 for full-season attempt). "
            "The script steps down automatically if the API rejects larger windows."
        )
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch from API but do not write to database")
    args = parser.parse_args()

    api_key = os.getenv("ODDS_API_KEY")
    db_url  = os.getenv("DATABASE_URL")

    if not api_key:
        logger.error("ODDS_API_KEY not set")
        sys.exit(1)
    if not db_url and not args.dry_run:
        logger.error("DATABASE_URL not set")
        sys.exit(1)

    logger.info(
        f"Starting NFL backfill -- requested daysFrom={args.days}, "
        f"dry_run={args.dry_run}"
    )
    logger.info(
        "Progressive fallback strategy: will step down window if API rejects "
        "the requested size (90->60->30->14->7->3->2->1)."
    )

    games, actual_days = fetch_scores(api_key, args.days)
    score_counts = store_scores(db_url, games, dry_run=args.dry_run)
    logger.info(
        f"Scores stored -> fixtures={score_counts['fixtures']}, "
        f"results={score_counts['results']}, schedule={score_counts['schedule']}"
    )

    events = fetch_upcoming_odds(api_key)
    odds_stored = store_odds(db_url, events, dry_run=args.dry_run)
    logger.info(f"Odds snapshots stored: {odds_stored}")

    if not args.dry_run and (score_counts["results"] > 0 or events):
        try:
            from models.multisport_data_collector import MultiSportDataCollector
            collector = MultiSportDataCollector()
            sync_result = collector.sync_to_training_table("americanfootball_nfl")
            logger.info(f"Training sync: {sync_result}")
        except Exception as exc:
            logger.warning(f"Training sync failed (will retry on next run): {exc}")

    if not args.dry_run:
        log_coverage_gap(db_url, actual_days)
        print_summary(db_url)

    if actual_days > 0 and actual_days < args.days:
        logger.warning(
            f"NOTE: Requested {args.days} days but API only accepted {actual_days} days. "
            f"Historical data before {actual_days} days ago is not available on this "
            f"Odds API plan. Upgrade to a higher-tier plan to access the full season history. "
            f"Ongoing daily collection will accumulate the season dataset from today forward."
        )

    logger.info("NFL backfill complete.")


if __name__ == "__main__":
    main()
