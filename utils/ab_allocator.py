"""
A/B Testing Allocator

Deterministic allocation of prediction traffic to model variants.
Uses a hash of (experiment_id, match_id) so the same match always
gets the same variant — ensuring consistency across repeated requests.
"""

import hashlib
import logging
from typing import Optional
from utils.ab_config import AB_EXPERIMENTS

logger = logging.getLogger(__name__)


def allocate_variant(experiment_id: str, match_id) -> Optional[str]:
    """
    Deterministically allocate a match to an experiment variant.

    Uses MD5 hash of (experiment_id, match_id) modulo 10000 for a
    uniform bucket distribution.  Returns the variant name, or None
    if the experiment doesn't exist or is inactive.
    """
    config = AB_EXPERIMENTS.get(experiment_id)
    if not config or not config.get("active"):
        return None

    variants = config["variants"]
    if not variants:
        return None

    # Single variant — short-circuit
    if len(variants) == 1:
        return list(variants.keys())[0]

    # Deterministic hash bucket (0–9999)
    raw = f"{experiment_id}:{match_id}"
    bucket = int(hashlib.md5(raw.encode()).hexdigest()[:8], 16) % 10000

    cumulative = 0.0
    for variant, weight in variants.items():
        cumulative += weight * 10000
        if bucket < cumulative:
            return variant

    # Fallback (should never reach here)
    return list(variants.keys())[0]


def get_active_experiments() -> dict:
    """Return only active experiments."""
    return {k: v for k, v in AB_EXPERIMENTS.items() if v.get("active")}


def get_experiment_info(experiment_id: str) -> Optional[dict]:
    """Return experiment config if it exists and is active."""
    config = AB_EXPERIMENTS.get(experiment_id)
    if config and config.get("active"):
        return config
    return None
