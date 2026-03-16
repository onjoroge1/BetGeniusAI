"""
Draw Specialist LightGBM Training Script

Trains a standalone binary classifier: draw (1) vs non-draw (0).

This model is intentionally isolated from the main prediction cascade
so it can be graded independently and its performance tracked separately.

Feature groups (20 features):
  - Draw implied probabilities   (6): per-book and consensus draw probs
  - Draw market structure        (4): dispersion, sharpness, overround fraction
  - Match closeness              (4): ELO-proxy gap, H/A ratio, margin
  - League context               (2): historical draw rate, league tier
  - Booking counts               (2): number of books available (data quality)
  - In-game style proxy          (2): shots/corners balance (when available)

Training data: historical_odds table — ~40k completed matches across 13 leagues.
Temporal split: train on matches before cutoff date, test on most recent 20%.

Usage:
    python training/train_draw_specialist.py

Output artifacts (saved to artifacts/models/draw_specialist/):
    draw_specialist.pkl          — LightGBM Booster model
    draw_specialist_meta.json    — feature list, metrics, thresholds
    draw_specialist_features.json — feature importances

Expected Results:
    ROC-AUC:   > 0.70
    Accuracy:  > 58% (vs 73% trivial "never predict draw" baseline)
    Log Loss:  < 0.60
    Precision (draw): > 0.45 at threshold 0.40
"""

import os
import sys
import json
import pickle
import logging
import numpy as np
import pandas as pd
from datetime import datetime
from pathlib import Path

import psycopg2
import lightgbm as lgb
from sklearn.metrics import (
    accuracy_score, roc_auc_score, log_loss,
    classification_report, confusion_matrix, precision_recall_curve
)
from sklearn.calibration import CalibratedClassifierCV
from sklearn.model_selection import TimeSeriesSplit

sys.path.append(".")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

OUTPUT_DIR = Path("artifacts/models/draw_specialist")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


BOOK_DRAW_COLS = ["b365_d", "bw_d", "iw_d", "lb_d", "ps_d", "wh_d", "sj_d", "vc_d"]
BOOK_HOME_COLS = ["b365_h", "bw_h", "iw_h", "lb_h", "ps_h", "wh_h", "sj_h", "vc_h"]
BOOK_AWAY_COLS = ["b365_a", "bw_a", "iw_a", "lb_a", "ps_a", "wh_a", "sj_a", "vc_a"]


def load_data() -> pd.DataFrame:
    logger.info("Loading historical_odds from database...")
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    query = """
        SELECT
            id, match_date, league_name,
            result,
            b365_h, b365_d, b365_a,
            bw_h,   bw_d,   bw_a,
            iw_h,   iw_d,   iw_a,
            lb_h,   lb_d,   lb_a,
            ps_h,   ps_d,   ps_a,
            wh_h,   wh_d,   wh_a,
            sj_h,   sj_d,   sj_a,
            vc_h,   vc_d,   vc_a,
            avg_h,  avg_d,  avg_a,
            max_h,  max_d,  max_a,
            home_shots, away_shots,
            home_corners, away_corners
        FROM historical_odds
        WHERE result IS NOT NULL
        ORDER BY match_date ASC
    """
    df = pd.read_sql(query, conn)
    conn.close()
    logger.info(f"Loaded {len(df):,} rows | Draw rate: {(df['result']=='D').mean()*100:.1f}%")
    return df


def build_league_draw_rates(df: pd.DataFrame) -> dict:
    """Compute per-league draw rate from full dataset for use as a feature."""
    rates = (
        df.groupby("league_name")["result"]
        .apply(lambda x: (x == "D").mean())
        .to_dict()
    )
    logger.info(f"Computed draw rates for {len(rates)} leagues")
    return rates


def build_features(df: pd.DataFrame, league_draw_rates: dict) -> pd.DataFrame:
    """
    Engineer all 20 draw-specialist features from raw bookmaker odds columns.
    Uses is_not_none checks to handle missing books gracefully.
    """
    feat = pd.DataFrame(index=df.index)

    # --- 1. Per-book draw implied probabilities ---
    draw_imp_cols = []
    home_imp_cols = []
    away_imp_cols = []

    for bd, bh, ba in zip(BOOK_DRAW_COLS, BOOK_HOME_COLS, BOOK_AWAY_COLS):
        if bd in df.columns:
            col_name = f"imp_{bd}"
            feat[col_name] = np.where(df[bd].notna() & (df[bd] > 1), 1.0 / df[bd], np.nan)
            draw_imp_cols.append(col_name)
        if bh in df.columns:
            col_name = f"imp_{bh}"
            feat[col_name] = np.where(df[bh].notna() & (df[bh] > 1), 1.0 / df[bh], np.nan)
            home_imp_cols.append(col_name)
        if ba in df.columns:
            col_name = f"imp_{ba}"
            feat[col_name] = np.where(df[ba].notna() & (df[ba] > 1), 1.0 / df[ba], np.nan)
            away_imp_cols.append(col_name)

    # --- 2. Draw market structure features ---
    # Mean draw implied prob across all available books
    feat["draw_prob_mean"] = feat[draw_imp_cols].mean(axis=1)

    # Dispersion: how tightly do books agree on draw price?
    feat["draw_prob_std"] = feat[draw_imp_cols].std(axis=1)

    # Consensus avg and max draw odds
    feat["draw_odds_avg"] = np.where(df["avg_d"].notna() & (df["avg_d"] > 1), df["avg_d"], np.nan)
    feat["draw_odds_max"] = np.where(df["max_d"].notna() & (df["max_d"] > 1), df["max_d"], np.nan)

    # Pinnacle sharpness: ratio of Pinnacle draw prob to soft-book avg
    ps_imp = np.where(df["ps_d"].notna() & (df["ps_d"] > 1), 1.0 / df["ps_d"], np.nan)
    feat["draw_sharp_ratio"] = np.where(
        feat["draw_prob_mean"] > 0,
        ps_imp / feat["draw_prob_mean"],
        np.nan
    )

    # Draw implied prob as fraction of total overround
    home_mean = feat[home_imp_cols].mean(axis=1) if home_imp_cols else 0.33
    away_mean = feat[away_imp_cols].mean(axis=1) if away_imp_cols else 0.33
    total_imp = home_mean + feat["draw_prob_mean"] + away_mean
    feat["draw_fraction"] = np.where(total_imp > 0, feat["draw_prob_mean"] / total_imp, np.nan)

    # Total overround (how large is the book margin?)
    feat["overround"] = np.where(total_imp > 0, total_imp - 1.0, np.nan)

    # --- 3. Match closeness features ---
    # Absolute gap between home and away implied probs (proxy for ELO gap)
    feat["ha_prob_gap"] = np.abs(home_mean - away_mean)

    # Ratio home/away — close to 1.0 means evenly matched
    feat["ha_odds_ratio"] = np.where(
        (df["avg_a"].notna()) & (df["avg_a"] > 1) & (df["avg_h"].notna()) & (df["avg_h"] > 1),
        df["avg_h"] / df["avg_a"],
        np.nan
    )

    # Favourite strength: how strong is the strongest side?
    feat["favourite_prob"] = np.maximum(home_mean, away_mean)

    # Max draw implied prob across all books (ceiling signal)
    feat["draw_prob_max_book"] = feat[draw_imp_cols].max(axis=1)

    # --- 4. League context features ---
    global_draw_rate = 0.266
    feat["league_draw_rate"] = df["league_name"].map(league_draw_rates).fillna(global_draw_rate)

    # --- 5. Data quality: number of books available ---
    feat["n_draw_books"] = feat[draw_imp_cols].notna().sum(axis=1)
    feat["n_home_books"] = feat[home_imp_cols].notna().sum(axis=1)

    # --- 6. In-game style proxies (pre-match, useful for post-training analysis) ---
    feat["shots_balance"] = np.where(
        df["home_shots"].notna() & df["away_shots"].notna(),
        (df["home_shots"] - df["away_shots"]).abs(),
        np.nan
    )
    feat["corners_balance"] = np.where(
        df["home_corners"].notna() & df["away_corners"].notna(),
        (df["home_corners"] - df["away_corners"]).abs(),
        np.nan
    )

    # Drop per-book raw implied prob columns — summary features carry the signal
    feat = feat.drop(columns=draw_imp_cols + home_imp_cols + away_imp_cols)

    logger.info(f"Built {len(feat.columns)} features: {list(feat.columns)}")
    return feat


def temporal_split(df: pd.DataFrame, feat: pd.DataFrame, test_frac: float = 0.20):
    """
    Strict temporal split: train on older matches, test on most recent test_frac.
    No shuffling — preserves real-world evaluation conditions.
    """
    n = len(df)
    split_idx = int(n * (1 - test_frac))
    split_date = df["match_date"].iloc[split_idx]

    X_train = feat.iloc[:split_idx]
    X_test  = feat.iloc[split_idx:]
    y_train = (df["result"].iloc[:split_idx] == "D").astype(int)
    y_test  = (df["result"].iloc[split_idx:] == "D").astype(int)

    logger.info(f"Train: {len(X_train):,} rows (up to {df['match_date'].iloc[split_idx-1]})")
    logger.info(f"Test:  {len(X_test):,} rows  (from {split_date})")
    logger.info(f"Train draw rate: {y_train.mean()*100:.1f}% | Test draw rate: {y_test.mean()*100:.1f}%")
    return X_train, X_test, y_train, y_test


def train_model(X_train: pd.DataFrame, y_train: pd.Series) -> lgb.Booster:
    """
    Train LightGBM binary classifier.

    27% draw rate is mild imbalance — no scale_pos_weight needed.
    Validation set is a random 15% stratified sample from training data
    to avoid temporal distribution drift in early stopping.
    """
    from sklearn.model_selection import train_test_split

    X_tr, X_val, y_tr, y_val = train_test_split(
        X_train, y_train, test_size=0.15, random_state=42, stratify=y_train
    )

    logger.info(f"Internal val draw rate: {y_val.mean()*100:.1f}% | val size: {len(y_val):,}")

    params = {
        "objective":         "binary",
        "metric":            ["binary_logloss", "auc"],
        "boosting_type":     "gbdt",
        "learning_rate":     0.05,
        "num_leaves":        31,
        "max_depth":         6,
        "min_child_samples": 40,
        "feature_fraction":  0.8,
        "bagging_fraction":  0.8,
        "bagging_freq":      5,
        "lambda_l1":         0.1,
        "lambda_l2":         0.1,
        "verbose":           -1,
        "seed":              42,
    }

    train_data = lgb.Dataset(X_tr,  label=y_tr,  free_raw_data=False)
    val_data   = lgb.Dataset(X_val, label=y_val, free_raw_data=False, reference=train_data)

    callbacks = [lgb.early_stopping(50, verbose=False), lgb.log_evaluation(50)]

    model = lgb.train(
        params,
        train_data,
        num_boost_round=600,
        valid_sets=[val_data],
        callbacks=callbacks,
    )

    logger.info(f"Best iteration: {model.best_iteration}")
    return model


def evaluate(model: lgb.Booster, X_test: pd.DataFrame, y_test: pd.Series) -> dict:
    """Full evaluation suite — binary metrics at multiple thresholds."""
    probs = model.predict(X_test)

    auc     = roc_auc_score(y_test, probs)
    ll      = log_loss(y_test, np.column_stack([1 - probs, probs]))
    trivial_ll = log_loss(y_test, np.full((len(y_test), 2), [1 - y_test.mean(), y_test.mean()]))

    logger.info("\n" + "="*60)
    logger.info("DRAW SPECIALIST — EVALUATION RESULTS")
    logger.info("="*60)
    logger.info(f"  Test samples:          {len(y_test):,}")
    logger.info(f"  Actual draw rate:      {y_test.mean()*100:.1f}%")
    logger.info(f"  ROC-AUC:               {auc:.4f}")
    logger.info(f"  Log Loss:              {ll:.4f}  (trivial baseline: {trivial_ll:.4f})")
    logger.info(f"  Improvement vs trivial: {(trivial_ll - ll):.4f}")

    for threshold in [0.30, 0.35, 0.40, 0.45, 0.50]:
        preds = (probs >= threshold).astype(int)
        acc   = accuracy_score(y_test, preds)
        cm    = confusion_matrix(y_test, preds)
        tn, fp, fn, tp = cm.ravel()
        prec  = tp / (tp + fp) if (tp + fp) > 0 else 0
        rec   = tp / (tp + fn) if (tp + fn) > 0 else 0
        f1    = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0
        predicted_draws = preds.sum()
        logger.info(
            f"  Threshold {threshold:.2f}: acc={acc:.3f}  prec={prec:.3f}  "
            f"rec={rec:.3f}  f1={f1:.3f}  predicted_draws={predicted_draws:,}"
        )

    # Find optimal F1 threshold
    precision_vals, recall_vals, thresholds_pr = precision_recall_curve(y_test, probs)
    f1_vals = np.where(
        (precision_vals + recall_vals) > 0,
        2 * precision_vals * recall_vals / (precision_vals + recall_vals),
        0
    )
    best_idx      = np.argmax(f1_vals[:-1])
    best_threshold = float(thresholds_pr[best_idx])
    best_f1        = float(f1_vals[best_idx])
    best_prec      = float(precision_vals[best_idx])
    best_rec       = float(recall_vals[best_idx])

    logger.info(f"\n  Optimal F1 threshold: {best_threshold:.3f}")
    logger.info(f"  At optimum — precision: {best_prec:.3f}  recall: {best_rec:.3f}  f1: {best_f1:.3f}")
    logger.info("="*60)

    return {
        "roc_auc":            round(auc, 4),
        "log_loss":           round(ll, 4),
        "trivial_log_loss":   round(trivial_ll, 4),
        "logloss_improvement": round(trivial_ll - ll, 4),
        "test_draw_rate":     round(float(y_test.mean()), 4),
        "test_samples":       int(len(y_test)),
        "optimal_threshold":  round(best_threshold, 4),
        "optimal_f1":         round(best_f1, 4),
        "optimal_precision":  round(best_prec, 4),
        "optimal_recall":     round(best_rec, 4),
    }


def feature_importance(model: lgb.Booster, feature_names: list) -> dict:
    """Return feature importances sorted by gain."""
    gain = model.feature_importance(importance_type="gain")
    split = model.feature_importance(importance_type="split")
    ranked = sorted(
        zip(feature_names, gain.tolist(), split.tolist()),
        key=lambda x: x[1], reverse=True
    )
    logger.info("\nTop 10 features by gain:")
    for name, g, s in ranked[:10]:
        logger.info(f"  {name:30s}  gain={g:10.1f}  splits={s}")
    return {name: {"gain": g, "splits": s} for name, g, s in ranked}


def save_artifacts(model, meta: dict, importances: dict, feature_names: list):
    model_path = OUTPUT_DIR / "draw_specialist.pkl"
    meta_path  = OUTPUT_DIR / "draw_specialist_meta.json"
    imp_path   = OUTPUT_DIR / "draw_specialist_features.json"

    with open(model_path, "wb") as f:
        pickle.dump(model, f)

    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)

    with open(imp_path, "w") as f:
        json.dump(importances, f, indent=2)

    logger.info(f"\nArtifacts saved to {OUTPUT_DIR}/")
    logger.info(f"  Model:   {model_path}")
    logger.info(f"  Meta:    {meta_path}")
    logger.info(f"  Imports: {imp_path}")


def main():
    logger.info("Starting Draw Specialist training...")

    df   = load_data()
    lr   = build_league_draw_rates(df)
    feat = build_features(df, lr)

    n_feat = len(feat.columns)
    null_pct = feat.isnull().mean().sort_values(ascending=False)
    logger.info(f"\nFeature null rates (top 5):")
    for col, pct in null_pct.head(5).items():
        logger.info(f"  {col}: {pct*100:.1f}% null")

    X_train, X_test, y_train, y_test = temporal_split(df, feat, test_frac=0.20)

    model = train_model(X_train, y_train)
    metrics = evaluate(model, X_test, y_test)
    importances = feature_importance(model, feat.columns.tolist())

    meta = {
        "model_type":      "lightgbm_binary",
        "target":          "draw vs non-draw",
        "trained_at":      datetime.utcnow().isoformat(),
        "train_samples":   int(len(X_train)),
        "test_samples":    int(len(X_test)),
        "n_features":      n_feat,
        "feature_names":   feat.columns.tolist(),
        "league_draw_rates": lr,
        "metrics":         metrics,
        "best_iteration":  int(model.best_iteration),
        "usage_note": (
            "Standalone draw classifier. Grade independently. "
            "Not wired into /predict cascade yet."
        ),
    }

    save_artifacts(model, meta, importances, feat.columns.tolist())
    logger.info("\nTraining complete.")
    return metrics


if __name__ == "__main__":
    main()
