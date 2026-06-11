"""
Unit tests for the national-team ELO math (no DB required).
Covers the core formulas: expected score, home advantage, K-factor weighting,
margin-of-victory multiplier, and the ELO→probability mapping.
"""
import pytest
from models.national_elo import (
    NationalEloModel, _k_factor, _mov_multiplier,
    INITIAL_ELO, HOME_ADVANTAGE, TOURNAMENT_K,
)


class TestExpectedScore:
    def test_equal_teams_neutral_is_half(self):
        e = NationalEloModel.expected(1500, 1500, neutral=True)
        assert abs(e - 0.5) < 1e-9

    def test_symmetry_neutral(self):
        # expected(A,B) + expected(B,A) == 1 at neutral venue
        a = NationalEloModel.expected(1700, 1500, neutral=True)
        b = NationalEloModel.expected(1500, 1700, neutral=True)
        assert abs((a + b) - 1.0) < 1e-9

    def test_higher_elo_favored(self):
        assert NationalEloModel.expected(1800, 1500, neutral=True) > 0.5

    def test_home_advantage_raises_expectation(self):
        neutral = NationalEloModel.expected(1500, 1500, neutral=True)
        home = NationalEloModel.expected(1500, 1500, neutral=False)
        assert home > neutral
        # 100-pt HFA on even teams → ~64% expected
        assert 0.60 < home < 0.68

    def test_expected_in_unit_interval(self):
        for dh, da in [(1000, 2000), (2000, 1000), (1500, 1505)]:
            e = NationalEloModel.expected(dh, da, neutral=True)
            assert 0.0 <= e <= 1.0


class TestKFactor:
    def test_world_cup_highest(self):
        assert _k_factor(1) == 60
        assert _k_factor(1) > _k_factor(10)  # WC > friendly

    def test_continental(self):
        for tid in (4, 6, 9):
            assert _k_factor(tid) == 50

    def test_qualifiers(self):
        for tid in (29, 30, 31, 32, 33, 34):
            assert _k_factor(tid) == 40

    def test_friendly_lowest(self):
        assert _k_factor(10) == 20

    def test_unknown_default(self):
        assert _k_factor(99999) == 30.0


class TestMovMultiplier:
    def test_one_goal_baseline(self):
        assert _mov_multiplier(1) == 1.0
        assert _mov_multiplier(-1) == 1.0  # symmetric

    def test_two_goals(self):
        assert _mov_multiplier(2) == 1.5

    def test_monotonic_increasing(self):
        vals = [_mov_multiplier(g) for g in range(1, 7)]
        assert vals == sorted(vals)

    def test_blowout_larger(self):
        assert _mov_multiplier(5) > _mov_multiplier(2)


class TestPredictProba:
    def setup_method(self):
        self.m = NationalEloModel()
        # inject ratings without touching DB
        self.m.elos = {1: 1900, 2: 1500, 3: 1900}

    def test_probs_sum_to_one(self):
        p = self.m.predict_proba(1, 2, neutral=True)
        assert abs(sum(p.values()) - 1.0) < 1e-6

    def test_probs_in_bounds(self):
        p = self.m.predict_proba(1, 2, neutral=True)
        assert all(0.0 <= v <= 1.0 for v in p.values())

    def test_stronger_team_higher_prob(self):
        p = self.m.predict_proba(1, 2, neutral=True)   # 1900 vs 1500
        assert p["home"] > p["away"]

    def test_even_match_draw_peaks(self):
        even = self.m.predict_proba(1, 3, neutral=True)     # 1900 vs 1900
        lopsided = self.m.predict_proba(1, 2, neutral=True)  # 1900 vs 1500
        assert even["draw"] > lopsided["draw"]

    def test_unrated_team_uses_initial(self):
        # team 99 has no rating → INITIAL_ELO; still valid probs
        p = self.m.predict_proba(1, 99, neutral=True)
        assert abs(sum(p.values()) - 1.0) < 1e-6
        assert p["home"] > p["away"]  # 1900 vs 1500 default
