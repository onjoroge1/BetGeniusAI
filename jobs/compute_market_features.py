"""
Compute Market Features from Odds Snapshots

Extracts market-derived features for each match:
- Opening odds (earliest snapshot)
- Last odds (latest pre-kick snapshot)
- Probability drift (movement over time)
- Book dispersion (cross-book variance)
- Temporal volatility (variance over time)

All snapshots must be ts_snapshot < kickoff_at (no data leakage).

Author: BetGenius AI Team
Date: Oct 2025
"""

import os
import sys
import psycopg2
import numpy as np
from datetime import datetime
from typing import Dict, List, Tuple

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from models.database import DatabaseManager


def odds_to_prob(odds: float) -> float:
    """Convert decimal odds to implied probability"""
    if odds <= 1.0:
        return 0.0
    return 1.0 / odds


def normalize_probs(ph: float, pd: float, pa: float) -> Tuple[float, float, float]:
    """Normalize probabilities to sum to 1.0"""
    total = ph + pd + pa
    if total < 0.01:
        return 1/3, 1/3, 1/3
    return ph/total, pd/total, pa/total


def compute_market_features_for_match(cursor, match_id: int, kickoff_at) -> Dict:
    """
    Compute all market features for a single match.
    
    Returns dict with opening odds, last odds, drift, dispersion, volatility.
    """
    # Fetch all pre-kick snapshots for this match
    sql = """
        SELECT ts_snapshot, book_id, outcome, odds_decimal
        FROM odds_snapshots
        WHERE match_id = %s
          AND market = 'h2h'
          AND ts_snapshot < %s
        ORDER BY ts_snapshot, book_id, outcome
    """
    
    cursor.execute(sql, (match_id, kickoff_at))
    rows = cursor.fetchall()
    
    if len(rows) < 6:  # Need at least 2 snapshots (H/D/A each)
        return None
    
    # Group by timestamp
    snapshots = {}  # ts -> {book_id -> {H: prob, D: prob, A: prob}}
    all_timestamps = set()
    
    for ts, book_id, outcome, odds in rows:
        if ts not in snapshots:
            snapshots[ts] = {}
        if book_id not in snapshots[ts]:
            snapshots[ts][book_id] = {}
        
        prob = odds_to_prob(float(odds))
        snapshots[ts][book_id][outcome] = prob
        all_timestamps.add(ts)
    
    if len(all_timestamps) < 2:
        return None
    
    sorted_times = sorted(all_timestamps)
    ts_open = sorted_times[0]
    ts_last = sorted_times[-1]
    
    # === Opening Consensus ===
    open_books = snapshots[ts_open]
    open_probs = {'H': [], 'D': [], 'A': []}
    for book_data in open_books.values():
        if 'H' in book_data and 'D' in book_data and 'A' in book_data:
            ph, pd, pa = normalize_probs(book_data['H'], book_data['D'], book_data['A'])
            open_probs['H'].append(ph)
            open_probs['D'].append(pd)
            open_probs['A'].append(pa)
    
    if len(open_probs['H']) == 0:
        return None
    
    p_open_home = float(np.mean(open_probs['H']))
    p_open_draw = float(np.mean(open_probs['D']))
    p_open_away = float(np.mean(open_probs['A']))
    
    # === Last/Closing Consensus ===
    last_books = snapshots[ts_last]
    last_probs = {'H': [], 'D': [], 'A': []}
    for book_data in last_books.values():
        if 'H' in book_data and 'D' in book_data and 'A' in book_data:
            ph, pd, pa = normalize_probs(book_data['H'], book_data['D'], book_data['A'])
            last_probs['H'].append(ph)
            last_probs['D'].append(pd)
            last_probs['A'].append(pa)
    
    if len(last_probs['H']) == 0:
        return None
    
    p_last_home = float(np.mean(last_probs['H']))
    p_last_draw = float(np.mean(last_probs['D']))
    p_last_away = float(np.mean(last_probs['A']))
    
    # === Drift (market movement) ===
    drift_home = p_last_home - p_open_home
    drift_draw = p_last_draw - p_open_draw
    drift_away = p_last_away - p_open_away
    drift_magnitude = float(np.sqrt(drift_home**2 + drift_draw**2 + drift_away**2))
    
    # === Dispersion (cross-book variance at last snapshot) ===
    dispersion_home = float(np.std(last_probs['H'])) if len(last_probs['H']) > 1 else 0.0
    dispersion_draw = float(np.std(last_probs['D'])) if len(last_probs['D']) > 1 else 0.0
    dispersion_away = float(np.std(last_probs['A'])) if len(last_probs['A']) > 1 else 0.0
    book_dispersion = float(np.mean([dispersion_home, dispersion_draw, dispersion_away]))
    
    # === Volatility (temporal variance across all snapshots) ===
    time_series = {'H': [], 'D': [], 'A': []}
    for ts in sorted_times:
        books = snapshots[ts]
        probs = {'H': [], 'D': [], 'A': []}
        for book_data in books.values():
            if 'H' in book_data and 'D' in book_data and 'A' in book_data:
                ph, pd, pa = normalize_probs(book_data['H'], book_data['D'], book_data['A'])
                probs['H'].append(ph)
                probs['D'].append(pd)
                probs['A'].append(pa)
        
        if len(probs['H']) > 0:
            time_series['H'].append(np.mean(probs['H']))
            time_series['D'].append(np.mean(probs['D']))
            time_series['A'].append(np.mean(probs['A']))
    
    volatility_home = float(np.std(time_series['H'])) if len(time_series['H']) > 1 else 0.0
    volatility_draw = float(np.std(time_series['D'])) if len(time_series['D']) > 1 else 0.0
    volatility_away = float(np.std(time_series['A'])) if len(time_series['A']) > 1 else 0.0
    
    # === Coverage metrics ===
    coverage_hours = (ts_last - ts_open).total_seconds() / 3600.0
    num_unique_snapshots = len(sorted_times)  # Count distinct timestamps, not rows
    
    return {
        'match_id': match_id,
        'p_open_home': p_open_home,
        'p_open_draw': p_open_draw,
        'p_open_away': p_open_away,
        'ts_open': ts_open,
        'p_last_home': p_last_home,
        'p_last_draw': p_last_draw,
        'p_last_away': p_last_away,
        'ts_last': ts_last,
        'prob_drift_home': drift_home,
        'prob_drift_draw': drift_draw,
        'prob_drift_away': drift_away,
        'drift_magnitude': drift_magnitude,
        'book_dispersion': book_dispersion,
        'dispersion_home': dispersion_home,
        'dispersion_draw': dispersion_draw,
        'dispersion_away': dispersion_away,
        'volatility_home': volatility_home,
        'volatility_draw': volatility_draw,
        'volatility_away': volatility_away,
        'num_books_open': len(open_books),
        'num_books_last': len(last_books),
        'num_snapshots': num_unique_snapshots,
        'coverage_hours': coverage_hours
    }


def run_computation(match_ids: List[int] = None, force_recompute: bool = False):
    """
    Compute market features for all matches (or specific match_ids).
    
    Args:
        match_ids: Optional list of match IDs to process. If None, processes all.
        force_recompute: If True, recompute even if features already exist.
    """
    print("=" * 70)
    print("MARKET FEATURES COMPUTATION")
    print("=" * 70)
    
    db_manager = DatabaseManager()
    conn = psycopg2.connect(db_manager.database_url)
    cursor = conn.cursor()
    
    # Get matches to process
    if match_ids:
        sql = """
            SELECT f.match_id, f.kickoff_at
            FROM fixtures f
            WHERE f.match_id = ANY(%s)
              AND f.kickoff_at IS NOT NULL
            ORDER BY f.kickoff_at
        """
        cursor.execute(sql, (match_ids,))
    else:
        sql = """
            SELECT f.match_id, f.kickoff_at
            FROM fixtures f
            LEFT JOIN market_features mf ON f.match_id = mf.match_id
            WHERE f.kickoff_at IS NOT NULL
              AND (mf.match_id IS NULL OR %s = TRUE)
            ORDER BY f.kickoff_at
        """
        cursor.execute(sql, (force_recompute,))
    
    matches = cursor.fetchall()
    print(f"📊 Processing {len(matches)} matches...")
    
    if len(matches) == 0:
        print("✅ No matches to process (all up-to-date)")
        cursor.close()
        conn.close()
        return
    
    # Process each match
    success_count = 0
    skip_count = 0
    error_count = 0
    
    for i, (match_id, kickoff_at) in enumerate(matches, 1):
        try:
            features = compute_market_features_for_match(cursor, match_id, kickoff_at)
            
            if features is None:
                skip_count += 1
                if i % 50 == 0:
                    print(f"   Progress: {i}/{len(matches)} ({skip_count} skipped, insufficient data)")
                continue
            
            # Upsert into market_features
            upsert_sql = """
                INSERT INTO market_features (
                    match_id, p_open_home, p_open_draw, p_open_away, ts_open,
                    p_last_home, p_last_draw, p_last_away, ts_last,
                    prob_drift_home, prob_drift_draw, prob_drift_away, drift_magnitude,
                    book_dispersion, dispersion_home, dispersion_draw, dispersion_away,
                    volatility_home, volatility_draw, volatility_away,
                    num_books_open, num_books_last, num_snapshots, coverage_hours
                ) VALUES (
                    %(match_id)s, %(p_open_home)s, %(p_open_draw)s, %(p_open_away)s, %(ts_open)s,
                    %(p_last_home)s, %(p_last_draw)s, %(p_last_away)s, %(ts_last)s,
                    %(prob_drift_home)s, %(prob_drift_draw)s, %(prob_drift_away)s, %(drift_magnitude)s,
                    %(book_dispersion)s, %(dispersion_home)s, %(dispersion_draw)s, %(dispersion_away)s,
                    %(volatility_home)s, %(volatility_draw)s, %(volatility_away)s,
                    %(num_books_open)s, %(num_books_last)s, %(num_snapshots)s, %(coverage_hours)s
                )
                ON CONFLICT (match_id) DO UPDATE SET
                    p_open_home = EXCLUDED.p_open_home,
                    p_open_draw = EXCLUDED.p_open_draw,
                    p_open_away = EXCLUDED.p_open_away,
                    ts_open = EXCLUDED.ts_open,
                    p_last_home = EXCLUDED.p_last_home,
                    p_last_draw = EXCLUDED.p_last_draw,
                    p_last_away = EXCLUDED.p_last_away,
                    ts_last = EXCLUDED.ts_last,
                    prob_drift_home = EXCLUDED.prob_drift_home,
                    prob_drift_draw = EXCLUDED.prob_drift_draw,
                    prob_drift_away = EXCLUDED.prob_drift_away,
                    drift_magnitude = EXCLUDED.drift_magnitude,
                    book_dispersion = EXCLUDED.book_dispersion,
                    dispersion_home = EXCLUDED.dispersion_home,
                    dispersion_draw = EXCLUDED.dispersion_draw,
                    dispersion_away = EXCLUDED.dispersion_away,
                    volatility_home = EXCLUDED.volatility_home,
                    volatility_draw = EXCLUDED.volatility_draw,
                    volatility_away = EXCLUDED.volatility_away,
                    num_books_open = EXCLUDED.num_books_open,
                    num_books_last = EXCLUDED.num_books_last,
                    num_snapshots = EXCLUDED.num_snapshots,
                    coverage_hours = EXCLUDED.coverage_hours,
                    computed_at = NOW()
            """
            
            cursor.execute(upsert_sql, features)
            conn.commit()
            success_count += 1
            
            if i % 50 == 0:
                print(f"   Progress: {i}/{len(matches)} ({success_count} success, {skip_count} skipped)")
        
        except Exception as e:
            error_count += 1
            print(f"   ❌ Error processing match {match_id}: {e}")
            conn.rollback()
    
    print("\n" + "=" * 70)
    print(f"✅ COMPLETE: {success_count} features computed, {skip_count} skipped, {error_count} errors")
    print("=" * 70)
    
    # Coverage stats
    cursor.execute("""
        SELECT COUNT(*) as total,
               AVG(coverage_hours) as avg_coverage,
               AVG(num_books_last) as avg_books,
               AVG(drift_magnitude) as avg_drift
        FROM market_features
    """)
    stats = cursor.fetchone()
    if stats[0] > 0:
        print(f"\n📊 Market Features Stats:")
        print(f"   Total matches: {stats[0]}")
        print(f"   Avg coverage: {stats[1]:.1f} hours")
        print(f"   Avg books: {stats[2]:.1f}")
        print(f"   Avg drift: {stats[3]:.4f}")
    
    cursor.close()
    conn.close()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Compute market features from odds snapshots')
    parser.add_argument('--match-ids', type=int, nargs='+', help='Specific match IDs to process')
    parser.add_argument('--force', action='store_true', help='Recompute even if features exist')
    
    args = parser.parse_args()
    
    run_computation(match_ids=args.match_ids, force_recompute=args.force)
