"""
Soccer Player Goal Model — LightGBM binary classifier

Predicts probability of a player scoring in a given match.
Uses 49K player_game_stats records with league as a feature.

Labels:
  - scored_goal: binary (1 if goals > 0)
  - goal_involvement: binary (1 if goals > 0 or assists > 0)

Features (25):
  FORM: goals_last_3/5, assists_last_3/5, shots_avg_3/5, rating_avg_5, minutes_avg_5
  SEASON: season_goals, season_assists, season_appearances, goals_per_90, shots_per_90
  MATCH: is_home, is_starter, minutes_played_avg, rest_days
  OPPONENT: opp_goals_conceded_avg, opp_clean_sheet_pct
  PLAYER: position_encoded, age_bucket
  LEAGUE: league_id (categorical), league_avg_goals, league_scorer_pct

Output: artifacts/models/player_soccer/
"""

import os
import sys
import json
import pickle
import logging
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict

import numpy as np
import psycopg2
import lightgbm as lgb
from sklearn.model_selection import TimeSeriesSplit
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import roc_auc_score, log_loss, precision_recall_fscore_support

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL")
ARTIFACTS_DIR = Path("artifacts/models/player_soccer")
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

POSITION_MAP = {
    "Attacker": 3, "Forward": 3, "F": 3,
    "Midfielder": 2, "M": 2,
    "Defender": 1, "D": 1,
    "Goalkeeper": 0, "G": 0,
}

FEATURE_NAMES = [
    # Form (8)
    "goals_last_3", "goals_last_5", "assists_last_3", "assists_last_5",
    "shots_avg_3", "shots_avg_5", "rating_avg_5", "minutes_avg_5",
    # Season (5)
    "season_goals", "season_assists", "season_appearances", "goals_per_90", "shots_per_90",
    # Match (4)
    "is_home", "is_starter", "minutes_played_avg", "rest_days",
    # Opponent (2)
    "opp_goals_conceded_avg", "opp_clean_sheet_pct",
    # Player (2)
    "position_encoded", "age_bucket",
    # League (4)
    "league_id_cat", "league_avg_goals", "league_scorer_pct", "league_goal_rate",
]


def load_data():
    """Load player game stats with context from DB."""
    logger.info("Loading player game stats from database...")
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    cur.execute("""
        SELECT pgs.player_id, pgs.game_id, pgs.league_id, pgs.team_id,
               pgs.opponent_team_id, pgs.game_date, pgs.is_home, pgs.is_starter,
               pgs.minutes_played, pgs.rating, pgs.stats,
               pu.position, pu.date_of_birth
        FROM player_game_stats pgs
        JOIN players_unified pu ON pgs.player_id = pu.player_id AND pu.sport_key = 'soccer'
        WHERE pgs.sport_key = 'soccer'
          AND pgs.minutes_played >= 15
          AND pu.position IS NOT NULL
          AND pgs.player_id IN (
              SELECT player_id FROM player_game_stats
              WHERE sport_key = 'soccer' AND minutes_played >= 15
              GROUP BY player_id HAVING COUNT(*) >= 5
          )
        ORDER BY pgs.game_date ASC, pgs.player_id ASC
    """)
    rows = cur.fetchall()
    logger.info(f"Loaded {len(rows):,} player-game records")

    # Pre-compute league stats
    cur.execute("""
        SELECT pgs.league_id,
               COUNT(DISTINCT pgs.game_id) as games,
               SUM((pgs.stats->>'goals')::int) as total_goals,
               COUNT(*) as total_appearances,
               COUNT(*) FILTER (WHERE (pgs.stats->>'goals')::int > 0) as scorer_apps
        FROM player_game_stats pgs
        WHERE pgs.sport_key = 'soccer' AND pgs.minutes_played >= 15
        GROUP BY pgs.league_id
    """)
    league_stats = {}
    for lid, games, goals, apps, scorer_apps in cur.fetchall():
        league_stats[lid] = {
            "avg_goals": (goals or 0) / max(games, 1),  # goals per match (all players)
            "scorer_pct": (scorer_apps or 0) / max(apps, 1),  # % of appearances with a goal
            "goal_rate": (goals or 0) / max(apps, 1),  # goals per player-appearance
        }

    conn.close()
    return rows, league_stats


def build_features(rows, league_stats):
    """Build feature matrix with rolling windows per player."""
    logger.info("Building features with rolling windows...")

    # Group by player for rolling computation
    player_history = defaultdict(list)  # player_id -> [(game_date, stats_dict, ...)]

    X_list = []
    y_scored = []
    y_involved = []
    meta = []  # for debugging

    for row in rows:
        pid, gid, lid, tid, opp_tid, gdate, is_home, is_starter, mins, rating, stats, position, dob = row
        stats = stats if isinstance(stats, dict) else json.loads(stats) if stats else {}

        goals = int(stats.get("goals", 0))
        assists = int(stats.get("assists", 0))
        shots = int(stats.get("shots", 0))

        # Get player's prior history (before this game)
        history = player_history[pid]

        if len(history) < 3:
            # Not enough history yet — add to history and skip
            player_history[pid].append({
                "date": gdate, "goals": goals, "assists": assists,
                "shots": shots, "rating": rating or 0, "minutes": mins,
                "league_id": lid, "team_id": tid,
            })
            continue

        # ── FORM FEATURES (rolling) ──
        last_3 = history[-3:]
        last_5 = history[-5:] if len(history) >= 5 else history

        goals_last_3 = sum(h["goals"] for h in last_3)
        goals_last_5 = sum(h["goals"] for h in last_5)
        assists_last_3 = sum(h["assists"] for h in last_3)
        assists_last_5 = sum(h["assists"] for h in last_5)
        shots_avg_3 = np.mean([h["shots"] for h in last_3])
        shots_avg_5 = np.mean([h["shots"] for h in last_5])
        rating_avg_5 = np.mean([h["rating"] for h in last_5 if h["rating"] > 0]) if any(h["rating"] > 0 for h in last_5) else 6.0
        minutes_avg_5 = np.mean([h["minutes"] for h in last_5])

        # ── SEASON FEATURES ──
        season_goals = sum(h["goals"] for h in history)
        season_assists = sum(h["assists"] for h in history)
        season_appearances = len(history)
        total_mins = sum(h["minutes"] for h in history)
        goals_per_90 = (season_goals / max(total_mins, 1)) * 90
        shots_per_90 = (sum(h["shots"] for h in history) / max(total_mins, 1)) * 90

        # ── MATCH FEATURES ──
        minutes_played_avg = np.mean([h["minutes"] for h in history])
        # Rest days
        if history:
            last_date = history[-1]["date"]
            rest_days = (gdate - last_date).days if hasattr(gdate, '__sub__') else 7
        else:
            rest_days = 7

        # ── OPPONENT FEATURES ──
        # Compute opponent's goals conceded from our data
        opp_games = [h for h in history if h.get("team_id") == opp_tid]
        # Fallback: use league average
        opp_goals_conceded_avg = league_stats.get(lid, {}).get("avg_goals", 2.5) / 2
        opp_clean_sheet_pct = 0.25  # default

        # ── PLAYER FEATURES ──
        position_encoded = POSITION_MAP.get(position, 1)
        age_bucket = 0  # default
        if dob:
            try:
                age = (gdate - dob).days / 365.25 if hasattr(gdate, '__sub__') else 27
                age_bucket = 0 if age < 23 else (1 if age < 28 else (2 if age < 33 else 3))
            except Exception:
                age_bucket = 1

        # ── LEAGUE FEATURES ──
        ls = league_stats.get(lid, {"avg_goals": 2.5, "scorer_pct": 0.06, "goal_rate": 0.08})
        league_id_cat = lid or 0
        league_avg_goals = ls["avg_goals"]
        league_scorer_pct = ls["scorer_pct"]
        league_goal_rate = ls["goal_rate"]

        # ── BUILD FEATURE VECTOR ──
        features = [
            goals_last_3, goals_last_5, assists_last_3, assists_last_5,
            shots_avg_3, shots_avg_5, rating_avg_5, minutes_avg_5,
            season_goals, season_assists, season_appearances, goals_per_90, shots_per_90,
            1 if is_home else 0, 1 if is_starter else 0, minutes_played_avg, min(rest_days, 14),
            opp_goals_conceded_avg, opp_clean_sheet_pct,
            position_encoded, age_bucket,
            league_id_cat, league_avg_goals, league_scorer_pct, league_goal_rate,
        ]

        X_list.append(features)
        y_scored.append(1 if goals > 0 else 0)
        y_involved.append(1 if (goals > 0 or assists > 0) else 0)
        meta.append({"player_id": pid, "game_id": gid, "date": str(gdate)})

        # Add current game to history
        player_history[pid].append({
            "date": gdate, "goals": goals, "assists": assists,
            "shots": shots, "rating": rating or 0, "minutes": mins,
            "league_id": lid, "team_id": tid,
        })

    X = np.array(X_list, dtype=np.float32)
    y_scored = np.array(y_scored)
    y_involved = np.array(y_involved)

    logger.info(f"Built {len(X):,} samples, {len(FEATURE_NAMES)} features")
    logger.info(f"Scored: {y_scored.sum():,} ({y_scored.mean()*100:.1f}%)")
    logger.info(f"Involved: {y_involved.sum():,} ({y_involved.mean()*100:.1f}%)")

    return X, y_scored, y_involved, meta


def train_model(X, y, label_name="scored"):
    """Train LightGBM with TimeSeriesSplit and return OOF predictions."""
    logger.info(f"\nTraining {label_name} model...")

    pos_rate = y.mean()
    scale_pos = (1 - pos_rate) / max(pos_rate, 0.001)

    params = {
        "objective": "binary",
        "metric": "binary_logloss",
        "boosting_type": "gbdt",
        "learning_rate": 0.02,
        "num_leaves": 24,
        "max_depth": 5,
        "min_data_in_leaf": 50,
        "feature_fraction": 0.7,
        "bagging_fraction": 0.7,
        "bagging_freq": 3,
        "lambda_l1": 0.5,
        "lambda_l2": 1.0,
        "scale_pos_weight": scale_pos,
        "verbose": -1,
        "force_row_wise": True,
        "seed": 42,
    }

    # Categorical feature
    cat_idx = [FEATURE_NAMES.index("league_id_cat")]

    tscv = TimeSeriesSplit(n_splits=5)
    oof_preds = np.zeros(len(y))
    oof_mask = np.zeros(len(y), dtype=bool)
    models = []
    importances = np.zeros(len(FEATURE_NAMES))

    for fold, (train_idx, val_idx) in enumerate(tscv.split(X)):
        X_tr, X_va = X[train_idx], X[val_idx]
        y_tr, y_va = y[train_idx], y[val_idx]

        td = lgb.Dataset(X_tr, label=y_tr, feature_name=FEATURE_NAMES,
                         categorical_feature=[FEATURE_NAMES[i] for i in cat_idx])
        vd = lgb.Dataset(X_va, label=y_va, reference=td)

        model = lgb.train(
            params, td, num_boost_round=2000,
            valid_sets=[vd], valid_names=["valid"],
            callbacks=[lgb.early_stopping(100), lgb.log_evaluation(0)],
        )
        models.append(model)
        oof_preds[val_idx] = model.predict(X_va, num_iteration=model.best_iteration)
        oof_mask[val_idx] = True
        importances += model.feature_importance(importance_type="gain")

        val_auc = roc_auc_score(y_va, oof_preds[val_idx])
        logger.info(f"  Fold {fold+1}: AUC={val_auc:.4f}, best_iter={model.best_iteration}")

    importances /= len(models)

    # OOF metrics
    oof_y = y[oof_mask]
    oof_p = oof_preds[oof_mask]
    auc = roc_auc_score(oof_y, oof_p)
    ll = log_loss(oof_y, oof_p)

    # Optimal threshold
    thresholds = np.arange(0.05, 0.5, 0.01)
    best_f1, best_thresh = 0, 0.1
    for t in thresholds:
        pred_cls = (oof_p >= t).astype(int)
        prec, rec, f1, _ = precision_recall_fscore_support(oof_y, pred_cls, average="binary", zero_division=0)
        if f1 > best_f1:
            best_f1, best_thresh = f1, t

    pred_cls = (oof_p >= best_thresh).astype(int)
    prec, rec, f1, _ = precision_recall_fscore_support(oof_y, pred_cls, average="binary", zero_division=0)

    logger.info(f"\n{'='*60}")
    logger.info(f"{label_name.upper()} MODEL RESULTS")
    logger.info(f"{'='*60}")
    logger.info(f"  ROC-AUC:     {auc:.4f}")
    logger.info(f"  LogLoss:     {ll:.4f}")
    logger.info(f"  Optimal threshold: {best_thresh:.2f}")
    logger.info(f"  Precision:   {prec:.4f}")
    logger.info(f"  Recall:      {rec:.4f}")
    logger.info(f"  F1:          {f1:.4f}")
    logger.info(f"  Positive rate: {oof_y.mean()*100:.1f}%")

    # Feature importance
    logger.info(f"\n  Feature Importance (top 10):")
    fi = sorted(zip(FEATURE_NAMES, importances), key=lambda x: -x[1])
    for name, imp in fi[:10]:
        logger.info(f"    {name:25s}: {imp:.0f}")

    # Calibration (isotonic)
    cal_split = int(len(oof_y) * 0.6)
    cal_ir = IsotonicRegression(out_of_bounds="clip")
    cal_ir.fit(oof_p[:cal_split], oof_y[:cal_split])
    cal_preds = cal_ir.predict(oof_p[cal_split:])
    cal_auc = roc_auc_score(oof_y[cal_split:], cal_preds)
    logger.info(f"\n  Calibrated AUC (test set): {cal_auc:.4f}")

    return models, importances, cal_ir, {
        "auc": round(auc, 4),
        "logloss": round(ll, 4),
        "f1": round(f1, 4),
        "precision": round(prec, 4),
        "recall": round(rec, 4),
        "threshold": round(best_thresh, 3),
        "positive_rate": round(float(oof_y.mean()), 4),
        "n_samples": int(oof_mask.sum()),
        "calibrated_auc": round(cal_auc, 4),
    }


def save_artifacts(models, importances, calibrator, metrics, label_name):
    """Save model ensemble and metadata."""
    prefix = f"{label_name}_"

    # Save ensemble
    with open(ARTIFACTS_DIR / f"{prefix}lgbm_ensemble.pkl", "wb") as f:
        pickle.dump(models, f)

    # Save calibrator
    with open(ARTIFACTS_DIR / f"{prefix}calibrator.pkl", "wb") as f:
        pickle.dump(calibrator, f)

    # Save feature names
    with open(ARTIFACTS_DIR / "features.json", "w") as f:
        json.dump(FEATURE_NAMES, f, indent=2)

    # Feature importance
    fi = sorted(zip(FEATURE_NAMES, importances.tolist()), key=lambda x: -x[1])

    # Metadata
    meta = {
        "model_type": "player_soccer_goal",
        "label": label_name,
        "framework": "lightgbm",
        "n_features": len(FEATURE_NAMES),
        "n_models": len(models),
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "metrics": metrics,
        "feature_importance": [{"name": n, "importance": round(v, 1)} for n, v in fi],
        "position_map": POSITION_MAP,
    }
    with open(ARTIFACTS_DIR / f"{prefix}metadata.json", "w") as f:
        json.dump(meta, f, indent=2)

    logger.info(f"\nSaved {label_name} model artifacts to {ARTIFACTS_DIR}/")


def main():
    logger.info("=" * 60)
    logger.info("SOCCER PLAYER GOAL MODEL — TRAINING")
    logger.info("=" * 60)

    rows, league_stats = load_data()
    X, y_scored, y_involved, meta = build_features(rows, league_stats)

    # Train goal scorer model
    models_scored, imp_scored, cal_scored, metrics_scored = train_model(X, y_scored, "scored")
    save_artifacts(models_scored, imp_scored, cal_scored, metrics_scored, "scored")

    # Train goal involvement model (goal OR assist)
    models_involved, imp_involved, cal_involved, metrics_involved = train_model(X, y_involved, "involved")
    save_artifacts(models_involved, imp_involved, cal_involved, metrics_involved, "involved")

    logger.info("\n" + "=" * 60)
    logger.info("TRAINING COMPLETE")
    logger.info("=" * 60)
    logger.info(f"  Scored model:   AUC={metrics_scored['auc']}, F1={metrics_scored['f1']}")
    logger.info(f"  Involved model: AUC={metrics_involved['auc']}, F1={metrics_involved['f1']}")


if __name__ == "__main__":
    main()
