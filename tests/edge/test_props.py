"""
Player-prop value tests — prop_value() (Phase A) and the offers contract
used by /predict-player, top-picks, and the parlay poison-leg gate (Phase C).
"""
import pytest
from utils.edge import prop_value, value_rating


def _ou_offers():
    """NBA-style O/U offers with line variance across books (the 60% case)."""
    return [
        {"book": "draftkings", "line": 24.5, "side": "over", "odds": 1.87},
        {"book": "draftkings", "line": 24.5, "side": "under", "odds": 1.95},
        {"book": "fanduel", "line": 24.5, "side": "over", "odds": 1.92},
        {"book": "fanduel", "line": 24.5, "side": "under", "odds": 1.90},
        {"book": "betmgm", "line": 25.5, "side": "over", "odds": 2.05},
    ]


class TestPropOverUnder:
    def test_modal_line_selected(self):
        pv = prop_value(0.57, _ou_offers(), side="over")
        assert pv["modal_line"] == 24.5      # 2 books at 24.5 vs 1 at 25.5

    def test_best_price_at_modal_line_only(self):
        pv = prop_value(0.57, _ou_offers(), side="over")
        # 2.05 is higher but at a DIFFERENT line — must not be picked
        assert pv["best_price"]["odds"] == 1.92
        assert pv["best_price"]["book"] == "fanduel"

    def test_alt_lines_listed_without_ev(self):
        pv = prop_value(0.57, _ou_offers(), side="over")
        assert pv["alt_lines"] == [{"line": 25.5, "best_odds": 2.05, "n_books": 1}]
        # no EV key inside alt_lines entries — the modal-line rule
        assert "ev" not in pv["alt_lines"][0]

    def test_devig_pair_produces_edge(self):
        pv = prop_value(0.57, _ou_offers(), side="over")
        assert pv["market_implied_fair"] is not None
        assert pv["edge"] == pytest.approx(0.57 - pv["market_implied_fair"], abs=1e-4)

    def test_ev_math(self):
        pv = prop_value(0.57, _ou_offers(), side="over")
        assert pv["ev_at_best"] == pytest.approx(0.57 * 1.92 - 1, abs=1e-4)

    def test_under_side(self):
        pv = prop_value(0.50, _ou_offers(), side="under")
        assert pv["side"] == "under"
        assert pv["best_price"]["odds"] == 1.95  # dk under at modal 24.5


class TestPropYesOnly:
    """Anytime-scorer markets: a 'yes' price only — no de-vig possible."""
    def _offers(self):
        return [
            {"book": "pinnacle", "line": None, "side": "yes", "odds": 1.80},
            {"book": "fanduel", "line": None, "side": "yes", "odds": 1.87},
            {"book": "betrivers", "line": None, "side": "yes", "odds": 1.709},
        ]

    def test_best_price_and_ev(self):
        pv = prop_value(0.55, self._offers(), side="yes")
        assert pv["best_price"]["odds"] == 1.87
        assert pv["ev_at_best"] == pytest.approx(0.55 * 1.87 - 1, abs=1e-4)

    def test_no_fake_edge_without_pair(self):
        pv = prop_value(0.55, self._offers(), side="yes")
        assert pv["market_implied_fair"] is None
        assert pv["edge"] is None  # honest: cannot de-vig a one-sided market

    def test_modal_line_none_for_lineless_market(self):
        pv = prop_value(0.55, self._offers(), side="yes")
        assert pv["modal_line"] is None
        assert pv["alt_lines"] is None


class TestPropGuards:
    def test_no_offers_returns_none(self):
        assert prop_value(0.40, [], side="yes") is None
        assert prop_value(0.40, _ou_offers(), side="yes") is None  # wrong side

    def test_invalid_probability_raises(self):
        with pytest.raises(ValueError):
            prop_value(0.0, _ou_offers())
        with pytest.raises(ValueError):
            prop_value(1.0, _ou_offers())

    def test_junk_odds_filtered(self):
        offers = [{"book": "x", "line": None, "side": "yes", "odds": 1.0},
                  {"book": "y", "line": None, "side": "yes", "odds": None}]
        assert prop_value(0.4, offers, side="yes") is None

    def test_rating_consistency(self):
        pv = prop_value(0.62, [{"book": "b", "line": None, "side": "yes", "odds": 1.95}],
                        side="yes")
        assert pv["rating"] == value_rating(pv["ev_at_best"])

    def test_kelly_quarter_is_quarter(self):
        pv = prop_value(0.60, [{"book": "b", "line": None, "side": "yes", "odds": 2.00}],
                        side="yes")
        assert pv["kelly_quarter"] == pytest.approx(pv["kelly_full"] / 4.0, abs=1e-4)


class TestOffersContract:
    """get_prop_offers shape → prop_value compatibility (Phase C wiring)."""
    def test_service_offer_shape_feeds_prop_value(self):
        # exact shape produced by models/player_props_service.get_prop_offers
        offers = [{"book": "pinnacle", "line": None, "side": "yes", "odds": 1.8}]
        pv = prop_value(0.5, offers, side="yes")
        assert pv is not None and pv["n_offers"] == 1

    def test_poison_leg_gate_semantics(self):
        # ev_eligible as computed in get_player_props_for_parlay
        good = prop_value(0.60, [{"book": "b", "line": None, "side": "yes", "odds": 2.0}], side="yes")
        bad = prop_value(0.40, [{"book": "b", "line": None, "side": "yes", "odds": 2.0}], side="yes")
        assert (good["ev_at_best"] > 0) is True
        assert (bad["ev_at_best"] > 0) is False
