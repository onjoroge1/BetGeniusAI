#!/usr/bin/env python3 -u
"""
Archive cold tables from Neon Postgres to Supabase REST API.

Archives rows older than the configured retention_days for each table.
Schema is discovered dynamically via information_schema — no hardcoded column lists.

Usage:
    python scripts/archive_cold_tables.py [--table <name>] [--dry-run] [--batch 2000]

Requirements:
    pip install requests psycopg2-binary

Environment (read from .env.local or .env):
    DATABASE_URL     — Neon Postgres connection string
    SUPABASE_URL     — e.g. https://muynbzaqwbinloxdumxg.supabase.co
    SUPABASE_KEY     — publishable / service-role key

Exit codes:
    0 = all tables succeeded (archived and verified)
    1 = one or more tables failed verification
"""

import os
import sys
import json
import time
import argparse
import warnings
from datetime import datetime, timezone, timedelta
from pathlib import Path

warnings.filterwarnings("ignore")

# ── Bootstrap ─────────────────────────────────────────────────────────────────

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))
os.chdir(REPO)

for name in [".env.local", ".env"]:
    p = REPO / name
    if not p.exists():
        continue
    for line in p.read_text().splitlines():
        m = __import__("re").match(r"^([^#=\s][^=]*)=(.*)$", line)
        if m:
            k, v = m.group(1).strip(), m.group(2).strip()
            if not os.environ.get(k):
                os.environ[k] = v
    break

try:
    import requests
except ImportError:
    print("ERROR: 'requests' not installed.  Run: pip install requests")
    sys.exit(1)

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    print("ERROR: 'psycopg2' not installed.  Run: pip install psycopg2-binary")
    sys.exit(1)

# ── Table definitions ─────────────────────────────────────────────────────────

COLD_TABLES = [
    {
        "table": "multisport_odds_snapshots",
        "ts_col": "ts_recorded",
        "retention_days": 30,
        "archive_table": "multisport_odds_snapshots_archive",
    },
    {
        "table": "odds_snapshots",
        "ts_col": "ts_snapshot",
        "retention_days": 90,
        "archive_table": "odds_snapshots_archive",
    },
    {
        "table": "player_prop_odds",
        "ts_col": "collected_at",
        "retention_days": 30,
        "archive_table": "player_prop_odds_archive",
    },
    {
        "table": "live_ai_analysis",
        "ts_col": "generated_at",
        "retention_days": 7,
        "archive_table": "live_ai_analysis_archive",
    },
    {
        "table": "player_game_stats",
        "ts_col": "game_date",
        "retention_days": 90,
        "archive_table": "player_game_stats_archive",
    },
    {
        "table": "clv_alerts_history",
        "ts_col": "created_at",
        "retention_days": 90,
        "archive_table": "clv_alerts_history_archive",
    },
]

COLD_TABLE_NAMES = {t["table"] for t in COLD_TABLES}

# ── Args ──────────────────────────────────────────────────────────────────────

parser = argparse.ArgumentParser(
    description="Archive cold Neon tables to Supabase."
)
parser.add_argument(
    "--table", metavar="NAME",
    help="Archive only this table (default: all tables)",
)
parser.add_argument(
    "--batch", type=int, default=2000,
    help="Rows per Supabase REST batch (default: 2000)",
)
parser.add_argument(
    "--dry-run", action="store_true",
    help="Count rows and estimate without writing to Supabase",
)
args = parser.parse_args()

if args.table and args.table not in COLD_TABLE_NAMES:
    print(f"ERROR: Unknown table '{args.table}'. Valid tables:")
    for t in COLD_TABLES:
        print(f"  {t['table']}")
    sys.exit(1)

tables_to_run = (
    [t for t in COLD_TABLES if t["table"] == args.table]
    if args.table
    else COLD_TABLES
)

# ── Config ────────────────────────────────────────────────────────────────────

DATABASE_URL = os.environ.get("DATABASE_URL")
SUPABASE_URL = os.environ.get("SUPABASE_URL") or os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
SUPABASE_KEY = (
    os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    or os.environ.get("SUPABASE_KEY")
    or os.environ.get("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY")
)

if not DATABASE_URL:
    print("ERROR: DATABASE_URL not set")
    sys.exit(1)
if not SUPABASE_URL:
    print("ERROR: SUPABASE_URL / NEXT_PUBLIC_SUPABASE_URL not set")
    sys.exit(1)
if not SUPABASE_KEY:
    print("ERROR: SUPABASE_SERVICE_ROLE_KEY / SUPABASE_KEY not set")
    sys.exit(1)

SUPABASE_REST = SUPABASE_URL.rstrip("/") + "/rest/v1"
HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=minimal",
}

# Build a requests Session with automatic retry + SSL tolerance
# (Python 3.14 SSL changes can cause SSLV3_ALERT_BAD_RECORD_MAC on large payloads)
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

_session = requests.Session()
_retry = Retry(
    total=5,
    backoff_factor=1.5,       # 0s, 1.5s, 3s, 6s, 12s
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["POST", "GET"],
    raise_on_status=False,
)
_session.mount("https://", HTTPAdapter(max_retries=_retry))

# ── Supabase helpers ──────────────────────────────────────────────────────────

def supabase_post(table: str, rows: list) -> bool:
    """Insert a batch of rows into a Supabase table via REST. Returns True on success."""
    url = f"{SUPABASE_REST}/{table}"
    for attempt in range(4):
        try:
            resp = _session.post(
                url, headers=HEADERS,
                data=json.dumps(rows, default=str),
                timeout=90, verify=False,
            )
            if resp.status_code in (200, 201):
                return True
            print(f"  Supabase error {resp.status_code} (attempt {attempt+1}): {resp.text[:200]}")
        except Exception as exc:
            wait = 2 ** attempt
            print(f"  Connection error (attempt {attempt+1}): {exc} — retrying in {wait}s")
            time.sleep(wait)
    return False


def supabase_count(table: str) -> int:
    """Return total row count from a Supabase table via Content-Range header."""
    url = f"{SUPABASE_REST}/{table}?select=count"
    try:
        resp = _session.get(
            url,
            headers={**HEADERS, "Prefer": "count=exact"},
            timeout=30,
            verify=False,
        )
    except Exception:
        return -1
    if resp.status_code != 200:
        return -1
    content_range = resp.headers.get("Content-Range", "")
    if "/" in content_range:
        return int(content_range.split("/")[1])
    return -1


def supabase_table_exists(table: str) -> bool:
    """Return True if the Supabase archive table is accessible (200 OK)."""
    url = f"{SUPABASE_REST}/{table}?limit=0"
    try:
        resp = _session.get(url, headers=HEADERS, timeout=10, verify=False)
        return resp.status_code == 200
    except Exception:
        return False

# ── Schema discovery ──────────────────────────────────────────────────────────

def get_columns(conn, schema: str, table: str) -> list[dict]:
    """
    Return ordered list of {name, data_type} for a Neon table.
    Excludes any column named 'id' (we add our own bigserial PK in the archive).
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name, data_type, udt_name
            FROM information_schema.columns
            WHERE table_schema = %s
              AND table_name   = %s
            ORDER BY ordinal_position
            """,
            (schema, table),
        )
        rows = cur.fetchall()
    return [{"name": r[0], "data_type": r[1], "udt_name": r[2]} for r in rows
            if r[0] != "id"]

# ── DDL generation ────────────────────────────────────────────────────────────

# Map Postgres data_type / udt_name to a reasonable Supabase column type.
_TYPE_MAP = {
    "integer":                   "integer",
    "bigint":                    "bigint",
    "smallint":                  "smallint",
    "numeric":                   "numeric",
    "double precision":          "double precision",
    "real":                      "real",
    "boolean":                   "boolean",
    "text":                      "text",
    "character varying":         "text",
    "character":                 "text",
    "uuid":                      "uuid",
    "json":                      "jsonb",
    "jsonb":                     "jsonb",
    "timestamp with time zone":  "timestamptz",
    "timestamp without time zone": "timestamp",
    "date":                      "date",
    "time with time zone":       "timetz",
    "time without time zone":    "time",
    "interval":                  "interval",
    "USER-DEFINED":              "text",  # enums etc. — safest fallback
    "ARRAY":                     "text",  # arrays — store as text
}

def pg_to_sb_type(col: dict) -> str:
    return _TYPE_MAP.get(col["data_type"], "text")


def generate_ddl(cfg: dict, columns: list[dict]) -> str:
    archive = cfg["archive_table"]
    ts_col  = cfg["ts_col"]

    col_defs = ["    id bigserial primary key"]
    for col in columns:
        sb_type = pg_to_sb_type(col)
        col_defs.append(f"    {col['name']} {sb_type}")

    ddl_lines = [
        f"-- Archive table for: {cfg['table']}",
        f"create table if not exists {archive} (",
        ",\n".join(col_defs),
        ");",
        f"alter table {archive} disable row level security;",
        f"create index if not exists idx_{archive}_{ts_col}",
        f"    on {archive} ({ts_col});",
    ]
    return "\n".join(ddl_lines)

# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    print("=" * 70)
    print("BetGeniusAI — Cold Table Archive")
    print(f"Run time : {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"Tables   : {', '.join(t['table'] for t in tables_to_run)}")
    print(f"Dry run  : {'YES' if args.dry_run else 'no'}")
    print("=" * 70)

    # Open a single Neon connection for schema discovery and row counting
    try:
        conn = psycopg2.connect(DATABASE_URL)
    except Exception as exc:
        print(f"ERROR: Cannot connect to Neon Postgres: {exc}")
        return 1

    # ── 1. Schema discovery ───────────────────────────────────────────────────

    print("\n>>> Discovering column schemas from Neon information_schema …\n")
    table_columns: dict[str, list[dict]] = {}
    for cfg in tables_to_run:
        cols = get_columns(conn, "public", cfg["table"])
        if not cols:
            print(f"  WARNING: No columns found for '{cfg['table']}' "
                  f"(table may not exist in Neon — skipping)")
        else:
            table_columns[cfg["table"]] = cols
            print(f"  {cfg['table']:40s}  {len(cols)} columns")

    # ── 2. Print DDL for all tables ────────────────────────────────────────────

    print("\n" + "=" * 70)
    print(">>> Supabase DDL — paste into SQL Editor if tables don't exist yet")
    print("=" * 70)
    for cfg in tables_to_run:
        cols = table_columns.get(cfg["table"])
        if not cols:
            continue
        print()
        print(generate_ddl(cfg, cols))
    print()
    print("=" * 70)

    # ── 3. Archive each table ─────────────────────────────────────────────────

    manifest_path = REPO / "scripts/cold_archive_manifest.json"
    try:
        manifest: dict = json.loads(manifest_path.read_text())
    except Exception:
        manifest = {}

    any_failed = False

    for cfg in tables_to_run:
        table        = cfg["table"]
        ts_col       = cfg["ts_col"]
        retention    = cfg["retention_days"]
        archive_tbl  = cfg["archive_table"]
        cutoff_dt    = datetime.now(timezone.utc) - timedelta(days=retention)
        cutoff       = cutoff_dt.isoformat()

        print(f"\n{'─' * 70}")
        print(f"Table : {table}")
        print(f"Cutoff: {cutoff[:10]}  (retain last {retention} days)")

        cols = table_columns.get(table)
        if not cols:
            print(f"  SKIP — no schema found (table may not exist in Neon)")
            continue

        col_names = [c["name"] for c in cols]

        # 3a. Check archive table exists in Supabase
        if not args.dry_run:
            if not supabase_table_exists(archive_tbl):
                print(f"\n  ERROR: Archive table '{archive_tbl}' does not exist in Supabase.")
                print(f"  Run the DDL printed above in the Supabase SQL Editor, then re-run.")
                any_failed = True
                continue
            print(f"  Supabase table '{archive_tbl}' exists — OK")

        # 3b. Count rows to archive
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {ts_col} < %s",
                (cutoff,),
            )
            total_to_archive = cur.fetchone()[0]

            cur.execute(f"SELECT COUNT(*) FROM {table}")
            total_rows = cur.fetchone()[0]

            cur.execute(
                f"SELECT MIN({ts_col}), MAX({ts_col}) FROM {table} WHERE {ts_col} < %s",
                (cutoff,),
            )
            min_ts, max_ts = cur.fetchone()

        print(f"  Source rows (total)   : {total_rows:,}")
        print(f"  Rows to archive       : {total_to_archive:,}")
        if min_ts:
            print(f"  Date range            : {str(min_ts)[:10]} → {str(max_ts)[:10]}")

        if total_to_archive == 0:
            print("  Nothing to archive — all rows are within retention window.")
            continue

        if args.dry_run:
            est_batches = (total_to_archive + args.batch - 1) // args.batch
            print(f"  DRY RUN — would send {est_batches} batches of up to {args.batch} rows each")
            continue

        # 3c. Archive in batches via named server-side cursor
        col_select = ", ".join(col_names)
        cursor_name = f"archive_cursor_{table}"

        archived  = 0
        failed    = 0
        batch_num = 0
        t_start   = time.time()

        print(f"\n  Archiving {total_to_archive:,} rows in batches of {args.batch} …")

        with conn.cursor(cursor_name, cursor_factory=psycopg2.extras.DictCursor) as cur2:
            cur2.execute(
                f"SELECT {col_select} FROM {table} WHERE {ts_col} < %s ORDER BY {ts_col}",
                (cutoff,),
            )

            while True:
                batch_raw = cur2.fetchmany(args.batch)
                if not batch_raw:
                    break

                batch_num += 1
                rows = []
                for row in batch_raw:
                    r = {}
                    for col in col_names:
                        val = row[col]
                        # datetime / date / Decimal — JSON-safe via default=str,
                        # but isoformat() gives cleaner strings for timestamps
                        if hasattr(val, "isoformat"):
                            val = val.isoformat()
                        r[col] = val
                    rows.append(r)

                ok = supabase_post(archive_tbl, rows)
                if ok:
                    archived += len(rows)
                    elapsed = time.time() - t_start
                    rate = archived / elapsed if elapsed > 0 else 0
                    eta  = (total_to_archive - archived) / rate if rate > 0 else 0
                    print(
                        f"  Batch {batch_num:4d}  +{len(rows):5d}  "
                        f"total={archived:,}/{total_to_archive:,}  "
                        f"rate={rate:.0f}/s  ETA={eta:.0f}s"
                    )
                else:
                    failed += len(rows)
                    print(f"  Batch {batch_num:4d} FAILED — {failed} rows not archived so far")
                    if failed > total_to_archive * 0.05:
                        print("  ERROR: >5% of rows failed. Aborting this table — do NOT run cleanup.")
                        break

        # 3d. Verify
        print(f"\n  Verifying Supabase row count …")
        time.sleep(2)
        sb_count = supabase_count(archive_tbl)
        print(f"  Supabase {archive_tbl}: {sb_count:,} rows total")
        print(f"  Rows archived this run: {archived:,}")
        print(f"  Rows failed           : {failed:,}")

        if failed > 0:
            print(f"  WARNING: {failed} rows failed. Skipping manifest entry — do NOT run cleanup.")
            any_failed = True
            continue

        if sb_count < 0:
            print(f"  ERROR: Could not read Supabase row count — skipping manifest entry.")
            any_failed = True
            continue

        if sb_count < archived:
            print(
                f"  VERIFICATION FAILED: Supabase has {sb_count:,} rows but "
                f"expected >= {archived:,}. Skipping manifest entry."
            )
            any_failed = True
            continue

        print(f"  Verification OK: Supabase total ({sb_count:,}) >= archived ({archived:,})")

        # 3e. Write manifest entry for this table
        manifest[table] = {
            "archived_at":      datetime.now(timezone.utc).isoformat(),
            "cutoff":           cutoff,
            "retention_days":   retention,
            "rows_archived":    archived,
            "supabase_count":   sb_count,
            "supabase_verified": True,
            "archive_table":    archive_tbl,
            "ts_col":           ts_col,
        }
        manifest_path.write_text(json.dumps(manifest, indent=2))
        print(f"  Manifest updated: {manifest_path}")

    conn.close()

    # ── Summary ───────────────────────────────────────────────────────────────

    print(f"\n{'=' * 70}")
    if any_failed:
        print("RESULT: One or more tables FAILED verification.")
        print("        Do NOT run cleanup_cold_tables.py until all tables pass.")
        return 1
    else:
        print("RESULT: All tables archived and verified successfully.")
        print(f"        Manifest: {manifest_path}")
        print("Next step: python scripts/cleanup_cold_tables.py --confirm")
        return 0


if __name__ == "__main__":
    sys.exit(main())
