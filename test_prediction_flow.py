#!/usr/bin/env python3
"""
Comprehensive Prediction Flow Test
Tests the full prediction pipeline and validates ML prediction consistency
"""

import requests
import json
import time
from datetime import datetime
from typing import Dict, List, Any
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class PredictionFlowTester:
    """Test the complete prediction flow and validate results"""
    
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.headers = {
            "Authorization": "Bearer betgenius_secure_key_2024",
            "Content-Type": "application/json"
        }
        self.test_results = []
    
    def get_upcoming_matches(self, league_id: int = 39, limit: int = 5) -> List[Dict]:
        """Get upcoming matches for testing"""
        
        try:
            url = f"{self.base_url}/matches/upcoming"
            params = {"league_id": league_id, "limit": limit}
            
            response = requests.get(url, headers=self.headers, params=params)
            
            if response.status_code == 200:
                data = response.json()
                return data.get('matches', [])
            else:
                logger.error(f"Failed to get matches: {response.status_code}")
                return []
                
        except Exception as e:
            logger.error(f"Error getting matches: {e}")
            return []
    
    def test_single_prediction(self, match_id: int, test_name: str = "") -> Dict[str, Any]:
        """Test prediction for a single match"""
        
        logger.info(f"Testing prediction for match {match_id} {test_name}")
        
        start_time = time.time()
        
        try:
            url = f"{self.base_url}/predict"
            payload = {"match_id": match_id, "include_analysis": True}
            
            response = requests.post(url, headers=self.headers, json=payload)
            
            response_time = time.time() - start_time
            
            if response.status_code == 200:
                data = response.json()
                
                # Extract key metrics
                ml_prediction = data.get('comprehensive_analysis', {}).get('ml_prediction', {})
                match_info = data.get('match_info', {})
                
                result = {
                    'match_id': match_id,
                    'test_name': test_name,
                    'status': 'SUCCESS',
                    'response_time': round(response_time, 2),
                    'match_info': {
                        'home_team': match_info.get('home_team'),
                        'away_team': match_info.get('away_team'),
                        'league': match_info.get('league'),
                        'date': match_info.get('date')
                    },
                    'ml_prediction': {
                        'confidence': ml_prediction.get('confidence'),
                        'model_type': ml_prediction.get('model_type'),
                        'probabilities': ml_prediction.get('probabilities', {}),
                        'predicted_outcome': max(ml_prediction.get('probabilities', {}), 
                                               key=ml_prediction.get('probabilities', {}).get) if ml_prediction.get('probabilities') else None
                    },
                    'ai_analysis': {
                        'has_analysis': 'ai_verdict' in data.get('comprehensive_analysis', {}),
                        'recommended_outcome': data.get('comprehensive_analysis', {}).get('ai_verdict', {}).get('recommended_outcome'),
                        'confidence_level': data.get('comprehensive_analysis', {}).get('ai_verdict', {}).get('confidence_level')
                    }
                }
                
                logger.info(f"✅ Prediction successful: {match_info.get('home_team')} vs {match_info.get('away_team')} - Confidence: {ml_prediction.get('confidence')}")
                return result
                
            else:
                logger.error(f"❌ Prediction failed: {response.status_code} - {response.text}")
                return {
                    'match_id': match_id,
                    'test_name': test_name,
                    'status': 'FAILED',
                    'error': f"HTTP {response.status_code}: {response.text}",
                    'response_time': round(response_time, 2)
                }
                
        except Exception as e:
            logger.error(f"❌ Error testing match {match_id}: {e}")
            return {
                'match_id': match_id,
                'test_name': test_name,
                'status': 'ERROR',
                'error': str(e),
                'response_time': 0
            }
    
    def test_prediction_consistency(self, match_id: int, num_tests: int = 3) -> Dict[str, Any]:
        """Test if predictions are consistent for the same match"""
        
        logger.info(f"Testing prediction consistency for match {match_id} ({num_tests} calls)")
        
        results = []
        for i in range(num_tests):
            result = self.test_single_prediction(match_id, f"consistency_test_{i+1}")
            if result['status'] == 'SUCCESS':
                results.append(result['ml_prediction'])
            time.sleep(0.5)  # Small delay between calls
        
        if len(results) < 2:
            return {'status': 'INSUFFICIENT_DATA', 'results': results}
        
        # Check consistency
        first_prediction = results[0]
        all_consistent = True
        
        for result in results[1:]:
            if (result['confidence'] != first_prediction['confidence'] or 
                result['probabilities'] != first_prediction['probabilities']):
                all_consistent = False
                break
        
        return {
            'match_id': match_id,
            'status': 'CONSISTENT' if all_consistent else 'INCONSISTENT',
            'num_tests': len(results),
            'results': results,
            'first_confidence': first_prediction.get('confidence'),
            'first_probabilities': first_prediction.get('probabilities')
        }
    
    def test_multiple_matches(self, match_ids: List[int]) -> Dict[str, Any]:
        """Test predictions for multiple matches and analyze patterns"""
        
        logger.info(f"Testing {len(match_ids)} different matches for uniqueness")
        
        results = []
        unique_predictions = set()
        
        for match_id in match_ids:
            result = self.test_single_prediction(match_id, f"uniqueness_test")
            if result['status'] == 'SUCCESS':
                results.append(result)
                
                # Create signature for uniqueness check
                ml_pred = result['ml_prediction']
                signature = (
                    ml_pred.get('confidence'),
                    tuple(sorted(ml_pred.get('probabilities', {}).items()))
                )
                unique_predictions.add(signature)
        
        return {
            'total_matches_tested': len(results),
            'unique_predictions': len(unique_predictions),
            'uniqueness_ratio': len(unique_predictions) / len(results) if results else 0,
            'is_dynamic': len(unique_predictions) > 1,
            'results': results
        }
    
    def run_comprehensive_test(self) -> Dict[str, Any]:
        """Run the complete test suite"""
        
        logger.info("🚀 Starting Comprehensive Prediction Flow Test")
        test_start = time.time()
        
        # Get test matches
        matches = self.get_upcoming_matches(league_id=39, limit=6)
        if len(matches) < 3:
            logger.warning("Not enough matches found, getting from multiple leagues")
            matches.extend(self.get_upcoming_matches(league_id=140, limit=3))  # La Liga
            matches.extend(self.get_upcoming_matches(league_id=135, limit=3))  # Serie A
        
        match_ids = [m['match_id'] for m in matches[:5]]
        
        if not match_ids:
            return {'error': 'No matches found for testing'}
        
        logger.info(f"Testing with {len(match_ids)} matches: {match_ids}")
        
        # Test Suite
        test_results = {
            'test_timestamp': datetime.now().isoformat(),
            'test_duration': 0,
            'match_ids_tested': match_ids,
            'tests': {}
        }
        
        # Test 1: Single prediction functionality
        logger.info("📋 Test 1: Single Prediction Functionality")
        single_test = self.test_single_prediction(match_ids[0], "functionality_test")
        test_results['tests']['single_prediction'] = single_test
        
        # Test 2: Prediction consistency (same match, multiple calls)
        logger.info("📋 Test 2: Prediction Consistency")
        consistency_test = self.test_prediction_consistency(match_ids[0], num_tests=3)
        test_results['tests']['consistency'] = consistency_test
        
        # Test 3: Multiple matches uniqueness
        logger.info("📋 Test 3: Multiple Matches Uniqueness")
        uniqueness_test = self.test_multiple_matches(match_ids)
        test_results['tests']['uniqueness'] = uniqueness_test
        
        # Test 4: Performance analysis
        logger.info("📋 Test 4: Performance Analysis")
        response_times = []
        for result in uniqueness_test['results']:
            if 'response_time' in result:
                response_times.append(result['response_time'])
        
        test_results['tests']['performance'] = {
            'avg_response_time': sum(response_times) / len(response_times) if response_times else 0,
            'max_response_time': max(response_times) if response_times else 0,
            'min_response_time': min(response_times) if response_times else 0,
            'total_calls': len(response_times)
        }
        
        test_results['test_duration'] = round(time.time() - test_start, 2)
        
        return test_results
    
    def print_test_summary(self, results: Dict[str, Any]):
        """Print a formatted test summary"""
        
        print("\n" + "="*60)
        print("🧪 BETGENIUS AI PREDICTION FLOW TEST RESULTS")
        print("="*60)
        
        print(f"📅 Test Date: {results.get('test_timestamp', 'Unknown')}")
        print(f"⏱️  Total Duration: {results.get('test_duration', 0)}s")
        print(f"🎯 Matches Tested: {len(results.get('match_ids_tested', []))}")
        
        tests = results.get('tests', {})
        
        # Single Prediction Test
        if 'single_prediction' in tests:
            single = tests['single_prediction']
            print(f"\n📋 Single Prediction Test:")
            print(f"   Status: {'✅ PASSED' if single.get('status') == 'SUCCESS' else '❌ FAILED'}")
            if single.get('status') == 'SUCCESS':
                ml_pred = single.get('ml_prediction', {})
                print(f"   Match: {single.get('match_info', {}).get('home_team')} vs {single.get('match_info', {}).get('away_team')}")
                print(f"   Confidence: {ml_pred.get('confidence')}")
                print(f"   Probabilities: {ml_pred.get('probabilities')}")
        
        # Consistency Test
        if 'consistency' in tests:
            consistency = tests['consistency']
            print(f"\n📋 Consistency Test:")
            print(f"   Status: {'✅ CONSISTENT' if consistency.get('status') == 'CONSISTENT' else '⚠️  INCONSISTENT'}")
            print(f"   Tests Run: {consistency.get('num_tests', 0)}")
            if consistency.get('first_confidence'):
                print(f"   Reference Confidence: {consistency.get('first_confidence')}")
        
        # Uniqueness Test
        if 'uniqueness' in tests:
            uniqueness = tests['uniqueness']
            print(f"\n📋 Uniqueness Test:")
            print(f"   Status: {'✅ DYNAMIC' if uniqueness.get('is_dynamic') else '❌ STATIC'}")
            print(f"   Matches Tested: {uniqueness.get('total_matches_tested', 0)}")
            print(f"   Unique Predictions: {uniqueness.get('unique_predictions', 0)}")
            print(f"   Uniqueness Ratio: {uniqueness.get('uniqueness_ratio', 0):.2%}")
        
        # Performance Test
        if 'performance' in tests:
            perf = tests['performance']
            print(f"\n📋 Performance Test:")
            print(f"   Average Response Time: {perf.get('avg_response_time', 0):.2f}s")
            print(f"   Max Response Time: {perf.get('max_response_time', 0):.2f}s")
            print(f"   Min Response Time: {perf.get('min_response_time', 0):.2f}s")
        
        print("\n" + "="*60)
        
        # Overall Assessment
        all_passed = (
            tests.get('single_prediction', {}).get('status') == 'SUCCESS' and
            tests.get('consistency', {}).get('status') == 'CONSISTENT' and
            tests.get('uniqueness', {}).get('is_dynamic', False)
        )
        
        print(f"🏆 OVERALL ASSESSMENT: {'✅ ALL TESTS PASSED' if all_passed else '⚠️  SOME ISSUES DETECTED'}")
        print("="*60)

def main():
    """Run the comprehensive test"""
    
    tester = PredictionFlowTester()
    
    try:
        results = tester.run_comprehensive_test()
        
        # Save results
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"prediction_flow_test_{timestamp}.json"
        
        with open(filename, 'w') as f:
            json.dump(results, f, indent=2)
        
        # Print summary
        tester.print_test_summary(results)
        
        print(f"\n💾 Detailed results saved to: {filename}")
        
        return results
        
    except Exception as e:
        logger.error(f"Test failed: {e}")
        return {'error': str(e)}

if __name__ == "__main__":
    main()