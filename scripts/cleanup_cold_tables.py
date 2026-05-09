#!/usr/bin/env python3 -u
"""
Delete cold rows from Neon after confirming they have been archived to Supabase.

Reads scripts/cold_archive_manifest.json written by archive_cold_tables.py.
Only deletes rows for tables where supabase_verified == true.

Usage:
    python scripts/cleanup_cold_tables.py           # dry-run (default)
    python scripts/cleanup_cold_tables.py --confirm  # execute DELETEs

Requirements:
    pip install psycopg2-binary

Environment (read from .env.local or .env):
    DATABASE_URL  — Neon Postgres connection string

Exit codes:
    0 = success
    1 = error (manifest missing, no verified tables, or DELETE failed)
"""

import os
import sys
import json
import time
import argparse
import warnings
from datetime import datetime, timezone
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
    import psycopg2
except ImportError:
    print("ERROR: 'psycopg2' not installed.  Run: pip install psycopg2-binary")
    sys.exit(1)

# ── Args ──────────────────────────────────────────────────────────────────────

parser = argparse.ArgumentParser(
    description="Delete cold Neon rows that have been verified in Supabase."
)
parser.add_argument(
    "--confirm", action="store_true",
    help="Execute the DELETEs (default: dry-run only)",
)
parser.add_argument(
    "--table", metavar="NAME",
    help="Clean up only this table (default: all verified tables in manifest)",
)
args = parser.parse_args()

DRY_RUN = not args.confirm

# ── Constants ─────────────────────────────────────────────────────────────────

BYTES_PER_ROW   = 400          # rough estimate for MB-freed calculation
MANIFEST_PATH   = REPO / "scripts/cold_archive_manifest.json"

# ── Config ────────────────────────────────────────────────────────────────────

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL not set")
    sys.exit(1)

# ── Load manifest ─────────────────────────────────────────────────────────────

if not MANIFEST_PATH.exists():
    print(f"ERROR: Manifest not found at {MANIFEST_PATH}")
    print("       Run archive_cold_tables.py first.")
    sys.exit(1)

try:
    manifest: dict = json.loads(MANIFEST_PATH.read_text())
except Exception as exc:
    print(f"ERROR: Cannot parse manifest: {exc}")
    sys.exit(1)

if not manifest:
    print("ERROR: Manifest is empty — nothing to clean up.")
    sys.exit(1)

# Filter to requested table if given
if args.table:
    if args.table not in manifest:
        print(f"ERROR: Table '{args.table}' not found in manifest.")
        print("       Available tables: " + ", ".join(manifest.keys()))
        sys.exit(1)
    entries = {args.table: manifest[args.table]}
else:
    entries = manifest

# Only act on verified entries that haven't already been cleaned up
pending = {
    tbl: meta
    for tbl, meta in entries.items()
    if meta.get("supabase_verified") and not meta.get("cleanup_at")
}

already_done = {
    tbl: meta
    for tbl, meta in entries.items()
    if meta.get("cleanup_at")
}

unverified = {
    tbl: meta
    for tbl, meta in entries.items()
    if not meta.get("supabase_verified") and not meta.get("cleanup_at")
}

# ── Summary header ────────────────────────────────────────────────────────────

print("=" * 70)
print("BetGeniusAI — Cold Table Cleanup")
print(f"Run time  : {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
print(f"Dry run   : {'YES — pass --confirm to execute' if DRY_RUN else 'NO — executing DELETEs'}")
print("=" * 70)

if already_done:
    print(f"\nAlready cleaned ({len(already_done)}):")
    for tbl, meta in already_done.items():
        print(f"  {tbl:45s}  cleaned {meta['cleanup_at'][:10]}  "
              f"{meta.get('rows_deleted', '?'):>8} rows deleted")

if unverified:
    print(f"\nNot verified — skipping ({len(unverified)}):")
    for tbl in unverified:
        print(f"  {tbl}")

if not pending:
    print("\nNothing to clean up.")
    sys.exit(0)

print(f"\nPending cleanup ({len(pending)} tables):")
total_rows_est = 0
for tbl, meta in pending.items():
    rows  = meta.get("rows_archived", 0)
    mb    = rows * BYTES_PER_ROW / 1_000_000
    total_rows_est += rows
    print(
        f"  {tbl:45s}  cutoff {meta['cutoff'][:10]}  "
        f"{rows:>8,} rows  ~{mb:.1f} MB"
    )

total_mb = total_rows_est * BYTES_PER_ROW / 1_000_000
print(f"\n  Estimated total: {total_rows_est:,} rows  ~{total_mb:.1f} MB freed")

if DRY_RUN:
    print("\nDRY RUN — no rows deleted.  Re-run with --confirm to execute.")
    sys.exit(0)

# ── Connect and execute ────────────────────────────────────────────────────────

print()
try:
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
except Exception as exc:
    print(f"ERROR: Cannot connect to Neon Postgres: {exc}")
    sys.exit(1)

any_failed = False

for tbl, meta in pending.items():
    ts_col  = meta.get("ts_col")
    cutoff  = meta.get("cutoff")
    archive = meta.get("archive_table", f"{tbl}_archive")

    if not ts_col or not cutoff:
        print(f"\n[{tbl}] ERROR: Manifest entry missing 'ts_col' or 'cutoff' — skipping.")
        any_failed = True
        continue

    print(f"\n{'─' * 70}")
    print(f"Table : {tbl}")
    print(f"Filter: {ts_col} < {cutoff[:10]}")

    # Count first (fast, uses index)
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT COUNT(*) FROM {tbl} WHERE {ts_col} < %s",
                (cutoff,),
            )
            count_before = cur.fetchone()[0]
    except Exception as exc:
        print(f"  ERROR counting rows: {exc}")
        conn.rollback()
        any_failed = True
        continue

    mb_est = count_before * BYTES_PER_ROW / 1_000_000
    print(f"  Rows to delete: {count_before:,}  (~{mb_est:.1f} MB)")

    if count_before == 0:
        print("  Nothing to delete.")
        continue

    # Execute DELETE
    t0 = time.time()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"DELETE FROM {tbl} WHERE {ts_col} < %s",
                (cutoff,),
            )
            rows_deleted = cur.rowcount
        conn.commit()
    except Exception as exc:
        print(f"  ERROR executing DELETE: {exc}")
        conn.rollback()
        any_failed = True
        continue

    elapsed = time.time() - t0
    mb_freed = rows_deleted * BYTES_PER_ROW / 1_000_000
    print(f"  Deleted : {rows_deleted:,} rows  ~{mb_freed:.1f} MB freed  ({elapsed:.1f}s)")

    # Update manifest
    manifest[tbl]["cleanup_at"]    = datetime.now(timezone.utc).isoformat()
    manifest[tbl]["rows_deleted"]  = rows_deleted
    manifest[tbl]["mb_freed_est"]  = round(mb_freed, 2)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))
    print(f"  Manifest updated.")

conn.close()

# ── Summary ────────────────────────────────────────────────────────────────────

print(f"\n{'=' * 70}")
if any_failed:
    print("RESULT: One or more tables encountered errors during cleanup.")
    sys.exit(1)
else:
    total_deleted = sum(
        manifest[tbl].get("rows_deleted", 0)
        for tbl in pending
        if manifest[tbl].get("rows_deleted") is not None
    )
    total_mb_freed = total_deleted * BYTES_PER_ROW / 1_000_000
    print(f"RESULT: Cleanup complete.")
    print(f"        {total_deleted:,} rows deleted  (~{total_mb_freed:.1f} MB freed)")
    print(f"        Manifest: {MANIFEST_PATH}")
    sys.exit(0)
