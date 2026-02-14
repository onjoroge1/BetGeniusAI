"""
Player Parlay Generator V2
Now delegates to V3 rewrite (PlayerParlayGenerator) for all generation.
Kept as a compatibility wrapper for routes that reference V2.
"""

import logging
from typing import Dict, List
from models.player_parlay_generator import PlayerParlayGenerator

logger = logging.getLogger(__name__)


class PlayerParlayGeneratorV2:
    def __init__(self):
        self._gen = PlayerParlayGenerator()

    def generate_all_player_parlays(self, hours_ahead: int = 72) -> Dict:
        result = self._gen.generate_all_player_parlays(hours_ahead)
        result['version'] = 'v2_via_v3'
        return result

    def get_best_parlays(self, limit: int = 10, min_ev: float = 0) -> List[Dict]:
        return self._gen.get_best_parlays(limit=limit)


def run_player_parlay_v2_generation(hours_ahead: int = 72) -> Dict:
    generator = PlayerParlayGeneratorV2()
    return generator.generate_all_player_parlays(hours_ahead)
