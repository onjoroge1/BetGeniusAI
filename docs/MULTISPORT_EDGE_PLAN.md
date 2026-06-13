# Multisport + Player Props Edge Conversion Plan

**Date:** 2026-06-13 · **Scope:** `/market-multisport`, `/predict-multisport/results`, `/predict-player` (+ `/top-picks`)
**Goal:** the same accuracy→edge pivot already shipped for soccer `/predict` and WC.
**Companions:** `utils/edge.py` (engine), `docs/FRONTEND_EDGE_MANUAL.md` (contract), `docs/FRONTEND_EDGE_QA.md` (QA gates).

---

## 1. Current state (verified against code + DB, 2026-06-13)

| | `/market-multisport` | `/predict-multisport/results` | `/predict-player` + `/top-picks` |
|---|---|---|---|
| Model | `MultisportV3Predictor` (LightGBM per sport: basketball/hockey/football) | same | `PlayerPropsService` (goal-involvement + goals-regression ensembles, isotonic-calibrated) |
| Framing today | `pick` + `confidence` (with **spread-based confidence floors up to 88%** — accuracy-era hacks) | accuracy %, confidence buckets, W/L streak | probability + High/Med/Low confidence; top-picks **ranked by raw probability** |
| Market data in hand | ✅ consensus + per-book odds **already fetched in-route** (12 books) | ✅ odds in results query | ⚠️ `player_prop_odds` exists & current (NBA 8 books; NHL 2) but **not joined** |
| Validation status | OOF-only (same trap as soccer V3 pre-holdout) — never tested vs favorite baseline | n/a | props models have no holdout record vs prices |
| Keying | `event_id` + `sport_key` (not match_id) | same | `player_id` + `match_id` vs odds keyed by `player_name` + `event_id` |

**Three verified data facts that shape the plan:**
1. `multisport_odds_snapshots`: 12 bookmakers recent for MLB/NHL/NBA — consensus (de-vig source) and best-price are computable from data the routes already load. **No new queries needed for Phase B.**
2. `player_prop_odds` is alive (updated today): `player_points` 10.7k rows/8 books, rebounds/assists/threes ~5k each, NHL `player_goals` 1.3k/2 books. **401 of 667 multi-book props carry different LINES across books** — props line-shopping is two-dimensional (price AND line).
3. **The real props blocker:** `player_name_aliases` (odds-API name → internal player_id bridge) has **0 rows**. The odds exist; the join doesn't. Also note a cross-shaped gap: rich odds are NBA/NHL while the trained props models are soccer — and soccer anytime-scorer odds are thin in the table despite the 4-hourly collection task (audit why in Phase C0).

---

## 2. Design decisions

### D1 — Generalize `utils/edge.py` to dynamic outcome sets
Today `OUTCOMES = ("home","draw","away")` is hardcoded. Change every core function to accept
`outcomes: tuple` (default 3-way for back-compat). Two-way canonical bets: `home→home_win`,
`away→away_win`. All math (de-vig, EV, Kelly, ratings, parlay) is already outcome-agnostic.

### D2 — Props are a different market shape: add a binary-prop helper
A prop is `p_model(yes)` vs an over/under (or yes-only) price:
- **O/U pairs** (NBA points etc.): de-vig from the over+under prices at the SAME line; edge per side.
- **Yes-only markets** (anytime scorer): no de-vig possible without the "no" price → skip the
  `edge` field, compute **EV at price** directly (`p×odds−1`), which is all `value_bet` needs.
- **Line shopping is (line, price) pairs**: group offers by line; EV computed per offer at the
  model's probability *for that line* (needs the regression model's distribution, v2) — v1 rule:
  only compare offers at the **modal line**, surface best price there; flag off-line offers as
  "alt-line" without EV claims.

### D3 — Honesty registry before edge claims (non-negotiable)
Register `v3_multisport_basketball/hockey/football` and `player_props_soccer` as
`edge_validated: false`. Each flips to true ONLY by passing its own temporal holdout vs the
favorite/market baseline (reuse the `validate_temporal_holdout.py` pattern; truth tables exist:
`multisport_match_results`, `player_game_stats`). Until then the UI shows probabilities +
market panel, no "proven edge" language (per FRONTEND_EDGE_QA §8).

### D4 — Retire accuracy-era artifacts (don't port them)
- Spread-based confidence floors/caps (88% floor!) in `multisport_v3_predictor.py` — replace
  with calibrated probability + edge; these rules exist to make confidence *look* right.
- `/predict-multisport/results` accuracy buckets stay as a *diagnostics* section, but the
  headline becomes edge metrics (below).

### D5 — Multisport "closing line" for CLV
`multisport_odds_snapshots` retains 30 days — the last pre-`commence_time` snapshot per event
is a retrospective closing proxy (same `last_prekickoff` approach as soccer). No new collection.

---

## 3. The plan, phased

### Phase A — Engine generalization (~½ day)
1. `utils/edge.py`: thread `outcomes` through `devig_proportional`, `implied_probs_from_odds`,
   `compute_edge`, `select_value_bet`, `build_value_payload`; add `_CANONICAL_BET` for 2-way.
2. New `prop_value(p_model, offers)` helper implementing D2 (O/U de-vig, yes-only EV, modal-line rule).
3. Registry entries per D3.
4. Tests: extend `tests/edge/` — 2-way devig/EV/value-bet, prop O/U pair, yes-only market,
   modal-line selection, 2-way parlay legs. **All existing 3-way tests must stay green.**

### Phase B — `/market-multisport` + `/predict-multisport/results` (~1 day)
1. In-route (data already in memory): build `market`/`value`/`clv` per game via
   `build_value_payload(model_probs, consensus_raw, best_prices, outcomes=("home","away"))`
   where `best_prices` = max odds across the `books` dict. Attach `model_track_record`.
2. Keep legacy `model.predictions` block untouched (back-compat).
3. `/predict-multisport/results`: per-game `edge_analysis` (model prob vs de-vigged market,
   was-the-disagreement-right) + summary `edge_metrics`:
   `median_clv` (vs last-pre-commence snapshot), `ev_weighted_return` (1u on every value_bet),
   `disagreement_hit_rate` — accuracy buckets demoted to a `diagnostics` sub-object.
4. **Gate B (per sport, before any `edge_validated:true`):** temporal holdout — model vs
   "pick the consensus favorite" on `multisport_match_results`. Expect NBA/MLB mainlines to
   FAIL (most efficient markets on earth) — that's fine and honest; the value panel still works
   as a market mirror + best-price surface, mostly saying `no_value`.

### Phase C — Player props (~1–1.5 days + C0 audit)
- **C0 (blocker removal, ~½ day):** populate `player_name_aliases` — fuzzy-match
  `player_prop_odds.player_name` → `players`/`players_unified` (exact → normalized → trigram;
  manual review file for the tail). Also audit why soccer `player_goal_scorer_anytime` rows are
  missing despite the 4-hourly `soccer_scorer_odds` task (separate bugfix if broken — same
  class of silent failure as the closing sampler).
- **C1:** `PlayerPropsService.get_prop_offers(player_id, event/match)` reading
  `player_prop_odds` via the alias bridge; returns offers grouped by market+line+book.
- **C2:** `POST /predict-player`: attach `value` block — `p_model` vs offers via `prop_value()`;
  nullable when no odds match (most soccer players, for now).
- **C3:** `/top-picks`: re-rank by **EV at best price** (descending), probability as tiebreak;
  picks without odds go to a separate `unpriced` list (no fake value claims). This is the
  single highest-behavior-change line in the whole plan (line 414).
- **C4:** parlay leg pool (player parlays) consumes only legs with `ev > 0` — poison-leg rule.

### Phase D — QA + frontend gates (~½ day)
1. API snapshot tests per endpoint (2-way contract: no `draw` key; props: nullable value).
2. Update `FRONTEND_EDGE_QA.md` rollout table: multisport/props move from "blocked" to testable.
3. Frontend flag: edge UI per sport enabled only when its backend block ships AND registry
   honesty renders correctly (validated badge truthful).

**Total effort: ~3–3.5 days.** Order: A → B and C0 in parallel → C → D.

---

## 4. What we explicitly do NOT do

- **No edge claims from unvalidated models** — the soccer V3 lesson, applied in advance.
- **No porting of confidence floors/conviction tiers** into the new blocks.
- **No NBA/NHL/MLB mainline "edge product" marketing** — those markets are maximally efficient;
  the expected steady state there is `no_value` + best-price surfacing. The realistic value
  segments, in order: **player props** (8-book line variance proven in our own data),
  NHL/lower-liquidity totals, then mainlines almost never.
- **No new odds collection** — every phase runs on tables already populated today.

---

## 5. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Name-alias fuzzy matching attaches odds to the wrong player | confidence column on aliases; only auto-accept exact/normalized; trigram matches go to review file |
| Consensus rows in `multisport_odds_snapshots` are raw (vig-in) like soccer's were | verified: `home_prob`+`away_prob` and overround fields present — de-vig in engine anyway (defensive normalize) |
| Props model probability is for "anytime" but offer line is alt-stat (points 24.5 vs 26.5) | modal-line rule v1; distribution-aware EV in v2 |
| Multisport models fail their holdout (likely for NBA/MLB) | by design: value panel still ships as market mirror; `edge_validated:false` renders honestly |
| `/top-picks` re-rank changes user-visible ordering overnight | feature-flag the sort; ship `ev` field first, flip default after frontend QA |
