# Frontend Manual — Snapbet Live Edge

**Audience:** the frontend agent building the live in-game betting UI.
**Backend design:** `docs/LIVE_EDGE_PLAN.md` · **Value semantics:** `docs/FRONTEND_EDGE_MANUAL.md`
**Date:** 2026-06-13 · **Status:** API contract (backend phased; see §9 readiness).

---

## 1. Is this a new API? — Yes, two endpoints

Live Edge is **not** `/predict`. `/predict` is one match, computed on request,
pre-match. Live Edge is a **continuously-updating board of all live matches**
with second-level freshness and expiring alerts. That needs its own surface:

| Endpoint | Purpose | Cadence |
|----------|---------|---------|
| `GET /live-edge/board` | All live matches with current state + edge verdict | poll every 20–30s (or SSE) |
| `GET /live-edge/match/{match_id}` | One match: full snapshot history + current alert + "why" | on detail open |

Reuse, don't reinvent: the **value semantics are identical to the pre-match edge
pivot** (`edge`, `ev`, `value_bet`, `no_value`, `min_acceptable_odds`,
`model_track_record`). A frontend that already renders the pre-match `value`
block reuses the same components here — only the transport (polling/SSE) and the
TTL/expiry behavior are new.

---

## 2. `GET /live-edge/board` — the response

```jsonc
{
  "generated_at": "2026-06-13T20:14:33Z",
  "active_matches": 42,
  "matches": [
    {
      "match_id": 1489371,
      "minute": 77,
      "period": "2H",
      "home": {"name": "Brazil", "score": 1},
      "away": {"name": "Morocco", "score": 1},
      "status": "BETTABLE",            // see §4 — drives the whole card UI
      "market": "over_0.5_more_goals", // which live market this card is about
      "pick": "over_0.5_more_goals",
      "model_prob": 0.508,             // Snapbet probability (calibrated)
      "market_implied": 0.426,         // de-vigged live price
      "edge": 0.082,                   // model_prob - market_implied
      "ev": 0.152,                     // EV at best price (p*odds - 1)
      "best_price": {"odds": 2.35, "book": "bet365"},
      "min_acceptable_odds": 1.97,     // below this the edge is gone — hard gate
      "confidence": "medium_high",     // low | medium | medium_high | high
      "pressure": {"home": 44.4, "away": 3.1, "total": 47.5},
      "expires_at": "2026-06-13T20:15:18Z",  // TTL — see §5
      "model_track_record": {"model": "live_edge_over05", "edge_validated": false}
    }
    // ... one card per live match (or per (match, market) once >1 market ships)
  ]
}
```

**Nullable contract (critical):** any of `market_implied`, `edge`, `ev`,
`best_price`, `min_acceptable_odds` may be `null` when **in-play odds aren't
available** for that match (Phase 3 dependency — see §9). When they're null the
card MUST fall back to `status: "WATCHLIST"` and show only match-state info — it
must NEVER fabricate an edge. `model_prob` and `pressure` are always present.

---

## 3. `GET /live-edge/match/{match_id}` — detail

Adds, on top of a board card:
```jsonc
{
  "snapshots": [ {"minute": 70, "home_score": 0, ...}, {"minute": 77, ...} ],
  "why": [                                  // the trust-builder — render as bullets
    "12 shots in last 12 minutes (Brazil)",
    "6 corners since 65'",
    "Brazil attacking pressure rising, Morocco subbed defensively",
    "~6 min stoppage estimated"
  ],
  "odds_movement": {"last_5min": [2.80, 2.55, 2.40, 2.35], "drifting": false},
  "alert_history": [ {"minute": 74, "status": "WATCHLIST"}, {"minute": 77, "status": "BETTABLE"} ]
}
```

---

## 4. The `status` field drives everything

Render the card entirely from `status` — do not invent your own thresholds:

| status | meaning | UI |
|--------|---------|----|
| `WATCHLIST` | game heating up, no bet yet (edge below threshold or odds not yet good / null) | muted card, "watching", no CTA |
| `BETTABLE` | positive edge, odds still valid, TTL live | highlighted card, show price + edge + bet CTA |
| `EXPIRED` | edge gone (odds moved or pressure faded or TTL passed) | greyed out, "edge gone", auto-remove after a few s |
| `SUSPENDED` | market suspended (goal/red card just happened, data stale) | "market suspended", no price |

A card can move WATCHLIST → BETTABLE → EXPIRED within a single match. Animate
transitions; never leave a stale BETTABLE on screen past `expires_at`.

---

## 5. TTL / freshness — live betting is time-critical

- Every BETTABLE card carries `expires_at`. **When `now > expires_at`, treat it
  as EXPIRED immediately**, even before the next poll — the price likely moved.
- Poll the board every **20–30s**; or subscribe to SSE `GET /live-edge/stream`
  (if shipped) for push. Show a "last updated Ns ago" indicator.
- The **price guard is non-negotiable**: before a user bets, the displayed
  `best_price` must be ≥ `min_acceptable_odds`. If the book's live price has
  dropped below it, show "edge gone — price moved" and disable the CTA. This is
  the single most important rule — a stale tip at a moved price is a losing bet.

---

## 6. What the user sees (the moat = the explanation)

Don't show "bet Over 0.5." Show the disagreement, like the spec's example:

```
LATE GOAL EDGE · 77'  · Brazil 1–1 Morocco
Pick: Over 0.5 more goals    Best odds: 2.35 (bet365)
Market says: 42.6%   Snapbet says: 50.8%   Edge: +8.2%
Why: 6 shots last 12' · 4 corners since 65' · pressure rising · ~6' stoppage
Confidence: Medium-High    ⚠ odds moving quickly
```

Always pair the number with the "why". The brand is **"live match intelligence +
odds value detection,"** not "magic AI."

---

## 7. Honesty rendering (same rule as pre-match)

`model_track_record.edge_validated` gates language:
- `false` → label the model **"experimental / not yet validated"**; you may show
  probability + pressure, but do NOT claim "we beat the market." Most live cards
  will be `false` until the CLV holdout passes (§9).
- `true` → may show validated-edge badge + historical CLV stats.

Never render `no_value` / null-edge cards as opportunities. "No bet" is a feature.

---

## 8. Build order (frontend)

1. **Board polling + card list** keyed by `status`. Works day-1 even with all
   `WATCHLIST` (probability + pressure only, no odds).
2. **Detail view** with snapshot timeline + "why" bullets.
3. **TTL/expiry engine** (client-side countdown off `expires_at` + price guard).
4. **SSE upgrade** when the stream endpoint ships.
5. **Value components**: reuse the pre-match `value` block renderer (edge, EV,
   best price, min-odds, Kelly stake) once in-play odds flow.

---

## 9. Backend readiness — what's live vs blocked (READ THIS)

| Layer | State | Frontend impact |
|-------|-------|-----------------|
| Live match state (`live_match_stats`) | ✅ collecting every ~60s | board can show minute/score/shots/pressure NOW |
| Persistent snapshots (`live_match_snapshots`) | ⏳ migration written, not deployed | needed for model training; no UI impact |
| Probability model (`live_edge_over05`) | ⏳ Phase 4 — not trained yet | `model_prob` may be a Poisson PRIOR, not the model, until then — `edge_validated:false` |
| **In-play odds** | 🔴 **NOT collected** (we stop at kickoff) | `market_implied`/`edge`/`ev`/`best_price` are **null** until Phase 3 — build the WATCHLIST path FIRST and treat the value fields as optional everywhere |
| Endpoints `/live-edge/*` | ⏳ not built yet | contract above is the spec to build against; mock it to start |

**Bottom line for the frontend:** build against this contract now, but assume the
**value fields are null** (WATCHLIST-only board) until in-play odds collection
ships. Everything degrades gracefully to "match intelligence" without odds.

---

## 10. QA checklist

**Contract / nullability**
- [ ] Board renders with `market_implied`/`edge`/`ev`/`best_price` all `null`
      (no crash, cards show as WATCHLIST with state + pressure only).
- [ ] No card EVER shows an edge/EV number when `best_price` is null.
- [ ] `model_track_record.edge_validated:false` → no "beats the market" copy anywhere.

**Status machine**
- [ ] A card transitions WATCHLIST → BETTABLE → EXPIRED correctly as fields change.
- [ ] BETTABLE card past `expires_at` flips to EXPIRED client-side without waiting
      for the next poll.
- [ ] SUSPENDED hides price + disables CTA.

**Price guard (most important)**
- [ ] When live `best_price` < `min_acceptable_odds`, CTA disabled + "price moved".
- [ ] "Last updated Ns ago" reflects real poll/stream recency.

**Math sanity (spot-check vs payload)**
- [ ] `edge ≈ model_prob − market_implied`.
- [ ] `ev ≈ model_prob × best_price.odds − 1`.
- [ ] `min_acceptable_odds ≈ 1 / model_prob`.

**Live behavior**
- [ ] Open during an actual live match (e.g. a WC game): minute/score/shots
      update within one poll of the real game; a goal flips affected cards to
      SUSPENDED then re-evaluates.
- [ ] Board with 0 live matches shows an empty/"no live games" state, not an error.

**Performance**
- [ ] Board poll ≤ 30s, render stays smooth with 40+ cards.
- [ ] Expired cards auto-removed; no unbounded growth.
