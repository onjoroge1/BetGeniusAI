"""
Two-way (no-draw) outcome-set tests — the Phase A generalization for US sports.
Contract rule under test: a 2-way payload must NEVER contain a 'draw' key.
"""
import pytest
from utils.edge import (
    OUTCOMES_2WAY, OUTCOMES_3WAY, build_value_payload, compute_edge,
    devig_proportional, implied_probs_from_odds, parlay_metrics,
    select_value_bet,
)


class TestTwoWayDevig:
    def test_devig_sums_to_one_no_draw(self):
        fair = devig_proportional({"home": 0.55, "away": 0.50}, OUTCOMES_2WAY)
        assert abs(sum(fair.values()) - 1.0) < 1e-9
        assert set(fair) == {"home", "away"}

    def test_devig_ignores_extraneous_draw_key(self):
        # defensive: a stray draw value must not leak into a 2-way devig
        fair = devig_proportional({"home": 0.55, "away": 0.50, "draw": 0.20},
                                  OUTCOMES_2WAY)
        assert "draw" not in fair
        assert abs(sum(fair.values()) - 1.0) < 1e-9

    def test_implied_from_odds_two_way(self):
        raw = implied_probs_from_odds({"home": 1.91, "away": 2.00}, OUTCOMES_2WAY)
        assert set(raw) == {"home", "away"}
        assert raw["home"] == pytest.approx(1 / 1.91)

    def test_missing_outcome_raises(self):
        with pytest.raises(ValueError):
            implied_probs_from_odds({"home": 1.91}, OUTCOMES_2WAY)


class TestTwoWayEdgeAndValue:
    def test_edge_keys(self):
        e = compute_edge({"home": 0.56, "away": 0.44},
                         {"home": 0.52, "away": 0.48}, OUTCOMES_2WAY)
        assert set(e) == {"home", "away"}
        assert e["home"] == pytest.approx(0.04)

    def test_select_value_bet_two_way_canonical(self):
        vb = select_value_bet({"home": 0.56, "away": 0.44},
                              {"home": {"odds": 1.95, "book": "dk"},
                               "away": {"odds": 2.10, "book": "fd"}},
                              OUTCOMES_2WAY)
        assert vb is not None
        assert vb["bet"] in ("home_win", "away_win")

    def test_no_value_returns_none(self):
        vb = select_value_bet({"home": 0.50, "away": 0.50},
                              {"home": {"odds": 1.85}, "away": {"odds": 1.85}},
                              OUTCOMES_2WAY)
        assert vb is None  # both EV negative → honest no-bet


class TestTwoWayPayload:
    def _payload(self):
        return build_value_payload(
            {"home": 0.565, "away": 0.435},
            {"home": 0.535, "away": 0.495},     # raw, vig-in (sums 1.03)
            {"home": {"odds": 1.91, "book": "fanduel"},
             "away": {"odds": 2.05, "book": "betmgm"}},
            n_books=12, outcomes=OUTCOMES_2WAY,
        )

    def test_no_draw_anywhere(self):
        p = self._payload()
        assert "draw" not in p["market"]["implied"]
        assert "draw" not in p["value"]["edge"]
        assert "draw" not in p["value"]["min_acceptable_odds"]

    def test_market_implied_normalized(self):
        p = self._payload()
        assert abs(sum(p["market"]["implied"].values()) - 1.0) < 1e-3
        assert p["market"]["overround"] == pytest.approx(1.03, abs=1e-6)

    def test_clv_bet_time_odds_tracks_value_bet(self):
        p = self._payload()
        vb = p["value"]["value_bet"]
        if vb:
            assert p["clv"]["bet_time_odds"] == vb["price"]

    def test_missing_market_degrades_nullable(self):
        p = build_value_payload({"home": 0.6, "away": 0.4},
                                None, None, outcomes=OUTCOMES_2WAY)
        assert p["market"] is None and p["value"] is None
        assert p["clv"]["realized_clv"] is None

    def test_three_way_default_unchanged(self):
        # regression: default callers (soccer) still get 3-way behavior
        p = build_value_payload({"home": 0.5, "draw": 0.27, "away": 0.23},
                                {"home": 0.50, "draw": 0.28, "away": 0.27})
        assert set(p["market"]["implied"]) == set(OUTCOMES_3WAY)


class TestTwoWayParlay:
    def test_parlay_legs_are_outcome_agnostic(self):
        legs = [{"p": 0.56, "odds": 1.95}, {"p": 0.60, "odds": 1.80}]
        m = parlay_metrics(legs)
        assert m["eligible"]
        # engine rounds ev to 4dp, so compare at 4dp tolerance
        assert m["ev"] == pytest.approx((0.56 * 1.95) * (0.60 * 1.80) - 1, abs=1e-3)

    def test_negative_leg_poisons_two_way_parlay(self):
        legs = [{"p": 0.56, "odds": 1.95}, {"p": 0.45, "odds": 1.90}]  # 2nd is -EV
        m = parlay_metrics(legs)
        assert not m["eligible"]
        assert m["kelly_quarter"] == 0.0
