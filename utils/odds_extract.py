from typing import Dict, Tuple, Optional, Any, List
import json
import logging

logger = logging.getLogger(__name__)

OutcomeProbs = Dict[str, float]
OutcomeOdds = Dict[str, float]

PREFERRED_KEYS = [
    ("prices",),
    ("odds", "decimal"),
    ("odds",),
]

def _to_dict(maybe: Any) -> Optional[dict]:
    """Convert various types to dict, handling stringified JSON."""
    if isinstance(maybe, dict):
        return maybe
    if isinstance(maybe, str):
        maybe = maybe.strip()
        if maybe and (maybe[0] in "[{" and maybe[-1] in "]}"):
            try:
                return json.loads(maybe)
            except Exception:
                return None
    return None

def _normalize_from_decimal_odds(o: OutcomeOdds) -> OutcomeProbs:
    """Convert decimal odds to normalized probabilities."""
    inv = {k: (1.0 / v) for k, v in o.items() if v and v > 0}
    s = sum(inv.values()) or 1.0
    return {k: inv.get(k, 0.0) / s for k in ("home", "draw", "away")}

def extract_odds_and_probs(books: Any) -> Tuple[Optional[OutcomeOdds], Optional[OutcomeProbs], Optional[dict]]:
    """
    Extract decimal odds and market probabilities from books data.
    
    Returns: (decimal_odds, market_probs, best_book_obj)
    - decimal_odds: last usable decimal odds found
    - market_probs: normalized probabilities from decimal_odds
    - best_book_obj: the original book dict we used (or None)
    """
    dict_books: List[dict] = []
    if isinstance(books, list):
        for b in books:
            d = _to_dict(b)
            if d:
                dict_books.append(d)
    else:
        d = _to_dict(books)
        if d:
            dict_books = [d]
    
    for book in dict_books:
        for prob_key in ("novig_current", "probabilities", "market_probs"):
            mp = book.get(prob_key)
            if isinstance(mp, dict) and all(k in mp for k in ("home", "draw", "away")):
                return None, {k: float(mp[k]) for k in ("home", "draw", "away")}, book
        
        for path in PREFERRED_KEYS:
            node = book
            ok = True
            for key in path:
                if isinstance(node, dict) and key in node:
                    node = node[key]
                else:
                    ok = False
                    break
            if ok and isinstance(node, dict) and all(k in node for k in ("home", "draw", "away")):
                try:
                    dec = {k: float(node[k]) for k in ("home", "draw", "away")}
                    return dec, _normalize_from_decimal_odds(dec), book
                except (ValueError, TypeError):
                    continue
        
        if all(k in book for k in ("home", "draw", "away")):
            try:
                dec = {k: float(book[k]) for k in ("home", "draw", "away")}
                return dec, _normalize_from_decimal_odds(dec), book
            except Exception:
                pass
    
    return None, None, None
