#!/usr/bin/env python3
"""
Regression tests for prediction system bugs
Tests to prevent the three critical bugs from recurring:
1. Probability normalization issues
2. Recommended bet misalignment
3. Missing outcome handling
"""

import unittest
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from models.simple_consensus_predictor import SimpleWeightedConsensusPredictor

class TestPredictionRegression(unittest.TestCase):
    """Regression tests for prediction system"""
    
    def setUp(self):
        """Set up test predictor"""
        self.predictor = SimpleWeightedConsensusPredictor()
    
    def test_probabilities_sum_to_one(self):
        """Test that probabilities always sum to 1.0"""
        test_odds = {
            'pinnacle': {'home': 2.10, 'draw': 3.40, 'away': 3.20},
            'bet365': {'home': 2.05, 'draw': 3.30, 'away': 3.15},
            'betway': {'home': 2.08, 'draw': 3.35, 'away': 3.18}
        }
        
        result = self.predictor.predict_match(test_odds)
        self.assertIsNotNone(result)
        
        probs = result['probabilities']
        total = probs['home'] + probs['draw'] + probs['away']
        
        # Must sum to 1.0 within tolerance (allow for floating point precision)
        self.assertAlmostEqual(total, 1.0, delta=0.01, 
                              msg=f"Probabilities don't sum to 1.0: {total}")
    
    def test_recommended_bet_matches_highest_probability(self):
        """Test that recommended bet always matches highest probability"""
        # Test case 1: Home favorite
        home_favorite_odds = {
            'pinnacle': {'home': 1.50, 'draw': 4.00, 'away': 6.00},
            'bet365': {'home': 1.52, 'draw': 3.90, 'away': 5.80}
        }
        
        result = self.predictor.predict_match(home_favorite_odds)
        self.assertIsNotNone(result)
        
        probs = result['probabilities']
        highest_prob_outcome = max(probs, key=probs.get)
        recommended = result['prediction']
        
        expected_recommendation = {'home': 'Home', 'draw': 'Draw', 'away': 'Away'}[highest_prob_outcome]
        
        # Handle "No Bet" case for low confidence
        if recommended != "No Bet":
            self.assertEqual(recommended, expected_recommendation,
                           f"Recommended bet '{recommended}' doesn't match highest probability outcome '{expected_recommendation}'")
        
        # Test case 2: Away favorite 
        away_favorite_odds = {
            'pinnacle': {'home': 5.00, 'draw': 3.50, 'away': 1.70},
            'bet365': {'home': 4.80, 'draw': 3.40, 'away': 1.75}
        }
        
        result = self.predictor.predict_match(away_favorite_odds)
        self.assertIsNotNone(result)
        
        probs = result['probabilities']
        highest_prob_outcome = max(probs, key=probs.get)
        recommended = result['prediction']
        
        expected_recommendation = {'home': 'Home', 'draw': 'Draw', 'away': 'Away'}[highest_prob_outcome]
        
        if recommended != "No Bet":
            self.assertEqual(recommended, expected_recommendation,
                           f"Recommended bet '{recommended}' doesn't match highest probability outcome '{expected_recommendation}'")
    
    def test_no_zero_probabilities_with_complete_data(self):
        """Test that complete odds data never produces zero probabilities"""
        complete_odds = {
            'pinnacle': {'home': 2.10, 'draw': 3.40, 'away': 3.20},
            'bet365': {'home': 2.05, 'draw': 3.30, 'away': 3.15}
        }
        
        result = self.predictor.predict_match(complete_odds)
        self.assertIsNotNone(result)
        
        probs = result['probabilities']
        
        # No probability should be zero with complete data
        self.assertGreater(probs['home'], 0, "Home probability should not be zero")
        self.assertGreater(probs['draw'], 0, "Draw probability should not be zero") 
        self.assertGreater(probs['away'], 0, "Away probability should not be zero")
    
    def test_missing_outcomes_handled_safely(self):
        """Test that missing outcomes are handled without breaking the system"""
        # Incomplete odds (missing 'away' outcome)
        incomplete_odds = {
            'pinnacle': {'home': 2.10, 'draw': 3.40},  # Missing 'away'
            'bet365': {'home': 2.05, 'draw': 3.30, 'away': 3.15}  # Complete
        }
        
        result = self.predictor.predict_match(incomplete_odds)
        
        # Should either return None or valid probabilities, never broken ones
        if result is not None:
            probs = result['probabilities']
            total = probs['home'] + probs['draw'] + probs['away']
            self.assertAlmostEqual(total, 1.0, delta=0.01)
            
            # Check for no "broken" probabilities (like 0, 0.255, 0)
            zero_count = sum(1 for p in probs.values() if p == 0)
            self.assertLess(zero_count, 2, "Too many zero probabilities suggest broken calculation")
    
    def test_safe_simplex_normalization(self):
        """Test the safe_simplex function handles edge cases"""
        # Test normal case
        normal_probs = {'home': 0.4, 'draw': 0.3, 'away': 0.2}
        result = self.predictor.safe_simplex(normal_probs)
        self.assertIsNotNone(result)
        total = sum(result.values())
        self.assertAlmostEqual(total, 1.0, places=6)
        
        # Test zero case
        zero_probs = {'home': 0.0, 'draw': 0.0, 'away': 0.0}
        result = self.predictor.safe_simplex(zero_probs)
        self.assertIsNone(result, "Zero probabilities should return None")
        
        # Test negative case (should be clamped)
        negative_probs = {'home': -0.1, 'draw': 0.5, 'away': 0.6}
        result = self.predictor.safe_simplex(negative_probs)
        self.assertIsNotNone(result)
        self.assertGreaterEqual(result['home'], 0, "Negative values should be clamped to 0")
    
    def test_entropy_confidence_bounds(self):
        """Test that entropy-based confidence is properly bounded [0,1]"""
        # High confidence case (strong favorite)
        strong_favorite = {'home': 0.8, 'draw': 0.1, 'away': 0.1}
        confidence = self.predictor.prob_confidence(strong_favorite)
        self.assertGreaterEqual(confidence, 0.0)
        self.assertLessEqual(confidence, 1.0)
        self.assertGreater(confidence, 0.3, "Strong favorite should have reasonable confidence")
        
        # Low confidence case (even odds)
        even_odds = {'home': 0.33, 'draw': 0.34, 'away': 0.33}
        confidence = self.predictor.prob_confidence(even_odds)
        self.assertGreaterEqual(confidence, 0.0)
        self.assertLessEqual(confidence, 1.0)
        self.assertLess(confidence, 0.3, "Even odds should have low confidence")
    
    def test_build_consensus_requires_complete_triplets(self):
        """Test that consensus only uses complete H/D/A triplets"""
        mixed_odds = {
            'pinnacle': {'home': 2.10, 'draw': 3.40, 'away': 3.20},  # Complete
            'bet365': {'home': 2.05, 'draw': 3.30},  # Incomplete - missing away
            'betway': {'home': 2.08, 'draw': 3.35, 'away': 3.18}   # Complete
        }
        
        result = self.predictor.build_consensus(mixed_odds)
        
        if result is not None:
            pH, pD, pA, triplet_count = result
            # Should only count complete triplets (pinnacle and betway)
            self.assertEqual(triplet_count, 2, "Should only count complete triplets")
            
            # Probabilities should be reasonable
            self.assertGreater(pH, 0)
            self.assertGreater(pD, 0)
            self.assertGreater(pA, 0)
    
    def test_devig_edge_cases(self):
        """Test devig function handles edge cases properly"""
        # Normal case
        result = self.predictor.devig_triplet(0.5, 0.3, 0.25)
        self.assertIsNotNone(result)
        pH, pD, pA = result
        self.assertAlmostEqual(pH + pD + pA, 1.0, places=3)
        
        # Zero total case
        result = self.predictor.devig_triplet(0.0, 0.0, 0.0)
        self.assertIsNone(result, "Zero total should return None")
        
        # Very small total case
        result = self.predictor.devig_triplet(1e-15, 1e-15, 1e-15)
        self.assertIsNone(result, "Tiny total should return None")

def run_regression_tests():
    """Run all regression tests and report results"""
    print("🧪 Running Prediction System Regression Tests")
    print("=" * 60)
    
    # Create test suite
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestPredictionRegression)
    
    # Run tests with detailed output
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Summary
    print("\n" + "=" * 60)
    print("📊 REGRESSION TEST SUMMARY")
    print("=" * 60)
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    
    if result.failures:
        print("\n❌ FAILURES:")
        for test, traceback in result.failures:
            error_msg = traceback.split('AssertionError: ')[-1].split('\n')[0]
            print(f"  • {test}: {error_msg}")
    
    if result.errors:
        print("\n🚨 ERRORS:")
        for test, traceback in result.errors:
            error_msg = traceback.split('\n')[-2]
            print(f"  • {test}: {error_msg}")
    
    if not result.failures and not result.errors:
        print("\n✅ ALL TESTS PASSED - No regression detected!")
    else:
        print(f"\n⚠️  {len(result.failures + result.errors)} issues found")
    
    return len(result.failures) + len(result.errors) == 0

if __name__ == "__main__":
    success = run_regression_tests()
    sys.exit(0 if success else 1)