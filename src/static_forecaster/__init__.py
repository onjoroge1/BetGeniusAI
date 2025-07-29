"""
Static Forecaster - Simplified accuracy-first prediction system
"""

from .data_snapshot import StaticSnapshotBuilder
from .models import (
    TwoStageClassifier, 
    PoissonDixonColes, 
    GoalDifferenceRegressor,
    EnsembleMetaLearner
)
from .evaluation import StaticEvaluator
from .trainer import StaticTrainer

__all__ = [
    'StaticSnapshotBuilder',
    'TwoStageClassifier',
    'PoissonDixonColes', 
    'GoalDifferenceRegressor',
    'EnsembleMetaLearner',
    'StaticEvaluator',
    'StaticTrainer'
]