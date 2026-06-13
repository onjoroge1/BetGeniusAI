"""
Edge Engine — the strategic pivot from accuracy to value (2026-06-12).

Core idea: a prediction's worth isn't "how often is it right" (accuracy) but
"does the price overpay you for the risk" (edge/EV). This module computes:

  - De-vigged market probabilities (the fair market line)
  - Per-outcome edge:  p_model - p_market_fair
  - EV at the best available price:  p_model * best_odds - 1
  - Value rating tiers + nullable value_bet ("no bet" is a first-class answer)
  - min_acceptable_odds (the price floor below which the edge is gone)
  - Kelly staking (full + quarter)
  - Parlay edge compounding (only +EV legs; one -EV leg poisons multiplicatively)

Design: pure-math core (fully unit-testable, no I/O) + thin DB wrappers that
read odds_consensus (market line, RAW implied probs incl. vig — must de-vig)
and odds_snapshots (per-book h2h prices → best price per outcome).

Validated context (scripts/line_shopping_result.json, n=26,556):
  - Betting Pinnacle-close favorites loses the vig (-2.15%); best price across
    books recovers ~2.1pp (→ ~breakeven). Line-shopping ERASES vig, it does not
    create profit alone — it's the multiplier on model edge, hence min odds +
    best price are first-class fields here.

Honesty registry: model_track_record reports which models have DEMONSTRATED
edge on a temporal holdout. v3_sharp has not (45.3% vs favorite 50.9%);
wc_elo has (61.2% vs 45.9%). CLV stats populate once the closing-odds loop
is wired (closing_odds/clv_realized tables).
"""

import os
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Outcome sets. Soccer/3-way is the default everywhere for back-compat;
# US sports (NBA/NHL/MLB/NFL moneyline) pass OUTCOMES_2WAY — no draw key, ever.
OUTCOMES_3WAY = ("home", "draw", "away")
OUTCOMES_2WAY = ("home", "away")
OUTCOMES = OUTCOMES_3WAY  # legacy alias

# EV-at-best-price tiers. Tunable; documented in docs/FRONTEND_EDGE_MANUAL.md.
RATING_TIERS = (
    (0.08, "strong_value"),
    (0.03, "value"),
    (0.0, "marginal"),
)

_CANONICAL_BET = {
    "home": "home_win", "draw": "draw", "away": "away_win",
    "over": "over", "under": "under", "yes": "yes",  # prop markets
}


# ── Pure math core ─────────────────────────────────────────────────────────────

def devig_proportional(raw_probs: Dict[str, float],
                       outcomes: tuple = OUTCOMES_3WAY) -> Dict[str, float]:
    """
    Remove the bookmaker margin from raw implied probabilities (which sum to
    1 + vig) by proportional normalization. Returns fair probs summing to 1.
    """
    total = sum(raw_probs.get(k, 0.0) or 0.0 for k in outcomes)
    if total <= 0:
        raise ValueError("raw probabilities must be positive")
    return {k: (raw_probs.get(k, 0.0) or 0.0) / total for k in outcomes}


def implied_probs_from_odds(odds: Dict[str, float],
                            outcomes: tuple = OUTCOMES_3WAY) -> Dict[str, float]:
    """Decimal odds -> raw implied probabilities (vig included)."""
    out = {}
    for k in outcomes:
        o = odds.get(k)
        if not o or o <= 1.0:
            raise ValueError(f"invalid decimal odds for {k}: {o}")
        out[k] = 1.0 / o
    return out


def compute_edge(model_probs: Dict[str, float], market_fair: Dict[str, float],
                 outcomes: tuple = OUTCOMES_3WAY) -> Dict[str, float]:
    """Per-outcome edge in probability points: p_model - p_market_fair."""
    return {k: round(model_probs[k] - market_fair[k], 4) for k in outcomes}


def ev_at_price(p: float, decimal_odds: float) -> float:
    """Expected value of a 1-unit bet: p*odds - 1."""
    return p * decimal_odds - 1.0


def min_acceptable_odds(p: float) -> float:
    """Break-even price for model probability p. Below this, the edge is gone."""
    if p <= 0:
        return float("inf")
    return round(1.0 / p, 3)


def kelly_fraction(p: float, decimal_odds: float) -> float:
    """
    Full-Kelly stake fraction for a binary bet at decimal odds.
    f* = (p*odds - 1) / (odds - 1). Returns 0 when there's no edge.
    """
    if decimal_odds <= 1.0:
        return 0.0
    f = (p * decimal_odds - 1.0) / (decimal_odds - 1.0)
    return max(0.0, round(f, 4))


def value_rating(ev: Optional[float]) -> str:
    """Map EV at best price to a display tier. <=0 → no_value."""
    if ev is None or ev <= 0:
        return "no_value"
    for threshold, name in RATING_TIERS:
        if ev >= threshold:
            return name
    return "no_value"


def select_value_bet(model_probs: Dict[str, float],
                     best_prices: Dict[str, dict],
                     outcomes: tuple = OUTCOMES_3WAY) -> Optional[dict]:
    """
    Pick the outcome with the highest positive EV at its best available price.
    Returns None when nothing clears EV > 0 — "no bet" is the honest default.

    best_prices: {"home": {"odds": 2.10, "book": "bet365"}, ...} (entries optional)
    """
    best = None
    for k in outcomes:
        entry = best_prices.get(k) or {}
        odds = entry.get("odds")
        if not odds or odds <= 1.0:
            continue
        ev = ev_at_price(model_probs[k], odds)
        if ev > 0 and (best is None or ev > best["ev"]):
            kf = kelly_fraction(model_probs[k], odds)  # compute once, derive quarter
            best = {
                "outcome": k,
                "bet": _CANONICAL_BET[k],
                "ev": round(ev, 4),
                "price": odds,
                "book": entry.get("book"),
                "min_acceptable_odds": min_acceptable_odds(model_probs[k]),
                "kelly_full": kf,
                "kelly_quarter": round(kf / 4.0, 4),
            }
    return best


def parlay_metrics(legs: List[dict], joint_prob: Optional[float] = None) -> dict:
    """
    Edge math for a parlay. legs: [{"p": model_prob, "odds": offered_decimal}, ...]

    Cross-match legs are treated as independent (fair prob = product). For
    same-game parlays pass joint_prob (correlation-adjusted) to override.

    Rule enforced: a parlay is only "eligible" when EVERY leg has positive EV —
    edges compound multiplicatively, and so does a single negative leg.
    """
    if not legs:
        raise ValueError("parlay needs at least one leg")
    leg_evs = []
    prob_product = 1.0
    odds_product = 1.0
    for leg in legs:
        p, o = leg["p"], leg["odds"]
        if not (0.0 < p < 1.0) or o <= 1.0:
            raise ValueError(f"invalid leg: p={p}, odds={o}")
        leg_evs.append(round(ev_at_price(p, o), 4))
        prob_product *= p
        odds_product *= o

    fair_prob = joint_prob if joint_prob is not None else prob_product
    ev = fair_prob * odds_product - 1.0
    eligible = all(e > 0 for e in leg_evs)
    return {
        "n_legs": len(legs),
        "leg_evs": leg_evs,
        "fair_prob": round(fair_prob, 4),
        "combined_odds": round(odds_product, 3),
        "fair_odds": round(1.0 / fair_prob, 3) if fair_prob > 0 else None,
        "ev": round(ev, 4),
        "eligible": eligible,  # False if any leg is -EV (poison-leg rule)
        "kelly_quarter": round(kelly_fraction(fair_prob, odds_product) / 4.0, 4) if eligible else 0.0,
        "rating": value_rating(ev if eligible else None),
    }


def prop_value(p_model: float, offers: List[dict], side: str = "over") -> Optional[dict]:
    """
    Value math for a player-prop market (points O/U, anytime scorer, etc.).

    offers: [{"book": str, "line": float|None, "side": "over"/"under"/"yes",
              "odds": float}, ...]  — every offer collected for this prop.
    p_model: the model's probability for `side` AT THE MODAL LINE (v1 rule:
             we only make EV claims at the most-common line across books;
             offers at other lines are listed as alt_lines with no EV claim,
             because p_model doesn't transfer across lines).
    side:    "over"/"yes" (or "under") — which side the model probability is for.

    De-vig: only possible when the SAME book quotes both sides at the modal
    line (a real O/U pair). Yes-only markets (anytime scorer) get no fair-prob
    or edge field — EV at price needs no de-vig and is what value_bet runs on.

    Returns None when there are no offers for `side` (no fake value claims).
    """
    if not (0.0 < p_model < 1.0):
        raise ValueError(f"invalid model probability: {p_model}")

    side_offers = [o for o in offers
                   if o.get("side") == side and (o.get("odds") or 0) > 1.0]
    if not side_offers:
        return None

    # Modal line: most common line among this side's offers (None groups together)
    line_counts: Dict[Optional[float], int] = {}
    for o in side_offers:
        line_counts[o.get("line")] = line_counts.get(o.get("line"), 0) + 1
    modal_line = max(line_counts, key=lambda l: line_counts[l])

    at_line = [o for o in side_offers if o.get("line") == modal_line]
    best = max(at_line, key=lambda o: o["odds"])
    ev = ev_at_price(p_model, best["odds"])
    kf = kelly_fraction(p_model, best["odds"])

    # Fair prob via de-vig when any book quotes BOTH sides at the modal line
    opposite = "under" if side in ("over", "yes") else "over"
    fair_p = None
    for o in at_line:
        pair = next((u for u in offers
                     if u.get("book") == o.get("book") and u.get("side") == opposite
                     and u.get("line") == modal_line and (u.get("odds") or 0) > 1.0), None)
        if pair:
            raw = {"a": 1.0 / o["odds"], "b": 1.0 / pair["odds"]}
            fair_p = raw["a"] / (raw["a"] + raw["b"])
            break

    alt_lines = sorted(
        ({"line": l, "best_odds": max(o["odds"] for o in side_offers if o.get("line") == l),
          "n_books": sum(1 for o in side_offers if o.get("line") == l)}
         for l in line_counts if l != modal_line),
        key=lambda d: (d["line"] is None, d["line"]),
    )

    return {
        "side": side,
        "modal_line": modal_line,
        "n_offers": len(side_offers),
        "n_books": len({o.get("book") for o in at_line}),
        "best_price": {"odds": round(best["odds"], 3), "book": best.get("book"),
                       "line": modal_line},
        "ev_at_best": round(ev, 4),
        "rating": value_rating(ev),
        "min_acceptable_odds": min_acceptable_odds(p_model),
        "kelly_full": kf,
        "kelly_quarter": round(kf / 4.0, 4),
        "market_implied_fair": round(fair_p, 4) if fair_p is not None else None,
        "edge": round(p_model - fair_p, 4) if fair_p is not None else None,
        "alt_lines": alt_lines or None,  # listed, never EV-claimed (v1 modal-line rule)
    }


def build_value_payload(model_probs: Dict[str, float],
                        market_raw_probs: Optional[Dict[str, float]] = None,
                        best_prices: Optional[Dict[str, dict]] = None,
                        n_books: Optional[int] = None,
                        outcomes: tuple = OUTCOMES_3WAY) -> dict:
    """
    Pure assembly of the `market` + `value` response blocks from already-fetched
    inputs. Fully testable without a DB. Any missing input degrades gracefully
    to nullable fields (the frontend contract allows it).
    Pass outcomes=OUTCOMES_2WAY for US sports — the payload then carries no
    draw key anywhere (frontend contract, FRONTEND_EDGE_QA §1).
    """
    market_block = None
    value_block = None

    fair = None
    if market_raw_probs:
        try:
            fair = devig_proportional(market_raw_probs, outcomes)
            overround = sum(market_raw_probs.get(k, 0.0) or 0.0 for k in outcomes)
            market_block = {
                "implied": {k: round(fair[k], 4) for k in outcomes},
                "overround": round(overround, 4),
                "n_books": n_books,
                "best_price": best_prices or None,
            }
        except ValueError:
            fair = None

    if fair:
        edge = compute_edge(model_probs, fair, outcomes)
        ev_best = {}
        if best_prices:
            for k in outcomes:
                entry = best_prices.get(k) or {}
                odds = entry.get("odds")
                ev_best[k] = round(ev_at_price(model_probs[k], odds), 4) if odds and odds > 1.0 else None
        vb = select_value_bet(model_probs, best_prices, outcomes) if best_prices else None
        top_ev = vb["ev"] if vb else (max((e for e in ev_best.values() if e is not None), default=None))
        value_block = {
            "edge": edge,
            "ev_at_best": ev_best or None,
            "value_bet": vb,
            "rating": value_rating(top_ev),
            "min_acceptable_odds": {k: min_acceptable_odds(model_probs[k]) for k in outcomes},
        }

    clv_block = {
        "bet_time_odds": (value_block or {}).get("value_bet", {}).get("price") if value_block and value_block.get("value_bet") else None,
        "closing_odds": None,      # filled by the closing sampler at kickoff
        "realized_clv": None,      # filled at settlement: bet_odds/closing_odds - 1
    }
    return {"market": market_block, "value": value_block, "clv": clv_block}


# ── Honesty registry: which models have demonstrated edge ─────────────────────

MODEL_REGISTRY = {
    # wc_elo: temporal holdout 61.2% vs majority baseline 45.9% (+15.3pp) —
    # artifacts/models/wc_model/metadata.json. Thin-market segment.
    "wc_elo": {"segment": "thin_market", "edge_validated": True,
               "validation": "temporal holdout +15.3pp vs baseline (n=765)"},
    # v3_sharp: temporal holdout 45.3% vs favorite 50.9% — FAILED.
    # scripts/temporal_holdout_result.json. Serves calibrated probs only.
    "v3_sharp": {"segment": "efficient_market", "edge_validated": False,
                 "validation": "temporal holdout 45.3% vs favorite 50.9% — no edge"},
    "v1_consensus": {"segment": "efficient_market", "edge_validated": False,
                     "validation": "is the market line (de-vigged consensus)"},
    "v0_form": {"segment": "efficient_market", "edge_validated": False,
                "validation": "ELO fallback, not holdout-validated for clubs"},
    # Multisport V3 (per sport): OOF-validated only — never tested against the
    # consensus-favorite baseline (the same trap soccer v3_sharp fell into).
    # Flip edge_validated ONLY after a per-sport temporal holdout passes
    # (docs/MULTISPORT_EDGE_PLAN.md, Gate B). NBA/MLB mainlines are the most
    # efficient markets in existence — expect these to stay false.
    "v3_multisport_basketball": {"segment": "efficient_market", "edge_validated": False,
                                 "validation": "OOF-only; no favorite-baseline holdout"},
    "v3_multisport_hockey": {"segment": "efficient_market", "edge_validated": False,
                             "validation": "OOF-only; no favorite-baseline holdout"},
    "v3_multisport_baseball": {"segment": "efficient_market", "edge_validated": False,
                               "validation": "OOF-only; no favorite-baseline holdout"},
    "v3_multisport_football": {"segment": "efficient_market", "edge_validated": False,
                               "validation": "OOF-only; no favorite-baseline holdout"},
    # Player props: AUC 0.72 OOF for soccer involvement models; never validated
    # against prop prices. Props are the thin/soft segment — validate then flip.
    "player_props_soccer": {"segment": "thin_market", "edge_validated": False,
                            "validation": "AUC-only; no price holdout yet"},
}

# sport_key prefix → registry id (multisport routes pass e.g. 'basketball_nba')
_SPORT_PREFIX_MODEL = {
    "basketball": "v3_multisport_basketball",
    "icehockey": "v3_multisport_hockey",
    "baseball": "v3_multisport_baseball",
    "americanfootball": "v3_multisport_football",
}


def multisport_model_id(sport_key: str) -> str:
    """Map a The-Odds-API sport_key ('basketball_nba') to its registry model id."""
    prefix = (sport_key or "").split("_", 1)[0]
    return _SPORT_PREFIX_MODEL.get(prefix, "v3_multisport_basketball")


def get_model_track_record(model_id: str) -> dict:
    """
    Per-model honesty block for the payload. median_clv_90d / n_settled stay
    null until the closing-odds loop (closing_odds, clv_realized) is wired.
    """
    reg = MODEL_REGISTRY.get(model_id) or {"segment": "unknown", "edge_validated": False,
                                           "validation": "not validated"}
    return {
        "model": model_id,
        "segment": reg["segment"],
        "edge_validated": reg["edge_validated"],
        "validation": reg["validation"],
        "median_clv_90d": None,
        "n_settled": None,
    }


# ── DB wrappers (thin; the math above stays pure) ─────────────────────────────

def fetch_market_context(match_id: int, db_url: Optional[str] = None):
    """
    Read the market line + best prices for a match.
      market line : latest odds_consensus row (ph/pd/pa are RAW implied, vig in)
      best price  : odds_snapshots h2h — latest snapshot per book per outcome,
                    then max odds across books (book_id reported)
    Returns (market_raw_probs|None, best_prices|None, n_books|None).
    """
    import psycopg2
    db_url = db_url or os.getenv("DATABASE_URL")
    if not db_url:
        return None, None, None

    market_raw = None
    best_prices = None
    n_books = None
    try:
        with psycopg2.connect(db_url, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT ph_cons, pd_cons, pa_cons, n_books
                    FROM odds_consensus
                    WHERE match_id = %s AND ph_cons IS NOT NULL
                    ORDER BY ts_effective DESC LIMIT 1
                """, (match_id,))
                row = cur.fetchone()
                if row:
                    market_raw = {"home": float(row[0]), "draw": float(row[1]), "away": float(row[2])}
                    n_books = row[3]

                # Best price per outcome from the latest snapshot of each book
                cur.execute("""
                    SELECT outcome, odds_decimal, book_id
                    FROM (
                        SELECT outcome, odds_decimal, book_id,
                               ROW_NUMBER() OVER (PARTITION BY book_id, outcome
                                                  ORDER BY ts_snapshot DESC) AS rn
                        FROM odds_snapshots
                        WHERE match_id = %s AND market = 'h2h'
                          AND odds_decimal > 1.0
                    ) t WHERE rn = 1
                """, (match_id,))
                latest = cur.fetchall()
                if latest:
                    key_map = {"H": "home", "D": "draw", "A": "away"}
                    bp = {}
                    for outcome, odds, book_id in latest:
                        k = key_map.get(outcome)
                        if not k:
                            continue
                        o = float(odds)
                        if k not in bp or o > bp[k]["odds"]:
                            bp[k] = {"odds": round(o, 3), "book": str(book_id)}
                    if bp:
                        best_prices = bp
    except Exception as e:
        logger.warning(f"fetch_market_context failed for match {match_id}: {e}")

    return market_raw, best_prices, n_books


def build_edge_blocks(match_id: int, model_probs: Dict[str, float],
                      db_url: Optional[str] = None) -> dict:
    """
    One-call helper for endpoint handlers: fetch market context and assemble
    the market/value/clv blocks. Never raises — degrades to nullable blocks.
    """
    try:
        market_raw, best_prices, n_books = fetch_market_context(match_id, db_url)
        return build_value_payload(model_probs, market_raw, best_prices, n_books)
    except Exception as e:
        logger.warning(f"build_edge_blocks failed for match {match_id}: {e}")
        return {"market": None, "value": None,
                "clv": {"bet_time_odds": None, "closing_odds": None, "realized_clv": None}}


def compute_realized_clv(bet_time_odds: float, closing_odds: float) -> float:
    """
    Closing-line value of a placed bet: positive means you beat the close.
    Called at settlement time once closing_odds is captured.
    """
    if not bet_time_odds or not closing_odds or closing_odds <= 1.0:
        raise ValueError("need valid bet-time and closing odds")
    return round(bet_time_odds / closing_odds - 1.0, 4)
