"""
Comprehensive unit tests for the Auto Parlay System.
Covers: generation flow, settlement correctness, leg result tracking, performance stats.

Run with:  python -m pytest tests/test_auto_parlay_system.py -v
"""
import pytest
from unittest.mock import MagicMock, patch, call
from datetime import datetime, timedelta, timezone


# ---------------------------------------------------------------------------
# HELPERS / FIXTURES
# ---------------------------------------------------------------------------

def _make_match(match_id=1001, home="Arsenal", away="Chelsea",
                ph=0.45, pd=0.28, pa=0.27, hours_ahead=24):
    kickoff = datetime.now(timezone.utc) + timedelta(hours=hours_ahead)
    return {
        "match_id": match_id,
        "home_team": home,
        "away_team": away,
        "home_team_id": 1,
        "away_team_id": 2,
        "league_id": 39,
        "league_name": "Premier League",
        "kickoff_at": kickoff,
        "market_prob": {"H": ph, "D": pd, "A": pa},
        "model_prob": {"H": ph + 0.06, "D": pd, "A": pa - 0.06},
        "odds": {"H": round(1 / ph, 2), "D": round(1 / pd, 2), "A": round(1 / pa, 2)},
    }


def _make_leg(leg_type, market_code, model_prob, market_prob, decimal_odds,
              edge_pct=None, match_id=1001):
    if edge_pct is None:
        edge_pct = round((model_prob - market_prob) * 100, 2)
    return {
        "leg_type": leg_type,
        "match_id": match_id,
        "home_team": "Arsenal",
        "away_team": "Chelsea",
        "league_name": "Premier League",
        "kickoff_at": datetime.now(timezone.utc) + timedelta(hours=24),
        "market_code": market_code,
        "market_name": f"{leg_type}:{market_code}",
        "player_id": None,
        "player_name": None,
        "model_prob": model_prob,
        "market_prob": market_prob,
        "decimal_odds": decimal_odds,
        "edge_pct": edge_pct,
    }


# ---------------------------------------------------------------------------
# UNIT TESTS: _check_leg_result
# ---------------------------------------------------------------------------

class TestCheckLegResult:
    """Tests for the per-leg outcome checker used during settlement."""

    @pytest.fixture
    def gen(self):
        from models.automated_parlay_generator import AutomatedParlayGenerator
        with patch("models.automated_parlay_generator.create_engine"), \
             patch("models.automated_parlay_generator.sessionmaker"):
            g = AutomatedParlayGenerator.__new__(AutomatedParlayGenerator)
            g.engine = MagicMock()
            g.Session = MagicMock()
            g.v2_predictor = None
            g.totals_predictor = None
            g.player_props = None
            return g

    # Match result -----------------------------------------------------------
    def test_home_win_correctly_detected(self, gen):
        assert gen._check_leg_result("match_result", "H", None, 2, 1, "H") is True

    def test_home_win_fails_on_draw(self, gen):
        assert gen._check_leg_result("match_result", "H", None, 1, 1, "D") is False

    def test_home_win_fails_on_away_win(self, gen):
        assert gen._check_leg_result("match_result", "H", None, 0, 1, "A") is False

    def test_draw_correctly_detected(self, gen):
        assert gen._check_leg_result("match_result", "D", None, 1, 1, "D") is True

    def test_draw_fails_on_home_win(self, gen):
        assert gen._check_leg_result("match_result", "D", None, 2, 0, "H") is False

    def test_away_win_correctly_detected(self, gen):
        assert gen._check_leg_result("match_result", "A", None, 0, 2, "A") is True

    def test_away_win_fails_on_home_win(self, gen):
        assert gen._check_leg_result("match_result", "A", None, 3, 1, "H") is False

    # Totals -----------------------------------------------------------------
    def test_over_2_5_with_3_goals(self, gen):
        assert gen._check_leg_result("totals", "over_2.5", None, 2, 1, "H") is True

    def test_over_2_5_with_exactly_2_goals(self, gen):
        assert gen._check_leg_result("totals", "over_2.5", None, 1, 1, "D") is False

    def test_under_2_5_with_2_goals(self, gen):
        assert gen._check_leg_result("totals", "under_2.5", None, 1, 1, "D") is True

    def test_under_2_5_with_3_goals(self, gen):
        assert gen._check_leg_result("totals", "under_2.5", None, 2, 1, "H") is False

    def test_under_1_5_with_1_goal(self, gen):
        assert gen._check_leg_result("totals", "under_1.5", None, 0, 1, "A") is True

    def test_under_1_5_with_2_goals(self, gen):
        assert gen._check_leg_result("totals", "under_1.5", None, 1, 1, "D") is False

    def test_over_0_5_zero_goals(self, gen):
        assert gen._check_leg_result("totals", "over_0.5", None, 0, 0, "D") is False

    def test_over_0_5_with_goal(self, gen):
        assert gen._check_leg_result("totals", "over_0.5", None, 1, 0, "H") is True

    # Edge cases -------------------------------------------------------------
    def test_unknown_leg_type_returns_false(self, gen):
        assert gen._check_leg_result("unknown_type", "X", None, 1, 1, "D") is False

    def test_none_scores_treated_as_zero(self, gen):
        assert gen._check_leg_result("totals", "under_0.5", None, None, None, "D") is True


# ---------------------------------------------------------------------------
# UNIT TESTS: _build_parlay  (edge / probability math)
# ---------------------------------------------------------------------------

class TestBuildParlay:
    """Tests for parlay construction — combined odds, edge, confidence tier."""

    @pytest.fixture
    def gen(self):
        from models.automated_parlay_generator import AutomatedParlayGenerator
        with patch("models.automated_parlay_generator.create_engine"), \
             patch("models.automated_parlay_generator.sessionmaker"):
            g = AutomatedParlayGenerator.__new__(AutomatedParlayGenerator)
            g.engine = MagicMock()
            g.Session = MagicMock()
            g.v2_predictor = None
            g.totals_predictor = None
            g.player_props = None
            return g

    def test_combined_odds_product(self, gen):
        legs = [
            _make_leg("match_result", "H", 0.51, 0.45, 2.22),
            _make_leg("totals", "under_2.5", 0.55, 0.48, 2.08),
        ]
        match = _make_match()
        parlay = gen._build_parlay(legs, match)
        assert parlay is not None
        expected_raw = round(2.22 * 2.08, 2)
        assert abs(parlay["combined_odds"] - expected_raw) < 0.5

    def test_edge_positive_when_model_beats_market(self, gen):
        legs = [
            _make_leg("match_result", "H", 0.55, 0.45, 2.22, edge_pct=10.0),
            _make_leg("totals", "under_2.5", 0.60, 0.48, 2.08, edge_pct=12.0),
        ]
        match = _make_match()
        parlay = gen._build_parlay(legs, match)
        assert parlay is not None
        assert parlay["edge_pct"] > 0

    def test_parlay_has_2_legs(self, gen):
        legs = [
            _make_leg("match_result", "H", 0.51, 0.45, 2.22),
            _make_leg("totals", "under_2.5", 0.55, 0.48, 2.08),
        ]
        match = _make_match()
        parlay = gen._build_parlay(legs, match)
        assert parlay is not None
        assert parlay["leg_count"] == 2

    def test_parlay_hash_is_deterministic(self, gen):
        legs = [
            _make_leg("match_result", "H", 0.51, 0.45, 2.22),
            _make_leg("totals", "under_2.5", 0.55, 0.48, 2.08),
        ]
        match = _make_match()
        p1 = gen._build_parlay(legs, match)
        p2 = gen._build_parlay(legs, match)
        assert p1["parlay_hash"] == p2["parlay_hash"]

    def test_payout_100_calculation(self, gen):
        legs = [
            _make_leg("match_result", "H", 0.51, 0.45, 2.0),
            _make_leg("totals", "under_2.5", 0.55, 0.48, 2.0),
        ]
        match = _make_match()
        parlay = gen._build_parlay(legs, match)
        assert parlay is not None
        assert abs(parlay["payout_100"] - 400.0) < 50

    def test_confidence_tier_assigned(self, gen):
        legs = [
            _make_leg("match_result", "H", 0.60, 0.45, 2.22, edge_pct=15.0),
            _make_leg("totals", "under_2.5", 0.65, 0.48, 2.08, edge_pct=17.0),
        ]
        match = _make_match()
        parlay = gen._build_parlay(legs, match)
        assert parlay is not None
        assert parlay["confidence_tier"] in ("high", "medium", "low")


# ---------------------------------------------------------------------------
# UNIT TESTS: generate_parlays_for_match (integration of flow)
# ---------------------------------------------------------------------------

class TestGenerationFlow:
    """Tests for the full generation flow with mocked DB and predictors."""

    @pytest.fixture
    def gen_with_mock(self):
        from models.automated_parlay_generator import AutomatedParlayGenerator
        with patch("models.automated_parlay_generator.create_engine"), \
             patch("models.automated_parlay_generator.sessionmaker"):
            g = AutomatedParlayGenerator.__new__(AutomatedParlayGenerator)
            g.engine = MagicMock()
            g.Session = MagicMock()
            g.v2_predictor = None
            g.totals_predictor = None
            g.player_props = None
            return g

    def test_returns_zero_when_insufficient_legs(self, gen_with_mock):
        gen_with_mock._get_match_info = MagicMock(return_value=_make_match())
        gen_with_mock._extract_all_legs = MagicMock(return_value=[
            _make_leg("match_result", "H", 0.51, 0.45, 2.22)
        ])
        result = gen_with_mock.generate_parlays_for_match(1001)
        assert result["parlays_generated"] == 0

    def test_generates_only_2_leg_parlays(self, gen_with_mock):
        """
        Given 4 candidate legs, the system should only emit 2-leg combos.
        Combos: C(4,2) = 6 possible. All passing edge filter → 6 parlays.
        """
        legs = [
            _make_leg("match_result", "H", 0.55, 0.45, 2.22, edge_pct=10.0),
            _make_leg("match_result", "A", 0.35, 0.27, 3.70, edge_pct=8.0),
            _make_leg("totals", "over_2.5", 0.58, 0.50, 2.00, edge_pct=8.0),
            _make_leg("totals", "under_2.5", 0.55, 0.48, 2.08, edge_pct=7.0),
        ]
        gen_with_mock._get_match_info = MagicMock(return_value=_make_match())
        gen_with_mock._extract_all_legs = MagicMock(return_value=legs)
        gen_with_mock._save_parlay = MagicMock(return_value=True)

        result = gen_with_mock.generate_parlays_for_match(1001)

        saved_parlays = gen_with_mock._save_parlay.call_args_list
        for save_call in saved_parlays:
            parlay_arg = save_call[0][0]
            assert parlay_arg["leg_count"] == 2, "Only 2-leg parlays should be generated"

    def test_edge_filter_rejects_below_minimum(self, gen_with_mock):
        legs = [
            _make_leg("match_result", "H", 0.46, 0.45, 2.22, edge_pct=1.0),
            _make_leg("totals", "under_2.5", 0.49, 0.48, 2.08, edge_pct=1.0),
        ]
        gen_with_mock._get_match_info = MagicMock(return_value=_make_match())
        gen_with_mock._extract_all_legs = MagicMock(return_value=legs)
        gen_with_mock._save_parlay = MagicMock(return_value=True)

        result = gen_with_mock.generate_parlays_for_match(1001)
        assert gen_with_mock._save_parlay.call_count == 0

    def test_edge_filter_rejects_above_maximum(self, gen_with_mock):
        legs = [
            _make_leg("match_result", "H", 0.75, 0.45, 2.22, edge_pct=30.0),
            _make_leg("totals", "under_2.5", 0.80, 0.48, 2.08, edge_pct=32.0),
        ]
        gen_with_mock._get_match_info = MagicMock(return_value=_make_match())
        gen_with_mock._extract_all_legs = MagicMock(return_value=legs)
        gen_with_mock._save_parlay = MagicMock(return_value=True)

        result = gen_with_mock.generate_parlays_for_match(1001)
        assert gen_with_mock._save_parlay.call_count == 0

    def test_duplicate_parlay_not_saved_twice(self, gen_with_mock):
        legs = [
            _make_leg("match_result", "H", 0.55, 0.45, 2.22, edge_pct=10.0),
            _make_leg("totals", "under_2.5", 0.55, 0.48, 2.08, edge_pct=7.0),
        ]
        gen_with_mock._get_match_info = MagicMock(return_value=_make_match())
        gen_with_mock._extract_all_legs = MagicMock(return_value=legs)
        gen_with_mock._save_parlay = MagicMock(return_value=False)

        result = gen_with_mock.generate_parlays_for_match(1001)
        assert result["parlays_generated"] == 0

    def test_returns_zero_when_match_not_found(self, gen_with_mock):
        gen_with_mock._get_match_info = MagicMock(return_value=None)
        result = gen_with_mock.generate_parlays_for_match(9999)
        assert "error" in result
        assert result["parlays_generated"] == 0


# ---------------------------------------------------------------------------
# UNIT TESTS: settle_parlays (settlement + leg result tracking)
# ---------------------------------------------------------------------------

class TestSettlement:
    """Tests for the settlement logic including per-leg result tracking."""

    @pytest.fixture
    def gen(self):
        from models.automated_parlay_generator import AutomatedParlayGenerator
        with patch("models.automated_parlay_generator.create_engine"), \
             patch("models.automated_parlay_generator.sessionmaker"):
            g = AutomatedParlayGenerator.__new__(AutomatedParlayGenerator)
            g.engine = MagicMock()
            g.Session = MagicMock()
            g.v2_predictor = None
            g.totals_predictor = None
            g.player_props = None
            return g

    def _make_session_with_parlay(self, gen, parlay_id, parlay_hash, payout,
                                  legs_data, settle_error=False):
        """
        Return a mocked session that yields one parlay needing settlement
        and the described leg rows.
        """
        mock_session = MagicMock()
        gen.Session.return_value = mock_session
        gen._update_performance_summary = MagicMock()

        parlay_row = MagicMock()
        parlay_row.__getitem__ = lambda self, i: [parlay_id, parlay_hash, payout][i]

        class LegRow:
            def __init__(self, leg_index, leg_type, market_code, player_id,
                         home_score, away_score, match_result):
                self.leg_index = leg_index
                self.leg_type = leg_type
                self.market_code = market_code
                self.player_id = player_id
                self.home_score = home_score
                self.away_score = away_score
                self.match_result = match_result

        leg_rows = [LegRow(*ld) for ld in legs_data]

        parlay_execute = MagicMock()
        parlay_execute.fetchall.return_value = [parlay_row]

        legs_execute = MagicMock()
        legs_execute.fetchall.return_value = leg_rows

        update_execute = MagicMock()

        call_count = {"n": 0}

        def side_effect(query, params=None):
            q = str(query)
            if "status = 'pending'" in q or ("SELECT DISTINCT" in q):
                return parlay_execute
            elif "parlay_precomputed_legs ppl" in q and "JOIN matches" in q:
                return legs_execute
            return update_execute

        mock_session.execute.side_effect = side_effect
        return mock_session

    def test_all_legs_win_settles_parlay_as_won(self, gen):
        """Home-win + Under-2.5, match is 1-0 → both legs win → parlay won."""
        mock_session = self._make_session_with_parlay(gen,
            parlay_id=1,
            parlay_hash="abc123",
            payout=450.0,
            legs_data=[
                (0, "match_result", "H", None, 1, 0, "H"),
                (1, "totals", "under_2.5", None, 1, 0, "H"),
            ]
        )
        result = gen.settle_parlays()
        assert result["won"] == 1
        assert result["lost"] == 0
        assert result["settled"] == 1

    def test_one_losing_leg_settles_parlay_as_lost(self, gen):
        """Home-win + Under-2.5, match is 2-1 → Under leg loses → parlay lost."""
        mock_session = self._make_session_with_parlay(gen,
            parlay_id=2,
            parlay_hash="def456",
            payout=450.0,
            legs_data=[
                (0, "match_result", "H", None, 2, 1, "H"),
                (1, "totals", "under_2.5", None, 2, 1, "H"),
            ]
        )
        result = gen.settle_parlays()
        assert result["won"] == 0
        assert result["lost"] == 1

    def test_leg_results_written_to_legs_table(self, gen):
        """
        The most important regression test: settle_parlays must call
        UPDATE parlay_precomputed_legs SET result = ... for each leg.
        """
        mock_session = MagicMock()
        gen.Session.return_value = mock_session
        gen._update_performance_summary = MagicMock()

        parlay_row = MagicMock()
        parlay_row.__getitem__ = lambda self, i: [10, "xyz789", 460.0][i]

        class LegRow:
            leg_index = 0
            leg_type = "match_result"
            market_code = "H"
            player_id = None
            home_score = 2
            away_score = 1
            match_result = "H"

        class LegRow2:
            leg_index = 1
            leg_type = "totals"
            market_code = "under_2.5"
            player_id = None
            home_score = 2
            away_score = 1
            match_result = "H"

        parlay_result_mock = MagicMock()
        parlay_result_mock.fetchall.return_value = [parlay_row]
        legs_result_mock = MagicMock()
        legs_result_mock.fetchall.return_value = [LegRow(), LegRow2()]

        def side_effect(query, params=None):
            q = str(query)
            if "SELECT DISTINCT" in q or "status = 'pending'" in q:
                return parlay_result_mock
            elif "parlay_precomputed_legs ppl" in q and "JOIN matches" in q:
                return legs_result_mock
            return MagicMock()

        mock_session.execute.side_effect = side_effect

        gen.settle_parlays()

        update_calls = [str(c[0][0]) for c in mock_session.execute.call_args_list]
        leg_updates = [c for c in update_calls if "UPDATE parlay_precomputed_legs" in c and "SET result" in c]
        assert len(leg_updates) == 2, (
            f"Expected 2 leg result updates, got {len(leg_updates)}. "
            "The settlement code must write each leg's result individually."
        )

    def test_both_legs_written_with_correct_results(self, gen):
        """Winning home-win leg gets result='won', losing under leg gets result='lost'."""
        mock_session = MagicMock()
        gen.Session.return_value = mock_session
        gen._update_performance_summary = MagicMock()

        parlay_row = MagicMock()
        parlay_row.__getitem__ = lambda self, i: [20, "legtest", 460.0][i]

        class WinningLeg:
            leg_index = 0
            leg_type = "match_result"
            market_code = "H"
            player_id = None
            home_score = 3
            away_score = 0
            match_result = "H"

        class LosingLeg:
            leg_index = 1
            leg_type = "totals"
            market_code = "under_2.5"
            player_id = None
            home_score = 3
            away_score = 0
            match_result = "H"

        parlay_result_mock = MagicMock()
        parlay_result_mock.fetchall.return_value = [parlay_row]
        legs_result_mock = MagicMock()
        legs_result_mock.fetchall.return_value = [WinningLeg(), LosingLeg()]

        def side_effect(query, params=None):
            q = str(query)
            if "SELECT DISTINCT" in q or "status = 'pending'" in q:
                return parlay_result_mock
            elif "parlay_precomputed_legs ppl" in q and "JOIN matches" in q:
                return legs_result_mock
            return MagicMock()

        mock_session.execute.side_effect = side_effect

        gen.settle_parlays()

        leg_update_params = []
        for i, c in enumerate(mock_session.execute.call_args_list):
            if c[0] and len(c[0]) >= 1:
                sql_str = str(c[0][0])
                if "UPDATE parlay_precomputed_legs" in sql_str and "SET result" in sql_str:
                    if len(c[0]) >= 2:
                        leg_update_params.append(c[0][1])

        assert len(leg_update_params) == 2, (
            f"Expected 2 leg UPDATE calls, got {len(leg_update_params)}"
        )
        results_by_index = {p["leg_index"]: p["result"] for p in leg_update_params}
        assert results_by_index.get(0) == "won", f"Leg 0 should be 'won', got {results_by_index.get(0)}"
        assert results_by_index.get(1) == "lost", f"Leg 1 should be 'lost', got {results_by_index.get(1)}"

    def test_empty_parlay_list_returns_zero_counts(self, gen):
        mock_session = MagicMock()
        gen.Session.return_value = mock_session
        gen._update_performance_summary = MagicMock()

        empty_result = MagicMock()
        empty_result.fetchall.return_value = []
        mock_session.execute.return_value = empty_result

        result = gen.settle_parlays()
        assert result["settled"] == 0
        assert result["won"] == 0
        assert result["lost"] == 0


# ---------------------------------------------------------------------------
# UNIT TESTS: get_performance_stats
# ---------------------------------------------------------------------------

class TestPerformanceStats:
    """Tests for performance stats calculation and ROI logic."""

    @pytest.fixture
    def gen(self):
        from models.automated_parlay_generator import AutomatedParlayGenerator
        with patch("models.automated_parlay_generator.create_engine"), \
             patch("models.automated_parlay_generator.sessionmaker"):
            g = AutomatedParlayGenerator.__new__(AutomatedParlayGenerator)
            g.engine = MagicMock()
            g.Session = MagicMock()
            g.v2_predictor = None
            g.totals_predictor = None
            g.player_props = None
            return g

    def _mock_stats_rows(self, gen, rows):
        mock_session = MagicMock()
        gen.Session.return_value = mock_session

        class Row:
            def __init__(self, leg_count, confidence_tier, total, won, lost,
                         pending, avg_edge, avg_payout, total_returns, total_staked):
                self.leg_count = leg_count
                self.confidence_tier = confidence_tier
                self.total = total
                self.won = won
                self.lost = lost
                self.pending = pending
                self.avg_edge = avg_edge
                self.avg_payout = avg_payout
                self.total_returns = total_returns
                self.total_staked = total_staked

        result_mock = MagicMock()
        result_mock.fetchall.return_value = [Row(*r) for r in rows]
        mock_session.execute.return_value = result_mock
        return mock_session

    def test_win_rate_calculation(self, gen):
        self._mock_stats_rows(gen, [
            (2, "medium", 50, 5, 45, 0, 8.5, 460.0, 2300.0, 5000.0),
        ])
        stats = gen.get_performance_stats()
        bucket = stats["by_bucket"][0]
        assert bucket["win_rate_pct"] == pytest.approx(10.0, abs=0.1)

    def test_roi_positive_when_returns_exceed_staked(self, gen):
        self._mock_stats_rows(gen, [
            (2, "high", 10, 10, 0, 0, 15.0, 500.0, 5000.0, 1000.0),
        ])
        stats = gen.get_performance_stats()
        bucket = stats["by_bucket"][0]
        assert bucket["roi_pct"] > 0

    def test_roi_negative_when_all_lost(self, gen):
        self._mock_stats_rows(gen, [
            (2, "low", 20, 0, 20, 0, -10.0, 460.0, 0.0, 2000.0),
        ])
        stats = gen.get_performance_stats()
        bucket = stats["by_bucket"][0]
        assert bucket["roi_pct"] == pytest.approx(-100.0, abs=0.1)

    def test_summary_totals_sum_across_buckets(self, gen):
        self._mock_stats_rows(gen, [
            (2, "high",   30, 3, 27, 0, 12.0, 480.0, 1440.0, 3000.0),
            (2, "medium", 20, 1, 19, 0,  8.0, 460.0,  460.0, 2000.0),
        ])
        stats = gen.get_performance_stats()
        assert stats["summary"]["total_parlays"] == 50
        assert stats["summary"]["total_won"] == 4
        assert stats["summary"]["total_lost"] == 46

    def test_zero_division_guarded_when_no_settled(self, gen):
        self._mock_stats_rows(gen, [
            (2, "high", 5, 0, 0, 5, 10.0, 460.0, 0.0, 0.0),
        ])
        stats = gen.get_performance_stats()
        bucket = stats["by_bucket"][0]
        assert bucket["win_rate_pct"] == 0.0


# ---------------------------------------------------------------------------
# INTEGRATION SMOKE TESTS (require DB connection — skipped in CI if no DB)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not __import__("os").environ.get("DATABASE_URL"),
    reason="Requires live DATABASE_URL"
)
class TestLiveIntegration:
    """Smoke tests against the real database — validates schema and query health."""

    @pytest.fixture
    def gen(self):
        from models.automated_parlay_generator import AutomatedParlayGenerator
        return AutomatedParlayGenerator()

    def test_generate_all_upcoming_runs_without_error(self, gen):
        result = gen.generate_all_upcoming_parlays(hours_ahead=48)
        assert "matches_processed" in result
        assert "total_parlays_generated" in result

    def test_settle_parlays_runs_without_error(self, gen):
        result = gen.settle_parlays()
        assert "settled" in result
        assert "won" in result
        assert "lost" in result

    def test_performance_stats_runs_without_error(self, gen):
        stats = gen.get_performance_stats()
        assert "by_bucket" in stats
        assert "summary" in stats

    def test_settled_parlays_have_leg_results(self, gen):
        """After any settlement run, all legs of settled parlays should have a result."""
        from sqlalchemy import text
        session = gen.Session()
        try:
            row = session.execute(text("""
                SELECT COUNT(*) AS null_legs
                FROM parlay_precomputed_legs ppl
                JOIN parlay_precomputed pp ON pp.id = ppl.parlay_id
                WHERE pp.status = 'settled'
                AND ppl.result IS NULL
            """)).fetchone()
            null_legs = row[0] if row else 0
            assert null_legs == 0, (
                f"{null_legs} settled parlay legs still have NULL result. "
                "Run the backfill script: python jobs/backfill_parlay_leg_results.py"
            )
        finally:
            session.close()

    def test_generated_parlays_are_2_leg_only(self, gen):
        """Any pending parlays generated by the new code should be 2-leg only."""
        from sqlalchemy import text
        session = gen.Session()
        try:
            row = session.execute(text("""
                SELECT COUNT(*) AS non_2_leg
                FROM parlay_precomputed
                WHERE status = 'pending'
                AND leg_count != 2
                AND created_at > NOW() - INTERVAL '1 hour'
            """)).fetchone()
            non_2_leg = row[0] if row else 0
            assert non_2_leg == 0, (
                f"{non_2_leg} recently-generated parlays are not 2-leg."
            )
        finally:
            session.close()
