# Multi-Sport Prediction System (NBA & NHL)

## Overview

BetGenius AI includes a multi-sport prediction system for **NBA (Basketball)** and **NHL (Hockey)**. Unlike football's 3-way predictions (Home/Draw/Away), these sports use **2-way classification** (Home/Away) since draws are extremely rare or resolved through overtime.

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    DATA COLLECTION LAYER                        │
├─────────────────────────────────────────────────────────────────┤
│  The Odds API  ───▶  multisport_odds_snapshots (834k+ rows)    │
│       │                                                         │
│       └─────────▶  multisport_fixtures (177 games)             │
│                          │                                      │
│                          ▼                                      │
│               multisport_training (146 games)                   │
└─────────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                    ML TRAINING LAYER                            │
├─────────────────────────────────────────────────────────────────┤
│  training/train_v2_multisport.py                               │
│       │                                                         │
│       ├───▶  V2-Basketball Model (30 features)                 │
│       │      artifacts/models/v2_basketball/                    │
│       │                                                         │
│       └───▶  V2-Hockey Model (30 features)                     │
│              artifacts/models/v2_hockey/                        │
└─────────────────────────────────────────────────────────────────┘
```

## Database Tables

### multisport_fixtures
Stores game metadata and results.

| Column | Type | Description |
|--------|------|-------------|
| id | serial | Primary key |
| sport | varchar(20) | 'basketball' or 'hockey' |
| sport_key | varchar(50) | API sport key (e.g., 'basketball_nba') |
| event_id | varchar(100) | Unique event ID from The Odds API |
| home_team | varchar(100) | Home team name |
| away_team | varchar(100) | Away team name |
| commence_time | timestamptz | Game start time |
| home_score | integer | Final home score |
| away_score | integer | Final away score |
| outcome | char(1) | 'H' or 'A' |
| status | varchar(20) | 'scheduled', 'live', 'finished' |

### multisport_odds_snapshots
Stores odds history for each game (~5000 snapshots per game).

| Column | Type | Description |
|--------|------|-------------|
| id | serial | Primary key |
| sport | varchar(20) | 'basketball' or 'hockey' |
| event_id | varchar(100) | Links to fixtures |
| home_odds | numeric(6,3) | Moneyline home odds |
| away_odds | numeric(6,3) | Moneyline away odds |
| home_prob | numeric(5,4) | Implied home probability |
| away_prob | numeric(5,4) | Implied away probability |
| home_spread | numeric(5,2) | Point spread for home team |
| total_line | numeric(5,2) | Over/under line |
| over_odds | numeric(6,3) | Over odds |
| under_odds | numeric(6,3) | Under odds |
| overround | numeric(5,4) | Market overround |
| n_bookmakers | integer | Number of bookmakers |
| ts_recorded | timestamp | When snapshot was taken |

### multisport_training
Training data with pre-computed features.

| Column | Type | Description |
|--------|------|-------------|
| id | serial | Primary key |
| sport | varchar(20) | 'basketball' or 'hockey' |
| event_id | varchar(100) | Links to fixtures |
| home_team | varchar(100) | Home team |
| away_team | varchar(100) | Away team |
| match_date | date | Game date |
| home_score | integer | Final home score |
| away_score | integer | Final away score |
| outcome | char(1) | 'H' or 'A' |
| features | jsonb | Pre-computed feature vector |
| consensus_home_prob | numeric(5,4) | Market consensus home probability |
| consensus_away_prob | numeric(5,4) | Market consensus away probability |

## Feature Engineering

### 30 Features Used in V2 Models

#### Moneyline Features (12)
- `open_home_odds`, `open_away_odds` - Opening odds
- `close_home_odds`, `close_away_odds` - Closing odds
- `home_odds_drift`, `away_odds_drift` - Odds movement
- `open_home_prob`, `open_away_prob` - Opening implied probabilities
- `close_home_prob`, `close_away_prob` - Closing implied probabilities
- `home_prob_drift`, `away_prob_drift` - Probability movement

#### Spread Features (5)
- `spread_line` - Closing point spread
- `home_spread_odds`, `away_spread_odds` - Spread odds
- `open_spread` - Opening spread
- `spread_drift` - Spread movement

#### Totals Features (4)
- `total_line` - Closing over/under line
- `over_odds`, `under_odds` - Totals odds
- `open_total`, `total_drift` - Opening total and movement

#### Market Efficiency Features (5)
- `overround` - Market efficiency (lower = more efficient)
- `n_bookmakers` - Number of books in consensus
- `n_snapshots` - Data quality indicator
- `hours_before_match` - Timing of last snapshot
- `home_odds_volatility` - Standard deviation of odds over time

#### Derived Features (4)
- `home_is_favorite` - Binary: 1 if home odds < away odds
- `odds_diff` - Closing home - away odds difference
- `prob_diff` - Closing home - away probability difference

## Model Performance

### V2-Basketball (NBA)
Trained on 68 games (Dec 5-15, 2025)

| Metric | Value |
|--------|-------|
| Accuracy | 92.9% |
| Log Loss | 0.2035 |
| ROC-AUC | 1.0000 |
| Train/Test Split | 54/14 |

**Top Features by Importance:**
1. close_away_prob (265.2)
2. home_odds_volatility (191.6)
3. close_home_odds (53.9)
4. close_away_odds (22.8)
5. home_odds_drift (2.8)

### V2-Hockey (NHL)
Trained on 78 games (Dec 6-15, 2025)

| Metric | Value |
|--------|-------|
| Accuracy | 75.0% |
| Log Loss | 0.4052 |
| ROC-AUC | 0.8413 |
| Train/Test Split | 62/16 |

**Top Features by Importance:**
1. home_odds_volatility (187.7)
2. away_odds_drift (143.4)
3. home_odds_drift (71.9)
4. close_home_prob (32.9)
5. home_prob_drift (29.7)

## Data Collection

### Collection Schedule
- **Odds Snapshots**: Every 60 minutes (reduced from 5 minutes to slow DB growth)
- **Results**: Every 60 minutes (fetch completed scores)
- **Team Data**: Every 60 minutes (API-Sports sync)

### Sport Keys
| Sport | API Key | Active Months |
|-------|---------|---------------|
| NBA | basketball_nba | Oct-Jun |
| NHL | icehockey_nhl | Oct-Jun |
| MLB | baseball_mlb | Apr-Oct (off-season) |

### API Usage
- **The Odds API**: Odds, spreads, totals for all sports
- **API-Sports**: Team metadata, player data (optional)

## Training Pipeline

### Sync Training Data
```bash
python -c "from training.multisport_training_sync import sync_training_data; sync_training_data()"
```

### Train Models
```bash
# Set library path for LightGBM
export LD_LIBRARY_PATH="$(gcc -print-file-name=libgomp.so | xargs dirname):$LD_LIBRARY_PATH"

# Train all sports
python training/train_v2_multisport.py --sport all

# Train specific sport
python training/train_v2_multisport.py --sport basketball
python training/train_v2_multisport.py --sport hockey
```

### Model Artifacts
Models are saved to:
- `artifacts/models/v2_basketball/v2_basketball_model.pkl`
- `artifacts/models/v2_hockey/v2_hockey_model.pkl`

Each pickle file contains:
- `model`: Trained LightGBM model
- `feature_names`: List of feature columns
- `metrics`: Training metrics
- `sport`: Sport identifier

## Key Differences from Football

| Aspect | Football | NBA/NHL |
|--------|----------|---------|
| Outcomes | 3-way (H/D/A) | 2-way (H/A) |
| Draw handling | Explicit class | N/A (OT decides) |
| Spread betting | Limited | Core market |
| Totals | Less common | Core market |
| Home advantage | ~45% win rate | ~55% win rate |
| Score volatility | Low (0-5) | High (80-130 NBA, 0-8 NHL) |

## Future Improvements

1. **More Training Data**: Current models trained on ~70 games each. Target 500+ games for robust models.

2. **Team-Level Features**: 
   - Historical win rates
   - Back-to-back game fatigue
   - Home/away splits
   - Recent form

3. **Player-Level Features**:
   - Key player injuries
   - Rest days
   - Star player performance

4. **Sharp Book Intelligence**:
   - Track Pinnacle and sharp bookmaker odds
   - Calculate CLV (Closing Line Value)
   - Reverse line movement detection

5. **Live Betting**:
   - In-play odds tracking
   - Momentum scoring
   - Live predictions

## Scheduler Configuration

Located in `utils/scheduler.py`:

```python
# Multi-Sport Odds Collection - runs every 60 minutes (reduced from 5min)
if "multisport_odds" not in self.last_run or (now - self.last_run["multisport_odds"]).total_seconds() >= 3600:
    await self._spawn("multisport_odds", self._run_multisport_odds_collection, timeout=120)

# Multi-Sport Results - runs every hour
if "multisport_results" not in self.last_run or (now - self.last_run["multisport_results"]).total_seconds() >= 3600:
    await self._spawn("multisport_results", self._run_multisport_results_collection, timeout=60)
```

## Troubleshooting

### LightGBM libgomp Error
If you see `libgomp.so.1: cannot open shared object file`:
```bash
export LD_LIBRARY_PATH="$(gcc -print-file-name=libgomp.so | xargs dirname):$LD_LIBRARY_PATH"
```

### Empty Training Table
Run the sync manually:
```bash
python -c "from training.multisport_training_sync import sync_training_data; sync_training_data()"
```

### Missing Features
Check that odds snapshots exist for the event:
```sql
SELECT COUNT(*) FROM multisport_odds_snapshots WHERE event_id = 'YOUR_EVENT_ID';
```

## Files Reference

| File | Purpose |
|------|---------|
| `models/multisport_collector.py` | Data collection from The Odds API |
| `training/multisport_training_sync.py` | Sync completed games to training table |
| `training/train_v2_multisport.py` | Model training script |
| `utils/scheduler.py` | Background collection scheduling |
| `docs/MULTISPORT.md` | This documentation |
