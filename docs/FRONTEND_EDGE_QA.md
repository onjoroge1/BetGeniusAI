# Frontend Edge-Pivot QA Plan — All Sports

**Audience:** frontend agent / QA. **Goal:** verify every user-facing surface is built on the
**edge/value model** (does the price overpay you?) and that no surface still runs on the old
**accuracy model** (who wins?). Companion docs: `docs/FRONTEND_EDGE_MANUAL.md` (the contract),
`tests/edge/` (backend source of truth for the math).

---

## 0. The one-sentence test

Open any prediction surface and ask: **"Does this screen tell the user to bet because we're
confident, or because the price is wrong?"**
If the primary call-to-action is driven by `confidence`/accuracy → **FAIL**.
If it's driven by `value.edge` / `value.ev_at_best` / `value.rating` → PASS.

---

## 1. Payload contract QA (per sport)

For each sport, snapshot a live API response and verify the blocks below. Backend reference:
`utils/edge.py` (`build_value_payload`), `tests/edge/test_payload_contract.py`.

| Block / field | Soccer club | World Cup (`wc_elo`) | NBA / NHL / MLB* |
|---|---|---|---|
| `predictions.*` (legacy) | present (back-compat) | present | present |
| `market.implied` (de-vigged, sums to 1.0 ±0.001) | present when odds exist | nullable (thin WC odds) | present when shipped |
| `market.overround` (≈1.02–1.10) | present | nullable | present |
| `market.best_price.{outcome}.odds/book` | present when ≥1 book | nullable | present (12 books) |
| `value.edge.{home,draw,away}` | 3 outcomes | 3 outcomes | **2 outcomes — NO `draw` key** |
| `value.value_bet` | **nullable** | nullable | nullable |
| `value.rating` ∈ {no_value, marginal, value, strong_value} | present | present | present |
| `value.min_acceptable_odds` | present | present | present |
| `clv.{bet_time_odds, closing_odds, realized_clv}` | present, progressively filled | present | present |
| `model_track_record.edge_validated` | **`false` for v3_sharp/v1** | **`true` for wc_elo** | `false` until validated |

*NBA/NHL/MLB columns apply once the 2-way edge backend ships (see §8).

**Hard contract checks (automate as API snapshot tests):**
1. `market.implied` values sum to 1.0 ±0.001 (de-vig applied — raw consensus sums to ~1.05).
2. `value.value_bet.bet` ∈ {home_win, draw, away_win} and equals the argmax-EV outcome.
3. `value_bet.ev > 0` always (a non-null value_bet with EV ≤ 0 is a backend bug — file it).
4. `value_bet.kelly_quarter == kelly_full / 4` and both are 0-capped.
5. Two-way sports: `draw` key absent everywhere, probabilities sum to 1.0 across 2 outcomes.
6. `model_track_record` is **honest**: `v3_sharp.edge_validated === false`. If any UI shows a
   "validated" or "proven" badge for v3_sharp, that is a **release-blocking** bug.

---

## 2. The five semantic inversions (visual QA)

These are the behaviors that distinguish edge-UI from accuracy-UI. Check each on every page
that renders predictions (match cards, match detail, parlay builder, history).

| # | Old (accuracy) behavior | Required (edge) behavior | PASS criteria |
|---|---|---|---|
| 1 | "62% confidence" as the headline | Probability AND edge shown as separate numbers | A card never shows probability without market context next to it |
| 2 | `recommended_bet` always present | **"No bet" is a first-class state** | A match with `value.rating == "no_value"` renders a deliberate empty/"no value" treatment — not a pick, not an error, not a blank |
| 3 | Model-agrees-with-market = "high conviction" | Agreement with market = no edge; **disagreement** (from a validated model) = the signal | No UI element labels market agreement as a reason to bet |
| 4 | Pick displayed at any price | **Price guard**: pick shown with `min_acceptable_odds` ("value at ≥ 3.85") | Every value_bet rendering includes its minimum odds |
| 5 | Stake left to the user | `kelly_quarter` rendered as suggested stake | Stake suggestion visible wherever a value_bet is shown |

---

## 3. State-matrix testing (how to force every state)

Build fixtures/mocks for each state and verify rendering. Recipes against the real backend:

| State | How to produce it | Expected UI |
|---|---|---|
| `strong_value` (EV ≥ 8%) | Mock: model_probs {0.55,0.25,0.20} + best_price home 2.10 | Strongest badge, stake suggestion, price guard |
| `value` / `marginal` | Scale the mock EV into [3,8)% / (0,3)% | Tiered badge, muted for marginal |
| `no_value` | Any match where model ≈ market (most matches!) | "No value at current prices" empty state |
| `market: null` | A match with no odds_consensus row (new/obscure fixture) | Probabilities shown WITHOUT value claims; no fake market data |
| `value_bet: null`, market present | Model probs ≤ market everywhere | Market panel renders, no pick pushed |
| `clv` unsettled | Any upcoming match | CLV row shows "—/pending" |
| `clv` settled | Match >4h after kickoff with closing_odds row (closing sampler now populates these) | `realized_clv` rendered with sign/color |
| WC match | Any `fixtures.league_id = 1` match via `/predict` | `selected_model: wc_elo`, `edge_validated: true` badge |
| 2-way sport | NBA/NHL/MLB event (post-backend-ship) | No draw column anywhere; 2-outcome edge grid |

**The no-value day test (critical):** mock a slate where *every* match is `no_value`. The page
must look intentional ("0 value bets found today — the market is priced correctly") — not broken.
This will be the most common real-world state; it's the honest product working as designed.

---

## 4. Anti-pattern code audit (grep the frontend repo)

Run these against the frontend codebase; each hit needs justification or removal:

```bash
# Picks derived from probability argmax without value gating
grep -rn "predictionType\|recommended_bet" app/ components/ | grep -v "value"
# Confidence used as a CTA gate (the old premium-pick logic)
grep -rn "confidence >\|confidence >=\|confidenceScore >" app/ components/
# Accuracy claims in user-facing copy
grep -rni "accuracy\|win rate\|hit rate" app/ components/ --include="*.tsx" | grep -vi "clv\|track"
# Old conviction tiers based on model agreement
grep -rn "conviction\|models_in_agreement" app/ components/
```

Legacy reads are allowed ONLY in: back-compat data plumbing, historical record pages, and
the (deprecated, flagged-off) old card component during migration.

---

## 5. End-to-end user journeys

**Journey A — value single:**
1. Land on slate → only matches with `value.rating ≥ marginal` carry badges
2. Open a value match → see: model prob vs market implied (side by side), edge, EV, best book+price, min acceptable odds, quarter-Kelly stake
3. Price moves below `min_acceptable_odds` (mock) → UI flips to "price gone — don't bet"
4. After settlement → bet appears in CLV ledger with `realized_clv`

**Journey B — parlay builder:**
1. Leg pool contains ONLY positive-EV legs (assert: no favorites-by-confidence in the pool)
2. Add 2 +EV legs → combined EV ≈ (1+ev₁)(1+ev₂)−1 displayed, fair odds vs offered odds shown
3. Attempt to add a −EV leg → blocked with the poison-leg explanation (`eligible: false`)
4. Parlay stake suggestion is smaller than singles (compounded variance)

**Journey C — the honest day:** no value anywhere → empty states everywhere → user told clearly
this is the product working, with the model track record link as the trust anchor.

---

## 6. CLV lifecycle QA

The payload fills in three stages; test all three against one real match:

| Stage | When | Check |
|---|---|---|
| Predict | pre-kickoff | `clv.bet_time_odds` set iff value_bet exists; others null |
| Close | ~kickoff | backend `closing_odds` row exists (sampler fixed 2026-06-12 — `method_used='last_prekickoff'`) |
| Settled | post-FT sync | `realized_clv = bet_time_odds/closing_odds − 1` rendered; model track record aggregates update |

Frontend wiring: settlement reuses the existing `update-result` sync — verify the CLV fields
ride along and the ledger view refreshes.

---

## 7. Regression / back-compat

- All legacy fields (`predictions.home_win`, `confidence`, `recommended_bet`, `models[]`)
  still present and unchanged in shape — old app versions must not crash.
- `/predict` for a WC match returns `selected_model: "wc_elo"` (never the club cascade).
- Soccer match detail with `include_additional_markets` still renders O/U & BTTS blocks.
- p95 payload size and latency: new blocks add one consensus read + one snapshot query —
  verify no visible slowdown on slate pages (target: < +150ms p95).

---

## 8. Per-sport rollout gates

| Sport | Backend status | Frontend QA gate |
|---|---|---|
| Soccer (club) | ✅ edge blocks live in `/predict` | Full §1–§7 now. Note: most matches will be `no_value` — correct, market is efficient |
| World Cup / intl | ✅ live (`wc_elo`, validated) | §1–§7 + the `edge_validated: true` badge renders |
| NBA / NHL / MLB | ⏳ needs 2-way edge backend (generalize `utils/edge.py` outcomes + `multisport_odds_snapshots` fetcher) | Block edge UI behind a flag until backend ships; meanwhile ensure accuracy-era copy ("model accuracy", confidence buckets) is removed from multisport pages |
| Player props / parlays | ⏳ props priced vs `player_prop_odds` | Parlay pool QA (§5B) applies the day it ships |

**Do not ship edge UI for a sport whose `model_track_record.edge_validated` is false while
displaying any "proven/validated" language.** Probabilities + market panel are fine; edge
claims require the validation badge state to be truthful.

---

## 9. Acceptance summary (release checklist)

- [ ] Contract checks §1 green for soccer + WC (automated snapshots)
- [ ] All five semantic inversions verified on: slate cards, match detail, parlay builder
- [ ] Full state matrix §3 rendered correctly, including the all-no-value day
- [ ] Anti-pattern greps §4 clean (or justified)
- [ ] Journeys A–C pass
- [ ] CLV lifecycle verified on ≥1 real settled match
- [ ] Back-compat §7 green
- [ ] v3_sharp shows NOT-validated; wc_elo shows validated — honesty is the brand
