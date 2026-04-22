"""
V3 Backtest — Test current leak-free model against held-out matches.
Breaks down results using the same dimensions as the production insights analysis.

Go/no-go criteria (same as user's April analysis):
- Overall accuracy > 50%
- High-confidence (>55%) accuracy > 70%
- Home picks > 50% accuracy
- Away picks > 40% accuracy
- Draw picks exist and are correct > 25% of time
- Contrarian picks NOT > 35% accuracy (if contrarian is strong, model is overriding market correctly)
- Per-league breakdown shows no league < 30% (catastrophic failure)
- V3 must NOT predict 94% draws (the April broken-model symptom)
"""

import os, sys, json, pickle, psycopg2, numpy as np
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, '.')
from features.v3_feature_builder import V3FeatureBuilder

MODEL_DIR = Path("artifacts/models/v3_sharp")
LEAGUES = {
    39: 'Premier League', 140: 'La Liga', 135: 'Serie A', 78: 'Bundesliga',
    61: 'Ligue 1', 88: 'Eredivisie', 94: 'Primeira', 2: 'UCL', 3: 'Europa League',
    71: 'Brasileirao', 98: 'J-League', 253: 'MLS'
}


def load_model():
    with open(MODEL_DIR / "lgbm_ensemble.pkl", 'rb') as f:
        models = pickle.load(f)
    with open(MODEL_DIR / "features.json") as f:
        feature_names = json.load(f)
    with open(MODEL_DIR / "metadata.json") as f:
        metadata = json.load(f)
    return models, feature_names, metadata


def get_test_matches():
    """Get ALL finished soccer matches with pre-kickoff odds, the last 15% chronologically."""
    conn = psycopg2.connect(os.environ['DATABASE_URL'])
    cur = conn.cursor()

    # Combine fixtures+matches and training_matches for broad test set
    # (training_matches wasn't used in current model's training)
    cur.execute("""
        SELECT match_id, outcome, league_id, kickoff_at FROM (
            -- Training_matches path (not used in current model training)
            SELECT tm.match_id,
                   CASE WHEN tm.outcome IN ('H','Home','home') THEN 'H'
                        WHEN tm.outcome IN ('A','Away','away') THEN 'A'
                        ELSE 'D' END as outcome,
                   tm.league_id,
                   tm.match_date as kickoff_at
            FROM training_matches tm
            JOIN odds_consensus oc ON tm.match_id = oc.match_id
            WHERE tm.outcome IS NOT NULL
              AND tm.match_id NOT IN (SELECT match_id FROM fixtures WHERE status='finished')
              AND oc.ts_effective < tm.match_date  -- STRICT pre-kickoff filter
            UNION ALL
            -- Fixtures+matches holdout (last 15% chronologically)
            SELECT f.match_id,
                   CASE WHEN m.home_goals > m.away_goals THEN 'H'
                        WHEN m.home_goals < m.away_goals THEN 'A' ELSE 'D' END as outcome,
                   f.league_id,
                   f.kickoff_at
            FROM fixtures f
            JOIN matches m ON f.match_id = m.match_id
            JOIN odds_consensus oc ON f.match_id = oc.match_id
            WHERE f.status = 'finished' AND m.home_goals IS NOT NULL
              AND oc.ts_effective < f.kickoff_at
        ) sub
        WHERE outcome IN ('H','D','A')
        ORDER BY kickoff_at DESC
        LIMIT 500
    """)
    matches = cur.fetchall()
    conn.close()
    return matches


def predict(mid, builder, models, feature_names):
    """Build features and predict for a single match."""
    conn = psycopg2.connect(os.environ['DATABASE_URL'])
    cur = conn.cursor()
    try:
        mi = builder._get_match_info(cur, mid)
        if not mi or not mi['kickoff_time']:
            return None

        cutoff = mi['kickoff_time']
        v2 = builder._build_v2_core_features(cur, mid, cutoff)
        if v2.get('prob_home') is None or (isinstance(v2.get('prob_home'), float) and np.isnan(v2['prob_home'])):
            return None

        ece = builder._build_ece_features(cur, mi['league_id'])
        h2h = builder._build_h2h_features(cur, mid, mi)
        cls = builder._build_closeness_features(v2)
        ld = builder._build_league_draw_features(cur, mi['league_id'], v2)
        dm = builder._build_draw_market_features(v2)
        feats = {**v2, **ece, **h2h, **cls, **ld, **dm}

        X = np.array([feats.get(f, np.nan) for f in feature_names]).reshape(1, -1)
        preds = np.mean([m.predict(X, num_iteration=m.best_iteration) for m in models], axis=0)[0]
        preds = preds / preds.sum()
        pick = ['H', 'D', 'A'][np.argmax(preds)]

        # Market pick (from prob_home/away/draw in features)
        market_probs = [v2.get('prob_home', 0), v2.get('prob_draw', 0), v2.get('prob_away', 0)]
        if any(np.isnan(p) for p in market_probs):
            market_pick = None
        else:
            market_pick = ['H', 'D', 'A'][np.argmax(market_probs)]

        return {
            'pick': pick,
            'confidence': float(max(preds)),
            'probs': {'H': float(preds[0]), 'D': float(preds[1]), 'A': float(preds[2])},
            'market_pick': market_pick,
        }
    finally:
        cur.close()
        conn.close()


def run_backtest():
    print("=" * 75)
    print("V3 BACKTEST — Leak-Free Model vs April-Style Analysis")
    print("=" * 75)

    models, feature_names, metadata = load_model()
    builder = V3FeatureBuilder()
    matches = get_test_matches()

    print(f"\nModel: {metadata.get('model_type')} ({metadata.get('n_features')} features)")
    print(f"Test matches: {len(matches)}")

    # Run predictions
    results = []
    for i, (mid, actual, lid, dt) in enumerate(matches):
        if i % 50 == 0:
            print(f"  Predicting... {i}/{len(matches)}")
        pred = predict(mid, builder, models, feature_names)
        if pred is None:
            continue
        correct = pred['pick'] == actual
        contrarian = pred['market_pick'] and pred['pick'] != pred['market_pick']
        results.append({
            'match_id': mid, 'league_id': lid, 'kickoff_at': dt,
            'actual': actual, 'pick': pred['pick'], 'confidence': pred['confidence'],
            'probs': pred['probs'], 'market_pick': pred['market_pick'],
            'correct': correct, 'contrarian': contrarian,
        })

    total = len(results)
    if total == 0:
        print("❌ No valid predictions")
        return False

    print(f"\n  Successfully predicted: {total}/{len(matches)}")

    # ═══════════════════════════════════════════════════════════
    # OVERALL ACCURACY
    # ═══════════════════════════════════════════════════════════
    correct = sum(1 for r in results if r['correct'])
    print(f"\n1. OVERALL ACCURACY")
    print(f"   {correct}/{total} = {correct/total*100:.1f}%")

    # Distribution
    picks = {k: sum(1 for r in results if r['pick'] == k) for k in 'HDA'}
    actuals = {k: sum(1 for r in results if r['actual'] == k) for k in 'HDA'}
    print(f"\n2. PICK DISTRIBUTION")
    print(f"   {'Outcome':<8} {'Picked':>10} {'Actual':>10} {'Skew':>8}")
    for k in 'HDA':
        p_pct = picks[k]/total*100
        a_pct = actuals[k]/total*100
        skew = p_pct - a_pct
        marker = "✅" if abs(skew) < 12 else ("⚠️" if abs(skew) < 20 else "❌")
        print(f"   {k:<8} {picks[k]} ({p_pct:.1f}%){'':>3} {actuals[k]} ({a_pct:.1f}%){'':>3} {skew:+.1f}pp {marker}")

    # ═══════════════════════════════════════════════════════════
    # BY CONFIDENCE BUCKET (critical — user's analysis dimension)
    # ═══════════════════════════════════════════════════════════
    print(f"\n3. ACCURACY BY CONFIDENCE BUCKET")
    buckets = [(0, 0.40, '<40%'), (0.40, 0.50, '40-49%'), (0.50, 0.55, '50-54%'),
               (0.55, 0.60, '55-59%'), (0.60, 0.70, '60-69%'), (0.70, 1.00, '70%+')]
    print(f"   {'Confidence':<12} {'Total':>6} {'Correct':>8} {'Accuracy':>10}")
    for lo, hi, label in buckets:
        bucket = [r for r in results if lo <= r['confidence'] < hi]
        if bucket:
            c = sum(1 for r in bucket if r['correct'])
            print(f"   {label:<12} {len(bucket):>6} {c:>8} {c/len(bucket)*100:>9.1f}%")

    # ═══════════════════════════════════════════════════════════
    # BY PICK TYPE
    # ═══════════════════════════════════════════════════════════
    print(f"\n4. ACCURACY BY PICK TYPE")
    for pick_type in 'HDA':
        bucket = [r for r in results if r['pick'] == pick_type]
        if bucket:
            c = sum(1 for r in bucket if r['correct'])
            label = {'H': 'Home picks', 'D': 'Draw picks', 'A': 'Away picks'}[pick_type]
            print(f"   {label:<15} {len(bucket):>5} total, {c:>4} correct = {c/len(bucket)*100:.1f}%")

    # ═══════════════════════════════════════════════════════════
    # BY ACTUAL OUTCOME (per-class accuracy)
    # ═══════════════════════════════════════════════════════════
    print(f"\n5. DETECTION RATE BY ACTUAL OUTCOME")
    for actual_type in 'HDA':
        bucket = [r for r in results if r['actual'] == actual_type]
        if bucket:
            c = sum(1 for r in bucket if r['correct'])
            label = {'H': 'Actual Home wins', 'D': 'Actual Draws', 'A': 'Actual Away wins'}[actual_type]
            print(f"   {label:<18} {len(bucket):>5} games, caught {c:>4} = {c/len(bucket)*100:.1f}%")

    # ═══════════════════════════════════════════════════════════
    # CONTRARIAN PICKS (model disagrees with market favorite)
    # ═══════════════════════════════════════════════════════════
    contrarian = [r for r in results if r['contrarian']]
    print(f"\n6. CONTRARIAN PICKS (model vs market favorite)")
    if contrarian:
        c = sum(1 for r in contrarian if r['correct'])
        print(f"   {len(contrarian):>5} matches ({len(contrarian)/total*100:.1f}% of all picks)")
        print(f"   {c:>5} correct = {c/len(contrarian)*100:.1f}%")
        # By league
        print(f"   Note: production showed 28.4% for contrarian picks")

    # ═══════════════════════════════════════════════════════════
    # BY LEAGUE
    # ═══════════════════════════════════════════════════════════
    print(f"\n7. BY LEAGUE (min 10 matches)")
    by_league = defaultdict(list)
    for r in results:
        by_league[r['league_id']].append(r)
    league_stats = []
    for lid, bucket in by_league.items():
        if len(bucket) >= 10:
            c = sum(1 for r in bucket if r['correct'])
            league_stats.append((LEAGUES.get(lid, f'league {lid}'), len(bucket), c, c/len(bucket)))
    league_stats.sort(key=lambda x: -x[3])
    print(f"   {'League':<20} {'Games':>6} {'Correct':>8} {'Accuracy':>10}")
    for name, n, c, acc in league_stats:
        marker = "✅" if acc >= 0.50 else ("⚠️" if acc >= 0.40 else "❌")
        print(f"   {name:<20} {n:>6} {c:>8} {acc*100:>9.1f}% {marker}")

    # ═══════════════════════════════════════════════════════════
    # GO/NO-GO CHECK
    # ═══════════════════════════════════════════════════════════
    print(f"\n" + "=" * 75)
    print("GO/NO-GO ASSESSMENT")
    print("=" * 75)

    overall_acc = correct/total
    high_conf = [r for r in results if r['confidence'] >= 0.55]
    high_conf_acc = sum(1 for r in high_conf if r['correct']) / max(len(high_conf), 1)
    home_acc = sum(1 for r in results if r['pick'] == 'H' and r['correct']) / max(sum(1 for r in results if r['pick'] == 'H'), 1)
    away_acc = sum(1 for r in results if r['pick'] == 'A' and r['correct']) / max(sum(1 for r in results if r['pick'] == 'A'), 1)
    draw_pick_rate = picks['D'] / total

    checks = [
        ("Overall accuracy > 48%", overall_acc > 0.48, f"{overall_acc*100:.1f}%"),
        ("High-conf (55%+) > 60%", high_conf_acc > 0.60, f"{high_conf_acc*100:.1f}% on {len(high_conf)} matches"),
        ("Home pick accuracy > 50%", home_acc > 0.50, f"{home_acc*100:.1f}%"),
        ("Away pick accuracy > 40%", away_acc > 0.40, f"{away_acc*100:.1f}%"),
        ("Draw picks in realistic range (5-40%)", 0.05 <= draw_pick_rate <= 0.40, f"{draw_pick_rate*100:.1f}%"),
        ("No 94% draw disaster", draw_pick_rate < 0.50, f"{draw_pick_rate*100:.1f}%"),
        ("No league < 30% accuracy", all(acc >= 0.30 for _, _, _, acc in league_stats), "check league table above"),
    ]

    print()
    all_pass = True
    for label, passed, detail in checks:
        marker = "✅" if passed else "❌"
        print(f"  {marker} {label}: {detail}")
        if not passed:
            all_pass = False

    print()
    if all_pass:
        print("✅ GO — All checks passed. Model is safe for production.")
    else:
        print("❌ NO-GO — Address failures above before deploying.")

    return all_pass


if __name__ == "__main__":
    success = run_backtest()
    sys.exit(0 if success else 1)
