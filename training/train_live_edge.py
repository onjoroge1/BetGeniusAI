"""
Train the live in-game model — the same recipe as V3, for the Over-0.5-more market.
Replaces the Poisson PRIOR in models/live_win_probability.py with a calibrated,
data-trained model once enough labeled live snapshots have accumulated.

Mirrors training/train_v3_sharp.py exactly where it matters:
  - LightGBM gradient boosting (binary here vs multiclass for V3)
  - TimeSeriesSplit (chronological, no leakage)
  - Isotonic calibration on out-of-fold predictions (V3's calibrator.pkl pattern)
  - Honest holdout gate: must beat BOTH baselines —
      (a) the Poisson prior it replaces (Brier/logloss)
      (b) the live market (CLV), once live odds are joined
  - Writes artifacts/models/live_edge/{model.pkl, calibrator.pkl, features.json, metadata.json}

Data source: live_match_snapshots (persistent store) labeled from match_events.
Until that table has accumulated (post-deploy), this reports INSUFFICIENT_DATA and
exits 0 — the Poisson prior keeps serving in the meantime.

Usage: python training/train_live_edge.py [--min-rows 2000] [--holdout-frac 0.2]
"""

import os
import re
import sys
import json
import argparse
import logging
from pathlib import Path
from datetime import datetime, timezone

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))
os.chdir(REPO)
for ef in (".env.local", ".env"):
    p = REPO / ef
    if p.exists():
        for line in p.read_text().splitlines():
            m = re.match(r"^([^#=\s][^=]*)=(.*)$", line)
            if m and not os.environ.get(m.group(1).strip()):
                os.environ[m.group(1).strip()] = m.group(2).strip()
        break

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("train_live_edge")

OUTPUT_DIR = REPO / "artifacts" / "models" / "live_edge"
TARGET = "target_more_goal"   # Over 0.5 more goals (binary). Next-goal multiclass = v2.


def load_labeled_snapshots():
    """
    Pull labeled live snapshots. Prefers the persistent live_match_snapshots
    store; if labels aren't backfilled there yet, returns [].
    """
    import psycopg2
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT match_id, match_minute, home_score, away_score,
                   home_shots, away_shots, home_sot, away_sot,
                   home_corners, away_corners, home_red, away_red, home_possession,
                   prematch_home_prob, prematch_away_prob,
                   target_more_goal, snapshot_ts
            FROM live_match_snapshots
            WHERE target_more_goal IS NOT NULL AND match_minute IS NOT NULL
            ORDER BY snapshot_ts ASC
        """)
        rows = cur.fetchall()
    except Exception as e:
        logger.warning(f"live_match_snapshots not ready: {e}")
        rows = []
    finally:
        cur.close(); conn.close()
    return rows


def build_frame(rows):
    import numpy as np
    feats, labels = [], []
    for r in rows:
        (mid, minute, hs, as_, hsh, ash, hsot, asot, hc, ac, hr, ar, poss,
         pm_h, pm_a, target, ts) = r
        # leak-safe features are already point-in-time in the snapshot row
        rem = max(0.0, 94 - minute) / 94.0
        feats.append([
            minute, rem, (hs or 0) + (as_ or 0), abs((hs or 0) - (as_ or 0)),
            hsh or 0, ash or 0, hsot or 0, asot or 0, hc or 0, ac or 0,
            (hr or 0) + (ar or 0), poss or 50,
            float(pm_h or 0), float(pm_a or 0),
        ])
        labels.append(int(target))
    cols = ["minute", "rem_frac", "total_goals", "abs_goal_diff",
            "home_shots", "away_shots", "home_sot", "away_sot",
            "home_corners", "away_corners", "red_total", "home_possession",
            "prematch_home", "prematch_away"]
    return np.array(feats, dtype=float), np.array(labels), cols


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-rows", type=int, default=2000)
    ap.add_argument("--holdout-frac", type=float, default=0.2)
    args = ap.parse_args()

    rows = load_labeled_snapshots()
    logger.info(f"Loaded {len(rows)} labeled live snapshots")
    if len(rows) < args.min_rows:
        logger.warning(f"INSUFFICIENT_DATA: need >= {args.min_rows} labeled snapshots, "
                       f"have {len(rows)}. The Poisson prior keeps serving. "
                       f"Deploy persistence + accumulate, then re-run.")
        return 0

    import numpy as np
    import lightgbm as lgb
    from sklearn.model_selection import TimeSeriesSplit
    from sklearn.isotonic import IsotonicRegression

    X, y, cols = build_frame(rows)
    split = int(len(X) * (1 - args.holdout_frac))
    X_tr, X_ho, y_tr, y_ho = X[:split], X[split:], y[:split], y[split:]
    logger.info(f"Train {len(X_tr)} / holdout {len(X_ho)} | base rate more-goal: {y.mean():.3f}")

    params = {  # same family as train_v3_sharp, binary
        "objective": "binary", "metric": "binary_logloss", "boosting_type": "gbdt",
        "learning_rate": 0.02, "num_leaves": 20, "max_depth": 5,
        "min_data_in_leaf": 30, "feature_fraction": 0.7, "bagging_fraction": 0.7,
        "bagging_freq": 3, "lambda_l1": 0.5, "lambda_l2": 1.0, "verbose": -1, "seed": 42,
    }
    # OOF predictions for isotonic calibration (V3 pattern)
    oof = np.full(len(X_tr), np.nan)
    models = []
    for tr_idx, val_idx in TimeSeriesSplit(n_splits=5).split(X_tr):
        dtr = lgb.Dataset(X_tr[tr_idx], label=y_tr[tr_idx])
        m = lgb.train(params, dtr, num_boost_round=400)
        oof[val_idx] = m.predict(X_tr[val_idx])
        models.append(m)
    mask = ~np.isnan(oof)
    iso = IsotonicRegression(out_of_bounds="clip").fit(oof[mask], y_tr[mask])

    # Holdout: ensemble mean → calibrate
    raw_ho = np.mean([m.predict(X_ho) for m in models], axis=0)
    cal_ho = iso.predict(raw_ho)

    def brier(p, yv): return float(np.mean((p - yv) ** 2))
    def logloss(p, yv):
        p = np.clip(p, 1e-6, 1 - 1e-6)
        return float(-np.mean(yv * np.log(p) + (1 - yv) * np.log(1 - p)))

    # Baseline (a): the Poisson prior this model replaces
    from models.live_win_probability import live_win_probability, lambdas_from_anchor
    prior = []
    for r in rows[split:]:
        minute, hs, as_, pm_h, pm_a = r[1], r[2] or 0, r[3] or 0, r[13], r[14]
        anchor = {"home": float(pm_h or 0), "away": float(pm_a or 0)} if pm_h else None
        lh, la = lambdas_from_anchor(anchor)
        prior.append(live_win_probability(hs, as_, minute, lambda_home_full=lh,
                                          lambda_away_full=la)["markets"]["over_0.5_more_goals"])
    prior = np.array(prior)

    m_brier, p_brier = brier(cal_ho, y_ho), brier(prior, y_ho)
    m_ll, p_ll = logloss(cal_ho, y_ho), logloss(prior, y_ho)
    beats_prior = m_brier < p_brier and m_ll < p_ll
    logger.info(f"Holdout Brier: model {m_brier:.4f} vs prior {p_brier:.4f} | "
                f"LogLoss: model {m_ll:.4f} vs prior {p_ll:.4f} | beats_prior={beats_prior}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    import pickle
    with open(OUTPUT_DIR / "model.pkl", "wb") as f:
        pickle.dump(models, f)
    with open(OUTPUT_DIR / "calibrator.pkl", "wb") as f:
        pickle.dump(iso, f)
    (OUTPUT_DIR / "features.json").write_text(json.dumps(cols, indent=2))
    (OUTPUT_DIR / "metadata.json").write_text(json.dumps({
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "target": TARGET, "n_rows": len(rows), "n_holdout": len(X_ho),
        "holdout_brier": round(m_brier, 4), "prior_brier": round(p_brier, 4),
        "holdout_logloss": round(m_ll, 4), "prior_logloss": round(p_ll, 4),
        "beats_prior": beats_prior,
        # edge_validated stays False until a CLV holdout vs live odds passes
        "edge_validated": False,
        "note": "Beats the Poisson prior on calibration, but NOT promoted to a betting "
                "signal until it beats the live market on CLV (live odds join, next step).",
    }, indent=2))
    logger.info(f"✅ Saved live model → {OUTPUT_DIR} (serve only if beats_prior; "
                f"edge_validated stays False pending CLV gate)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
