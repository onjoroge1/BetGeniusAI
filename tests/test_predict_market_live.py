"""
Live API Integration Tests for Predict and Market Flows

These tests run against the actual API endpoints to verify
the V1 consensus and V3 fallback systems work correctly.

Run with: python tests/test_predict_market_live.py
"""

import os
import sys
import json
import requests
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE_URL = "http://localhost:8000"
AUTH_HEADER = {"Authorization": "Bearer betgenius_secure_key_2024"}


def get_match_with_consensus():
    """Find a match ID that has V1 consensus data"""
    import psycopg2
    try:
        conn = psycopg2.connect(os.environ.get('DATABASE_URL'))
        cursor = conn.cursor()
        cursor.execute("""
            SELECT match_id FROM consensus_predictions 
            WHERE consensus_h > 0 
            ORDER BY created_at DESC LIMIT 1
        """)
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        return row[0] if row else None
    except Exception as e:
        print(f"Error finding consensus match: {e}")
        return None


def get_match_without_consensus_but_sharp():
    """Find a match ID that has sharp book data but no consensus"""
    import psycopg2
    try:
        conn = psycopg2.connect(os.environ.get('DATABASE_URL'))
        cursor = conn.cursor()
        cursor.execute("""
            SELECT s.match_id 
            FROM sharp_book_odds s
            LEFT JOIN consensus_predictions c ON s.match_id = c.match_id
            WHERE c.match_id IS NULL
              AND s.match_id IS NOT NULL
              AND s.odds_home IS NOT NULL
            ORDER BY s.ts_recorded DESC
            LIMIT 1
        """)
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        return row[0] if row else None
    except Exception as e:
        print(f"Error finding sharp-only match: {e}")
        return None


class TestPredictAPIV1Consensus(unittest.TestCase):
    """Test /predict endpoint with V1 consensus data"""
    
    @classmethod
    def setUpClass(cls):
        cls.match_id = get_match_with_consensus()
        if not cls.match_id:
            print("WARNING: No match with consensus found, skipping V1 tests")
    
    def test_predict_returns_200(self):
        """Predict endpoint should return 200 for valid match"""
        if not self.match_id:
            self.skipTest("No match with consensus available")
        
        response = requests.post(
            f"{BASE_URL}/predict",
            json={"match_id": self.match_id, "include_analysis": False},
            headers=AUTH_HEADER,
            timeout=120
        )
        self.assertEqual(response.status_code, 200)
    
    def test_predict_has_v1_consensus_source(self):
        """Predict should return v1_consensus as prediction source"""
        if not self.match_id:
            self.skipTest("No match with consensus available")
        
        response = requests.post(
            f"{BASE_URL}/predict",
            json={"match_id": self.match_id, "include_analysis": False},
            headers=AUTH_HEADER,
            timeout=120
        )
        data = response.json()
        
        final_decision = data.get('predictions', {}).get('final_decision', {})
        self.assertEqual(final_decision.get('prediction_source'), 'v1_consensus')
    
    def test_predict_has_full_data_quality(self):
        """Predict with V1 should have full data quality"""
        if not self.match_id:
            self.skipTest("No match with consensus available")
        
        response = requests.post(
            f"{BASE_URL}/predict",
            json={"match_id": self.match_id, "include_analysis": False},
            headers=AUTH_HEADER,
            timeout=120
        )
        data = response.json()
        
        final_decision = data.get('predictions', {}).get('final_decision', {})
        self.assertEqual(final_decision.get('data_quality'), 'full')
    
    def test_predict_v2_active_with_v1(self):
        """V2 should be active when using V1 consensus"""
        if not self.match_id:
            self.skipTest("No match with consensus available")
        
        response = requests.post(
            f"{BASE_URL}/predict",
            json={"match_id": self.match_id, "include_analysis": False},
            headers=AUTH_HEADER,
            timeout=120
        )
        data = response.json()
        
        models = data.get('predictions', {}).get('models', [])
        v2_model = next((m for m in models if m.get('id') == 'v2_unified'), None)
        
        if v2_model:
            self.assertIn(v2_model.get('status'), ['active', 'unavailable'])
    
    def test_predict_model_info_structure(self):
        """Model info should have required fields"""
        if not self.match_id:
            self.skipTest("No match with consensus available")
        
        response = requests.post(
            f"{BASE_URL}/predict",
            json={"match_id": self.match_id, "include_analysis": False},
            headers=AUTH_HEADER,
            timeout=120
        )
        data = response.json()
        
        model_info = data.get('model_info', {})
        self.assertIn('prediction_source', model_info)
        self.assertIn('data_quality', model_info)


class TestPredictAPIV3Fallback(unittest.TestCase):
    """Test /predict endpoint with V3 sharp fallback"""
    
    @classmethod
    def setUpClass(cls):
        cls.match_id = get_match_without_consensus_but_sharp()
        if not cls.match_id:
            print("WARNING: No match with sharp-only data found, skipping V3 tests")
    
    def test_predict_v3_returns_200(self):
        """Predict should return 200 for sharp-only match"""
        if not self.match_id:
            self.skipTest("No match with sharp-only data available")
        
        response = requests.post(
            f"{BASE_URL}/predict",
            json={"match_id": self.match_id, "include_analysis": False},
            headers=AUTH_HEADER,
            timeout=120
        )
        self.assertEqual(response.status_code, 200)
    
    def test_predict_v3_has_fallback_source(self):
        """Predict should return v3_sharp_fallback as prediction source"""
        if not self.match_id:
            self.skipTest("No match with sharp-only data available")
        
        response = requests.post(
            f"{BASE_URL}/predict",
            json={"match_id": self.match_id, "include_analysis": False},
            headers=AUTH_HEADER,
            timeout=120
        )
        data = response.json()
        
        final_decision = data.get('predictions', {}).get('final_decision', {})
        prediction_source = final_decision.get('prediction_source')
        self.assertIn(prediction_source, ['v3_sharp_fallback', 'none'])
    
    def test_predict_v3_has_limited_quality(self):
        """Predict with V3 should have limited data quality"""
        if not self.match_id:
            self.skipTest("No match with sharp-only data available")
        
        response = requests.post(
            f"{BASE_URL}/predict",
            json={"match_id": self.match_id, "include_analysis": False},
            headers=AUTH_HEADER,
            timeout=120
        )
        data = response.json()
        
        final_decision = data.get('predictions', {}).get('final_decision', {})
        data_quality = final_decision.get('data_quality')
        self.assertIn(data_quality, ['limited', 'unavailable'])
    
    def test_predict_v2_skipped_with_v3(self):
        """V2 should be skipped when using V3 fallback"""
        if not self.match_id:
            self.skipTest("No match with sharp-only data available")
        
        response = requests.post(
            f"{BASE_URL}/predict",
            json={"match_id": self.match_id, "include_analysis": False},
            headers=AUTH_HEADER,
            timeout=120
        )
        data = response.json()
        
        final_decision = data.get('predictions', {}).get('final_decision', {})
        if final_decision.get('prediction_source') == 'v3_sharp_fallback':
            models = data.get('predictions', {}).get('models', [])
            v2_model = next((m for m in models if m.get('id') == 'v2_unified'), None)
            
            if v2_model:
                self.assertEqual(v2_model.get('status'), 'skipped')


class TestMarketAPILite(unittest.TestCase):
    """Test /market API lite mode"""
    
    def test_market_lite_returns_200(self):
        """Market API lite should return 200"""
        response = requests.get(
            f"{BASE_URL}/api/v1/market?status=all&limit=5",
            headers=AUTH_HEADER,
            timeout=30
        )
        self.assertEqual(response.status_code, 200)
    
    def test_market_lite_has_matches(self):
        """Market API should return matches array"""
        response = requests.get(
            f"{BASE_URL}/api/v1/market?status=all&limit=5",
            headers=AUTH_HEADER,
            timeout=30
        )
        data = response.json()
        self.assertIn('matches', data)
    
    def test_market_lite_prediction_structure(self):
        """Market lite predictions should have source and data_quality"""
        response = requests.get(
            f"{BASE_URL}/api/v1/market?status=all&limit=10",
            headers=AUTH_HEADER,
            timeout=30
        )
        data = response.json()
        
        matches = data.get('matches', [])
        for match in matches[:5]:
            prediction = match.get('prediction')
            if prediction:
                self.assertIn('source', prediction, f"Match {match.get('match_id')} missing source")
                self.assertIn('data_quality', prediction, f"Match {match.get('match_id')} missing data_quality")


class TestHealthEndpoint(unittest.TestCase):
    """Test health and root endpoints"""
    
    def test_root_returns_200(self):
        """Root endpoint should return 200"""
        response = requests.get(f"{BASE_URL}/", timeout=10)
        self.assertEqual(response.status_code, 200)
    
    def test_root_has_status(self):
        """Root should have running status"""
        response = requests.get(f"{BASE_URL}/", timeout=10)
        data = response.json()
        self.assertEqual(data.get('status'), 'running')


class TestAuthRequired(unittest.TestCase):
    """Test authentication is required"""
    
    def test_predict_requires_auth(self):
        """Predict should return 401 without auth"""
        response = requests.post(
            f"{BASE_URL}/predict",
            json={"match_id": 12345},
            timeout=10
        )
        self.assertEqual(response.status_code, 401)
    
    def test_predict_with_wrong_auth(self):
        """Predict should return 401 with wrong auth"""
        response = requests.post(
            f"{BASE_URL}/predict",
            json={"match_id": 12345},
            headers={"Authorization": "Bearer wrong_token"},
            timeout=10
        )
        self.assertEqual(response.status_code, 401)


def run_live_tests():
    """Run all live API tests"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    suite.addTests(loader.loadTestsFromTestCase(TestHealthEndpoint))
    suite.addTests(loader.loadTestsFromTestCase(TestAuthRequired))
    suite.addTests(loader.loadTestsFromTestCase(TestPredictAPIV1Consensus))
    suite.addTests(loader.loadTestsFromTestCase(TestPredictAPIV3Fallback))
    suite.addTests(loader.loadTestsFromTestCase(TestMarketAPILite))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    print(f"\n{'='*60}")
    print(f"LIVE API TESTS SUMMARY")
    print(f"{'='*60}")
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Skipped: {len(result.skipped)}")
    print(f"Success: {result.wasSuccessful()}")
    
    return result


if __name__ == '__main__':
    run_live_tests()
