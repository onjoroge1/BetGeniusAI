"""
Delete archived cold data from Neon after Supabase archival is confirmed.

Reads the manifest written by archive_to_supabase.py and requires --confirm
to actually delete. Prints exactly how many rows it will delete so you can
sanity-check before committing.

Usage:
    # Preview what will be deleted (no changes):
    python scripts/cleanup_neon_cold_data.py

    # Actually delete (irreversible):
    python scripts/cleanup_neon_cold_data.py --confirm

Exit codes:
    0 = success
    1 = manifest missing, count mismatch, or delete failed
"""

import os
import sys
import json
import argparse
from datetime import datetime, timezone
from pathlib import Path

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
    import psycopg2
except ImportError:
    print("ERROR: 'psycopg2' not installed. Run: pip install psycopg2-binary")
    sys.exit(1)

# ── Args ─────────────────────────────────────────────────────────────────────

parser = argparse.ArgumentParser()
parser.add_argument("--confirm", action="store_true",
                    help="Actually delete rows (without this flag, just previews)")
parser.add_argument("--manifest", type=str, default="scripts/archive_manifest.json",
                    help="Path to manifest from archive_to_supabase.py")
args = parser.parse_args()

# ── Load manifest ─────────────────────────────────────────────────────────────

manifest_path = REPO / args.manifest
if not manifest_path.exists():
    print(f"ERROR: Manifest not found at {manifest_path}")
    print("Run archive_to_supabase.py first to create it.")
    sys.exit(1)

manifest = json.loads(manifest_path.read_text())
cutoff        = manifest["cutoff"]
rows_archived = manifest["rows_archived"]
archived_at   = manifest["archived_at"]

print(f"Cleanup Neon cold data")
print(f"  Archive manifest  : {manifest_path}")
print(f"  Archived at       : {archived_at[:19]}")
print(f"  Rows archived     : {rows_archived:,}")
print(f"  Cutoff            : {cutoff[:10]}")

# ── Connect and count ─────────────────────────────────────────────────────────

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL not set")
    sys.exit(1)

conn = psycopg2.connect(DATABASE_URL)
cur  = conn.cursor()

cur.execute(
    "SELECT COUNT(*) FROM sharp_book_odds WHERE ts_recorded < %s",
    (cutoff,)
)
rows_to_delete = cur.fetchone()[0]

cur.execute("SELECT COUNT(*) FROM sharp_book_odds")
total_before = cur.fetchone()[0]

print(f"\n  sharp_book_odds (current)   : {total_before:,} rows")
print(f"  Rows matching cutoff        : {rows_to_delete:,}")
print(f"  Rows remaining after delete : {total_before - rows_to_delete:,}")

# ── Safety check ─────────────────────────────────────────────────────────────

if rows_to_delete == 0:
    print("\nNothing to delete — no rows older than the archive cutoff.")
    cur.close()
    conn.close()
    sys.exit(0)

# Warn if counts diverge significantly (>1% tolerance)
tolerance = max(int(rows_archived * 0.01), 100)
if abs(rows_to_delete - rows_archived) > tolerance:
    print(f"\n⚠️  Row count mismatch: manifest says {rows_archived:,} archived "
          f"but Neon has {rows_to_delete:,} matching cutoff.")
    print("   This can happen if new rows were collected that fall in the same window.")
    print("   Proceeding — delete will only remove rows before the recorded cutoff.")

if not args.confirm:
    print(f"\nDRY RUN — {rows_to_delete:,} rows WOULD be deleted from sharp_book_odds.")
    print("Re-run with --confirm to actually delete.")
    cur.close()
    conn.close()
    sys.exit(0)

# ── Delete ────────────────────────────────────────────────────────────────────

print(f"\nDeleting {rows_to_delete:,} rows from sharp_book_odds…")
cur.execute(
    "DELETE FROM sharp_book_odds WHERE ts_recorded < %s",
    (cutoff,)
)
deleted = cur.rowcount
conn.commit()

cur.execute("SELECT COUNT(*) FROM sharp_book_odds")
total_after = cur.fetchone()[0]

cur.close()
conn.close()

print(f"  Deleted       : {deleted:,} rows")
print(f"  Remaining     : {total_after:,} rows")
expected_remaining = total_before - deleted
if total_after == expected_remaining:
    print(f"  Count check   : ✅ ({total_after:,} == {expected_remaining:,})")
else:
    print(f"  Count check   : ⚠️  expected {expected_remaining:,}, got {total_after:,}")

# Update manifest to record cleanup
manifest["cleanup_at"]   = datetime.now(timezone.utc).isoformat()
manifest["rows_deleted"] = deleted
manifest["rows_remaining"] = total_after
manifest_path.write_text(json.dumps(manifest, indent=2))

print(f"\n✅ Cleanup complete — freed ~{deleted * 400 / 1e9:.2f} GB from Neon.")
print(f"   Updated manifest: {manifest_path}")
