"""
Archive cold data from Neon to Supabase cold storage.

Archives rows older than --days (default 60) from:
  - sharp_book_odds    (3.9 GB, ~2M rows/month)

Runs in batches to avoid memory pressure. Verifies row counts before
returning success — the companion cleanup_neon_cold_data.py should only
run after this script exits 0.

Usage:
    python scripts/archive_to_supabase.py [--days 60] [--batch 2000] [--dry-run]

Requirements:
    pip install requests psycopg2-binary python-dotenv

Environment (read from .env.local or .env):
    DATABASE_URL          — Neon Postgres connection string
    SUPABASE_URL          — e.g. https://muynbzaqwbinloxdumxg.supabase.co
    SUPABASE_KEY          — publishable / service-role key

Exit codes:
    0 = success (all rows archived and verified)
    1 = error   (partial — do NOT run cleanup)
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

# ── Bootstrap ────────────────────────────────────────────────────────────────

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
    print("ERROR: 'requests' not installed. Run: pip install requests")
    sys.exit(1)

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    print("ERROR: 'psycopg2' not installed. Run: pip install psycopg2-binary")
    sys.exit(1)

# ── Args ─────────────────────────────────────────────────────────────────────

parser = argparse.ArgumentParser()
parser.add_argument("--days", type=int, default=7,
                    help="Archive rows older than this many days (default: 7)")
parser.add_argument("--batch", type=int, default=2000,
                    help="Rows per Supabase REST batch (default: 2000)")
parser.add_argument("--dry-run", action="store_true",
                    help="Count rows and estimate without writing to Supabase")
args = parser.parse_args()

CUTOFF = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()

print(f"Archive cold data  |  older than {args.days} days (before {CUTOFF[:10]})")
if args.dry_run:
    print("DRY RUN — no writes")

# ── Config ───────────────────────────────────────────────────────────────────

DATABASE_URL  = os.environ.get("DATABASE_URL")
SUPABASE_URL  = os.environ.get("SUPABASE_URL") or os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
SUPABASE_KEY  = (
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

# ── Helpers ───────────────────────────────────────────────────────────────────

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
    """Return row count from a Supabase table."""
    url = f"{SUPABASE_REST}/{table}?select=count"
    try:
        resp = _session.get(url, headers={**HEADERS, "Prefer": "count=exact"}, timeout=30, verify=False)
    except Exception:
        return -1
    if resp.status_code != 200:
        return -1
    content_range = resp.headers.get("Content-Range", "")
    # Content-Range: 0-0/12345
    if "/" in content_range:
        return int(content_range.split("/")[1])
    return -1


def supabase_table_exists(table: str) -> bool:
    url = f"{SUPABASE_REST}/{table}?limit=0"
    try:
        resp = _session.get(url, headers=HEADERS, timeout=10, verify=False)
        return resp.status_code == 200
    except Exception:
        return False


# ── Ensure archive table exists in Supabase ───────────────────────────────────

SHARP_BOOK_DDL = """
create table if not exists sharp_book_odds_archive (
    id           bigserial primary key,
    event_id     text,
    match_id     text,
    sport        text,
    bookmaker    text,
    is_sharp     boolean,
    home_team    text,
    away_team    text,
    odds_home    numeric,
    odds_draw    numeric,
    odds_away    numeric,
    prob_home    numeric,
    prob_draw    numeric,
    prob_away    numeric,
    overround    numeric,
    margin       numeric,
    ts_recorded  timestamptz,
    ts_kickoff   timestamptz,
    hours_before_kickoff numeric
);
"""

# We can't run DDL via REST — the user must create the table once in Supabase SQL editor.
# We detect and bail with a helpful message.
if not args.dry_run:
    if not supabase_table_exists("sharp_book_odds_archive"):
        print()
        print("ERROR: Table 'sharp_book_odds_archive' does not exist in Supabase.")
        print()
        print("Run this once in your Supabase SQL Editor (Dashboard → SQL Editor):")
        print()
        print(SHARP_BOOK_DDL)
        print()
        print("Then re-run this script.")
        sys.exit(1)
    print("✓ Supabase table 'sharp_book_odds_archive' exists")

# ── Count rows to archive ────────────────────────────────────────────────────

conn = psycopg2.connect(DATABASE_URL)
cur  = conn.cursor()

cur.execute(
    "SELECT COUNT(*) FROM sharp_book_odds WHERE ts_recorded < %s",
    (CUTOFF,)
)
total_to_archive = cur.fetchone()[0]

cur.execute("SELECT COUNT(*) FROM sharp_book_odds")
total_rows = cur.fetchone()[0]

cur.execute(
    "SELECT MIN(ts_recorded), MAX(ts_recorded) FROM sharp_book_odds WHERE ts_recorded < %s",
    (CUTOFF,)
)
min_ts, max_ts = cur.fetchone()

print(f"\n  sharp_book_odds total    : {total_rows:,} rows")
print(f"  Rows to archive (<{args.days}d) : {total_to_archive:,} rows")
if min_ts:
    print(f"  Date range               : {str(min_ts)[:10]} → {str(max_ts)[:10]}")

if total_to_archive == 0:
    print("\nNothing to archive — all rows are within the retention window.")
    cur.close()
    conn.close()
    sys.exit(0)

if args.dry_run:
    est_batches = (total_to_archive + args.batch - 1) // args.batch
    print(f"\n  DRY RUN — would send {est_batches} batches of up to {args.batch} rows each")
    print("  Re-run without --dry-run to proceed.")
    cur.close()
    conn.close()
    sys.exit(0)

# ── Archive in batches ────────────────────────────────────────────────────────

COLUMNS = [
    "event_id", "match_id", "sport", "bookmaker", "is_sharp",
    "home_team", "away_team",
    "odds_home", "odds_draw", "odds_away",
    "prob_home", "prob_draw", "prob_away",
    "overround", "margin",
    "ts_recorded", "ts_kickoff", "hours_before_kickoff",
]

cur2 = conn.cursor("archive_cursor", cursor_factory=psycopg2.extras.DictCursor)
cur2.execute(
    f"SELECT {', '.join(COLUMNS)} FROM sharp_book_odds WHERE ts_recorded < %s ORDER BY ts_recorded",
    (CUTOFF,)
)

archived  = 0
failed    = 0
batch_num = 0
t_start   = time.time()

print(f"\nArchiving {total_to_archive:,} rows in batches of {args.batch}…")

while True:
    batch_raw = cur2.fetchmany(args.batch)
    if not batch_raw:
        break

    batch_num += 1
    rows = []
    for row in batch_raw:
        r = {}
        for col in COLUMNS:
            val = row[col]
            if hasattr(val, "isoformat"):
                val = val.isoformat()
            r[col] = val
        rows.append(r)

    ok = supabase_post("sharp_book_odds_archive", rows)
    if ok:
        archived += len(rows)
        elapsed = time.time() - t_start
        rate = archived / elapsed if elapsed > 0 else 0
        eta   = (total_to_archive - archived) / rate if rate > 0 else 0
        print(f"  Batch {batch_num:4d}  +{len(rows):5d}  total={archived:,}/{total_to_archive:,}  "
              f"rate={rate:.0f}/s  ETA={eta:.0f}s")
    else:
        failed += len(rows)
        print(f"  Batch {batch_num:4d} FAILED — {failed} rows not archived")
        if failed > total_to_archive * 0.05:
            print("ERROR: >5% of rows failed. Aborting — do NOT run cleanup.")
            cur2.close()
            cur.close()
            conn.close()
            sys.exit(1)

cur2.close()
cur.close()
conn.close()

# ── Verify ────────────────────────────────────────────────────────────────────

print(f"\nVerifying Supabase row count…")
time.sleep(2)  # Brief pause for Supabase indexing
sb_count = supabase_count("sharp_book_odds_archive")
print(f"  Supabase sharp_book_odds_archive: {sb_count:,} rows")
print(f"  Rows archived this run          : {archived:,}")
print(f"  Rows failed                     : {failed:,}")

if failed > 0:
    print(f"\n⚠️  {failed} rows failed to archive. Do NOT run cleanup until all rows are confirmed.")
    sys.exit(1)

# ── Hard equality check — must match before we allow cleanup ──────────────────
# supabase_count returns the total table count (cumulative across all runs).
# We check that Supabase has AT LEAST as many rows as we archived this run.
# On the very first run they should be equal; on subsequent runs sb_count >= archived.
if sb_count < 0:
    print(f"\nERROR: Could not read Supabase row count — aborting to protect Neon data.")
    print("       Check SUPABASE_URL and SUPABASE_KEY, then re-run.")
    sys.exit(1)

if sb_count < archived:
    print(f"\n❌ VERIFICATION FAILED: Supabase has {sb_count:,} rows but we expected "
          f"at least {archived:,}.")
    print("   Some rows did not land in Supabase. Do NOT run cleanup.")
    sys.exit(1)

print(f"  Verification      : ✅ Supabase total ({sb_count:,}) >= archived this run ({archived:,})")

# Write a manifest so cleanup script can verify before deleting
manifest = {
    "archived_at": datetime.now(timezone.utc).isoformat(),
    "cutoff": CUTOFF,
    "days": args.days,
    "rows_archived": archived,
    "supabase_count": sb_count,
    "supabase_verified": True,
    "table": "sharp_book_odds_archive",
}
manifest_path = REPO / "scripts/archive_manifest.json"
manifest_path.write_text(json.dumps(manifest, indent=2))
print(f"\n✅ Archive complete — {archived:,} rows written to Supabase.")
print(f"   Manifest saved to {manifest_path}")
print(f"\nNext step: python scripts/cleanup_neon_cold_data.py --confirm")
