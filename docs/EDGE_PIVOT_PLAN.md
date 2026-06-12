# Edge Pivot — Comprehensive Plan
**Date:** 2026-06-12 · **Status:** Phases 0–2 implemented, Phases 3–5 scheduled

## 1. Context — why this pivot

The council review (2026-06-03, five independent analyses verified against the DB)
established:

| Finding | Evidence |
|---|---|
| V3 1X2 loses to "pick the favorite" | Temporal holdout: **45.3% vs 50.9%**, Brier worse (0.634 vs 0.591) — `scripts/temporal_holdout_result.json` |
| V3 is a market echo | 78% of feature importance = transforms of bookmaker odds |
| More market features can't fix it | Sharp/drift features already in the model at **0.0 importance** — the market prices them |
| Accuracy is the wrong metric | It rewards *copying* the line. Profit comes from **edge** (model prob vs price), measured by **CLV** |
| Thin markets are beatable | WC ELO: **+15.3pp over baseline** (61.2% vs 45.9%) on temporal holdout |

**The pivot:** stop selling predictions ("we predict X, 62% confident"); start selling
value ("market prices X at 49%, we make it 38% — Paraguay at 4.50 is +EV").

## 2. Phase 0 — Line-shopping gate (DONE, result: MARGINAL)

`scripts/validate_line_shopping.py` on 26,556 matches with Pinnacle close + best
price + result (`scripts/line_shopping_result.json`):

- Favorite-only edge of best price over Pinnacle close: **+2.09pp** (real — median
  best-price overround 1.0078, not a synthetic arb)
- BUT: Pinnacle-close favorites return −2.15%; best price → **−0.06%** (~breakeven);
  50% executability haircut → −1.10%
- Blind always-Draw at best price: **+1.57%** over 26k matches (supports the
  "draws are structurally mispriced" thesis — a hypothesis to test, not a product claim)

**Conclusion:** line-shopping *erases the vig but doesn't create profit alone*. It is
the **multiplier** on model edge (a +1% model edge ≈ +3% at best price), so best
price + min-acceptable-odds are first-class payload fields. The standalone
"free money" product is killed; the value-alert product (model edge × best price)
stands.

## 3. Phase 1 — Edge engine + payload (DONE)

**`utils/edge.py`** — pure-math core (unit-testable, no I/O) + thin DB wrappers:
- `devig_proportional` — odds_consensus probs are RAW implied (sum ≈ 1.05); de-vig required
- `compute_edge` (p_model − p_market_fair), `ev_at_price`, `min_acceptable_odds` (1/p)
- `kelly_fraction` (full + quarter), `value_rating` tiers
  (≤0 no_value · <3% marginal · <8% value · ≥8% strong_value)
- `select_value_bet` — highest +EV outcome at best price; **None = "no bet" is the
  honest default**
- `parlay_metrics` — edges compound (Π(1+ev)−1); **poison-leg rule**: ineligible if
  any leg ≤ 0 EV; `joint_prob` override for correlated SGP legs
- `fetch_market_context` — market line from `odds_consensus` (latest row), best
  price per outcome from `odds_snapshots` (h2h, latest snapshot per book, max
  across ~75 books)
- `MODEL_REGISTRY` honesty table — `edge_validated` true only for models that
  passed a temporal holdout (today: `wc_elo` only; `v3_sharp` explicitly false)
- `compute_realized_clv(bet_odds, closing_odds)` — settlement-time CLV

**Payload (additive, backward compatible)** — attached in `/predict`
(`main.py`, after the response dict) and `build_wc_response`
(`models/wc_predictor.py`); never fatal (degrades to nullable blocks):

```json
"market": { "implied": {de-vigged}, "overround": 1.053, "n_books": 75,
            "best_price": {"away": {"odds": 4.5, "book": "unibet_nl"}, ...} },
"value":  { "edge": {...}, "ev_at_best": {...},
            "value_bet": { "outcome", "bet", "ev", "price", "book",
                           "min_acceptable_odds", "kelly_full", "kelly_quarter" } | null,
            "rating": "no_value|marginal|value|strong_value",
            "min_acceptable_odds": {...} },
"clv":    { "bet_time_odds", "closing_odds": null, "realized_clv": null },
"model_track_record": { "model", "segment", "edge_validated", "validation",
                        "median_clv_90d": null, "n_settled": null }
```

Verified live on WC fixture 1489370 (USA–Paraguay): market 49.5/27.9/22.6,
wc_elo 38/28/34 → value_bet away @ 4.50, quarter-Kelly 3.7%.

## 4. Phase 2 — QA suite (this change set)

`tests/edge/` — pure-math tests (de-vig, edge, EV, Kelly, parlay compounding,
poison-leg, no-bet state, rating tiers), payload-contract tests (nullability,
key shape, canonical bet strings), DB-gated integration tests (live market
context, WC fixture end-to-end). Run with `pytest tests/edge tests/wc`.

## 5. Phase 3 — Close the CLV loop (NEXT, needs Replit)

1. Run the closing sampler in the T−6m→T+2m window (scheduler already exists)
   → populate `closing_odds` (currently **empty**)
2. At settlement, `compute_realized_clv` per logged pick → `clv_realized`
3. Aggregate per-model rolling stats → fill `median_clv_90d` / `n_settled`
   in `model_track_record`
4. **Switch the model gate** in `validate_temporal_holdout.py` from accuracy to
   median CLV > 0

## 6. Phase 4 — Parlay generator migration

Rewire `AutomatedParlayGenerator` leg selection: pool = `value_bet` legs only
(today it compounds −EV favorites: two 65% favorites @1.40 → −17% EV; two +10%
legs → +23% EV). Cross-match = independent product; SGP = `joint_prob` via the
existing correlation templates. Serve `parlay_metrics` in the parlay payload.

## 7. Phase 5 — Model strategy under the new gate

- `v3_sharp`: demoted to calibrated-probability provider (`edge_validated: false`
  is now IN the payload). No picks surfaced from it.
- `wc_elo`: the validated template. Extend the thin-market ELO approach to
  cups/lower divisions; each league ships only if CLV > 0 on holdout.
- Draw mispricing (+1.57% blind at best price): investigate as the first
  candidate market-specific strategy.

## 8. Risks & honesty notes

- Big EVs mostly reflect **model-market disagreement** — only actionable from
  `edge_validated` models; the frontend must gate display on that flag.
- Best price is a top-of-book quote; executability haircut is real (gate showed
  −1.10% at 50% haircut for no-edge bets). `min_acceptable_odds` is the user's guard.
- odds_consensus n_books=75 is bookmaker-feed count; thin matches degrade to
  null blocks by design.
