"""
Fixtures for API contract tests (#4). Boots the real FastAPI app via TestClient
with auth bypassed. Skips cleanly where the app can't be imported (minimal dev
env without fastapi/route deps) — these run in CI / on Replit where deps exist.
"""
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

# NOTE: pytest's default import mode shares the module name `conftest` across all
# test dirs, so this symbol must also exist here (the edge/wc conftests define it
# too) or `from conftest import requires_db` in those suites resolves to THIS file
# and fails. Keep in sync with tests/wc/conftest.py.
HAS_DB = bool(os.environ.get("DATABASE_URL"))
requires_db = pytest.mark.skipif(not HAS_DB, reason="DATABASE_URL not set")


@pytest.fixture(scope="session")
def client():
    """TestClient for the real app, with API-key auth bypassed. Skips if fastapi/app
    can't be imported (minimal dev env) — runs in CI / on Replit."""
    pytest.importorskip("fastapi.testclient", reason="fastapi not installed")
    try:
        import main as app_main  # noqa
        from main import app
    except Exception as e:
        pytest.skip(f"app not importable in this env: {e}")

    from fastapi.testclient import TestClient
    # bypass auth on whatever dependency the routes use
    for dep_name in ("verify_api_key", "verify_api_key_dep"):
        dep = getattr(app_main, dep_name, None)
        if dep is not None:
            app.dependency_overrides[dep] = lambda: "test-key"
    # also override the live-edge router's dependency if present
    try:
        from routes.live_edge import verify_api_key_dep as le_dep
        app.dependency_overrides[le_dep] = lambda: "test-key"
    except Exception:
        pass
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
