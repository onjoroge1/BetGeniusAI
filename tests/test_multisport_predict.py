"""
Integration tests for POST /predict-multisport and GET /predict-multisport/available
"""

import os
import sys
import pytest
import requests

BASE_URL = os.environ.get("TEST_BASE_URL", "http://localhost:5000")
AUTH_HEADER = {"Authorization": "Bearer betgenius_secure_key_2024"}

def _get_upcoming_event(sport_key):
    """Helper: grab first available event_id for a sport."""
    resp = requests.get(
        f"{BASE_URL}/predict-multisport/available",
        params={"sport": sport_key},
        headers=AUTH_HEADER,
        timeout=30,
    )
    if resp.status_code != 200 or not resp.json().get("fixtures"):
        pytest.skip(f"No upcoming {sport_key} fixtures with odds")
    return resp.json()["fixtures"][0]["event_id"]


class TestPredictMultisportNBA:
    @pytest.fixture(autouse=True)
    def _event(self):
        self.event_id = _get_upcoming_event("basketball_nba")

    def _predict(self, **overrides):
        body = {"event_id": self.event_id, "sport": "basketball_nba", "include_analysis": False}
        body.update(overrides)
        return requests.post(
            f"{BASE_URL}/predict-multisport",
            json=body,
            headers=AUTH_HEADER,
            timeout=30,
        )

    def test_nba_returns_200(self):
        resp = self._predict()
        assert resp.status_code == 200

    def test_nba_no_draw(self):
        data = self._predict().json()
        assert data["no_draw"] is True
        assert "draw" not in data["predictions"]

    def test_nba_predictions_fields(self):
        p = self._predict().json()["predictions"]
        for key in ("home_win", "away_win", "pick", "recommended_bet", "confidence", "conviction_tier"):
            assert key in p, f"Missing predictions.{key}"
        assert p["pick"] in ("H", "A")
        assert 0 < p["confidence"] <= 1.0

    def test_nba_model_info(self):
        mi = self._predict().json()["model_info"]
        assert mi["n_features"] == 46
        assert mi["type"] == "lightgbm"
        assert "feature_groups" in mi
        assert len(mi["feature_groups"]) == 7

    def test_nba_has_5_markets(self):
        markets = self._predict().json()["markets"]
        types = {m["type"] for m in markets}
        assert "moneyline" in types
        assert "spread" in types
        assert "total" in types
        assert "first_half_total" in types
        assert "team_totals" in types
        assert len(markets) == 5

    def test_nba_market_fields_complete(self):
        markets = self._predict().json()["markets"]
        for m in markets:
            if "options" in m:
                for opt in m["options"]:
                    for field in ("model_prob", "implied_prob", "decimal_odds", "edge"):
                        assert field in opt, f"Missing {field} in {m['market']}/{opt.get('label')}"
            elif "projections" in m:
                for side in ("home", "away"):
                    proj = m["projections"][side]
                    for field in ("model_prob", "implied_prob", "decimal_odds", "edge"):
                        assert field in proj, f"Missing {field} in {m['market']}/{side}"

    def test_nba_team_context(self):
        tc = self._predict().json()["team_context"]
        for side in ("home", "away"):
            assert "recent_form" in tc[side]
            assert "season_stats" in tc[side]
            assert "rest" in tc[side]

    def test_nba_feature_values(self):
        fv = self._predict().json()["feature_values"]
        assert len(fv) == 46


class TestPredictMultisportNHL:
    @pytest.fixture(autouse=True)
    def _event(self):
        self.event_id = _get_upcoming_event("icehockey_nhl")

    def _predict(self, **overrides):
        body = {"event_id": self.event_id, "sport": "icehockey_nhl", "include_analysis": False}
        body.update(overrides)
        return requests.post(
            f"{BASE_URL}/predict-multisport",
            json=body,
            headers=AUTH_HEADER,
            timeout=30,
        )

    def test_nhl_returns_200(self):
        resp = self._predict()
        assert resp.status_code == 200

    def test_nhl_no_draw(self):
        data = self._predict().json()
        assert data["no_draw"] is True

    def test_nhl_spread_is_puck_line(self):
        markets = self._predict().json()["markets"]
        spread_markets = [m for m in markets if m["type"] == "spread"]
        if spread_markets:
            assert spread_markets[0]["market"] == "Puck Line"


class TestPredictMultisportAvailable:
    def test_nba_available_returns_fixtures(self):
        resp = requests.get(
            f"{BASE_URL}/predict-multisport/available",
            params={"sport": "basketball_nba"},
            headers=AUTH_HEADER,
            timeout=30,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "fixtures" in data
        assert "count" in data
        if data["count"] > 0:
            f = data["fixtures"][0]
            for key in ("event_id", "home_team", "away_team", "commence_time", "model_pick", "model_confidence"):
                assert key in f

    def test_nhl_available_returns_fixtures(self):
        resp = requests.get(
            f"{BASE_URL}/predict-multisport/available",
            params={"sport": "icehockey_nhl"},
            headers=AUTH_HEADER,
            timeout=30,
        )
        assert resp.status_code == 200

    def test_invalid_sport_returns_400(self):
        resp = requests.get(
            f"{BASE_URL}/predict-multisport/available",
            params={"sport": "invalid_sport"},
            headers=AUTH_HEADER,
            timeout=30,
        )
        assert resp.status_code == 400


class TestPredictMultisportValidation:
    def test_missing_auth_returns_401(self):
        resp = requests.post(
            f"{BASE_URL}/predict-multisport",
            json={"event_id": "abc", "sport": "basketball_nba"},
            timeout=10,
        )
        assert resp.status_code == 401

    def test_invalid_sport_returns_400(self):
        resp = requests.post(
            f"{BASE_URL}/predict-multisport",
            json={"event_id": "abc", "sport": "baseball_mlb"},
            headers=AUTH_HEADER,
            timeout=10,
        )
        assert resp.status_code == 400

    def test_unknown_event_returns_404(self):
        resp = requests.post(
            f"{BASE_URL}/predict-multisport",
            json={"event_id": "nonexistent_event_id_123", "sport": "basketball_nba"},
            headers=AUTH_HEADER,
            timeout=15,
        )
        assert resp.status_code == 404
