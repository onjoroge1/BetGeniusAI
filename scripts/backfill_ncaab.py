"""
NCAAB Season Backfill Script

One-time script to pull all available NCAAB game data for the current season
(November 2025 – present) using The Odds API scores endpoint.

Usage:
    python scripts/backfill_ncaab.py
    python scripts/backfill_ncaab.py --days 30      # last 30 days only
    python scripts/backfill_ncaab.py --dry-run       # check API without storing
"""

import os
import sys
import argparse
import logging
import requests
import psycopg2
from datetime import datetime, timezone

# Ensure project root is on sys.path so that `models.*` imports work
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

SPORT_KEY = "basketball_ncaab"
SPORT     = "basketball"
BASE_URL  = "https://api.the-odds-api.com/v4"

# The Odds API NCAAB scores endpoint supports daysFrom=1,2,3 only on most plans.
# Higher values return 422 Unprocessable Entity.
MAX_DAYS_BACK = 3


def fetch_scores(api_key: str, days_from: int) -> list:
    """
    Fetch completed NCAAB game scores.
    The Odds API NCAAB scores endpoint supports daysFrom=1,2,3 only.
    Larger values return 422 — the function automatically falls back to daysFrom=3.
    """
    url = f"{BASE_URL}/sports/{SPORT_KEY}/scores"
    days_from = min(days_from, MAX_DAYS_BACK)

    for attempt_days in [days_from, 3, 2, 1]:
        params = {"apiKey": api_key, "daysFrom": attempt_days}
        logger.info(f"Fetching NCAAB scores: daysFrom={attempt_days} …")
        resp = requests.get(url, params=params, timeout=30)
        remaining = resp.headers.get("x-requests-remaining", "?")
        used      = resp.headers.get("x-requests-used", "?")
        logger.info(f"  API quota → used={used}, remaining={remaining}")

        if resp.status_code == 422:
            if attempt_days > 1:
                logger.warning(f"  422 for daysFrom={attempt_days} — retrying with smaller window")
                continue
            logger.warning("  422 on daysFrom=1 — NCAAB scores unavailable on this plan")
            return []
        if resp.status_code == 404:
            logger.warning("  404 — no NCAAB data found (sport may be off-season)")
            return []
        resp.raise_for_status()
        games = resp.json()
        logger.info(f"  Received {len(games)} game records")
        return games
    return []


def fetch_upcoming_odds(api_key: str) -> list:
    """Fetch upcoming NCAAB odds (fixtures + odds snapshots)."""
    url = f"{BASE_URL}/sports/{SPORT_KEY}/odds"
    params = {
        "apiKey": api_key,
        "regions": "us",
        "markets": "h2h,spreads,totals",
        "oddsFormat": "decimal",
    }
    logger.info("Fetching upcoming NCAAB odds …")
    resp = requests.get(url, params=params, timeout=30)
    remaining = resp.headers.get("x-requests-remaining", "?")
    used      = resp.headers.get("x-requests-used", "?")
    logger.info(f"  API quota → used={used}, remaining={remaining}")

    if resp.status_code == 404:
        logger.warning("  404 — no upcoming NCAAB games")
        return []
    resp.raise_for_status()
    events = resp.json()
    logger.info(f"  Received {len(events)} upcoming game records")
    return events


def store_scores(db_url: str, games: list, dry_run: bool = False) -> dict:
    if not games:
        return {"fixtures": 0, "results": 0, "schedule": 0}

    fixtures_stored = 0
    results_stored  = 0
    schedule_stored = 0

    if dry_run:
        completed = sum(1 for g in games if g.get("completed"))
        logger.info(f"[DRY RUN] Would store {len(games)} games ({completed} completed)")
        return {"fixtures": len(games), "results": completed, "schedule": len(games)}

    conn = psycopg2.connect(db_url)
    cursor = conn.cursor()
    now = datetime.now(timezone.utc)

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

            # Parse scores
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

            # multisport_fixtures
            cursor.execute("""
                INSERT INTO multisport_fixtures (
                    sport, sport_key, event_id,
                    home_team, away_team, commence_time,
                    status, home_score, away_score, outcome,
                    updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (sport, event_id) DO UPDATE SET
                    home_score  = EXCLUDED.home_score,
                    away_score  = EXCLUDED.away_score,
                    outcome     = EXCLUDED.outcome,
                    status      = EXCLUDED.status,
                    updated_at  = NOW()
                RETURNING (xmax = 0) AS inserted
            """, (
                SPORT, SPORT_KEY, event_id,
                home_team, away_team, game_dt,
                status, home_score, away_score, result,
            ))
            row = cursor.fetchone()
            if row and row[0]:
                fixtures_stored += 1

            # multisport_schedule
            cursor.execute("""
                INSERT INTO multisport_schedule (
                    sport_key, event_id,
                    home_team, away_team, commence_time,
                    status, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (sport_key, event_id) DO UPDATE SET
                    status = EXCLUDED.status,
                    updated_at = NOW()
            """, (SPORT_KEY, event_id, home_team, away_team, game_dt, status))
            schedule_stored += 1

            # multisport_match_results (completed games only)
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
                """, (
                    SPORT_KEY, event_id, game_dt,
                    home_team, away_team,
                    home_score, away_score, result,
                    status,
                ))
                results_stored += 1

        except Exception as e:
            logger.warning(f"  Error storing game {game.get('id')}: {e}")
            continue

    conn.commit()
    cursor.close()
    conn.close()

    return {"fixtures": fixtures_stored, "results": results_stored, "schedule": schedule_stored}


def store_odds(db_url: str, events: list, dry_run: bool = False) -> int:
    """Store upcoming game odds snapshots."""
    if not events:
        return 0

    if dry_run:
        logger.info(f"[DRY RUN] Would store odds for {len(events)} upcoming NCAAB games")
        return 0

    conn = psycopg2.connect(db_url)
    cursor = conn.cursor()
    now = datetime.now(timezone.utc)
    stored = 0

    for event in events:
        event_id   = event.get("id")
        home_team  = event.get("home_team")
        away_team  = event.get("away_team")
        commence   = event.get("commence_time")

        try:
            commence_dt = datetime.fromisoformat(commence.replace("Z", "+00:00"))
        except Exception:
            commence_dt = None

        # Store fixtures (upcoming)
        if all([event_id, home_team, away_team, commence_dt]):
            cursor.execute("""
                INSERT INTO multisport_fixtures (
                    sport, sport_key, event_id,
                    home_team, away_team, commence_time,
                    status, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, 'scheduled', NOW())
                ON CONFLICT (sport, event_id) DO UPDATE SET
                    home_team    = EXCLUDED.home_team,
                    away_team    = EXCLUDED.away_team,
                    commence_time = EXCLUDED.commence_time,
                    updated_at   = NOW()
            """, (SPORT, SPORT_KEY, event_id, home_team, away_team, commence_dt))

        # Store odds per bookmaker + consensus
        bookmakers = event.get("bookmakers", [])
        home_probs, away_probs, spreads, totals = [], [], [], []

        for bm in bookmakers:
            bm_key = bm.get("key")
            h_odds = a_odds = None
            spread = s_h_odds = s_a_odds = None
            total  = o_odds = u_odds = None

            for market in bm.get("markets", []):
                mk = market.get("key")
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
                overround = hp + ap
                hp_norm = hp / overround
                ap_norm = ap / overround
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
                            home_odds, away_odds,
                            home_prob, away_prob,
                            home_spread, home_spread_odds, away_spread_odds,
                            total_line, over_odds, under_odds,
                            overround, n_bookmakers,
                            bookmaker, is_consensus, ts_recorded
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s
                        ) ON CONFLICT (event_id, bookmaker, ts_recorded) DO NOTHING
                    """, (
                        SPORT, SPORT_KEY, event_id,
                        home_team, away_team, commence_dt,
                        h_odds, a_odds,
                        hp_norm, ap_norm,
                        spread, s_h_odds, s_a_odds,
                        total, o_odds, u_odds,
                        round(overround, 4), 1,
                        bm_key, False, now,
                    ))
                    stored += 1
                except Exception:
                    pass

        # Consensus row
        if home_probs and away_probs:
            avg_hp = sum(home_probs) / len(home_probs)
            avg_ap = sum(away_probs) / len(away_probs)
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
                        %s, %s, %s, %s, %s, %s,
                        %s, %s,
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s
                    ) ON CONFLICT (event_id, bookmaker, ts_recorded) DO NOTHING
                """, (
                    SPORT, SPORT_KEY, event_id,
                    home_team, away_team, commence_dt,
                    round(avg_hp, 4), round(avg_ap, 4),
                    cons_spread[0], cons_spread[1], cons_spread[2],
                    cons_total[0], cons_total[1], cons_total[2],
                    round(avg_hp + avg_ap, 4), len(bookmakers),
                    "consensus", True, now,
                ))
                stored += 1
            except Exception:
                pass

    conn.commit()
    cursor.close()
    conn.close()
    return stored


def print_summary(db_url: str):
    conn = psycopg2.connect(db_url)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT COUNT(*) FROM multisport_fixtures WHERE sport_key = 'basketball_ncaab'
    """)
    total_fixtures = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*) FROM multisport_fixtures
        WHERE sport_key = 'basketball_ncaab' AND outcome IS NOT NULL
    """)
    completed = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*) FROM multisport_odds_snapshots WHERE sport_key = 'basketball_ncaab'
    """)
    total_odds = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(DISTINCT bookmaker)
        FROM multisport_odds_snapshots WHERE sport_key = 'basketball_ncaab'
    """)
    bookmakers = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*) FROM multisport_training WHERE sport_key = 'basketball_ncaab'
    """)
    training = cursor.fetchone()[0]

    cursor.close()
    conn.close()

    logger.info("=" * 60)
    logger.info("  NCAAB Data Collection Summary")
    logger.info("=" * 60)
    logger.info(f"  Fixtures total      : {total_fixtures}")
    logger.info(f"  Completed with result: {completed}")
    logger.info(f"  Odds snapshots      : {total_odds}")
    logger.info(f"  Unique bookmakers   : {bookmakers}")
    logger.info(f"  Training rows       : {training}")
    logger.info("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Backfill NCAAB data from The Odds API")
    parser.add_argument("--days", type=int, default=MAX_DAYS_BACK,
                        help=f"Days back to fetch (max {MAX_DAYS_BACK})")
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

    days = min(max(args.days, 1), MAX_DAYS_BACK)
    logger.info(f"Starting NCAAB backfill — daysFrom={days}, dry_run={args.dry_run}")

    # Step 1: Pull completed game scores
    games = fetch_scores(api_key, days)
    score_counts = store_scores(db_url, games, dry_run=args.dry_run)
    logger.info(
        f"Scores stored → fixtures={score_counts['fixtures']}, "
        f"results={score_counts['results']}, schedule={score_counts['schedule']}"
    )

    # Step 2: Pull upcoming games + odds
    events = fetch_upcoming_odds(api_key)
    odds_stored = store_odds(db_url, events, dry_run=args.dry_run)
    logger.info(f"Odds snapshots stored: {odds_stored}")

    # Step 3: Training sync for completed rows
    if not args.dry_run and (score_counts["results"] > 0 or events):
        try:
            from models.multisport_data_collector import MultiSportDataCollector
            collector = MultiSportDataCollector()
            sync_result = collector.sync_to_training_table("basketball_ncaab")
            logger.info(f"Training sync: {sync_result}")
        except Exception as e:
            logger.warning(f"Training sync failed (will retry on next collection run): {e}")

    if not args.dry_run:
        print_summary(db_url)

    logger.info("NCAAB backfill complete.")


if __name__ == "__main__":
    main()
