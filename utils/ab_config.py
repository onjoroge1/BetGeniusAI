"""
A/B Testing Experiment Configuration

Defines active experiments, variant weights, and evaluation criteria.
Experiments route prediction traffic between model variants to measure
which model performs best in production.
"""

AB_EXPERIMENTS = {
    "soccer_primary_model": {
        "description": "Compare V1 consensus, V2 LightGBM, and V3 sharp for soccer predictions",
        "variants": {
            "v1_consensus": 0.50,   # 50% of traffic
            "v2_lgbm": 0.30,        # 30% of traffic
            "v3_sharp": 0.20,       # 20% of traffic
        },
        "metric": "hit_rate",       # Primary metric to optimize
        "min_samples": 100,         # Min settled predictions before declaring winner
        "active": True,
    },
    "multisport_model": {
        "description": "Track multisport V3 model performance across NBA, NHL, NCAAB, NFL",
        "variants": {
            "v3_default": 1.0,      # Single variant — pure tracking, no split
        },
        "metric": "hit_rate",
        "min_samples": 50,
        "active": True,
    },
}
