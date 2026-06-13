"""
Unit tests for the live (in-game) feature + label builder — pure, no DB.
Guards the leak-safety that makes an in-game backtest trustworthy.
"""
import pytest
from features.live_feature_builder import (
    build_live_features, label_from_goals, implied_more_goal_poisson,
)

SNAPS = [
    {"minute": 60, "home_score": 0, "away_score": 0, "home_shots_total": 4, "away_shots_total": 3,
     "home_shots_on_target": 1, "away_shots_on_target": 1, "home_corners": 2, "away_corners": 1,
     "home_possession": 52, "home_red_cards": 0, "away_red_cards": 0},
    {"minute": 70, "home_score": 0, "away_score": 0, "home_shots_total": 6, "away_shots_total": 3,
     "home_shots_on_target": 2, "away_shots_on_target": 1, "home_corners": 3, "away_corners": 1,
     "home_possession": 58, "home_red_cards": 0, "away_red_cards": 0},
    {"minute": 77, "home_score": 0, "away_score": 0, "home_shots_total": 12, "away_shots_total": 3,
     "home_shots_on_target": 5, "away_shots_on_target": 1, "home_corners": 6, "away_corners": 1,
     "home_possession": 64, "home_red_cards": 0, "away_red_cards": 0},
    {"minute": 85, "home_score": 1, "away_score": 0, "home_shots_total": 14, "away_shots_total": 4,
     "home_shots_on_target": 6, "away_shots_on_target": 1, "home_corners": 7, "away_corners": 1,
     "home_possession": 63, "home_red_cards": 0, "away_red_cards": 0},
]


class TestLeakSafety:
    def test_features_ignore_future_snapshots(self):
        f = build_live_features(SNAPS, 77)
        # the 85' snapshot (1-0) must NOT leak into a 77' decision
        assert f["home_score"] == 0
        assert f["minute"] == 77

    def test_empty_when_no_snapshots_before_minute(self):
        assert build_live_features(SNAPS, 30) == {}


class TestMomentum:
    def test_rolling_shot_delta(self):
        f = build_live_features(SNAPS, 77)
        # shots went 6 → 12 between 70' and 77' (within last 10)
        assert f["home_shots_10"] >= 6

    def test_pressure_favors_dominant_side(self):
        f = build_live_features(SNAPS, 77)
        assert f["pressure_home"] > f["pressure_away"]


class TestPrematchAnchor:
    def test_favorite_trailing_flag(self):
        f = build_live_features(SNAPS, 77, prematch={"home": 0.55, "away": 0.25, "favorite": "home"})
        assert f["favorite_trailing"] == 0.0  # 0-0, not trailing
        assert f["favorite_leading"] == 0.0


class TestLabels:
    def test_more_goal_and_next_team(self):
        lab = label_from_goals([84], 77, (0, 0), (1, 0), next_goal_team="home")
        assert lab["target_more_goal"] == 1
        assert lab["target_next_goal"] == "home"
        assert lab["target_result_holds"] == 0  # 0-0 → 1-0 doesn't hold

    def test_result_holds_when_no_more_goals(self):
        lab = label_from_goals([84], 85, (1, 0), (1, 0))
        assert lab["target_more_goal"] == 0
        assert lab["target_next_goal"] == "none"
        assert lab["target_result_holds"] == 1


class TestPoissonPrior:
    def test_prior_decreases_with_minute(self):
        early = implied_more_goal_poisson(0, 0, 60)
        late = implied_more_goal_poisson(0, 0, 85)
        assert 0 < late < early < 1

    def test_prior_in_unit_interval(self):
        assert 0.0 <= implied_more_goal_poisson(2, 1, 77) <= 1.0
