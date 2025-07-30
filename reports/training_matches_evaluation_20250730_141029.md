# Training Matches ML Evaluation Report
*Generated: 20250730_141029*

## Dataset Overview
- **Total Matches**: 1,893
- **Date Range**: 2023-08-11 19:00:00 to 2025-06-12 00:02:38.035213
- **Leagues**: 10
- **Features Extracted**: 25

## Outcome Distribution
{'Home': 826, 'Away': 620, 'Draw': 447}

## Baseline Performance

| Baseline | Accuracy | LogLoss | Brier Score | Description |
|----------|----------|---------|-------------|-------------|
| Uniform | 0.236 | 1.0986 | 0.6667 | Uniform 33.33% probability for each outcome |
| Frequency | 0.436 | 1.0683 | 0.6466 | Historical frequencies: ['43.6%', '23.6%', '32.8%'] |
| Random | 0.349 | 1.4978 | 0.8235 | Random predictions with Dirichlet probabilities |

## Model Performance

| Model | Accuracy | LogLoss | Brier Score | vs Uniform | vs Frequency |
|-------|----------|---------|-------------|------------|--------------|
| Random Forest | 1.000 | 0.0008 | 0.0000 | +323.5% | +129.2% |
| Logistic Regression | 1.000 | 0.0133 | 0.0016 | +323.5% | +129.2% |

## Top 10 Feature Importance

| Rank | Feature | Importance |
|------|---------|------------|
| 1 | goal_difference | 0.5055 |
| 2 | venue_advantage_realized | 0.2556 |
| 3 | competitiveness_indicator | 0.1155 |
| 4 | total_goals | 0.0545 |
| 5 | goal_expectancy | 0.0530 |
| 6 | cross_league_applicability | 0.0026 |
| 7 | south_american_flag | 0.0023 |
| 8 | training_weight | 0.0016 |
| 9 | league_home_advantage | 0.0013 |
| 10 | regional_intensity | 0.0012 |
