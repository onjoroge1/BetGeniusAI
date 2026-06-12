"""
Line-Shopping Validation — the council's Phase-0 gate (2026-06-12)
==================================================================
Tests whether the claimed +2.5-3.4% "best price vs Pinnacle close" edge in
historical_odds is REAL or a data artifact, before any product is built on it.

Data: historical_odds rows where Pinnacle close (ps_h/d/a), market best price
(max_h/d/a — football-data.co.uk Betbrain best-of-N), and result all exist.
Both prices are closing-time, same row — no timestamp/name join needed.

Artifact checks (each can fake the edge):
  1. VIG CHECK     — max_ is best-of-N across books. If its synthetic overround
                     is < 1.0, the "edge" is just summing quotes that never
                     coexisted at one book (an un-takeable arb). Median
                     overround_max must be >= 0.99.
  2. CHERRY-PICK   — betting all three outcomes at best price post-hoc leaks.
                     The decisive test is FAVORITE-ONLY: pick the Pinnacle
                     favorite, compare returns at ps price vs max price.
  3. COVERAGE      — max_ must be present on the same rows as ps_ (no
                     longshot-selection bias). Report overlap %.
  4. EXECUTABILITY — a historical best quote isn't a fillable price. Haircut:
                     assume you get ps + 50% of the (max - ps) gap.

Decision gate (council):
  PROCEED  : favorite-only edge >= +1.5pp AND median overround_max >= 0.99
             AND haircut edge > 0
  MARGINAL : edge in (0, +1.5pp) or only survives full gap
  KILL     : favorite-only edge <= 0 OR overround_max < 0.99 drives the edge

Usage: python scripts/validate_line_shopping.py
Writes scripts/line_shopping_result.json
"""

import os
import re
import sys
import json
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

OUT = {"H": 0, "D": 1, "A": 2}

conn = psycopg2.connect(os.environ["DATABASE_URL"])
cur = conn.cursor()

# Coverage / overlap first
cur.execute("""
    SELECT COUNT(*) FILTER (WHERE ps_h IS NOT NULL AND ps_d IS NOT NULL AND ps_a IS NOT NULL),
           COUNT(*) FILTER (WHERE max_h IS NOT NULL AND max_d IS NOT NULL AND max_a IS NOT NULL),
           COUNT(*) FILTER (WHERE ps_h IS NOT NULL AND max_h IS NOT NULL
                            AND ps_d IS NOT NULL AND max_d IS NOT NULL
                            AND ps_a IS NOT NULL AND max_a IS NOT NULL
                            AND result IN ('H','D','A')),
           COUNT(*)
    FROM historical_odds
""")
n_ps, n_max, n_both, n_total = cur.fetchone()

cur.execute("""
    SELECT ps_h, ps_d, ps_a, max_h, max_d, max_a, result, match_date, league
    FROM historical_odds
    WHERE ps_h IS NOT NULL AND ps_d IS NOT NULL AND ps_a IS NOT NULL
      AND max_h IS NOT NULL AND max_d IS NOT NULL AND max_a IS NOT NULL
      AND ps_h > 1.0 AND ps_d > 1.0 AND ps_a > 1.0
      AND max_h > 1.0 AND max_d > 1.0 AND max_a > 1.0
      AND result IN ('H','D','A')
""")
rows = cur.fetchall()
conn.close()

n = len(rows)
print(f"Line-shopping validation  |  {n:,} matches with Pinnacle + best price + result")
print(f"Coverage: ps={n_ps:,}  max={n_max:,}  both+result={n_both:,}  total={n_total:,}  "
      f"overlap={100.0*n_both/max(n_ps,1):.1f}% of ps rows")

ov_ps_list, ov_max_list = [], []
ret_fav_ps, ret_fav_max, ret_fav_haircut = [], [], []
blind = {k: {"ps": [], "mx": []} for k in ("H", "D", "A")}

for ps_h, ps_d, ps_a, mx_h, mx_d, mx_a, result, mdate, league in rows:
    ps = [float(ps_h), float(ps_d), float(ps_a)]
    mx = [float(mx_h), float(mx_d), float(mx_a)]
    ov_ps = sum(1.0 / o for o in ps)
    ov_mx = sum(1.0 / o for o in mx)
    ov_ps_list.append(ov_ps)
    ov_max_list.append(ov_mx)

    res_idx = OUT[result]

    # Favorite per Pinnacle = lowest ps odds (pre-result info only)
    fav = min(range(3), key=lambda i: ps[i])
    win = 1.0 if fav == res_idx else 0.0
    ret_fav_ps.append(win * ps[fav] - 1.0)
    ret_fav_max.append(win * mx[fav] - 1.0)
    haircut_odds = ps[fav] + 0.5 * (mx[fav] - ps[fav])
    ret_fav_haircut.append(win * haircut_odds - 1.0)

    # Context: blind single-outcome strategies
    for k, i in OUT.items():
        w = 1.0 if i == res_idx else 0.0
        blind[k]["ps"].append(w * ps[i] - 1.0)
        blind[k]["mx"].append(w * mx[i] - 1.0)

def mean(xs):
    return sum(xs) / len(xs) if xs else 0.0

def median(xs):
    s = sorted(xs)
    m = len(s) // 2
    return s[m] if len(s) % 2 else 0.5 * (s[m - 1] + s[m])

ov_ps_med = median(ov_ps_list)
ov_mx_med = median(ov_max_list)
fav_ps = mean(ret_fav_ps)
fav_mx = mean(ret_fav_max)
fav_hc = mean(ret_fav_haircut)
edge_full = fav_mx - fav_ps
edge_hc = fav_hc - fav_ps

print()
print(f"  Overround (median):   Pinnacle {ov_ps_med:.4f}   |   best-price {ov_mx_med:.4f}")
print(f"  {'(overround_max < 1.0 means the best-of-N edge is a synthetic arb artifact)'}")
print()
print(f"  FAVORITE-ONLY (the decisive test, n={n:,}):")
print(f"    return @ Pinnacle close : {fav_ps:+.4f}  ({fav_ps*100:+.2f}%)")
print(f"    return @ best price     : {fav_mx:+.4f}  ({fav_mx*100:+.2f}%)")
print(f"    edge (full gap)         : {edge_full*100:+.2f}pp")
print(f"    edge (50% haircut)      : {edge_hc*100:+.2f}pp   → return {fav_hc*100:+.2f}%")
print()
print("  Context — blind single-outcome returns (ps → max):")
for k in ("H", "D", "A"):
    print(f"    always-{k}: {mean(blind[k]['ps'])*100:+.2f}% → {mean(blind[k]['mx'])*100:+.2f}%")

# Gate
vig_ok = ov_mx_med >= 0.99
edge_ok = edge_full >= 0.015
haircut_ok = fav_hc > fav_ps and fav_hc > -0.005  # haircut return ~breakeven or better

print()
print("  DECISION GATE:")
print(f"    favorite-only edge >= +1.5pp ....... {'✅' if edge_ok else '❌'}  ({edge_full*100:+.2f}pp)")
print(f"    median overround_max >= 0.99 ....... {'✅' if vig_ok else '❌'}  ({ov_mx_med:.4f})")
print(f"    haircut return viable .............. {'✅' if haircut_ok else '❌'}  ({fav_hc*100:+.2f}%)")
print()
if edge_ok and vig_ok and haircut_ok:
    verdict = "PROCEED"
    print("  ✅ PROCEED — line-shopping edge is real. Build the value-alert product.")
elif edge_full > 0 and (vig_ok or haircut_ok):
    verdict = "MARGINAL"
    print("  ➖ MARGINAL — edge exists but thin/partially artifact. Paper-trade on the live feed first.")
else:
    verdict = "KILL"
    print("  ❌ KILL — the edge is an artifact (synthetic best-of-N arb or not executable).")

result = {
    "validated_at": datetime.now(timezone.utc).isoformat(),
    "n_matches": n,
    "overlap_pct_of_ps": round(100.0 * n_both / max(n_ps, 1), 1),
    "overround_ps_median": round(ov_ps_med, 4),
    "overround_max_median": round(ov_mx_med, 4),
    "favorite_return_at_pinnacle": round(fav_ps, 4),
    "favorite_return_at_best": round(fav_mx, 4),
    "favorite_return_at_haircut": round(fav_hc, 4),
    "edge_full_pp": round(edge_full * 100, 2),
    "edge_haircut_pp": round(edge_hc * 100, 2),
    "blind_returns": {k: {"ps": round(mean(blind[k]["ps"]), 4), "max": round(mean(blind[k]["mx"]), 4)}
                      for k in ("H", "D", "A")},
    "gates": {"edge_ok": edge_ok, "vig_ok": vig_ok, "haircut_ok": haircut_ok},
    "verdict": verdict,
}
out_path = REPO / "scripts" / "line_shopping_result.json"
out_path.write_text(json.dumps(result, indent=2))
print(f"\n  Result saved: {out_path}")
