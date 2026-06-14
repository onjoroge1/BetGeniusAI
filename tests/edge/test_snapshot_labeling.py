"""
Unit tests for the live snapshot labeling logic (#2 data foundation).
Pure functions — guards the targets that train the live model.
"""
from models.live_snapshot_writer import next_goal_after, label_snapshot


class TestNextGoalAfter:
    GOALS = [(23, "home"), (58, "away"), (84, "home")]

    def test_first_goal_after_minute(self):
        assert next_goal_after(self.GOALS, 50) == "away"   # 58' away is next after 50'
        assert next_goal_after(self.GOALS, 60) == "home"   # 84' home is next after 60'

    def test_none_after_last_goal(self):
        assert next_goal_after(self.GOALS, 85) is None

    def test_at_exact_minute_is_strictly_after(self):
        assert next_goal_after(self.GOALS, 23) == "away"    # 23' not counted (strictly >)

    def test_empty(self):
        assert next_goal_after([], 70) is None


class TestLabelSnapshot:
    GOALS = [(23, "home"), (58, "away"), (84, "home")]  # final 2-1 home

    def test_more_goal_and_next(self):
        lab = label_snapshot(self.GOALS, 70, (1, 1), (2, 1))
        assert lab["target_more_goal"] == 1
        assert lab["target_next_goal"] == "home"   # 84' home
        assert lab["target_result_holds"] == 0     # 1-1 (draw) → 2-1 (home), didn't hold

    def test_no_more_goals_result_holds(self):
        lab = label_snapshot(self.GOALS, 85, (2, 1), (2, 1))
        assert lab["target_more_goal"] == 0
        assert lab["target_next_goal"] == "none"
        assert lab["target_result_holds"] == 1     # 2-1 home → 2-1 home, held

    def test_result_holds_when_leader_extends(self):
        # at 60' it's 1-1 (draw state); final 2-1 home → draw state did NOT hold
        lab = label_snapshot(self.GOALS, 60, (1, 1), (2, 1))
        assert lab["target_result_holds"] == 0

    def test_lead_held_to_full_time(self):
        goals = [(10, "home")]  # 1-0, no more
        lab = label_snapshot(goals, 20, (1, 0), (1, 0))
        assert lab["target_more_goal"] == 0
        assert lab["target_result_holds"] == 1
