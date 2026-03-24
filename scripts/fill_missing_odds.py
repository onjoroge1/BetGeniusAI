"""
Fill missing odds for upcoming matches using The Odds API directly.

Run this in production (Replit) where ODDS_API_KEY is set:
  python scripts/fill_missing_odds.py

Or pass the key as an argument:
  python scripts/fill_missing_odds.py <YOUR_ODDS_API_KEY>
"""

import os
import sys
import json
import time
import psycopg2
import requests
from datetime import datetime, timezone

DATABASE_URL = os.environ.get("DATABASE_URL")
ODDS_API_KEY = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("ODDS_API_KEY") or os.environ.get("THE_ODDS_API_KEY")

# League ID → The Odds API sport key mapping
LEAGUE_SPORT_MAP = {
    39: "soccer_epl",
    140: "soccer_spain_la_liga",
    78: "soccer_germany_bundesliga",
    135: "soccer_italy_serie_a",
    61: "soccer_france_ligue_one",
    88: "soccer_netherlands_eredivisie",
    94: "soccer_portugal_primeira_liga",
    2: "soccer_uefa_champs_league",
    3: "soccer_uefa_europa_league",
    71: "soccer_brazil_campeonato",
    45: "soccer_england_league1",
}


def main():
    if not DATABASE_URL:
        print("ERROR: DATABASE_URL not set")
        return
    if not ODDS_API_KEY:
        print("ERROR: ODDS_API_KEY not set. Pass as argument or set env var.")
        print("Usage: python scripts/fill_missing_odds.py <YOUR_API_KEY>")
        return

    print(f"API Key: {ODDS_API_KEY[:8]}...{ODDS_API_KEY[-4:]}")
    print(f"Database: {DATABASE_URL[:50]}...")

    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    # Find upcoming matches without odds_consensus
    cur.execute("""
        SELECT f.match_id, f.home_team, f.away_team, f.kickoff_at, f.league_id
        FROM fixtures f
        LEFT JOIN odds_consensus oc ON f.match_id = oc.match_id
        WHERE f.kickoff_at > NOW()
          AND f.kickoff_at < NOW() + INTERVAL '14 days'
          AND oc.match_id IS NULL
        ORDER BY f.kickoff_at
    """)
    missing = cur.fetchall()
    print(f"\n{len(missing)} upcoming matches without odds")

    if not missing:
        print("All matches have odds!")
        return

    # Group by league
    by_league = {}
    for mid, home, away, ko, lid in missing:
        by_league.setdefault(lid, []).append((mid, home, away, ko))

    print(f"Leagues needing odds: {list(by_league.keys())}")

    filled = 0
    api_calls = 0

    for league_id, matches in by_league.items():
        sport_key = LEAGUE_SPORT_MAP.get(league_id)
        if not sport_key:
            print(f"  League {league_id}: No sport key mapping, skipping {len(matches)} matches")
            continue

        print(f"\n  League {league_id} ({sport_key}): {len(matches)} matches")

        # Fetch all odds for this sport from The Odds API
        url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds"
        params = {
            "apiKey": ODDS_API_KEY,
            "regions": "us,eu,uk,au",
            "markets": "h2h",
            "oddsFormat": "decimal",
            "dateFormat": "iso",
        }

        try:
            resp = requests.get(url, params=params, timeout=15)
            api_calls += 1

            if resp.status_code == 401:
                print(f"    ERROR: Invalid API key (401)")
                return
            if resp.status_code == 429:
                print(f"    ERROR: Rate limited (429)")
                return
            if resp.status_code != 200:
                print(f"    ERROR: HTTP {resp.status_code}")
                continue

            # Show remaining quota
            remaining = resp.headers.get("x-requests-remaining", "?")
            used = resp.headers.get("x-requests-used", "?")
            print(f"    API quota: {used} used, {remaining} remaining")

            events = resp.json()
            print(f"    Got {len(events)} events from API")

            # Match API events to our fixtures
            for mid, home, away, ko in matches:
                best_match = None
                best_score = 0

                for event in events:
                    # Simple fuzzy match on team names
                    eh = event.get("home_team", "").lower()
                    ea = event.get("away_team", "").lower()
                    h_match = _fuzzy_score(home.lower(), eh)
                    a_match = _fuzzy_score(away.lower(), ea)
                    score = (h_match + a_match) / 2

                    if score > best_score and score > 0.6:
                        best_score = score
                        best_match = event

                if not best_match:
                    print(f"    ❌ No match found: {home} vs {away}")
                    continue

                # Extract bookmaker odds and build consensus
                bookmakers = best_match.get("bookmakers", [])
                all_h, all_d, all_a = [], [], []

                for bm in bookmakers:
                    outcomes = {o["name"]: o["price"] for m in bm.get("markets", []) if m["key"] == "h2h" for o in m.get("outcomes", [])}
                    if "Home Team" in outcomes and "Draw" in outcomes and "Away Team" in outcomes:
                        h_odds, d_odds, a_odds = outcomes["Home Team"], outcomes["Draw"], outcomes["Away Team"]
                        total = 1/h_odds + 1/d_odds + 1/a_odds
                        all_h.append(1/h_odds / total)
                        all_d.append(1/d_odds / total)
                        all_a.append(1/a_odds / total)

                        # Also insert into odds_snapshots
                        book_id = f"theodds:{bm['key']}"
                        for outcome, odds_dec, imp_prob in [
                            ("H", h_odds, 1/h_odds), ("D", d_odds, 1/d_odds), ("A", a_odds, 1/a_odds)
                        ]:
                            try:
                                cur.execute("""
                                    INSERT INTO odds_snapshots
                                    (match_id, league_id, book_id, market, ts_snapshot,
                                     secs_to_kickoff, outcome, odds_decimal, implied_prob,
                                     market_margin, created_at)
                                    VALUES (%s, %s, %s, 'h2h', NOW(),
                                            EXTRACT(EPOCH FROM (%s::timestamptz - NOW())),
                                            %s, %s, %s, %s, NOW())
                                    ON CONFLICT (match_id, book_id, market, outcome)
                                    DO UPDATE SET odds_decimal = EXCLUDED.odds_decimal,
                                                  implied_prob = EXCLUDED.implied_prob,
                                                  ts_snapshot = NOW(),
                                                  secs_to_kickoff = EXCLUDED.secs_to_kickoff
                                """, (mid, league_id, book_id, ko, outcome, odds_dec, imp_prob, total - 1))
                            except Exception:
                                conn.rollback()

                if not all_h:
                    print(f"    ❌ No complete odds: {home} vs {away}")
                    continue

                # Build consensus (median)
                import statistics
                ph = statistics.median(all_h)
                pd = statistics.median(all_d)
                pa = statistics.median(all_a)
                n_books = len(all_h)
                disp_h = statistics.stdev(all_h) if len(all_h) > 1 else 0.02
                disp_d = statistics.stdev(all_d) if len(all_d) > 1 else 0.015
                disp_a = statistics.stdev(all_a) if len(all_a) > 1 else 0.02
                margin = ph + pd + pa - 1.0

                # Insert consensus
                try:
                    cur.execute("""
                        INSERT INTO odds_consensus
                        (match_id, horizon_hours, ts_effective, ph_cons, pd_cons, pa_cons,
                         disph, dispd, dispa, n_books, market_margin_avg, created_at, league_id)
                        VALUES (%s,
                                EXTRACT(EPOCH FROM (%s::timestamptz - NOW())) / 3600,
                                NOW(), %s, %s, %s, %s, %s, %s, %s, %s, NOW(), %s)
                        ON CONFLICT (match_id) DO UPDATE SET
                            ph_cons = EXCLUDED.ph_cons, pd_cons = EXCLUDED.pd_cons, pa_cons = EXCLUDED.pa_cons,
                            disph = EXCLUDED.disph, dispd = EXCLUDED.dispd, dispa = EXCLUDED.dispa,
                            n_books = EXCLUDED.n_books, ts_effective = NOW(), created_at = NOW()
                    """, (mid, ko, ph, pd, pa, disp_h, disp_d, disp_a, n_books, margin, league_id))
                    conn.commit()
                    filled += 1
                    print(f"    ✅ {home} vs {away}: H={ph:.2f} D={pd:.2f} A={pa:.2f} ({n_books} books)")
                except Exception as e:
                    conn.rollback()
                    print(f"    ❌ DB error: {e}")

        except requests.exceptions.Timeout:
            print(f"    ERROR: Timeout")
        except Exception as e:
            print(f"    ERROR: {e}")

        time.sleep(1)  # Rate limit courtesy

    print(f"\n{'='*60}")
    print(f"DONE: Filled {filled}/{len(missing)} matches with odds")
    print(f"API calls made: {api_calls}")

    conn.close()


def _fuzzy_score(a: str, b: str) -> float:
    """Simple word overlap fuzzy matching."""
    words_a = set(a.split())
    words_b = set(b.split())
    if not words_a or not words_b:
        return 0.0
    overlap = len(words_a & words_b)
    return overlap / max(len(words_a), len(words_b))


if __name__ == "__main__":
    main()
