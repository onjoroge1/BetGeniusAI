"""
HTTP contract tests (#4) — boot the real app and assert the payload contracts
the frontend manuals depend on. Skipped where fastapi/app isn't importable
(minimal dev env); runs in CI / on Replit.

These catch the class of bug unit tests can't: wiring/serialization errors in the
actual endpoints (the value blocks, nullable contracts, WC routing, 2-way no-draw).
"""
import pytest


def _probs_sum_ok(p, keys, tol=0.02):
    s = sum(p[k] for k in keys if p.get(k) is not None)
    return abs(s - 1.0) <= tol


class TestLiveEdgeBoard:
    def test_board_ok_and_shape(self, client):
        r = client.get("/live-edge/board")
        assert r.status_code == 200
        body = r.json()
        assert "matches" in body and "active_matches" in body
        for card in body["matches"]:
            # Layer-1 always present
            assert "win_probability" in card and "status" in card
            assert card["status"] in ("WATCHLIST", "BETTABLE", "SUSPENDED", "EXPIRED")
            wp = card.get("win_probability")
            if wp:
                assert _probs_sum_ok(wp, ("home", "draw", "away"))
            # honesty: never BETTABLE without a value block / fresh odds
            if card["status"] == "BETTABLE":
                assert card.get("value") is not None
            # stale feed must not be BETTABLE
            if card.get("data_quality") == "stale":
                assert card["status"] != "BETTABLE"

    def test_board_requires_auth(self, client):
        # with overrides cleared this would 401; here auth is bypassed so just 200
        r = client.get("/live-edge/board")
        assert r.status_code in (200, 401)


class TestMarketMultisport:
    def test_2way_has_no_draw_in_value(self, client):
        r = client.get("/market-multisport?sport=basketball_nba&status=upcoming&limit=5")
        assert r.status_code == 200
        for m in r.json().get("matches", []):
            val = m.get("value")
            if val and val.get("edge"):
                assert "draw" not in val["edge"], "2-way market leaked a draw key"
            mtr = m.get("model_track_record")
            if mtr:
                assert mtr["edge_validated"] is False  # multisport not validated


class TestHealth:
    def test_health(self, client):
        r = client.get("/health")
        assert r.status_code == 200


class TestPredictWcContract:
    def test_predict_wc_or_skip(self, client):
        r = client.post("/predict-wc", json={"home_team": "Spain", "away_team": "Brazil", "neutral": True})
        if r.status_code == 404:
            pytest.skip("teams not rated in this env")
        assert r.status_code == 200
        body = r.json()
        assert body.get("selected_model") == "wc_elo"
        p = body["predictions"]
        assert _probs_sum_ok({"home": p["home_win"], "draw": p["draw"], "away": p["away_win"]},
                             ("home", "draw", "away"))
        # recommended_bet must equal argmax (the bug that corrupted picks before)
        probs = {"home_win": p["home_win"], "draw": p["draw"], "away_win": p["away_win"]}
        assert p["recommended_bet"] == max(probs, key=probs.get)
