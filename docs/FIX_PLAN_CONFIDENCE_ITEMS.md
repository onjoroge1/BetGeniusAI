# Fix Plan — Confidence Items #1–#4 (2026-06-14)

Concrete remediation for the four things flagged as low-confidence. #1 is the
fire (fake-data contamination); the rest are correctness/coverage gaps.

---

## #1 — Fake/synthetic odds (FIRE — fix ASAP) ✅ source killed, deploy pending

**Root cause (found):** `models/database.py :: save_odds_consensus_batch()` fabricated
odds_consensus rows from the match OUTCOME (Home→0.65/0.25/0.10, etc.) — target
leakage — and ran on the **6-hour collection cycle**, re-poisoning the DB after
every cleanup. (The earlier-disabled `fix_odds_consensus_backfill.py` was a manual
script, never the live source.)

**Done in this branch:**
- `save_odds_consensus_batch()` → permanent **no-op** with a loud warning.
- The dual-table call in `save_training_matches_batch` removed.
- `fix_odds_consensus_backfill.py` already disabled (belt-and-suspenders).
- Full purge of synthetic rows from odds_consensus (backed up).
- Contamination test guards regressions (`tests/wc/test_data_integrity.py`).

**Still required:**
1. **DEPLOY** (branch→main→Replit). Until then production keeps regenerating fake
   rows every 6h — this is now the #1 reason to deploy immediately.
2. Post-deploy: confirm over one 6h cycle that **0 new synthetic rows** appear
   (run the contamination query; it should stay 0 without manual cleanup).
3. Tighten `test_no_synthetic_rows_contaminate_training` to **zero-tolerance
   anywhere** (drop the orphan tolerance) once deploy confirms no regeneration.
4. **Policy note (codified here): NEVER synthesize odds/consensus/probabilities.**
   A match with no real collected odds gets NO row; the cascade falls back to
   V0/ELO. Any "backfill consensus" idea must read real odds only.

---

## #2 — Live win-probability has no calibration evidence

**Cause:** it's a Poisson PRIOR with hardcoded constants (`DEFAULT_TOTAL_XG=2.7`,
`0.53/0.47` split, red multipliers, compression term). No labeled snapshot data
exists to calibrate against (persistence not deployed; live stats purged at 4h).

**Plan:**
1. **Deploy persistence** (`live_match_snapshots` + the snapshot writer) so labeled
   decision-moments accumulate; ensure `stale_cleanup` never purges that table.
2. Backfill labels at FT from `match_events` (already designed in `live_feature_builder`).
3. After ~weeks of volume, run `training/train_live_edge.py` → LightGBM + isotonic,
   **gated**: must beat the Poisson prior on Brier/logloss AND beat the live market
   on CLV before it serves or claims edge.
4. Publish a **reliability curve** (does "70%" happen 70%?) as the calibration proof.
5. Until then: keep labeling the output `live_poisson_prior` / `edge_validated=false`
   so the UI never overclaims.

---

## #3 — Club live-odds mapping + xG coverage unproven beyond WC

**Cause:** the live-odds fixture→match_id map was only ever exercised for WC
internationals (where `match_id` == API fixture id). The club path
(`matches.api_football_fixture_id`) has never resolved a live club match (0/18 live
fixtures mapped at test time — all lower leagues we don't track). The one xG row
captured was purged, so cross-league xG availability is untested.

**Plan:**
1. **Coverage test:** when a tracked club/major match is live, assert
   `live_odds_collector` maps it (rows land for that match_id) — add to the live QA.
2. **Backfill `matches.api_football_fixture_id`** for tracked upcoming fixtures so
   the club mapping path actually resolves (the WC path works because seeding set
   match_id = API id; clubs need the matches row populated pre-match).
3. **xG availability audit:** for each tracked league, check whether
   `fixtures/statistics` returns `expected_goals` (it's league/coverage-dependent on
   API-Football). Where absent, fall back to a shots-based xG proxy in the feature
   builder; record `xg_source` so the model knows real-vs-proxy.
4. Add a nightly "live coverage" report: % of tracked live matches that got
   stats + odds + xG, so gaps are visible instead of silent.

---

## #4 — End-to-end payload correctness untested (no FastAPI locally)

**Cause:** the value-block wiring in `/predict`, `/market-multisport`,
`/predict-player`, `/live-edge` is verified by pure-unit tests + manual data-path
runs, but never by an actual HTTP response (fastapi not installed in the dev env).

**Plan:**
1. **CI job** with `fastapi`+`httpx` TestClient that boots the app and hits each
   endpoint against a seeded test DB (or the live DB read-only), asserting the
   contract: probs sum to 1, `value`/`edge` present-or-null per the manual,
   `recommended_bet == argmax(probs)`, no `draw` key for 2-way, WC routes to wc_elo.
2. **Post-deploy smoke:** curl each endpoint once and diff against the documented
   contract (`docs/FRONTEND_*` manuals).
3. Make the legacy `tests/*.py` standalone scripts non-blocking (they `sys.exit` at
   import and break `pytest tests/`): move them to `tests/legacy/` excluded from the
   pytest path, so `pytest` runs clean end-to-end.

---

## Sequencing
1. **NOW:** #1 source kill (done) + **deploy** (stops prod fake-data generation).
2. **This week:** #4 CI TestClient + legacy test quarantine (cheap, unblocks honest
   green); #3 `api_football_fixture_id` backfill + xG audit.
3. **Ongoing (weeks):** #2 accumulate snapshots → train → calibration curve → CLV gate.

**The throughline:** deploy is the gate for #1 (and most of the session). Every hour
unmerged = more fabricated odds in prod + more purged live-validation data.
