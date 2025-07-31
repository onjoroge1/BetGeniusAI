
# Simple Weighted Consensus - Production Model

## Overview
BetGenius AI production model using simple weighted consensus based on 31-year bookmaker analysis.

## Model Performance
- **LogLoss**: 0.963475
- **Brier Score**: 0.572791  
- **Accuracy**: 0.543
- **Sample Size**: 1,500 matches

## Quality Weights
Based on comprehensive 31-year historical analysis:
- **Pinnacle**: 35% (Sharp bookmaker, best LogLoss performance)
- **Bet365**: 25% (High-quality recreational)
- **Betway**: 22% (Quality recreational)
- **William Hill**: 18% (Standard recreational)

## Why Simple Consensus?
1. **Performance Proven**: Outperforms complex models by 0.031549 LogLoss
2. **Market Efficiency**: T-72h bookmaker consensus is highly efficient
3. **Robustness**: Simple approach is more reliable and maintainable
4. **Operational Excellence**: Easy to monitor, debug, and explain

## Implementation
```python
from production.simple_consensus_predictor import SimpleWeightedConsensusPredictor

predictor = SimpleWeightedConsensusPredictor()
result = predictor.predict_match({
    'pinnacle': {'home': 2.10, 'draw': 3.40, 'away': 3.20},
    'bet365': {'home': 2.05, 'draw': 3.30, 'away': 3.15},
    'betway': {'home': 2.08, 'draw': 3.35, 'away': 3.18},
    'william_hill': {'home': 2.00, 'draw': 3.25, 'away': 3.10}
})
```

## Monitoring
- Monitor bookmaker coverage per match
- Track quality score (target: >0.8)
- Validate consensus dispersion for uncertainty quantification
- Log prediction confidence for performance analysis

## Deployment Date
July 31, 2025

## Next Steps
1. Integration with main application
2. API endpoint updates
3. Frontend probability display
4. Production monitoring setup
