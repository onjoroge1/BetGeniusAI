"""
WC 2026 Track 1 Setup — Data Collection Foundation
====================================================
Run this ONCE on Replit to bootstrap all World Cup data collection.

Steps performed:
  1. Run DB migration  — create international_matches + 5 supporting tables
  2. Verify league_map — ensure WC / qualifier sport keys are present for odds collection
  3. Historical backfill — WC 2002-2022, Euro, Copa America, AFCON, WC qualifiers
  4. Squad collection   — WC 2026 squad lists for all 32 nations
  5. Stats summary      — print row counts so you can verify success

Usage:
    python scripts/wc2026_track1_setup.py [--skip-backfill] [--skip-squads] [--dry-run]

Flags:
    --skip-backfill   Skip the 1-2h historical backfill (use if already done)
    --skip-squads     Skip squad collection (run separately if squad API not ready)
    --dry-run         Print what would run without making any DB or API calls

Expected runtime:
    Full run  : ~1.5–2.5 hours  (API-Football rate limits pace the backfill)
    No backfill: ~5 minutes

Exit codes:
    0 = success
    1 = fatal error (migration failed or no API key)
"""

import os
import sys
import json
import time
import argparse
import logging
from pathlib import Path
from datetime import datetime, timezone

# ── Bootstrap ─────────────────────────────────────────────────────────────────

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))
os.chdir(REPO)

for env_file in [".env.local", ".env"]:
    p = REPO / env_file
    if not p.exists():
        continue
    for line in p.read_text().splitlines():
        m = __import__("re").match(r"^([^#=\s][^=]*)=(.*)$", line)
        if m:
            k, v = m.group(1).strip(), m.group(2).strip()
            if not os.environ.get(k):
                os.environ[k] = v
    break

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Args ───────────────────────────────────────────────────────────────────────

parser = argparse.ArgumentParser(description="WC 2026 Track 1 Setup")
parser.add_argument("--skip-backfill", action="store_true",
                    help="Skip historical match backfill (1-2h)")
parser.add_argument("--skip-squads",   action="store_true",
                    help="Skip WC 2026 squad collection")
parser.add_argument("--dry-run",       action="store_true",
                    help="Print plan without executing")
args = parser.parse_args()

# ── Env checks ────────────────────────────────────────────────────────────────

DATABASE_URL  = os.environ.get("DATABASE_URL")
RAPIDAPI_KEY  = os.environ.get("RAPIDAPI_KEY")

if not DATABASE_URL:
    logger.error("DATABASE_URL not set — cannot continue")
    sys.exit(1)

if not RAPIDAPI_KEY:
    logger.error("RAPIDAPI_KEY not set — cannot call API-Football")
    sys.exit(1)

if args.dry_run:
    logger.info("DRY RUN — no DB writes or API calls will be made")
    logger.info("")
    logger.info("Steps that WOULD run:")
    logger.info("  1. Run DB migration  (migrations/world_cup_2026_tables.sql)")
    logger.info("  2. Verify league_map for WC leagues (9 rows)")
    if not args.skip_backfill:
        logger.info("  3. Historical backfill — WC 2002-2022, Euro, Copa, AFCON, Qualifiers (~1-2h)")
    else:
        logger.info("  3. [SKIPPED] Historical backfill")
    if not args.skip_squads:
        logger.info("  4. Collect WC 2026 squads for all 32 nations")
    else:
        logger.info("  4. [SKIPPED] Squad collection")
    logger.info("  5. Print stats summary")
    sys.exit(0)

# ── Helpers ────────────────────────────────────────────────────────────────────

def section(title: str):
    logger.info("")
    logger.info(f"{'═' * 60}")
    logger.info(f"  {title}")
    logger.info(f"{'═' * 60}")


def run_migration() -> bool:
    """Create international tables if they don't exist."""
    import psycopg2
    sql_path = REPO / "migrations" / "world_cup_2026_tables.sql"
    if not sql_path.exists():
        logger.error(f"Migration file not found: {sql_path}")
        return False

    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur  = conn.cursor()
        cur.execute(sql_path.read_text())
        conn.commit()
        cur.close()
        conn.close()
        logger.info("✅ Migration complete — international tables ready")
        return True
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        return False


def print_stats(collector):
    """Print current row counts for all international tables."""
    import psycopg2
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur  = conn.cursor()

        tables = [
            "international_matches",
            "national_team_squads",
            "player_international_stats",
            "national_team_elo",
            "tournament_features",
            "penalty_shootout_history",
        ]
        logger.info("")
        logger.info("  📊 Table row counts:")
        for t in tables:
            try:
                cur.execute(f"SELECT COUNT(*) FROM {t}")
                count = cur.fetchone()[0]
                logger.info(f"     {t:<35} {count:>8,} rows")
            except Exception:
                logger.info(f"     {t:<35}  (table not found)")

        # Per-tournament breakdown
        cur.execute("""
            SELECT tournament_name, COUNT(*) as n, MIN(match_date::text), MAX(match_date::text)
            FROM international_matches
            GROUP BY tournament_name ORDER BY n DESC
        """)
        rows = cur.fetchall()
        if rows:
            logger.info("")
            logger.info("  📊 Matches by tournament:")
            for row in rows:
                logger.info(f"     {row[0]:<40} {row[1]:>6,} matches  ({row[2][:4]}–{row[3][:4]})")

        cur.close()
        conn.close()
    except Exception as e:
        logger.warning(f"Stats query failed: {e}")


# ── Main ───────────────────────────────────────────────────────────────────────

t0 = time.time()

# ── Step 1: Migration ─────────────────────────────────────────────────────────
section("Step 1/4 — DB Migration")
if not run_migration():
    sys.exit(1)

# ── Step 2: league_map ────────────────────────────────────────────────────────
section("Step 2/4 — Verify league_map for WC leagues")
try:
    from models.international_match_collector import InternationalMatchCollector
    collector = InternationalMatchCollector()
    lm_result = collector.verify_league_map()
    logger.info(f"  league_map: {lm_result['upserted']} rows upserted — WC odds collection active")
except Exception as e:
    logger.error(f"league_map verification failed: {e}")
    sys.exit(1)

# ── Step 3: Historical backfill ───────────────────────────────────────────────
if args.skip_backfill:
    section("Step 3/4 — Historical Backfill [SKIPPED]")
    logger.info("  Pass --skip-backfill was set — skipping. Run without flag to execute.")
else:
    section("Step 3/4 — Historical Backfill (WC 2002-2022 + Euro + Copa + AFCON + Qualifiers)")
    logger.info("  Expected runtime: 1–2 hours. Progress logged below.")
    logger.info("")
    try:
        bf_result = collector.run_full_backfill()
        logger.info(f"  ✅ Backfill complete")
        logger.info(f"     API calls     : {bf_result['api_calls']:,}")
        logger.info(f"     Matches found : {bf_result['matches_collected']:,}")
        logger.info(f"     Rows inserted : {bf_result['matches_inserted']:,}")
        logger.info(f"     Errors        : {bf_result['errors']}")
        logger.info(f"     Duration      : {bf_result['duration_seconds']:.0f}s")
    except Exception as e:
        logger.error(f"Backfill failed: {e}")
        # Non-fatal — squad collection can still run

# ── Step 4: Squad collection ──────────────────────────────────────────────────
if args.skip_squads:
    section("Step 4/4 — WC 2026 Squad Collection [SKIPPED]")
    logger.info("  Pass --skip-squads was set — skipping.")
else:
    section("Step 4/4 — WC 2026 Squad Collection (32 nations)")
    try:
        squad_result = collector.collect_wc2026_squads()
        if squad_result.get("teams_processed", 0) == 0:
            logger.warning(
                "  ⚠️  No squads returned. WC 2026 squads may not be published yet "
                "on API-Football — re-run this step closer to June 11."
            )
        else:
            logger.info(f"  ✅ Squads collected: {squad_result['teams_processed']} teams, "
                        f"{squad_result['players_inserted']} players")
    except Exception as e:
        logger.error(f"Squad collection failed: {e}")

# ── Step 5: Summary ───────────────────────────────────────────────────────────
section("Summary")
print_stats(collector)
elapsed = time.time() - t0
logger.info("")
logger.info(f"  Total time: {elapsed:.0f}s ({elapsed/60:.1f} min)")
logger.info("")
logger.info("  ✅ Track 1 complete. Next steps:")
logger.info("     1. Verify squad rows above > 0  (re-run --skip-backfill if squads still empty)")
logger.info("     2. Check Replit logs at next 04:00 UTC for 'intl_qualifiers' task success")
logger.info("     3. Check odds collection logs for 'soccer_fifa_world_cup' entries")
logger.info("     4. Proceed to Track 2: WC prediction model integration")

# ── Write manifest ────────────────────────────────────────────────────────────
manifest = {
    "track1_run_at": datetime.now(timezone.utc).isoformat(),
    "skip_backfill": args.skip_backfill,
    "skip_squads": args.skip_squads,
    "elapsed_seconds": round(elapsed),
}
manifest_path = REPO / "scripts" / "wc2026_track1_manifest.json"
manifest_path.write_text(json.dumps(manifest, indent=2))
logger.info(f"     Manifest saved: {manifest_path}")
