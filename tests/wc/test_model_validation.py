"""
Model-validation tests: the WC model's recorded results meet the honesty bar
(beats the majority-class baseline) and the V3 fixes are in place.

These assert on the persisted training/validation artifacts so they don't have
to re-run multi-minute training jobs.
"""
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


class TestWCModelMetadata:
    META = REPO / "artifacts" / "models" / "wc_model" / "metadata.json"

    def _meta(self):
        if not self.META.exists():
            pytest.skip("WC model not trained yet (run training/train_wc_model.py)")
        return json.loads(self.META.read_text())

    def test_elo_beats_majority(self):
        m = self._meta()
        assert m["elo_acc"] > m["majority_acc"], \
            f"ELO {m['elo_acc']:.3f} must beat majority {m['majority_acc']:.3f}"

    def test_elo_meaningfully_above_baseline(self):
        m = self._meta()
        # the headline result: ~+15pp over majority class
        assert (m["elo_acc"] - m["majority_acc"]) >= 0.08

    def test_recommended_is_elo(self):
        m = self._meta()
        # trained layer did not beat pure ELO → ship ELO (the disciplined call)
        assert m["recommended"] == "elo"

    def test_holdout_was_real(self):
        m = self._meta()
        assert m["n_holdout"] >= 200, "holdout too small to trust"


class TestV3FixesInPlace:
    """Guards against regressions of the V3 bugs we fixed."""
    def test_league_draw_rate_feature_present(self):
        # the double-fetchone bug had us delete it; the fix resurrects it
        from features.v3_feature_builder import V3FeatureBuilder
        assert "league_draw_rate" in V3FeatureBuilder.LEAGUE_DRAW_FEATURE_NAMES
        assert "league_rolling_draw_rate" in V3FeatureBuilder.LEAGUE_DRAW_FEATURE_NAMES

    def test_training_query_has_synthetic_filter(self):
        # train_v3_sharp must exclude the 3 template vectors
        src = (REPO / "training" / "train_v3_sharp.py").read_text()
        assert "SYNTHETIC_FILTER" in src
        assert "0.650" in src and "0.250" in src

    def test_draw_boost_in_sample_weights(self):
        src = (REPO / "training" / "train_v3_sharp.py").read_text()
        assert "draw_boost" in src


class TestV3HonestyRecord:
    """The temporal-holdout result must be recorded (even though it failed)."""
    RESULT = REPO / "scripts" / "temporal_holdout_result.json"

    def test_result_recorded(self):
        if not self.RESULT.exists():
            pytest.skip("V3 temporal holdout not run")
        r = json.loads(self.RESULT.read_text())
        assert "v3_accuracy" in r and "favorite_accuracy" in r
        # we keep the honest record that V3 did not beat the line
        assert "gate_passed" in r
