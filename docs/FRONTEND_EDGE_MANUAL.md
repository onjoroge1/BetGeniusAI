# Frontend Manual — The Edge Pivot
**Audience:** the frontend agent redesigning the Next.js app (`snapbet/ai-bet`)
**Backend contract version:** edge-payload v1 (2026-06-12) · additive, backward compatible
**Companion doc:** `docs/EDGE_PIVOT_PLAN.md` (why), this doc (what to build)

---

## 1. The one-paragraph why

The product stops claiming *"we predict Arsenal, 62% confident"* and starts claiming
*"the market prices Arsenal at 49%, we make it 54% — that's a +5.8% EV bet at
bet365's 2.10, from a model that has beaten its holdout baseline."* Accuracy
rewards copying the bookmaker; **edge** (our probability vs the price) is the only
number mathematically connected to a user's bankroll. The backend now serves both;
the frontend's job is to lead with edge and demote raw confidence to a detail.

**Hard evidence behind this** (don't soften it in copy):
- The club V3 model **failed** its honest holdout (45.3% vs 50.9% for "pick the favorite") — it must never be displayed as a pick source. Its payload says so: `model_track_record.edge_validated: false`.
- The WC/international ELO model **passed** (+15.3pp) — `edge_validated: true`.
- Line-shopping recovers ~2.1pp of vig but isn't profit alone — which is why every value bet carries a **minimum acceptable price**.

---

## 2. Payload contract reference

Four new **top-level** blocks on `/predict` (and `/predict-wc`). All existing fields
(`predictions`, `models[]`, `final_decision`, …) are unchanged. Every new block is
**nullable** — render gracefully when null.

### 2.1 `market` — the de-vigged line (null when no odds collected)

```json
"market": {
  "implied":    { "home": 0.4946, "draw": 0.2793, "away": 0.2261 },  // FAIR probs, sum=1.0 (vig removed)
  "overround":  1.053,                       // raw market sum; (overround-1) = the vig ≈ 5.3%
  "n_books":    75,                          // bookmaker count behind the line
  "best_price": {                            // best available decimal odds per outcome (nullable)
    "home": { "odds": 2.02, "book": "betfair_ex_au" },
    "draw": { "odds": 3.60, "book": "onexbet" },
    "away": { "odds": 4.50, "book": "unibet_nl" }
  }
}
```

### 2.2 `value` — the edge analysis (null when `market` is null)

```json
"value": {
  "edge":       { "home": -0.1128, "draw": 0.002, "away": 0.1108 },  // p_model − p_market (prob points)
  "ev_at_best": { "home": -0.2288, "draw": 0.0127, "away": 0.516 },  // expected value per 1u at best price
  "value_bet": {                              // ⚠ NULLABLE — null = "no bet" (common, correct)
    "outcome": "away",
    "bet": "away_win",                        // canonical: home_win | draw | away_win
    "ev": 0.516,
    "price": 4.50, "book": "unibet_nl",
    "min_acceptable_odds": 2.968,             // below this price the edge is GONE
    "kelly_full": 0.1474, "kelly_quarter": 0.0369   // stake fractions of bankroll
  },
  "rating": "strong_value",                   // no_value | marginal | value | strong_value
  "min_acceptable_odds": { "home": 2.619, "draw": 3.555, "away": 2.968 }
}
```

Rating tiers (EV at best price): `≤0 → no_value` · `<3% → marginal` · `<8% → value` · `≥8% → strong_value`.

### 2.3 `clv` — the verification ledger (fills in over time)

```json
"clv": { "bet_time_odds": 4.50, "closing_odds": null, "realized_clv": null }
```

| Stage | When | What fills in |
|---|---|---|
| Predict time | now | `bet_time_odds` (the value-bet price) |
| Kickoff | closing sampler | `closing_odds` |
| Settlement | existing update-result sync | `realized_clv` = bet_odds/close − 1 |

`realized_clv > 0` = the user beat the closing line = proof of edge **independent of
whether the bet won**. This is the retention metric — see §4.5.

### 2.4 `model_track_record` — the honesty block

```json
"model_track_record": {
  "model": "wc_elo",
  "segment": "thin_market",                  // thin_market | efficient_market | unknown
  "edge_validated": true,                    // passed a temporal holdout vs baseline
  "validation": "temporal holdout +15.3pp vs baseline (n=765)",
  "median_clv_90d": null,                    // populates once the CLV loop is live
  "n_settled": null
}
```

**THE GATING RULE — most important line in this manual:**
> Only render value bets / parlay legs as actionable when
> `model_track_record.edge_validated === true`. When false, show probabilities as
> *information* ("calibrated probabilities — no demonstrated edge") and never a CTA.

---

## 3. Semantic inversions — unlearn these three things

1. **"Confidence" splits into two numbers.** Probability (how likely) and edge (is
   the price wrong). A 65% favorite can be a terrible bet; a 26% underdog can be the
   best bet on the slate. Never present probability alone as a reason to bet.
2. **`recommended_bet` ≠ bet recommendation anymore.** The legacy field is the
   model's argmax. The actionable field is `value.value_bet`, and it is **null on
   most matches**. Null is success, not an error — render the no-value state (§4.6).
3. **Model agreement inverts.** Old UI: "models agree → high conviction." New truth:
   agreeing with the market = zero edge. The signal is **calibrated disagreement** —
   a validated model diverging from `market.implied`. Retire agreement-based
   conviction badges for value surfaces.

---

## 4. UI components to build

### 4.1 Value Badge (replaces the confidence pill)
Tier-colored chip from `value.rating`: `strong_value` / `value` / `marginal` /
`no_value` (muted). Show `+{ev_at_best}%` for the value outcome. Hide entirely
when `value` is null.

### 4.2 Edge Meter (the new core visual per match)
Three rows (H/D/A), each showing `market.implied` vs the model probability
(`predictions.home_win` etc.) as paired bars; the gap IS the edge. Annotate the
value outcome: *"Market 22.6% → Model 33.7% (+11.1)"*.

### 4.3 Price Guard (prevents the stale-tip loss)
On every value bet render: **"Value at ≥ {min_acceptable_odds}. Best now:
{price} ({book})"**. If your displayed live price drops below
`min_acceptable_odds`, flip the card to "edge gone — don't bet" automatically.
This single component prevents users taking dead prices.

### 4.4 Stake Suggester
From `kelly_quarter`: *"Suggested: 3.7% of bankroll (quarter-Kelly)"* with a
user-set bankroll → unit conversion. Always show quarter (full Kelly only behind
an "advanced" toggle, with a variance warning). Cap display at 5% even if Kelly
says more.

### 4.5 CLV Ledger (the retention feature)
Per settled pick: bet price vs closing price vs `realized_clv`, plus rolling
aggregates ("You beat the close on 68% of picks, avg +2.1%"). Sell it in-product:
*"CLV proves edge in ~50 bets; win-rate needs thousands."* This keeps users
through inevitable losing streaks. Data arrives via the existing settlement sync.

### 4.6 No-Value Empty State (design it deliberately)
Most matches: `value_bet: null`. Copy: **"No value at current prices — the market
has this one right. Not betting is the +EV move today."** Show the Edge Meter
anyway (information), no CTA. A filter toggle "value only" should be the default
list view.

### 4.7 Parlay Builder (rules change completely)
- Leg pool = **only** matches with `value_bet != null` from `edge_validated` models.
- Never allow a leg with EV ≤ 0 ("anchor favorites" are banned — one −EV leg
  poisons the ticket multiplicatively).
- Display compounding explicitly: legs +10% and +12% → ticket **+23.2%**; show
  `fair_odds` vs offered combined odds.
- 2–3 legs max; stake from the parlay's own quarter-Kelly (it's smaller — variance
  compounds too).
- Backend helper exists: `utils/edge.parlay_metrics(legs)` → use its `eligible`,
  `ev`, `fair_odds`, `rating` verbatim when a parlay endpoint serves them.

---

## 5. Copy guidelines

| Don't write | Write instead |
|---|---|
| "We predict Arsenal to win (62%)" | "Market prices Arsenal at 49% — we make it 54%" |
| "High confidence pick ✅" | "+5.8% EV at 2.10 (bet365) · value at ≥1.85" |
| "5 hot picks today!" | "2 value bets found today (37 matches scanned)" |
| "Our AI is 73% accurate" | "Our picks beat the closing line by +2.1% (90d median)" |
| "Guaranteed / lock / can't miss" | never — and EV is long-run, single bets lose often |

Tone rules: state probabilities, prices, and EV; never certainty. Losing weeks are
expected and the CLV ledger is the honest answer to "is this working?". Keep
responsible-gambling affordances (bankroll caps, quarter-Kelly defaults).

**Disclosure rule:** anywhere a v3/club pick would previously have shown, the
payload now says `edge_validated: false` — display club matches as *market
information + calibrated probabilities*, not picks. Do not work around the flag.

---

## 6. User journeys

**Single bet:** scan list (default filter: value only) → open match → Edge Meter +
Value Badge → Price Guard confirms live price ≥ min odds → Stake Suggester →
user bets at their book → settlement fills CLV ledger.

**Parlay:** builder shows eligible legs (value bets only) → user picks 2–3 →
compounded EV + fair-vs-offered odds → quarter-Kelly stake → ledger tracks the
ticket like a single.

**Losing-streak reassurance:** dashboard surfaces CLV aggregates above win-rate;
copy explains variance vs edge.

---

## 7. Migration plan (3 phases, feature-flagged)

1. **Read additively** (no visual change): consume `market/value/clv/model_track_record`,
   log nulls, verify shapes in staging. Legacy fields keep working.
2. **Redesign cards** behind a flag: Value Badge + Edge Meter + Price Guard +
   no-value state; default list filter to value-only; gate CTAs on `edge_validated`.
3. **Deprecate** confidence-led UI: retire the old confidence pill and
   agreement-conviction badges; `predictions.recommended_bet` becomes a debug field.

Nullability matrix to test: (a) all blocks null (no odds), (b) `market` only
(no best price → edge shown, no value_bet), (c) full blocks with `value_bet: null`,
(d) full blocks with a value bet. All four occur in production today.

---

## 8. Worked examples (real shapes from staging)

**A. Strong value (WC, validated model)** — USA vs Paraguay (match 1489370):
market implies USA 49.5%; wc_elo says 38/28/34 → value_bet `away_win` @ 4.50
(unibet_nl), EV +51.6% (driven by model-market disagreement), min odds 2.97,
quarter-Kelly 3.7%, rating `strong_value`. Render: Edge Meter shows the 11-point
away gap; Price Guard "value while ≥ 2.97".

**B. No value (club match, unvalidated model)** — any V3 match:
`edge_validated: false` → no CTA ever; show market line + calibrated probs +
"no demonstrated edge in this market segment" footnote.

**C. Parlay** — legs A (+10%) and B (+12%), both from validated models:
ticket EV +23.2%, eligible=true. Same legs plus a 1.40 favorite (−9% EV):
eligible=false — builder must refuse with "this leg removes the ticket's edge."

---

## 9. Glossary

- **Edge** — your probability minus the market's fair probability (points).
- **EV** — expected profit per 1 unit staked: `p × odds − 1`.
- **Vig / overround** — bookmaker margin; raw implied probs sum to >1 by this much.
- **De-vig / fair probs** — implied probs normalized to sum to 1.
- **Fair odds** — `1 / fair prob`; the no-margin price.
- **Min acceptable odds** — `1 / p_model`; the break-even price floor for a bet.
- **CLV** — closing line value; beat-the-close % per bet. The fastest honest proof of edge.
- **Kelly / quarter-Kelly** — bankroll-optimal stake fraction; quarter = the sane default.
- **Thin market** — low-liquidity segment (internationals, lower leagues) where
  models can beat the line. **Efficient market** — top leagues; they can't.
- **edge_validated** — model passed a temporal holdout against its baseline; the
  only license to render CTAs.
