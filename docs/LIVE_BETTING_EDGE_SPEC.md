# Live Betting Edge — Spec Governance Framework

**Date:** 2026-06-13 · **Status:** framework + honest sequencing
**Companions:** `docs/LIVE_EDGE_PLAN.md` (engine), `docs/FRONTEND_LIVE_EDGE.md` (UI),
`utils/edge.py` (value math), `models/live_win_probability.py` (Layer-1 engine),
`migrations/live_edge_snapshots.sql` (snapshot store), `specs/strategy/*.json` (locked specs).

> A betting idea without a spec is a hunch.
> A betting idea with a *locked* spec is a controlled experiment.
> A betting idea that beats the closing line after costs is a validated Snapbet signal.

This turns Snapbet from a tipster app into a live sports trading lab. The same
edge discipline already applied to V3 (accuracy lied; the favorite baseline and
CLV told the truth) is the governance system here.

---

## 1. Two spec layers (the core architecture)

| Layer | Answers | Unit | Mutability |
|-------|---------|------|-----------|
| **Strategy Spec** | "When are we allowed to call this bet, and what must it beat?" | a reusable betting setup | **LOCKED + HASHED** — edits create a new version, never overwrite |
| **Match Spec** | "What was true in this match at each moment, and what happened?" | one match, machine-generated JSON | append-only evidence/audit record |

```
Strategy Spec = the hypothesis (experiment design)
Match Spec    = the evidence (one match's decision moments + outcomes)
Snapshots     = training rows · Outcomes = labels · Models learn the accumulation
```

The match spec is a **label factory**: one 77' snapshot yields labels for 8+ heads
(more-goal, home-next, away-next, no-goal, BTTS, over-2.5, result-holds, alert-was-+EV).

---

## 2. Strategy Spec — required fields (locked & hashed)

Stored as `specs/strategy/{ID}.json`, loaded/validated/hashed by `utils/strategy_spec.py`.
Every alert references `{strategy_id, version, spec_hash}` so the experiment is auditable
and tamper-evident. Threshold change ⇒ new version (`v1.0 → v1.1`), old results frozen.

```
identity     : strategy_id, version, name, market, time_window, league_scope, status
hypothesis   : one-sentence falsifiable edge claim
required_data / optional_data
entry_rules  : exact, codeable conditions (minute, score_diff, pressure pct,
               odds floor, edge ≥ X, data freshness)
exclusion_rules : suspended / stale odds / goal in last Nm / red card just now /
                  price moved against us / low-liquidity league
settlement   : how the bet is graded
baseline     : the matched naive strategy this MUST beat (not just "be profitable")
success_gate : min historical N, min forward N, leagues, ROI after vig, POSITIVE CLV,
               Brier/logloss vs market, no league > 40% of profit, max drawdown
promotion_rule / retirement_rule
```

Status lifecycle: `Draft → Registered(locked) → Validating → Promoted → Retired`.

The first spec is real and committed: **`SB-LIVE-OVER05-001` (Late Goal Pressure)** —
`specs/strategy/SB-LIVE-OVER05-001.json`.

---

## 3. Match Spec — the evidence record (auto-generated JSON)

Never hand-written. The snapshot writer + outcome labeler produce one JSON per match:
`prematch_context` (anchor probs, xG env) → `lineup_context` → `snapshots[]` (each with
state, live stats, live odds, market_implied, eligible_strategy_specs,
snapbet_prediction, edge, decision+reason_codes) → per-snapshot `outcome`.

Backed by the tables (reconciled with what we already have):

| Table | Purpose | Status |
|-------|---------|--------|
| `live_match_snapshots` | one row per (match, minute): state + odds + labels | migration written (`migrations/live_edge_snapshots.sql`), **not deployed** |
| `strategy_specs` | registered locked specs + hash | to build (mirrors `specs/strategy/*.json`) |
| `strategy_alerts` | every fired alert + result + CLV (audit trail) | to build (Layer 2) |
| `live_match_stats` / `match_events` | live source feed | ✅ collecting (but purged 4h post-match → why the persistent table exists) |

---

## 4. Prediction ≠ edge (the rule that governs everything)

```
model_prob 62%  vs  market-implied 45%  → edge +17pp → candidate alert
model_prob 62%  vs  market-implied 70%  → NO BET (negative edge), even though a goal is "likely"
```
A strategy fires only when `model_prob ≥ market_implied + edge_buffer` AND the spec's
entry rules pass AND no exclusion trips. This is `utils.edge` applied live.

---

## 5. The nightly learning loop

```
live feed → snapshot writer → match-spec JSON → outcome labeler (at FT)
   → accumulated labeled snapshots → NIGHTLY LightGBM multi-head retrain
   → backtest each retrained head against LOCKED strategy specs
   → promote a spec ONLY if it clears its success_gate (ROI after vig + positive CLV
     + beats baseline + out-of-sample + no single league > 40%)
```
"Similar game dynamics → clearer result" is exactly what the tree model learns
(it partitions feature space into neighborhoods of similar live states). A
**case-retrieval** view over `live_match_snapshots` ("50 most-similar 77' moments,
goal came 58%") is the explainability layer on top — a query, not a model.

AI's role is bounded: **propose** specs + write the user-facing "why"; it may NOT
change a locked spec after seeing outcomes. Spec governs · backtest validates ·
engine executes.

---

## 6. Honest sequencing (what's ready vs blocked)

| Phase | Work | Dependency | State |
|-------|------|-----------|-------|
| **A** | Deploy `live_match_snapshots`; snapshot writer persists every cycle; outcome labeler backfills at FT. **Start accumulating now** — the validation clock starts here. | the P0 deploy | migration ready |
| **B** | **In-play odds collection** → `live_odds_snapshots`. Without it: no live price → no edge → no CLV → **no strategy can be validated**. This is THE gate for the whole framework. | net-new compute (weigh vs bill) | 🔴 blocker |
| **C** | Lock spec #1 (`SB-LIVE-OVER05-001`); backtest on accumulated snapshots vs its baseline. | A + enough volume | spec committed |
| **D** | Nightly LightGBM multi-head; promote specs past the CLV gate only. | A + B + months of volume | designed |

**Reality check:** Layer-1 intelligence (live win-prob + markets, already shipped via
`live_win_probability.py`) needs none of this and works today. Everything in *this*
doc — the spec-validated *betting* product — is gated on persistence + in-play odds +
a volume runway (≈3 months forward). Start collecting immediately; validate later.

**Caveats to resolve:** (1) our live feed has shots/SoT/corners but **not xG** — source
it or use a shot-based xG proxy before specs that require xG; (2) start with ONE spec,
not seven — premature locking is its own bias.
