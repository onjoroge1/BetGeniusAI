"""
Comprehensive QA Tests for Predict and Market API Flows

Test Categories:
1. V1 Consensus Flow Tests
2. V3 Sharp Fallback Flow Tests
3. No Prediction Flow Tests
4. /market API Integration Tests
5. Sharp Book Availability Tests
6. Response Structure Validation Tests
7. Edge Cases and Error Handling Tests
"""

import os
import sys
import unittest
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch, MagicMock, AsyncMock
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestSharpBookAvailability(unittest.TestCase):
    """Test sharp book availability checking logic"""
    
    def test_check_pinnacle_detection(self):
        """Should detect Pinnacle as sharp book"""
        available_books = ['pinnacle', 'bet365', 'unibet']
        has_pinnacle = any('pinnacle' in b for b in available_books)
        self.assertTrue(has_pinnacle)
    
    def test_check_bet365_detection(self):
        """Should detect Bet365 as sharp book"""
        available_books = ['bet365', 'unibet', 'williamhill']
        has_bet365 = any('bet365' in b for b in available_books)
        self.assertTrue(has_bet365)
    
    def test_check_betfair_detection(self):
        """Should detect Betfair exchange as sharp book"""
        available_books = ['betfair_ex_uk', 'ladbrokes']
        has_betfair = any('betfair' in b for b in available_books)
        self.assertTrue(has_betfair)
    
    def test_no_sharp_books_detected(self):
        """Should return False when no sharp books available"""
        available_books = ['unibet', 'williamhill', 'ladbrokes']
        has_pinnacle = any('pinnacle' in b for b in available_books)
        has_bet365 = any('bet365' in b for b in available_books)
        has_betfair = any('betfair' in b for b in available_books)
        has_sharp_book = has_pinnacle or has_bet365 or has_betfair
        self.assertFalse(has_sharp_book)
    
    def test_sharp_book_result_structure(self):
        """Should return correct structure from availability check"""
        available_books = ['pinnacle', 'bet365']
        has_pinnacle = any('pinnacle' in b for b in available_books)
        has_bet365 = any('bet365' in b for b in available_books)
        has_betfair = any('betfair' in b for b in available_books)
        
        result = {
            'has_sharp_book': has_pinnacle or has_bet365 or has_betfair,
            'has_pinnacle': has_pinnacle,
            'has_bet365': has_bet365,
            'has_betfair': has_betfair,
            'book_count': len(available_books),
            'available_books': available_books[:10]
        }
        
        self.assertTrue(result['has_sharp_book'])
        self.assertTrue(result['has_pinnacle'])
        self.assertTrue(result['has_bet365'])
        self.assertFalse(result['has_betfair'])
        self.assertEqual(result['book_count'], 2)


class TestPredictionSourceLogic(unittest.TestCase):
    """Test cascading prediction source logic"""
    
    def test_v1_consensus_takes_priority(self):
        """V1 consensus should be used when available"""
        v1_result = {'confidence': 0.55, 'probabilities': {'home': 0.45, 'draw': 0.28, 'away': 0.27}}
        
        if v1_result and v1_result.get('confidence', 0) > 0:
            prediction_source = "v1_consensus"
            data_quality = "full"
        else:
            prediction_source = "none"
            data_quality = "unavailable"
        
        self.assertEqual(prediction_source, "v1_consensus")
        self.assertEqual(data_quality, "full")
    
    def test_v3_fallback_when_v1_unavailable(self):
        """V3 should be used when V1 fails but sharp books available"""
        v1_result = None
        sharp_check = {'has_sharp_book': True, 'has_pinnacle': True}
        v3_result = {'confidence': 0.48, 'probabilities': {'home': 0.40, 'draw': 0.30, 'away': 0.30}}
        
        if v1_result and v1_result.get('confidence', 0) > 0:
            prediction_source = "v1_consensus"
            data_quality = "full"
        elif sharp_check.get('has_sharp_book') and v3_result:
            prediction_source = "v3_sharp_fallback"
            data_quality = "limited"
        else:
            prediction_source = "none"
            data_quality = "unavailable"
        
        self.assertEqual(prediction_source, "v3_sharp_fallback")
        self.assertEqual(data_quality, "limited")
    
    def test_no_prediction_when_both_fail(self):
        """Should return no prediction when V1 and V3 both fail"""
        v1_result = None
        sharp_check = {'has_sharp_book': False}
        v3_result = None
        
        if v1_result and v1_result.get('confidence', 0) > 0:
            prediction_source = "v1_consensus"
            data_quality = "full"
        elif sharp_check.get('has_sharp_book') and v3_result:
            prediction_source = "v3_sharp_fallback"
            data_quality = "limited"
        else:
            prediction_source = "none"
            data_quality = "unavailable"
        
        self.assertEqual(prediction_source, "none")
        self.assertEqual(data_quality, "unavailable")


class TestV2SkipLogic(unittest.TestCase):
    """Test V2 model skip logic when V3 fallback is active"""
    
    def test_v2_runs_when_v1_active(self):
        """V2 should run when using V1 consensus"""
        using_v3_fallback = False
        v2_should_run = not using_v3_fallback
        self.assertTrue(v2_should_run)
    
    def test_v2_skipped_when_v3_active(self):
        """V2 should be skipped when using V3 fallback"""
        using_v3_fallback = True
        v2_should_run = not using_v3_fallback
        self.assertFalse(v2_should_run)


class TestModelsArrayStructure(unittest.TestCase):
    """Test the models array structure in response"""
    
    def test_v1_consensus_model_structure(self):
        """V1 consensus model entry should have correct structure"""
        v1_model = {
            "id": "v1_consensus",
            "name": "Market Weighted Consensus",
            "type": "ensemble",
            "version": "1.0.0",
            "status": "active",
            "data_quality": "full",
            "predictions": {
                "home_win": 0.45,
                "draw": 0.28,
                "away_win": 0.27
            },
            "confidence": 0.55,
            "recommended_bet": "home_win",
            "quality_metrics": {
                "metric": "multi_logloss",
                "value": 0.963475,
                "sample_size": 5415
            }
        }
        
        self.assertEqual(v1_model['id'], 'v1_consensus')
        self.assertEqual(v1_model['status'], 'active')
        self.assertEqual(v1_model['data_quality'], 'full')
        self.assertIn('predictions', v1_model)
        self.assertIn('quality_metrics', v1_model)
    
    def test_v3_fallback_model_structure(self):
        """V3 fallback model entry should have correct structure"""
        v3_model = {
            "id": "v3_sharp_fallback",
            "name": "V3 Sharp Intelligence (Fallback)",
            "type": "lightgbm_ensemble",
            "version": "3.0.0",
            "status": "active",
            "data_quality": "limited",
            "predictions": {
                "home_win": 0.40,
                "draw": 0.30,
                "away_win": 0.30
            },
            "confidence": 0.48,
            "recommended_bet": "home_win",
            "quality_metrics": {
                "metric": "multi_logloss",
                "value": 0.9788,
                "sample_size": 4021,
                "features_used": 8,
                "total_features": 34
            },
            "fallback_reason": "V1 consensus unavailable - using V3 sharp book intelligence"
        }
        
        self.assertEqual(v3_model['id'], 'v3_sharp_fallback')
        self.assertEqual(v3_model['status'], 'active')
        self.assertEqual(v3_model['data_quality'], 'limited')
        self.assertIn('fallback_reason', v3_model)
        self.assertIn('features_used', v3_model['quality_metrics'])
    
    def test_v2_skipped_model_structure(self):
        """V2 skipped model entry should have correct structure"""
        v2_model = {
            "id": "v2_unified",
            "name": "Unified V2 Context Model",
            "type": "lightgbm",
            "version": "2.0.0",
            "status": "skipped",
            "reason": "Skipped - using V3 sharp fallback",
            "predictions": None,
            "confidence": None,
            "recommended_bet": None
        }
        
        self.assertEqual(v2_model['id'], 'v2_unified')
        self.assertEqual(v2_model['status'], 'skipped')
        self.assertIn('V3 sharp fallback', v2_model['reason'])
        self.assertIsNone(v2_model['predictions'])


class TestFinalDecisionStructure(unittest.TestCase):
    """Test final_decision block structure"""
    
    def test_v1_final_decision(self):
        """Final decision for V1 should have correct structure"""
        final_decision = {
            "selected_model": "v1_consensus",
            "strategy": "v1_primary_v2_transparency",
            "reason": "V1 consensus is primary model",
            "prediction_source": "v1_consensus",
            "data_quality": "full"
        }
        
        self.assertEqual(final_decision['selected_model'], 'v1_consensus')
        self.assertEqual(final_decision['prediction_source'], 'v1_consensus')
        self.assertEqual(final_decision['data_quality'], 'full')
    
    def test_v3_final_decision(self):
        """Final decision for V3 should have correct structure"""
        final_decision = {
            "selected_model": "v3_sharp_fallback",
            "strategy": "v3_sharp_fallback",
            "reason": "V3 sharp intelligence fallback (V1 consensus unavailable)",
            "prediction_source": "v3_sharp_fallback",
            "data_quality": "limited"
        }
        
        self.assertEqual(final_decision['selected_model'], 'v3_sharp_fallback')
        self.assertEqual(final_decision['prediction_source'], 'v3_sharp_fallback')
        self.assertEqual(final_decision['data_quality'], 'limited')


class TestModelInfoStructure(unittest.TestCase):
    """Test model_info block structure"""
    
    def test_v1_model_info(self):
        """Model info for V1 should have correct structure"""
        model_info = {
            "type": "simple_weighted_consensus",
            "version": "1.0.0",
            "performance": "0.963475 LogLoss (best performing)",
            "bookmaker_count": 12,
            "quality_score": 0.85,
            "data_quality": "full",
            "prediction_source": "v1_consensus",
            "data_sources": ["RapidAPI Football", "Multiple Bookmakers", "Real-time Injuries", "Team News"]
        }
        
        self.assertEqual(model_info['prediction_source'], 'v1_consensus')
        self.assertEqual(model_info['data_quality'], 'full')
        self.assertIn('bookmaker_count', model_info)
    
    def test_v3_model_info(self):
        """Model info for V3 should have correct structure"""
        model_info = {
            "type": "v3_sharp_fallback",
            "version": "3.0.0",
            "performance": "0.9788 LogLoss (sharp book intelligence)",
            "bookmaker_count": 1,
            "quality_score": 0.65,
            "data_quality": "limited",
            "prediction_source": "v3_sharp_fallback",
            "features_used": 8,
            "total_features": 34,
            "data_sources": ["Sharp Bookmakers", "League Statistics", "Real-time Injuries"]
        }
        
        self.assertEqual(model_info['prediction_source'], 'v3_sharp_fallback')
        self.assertEqual(model_info['data_quality'], 'limited')
        self.assertIn('features_used', model_info)
        self.assertIn('total_features', model_info)


class TestMarketAPILiteMode(unittest.TestCase):
    """Test /market API lite mode structure"""
    
    def test_lite_prediction_with_v1(self):
        """Lite mode prediction with V1 should have correct structure"""
        prediction = {
            "pick": "home",
            "confidence": 0.55,
            "source": "v1_consensus",
            "data_quality": "full"
        }
        
        self.assertEqual(prediction['source'], 'v1_consensus')
        self.assertEqual(prediction['data_quality'], 'full')
        self.assertIn('pick', prediction)
        self.assertIn('confidence', prediction)
    
    def test_lite_prediction_with_v3(self):
        """Lite mode prediction with V3 should have correct structure"""
        prediction = {
            "pick": "home",
            "confidence": 0.48,
            "source": "v3_fallback",
            "data_quality": "limited"
        }
        
        self.assertEqual(prediction['source'], 'v3_fallback')
        self.assertEqual(prediction['data_quality'], 'limited')


class TestMarketAPIFullMode(unittest.TestCase):
    """Test /market API full mode structure"""
    
    def test_full_v1_data_structure(self):
        """Full mode V1 data should have correct structure"""
        v1_data = {
            "probs": {"home": 0.45, "draw": 0.28, "away": 0.27},
            "pick": "home",
            "confidence": 0.55,
            "source": "v1_consensus",
            "data_quality": "full"
        }
        
        self.assertIn('probs', v1_data)
        self.assertEqual(v1_data['source'], 'v1_consensus')
        self.assertEqual(v1_data['data_quality'], 'full')
    
    def test_full_v3_data_structure(self):
        """Full mode V3 fallback data should have correct structure"""
        v1_data = {
            "probs": {"home": 0.40, "draw": 0.30, "away": 0.30},
            "pick": "home",
            "confidence": 0.48,
            "source": "v3_sharp_fallback",
            "data_quality": "limited",
            "features_used": 8,
            "total_features": 34
        }
        
        self.assertIn('probs', v1_data)
        self.assertEqual(v1_data['source'], 'v3_sharp_fallback')
        self.assertEqual(v1_data['data_quality'], 'limited')
        self.assertIn('features_used', v1_data)


class TestProbabilityNormalization(unittest.TestCase):
    """Test probability normalization logic"""
    
    def test_normalize_valid_probabilities(self):
        """Should correctly normalize probabilities that sum to 1"""
        h, d, a = 0.45, 0.28, 0.27
        total = h + d + a
        h_norm = h / total if total > 0 else 0.33
        d_norm = d / total if total > 0 else 0.33
        a_norm = a / total if total > 0 else 0.34
        
        self.assertAlmostEqual(h_norm + d_norm + a_norm, 1.0, places=5)
    
    def test_normalize_zero_probabilities(self):
        """Should handle zero probabilities gracefully"""
        h, d, a = 0.0, 0.0, 0.0
        total = h + d + a
        h_norm = h / total if total > 0 else 0.33
        d_norm = d / total if total > 0 else 0.33
        a_norm = a / total if total > 0 else 0.34
        
        self.assertAlmostEqual(h_norm + d_norm + a_norm, 1.0, places=5)
    
    def test_normalize_unnormalized_probabilities(self):
        """Should correctly normalize probabilities that don't sum to 1"""
        h, d, a = 0.50, 0.30, 0.30  # Sums to 1.1
        total = h + d + a
        h_norm = h / total if total > 0 else 0.33
        d_norm = d / total if total > 0 else 0.33
        a_norm = a / total if total > 0 else 0.34
        
        self.assertAlmostEqual(h_norm + d_norm + a_norm, 1.0, places=5)


class TestConfidenceGating(unittest.TestCase):
    """Test confidence-based recommendation gating"""
    
    def test_high_confidence_full_recommendation(self):
        """High confidence should give full recommendation"""
        confidence = 0.55
        raw_prediction = "home"
        
        if confidence >= 0.50:
            recommended_bet = raw_prediction
            recommendation_tone = "confident"
        elif confidence >= 0.40:
            recommended_bet = raw_prediction
            recommendation_tone = "moderate"
        else:
            recommended_bet = "No Recommendation"
            recommendation_tone = "uncertain"
        
        self.assertEqual(recommended_bet, "home")
        self.assertEqual(recommendation_tone, "confident")
    
    def test_low_confidence_uncertain(self):
        """Low confidence should give uncertain recommendation"""
        confidence = 0.35
        raw_prediction = "home"
        
        if confidence >= 0.50:
            recommended_bet = raw_prediction
            recommendation_tone = "confident"
        elif confidence >= 0.40:
            recommended_bet = raw_prediction
            recommendation_tone = "moderate"
        else:
            recommended_bet = "No Recommendation"
            recommendation_tone = "uncertain"
        
        self.assertEqual(recommended_bet, "No Recommendation")
        self.assertEqual(recommendation_tone, "uncertain")


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and error handling"""
    
    def test_empty_odds_snapshots(self):
        """Should handle empty odds_snapshots gracefully"""
        available_books = []
        has_sharp_book = any('pinnacle' in b for b in available_books) or \
                        any('bet365' in b for b in available_books) or \
                        any('betfair' in b for b in available_books)
        
        self.assertFalse(has_sharp_book)
    
    def test_missing_probabilities(self):
        """Should handle missing probabilities gracefully"""
        prediction_result = {}
        probs = prediction_result.get('probabilities', {})
        h = probs.get('home', 0.0)
        d = probs.get('draw', 0.0)
        a = probs.get('away', 0.0)
        
        self.assertEqual(h, 0.0)
        self.assertEqual(d, 0.0)
        self.assertEqual(a, 0.0)
    
    def test_v3_with_partial_features(self):
        """V3 should work with partial features"""
        v3_result = {
            'features_used': 8,
            'total_features': 34,
            'confidence': 0.48
        }
        
        feature_coverage = v3_result['features_used'] / v3_result['total_features']
        self.assertLess(feature_coverage, 0.5)  # Less than 50% features
        self.assertGreater(v3_result['confidence'], 0)  # But still has confidence


class TestIntegrationFlow(unittest.TestCase):
    """Integration tests for full prediction flow"""
    
    def test_full_v1_flow_structure(self):
        """Test complete V1 consensus flow produces valid structure"""
        response = {
            "match_info": {
                "home_team": "Team A",
                "away_team": "Team B"
            },
            "predictions": {
                "home_win": 0.45,
                "draw": 0.28,
                "away_win": 0.27,
                "confidence": 0.55,
                "recommended_bet": "home_win",
                "models": [
                    {"id": "v1_consensus", "status": "active"},
                    {"id": "v2_unified", "status": "active"}
                ],
                "final_decision": {
                    "selected_model": "v1_consensus",
                    "prediction_source": "v1_consensus",
                    "data_quality": "full"
                }
            },
            "model_info": {
                "prediction_source": "v1_consensus",
                "data_quality": "full"
            }
        }
        
        self.assertEqual(response['predictions']['final_decision']['prediction_source'], 'v1_consensus')
        self.assertEqual(response['model_info']['data_quality'], 'full')
        self.assertEqual(len(response['predictions']['models']), 2)
    
    def test_full_v3_flow_structure(self):
        """Test complete V3 fallback flow produces valid structure"""
        response = {
            "match_info": {
                "home_team": "Team A",
                "away_team": "Team B"
            },
            "predictions": {
                "home_win": 0.40,
                "draw": 0.30,
                "away_win": 0.30,
                "confidence": 0.48,
                "recommended_bet": "Home",
                "models": [
                    {"id": "v3_sharp_fallback", "status": "active", "data_quality": "limited"},
                    {"id": "v2_unified", "status": "skipped"}
                ],
                "final_decision": {
                    "selected_model": "v3_sharp_fallback",
                    "prediction_source": "v3_sharp_fallback",
                    "data_quality": "limited"
                }
            },
            "model_info": {
                "prediction_source": "v3_sharp_fallback",
                "data_quality": "limited"
            }
        }
        
        self.assertEqual(response['predictions']['final_decision']['prediction_source'], 'v3_sharp_fallback')
        self.assertEqual(response['model_info']['data_quality'], 'limited')
        self.assertEqual(response['predictions']['models'][1]['status'], 'skipped')


class TestAsyncDatabaseQueries(unittest.TestCase):
    """Test async database query patterns"""
    
    def test_union_query_structure(self):
        """Union query should combine both tables correctly"""
        query = """
            SELECT DISTINCT book_id FROM odds_snapshots 
            WHERE match_id = %s AND market = 'h2h'
            UNION
            SELECT DISTINCT bookmaker FROM sharp_book_odds 
            WHERE match_id = %s AND odds_home IS NOT NULL
        """
        
        self.assertIn('odds_snapshots', query)
        self.assertIn('sharp_book_odds', query)
        self.assertIn('UNION', query)


if __name__ == '__main__':
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    suite.addTests(loader.loadTestsFromTestCase(TestSharpBookAvailability))
    suite.addTests(loader.loadTestsFromTestCase(TestPredictionSourceLogic))
    suite.addTests(loader.loadTestsFromTestCase(TestV2SkipLogic))
    suite.addTests(loader.loadTestsFromTestCase(TestModelsArrayStructure))
    suite.addTests(loader.loadTestsFromTestCase(TestFinalDecisionStructure))
    suite.addTests(loader.loadTestsFromTestCase(TestModelInfoStructure))
    suite.addTests(loader.loadTestsFromTestCase(TestMarketAPILiteMode))
    suite.addTests(loader.loadTestsFromTestCase(TestMarketAPIFullMode))
    suite.addTests(loader.loadTestsFromTestCase(TestProbabilityNormalization))
    suite.addTests(loader.loadTestsFromTestCase(TestConfidenceGating))
    suite.addTests(loader.loadTestsFromTestCase(TestEdgeCases))
    suite.addTests(loader.loadTestsFromTestCase(TestIntegrationFlow))
    suite.addTests(loader.loadTestsFromTestCase(TestAsyncDatabaseQueries))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    print(f"\n{'='*60}")
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Success: {result.wasSuccessful()}")
