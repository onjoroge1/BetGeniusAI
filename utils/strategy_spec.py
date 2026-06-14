"""
Strategy-spec registry — load, validate, and HASH locked betting specs.

The hash is the tamper-evidence: every alert stores the spec_hash it fired under,
so you can prove which exact rule set produced a pick. Changing any rule changes
the hash → it must become a new version (the framework's anti-hindsight rule).
See docs/LIVE_BETTING_EDGE_SPEC.md.

Pure stdlib (json + hashlib) so it's importable anywhere and fully testable.
"""

import json
import hashlib
from pathlib import Path
from typing import Dict, List, Optional

SPEC_DIR = Path(__file__).parent.parent / "specs" / "strategy"

# Fields required for a spec to be considered well-formed / registrable.
REQUIRED_FIELDS = (
    "strategy_id", "version", "name", "market", "status",
    "hypothesis", "entry_rules", "exclusion_rules",
    "settlement", "baseline", "success_gate",
)
# Hash covers the RULES (not status/notes) — promoting a spec or editing a note
# must NOT change the hash; changing a threshold MUST.
HASHED_FIELDS = (
    "strategy_id", "version", "market", "time_window", "league_scope",
    "hypothesis", "entry_rules", "exclusion_rules", "settlement", "baseline",
    "success_gate",
)


def spec_hash(spec: Dict) -> str:
    """Deterministic hash of a spec's rule content (stable across key order)."""
    payload = {k: spec.get(k) for k in HASHED_FIELDS}
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def validate_spec(spec: Dict) -> List[str]:
    """Return a list of problems; empty list means valid."""
    problems = []
    for f in REQUIRED_FIELDS:
        if f not in spec or spec[f] in (None, "", {}):
            problems.append(f"missing required field: {f}")
    if spec.get("status") not in (None, "Draft", "Registered", "Validating", "Promoted", "Retired"):
        problems.append(f"invalid status: {spec.get('status')}")
    er = spec.get("entry_rules") or {}
    if "edge_min_pp" in er and not isinstance(er["edge_min_pp"], (int, float)):
        problems.append("entry_rules.edge_min_pp must be numeric")
    sg = spec.get("success_gate") or {}
    if sg and not sg.get("require_positive_clv"):
        problems.append("success_gate must require positive CLV (governance rule)")
    return problems


def load_spec(strategy_id: str, spec_dir: Optional[Path] = None) -> Dict:
    """Load one spec by id, attach its computed hash, validate."""
    d = spec_dir or SPEC_DIR
    path = d / f"{strategy_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"strategy spec not found: {path}")
    spec = json.loads(path.read_text())
    problems = validate_spec(spec)
    if problems:
        raise ValueError(f"invalid spec {strategy_id}: {problems}")
    spec["spec_hash"] = spec_hash(spec)
    return spec


def load_all_specs(spec_dir: Optional[Path] = None) -> List[Dict]:
    """Load + validate every spec in the directory (skips invalid with no crash is NOT done — invalid specs raise)."""
    d = spec_dir or SPEC_DIR
    if not d.exists():
        return []
    out = []
    for p in sorted(d.glob("*.json")):
        spec = json.loads(p.read_text())
        problems = validate_spec(spec)
        if problems:
            raise ValueError(f"invalid spec {p.name}: {problems}")
        spec["spec_hash"] = spec_hash(spec)
        out.append(spec)
    return out
