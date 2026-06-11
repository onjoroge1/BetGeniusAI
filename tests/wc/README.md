# WC / Prediction Test Suite

Comprehensive tests for the World Cup ELO model, the national-team rating
pipeline, the `/predict` + `/predict-wc` endpoints, the training data, and the
recorded validation results.

## Run

```bash
# from repo root (loads .env.local automatically via conftest)
PYTHONPATH=. python3 -m pytest tests/wc/ -v
```

Requires `pytest`. DB-backed tests need `DATABASE_URL` (read from `.env.local`);
they skip cleanly if it's absent. The HTTP endpoint tests need the full app
(`fastapi`) and skip in minimal envs — they run in CI / on Replit.

## What's covered

| File | Scope | DB? |
|------|-------|-----|
| `test_national_elo.py` | ELO math — expected score, home advantage, K-factor, margin-of-victory, prob mapping | no |
| `test_wc_predictor.py` | `WCPredictor`, `build_wc_response`, `route_wc_by_match_id`, international detection | partial |
| `test_data_integrity.py` | synthetic odds removed, ELO/squads populated, WC fixtures seeded with team ids + ELO | yes |
| `test_model_validation.py` | WC ELO beats majority baseline (+15pp), recommended=elo, V3 fixes in place, V3 holdout recorded | no |
| `test_endpoints.py` | HTTP contract for `/predict-wc` + WC routing through `/predict` (TestClient) | CI/Replit |

## Guards / regressions pinned

- **Recommended-bet == argmax(probs)** — the exact bug that once corrupted every pick.
- **Probabilities sum to exactly 1.0** — caught a rounding bug; now enforced.
- **No synthetic template rows in `odds_consensus`** — caught 4 freshly-generated
  outcome-leaking rows; source script (`fix_odds_consensus_backfill.py`) now disabled.
- **`league_draw_rate` feature present** — guards the double-fetchone bug we fixed.
- **Training query has the synthetic filter + draw boost.**
- **WC fixtures have team ids and ELO ratings** — without these, match_id routing breaks.
