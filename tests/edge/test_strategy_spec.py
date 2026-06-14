"""
Tests for the strategy-spec registry — the governance layer (load, validate, hash).
Guards the anti-hindsight rule: rule changes MUST change the hash; status/notes
changes MUST NOT.
"""
import copy
import pytest
from utils.strategy_spec import (
    load_spec, load_all_specs, spec_hash, validate_spec,
)


@pytest.fixture
def first_spec():
    return load_spec("SB-LIVE-OVER05-001")


class TestFirstSpecLoads:
    def test_loads_and_validates(self, first_spec):
        assert first_spec["strategy_id"] == "SB-LIVE-OVER05-001"
        assert first_spec["market"] == "over_0.5_more_goals"
        assert "spec_hash" in first_spec and len(first_spec["spec_hash"]) == 16

    def test_all_specs_load(self):
        specs = load_all_specs()
        assert len(specs) >= 1
        assert all("spec_hash" in s for s in specs)


class TestHashGovernance:
    def test_hash_is_deterministic(self, first_spec):
        assert spec_hash(first_spec) == spec_hash(first_spec)

    def test_status_change_does_not_change_hash(self, first_spec):
        h0 = spec_hash(first_spec)
        promoted = copy.deepcopy(first_spec)
        promoted["status"] = "Promoted"
        promoted["notes"] = "promoted after gate"
        assert spec_hash(promoted) == h0  # status/notes excluded from hash

    def test_threshold_change_changes_hash(self, first_spec):
        h0 = spec_hash(first_spec)
        tampered = copy.deepcopy(first_spec)
        tampered["entry_rules"]["edge_min_pp"] = 3   # loosen the edge bar
        assert spec_hash(tampered) != h0  # rule change MUST be a new hash


class TestValidation:
    def test_missing_field_flagged(self, first_spec):
        bad = copy.deepcopy(first_spec)
        del bad["hypothesis"]
        assert any("hypothesis" in p for p in validate_spec(bad))

    def test_clv_gate_required(self, first_spec):
        bad = copy.deepcopy(first_spec)
        bad["success_gate"]["require_positive_clv"] = False
        assert any("CLV" in p for p in validate_spec(bad))

    def test_valid_spec_has_no_problems(self, first_spec):
        # the loaded spec carries a computed spec_hash; validation ignores it
        assert validate_spec(first_spec) == []
