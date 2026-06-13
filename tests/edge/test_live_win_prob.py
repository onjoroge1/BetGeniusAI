"""
Unit tests for the live win-probability engine (Snapbet Live Edge Layer 1).
Pure math, no DB — guards the dynamic win-prob + advanced-markets logic.
"""
import pytest
from models.live_win_probability import live_win_probability, lambdas_from_anchor


def wp(**kw):
    return live_win_probability(**kw)


class TestWinProbSums:
    @pytest.mark.parametrize("kw", [
        dict(home_score=0, away_score=0, minute=10),
        dict(home_score=0, away_score=0, minute=85),
        dict(home_score=2, away_score=1, minute=70),
        dict(home_score=0, away_score=1, minute=80, red_home=1),
    ])
    def test_sums_to_one_exactly(self, kw):
        w = wp(**kw)["win_probability"]
        assert abs(sum(w.values()) - 1.0) < 1e-9

    def test_all_in_unit_interval(self):
        w = wp(home_score=1, away_score=1, minute=60)["win_probability"]
        assert all(0.0 <= v <= 1.0 for v in w.values())


class TestDynamics:
    def test_draw_dominates_level_late(self):
        w = wp(home_score=0, away_score=0, minute=88)["win_probability"]
        assert w["draw"] > w["home"] and w["draw"] > w["away"]

    def test_leader_dominates_late(self):
        w = wp(home_score=1, away_score=0, minute=88)["win_probability"]
        assert w["home"] > 0.85

    def test_more_time_more_open(self):
        early = wp(home_score=0, away_score=0, minute=10)["win_probability"]["draw"]
        late = wp(home_score=0, away_score=0, minute=88)["win_probability"]["draw"]
        assert late > early  # draw becomes far more likely as time runs out at 0-0

    def test_trailing_team_helped_by_opponent_red(self):
        base = wp(home_score=0, away_score=1, minute=75)["win_probability"]["home"]
        with_red = wp(home_score=0, away_score=1, minute=75, red_away=1)["win_probability"]["home"]
        assert with_red > base  # away red card improves home's comeback odds


class TestMarkets:
    def test_btts_one_when_both_scored(self):
        m = wp(home_score=1, away_score=1, minute=70)["markets"]
        assert m["btts"] == 1.0

    def test_over25_equals_over05more_at_two_goals(self):
        # at a 2-goal current total, "over 2.5 total" == "at least one more goal"
        m = wp(home_score=1, away_score=1, minute=60)["markets"]
        assert abs(m["over_2.5_total"] - m["over_0.5_more_goals"]) < 1e-9

    def test_next_goal_split_sums_to_one(self):
        ng = wp(home_score=0, away_score=0, minute=50)["markets"]["next_goal"]
        assert abs((ng["home"] + ng["away"] + ng["none"]) - 1.0) < 0.02

    def test_over05more_drops_with_time(self):
        early = wp(home_score=0, away_score=0, minute=20)["markets"]["over_0.5_more_goals"]
        late = wp(home_score=0, away_score=0, minute=88)["markets"]["over_0.5_more_goals"]
        assert early > late


class TestAnchorSplit:
    def test_favorite_gets_more_goals(self):
        lh, la = lambdas_from_anchor({"home": 0.62, "away": 0.20})
        assert lh > la

    def test_no_anchor_mild_home_tilt(self):
        lh, la = lambdas_from_anchor(None)
        assert lh > la and abs(lh - la) < 0.5
