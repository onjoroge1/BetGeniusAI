"""
Tests for WCPredictor, the response builder, and match_id routing.
Most need DB (ELO ratings + seeded fixtures); pure-logic tests do not.
"""
import pytest
from conftest import requires_db
from models.wc_predictor import (
    WCPredictor, build_wc_response, route_wc_by_match_id,
    INTERNATIONAL_LEAGUE_IDS,
)


class TestInternationalDetection:
    def test_wc_and_qualifiers_are_international(self):
        for lid in (1, 4, 5, 6, 9, 10, 29, 30, 31, 32, 33, 34):
            assert WCPredictor.is_international(lid)

    def test_club_leagues_not_international(self):
        for lid in (39, 140, 135, 78, 61, 88, 94, 203):  # EPL, La Liga, etc.
            assert not WCPredictor.is_international(lid)

    def test_none_not_international(self):
        assert not WCPredictor.is_international(None)


class TestResponseBuilder:
    """build_wc_response is pure — no DB needed. Guards the frontend contract."""
    def _fake_result(self):
        return {
            "probabilities": {"home": 0.55, "draw": 0.25, "away": 0.20},
            "prediction": "home",
            "recommended_bet": "home_win",
            "confidence": 0.55,
            "elo_home": 1900.0, "elo_away": 1700.0, "elo_diff": 200.0,
            "note": "test",
        }

    def test_has_all_frontend_keys(self):
        r = build_wc_response(123, "Spain", "Brazil", self._fake_result(), neutral=True)
        assert r["predictions"]["recommended_bet"] == "home_win"
        assert {"home_win", "draw", "away_win"} <= set(r["predictions"])
        assert r["selected_model"] == "wc_elo"
        assert r["models"][0]["id"] == "wc_elo"
        assert r["models"][0]["status"] == "primary"
        assert r["models"][0]["recommended_bet"] == "home_win"
        assert r["final_decision"]["recommended_bet"] == "home_win"

    def test_recommended_bet_matches_argmax(self):
        # The exact bug that corrupted picks before: pick must match argmax(probs)
        r = build_wc_response(1, "A", "B", self._fake_result(), neutral=True)
        probs = r["models"][0]["predictions"]
        argmax = max(probs, key=probs.get)  # 'home'
        canon = {"home": "home_win", "draw": "draw", "away": "away_win"}[argmax]
        assert r["predictions"]["recommended_bet"] == canon

    def test_match_id_preserved(self):
        r = build_wc_response(987654, "X", "Y", self._fake_result(), neutral=False)
        assert r["match_info"]["match_id"] == 987654
        assert r["match_info"]["neutral_venue"] is False


@requires_db
class TestPredictorWithRatings:
    def test_available(self, wc_predictor):
        assert wc_predictor.is_available()
        assert len(wc_predictor.elo.elos) >= 100

    def test_predict_valid_probs(self, wc_predictor):
        # Spain(9)/Argentina(26)? use known ids from squads — look up by name instead
        r = wc_predictor.predict_by_name("Spain", "Argentina", neutral=True)
        assert r is not None
        p = r["probabilities"]
        assert abs(sum(p.values()) - 1.0) < 1e-6
        assert all(0 <= v <= 1 for v in p.values())
        assert r["recommended_bet"] in ("home_win", "draw", "away_win")

    def test_recommended_bet_is_argmax(self, wc_predictor):
        r = wc_predictor.predict_by_name("Brazil", "Germany", neutral=True)
        p = r["probabilities"]
        argmax = max(p, key=p.get)
        canon = {"home": "home_win", "draw": "draw", "away": "away_win"}[argmax]
        assert r["recommended_bet"] == canon

    def test_stronger_team_favored(self, wc_predictor):
        # Spain (elite) should beat a weak side on neutral ground
        r = wc_predictor.predict_by_name("Spain", "New Zealand", neutral=True)
        assert r["probabilities"]["home"] > r["probabilities"]["away"]

    def test_unknown_team_returns_none(self, wc_predictor):
        assert wc_predictor.predict_by_name("Atlantis", "Wakanda") is None

    def test_home_advantage_effect(self, wc_predictor):
        home = wc_predictor.predict_by_name("Mexico", "Croatia", neutral=False)
        neutral = wc_predictor.predict_by_name("Mexico", "Croatia", neutral=True)
        assert home["probabilities"]["home"] > neutral["probabilities"]["home"]


@requires_db
class TestMatchIdRouting:
    def test_seeded_wc_fixture_routes(self, db):
        cur = db.cursor()
        cur.execute("SELECT match_id FROM fixtures WHERE league_id=1 AND season=2026 LIMIT 1")
        row = cur.fetchone()
        if not row:
            pytest.skip("no WC fixtures seeded")
        resp = route_wc_by_match_id(row[0])
        assert resp is not None
        assert resp["selected_model"] == "wc_elo"
        assert resp["predictions"]["recommended_bet"] in ("home_win", "draw", "away_win")

    def test_nonexistent_match_returns_none(self):
        assert route_wc_by_match_id(99999999) is None
