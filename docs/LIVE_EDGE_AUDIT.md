# Live Edge — Audit: what's real vs static vs missing (2026-06-14)

Verified against the live Haiti–Scotland match. Honest accounting of what is real
data, what is a static/heuristic placeholder, and what is missing or not deployed.
Nothing here is a test failure (suite: 175 passed) — these are product-readiness gaps.

## 🔴 NOT DEPLOYED (works on branch, not in production)
- **`live_odds_collector` is NOT on `origin/main`** → production collects **no in-play
  odds**. The `/live-edge` board exists in prod but its value layer (edge/EV/BETTABLE)
  is null there. The live odds only flowed in testing because the collector was run
  by hand. **Deploy unblocks this.**
- `live_match_snapshots` / `live_odds_snapshots` tables: created on the DB via
  migration here, but the **persistent snapshot write path isn't running in prod**
  until deploy — so no training data accumulates yet.

## 🟠 DATA QUALITY — live stats can freeze (needs a guard)
- Haiti–Scotland: `live_match_stats` timestamp was **fresh (updating each poll)** but
  `minute` was **frozen ~48–49** while real match time was ~73', and shots/score were
  unchanged across snapshots. API-Football's live stats feed lagged/stalled for this
  fixture. **Impact:** win-prob computed at minute 49 overstates remaining time →
  overstates P(more goal). **Missing:** a staleness/minute-sanity guard (e.g. trust
  `fixture.status.elapsed`, drop matches whose stats haven't advanced in N polls,
  mark `data_quality` on the card). This is exactly the "odds/stats stale → no bet"
  exclusion the spec framework calls for, not yet enforced.

## 🟡 STATIC / HEURISTIC priors (expected for v1, NOT trained/calibrated)
The live win-probability is a **principled Poisson prior, not a trained model**.
These constants are reasonable defaults but are NOT data-derived and should be
replaced by the nightly LightGBM + calibration once snapshots accumulate:
- `DEFAULT_TOTAL_XG = 2.7`, home/away split `0.53/0.47` (`live_win_probability.py`)
- `MATCH_MINUTES = 92` (fixed stoppage assumption — real stoppage varies)
- Red-card multipliers `0.80 / 1.25` (literature rough, not fit to our data)
- `prematch_total_goals = 2.6` in the Poisson prior (`live_feature_builder.py`)
- Pressure-score weights + the `×10/×15/×8` scaling and `_PRESSURE_HEAT = 25`
  (`live_edge.py`) — heuristic, uncalibrated; the `pressure_percentile_min: 70`
  in the spec has **no league baseline table yet** to compute the percentile from.
- BETTABLE thresholds (`ev>0`, odds_age ≤30s, price ≥1.85) — sensible but not
  validated against CLV outcomes.

## 🟡 MISSING DATA the spec assumes
- **xG**: live feed has shots/SoT/corners but **no xG column** — the spec's best
  pressure signal is absent. Either source it or compute a shots→xG proxy.
- **Per-book live odds**: `/odds/live` gives one consensus line, not per-bookmaker,
  so `best_price.book` is `"live_consensus"` — true line-shopping (best across books)
  isn't available on this feed. `min_acceptable_odds` / price-guard still work.
- **League baseline table** for pressure percentiles and league-reliability scoring
  (spec exclusion rule) — not built.
- **`strategy_alerts` table** (audit trail / label factory) — designed, not built.

## ✅ REAL (verified live)
- Live match state (score/shots/SoT/corners/possession/cards) — real, from API-Football.
- Live odds (1X2, totals, BTTS) — real, via `/odds/live` (proven: 25–50 rows/match).
- Win-probability + advanced markets — real computation off real inputs.
- Edge/EV/value verdict — real, and honest: returned `no_value` when the market
  priced a goal higher than the model (prediction ≠ edge, working).
- Strategy-spec governance (load/validate/hash) — real and enforced.

## Bottom line
The pipeline is real and correct end-to-end on the branch. The gaps are: (1) **deploy**
to make in-play odds + persistence run in prod, (2) a **stats-staleness guard** (real
bug exposed by Haiti–Scotland), (3) the **static priors are a v1** awaiting the nightly
trained model + calibration, (4) **xG / per-book odds / league baselines / alert audit
table** are not yet sourced. None block shipping Layer-1 intelligence; all gate the
validated *betting* product.
