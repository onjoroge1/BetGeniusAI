"""
Backend sanity-layer tests — the guards added after the frontend caught wc_elo
emitting "validated" absurd bets (Spain→Cape Verde @26.0 "+218% EV", Saudi≈Uruguay).

Two protections:
  1. edge_validated means VALUE/CLV-proven, NOT accuracy. wc_elo (accuracy-only)
     must report edge_validated=False, outcome_validated=True.
  2. value_bet selection rejects implausible/inconsistent edges so a miscalibrated
     model can't surface a longshot as "strong_value".
"""
import pytest
from utils.edge import (
    build_value_payload, select_value_bet, get_model_track_record,
    MAX_PLAUSIBLE_EDGE, MAX_PLAUSIBLE_EV, OUTCOMES_3WAY,
)


class TestEdgeValidatedSemantics:
    def test_wc_elo_is_not_edge_validated(self):
        tr = get_model_track_record("wc_elo")
        assert tr["edge_validated"] is False        # accuracy != value
        assert tr["outcome_validated"] is True       # but it did pass accuracy

    def test_unvalidated_models_false(self):
        for m in ("v3_sharp", "v3_multisport_basketball", "live_edge_over05"):
            assert get_model_track_record(m)["edge_validated"] is False


class TestPlausibilityGuards:
    def _prices(self, **kw):
        return {k: {"odds": v, "book": "x"} for k, v in kw.items()}

    def test_longshot_below_market_suppressed(self):
        # model 12% on away, market(de-vig) higher → +EV only from 26.0 longshot.
        # This is the Spain-Cape Verde case: must NOT become a value bet.
        model = {"home": 0.80, "draw": 0.08, "away": 0.12}
        fair = {"home": 0.86, "draw": 0.095, "away": 0.045}
        vb = select_value_bet(model, self._prices(away=26.0), OUTCOMES_3WAY, market_fair=fair)
        assert vb is None

    def test_implausible_edge_suppressed(self):
        # model 35pp above market = miscalibration, not edge (Saudi≈Uruguay)
        model = {"home": 0.55, "draw": 0.25, "away": 0.20}
        fair = {"home": 0.13, "draw": 0.22, "away": 0.65}
        vb = select_value_bet(model, self._prices(home=8.5), OUTCOMES_3WAY, market_fair=fair)
        assert vb is None

    def test_implausible_ev_suppressed(self):
        # even a small positive edge at an absurd price → EV cap kicks in
        model = {"home": 0.30, "draw": 0.30, "away": 0.40}
        fair = {"home": 0.28, "draw": 0.30, "away": 0.42}
        vb = select_value_bet(model, self._prices(home=20.0), OUTCOMES_3WAY, market_fair=fair)
        assert vb is None  # EV = 0.30*20-1 = 5.0 >> cap

    def test_legit_edge_preserved(self):
        # a real ~6pp edge at a fair price MUST still surface
        model = {"home": 0.50, "draw": 0.28, "away": 0.22}
        fair = {"home": 0.437, "draw": 0.291, "away": 0.272}
        vb = select_value_bet(model, self._prices(home=2.25, draw=3.4, away=3.9),
                              OUTCOMES_3WAY, market_fair=fair)
        assert vb is not None and vb["bet"] == "home_win"
        assert 0 < vb["ev"] <= MAX_PLAUSIBLE_EV
        assert 0 < vb["edge"] <= MAX_PLAUSIBLE_EDGE

    def test_caps_are_model_aware(self):
        # The silent-product-killer fix: an UNVALIDATED model's big-EV longshot is
        # suppressed, but a CLV-VALIDATED model earns the headroom (thin-market
        # value IS the product). Same inputs, opposite outcome by validation status.
        model = {"home": 0.30, "draw": 0.25, "away": 0.45}
        fair = {"home": 0.28, "draw": 0.27, "away": 0.45}   # away edge ~0 → use home
        prices = self._prices(home=4.6)                      # 0.30*4.6-1 = +0.38 EV
        fair2 = {"home": 0.26, "draw": 0.30, "away": 0.44}   # home edge +4pp (plausible)
        unvalidated = select_value_bet(model, prices, OUTCOMES_3WAY, market_fair=fair2,
                                       edge_validated=False)
        validated = select_value_bet(model, prices, OUTCOMES_3WAY, market_fair=fair2,
                                     edge_validated=True)
        assert unvalidated is None          # 38% EV > unvalidated cap (0.25) → suppressed
        assert validated is not None        # validated model earns the headroom
        assert validated["bet"] == "home_win"

    def test_rating_no_value_when_bet_suppressed(self):
        # the full payload rating must follow the (suppressed) bet, not raw max EV
        b = build_value_payload({"home": 0.80, "draw": 0.08, "away": 0.12},
                                {"home": 0.86, "draw": 0.095, "away": 0.045},
                                {"away": {"odds": 26.0, "book": "x"}})
        assert b["value"]["value_bet"] is None
        assert b["value"]["rating"] == "no_value"
