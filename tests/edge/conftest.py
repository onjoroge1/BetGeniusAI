"""Shared fixtures for the edge-engine test suite (mirrors tests/wc/conftest.py)."""
import os
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

for _ef in (".env.local", ".env"):
    _p = REPO / _ef
    if _p.exists():
        for _line in _p.read_text().splitlines():
            _m = re.match(r"^([^#=\s][^=]*)=(.*)$", _line)
            if _m and not os.environ.get(_m.group(1).strip()):
                os.environ[_m.group(1).strip()] = _m.group(2).strip()
        break

HAS_DB = bool(os.environ.get("DATABASE_URL"))
requires_db = pytest.mark.skipif(not HAS_DB, reason="DATABASE_URL not set")


@pytest.fixture(scope="session")
def db():
    if not HAS_DB:
        pytest.skip("DATABASE_URL not set")
    import psycopg2
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    conn.set_session(readonly=True, autocommit=True)
    yield conn
    conn.close()
