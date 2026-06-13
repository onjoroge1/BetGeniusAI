"""
Multisport endpoint assembly tests (Phase B) — exercises the exact pure
helpers the routes call, with route-shaped inputs. No FastAPI needed.
"""
import pytest
from utils.edge import get_model_track_record, multisport_model_id
from utils.multisport_edge import (
    best_prices_from_books, build_multisport_edge_blocks,
    edge_analysis_for_result, summarize_edge_metrics,
)


CONS = {"home_odds": 1.87, "away_odds": 2.02, "home_prob": 0.535,
        "away_prob": 0.495, "n_bookmakers": 12, "overround": 1.03}
BOOKS = {
    "draftkings": {"home": 1.87, "away": 2.00, "total_line": 224.5},
    "fanduel": {"home": 1.91, "away": 1.98},
    "betmgm": {"home": 1.85, "away": 2.05},
}
MODEL = {"home_win": 0.565, "away_win": 0.435, "pick": "H", "confidence": 0.565}


class TestBestPrices:
    def test_max_across_books(self):
        bp = best_prices_from_books(BOOKS)
        assert bp["home"] == {"odds": 1.91, "book": "fanduel"}
        assert bp["away"] == {"odds": 2.05, "book": "betmgm"}

    def test_empty_and_junk(self):
        assert best_prices_from_books({}) is None
        assert best_prices_from_books({"x": {"home": None, "away": 1.0}}) is None


class TestGameBlocks:
    def test_full_assembly_contract(self):
        b = build_multisport_edge_blocks(CONS, BOOKS, MODEL, "basketball_nba")
        assert set(b) == {"market", "value", "clv", "model_track_record"}
        assert "draw" not in b["market"]["implied"]
        assert abs(sum(b["market"]["implied"].values()) - 1.0) < 1e-3
        assert b["market"]["n_books"] == 12

    def test_value_bet_is_argmax_positive_ev(self):
        b = build_multisport_edge_blocks(CONS, BOOKS, MODEL, "basketball_nba")
        vb = b["value"]["value_bet"]
        assert vb["bet"] == "home_win"      # model 56.5% vs market ~52%
        assert vb["ev"] > 0
        assert vb["min_acceptable_odds"] == pytest.approx(1 / 0.565, abs=0.01)

    def test_no_model_returns_none(self):
        assert build_multisport_edge_blocks(CONS, BOOKS, None, "basketball_nba") is None
        assert build_multisport_edge_blocks(CONS, BOOKS, {"home_win": None}, "x") is None

    def test_missing_consensus_degrades_nullable(self):
        b = build_multisport_edge_blocks(None, BOOKS, MODEL, "basketball_nba")
        assert b["market"] is None and b["value"] is None
        assert b["model_track_record"]["model"] == "v3_multisport_basketball"

    def test_honesty_registry_never_validated(self):
        # NO multisport model may claim validated edge until its holdout passes
        for sk in ("basketball_nba", "icehockey_nhl", "baseball_mlb", "americanfootball_nfl"):
            tr = get_model_track_record(multisport_model_id(sk))
            assert tr["edge_validated"] is False, f"{sk} must not claim edge"


class TestSportKeyMapping:
    def test_known_prefixes(self):
        assert multisport_model_id("basketball_nba") == "v3_multisport_basketball"
        assert multisport_model_id("icehockey_nhl") == "v3_multisport_hockey"
        assert multisport_model_id("baseball_mlb") == "v3_multisport_baseball"
        assert multisport_model_id("americanfootball_nfl") == "v3_multisport_football"

    def test_unknown_defaults_safely(self):
        assert multisport_model_id("cricket_ipl").startswith("v3_multisport")
        assert multisport_model_id(None).startswith("v3_multisport")


class TestEdgeAnalysis:
    def test_winning_pick(self):
        ea = edge_analysis_for_result(MODEL, CONS, "H")
        assert ea["won"] is True
        assert ea["realized_return_1u"] == pytest.approx(0.87, abs=1e-6)
        assert ea["disagreed_with_market"] is False  # both favored home

    def test_losing_disagreement(self):
        away_model = {"pick": "A", "home_win": 0.40, "away_win": 0.60}
        ea = edge_analysis_for_result(away_model, CONS, "H")
        assert ea["won"] is False
        assert ea["realized_return_1u"] == -1.0
        assert ea["disagreed_with_market"] is True

    def test_guards(self):
        assert edge_analysis_for_result(None, CONS, "H") is None
        assert edge_analysis_for_result(MODEL, {}, "H") is None
        assert edge_analysis_for_result(MODEL, CONS, "D") is None  # no draws in 2-way


class TestSummary:
    def test_aggregates(self):
        rows = [
            edge_analysis_for_result(MODEL, CONS, "H"),                                   # win, agree
            edge_analysis_for_result({"pick": "A", "home_win": 0.4, "away_win": 0.6}, CONS, "H"),  # loss, disagree
            edge_analysis_for_result({"pick": "A", "home_win": 0.4, "away_win": 0.6}, CONS, "A"),  # win, disagree
        ]
        s = summarize_edge_metrics(rows)
        assert s["n_games"] == 3
        assert s["disagreements"] == 2
        assert s["disagreement_hit_rate"] == pytest.approx(0.5)
        # 0.87 - 1.0 + 1.02 = 0.89
        assert s["total_return_1u_at_consensus"] == pytest.approx(0.89, abs=0.01)

    def test_empty_returns_none(self):
        assert summarize_edge_metrics([]) is None
        assert summarize_edge_metrics([None, None]) is None
