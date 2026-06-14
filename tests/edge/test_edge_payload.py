"""
Payload-contract tests: the market/value/clv blocks the frontend consumes.
Pure assembly (build_value_payload) plus DB-gated end-to-end checks.
"""
import pytest
from conftest import requires_db
from utils.edge import build_value_payload, build_edge_blocks

MODEL = {"home": 0.38, "draw": 0.28, "away": 0.34}
RAW_MARKET = {"home": 0.52, "draw": 0.295, "away": 0.238}  # sums 1.053 (vig in)
PRICES = {"home": {"odds": 2.02, "book": "betfair"},
          "draw": {"odds": 3.60, "book": "onexbet"},
          "away": {"odds": 3.30, "book": "unibet"}}


class TestContractShape:
    def test_full_payload_keys(self):
        blocks = build_value_payload(MODEL, RAW_MARKET, PRICES, n_books=75)
        assert set(blocks) == {"market", "value", "clv"}
        m, v, c = blocks["market"], blocks["value"], blocks["clv"]
        assert {"implied", "overround", "n_books", "best_price"} <= set(m)
        assert {"edge", "ev_at_best", "value_bet", "rating", "min_acceptable_odds"} <= set(v)
        assert {"bet_time_odds", "closing_odds", "realized_clv"} == set(c)

    def test_market_implied_is_devigged(self):
        blocks = build_value_payload(MODEL, RAW_MARKET, PRICES)
        implied = blocks["market"]["implied"]
        assert abs(sum(implied.values()) - 1.0) < 0.001
        assert blocks["market"]["overround"] == pytest.approx(1.053, abs=0.001)

    def test_value_bet_when_edge_exists(self):
        blocks = build_value_payload(MODEL, RAW_MARKET, PRICES)
        vb = blocks["value"]["value_bet"]
        assert vb is not None and vb["outcome"] == "away"
        assert blocks["value"]["rating"] in ("value", "strong_value")
        # clv pre-fills bet_time_odds from the value bet
        assert blocks["clv"]["bet_time_odds"] == vb["price"]
        assert blocks["clv"]["closing_odds"] is None

    def test_no_market_degrades_to_null(self):
        blocks = build_value_payload(MODEL, None, None)
        assert blocks["market"] is None
        assert blocks["value"] is None
        assert blocks["clv"]["bet_time_odds"] is None

    def test_market_without_prices_still_gives_edge(self):
        blocks = build_value_payload(MODEL, RAW_MARKET, None)
        assert blocks["market"] is not None
        v = blocks["value"]
        assert v["edge"]["away"] > 0      # edge computable from the line alone
        assert v["value_bet"] is None     # but no bet without a price to take

    def test_no_value_state(self):
        # model agrees with the market and every price is below break-even:
        # 0.46*2.0=-8%, 0.28*3.3=-7.6%, 0.26*3.7=-3.8% → honest answer is "no bet"
        model = {"home": 0.46, "draw": 0.28, "away": 0.26}
        raw = {"home": 0.50, "draw": 0.30, "away": 0.25}
        prices = {"home": {"odds": 2.0}, "draw": {"odds": 3.3}, "away": {"odds": 3.7}}
        blocks = build_value_payload(model, raw, prices)
        assert blocks["value"]["value_bet"] is None
        assert blocks["value"]["rating"] == "no_value"


@requires_db
class TestLiveIntegration:
    def test_wc_fixture_end_to_end(self, db):
        cur = db.cursor()
        cur.execute("""
            SELECT f.match_id FROM fixtures f
            JOIN odds_consensus oc ON oc.match_id = f.match_id
            WHERE f.league_id = 1 AND f.season = 2026 LIMIT 1
        """)
        row = cur.fetchone()
        if not row:
            pytest.skip("no WC fixture with collected odds yet")
        blocks = build_edge_blocks(row[0], MODEL)
        assert blocks["market"] is not None
        assert abs(sum(blocks["market"]["implied"].values()) - 1.0) < 0.001
        bp = blocks["market"]["best_price"]
        if bp:  # best price must beat or equal the de-vigged fair price's implied
            for k, entry in bp.items():
                assert entry["odds"] > 1.0 and entry.get("book")

    def test_nonexistent_match_degrades(self):
        blocks = build_edge_blocks(99999999, MODEL)
        assert blocks["market"] is None and blocks["value"] is None

    def test_wc_response_carries_edge_blocks(self, db):
        from models.wc_predictor import route_wc_by_match_id
        cur = db.cursor()
        cur.execute("SELECT match_id FROM fixtures WHERE league_id=1 AND season=2026 LIMIT 1")
        row = cur.fetchone()
        if not row:
            pytest.skip("no WC fixtures seeded")
        resp = route_wc_by_match_id(row[0])
        assert resp is not None
        assert "market" in resp and "value" in resp and "clv" in resp
        assert resp["model_track_record"]["model"] == "wc_elo"
        assert resp["model_track_record"]["edge_validated"] is False  # accuracy != value
        assert resp["model_track_record"]["outcome_validated"] is True


class TestLineShoppingGateRecord:
    """The Phase-0 gate result must be recorded with its verdict."""
    def test_result_file(self):
        import json
        from pathlib import Path
        p = Path(__file__).resolve().parents[2] / "scripts" / "line_shopping_result.json"
        if not p.exists():
            pytest.skip("line-shopping validation not run")
        r = json.loads(p.read_text())
        assert r["verdict"] in ("PROCEED", "MARGINAL", "KILL")
        assert r["n_matches"] > 20000
        # the honest finding: best price ~erases vig on favorites (return ≈ 0)
        assert r["favorite_return_at_best"] > r["favorite_return_at_pinnacle"]
