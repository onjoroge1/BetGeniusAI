# /market API Analysis

## Question 1: Is `novig_current` the consensus odds?

**YES!** `novig_current` is the **no-vig consensus odds** calculated from all available bookmakers.

### How it works:
1. **Fetches all bookmaker odds** for a match from `odds_snapshots` table
2. **Converts to implied probabilities**: For each bookmaker's odds (e.g., 2.50 → 1/2.50 = 0.40)
3. **Removes the vig (overround)**: Normalizes probabilities to sum to 1.0
4. **Averages across all bookmakers**: Takes mean of no-vig probabilities
5. **Returns consensus**: Final probabilities representing the "true" market view

### Example from API response:
```json
"novig_current": {
  "home": 0.374,   // 37.4% home win probability
  "draw": 0.31,    // 31.0% draw probability  
  "away": 0.317    // 31.7% away win probability
}
```

This is calculated from 38 bookmakers in the example (see `calculate_novig_consensus()` function in `main.py` line 5923).

---

## Question 2: Are the `apif` items under `odds>books` the bookmakers?

**YES!** The items under `odds.books` are all bookmakers, with two formats:

### Format 1: API-Football bookmakers (with `apif:` prefix)
```json
"apif:1": {"home": 2.52, "draw": 3.15, "away": 2.88},  // 10bet
"apif:8": {"home": 2.55, "draw": 3.1, "away": 3.0},    // Bet365
"apif:11": {"home": 2.64, "draw": 3.17, "away": 3.11}  // 1xbet
```

### Format 2: The Odds API bookmakers (numeric IDs)
```json
"118": {"home": 2.35, "draw": 2.93, "away": 2.83},
"124": {"home": 2.4, "draw": 2.9, "away": 2.8},
"154": {"home": 2.53, "draw": 3.1, "away": 3.2}
```

**Both formats represent real bookmaker odds** collected from two different data sources.

---

## Question 3: Can we add bookmaker names instead of IDs?

**YES - PARTIALLY POSSIBLE!** We have name mappings for API-Football bookmakers but NOT for The Odds API bookmakers.

### Current mapping situation:

| Book ID Format | Name Available? | Example Mapping |
|---------------|----------------|-----------------|
| `apif:1` | ✅ YES | 10bet |
| `apif:8` | ✅ YES | Bet365 |
| `apif:11` | ✅ YES | 1xbet |
| `118` (TheOdds) | ❌ NO | Unknown |
| `124` (TheOdds) | ❌ NO | Unknown |

### Why the gap?
- `bookmaker_xwalk` table has mappings for `api_football_book_id` (works!)
- `theodds_book_id` column is **empty** (no mappings available)

### Solution: Add names for API-Football books only

We can modify the `/market` API to include names for the `apif:` prefixed bookmakers:

```python
# In /market endpoint, after fetching odds:
books_with_names = {}
for book_id, odds in books.items():
    if book_id.startswith('apif:'):
        # Look up name from bookmaker_xwalk
        name = get_bookmaker_name(book_id)  # e.g., "10bet", "Bet365"
    else:
        name = book_id  # Keep numeric ID as-is
    
    books_with_names[name] = odds
```

**Recommendation**: If you want full bookmaker names, we need to:
1. Populate `theodds_book_id` column in `bookmaker_xwalk` with The Odds API mappings
2. Then modify the API to look up names for both sources

Would you like me to implement the partial solution (names for API-Football books only)?

---

## Summary

✅ **novig_current** = No-vig consensus calculated from all bookmakers (market truth)  
✅ **odds.books** = Individual bookmaker odds (both API-Football and The Odds API)  
⚠️ **Names** = Possible for API-Football (`apif:*`), missing for The Odds API (numeric IDs)
