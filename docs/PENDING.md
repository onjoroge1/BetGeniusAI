# Pending Tracker — BetGenius / Snapbet

Living list of everything outstanding. Updated 2026-06-13.
Branch `claude/gallant-roentgen-016375` is **N commits ahead of main** — most
items below unblock on the **one deploy action** at the top.

---

## 🔴 P0 — Deploy & secrets (one merge unblocks a pile of fixes)

- [ ] **Merge branch → main and redeploy Replit.** This single action activates,
      all already-built and tested:
      - kills the synthetic-odds generator (`fix_odds_consensus_backfill` disabled)
      - closing-capture fix (was inserting 0 rows forever — H/D/A key + lookback)
      - scorer-odds fix (wrong market key + alias schema) → props value chain live
      - edge payloads on /predict, /predict-wc, /market-multisport, /predict-player
      - WC match_id routing + 72 seeded fixtures + national ELO
      - scheduler: disabled experimental tasks, cold-archive task, WC tasks
      PR: https://github.com/onjoroge1/BetGeniusAI/compare/main...claude/gallant-roentgen-016375
- [ ] **Add Supabase secrets to Replit** (`SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`)
      so the nightly cold-archive actually runs — else Neon climbs back to 6 GB
      in ~5 weeks (values are in local `.env.local`).
- [ ] **Rotate the SportsData API key.** It leaked in git history (commit 37be699,
      `.env.sportsdata`); untracking it stops future exposure but the old key is
      still public. Rotate in the SportsData account.

## 🟠 P1 — Cost & strategy (need user input / decision)

- [ ] **Replit cost breakdown** — still needed to find the true bill driver
      (Autoscale vs Reserved VM vs storage). Move the receipt PDF out of
      `~/Downloads` or paste the line items.
- [ ] **V3 strategic decision.** V3 fails its holdout (45.3% vs 50.9% favorite) —
      council says pivot from pre-match 1X2 prediction toward value/CLV + thin
      markets. Current call: keep V3 as shadow (calibrated probs, no "pick"),
      don't deploy the retrain as primary. Confirm or choose a direction.

## 🟡 P2 — Edge pivot follow-through (built, needs validation/deploy to light up)

- [ ] **Multisport per-sport holdout gates.** NBA/NHL/MLB models are registered
      `edge_validated=False`. Run a favorite-baseline temporal holdout per sport
      before any flips to true (expect NBA/MLB mainlines to stay false — efficient).
- [ ] **`/top-picks` EV ranking.** Deferred — it's a static list with no per-player
      probability; EV ranking belongs where p_model exists (POST /predict-player).
      Wire if/when top-picks computes probabilities.
- [ ] **NBA/NHL player-props model gap.** Prop ODDS flow (8 books) but no model
      serves them via /predict-player (it's soccer-only). Either train a US-sport
      props model or scope props value to soccer for now.
- [ ] **Soccer scorer-odds, ongoing coverage.** Now flowing (2,902 rows, WC) after
      the market-key fix — confirm the 4-hourly scheduler task keeps it fresh
      across all 7 leagues once deployed.

## 🔵 P3 — Snapbet Live Edge (in-game model — docs/LIVE_EDGE_PLAN.md, LIVE_BETTING_EDGE_SPEC.md)

- [x] **Live win-probability engine** (`models/live_win_probability.py`) — dynamic
      1X2 + advanced markets (over0.5more/over2.5/btts/next-goal), wired into /live-edge.
- [x] **/live-edge endpoints** (board + match detail + win_prob_history graph).
- [x] **Live feature/label builder** (`features/live_feature_builder.py`) — leak-safe.
- [x] **In-play odds collection** ✅ — `models/live_odds_collector.py` via API-Football
      /odds/live (ONE call covers all live fixtures). Proven live: 25 rows for a
      tracked match. Scheduler task `live_odds` every ~55s. **Layer 2 is unblocked.**
- [x] **/live-edge value layer wired** — model_prob vs de-vigged live price →
      edge/EV/BETTABLE, with the price-guard (BETTABLE needs +EV, odds ≤30s old,
      price ≥1.85). Proven live: correctly returned `no_value` when the market
      priced a goal higher than the model (prediction ≠ edge, working).
- [ ] **Persistence to deploy:** `live_match_snapshots` + `live_odds_snapshots`
      migrations applied to DB; ensure stale_cleanup does NOT purge them (training store).
- [ ] **Phase 4:** nightly LightGBM Over-0.5 / Next-Goal multi-head (replaces the
      Poisson prior) once enough labeled snapshots accumulate (~weeks). edge_validated
      flips only past the CLV holdout.
- [ ] **Spec validation:** backtest `SB-LIVE-OVER05-001` vs its baseline on
      accumulated snapshots; promote only past the success gate (ROI+vig, +CLV).
- [ ] **xG gap:** live feed has shots/SoT/corners but no xG — source it or proxy
      from shots for the pressure/feature quality the specs assume.
- [ ] **strategy_alerts + match-spec writer:** persist each fired alert (spec_hash,
      features, odds, outcome, CLV) — the audit trail / label factory.
- [ ] **Case-retrieval "why":** query over live_match_snapshots ("50 similar 77'
      moments → goal X%") as the explainability layer.

## ✅ Done this session (for reference)

- Neon DB 6 GB → 349 MB (archived sharp_book_odds + 6 cold tables to Supabase, VACUUM).
- Synthetic odds removed from training + DB; `fix_odds_consensus_backfill` hard-disabled.
- V3: synthetic filter, draw-blindness fix (recall .33→.42), temporal-holdout harness
  (which exposed V3 < favorite — the key honest finding).
- WC: national ELO model (+15pp holdout), /predict-wc, match_id routing, 72 fixtures,
  1,248 squad players, full backfill (3,821 intl matches).
- Edge engine (`utils/edge.py`): de-vig, EV, edge, Kelly, parlay poison-leg rule,
  prop_value; wired into /predict, /predict-wc, /market-multisport, /predict-player,
  player parlays (C4). 143 tests green.
- Fixed: closing-capture (0 rows), scorer-odds market key, alias-schema drift,
  live-collector status/window, per-match-connection training perf.
