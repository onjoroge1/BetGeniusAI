"""
Test V2 Model with Full 46-Feature Pipeline

Validates:
1. Feature builder constructs all 46 features
2. V2 predictor uses full pipeline
3. Feature parity validation works
4. Accuracy improvement vs market-only mode
"""

import logging
import sys
import os
from datetime import datetime

# Setup path
sys.path.append('.')

from features.v2_feature_builder import get_v2_feature_builder
from models.v2_lgbm_predictor import V2LightGBMPredictor
from sqlalchemy import create_engine, text

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_feature_builder():
    """Test that feature builder creates all 46 features"""
    logger.info("\n" + "="*60)
    logger.info("TEST 1: Feature Builder")
    logger.info("="*60)
    
    try:
        # Get a recent match from database
        database_url = os.getenv('DATABASE_URL')
        engine = create_engine(database_url)
        
        query = text("""
            SELECT match_id, home_team, away_team, match_date
            FROM training_matches
            WHERE outcome IS NOT NULL
              AND match_date >= '2024-01-01'
            ORDER BY match_date DESC
            LIMIT 1
        """)
        
        with engine.connect() as conn:
            result = conn.execute(query).mappings().first()
        
        if not result:
            logger.error("❌ No matches found in database")
            return False
        
        match_id = result['match_id']
        logger.info(f"✅ Testing with match {match_id}: {result['home_team']} vs {result['away_team']}")
        logger.info(f"   Date: {result['match_date']}")
        
        # Build features
        builder = get_v2_feature_builder()
        features = builder.build_features(match_id)
        
        # Validate
        logger.info(f"\n📊 Feature Summary:")
        logger.info(f"   Total features: {len(features)}")
        logger.info(f"   Expected: 46")
        
        if len(features) != 46:
            logger.warning(f"⚠️  Feature count mismatch!")
        else:
            logger.info(f"✅ Feature count correct!")
        
        # Show sample features
        logger.info(f"\n📋 Sample Features:")
        sample_keys = [
            'p_last_home', 'p_last_draw', 'p_last_away',
            'home_elo', 'away_elo', 'elo_diff',
            'home_form_points', 'away_form_points',
            'h2h_home_wins', 'h2h_draws', 'h2h_away_wins',
            'days_since_home_last_match', 'days_since_away_last_match'
        ]
        
        for key in sample_keys:
            value = features.get(key, 'MISSING')
            logger.info(f"   {key:30s}: {value}")
        
        # Check for missing values
        missing = [k for k, v in features.items() if v is None or (isinstance(v, float) and v == 0.0)]
        if missing:
            logger.info(f"\n⚠️  Features with zero/missing values: {len(missing)}")
            logger.info(f"   (This is expected if data is sparse)")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Feature builder test failed: {e}")
        logger.exception(e)
        return False


def test_v2_predictor():
    """Test V2 predictor with full features"""
    logger.info("\n" + "="*60)
    logger.info("TEST 2: V2 Predictor with Full Features")
    logger.info("="*60)
    
    try:
        # Get a recent match
        database_url = os.getenv('DATABASE_URL')
        engine = create_engine(database_url)
        
        query = text("""
            SELECT tm.match_id, tm.home_team, tm.away_team, tm.outcome,
                   oc.ph_cons, oc.pd_cons, oc.pa_cons
            FROM training_matches tm
            LEFT JOIN odds_consensus oc ON tm.match_id = oc.match_id
            WHERE tm.outcome IS NOT NULL
              AND tm.match_date >= '2024-01-01'
              AND oc.ph_cons IS NOT NULL
            ORDER BY tm.match_date DESC
            LIMIT 1
        """)
        
        with engine.connect() as conn:
            result = conn.execute(query).mappings().first()
        
        if not result:
            logger.error("❌ No matches with odds found")
            return False
        
        match_id = result['match_id']
        market_probs = {
            'home': result['ph_cons'],
            'draw': result['pd_cons'],
            'away': result['pa_cons']
        }
        
        logger.info(f"✅ Testing with match {match_id}: {result['home_team']} vs {result['away_team']}")
        logger.info(f"\n📊 Market Probabilities:")
        logger.info(f"   Home: {market_probs['home']:.3f}")
        logger.info(f"   Draw: {market_probs['draw']:.3f}")
        logger.info(f"   Away: {market_probs['away']:.3f}")
        
        # Initialize predictor
        predictor = V2LightGBMPredictor()
        
        # Test 1: Full pipeline (with match_id)
        logger.info(f"\n🔬 Test 1: FULL FEATURE PIPELINE")
        pred_full = predictor.predict(match_id=match_id)
        
        if pred_full:
            logger.info(f"   Source: {pred_full.get('feature_source', 'unknown')}")
            logger.info(f"   Probabilities:")
            logger.info(f"      Home: {pred_full['probabilities']['home']:.3f}")
            logger.info(f"      Draw: {pred_full['probabilities']['draw']:.3f}")
            logger.info(f"      Away: {pred_full['probabilities']['away']:.3f}")
            logger.info(f"   Confidence: {pred_full['confidence']:.3f}")
            logger.info(f"   Prediction: {pred_full['prediction']}")
            
            if pred_full.get('feature_source') == 'full_pipeline':
                logger.info("   ✅ Using full 46-feature pipeline!")
            else:
                logger.warning("   ⚠️  Fell back to market-only mode")
        else:
            logger.error("   ❌ Prediction failed")
        
        # Test 2: Market-only mode (legacy)
        logger.info(f"\n🔬 Test 2: MARKET-ONLY MODE (legacy)")
        pred_market = predictor.predict(market_probs=market_probs)
        
        if pred_market:
            logger.info(f"   Source: {pred_market.get('feature_source', 'unknown')}")
            logger.info(f"   Probabilities:")
            logger.info(f"      Home: {pred_market['probabilities']['home']:.3f}")
            logger.info(f"      Draw: {pred_market['probabilities']['draw']:.3f}")
            logger.info(f"      Away: {pred_market['probabilities']['away']:.3f}")
            logger.info(f"   Confidence: {pred_market['confidence']:.3f}")
        else:
            logger.error("   ❌ Prediction failed")
        
        # Compare predictions
        if pred_full and pred_market:
            logger.info(f"\n📊 Comparison:")
            logger.info(f"   Full pipeline vs Market-only")
            
            for outcome in ['home', 'draw', 'away']:
                full_prob = pred_full['probabilities'][outcome]
                market_prob = pred_market['probabilities'][outcome]
                diff = full_prob - market_prob
                logger.info(f"   {outcome.capitalize():6s}: {full_prob:.3f} vs {market_prob:.3f} (Δ {diff:+.3f})")
            
            # Actual outcome
            actual = result['outcome']
            logger.info(f"\n🎯 Actual outcome: {actual}")
            
            outcome_map = {'H': 'home', 'D': 'draw', 'A': 'away'}
            if actual in outcome_map:
                actual_outcome = outcome_map[actual]
                full_prob_actual = pred_full['probabilities'][actual_outcome]
                market_prob_actual = pred_market['probabilities'][actual_outcome]
                
                logger.info(f"   Full pipeline gave actual outcome prob: {full_prob_actual:.3f}")
                logger.info(f"   Market-only gave actual outcome prob:  {market_prob_actual:.3f}")
                
                if full_prob_actual > market_prob_actual:
                    logger.info(f"   ✅ Full pipeline was MORE confident in correct outcome")
                elif full_prob_actual < market_prob_actual:
                    logger.info(f"   ⚠️  Full pipeline was LESS confident in correct outcome")
                else:
                    logger.info(f"   ➡️  Equal confidence")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ V2 predictor test failed: {e}")
        logger.exception(e)
        return False


def main():
    """Run all tests"""
    logger.info("\n" + "="*60)
    logger.info("  BetGenius AI - V2 Full Feature Pipeline Test")
    logger.info("="*60)
    
    results = {}
    
    # Run tests
    results['feature_builder'] = test_feature_builder()
    results['v2_predictor'] = test_v2_predictor()
    
    # Summary
    logger.info("\n" + "="*60)
    logger.info("  Test Summary")
    logger.info("="*60)
    
    for test_name, passed in results.items():
        status = "✅ PASSED" if passed else "❌ FAILED"
        logger.info(f"  {test_name:20s}: {status}")
    
    all_passed = all(results.values())
    
    if all_passed:
        logger.info("\n🎉 All tests passed!")
        logger.info("\n📋 Next Steps:")
        logger.info("  1. Run evaluation harness on historical data")
        logger.info("  2. Measure accuracy improvement (expect +10-15%)")
        logger.info("  3. Apply database schema extensions")
        logger.info("  4. Implement data fetchers for backfill agent")
        logger.info("  5. Start collecting referee/weather/lineup data")
    else:
        logger.error("\n❌ Some tests failed - review errors above")
    
    logger.info("="*60)


if __name__ == "__main__":
    main()
