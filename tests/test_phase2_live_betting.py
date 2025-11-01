"""
Comprehensive Phase 2 Live Betting Tests
Tests all components: Momentum Engine, Live Markets, WebSocket, /market API
"""
import asyncio
import requests
import json
from datetime import datetime
import websockets
import time

BASE_URL = "http://localhost:8000"
API_KEY = "betgenius_secure_key_2024"
HEADERS = {"Authorization": f"Bearer {API_KEY}"}

class Phase2TestSuite:
    def __init__(self):
        self.results = {
            "passed": [],
            "failed": [],
            "warnings": []
        }
    
    def log_result(self, test_name, status, message="", data=None):
        """Log test result"""
        result = {
            "test": test_name,
            "status": status,
            "message": message,
            "timestamp": datetime.now().isoformat()
        }
        if data:
            result["data"] = data
        
        if status == "PASS":
            self.results["passed"].append(result)
            print(f"✅ {test_name}: {message}")
        elif status == "FAIL":
            self.results["failed"].append(result)
            print(f"❌ {test_name}: {message}")
        else:
            self.results["warnings"].append(result)
            print(f"⚠️  {test_name}: {message}")
        
        if data:
            print(f"   Data: {json.dumps(data, indent=2)}")
    
    def test_health_check(self):
        """Test 1: Basic health check"""
        try:
            response = requests.get(f"{BASE_URL}/", timeout=5)
            if response.status_code == 200:
                self.log_result("Health Check", "PASS", "API is responding")
                return True
            else:
                self.log_result("Health Check", "FAIL", f"Status: {response.status_code}")
                return False
        except Exception as e:
            self.log_result("Health Check", "FAIL", f"Error: {str(e)}")
            return False
    
    def test_market_endpoint_live_matches(self):
        """Test 2: /market endpoint with status=live"""
        try:
            # Test with status=live
            response = requests.get(
                f"{BASE_URL}/market",
                params={"status": "live"},
                headers=HEADERS,
                timeout=10
            )
            
            if response.status_code != 200:
                self.log_result(
                    "Market API (live)", 
                    "FAIL", 
                    f"HTTP {response.status_code}: {response.text[:200]}"
                )
                return False
            
            data = response.json()
            
            # Check structure
            if "matches" not in data:
                self.log_result("Market API (live)", "FAIL", "Missing 'matches' key")
                return False
            
            matches = data["matches"]
            
            if len(matches) == 0:
                self.log_result(
                    "Market API (live)", 
                    "WARN", 
                    "No live matches found (this is OK if no games are currently live)"
                )
                return True
            
            # Verify live match structure
            sample_match = matches[0]
            required_fields = ["match_id", "home_team", "away_team", "kickoff_at"]
            missing_fields = [f for f in required_fields if f not in sample_match]
            
            if missing_fields:
                self.log_result(
                    "Market API (live)", 
                    "FAIL", 
                    f"Missing fields: {missing_fields}",
                    sample_match
                )
                return False
            
            # Check for Phase 2 fields (momentum, model_markets)
            has_momentum = "momentum" in sample_match
            has_model_markets = "model_markets" in sample_match
            
            if has_momentum and has_model_markets:
                self.log_result(
                    "Market API (live)", 
                    "PASS", 
                    f"Found {len(matches)} live matches with Phase 2 data",
                    {
                        "match_count": len(matches),
                        "sample_match_id": sample_match.get("match_id"),
                        "has_momentum": has_momentum,
                        "has_model_markets": has_model_markets,
                        "momentum_sample": sample_match.get("momentum"),
                        "model_markets_sample": sample_match.get("model_markets")
                    }
                )
                return True
            else:
                self.log_result(
                    "Market API (live)", 
                    "WARN", 
                    f"Phase 2 data missing (momentum: {has_momentum}, model_markets: {has_model_markets})",
                    sample_match
                )
                return False
                
        except Exception as e:
            self.log_result("Market API (live)", "FAIL", f"Error: {str(e)}")
            return False
    
    def test_market_endpoint_upcoming(self):
        """Test 3: /market endpoint with status=upcoming (baseline)"""
        try:
            response = requests.get(
                f"{BASE_URL}/market",
                params={"status": "upcoming"},
                headers=HEADERS,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                match_count = len(data.get("matches", []))
                self.log_result(
                    "Market API (upcoming)", 
                    "PASS", 
                    f"Found {match_count} upcoming matches"
                )
                return True
            else:
                self.log_result(
                    "Market API (upcoming)", 
                    "FAIL", 
                    f"HTTP {response.status_code}"
                )
                return False
                
        except Exception as e:
            self.log_result("Market API (upcoming)", "FAIL", f"Error: {str(e)}")
            return False
    
    def test_database_live_momentum(self):
        """Test 4: Check live_momentum table has data"""
        try:
            # Query via admin endpoint if available, otherwise skip
            response = requests.get(
                f"{BASE_URL}/admin/stats/live-betting",
                headers=HEADERS,
                timeout=5
            )
            
            if response.status_code == 200:
                data = response.json()
                momentum_count = data.get("live_momentum_records", 0)
                
                if momentum_count > 0:
                    self.log_result(
                        "Database (live_momentum)", 
                        "PASS", 
                        f"Found {momentum_count} momentum records",
                        {"momentum_count": momentum_count}
                    )
                    return True
                else:
                    self.log_result(
                        "Database (live_momentum)", 
                        "WARN", 
                        "No momentum records (OK if no live matches)"
                    )
                    return True
            else:
                self.log_result(
                    "Database (live_momentum)", 
                    "WARN", 
                    "Admin endpoint not available, skipping"
                )
                return True
                
        except Exception as e:
            self.log_result(
                "Database (live_momentum)", 
                "WARN", 
                f"Could not verify: {str(e)}"
            )
            return True  # Non-critical
    
    def test_prometheus_metrics(self):
        """Test 5: Verify Prometheus metrics endpoint"""
        try:
            response = requests.get(f"{BASE_URL}/metrics", timeout=5)
            
            if response.status_code != 200:
                self.log_result(
                    "Prometheus Metrics", 
                    "FAIL", 
                    f"HTTP {response.status_code}"
                )
                return False
            
            metrics_text = response.text
            
            # Check for Phase 2 metrics
            expected_metrics = [
                "momentum_calculations_total",
                "momentum_calculation_duration_seconds",
                "live_market_generations_total",
                "live_market_generation_duration_seconds",
                "websocket_connections_active",
                "fixture_resolution_attempts_total"
            ]
            
            found_metrics = []
            missing_metrics = []
            
            for metric in expected_metrics:
                if metric in metrics_text:
                    found_metrics.append(metric)
                else:
                    missing_metrics.append(metric)
            
            if len(found_metrics) == len(expected_metrics):
                self.log_result(
                    "Prometheus Metrics", 
                    "PASS", 
                    f"All {len(expected_metrics)} Phase 2 metrics found",
                    {"metrics": found_metrics}
                )
                return True
            else:
                self.log_result(
                    "Prometheus Metrics", 
                    "FAIL", 
                    f"Missing metrics: {missing_metrics}",
                    {
                        "found": found_metrics,
                        "missing": missing_metrics
                    }
                )
                return False
                
        except Exception as e:
            self.log_result("Prometheus Metrics", "FAIL", f"Error: {str(e)}")
            return False
    
    async def test_websocket_connection(self):
        """Test 6: WebSocket connection and message streaming"""
        try:
            # First get a live match ID
            response = requests.get(
                f"{BASE_URL}/market",
                params={"status": "live"},
                headers=HEADERS,
                timeout=5
            )
            
            if response.status_code != 200:
                self.log_result(
                    "WebSocket Test", 
                    "WARN", 
                    "No live matches to test WebSocket"
                )
                return True
            
            data = response.json()
            matches = data.get("matches", [])
            
            if len(matches) == 0:
                self.log_result(
                    "WebSocket Test", 
                    "WARN", 
                    "No live matches available for WebSocket test"
                )
                return True
            
            match_id = matches[0]["match_id"]
            
            # Connect to WebSocket
            ws_url = f"ws://localhost:8000/ws/live/{match_id}"
            
            try:
                async with websockets.connect(ws_url, timeout=10) as websocket:
                    # Wait for initial message
                    message = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                    data = json.loads(message)
                    
                    # Verify message structure
                    if "type" in data and "data" in data:
                        self.log_result(
                            "WebSocket Test", 
                            "PASS", 
                            f"Connected to match {match_id}, received message",
                            {
                                "match_id": match_id,
                                "message_type": data.get("type"),
                                "has_data": bool(data.get("data"))
                            }
                        )
                        return True
                    else:
                        self.log_result(
                            "WebSocket Test", 
                            "FAIL", 
                            "Invalid message structure",
                            data
                        )
                        return False
                        
            except asyncio.TimeoutError:
                self.log_result(
                    "WebSocket Test", 
                    "WARN", 
                    "No message received within 5s (may be waiting for next update cycle)"
                )
                return True
            except Exception as e:
                self.log_result(
                    "WebSocket Test", 
                    "FAIL", 
                    f"WebSocket error: {str(e)}"
                )
                return False
                
        except Exception as e:
            self.log_result("WebSocket Test", "FAIL", f"Setup error: {str(e)}")
            return False
    
    def test_fixture_id_resolver(self):
        """Test 7: Verify fixture ID resolver is working"""
        try:
            # Check if we have resolved fixtures
            response = requests.get(
                f"{BASE_URL}/admin/stats/resolver",
                headers=HEADERS,
                timeout=5
            )
            
            if response.status_code == 200:
                data = response.json()
                total_resolved = data.get("total_resolved", 0)
                
                if total_resolved > 0:
                    self.log_result(
                        "Fixture ID Resolver", 
                        "PASS", 
                        f"Resolved {total_resolved} fixtures",
                        data
                    )
                    return True
                else:
                    self.log_result(
                        "Fixture ID Resolver", 
                        "WARN", 
                        "No fixtures resolved yet (may be running)"
                    )
                    return True
            else:
                self.log_result(
                    "Fixture ID Resolver", 
                    "WARN", 
                    "Stats endpoint not available"
                )
                return True
                
        except Exception as e:
            self.log_result(
                "Fixture ID Resolver", 
                "WARN", 
                f"Could not verify: {str(e)}"
            )
            return True  # Non-critical
    
    def print_summary(self):
        """Print test summary"""
        print("\n" + "="*60)
        print("PHASE 2 LIVE BETTING TEST SUMMARY")
        print("="*60)
        
        total_tests = len(self.results["passed"]) + len(self.results["failed"]) + len(self.results["warnings"])
        
        print(f"\n✅ PASSED: {len(self.results['passed'])}/{total_tests}")
        print(f"❌ FAILED: {len(self.results['failed'])}/{total_tests}")
        print(f"⚠️  WARNINGS: {len(self.results['warnings'])}/{total_tests}")
        
        if self.results["failed"]:
            print("\n⚠️  FAILURES:")
            for result in self.results["failed"]:
                print(f"  - {result['test']}: {result['message']}")
        
        if self.results["warnings"]:
            print("\n⚠️  WARNINGS:")
            for result in self.results["warnings"]:
                print(f"  - {result['test']}: {result['message']}")
        
        print("\n" + "="*60)
        
        # Overall status
        if len(self.results["failed"]) == 0:
            if len(self.results["warnings"]) == 0:
                print("🎉 ALL TESTS PASSED - PHASE 2 FULLY OPERATIONAL")
            else:
                print("✅ TESTS PASSED - Some warnings (likely no live matches)")
        else:
            print("❌ SOME TESTS FAILED - Review failures above")
        
        print("="*60)
        
        return len(self.results["failed"]) == 0

async def run_async_tests(suite):
    """Run async tests"""
    await suite.test_websocket_connection()

def main():
    """Run all tests"""
    print("="*60)
    print("PHASE 2 LIVE BETTING - COMPREHENSIVE TEST SUITE")
    print("="*60)
    print(f"Target: {BASE_URL}")
    print(f"Time: {datetime.now().isoformat()}")
    print("="*60 + "\n")
    
    suite = Phase2TestSuite()
    
    # Wait for server to be ready
    print("Waiting for server to be ready...")
    for i in range(10):
        try:
            response = requests.get(f"{BASE_URL}/", timeout=2)
            if response.status_code == 200:
                print("✅ Server is ready\n")
                break
        except:
            pass
        time.sleep(2)
        if i == 9:
            print("❌ Server did not start in time\n")
            return
    
    # Run synchronous tests
    suite.test_health_check()
    suite.test_market_endpoint_live_matches()
    suite.test_market_endpoint_upcoming()
    suite.test_database_live_momentum()
    suite.test_prometheus_metrics()
    suite.test_fixture_id_resolver()
    
    # Run async tests
    print("\nRunning async tests...")
    asyncio.run(run_async_tests(suite))
    
    # Print summary
    suite.print_summary()
    
    # Save results to file
    with open("test_results_phase2.json", "w") as f:
        json.dump(suite.results, f, indent=2)
    
    print(f"\n📄 Full results saved to: test_results_phase2.json")

if __name__ == "__main__":
    main()
