"""
HTTP contract tests for /predict-wc and /predict via FastAPI TestClient.

Requires the full app to import (fastapi + all route deps), so these are SKIPPED
in minimal local envs and run in CI / on Replit where deps are installed.
Auth is bypassed via dependency_overrides so the tests exercise the handlers.
"""
import os
import pytest
from conftest import requires_db

# Skip the whole module if the app can't be imported (minimal local env)
fastapi_testclient = pytest.importorskip("fastapi.testclient", reason="fastapi not installed")

try:
    import main as app_main
    from main import app, verify_api_key
    _APP_OK = True
except Exception as _e:  # noqa
    _APP_OK = False
    _IMPORT_ERR = str(_e)

pytestmark = pytest.mark.skipif(not _APP_OK, reason="app not importable in this env")


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    # bypass API-key auth for tests
    app.dependency_overrides[verify_api_key] = lambda: "test-key"
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


class TestPredictWcEndpoint:
    @requires_db
    def test_valid_by_name(self, client):
        r = client.post("/predict-wc", json={"home_team": "Spain", "away_team": "Argentina", "neutral": True})
        assert r.status_code == 200
        body = r.json()
        p = body["predictions"]
        assert abs((p["home_win"] + p["draw"] + p["away_win"]) - 1.0) < 0.02
        assert p["recommended_bet"] in ("home_win", "draw", "away_win")
        assert body["selected_model"] == "wc_elo"

    def test_missing_params_400(self, client):
        r = client.post("/predict-wc", json={"neutral": True})
        assert r.status_code == 400

    @requires_db
    def test_unknown_team_404(self, client):
        r = client.post("/predict-wc", json={"home_team": "Atlantis", "away_team": "Wakanda"})
        assert r.status_code == 404


class TestPredictRoutesWC:
    @requires_db
    def test_wc_match_id_routes_to_elo(self, client, db):
        cur = db.cursor()
        cur.execute("SELECT match_id FROM fixtures WHERE league_id=1 AND season=2026 LIMIT 1")
        row = cur.fetchone()
        if not row:
            pytest.skip("no WC fixtures seeded")
        r = client.post("/predict", json={"match_id": row[0], "include_analysis": False})
        assert r.status_code == 200
        body = r.json()
        # WC matches must be served by the ELO model, not the club cascade
        assert body.get("selected_model") == "wc_elo"


class TestHealth:
    def test_health_ok(self, client):
        r = client.get("/health")
        assert r.status_code == 200
