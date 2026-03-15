# BetGenius AI — Central API Documentation

> **Base URL (production):** your deployed domain  
> **Base URL (dev):** `https://$REPLIT_DEV_DOMAIN`  
> **Authentication:** All protected endpoints require the header  
> `Authorization: Bearer betgenius_secure_key_2024`  
> Endpoints marked **[Public]** do not require auth.

---

## Table of Contents

1. [Health & Status](#1-health--status)
2. [Soccer Predictions](#2-soccer-predictions)
3. [NBA / NHL Predictions (Multisport)](#3-nba--nhl-predictions-multisport)
4. [Betting Intelligence & CLV](#4-betting-intelligence--clv)
5. [Trending & Hot Matches](#5-trending--hot-matches)
6. [Parlay Recommendations](#6-parlay-recommendations)
7. [Player Statistics & Predictions](#7-player-statistics--predictions)
8. [Metrics & Model Evaluation](#8-metrics--model-evaluation)
9. [Admin & Data Collection](#9-admin--data-collection)
10. [WebSocket — Live Betting](#10-websocket--live-betting)
11. [Training Scripts Reference](#11-training-scripts-reference)
12. [Background Jobs Reference](#12-background-jobs-reference)

---

## 1. Health & Status

### `GET /healthz` [Public]
Ultra-lightweight liveness probe. Returns `{"status": "ok"}`. Used by auto-scaling checks.

### `GET /health`
Detailed health check including consensus model coverage guardrails, database connection, Redis status, and model availability.

**Response fields:** `status`, `database`, `redis`, `models`, `consensus_coverage`

### `GET /predict/health`
Dedicated health check for the prediction subsystem. Reports which model version is active and data availability.

---

## 2. Soccer Predictions

### `POST /predict` [Public — no auth on examples]
**Primary soccer prediction endpoint.** Uses the V3 Binary Expert Ensemble as first choice, falling back through V1 Weighted Consensus → V0 Form-Only based on data availability.

**Request body:**
```json
{
  "home_team": "Arsenal",
  "away_team": "Chelsea",
  "match_id": "optional-string"
}
```

**Response highlights:**
- `predictions` — array of up to 3 model outputs:
  ```json
  [
    {
      "model": "v3_sharp",
      "home_win": 0.52,
      "draw": 0.25,
      "away_win": 0.23,
      "conviction_tier": "HIGH"
    },
    ...
  ]
  ```
- `conviction_tier` — `HIGH / MEDIUM / LOW / VERY_LOW` based on model agreement and margin
- `shadow_log_id` — reference for internal performance tracking

**Models in cascade:**
| Priority | Model | Description |
|---|---|---|
| 1 | V3 Sharp | 36-feature stacked ensemble with sharp book data |
| 2 | V1 Consensus | Weighted consensus across calibrated classifiers |
| 3 | V0 Form | ELO-only fallback (no odds required) |

---

### `POST /predict-v2`
V2 LightGBM model endpoint with market + ELO features. Kept for backward compatibility.

**Request:** same as `/predict`  
**Response:** single model output with H/D/A probabilities

---

### `POST /predict-v3`
Direct access to V3 Sharp model. Returns raw V3 output including 34-feature values, calibrated probabilities, and league-aware ECE weights.

### `GET /predict-v3/status`
Returns V3 model status: training date, sample count, feature list, and accuracy/LogLoss on the holdout set.

### `GET /predict/which-primary`
Shows which model is currently active as the primary production model.

### `GET /market`
Returns a prediction enriched with market context — implied probabilities from consensus odds, overround, and value edges.

**Query params:** `home_team`, `away_team`

---

### `GET /matches/upcoming`
Lists upcoming matches seeded in the fixture table. Shows consensus odds and predicted probabilities.

**Query params:** `sport` (default `soccer`), `days_ahead` (default 7)

### `GET /matches/search`
Fuzzy search for teams across all upcoming fixtures.

**Query params:** `q` (team name fragment)

### `GET /leagues`
Lists all leagues/competitions tracked in the database.

### `GET /teams`
Lists all teams with their ELO ratings and league membership.

---

## 3. NBA / NHL Predictions (Multisport)

### `POST /predict-multisport`
**Full-fidelity NBA/NHL prediction endpoint.** Mirrors soccer's `/predict` richness: V3 LightGBM model, 5 betting markets, team context, H2H, optional GPT-4o analysis.

**Request body:**
```json
{
  "sport_key": "basketball_nba",
  "event_id": "uuid-string",
  "include_analysis": true
}
```
`sport_key` options: `basketball_nba`, `icehockey_nhl`

**Response structure:**
```json
{
  "match_info": {
    "home_team": "...",
    "away_team": "...",
    "commence_time": "2026-01-15T19:00:00Z",
    "league_name": "NBA"
  },
  "predictions": {
    "home_win": 0.61,
    "away_win": 0.39,
    "no_draw": true,
    "conviction_tier": "HIGH",
    "pick": "home",
    "confidence": 0.61
  },
  "model_info": {
    "version": "v3_multisport",
    "type": "lightgbm",
    "n_features": 46,
    "feature_groups": ["odds", "spread_totals", "rest_schedule", "team_form", "elo", "h2h", "season_context"]
  },
  "markets": [...],
  "team_context": {...},
  "h2h": {...},
  "odds": {...},
  "feature_values": {...},
  "analysis": "GPT-4o narrative (if include_analysis=true)",
  "processing_time_ms": 320
}
```

**5 Market Types returned:**

| Market Type | Key | Description |
|---|---|---|
| Moneyline | `moneyline` | H/A win probabilities vs implied odds |
| Spread | `spread` | Point spread (NBA) / Puck line (NHL) with edge |
| Game Total | `total` | Over/Under with model vs market probs |
| First Half/Period Total | `first_half_total` | First-half total for NBA; 1st period for NHL |
| Team Totals | `team_totals` | Per-team projected scoring vs market lines |

Each market option includes: `model_prob`, `implied_prob`, `decimal_odds`, `edge`

**Model performance:**
| Sport | Accuracy | LogLoss | Training samples |
|---|---|---|---|
| NBA | 85.6% | 0.346 | 410 |
| NHL | 70.7% | 0.531 | 341 |

---

### `GET /predict-multisport/available`
Lists upcoming NBA/NHL fixtures with model picks and confidence scores.

**Query params:** `sport` (`basketball_nba` or `icehockey_nhl`), `days_ahead` (default 7)

**Response:** array of fixtures with `event_id`, `home_team`, `away_team`, `commence_time`, `spread`, `total_line`, `model_pick`, `model_confidence`

---

## 4. Betting Intelligence & CLV

### `GET /betting-intelligence`
Returns a curated list of current value opportunities across all tracked matches — sorted by edge, filtered by minimum confidence threshold.

**Response:** list of opportunities with `match`, `market`, `edge`, `kelly_fraction`, `clv_projection`

### `GET /betting-intelligence/{match_id}`
Per-match betting intelligence: current CLV estimate, edge on each market, Kelly sizing recommendation.

**Response fields:** `clv_current`, `clv_at_close_projection`, `edge_by_market`, `kelly_quarter`, `line_history`

---

### CLV Dashboard Endpoints

| Endpoint | Description |
|---|---|
| `GET /clv/dashboard` | Overall CLV summary dashboard |
| `GET /clv/match/{match_id}` | CLV tracking for a single match |
| `GET /clv/opportunities` | Current open CLV opportunities |
| `GET /clv/alerts` | Active CLV movement alerts |
| `GET /clv/club/daily` | Daily CLV club report |
| `GET /clv/club/stats` | CLV club aggregate stats |
| `GET /clv/club/opportunities` | CLV club curated opportunities |
| `GET /clv/club/realized` | Realized CLV on settled bets |
| `GET /clv/club/alerts/history` | Historical CLV alert log |

---

## 5. Trending & Hot Matches

Prefix: `/api/v1/trending`

### `GET /api/v1/trending/hot`
Matches currently trending as "hot" — high betting volume, sharp movement, or model divergence from market. Backed by Redis with DB fallback.

**Query params:** `limit` (default 10), `sport`

### `GET /api/v1/trending/trending`
Matches with sustained upward trending signals over the past 24 hours.

### `GET /api/v1/trending/status`
Health and freshness status of the trending computation pipeline.

---

## 6. Parlay Recommendations

Prefix: `/api/v1/parlays`

### `GET /api/v1/parlays`
Returns the current list of AI-curated parlay recommendations.

**Response fields per parlay:** `legs`, `combined_probability`, `correlation_adjusted_prob`, `decimal_odds`, `edge`, `confidence_tier`

### `GET /api/v1/parlays/recommended`
Top recommended parlays filtered by minimum edge and confidence threshold.

### `POST /api/v1/parlays/build`
Build a custom parlay from a user-specified list of match/market selections. Returns correlation-adjusted odds and edge estimate.

**Request body:**
```json
{
  "legs": [
    {"match_id": "...", "market": "moneyline", "selection": "home"},
    {"match_id": "...", "market": "total", "selection": "over"}
  ]
}
```

### `GET /api/v1/parlays/status`
Parlay engine status and last computation timestamp.

### `GET /api/v1/parlays/performance`
Historical performance of parlay recommendations (hit rate, ROI, by confidence tier).

### `GET /api/v1/parlays/health`
Health check for the parlay computation subsystem.

---

## 7. Player Statistics & Predictions

Prefix: `/api/v1/players`

### `GET /api/v1/players/top-scorers/{sport}`
Top scorers for the given sport (`soccer`, `nba`, `nhl`) in the current season.

### `GET /api/v1/players/search/{sport}`
Search players by name fragment within a sport.

**Query params:** `q` (name fragment), `limit`

### `GET /api/v1/players/stats/{sport}/{season}`
Full player stats table for a sport and season.

**Query params:** `team`, `position`, `min_games`

### `GET /api/v1/players/summary`
Cross-sport summary: total players tracked, stats coverage, last collection timestamp.

### `GET /api/v1/players/game-history/{player_id}`
Game-by-game stat history for a specific player.

### `POST /api/v1/players/collect/{sport}`
Trigger a player stats collection job for the given sport. Admin use.

### `POST /api/v1/players/collect-game-stats`
Trigger collection of per-game player stats (box scores). Admin use.

---

### Player Performance Predictions (V2-Player)

| Endpoint | Description |
|---|---|
| `POST /predict-player` | Predict goal involvement + goals scored for a player in a given match |
| `GET /predict-player/available` | Players with sufficient data for V2-Player prediction |

**Predict request:**
```json
{
  "player_id": 123,
  "match_id": "abc",
  "home_team": "Arsenal",
  "away_team": "Chelsea"
}
```

**Response:** `goal_involvement_prob`, `expected_goals`, `expected_assists`, `confidence`

---

## 8. Metrics & Model Evaluation

### `GET /metrics/summary`
High-level model performance summary: accuracy, LogLoss, Brier score across all active models.

### `GET /metrics/evaluation`
Detailed holdout evaluation with calibration curves, ECE by league, and probability buckets.

### `GET /metrics/match/{match_id}`
Prediction log entry for a specific match — model used, predicted probs, actual result, CLV delta.

### `GET /metrics/ab`
A/B test status between active model versions. Shows sample counts and statistical significance.

### `GET /metrics/clv-summary`
Aggregated CLV performance across all settled matches.

### `GET /metrics/temperature-scaling`
Current temperature scaling calibration parameters for each model.

### `POST /metrics/compute`
Trigger a metrics recompute pass over the prediction log.

### `POST /metrics/result`
Log an actual match result against a pending prediction.

### `GET /internal/metrics/api`
Internal API call volume and latency metrics dashboard (HTML page).

### `GET /consensus/sync`
Sync status for the consensus odds aggregation pipeline.

---

## 9. Admin & Data Collection

All admin endpoints require `Authorization: Bearer betgenius_secure_key_2024`.

### `GET /admin/stats/live-betting`
Live betting system stats: open WebSocket connections, event count, last update time.

### `GET /admin/stats/resolver`
Fixture ID resolver stats: cross-source match rate, unresolved count, last run.

### `GET /admin/training-stats`
Training data volume by sport, model, and date range.

### `GET /admin/team-stats`
Team record counts in `multisport_team_stats` by sport.

### `POST /admin/retrain-models`
Trigger a model retraining cycle. Supports selective retraining by model version.

**Request body:**
```json
{
  "models": ["v3", "multisport_nba", "multisport_nhl"],
  "force": false
}
```

### `POST /admin/collect-recent-matches`
Collect results and stats for recently completed matches.

### `POST /admin/collect-single-league`
Collect data for a specific league by ID.

**Request body:** `{"league_id": 39, "season": 2025}`

### `POST /admin/collect-training-data`
Bulk historical data collection for model training.

### `POST /admin/daily-collection-cycle`
Trigger the full daily pipeline: fixtures → odds → results → feature computation.

### `POST /admin/enrich-tbd-fixtures`
Enrich fixtures where team names are TBD using API lookup.

### `POST /admin/enrich-tbd-batch`
Batch TBD enrichment for multiple leagues.

### `POST /admin/enrich-tbd-one`
Enrich a single TBD fixture by event ID.

### `POST /admin/enrich-team-logos`
Pull and store team logo URLs for all tracked teams.

### `POST /admin/link-fixtures-to-teams`
Link orphaned fixture records to their canonical team IDs.

### `POST /admin/targeted-collection`
Targeted collection for a specific fixture ID or date range.

### `GET /admin/collection-history`
Log of recent data collection runs: source, records fetched, errors.

---

## 10. WebSocket — Live Betting

### `WebSocket /ws/live/{match_id}`
Real-time live betting stream for an in-progress match.

**Connection:** Standard WebSocket upgrade with Bearer token in query param or header.

**Message types received:**
```json
{"type": "odds_update", "data": {...}}
{"type": "score_update", "data": {...}}
{"type": "prediction_update", "data": {...}}
{"type": "clv_alert", "data": {...}}
```

**Ping/keep-alive:** Send `{"type": "ping"}` — server responds `{"type": "pong"}`.

---

## 11. Training Scripts Reference

All scripts live in the `training/` directory and are run manually or via the auto-retrain job.

### Soccer Models

| Script | Output model | Notes |
|---|---|---|
| `train_v0_form.py` | V0 Form-only (ELO) | No odds needed; trained on all historical matches |
| `train_v0_fast.py` | V0 fast variant | Lighter feature set for rapid iteration |
| `train_v2_lgbm.py` | V2 LightGBM | Market + ELO features; dry run / pipeline validation |
| `train_v2_production.py` | V2 production | Full V2 feature set for production promotion |
| `train_v2_improved.py` | V2 improved | Enhanced feature engineering experiments |
| `train_v2_odds_only.py` | V2 odds-only | Ablation: odds features only |
| `train_v3_sharp.py` | V3 Sharp | 34 features incl. sharp book + calibrated ECE weights |
| `train_v3_full.py` | V3 Full | Full V3 pipeline with all feature groups |
| `train_v3_temporal.py` | V3 temporal | Strict walk-forward temporal validation |
| `train_stacked_ensemble.py` | Stacked ensemble | Meta-learner over V2/V3 base models |
| `train_voting_ensemble.py` | Voting ensemble | Simple voting across calibrated classifiers |
| `train_binary_experts.py` | Binary experts | Per-outcome specialist models (H/D/A) |
| `train_lgbm_historical_36k.py` | V3 on 36k samples | Full historical dataset training run |
| `create_simple_ensemble.py` | Weighted consensus | Final production ensemble weighting |

### Multisport Models

| Script | Output model | Notes |
|---|---|---|
| `train_multisport_v3.py` | NBA + NHL V3 | 46 features, 7 groups; binary H/A classifier |
| `train_v2_multisport.py` | Multisport V2 | Earlier iteration; V3 supersedes this |
| `train_v2_nba.py` | NBA V2 | NBA-specific V2 training |

### Player Models

| Script | Output model | Notes |
|---|---|---|
| `train_player_v2.py` | V2-Player | Goal involvement (binary) + goals/assists (regression) |

### Utilities & Diagnostics

| Script | Purpose |
|---|---|
| `leak_detector.py` | Detects temporal leakage in feature pipelines |
| `leak_detector_v2.py` | V2 leak detection with stricter walk-forward checks |
| `leak_detector_ablation.py` | Ablation study of features suspected of leaking |
| `step_a_optimizations.py` | Gradient / LR optimization sweeps |
| `multisport_training_sync.py` | Syncs completed multisport match results for retraining |

---

**How to run a training script:**
```bash
python training/train_multisport_v3.py
# or force a retrain via the admin API:
curl -X POST https://<host>/admin/retrain-models \
  -H "Authorization: Bearer betgenius_secure_key_2024" \
  -d '{"models": ["multisport_nba", "multisport_nhl"]}'
```

---

## 12. Background Jobs Reference

All scripts live in the `jobs/` directory and are scheduled or triggered by the admin endpoints.

| Script | Trigger | Purpose |
|---|---|---|
| `auto_retrain.py` | Scheduled / admin | Checks data volume, staleness, accuracy drift; triggers retraining when thresholds exceeded |
| `backfill_historical_odds.py` | Manual | Backfills odds snapshots for historical fixtures |
| `backfill_multisport_features.py` | Manual | Recomputes 46-feature vectors for completed NBA/NHL matches |
| `backfill_parlay_leg_results.py` | Post-match | Settles open parlay legs against actual results |
| `backfill_prediction_log.py` | Manual | Fills gaps in the unified prediction log |
| `backfill_team_injury_summary.py` | Manual | Backfills injury impact summaries for team stats |
| `collect_multisport_team_stats.py` | Scheduled | Refreshes season standings and team stat tables for NBA/NHL |
| `compute_ev_clv.py` | Post-close | Computes EV and realized CLV after line close |
| `compute_historical_features_batch.py` | Manual | Batch feature computation across date ranges |
| `compute_historical_features_fast.py` | Manual | Fast feature computation for recent windows |
| `compute_market_features.py` | Scheduled | Updates market features (drift, dispersion) from latest odds |
| `compute_trending_scores.py` | Scheduled | Recomputes trending/hot scores and writes to Redis |
| `elo_recompute.py` | Weekly | Full ELO rating recomputation across all leagues |
| `import_csv_historical_odds.py` | Manual | Imports bulk historical odds from CSV exports |
| `injury_collector.py` | Daily | Collects latest injury reports and player availability |
| `league_ece_calculator.py` | Weekly | Recomputes Expected Calibration Error weights by league |
| `retrain_v3_background.py` | Auto | Background V3 retraining triggered by auto_retrain.py |
| `settle_parlays.py` | Post-match | Settles open parlays and updates performance logs |
| `sync_fixtures_to_matches.py` | Daily | Syncs new fixtures from canonical table to matches table |

---

## Feature Groups Reference

### Soccer V3 (36 features)
`Odds` · `Drift` · `ELO` · `Form` · `H2H` · `Sharp Book`

### NBA / NHL V3 (46 features)
| Group | Examples |
|---|---|
| Odds | home_odds, away_odds, home_implied_prob, overround |
| Spread / Totals | home_spread, total_line, spread_implied, over_implied |
| Rest / Schedule | home_days_rest, away_days_rest, home_b2b, away_b2b |
| Team Form | home_win_pct_l10, away_win_pct_l10, home_pts_pg_l10 |
| ELO | home_elo, away_elo, elo_diff |
| H2H | h2h_home_wins, h2h_away_wins, h2h_avg_total |
| Season Context | days_until_playoffs, home_home_win_pct, season_progress |

---

*Last updated: March 2026 — BetGenius AI v3 Multisport Release*
