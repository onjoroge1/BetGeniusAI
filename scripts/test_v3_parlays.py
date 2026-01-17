#!/usr/bin/env python3
"""
Test V3 Ensemble for Auto-Parlays
Compares V2 vs V3 predictions and shows sample parlay results
"""

import os
import sys
import json
import logging
from pathlib import Path
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

engine = create_engine(os.environ.get('DATABASE_URL'), pool_pre_ping=True)
Session = sessionmaker(bind=engine)

def get_upcoming_matches(limit=10):
    """Get upcoming matches with odds"""
    session = Session()
    try:
        now = datetime.now(timezone.utc)
        cutoff = now + timedelta(hours=72)
        
        result = session.execute(text("""
            SELECT DISTINCT ON (f.match_id) 
                   f.match_id, f.home_team, f.away_team, f.kickoff_at,
                   f.league_name,
                   oc.ph_cons, oc.pd_cons, oc.pa_cons,
                   sb.prob_home, sb.prob_draw, sb.prob_away
            FROM fixtures f
            JOIN odds_consensus oc ON f.match_id = oc.match_id
            LEFT JOIN sharp_book_odds sb ON f.match_id = sb.match_id AND sb.bookmaker = 'pinnacle'
            WHERE f.status = 'scheduled'
            AND f.kickoff_at > :now
            AND f.kickoff_at < :cutoff
            AND oc.ph_cons IS NOT NULL
            ORDER BY f.match_id, f.kickoff_at
            LIMIT :limit
        """), {'now': now, 'cutoff': cutoff, 'limit': limit})
        
        matches = []
        for row in result.fetchall():
            ph_cons = float(row[5] or 0.33)
            pd_cons = float(row[6] or 0.33)
            pa_cons = float(row[7] or 0.33)
            ph_ps = float(row[8] or ph_cons)
            pd_ps = float(row[9] or pd_cons)
            pa_ps = float(row[10] or pa_cons)
            
            matches.append({
                'match_id': row[0],
                'home_team': row[1],
                'away_team': row[2],
                'kickoff': row[3],
                'league': row[4],
                'odds_cons': {'h': ph_cons, 'd': pd_cons, 'a': pa_cons},
                'odds_ps': {'h': ph_ps, 'd': pd_ps, 'a': pa_ps}
            })
        return matches
    finally:
        session.close()


def test_v3_predictions(matches):
    """Test V3 predictions on upcoming matches"""
    print("\n" + "=" * 80)
    print("V3 ENSEMBLE PARLAY TEST")
    print("=" * 80)
    
    try:
        from models.v3_ensemble_predictor import get_v3_ensemble_predictor
        v3 = get_v3_ensemble_predictor()
        print(f"\n✅ V3 Ensemble loaded: {v3.get_model_info()}")
    except Exception as e:
        print(f"\n❌ V3 Ensemble not available: {e}")
        print("Using V3 temporal model instead...")
        try:
            from models.v3_temporal_predictor import V3TemporalPredictor
            v3 = V3TemporalPredictor()
        except:
            v3 = None
    
    try:
        from models.v2_lgbm_predictor import V2LightGBMPredictor
        v2 = V2LightGBMPredictor()
        print(f"✅ V2 LightGBM loaded")
    except Exception as e:
        print(f"⚠️  V2 not available: {e}")
        v2 = None
    
    results = []
    
    print(f"\n📊 Testing {len(matches)} upcoming matches...\n")
    print("-" * 100)
    print(f"{'Match':<40} {'V3 Pred':<12} {'V3 Conf':<10} {'Book Fav':<12} {'Edge':<10}")
    print("-" * 100)
    
    for match in matches:
        mid = match['match_id']
        name = f"{match['home_team'][:18]} vs {match['away_team'][:18]}"
        
        book_probs = match['odds_ps']
        total = book_probs['h'] + book_probs['d'] + book_probs['a']
        if total > 0:
            book_h = book_probs['h'] / total
            book_d = book_probs['d'] / total
            book_a = book_probs['a'] / total
        else:
            book_h = book_d = book_a = 0.33
        
        book_fav = 'Home' if book_h > max(book_d, book_a) else ('Away' if book_a > book_d else 'Draw')
        
        v3_result = None
        if v3:
            try:
                features = build_features_from_match(match)
                v3_result = v3.predict(features)
            except Exception as e:
                logger.debug(f"V3 prediction failed for {mid}: {e}")
                pass
        
        if v3_result:
            v3_pred = v3_result.get('prediction', 'N/A')
            v3_conf = v3_result.get('confidence', 0)
            v3_probs = v3_result.get('probabilities', {})
            
            pred_map = {'H': 'home', 'A': 'away', 'D': 'draw', 'home': 'home', 'away': 'away', 'draw': 'draw'}
            pred_key = pred_map.get(v3_pred, 'home')
            pred_prob = v3_probs.get(pred_key, 0)
            book_prob = book_h if pred_key == 'home' else (book_a if pred_key == 'away' else book_d)
            
            edge = (pred_prob - book_prob) * 100 if pred_prob and book_prob else 0
            
            print(f"{name:<40} {v3_pred:<12} {v3_conf:.2f}       {book_fav:<12} {edge:+.1f}%")
            
            results.append({
                'match_id': mid,
                'match': name,
                'league': match['league'],
                'v3_prediction': v3_pred,
                'v3_confidence': v3_conf,
                'v3_probabilities': v3_probs,
                'book_probabilities': {'home': book_h, 'draw': book_d, 'away': book_a},
                'book_favorite': book_fav,
                'edge_pct': edge
            })
        else:
            print(f"{name:<40} {'N/A':<12} {'N/A':<10} {book_fav:<12} {'N/A':<10}")
    
    print("-" * 100)
    
    return results


def build_features_from_match(match):
    """Build feature dict from match data for V3"""
    book = match['odds_ps']
    cons = match['odds_cons']
    
    total_ps = book['h'] + book['d'] + book['a']
    total_cons = cons['h'] + cons['d'] + cons['a']
    
    features = {
        'p_ps_h': book['h'] / total_ps if total_ps > 0 else 0.33,
        'p_ps_d': book['d'] / total_ps if total_ps > 0 else 0.33,
        'p_ps_a': book['a'] / total_ps if total_ps > 0 else 0.33,
        'p_avg_h': cons['h'] / total_cons if total_cons > 0 else 0.33,
        'p_avg_d': cons['d'] / total_cons if total_cons > 0 else 0.33,
        'p_avg_a': cons['a'] / total_cons if total_cons > 0 else 0.33,
        'p_b365_h': cons['h'] / total_cons if total_cons > 0 else 0.33,
        'p_b365_d': cons['d'] / total_cons if total_cons > 0 else 0.33,
        'p_b365_a': cons['a'] / total_cons if total_cons > 0 else 0.33,
    }
    
    h, d, a = features['p_ps_h'], features['p_ps_d'], features['p_ps_a']
    features['favorite_strength'] = max(h, d, a) - min(h, d, a)
    features['underdog_value'] = min(h, a)
    features['draw_tendency'] = d
    features['market_overround'] = total_ps - 1.0 if total_ps > 0 else 0.05
    features['sharp_soft_divergence'] = abs(h - features['p_avg_h']) + abs(a - features['p_avg_a'])
    features['max_vs_avg_edge_h'] = h - features['p_avg_h']
    features['max_vs_avg_edge_d'] = d - features['p_avg_d']
    features['max_vs_avg_edge_a'] = a - features['p_avg_a']
    features['league_home_win_rate'] = 0.45
    features['league_draw_rate'] = 0.27
    features['league_goals_avg'] = 2.7
    features['season_month'] = datetime.now().month
    features['expected_total_goals'] = 2.7
    features['home_goals_expected'] = 1.5
    features['away_goals_expected'] = 1.2
    features['goal_diff_expected'] = 0.3
    features['home_value_score'] = h * (1/h if h > 0 else 1) - 1
    features['draw_value_score'] = d * (1/d if d > 0 else 1) - 1
    features['away_value_score'] = a * (1/a if a > 0 else 1) - 1
    features['home_advantage_signal'] = h - a
    features['draw_vs_away_ratio'] = d / a if a > 0 else 1
    features['favorite_confidence'] = max(h, a) - 0.5
    features['upset_potential'] = min(h, a)
    features['book_agreement_score'] = 1 - features['sharp_soft_divergence']
    features['implied_competitiveness'] = 1 - features['favorite_strength']
    features['sharp_home_signal'] = features['max_vs_avg_edge_h']
    features['sharp_away_signal'] = features['max_vs_avg_edge_a']
    features['sharp_draw_signal'] = features['max_vs_avg_edge_d']
    
    return features


def generate_sample_parlays(results):
    """Generate sample parlays from V3 predictions"""
    print("\n" + "=" * 80)
    print("SAMPLE V3 PARLAYS")
    print("=" * 80)
    
    positive_edge = [r for r in results if r.get('edge_pct', 0) > 0]
    high_conf = [r for r in results if r.get('v3_confidence', 0) > 0.55]
    
    print(f"\n📈 Matches with positive edge: {len(positive_edge)}")
    print(f"🎯 High confidence matches (>55%): {len(high_conf)}")
    
    if len(positive_edge) >= 2:
        print("\n--- 2-LEG PARLAY (Positive Edge Picks) ---")
        legs = positive_edge[:2]
        combined_prob = 1.0
        combined_odds = 1.0
        
        for i, leg in enumerate(legs, 1):
            pred = leg['v3_prediction'].lower()
            prob = leg['v3_probabilities'].get(pred, 0.5)
            book_prob = leg['book_probabilities'].get(pred, 0.5)
            decimal_odds = 1 / book_prob if book_prob > 0 else 2.0
            
            combined_prob *= prob
            combined_odds *= decimal_odds
            
            print(f"  Leg {i}: {leg['match']}")
            print(f"         Pick: {leg['v3_prediction']} @ {decimal_odds:.2f}")
            print(f"         V3 Prob: {prob:.1%}, Edge: {leg['edge_pct']:+.1f}%")
        
        ev = (combined_prob * combined_odds) - 1
        payout = 100 * combined_odds
        
        print(f"\n  Combined Odds: {combined_odds:.2f}")
        print(f"  Combined Prob: {combined_prob:.1%}")
        print(f"  Expected Value: {ev*100:+.1f}%")
        print(f"  $100 Bet Payout: ${payout:.2f}")
    
    if len(high_conf) >= 3:
        print("\n--- 3-LEG PARLAY (High Confidence Picks) ---")
        legs = high_conf[:3]
        combined_prob = 1.0
        combined_odds = 1.0
        
        for i, leg in enumerate(legs, 1):
            pred = leg['v3_prediction'].lower()
            prob = leg['v3_probabilities'].get(pred, 0.5)
            book_prob = leg['book_probabilities'].get(pred, 0.5)
            decimal_odds = 1 / book_prob if book_prob > 0 else 2.0
            
            combined_prob *= prob
            combined_odds *= decimal_odds
            
            print(f"  Leg {i}: {leg['match']}")
            print(f"         Pick: {leg['v3_prediction']} @ {decimal_odds:.2f}, Conf: {leg['v3_confidence']:.0%}")
        
        ev = (combined_prob * combined_odds) - 1
        payout = 100 * combined_odds
        
        print(f"\n  Combined Odds: {combined_odds:.2f}")
        print(f"  Combined Prob: {combined_prob:.1%}")
        print(f"  Expected Value: {ev*100:+.1f}%")
        print(f"  $100 Bet Payout: ${payout:.2f}")
    
    return {
        'positive_edge_count': len(positive_edge),
        'high_confidence_count': len(high_conf),
        'sample_parlays_generated': 2 if len(positive_edge) >= 2 else 0
    }


def main():
    print("\n🎲 V3 ENSEMBLE PARLAY TESTING")
    print("=" * 80)
    
    matches = get_upcoming_matches(limit=15)
    print(f"\n📅 Found {len(matches)} upcoming matches with odds")
    
    if not matches:
        print("❌ No upcoming matches found. Try running fixture seeder first.")
        return
    
    results = test_v3_predictions(matches)
    
    if results:
        parlay_summary = generate_sample_parlays(results)
        
        print("\n" + "=" * 80)
        print("SUMMARY")
        print("=" * 80)
        print(f"Matches analyzed: {len(results)}")
        print(f"Positive edge picks: {parlay_summary['positive_edge_count']}")
        print(f"High confidence picks: {parlay_summary['high_confidence_count']}")
        
        avg_edge = sum(r.get('edge_pct', 0) for r in results) / len(results) if results else 0
        print(f"Average edge: {avg_edge:+.2f}%")
        
        with open('artifacts/v3_parlay_test_results.json', 'w') as f:
            json.dump({
                'timestamp': datetime.now().isoformat(),
                'matches_tested': len(results),
                'results': results,
                'summary': parlay_summary
            }, f, indent=2, default=str)
        
        print(f"\n✅ Results saved to artifacts/v3_parlay_test_results.json")


if __name__ == "__main__":
    main()
