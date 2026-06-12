"""
Pure-math tests for utils/edge.py — no DB, no I/O.
These encode the betting math the product's claims rest on.
"""
import pytest
from utils.edge import (
    devig_proportional, implied_probs_from_odds, compute_edge, ev_at_price,
    min_acceptable_odds, kelly_fraction, value_rating, select_value_bet,
    parlay_metrics, build_value_payload, compute_realized_clv,
    get_model_track_record, MODEL_REGISTRY,
)


class TestDevig:
    def test_removes_vig(self):
        raw = {"home": 0.55, "draw": 0.28, "away": 0.22}  # sums to 1.05
        fair = devig_proportional(raw)
        assert abs(sum(fair.values()) - 1.0) < 1e-9

    def test_proportions_preserved(self):
        raw = {"home": 0.50, "draw": 0.30, "away": 0.25}
        fair = devig_proportional(raw)
        assert abs(fair["home"] / fair["draw"] - 0.50 / 0.30) < 1e-9

    def test_already_fair_unchanged(self):
        raw = {"home": 0.5, "draw": 0.3, "away": 0.2}
        fair = devig_proportional(raw)
        assert abs(fair["home"] - 0.5) < 1e-9

    def test_rejects_zero(self):
        with pytest.raises(ValueError):
            devig_proportional({"home": 0, "draw": 0, "away": 0})

    def test_real_consensus_shape(self):
        # actual odds_consensus rows sum to ~1.05 (vig in) — must normalize
        raw = {"home": 0.5988, "draw": 0.2667, "away": 0.1818}
        fair = devig_proportional(raw)
        assert abs(sum(fair.values()) - 1.0) < 1e-9
        assert fair["home"] < raw["home"]  # de-vig shrinks each prob


class TestImpliedFromOdds:
    def test_basic(self):
        probs = implied_probs_from_odds({"home": 2.0, "draw": 4.0, "away": 5.0})
        assert abs(probs["home"] - 0.5) < 1e-9

    def test_rejects_invalid_odds(self):
        with pytest.raises(ValueError):
            implied_probs_from_odds({"home": 1.0, "draw": 4.0, "away": 5.0})


class TestEdgeAndEV:
    def test_edge_sign(self):
        model = {"home": 0.40, "draw": 0.28, "away": 0.32}
        market = {"home": 0.49, "draw": 0.27, "away": 0.24}
        edge = compute_edge(model, market)
        assert edge["home"] < 0 and edge["away"] > 0

    def test_ev_positive_when_price_overpays(self):
        # p=0.29 at odds 4.20 → EV = +21.8% (the draw example from the design)
        assert abs(ev_at_price(0.29, 4.20) - 0.218) < 1e-9

    def test_ev_negative_favorite_trap(self):
        # 62% probability at 1.50 → -7% (the accuracy-framing trap)
        assert ev_at_price(0.62, 1.50) < 0

    def test_min_acceptable_odds_is_breakeven(self):
        p = 0.4
        mo = min_acceptable_odds(p)
        assert abs(ev_at_price(p, mo)) < 0.01  # ~breakeven at the floor
        assert ev_at_price(p, mo + 0.2) > 0    # value above it


class TestKelly:
    def test_known_value(self):
        # p=0.55 @ 2.00: f* = (1.10-1)/(1) = 0.10
        assert abs(kelly_fraction(0.55, 2.0) - 0.10) < 1e-9

    def test_zero_when_no_edge(self):
        assert kelly_fraction(0.45, 2.0) == 0.0

    def test_never_negative(self):
        assert kelly_fraction(0.10, 1.50) == 0.0


class TestValueRating:
    @pytest.mark.parametrize("ev,expected", [
        (None, "no_value"), (-0.05, "no_value"), (0.0, "no_value"),
        (0.01, "marginal"), (0.05, "value"), (0.10, "strong_value"),
    ])
    def test_tiers(self, ev, expected):
        assert value_rating(ev) == expected


class TestSelectValueBet:
    MODEL = {"home": 0.38, "draw": 0.28, "away": 0.34}

    def test_picks_highest_ev(self):
        prices = {"home": {"odds": 2.02, "book": "a"},
                  "draw": {"odds": 3.60, "book": "b"},
                  "away": {"odds": 4.50, "book": "c"}}
        vb = select_value_bet(self.MODEL, prices)
        assert vb["outcome"] == "away"
        assert vb["bet"] == "away_win"           # canonical string (frontend contract)
        assert vb["ev"] > 0
        assert vb["min_acceptable_odds"] == pytest.approx(1 / 0.34, abs=0.01)
        assert vb["kelly_quarter"] == pytest.approx(vb["kelly_full"] / 4, abs=1e-4)

    def test_no_bet_when_nothing_positive(self):
        # market prices everything tight — no outcome clears EV > 0
        prices = {"home": {"odds": 2.40}, "draw": {"odds": 3.30}, "away": {"odds": 2.70}}
        model = {"home": 0.40, "draw": 0.29, "away": 0.31}
        assert select_value_bet(model, prices) is None  # "no bet" is first-class

    def test_missing_prices_skipped(self):
        vb = select_value_bet(self.MODEL, {"away": {"odds": 4.50, "book": "c"}})
        assert vb["outcome"] == "away"


class TestParlay:
    def test_edges_compound(self):
        # The worked example: +10% and +12% legs → +23.2% parlay
        legs = [{"p": 0.55, "odds": 2.00}, {"p": 0.40, "odds": 2.80}]
        m = parlay_metrics(legs)
        assert m["eligible"]
        assert m["ev"] == pytest.approx(1.10 * 1.12 - 1, abs=1e-3)

    def test_poison_leg_rule(self):
        # one -EV leg makes the parlay ineligible even if total EV looks ok
        legs = [{"p": 0.55, "odds": 2.00}, {"p": 0.65, "odds": 1.40}]  # 2nd leg EV -9%
        m = parlay_metrics(legs)
        assert not m["eligible"]
        assert m["kelly_quarter"] == 0.0
        assert m["rating"] == "no_value"

    def test_negative_legs_compound_losses(self):
        # two -9% favorites → ~-17% parlay (the current generator's failure mode)
        legs = [{"p": 0.65, "odds": 1.40}, {"p": 0.65, "odds": 1.40}]
        m = parlay_metrics(legs)
        assert m["ev"] == pytest.approx(0.91 * 0.91 - 1, abs=1e-3)
        assert not m["eligible"]

    def test_joint_prob_override_for_sgp(self):
        legs = [{"p": 0.50, "odds": 2.20}, {"p": 0.50, "odds": 2.20}]
        independent = parlay_metrics(legs)
        correlated = parlay_metrics(legs, joint_prob=0.35)  # positively correlated
        assert correlated["fair_prob"] > independent["fair_prob"]
        assert correlated["ev"] > independent["ev"]

    def test_rejects_bad_leg(self):
        with pytest.raises(ValueError):
            parlay_metrics([{"p": 1.5, "odds": 2.0}])

    def test_rejects_empty(self):
        with pytest.raises(ValueError):
            parlay_metrics([])


class TestRealizedCLV:
    def test_beat_the_close(self):
        assert compute_realized_clv(4.50, 4.10) == pytest.approx(0.0976, abs=1e-4)

    def test_lost_to_close(self):
        assert compute_realized_clv(2.00, 2.20) < 0

    def test_rejects_invalid(self):
        with pytest.raises(ValueError):
            compute_realized_clv(2.0, 0.0)


class TestModelRegistry:
    def test_v3_not_edge_validated(self):
        # The honesty rule: v3_sharp failed its holdout and must say so
        tr = get_model_track_record("v3_sharp")
        assert tr["edge_validated"] is False

    def test_wc_elo_validated(self):
        tr = get_model_track_record("wc_elo")
        assert tr["edge_validated"] is True
        assert tr["segment"] == "thin_market"

    def test_unknown_model_defaults_unvalidated(self):
        tr = get_model_track_record("mystery_model")
        assert tr["edge_validated"] is False

    def test_clv_fields_present_but_null_until_loop_wired(self):
        tr = get_model_track_record("wc_elo")
        assert "median_clv_90d" in tr and tr["median_clv_90d"] is None
        assert "n_settled" in tr and tr["n_settled"] is None
