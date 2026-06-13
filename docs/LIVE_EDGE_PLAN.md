# Snapbet Live Edge — In-Game Prediction & Value Model

**Date:** 2026-06-13 · **Status:** design (grounded in current infra)
**Companions:** `utils/edge.py` (value layer — reuse), `docs/FRONTEND_EDGE_MANUAL.md`,
`docs/MULTISPORT_EDGE_PLAN.md`. Same discipline as the rest of the pivot:
two layers — (1) what happens next, (2) is the live price wrong — and **no edge
claim ships until it beats a baseline on a holdout.**

---

## 1. What we already have (verified 2026-06-13)

The single most important fact: **we are already collecting the match-state side.**

| Asset | State | Maps to the spec's… |
|-------|-------|---------------------|
| `live_match_stats` (every 60s) | ✅ flowing — captured USA–Paraguay end-to-end | snapshot table: minute, period, scores, possession, shots, shots_on_target, corners, yellow/red cards, fouls, offsides |
| `match_events` | ✅ flowing — minute + score_home/away per goal/card | **labels**: when did the next goal happen → target_more_goal / target_next_goal |
| `utils/edge.py` | ✅ built | the entire **value layer**: de-vig, EV, edge, Kelly, calibration-ready, `value_rating` |
| Isotonic calibration pattern | ✅ proven (V3, props) | §7 probability calibration |
| Temporal-holdout harness | ✅ `validate_temporal_holdout.py` | §16 backtest discipline |
| live collector window | ✅ runs every 55s for matches kicked off ≤150 min ago | the 30–60s update loop |

**The one missing input: in-play odds.** `odds_snapshots` stops at kickoff
(`secs_to_kickoff < 0` → 0 rows). So today we can build **Layer 1 (what happens
next)** fully, but **Layer 2 (is the price wrong)** is blocked until we collect
live odds. This is the critical-path dependency, called out everywhere below.

**Implication:** we do NOT need a new snapshot table or a new collector to start —
`live_match_stats` IS the snapshot store. We need a feature/label layer on top,
in-play odds, and the models. That collapses the spec's "Week 1: build collectors"
into "Week 1: we already have them, start labeling."

---

## 2. Scope (start narrow, exactly as proposed)

**Product: "Snapbet Live Edge" — 70'+ window, two markets first:**
1. **Over 0.5 more goals** (will another goal come before FT?) — most readable
2. **Next goal: home / away / none** — strong when one side is dominating

Defer: Over 1.5 more, result-holds, DNB — add once the first two validate.

---

## 3. Architecture (reusing what exists)

```
live_match_stats + match_events   ← already flowing (Layer-1 inputs)
        ↓
live_feature_builder.py (NEW)     ← rolling windows + pressure score, leak-safe
        ↓
live LightGBM models (NEW)        ← Over0.5 / NextGoal, isotonic-calibrated
        ↓                            (same recipe as V3/props)
in-play odds  (NEW COLLECTION)    ← BLOCKER for value; The Odds API in-play / API-Football live
        ↓
utils.edge  (REUSE)               ← EV, edge, value_rating, no_value default
        ↓
alert engine (NEW)                ← thresholds + TTL + dedupe + "why" explanation
        ↓
/predict-live endpoint + push     ← FastAPI (existing), additive payload
```

No Redis required for v1 — `live_match_stats` already persists every snapshot;
read the last N rows for rolling features. Add Redis only if inference latency
becomes a problem at scale.

---

## 4. Targets (labeled from match_events — no new data)

For each `live_match_stats` snapshot at minute m, derive from `match_events`:
- `target_more_goal` = 1 if any goal event has minute > m, else 0
- `target_next_goal` ∈ {home, away, none} = team of the first goal event after m
- `target_result_holds` = 1 if FT outcome == outcome implied by score at m

These are pure SQL joins on data we already store. **We can label every
historical live snapshot we've collected today, retroactively.**

---

## 5. Features (all derivable from live_match_stats history)

- **Clock/score** (free, non-negotiable): minute, est. remaining, score, goal_diff,
  is_tied, favorite_trailing (needs pre-match prob — we have it), is_knockout.
- **Pre-match anchor**: V3/consensus pre-match probs + league avg goals (we store these).
- **Live cumulative**: shots, SoT, corners, cards, fouls, possession (direct columns).
- **Momentum (rolling)**: deltas over last 5/10/15 min by diffing prior snapshots
  → `shots_last_10`, `sot_last_10`, `corners_last_10`, `possession_delta_10`.
- **Pressure score**: the weighted composite from the spec, normalized by league.

`live_feature_builder.py` mirrors the leak-safe pattern of `v3_feature_builder`:
every feature uses only snapshots at or before minute m.

---

## 6. Phased build (grounded order, not calendar weeks)

| Phase | Work | Gate / proof | Blocker |
|-------|------|-------------|---------|
| **0** | Widen live collection to start logging at 55' for ALL live matches; confirm snapshot density (≥1/min in 70–90'). Mostly already happening. | ≥10 matches with dense 70'+ snapshots | none |
| **1** | `live_feature_builder.py` + label snapshots from match_events. Backtest the **"77' intuition"**: is Over-0.5-more profitable by minute bucket / score-state? | enough snapshots (target ~5–10k) → measurable hit rates | volume (accrues as WC + leagues play) |
| **2** | Rule-based **Late Edge score** scanner (spec §13). Ships a watchlist UI with NO model + NO odds — pure pressure/score-state heuristic. | qualitative: does it flag the right games? | none |
| **3** | **In-play odds collection** — the value blocker. Add a live-odds task (The Odds API in-play `markets=totals`/scorer, or API-Football live odds) writing to a `live_odds_snapshots` table. | in-play odds landing for live matches | NEW COMPUTE (call out re: bill) |
| **4** | LightGBM **Over 0.5 / Next Goal** models + isotonic calibration. | Brier/logloss + reliability curve; **calibrated**, not just accurate | Phase 1 volume |
| **5** | Wire **utils.edge** value layer + alert engine (thresholds, TTL 30–90s, dedupe, "why" string). | **CLV/EV holdout** vs live price — no edge claim until positive | Phase 3 odds |

**Honest critical path:** Layers 1–2 (probability + rules) need only data we
already collect. The **value product** (the moat) needs Phase 3 in-play odds,
which is net-new collection cost — to be weighed against the Replit bill.

---

## 7. Validation discipline (same as the rest of the pivot)

- Calibration first: Brier, log-loss, reliability curve. A live model that says
  50% must hit ~50%.
- Value gate: simulate betting only `edge > threshold` snapshots at the live
  price, measure ROI **and CLV vs the closing/last-pre-FT price**. This is the
  in-game analog of `validate_temporal_holdout.py`.
- Register `live_edge_over05` / `live_edge_nextgoal` in `utils.edge.MODEL_REGISTRY`
  with `edge_validated=False` until they pass. **No "Snapbet probability beats
  the market" language in the UI until the holdout says so.**

## 8. Why this is the most promising model we have

Pre-match V3 failed because mainline pre-match markets are maximally efficient.
**In-play markets are softer** (books re-price under time pressure with thinner
liquidity), and we hold a real-time signal — established game dynamics (18 shots
vs 2 shots at 0–0 77') — that the live price may underweight. This is the same
"thin/soft segment" thesis that made the WC ELO model work (+15pp). It's the
strongest theoretical case for genuine edge in the whole platform — *if* Phase 3
live odds confirm it on a CLV holdout.

## 9. Naming
Internal: `snapbet_live_edge_v1` · User-facing: **Snapbet Live Edge** (alt:
"Final 20 Edge", "Late Goal Radar").
