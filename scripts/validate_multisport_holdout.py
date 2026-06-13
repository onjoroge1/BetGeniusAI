"""
Multisport holdout gate (P2) — does each sport's model beat "pick the consensus
favorite"? Same discipline as scripts/validate_temporal_holdout.py (soccer).

For each finished event with consensus odds AND a result:
  - model pick   : MultisportV3Predictor.predict()
  - favorite pick: argmax of de-vigged consensus (lowest odds)
  - score both against the actual result
Reports per-sport: n, model_acc, favorite_acc, delta, Brier, and a VERDICT that
gates utils.edge.MODEL_REGISTRY[...].edge_validated.

Honest by construction: with small N we report INSUFFICIENT_SAMPLE rather than a
verdict (NBA/MLB mainlines are the most efficient markets in existence — do not
flip edge_validated on 30 games of noise).

Usage: python scripts/validate_multisport_holdout.py [--sport basketball_nba] [--min-n 100]
"""

import os
import re
import sys
import json
import argparse
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

import psycopg2

parser = argparse.ArgumentParser()
parser.add_argument("--sport", default=None, help="restrict to one sport_key")
parser.add_argument("--min-n", type=int, default=100,
                    help="below this, report INSUFFICIENT_SAMPLE (default 100)")
args = parser.parse_args()


def devig2(home_odds, away_odds):
    ph, pa = 1.0 / home_odds, 1.0 / away_odds
    t = ph + pa
    return ph / t, pa / t


def run_sport(sport_key, min_n):
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()
    cur.execute("""
        SELECT f.event_id, f.home_team, f.away_team, f.commence_time,
               o.home_odds, o.away_odds, r.result
        FROM multisport_match_results r
        JOIN multisport_fixtures f USING(event_id)
        JOIN LATERAL (
            SELECT home_odds, away_odds FROM multisport_odds_snapshots s
            WHERE s.event_id = r.event_id AND s.is_consensus = true
              AND s.home_odds > 1.0 AND s.away_odds > 1.0
            ORDER BY s.ts_recorded DESC LIMIT 1
        ) o ON true
        WHERE f.sport_key = %s AND r.result IN ('H','A')
    """, (sport_key,))
    rows = cur.fetchall()
    conn.close()

    if not rows:
        return {"sport": sport_key, "n_with_odds": 0, "verdict": "NO_DATA"}

    try:
        from models.multisport_v3_predictor import get_multisport_predictor
        from dateutil.parser import parse as dtparse
        predictor = get_multisport_predictor(sport_key)
    except Exception as e:
        predictor = None
        pred_err = str(e)

    n = 0
    model_correct = fav_correct = 0
    model_brier = 0.0
    fav_brier = 0.0
    model_failures = 0
    for event_id, home, away, ct, ho, fo, result in rows:
        res_home = 1.0 if result == "H" else 0.0
        fph, fpa = devig2(float(ho), float(fo))
        fav = "H" if fph >= fpa else "A"

        p_home = None
        if predictor:
            try:
                gd = ct if isinstance(ct, datetime) else dtparse(str(ct))
                pr = predictor.predict(sport_key=sport_key, event_id=event_id,
                                       home_team=home, away_team=away, game_date=gd)
                if pr:
                    p_home = float(pr["prob_home"])
            except Exception:
                model_failures += 1
        if p_home is None:
            continue

        n += 1
        model_pick = "H" if p_home >= 0.5 else "A"
        model_correct += int(model_pick == result)
        fav_correct += int(fav == result)
        model_brier += (p_home - res_home) ** 2
        fav_brier += (fph - res_home) ** 2

    if n == 0:
        return {"sport": sport_key, "n_with_odds": len(rows), "n_scored": 0,
                "verdict": "MODEL_UNAVAILABLE",
                "note": pred_err if not predictor else f"{model_failures} prediction failures"}

    model_acc = model_correct / n
    fav_acc = fav_correct / n
    verdict = ("INSUFFICIENT_SAMPLE" if n < min_n
               else "PASS" if model_acc > fav_acc
               else "FAIL")
    return {
        "sport": sport_key,
        "n_with_odds": len(rows),
        "n_scored": n,
        "model_accuracy": round(model_acc, 4),
        "favorite_accuracy": round(fav_acc, 4),
        "delta_pp": round((model_acc - fav_acc) * 100, 2),
        "model_brier": round(model_brier / n, 4),
        "favorite_brier": round(fav_brier / n, 4),
        "verdict": verdict,
        "edge_validated_recommendation": verdict == "PASS",
    }


SPORTS = [args.sport] if args.sport else ["basketball_nba", "icehockey_nhl", "basketball_ncaab"]
results = []
print("Multisport holdout gate — model vs consensus-favorite\n" + "=" * 56)
for sk in SPORTS:
    r = run_sport(sk, args.min_n)
    results.append(r)
    print(f"\n{sk}")
    for k, v in r.items():
        if k != "sport":
            print(f"  {k:32} {v}")

out = REPO / "scripts" / "multisport_holdout_result.json"
out.write_text(json.dumps({"validated_at": datetime.now(timezone.utc).isoformat(),
                           "min_n": args.min_n, "results": results}, indent=2))
print(f"\nSaved → {out}")
print("\nVERDICT SUMMARY:")
for r in results:
    print(f"  {r['sport']:22} {r['verdict']:20} "
          f"(n={r.get('n_scored', 0)}, Δ={r.get('delta_pp', 'n/a')}pp)")
print("\nAll sports remain edge_validated=False until a PASS on n>=min_n. "
      "Efficient mainline markets are expected to stay FAIL/INSUFFICIENT.")
