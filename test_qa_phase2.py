#!/usr/bin/env python3
"""
Comprehensive QA Test Suite for Phase 2 TBD Auto-Enrichment
Tests /market and /teams APIs with detailed validation
"""
import requests
import json
import time
from typing import Dict, List, Any

BASE_URL = "http://localhost:8000"
API_KEY = "betgenius_secure_key_2024"
HEADERS = {"Authorization": f"Bearer {API_KEY}"}

class TestResults:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.warnings = 0
        self.tests = []
    
    def add_pass(self, test_name: str, details: str = ""):
        self.passed += 1
        self.tests.append({"name": test_name, "status": "PASS", "details": details})
        print(f"✅ PASS: {test_name}")
        if details:
            print(f"   → {details}")
    
    def add_fail(self, test_name: str, details: str):
        self.failed += 1
        self.tests.append({"name": test_name, "status": "FAIL", "details": details})
        print(f"❌ FAIL: {test_name}")
        print(f"   → {details}")
    
    def add_warning(self, test_name: str, details: str):
        self.warnings += 1
        self.tests.append({"name": test_name, "status": "WARN", "details": details})
        print(f"⚠️  WARN: {test_name}")
        print(f"   → {details}")
    
    def summary(self):
        total = self.passed + self.failed + self.warnings
        print(f"\n{'='*60}")
        print(f"TEST SUMMARY")
        print(f"{'='*60}")
        print(f"Total Tests: {total}")
        print(f"✅ Passed: {self.passed} ({self.passed/total*100:.1f}%)")
        print(f"❌ Failed: {self.failed} ({self.failed/total*100:.1f}%)")
        print(f"⚠️  Warnings: {self.warnings} ({self.warnings/total*100:.1f}%)")
        print(f"{'='*60}")
        return self.failed == 0

results = TestResults()

def test_market_basic_functionality():
    """Test 1: /market basic functionality"""
    print("\n" + "="*60)
    print("TEST SUITE 1: /market API Basic Functionality")
    print("="*60)
    
    # Test 1.1: Basic request
    try:
        response = requests.get(f"{BASE_URL}/market", headers=HEADERS)
        if response.status_code == 200:
            results.add_pass("Market API returns 200 OK")
        else:
            results.add_fail("Market API returns 200 OK", f"Got status {response.status_code}")
    except Exception as e:
        results.add_fail("Market API returns 200 OK", str(e))
    
    # Test 1.2: Response structure
    try:
        data = response.json()
        required_fields = ["matches", "total_count", "timestamp"]
        missing = [f for f in required_fields if f not in data]
        if not missing:
            results.add_pass("Market response has required fields", f"Fields: {', '.join(required_fields)}")
        else:
            results.add_fail("Market response has required fields", f"Missing: {', '.join(missing)}")
    except Exception as e:
        results.add_fail("Market response has required fields", str(e))
    
    # Test 1.3: Match structure validation
    try:
        matches = data.get("matches", [])
        if matches:
            match = matches[0]
            required_match_fields = ["match_id", "league", "kickoff_at", "home", "away", "odds", "models"]
            missing = [f for f in required_match_fields if f not in match]
            if not missing:
                results.add_pass("Match objects have required fields", f"{len(matches)} matches validated")
            else:
                results.add_fail("Match objects have required fields", f"Missing: {', '.join(missing)}")
        else:
            results.add_warning("Match objects have required fields", "No matches returned")
    except Exception as e:
        results.add_fail("Match objects have required fields", str(e))
    
    # Test 1.4: Team structure validation
    try:
        if matches:
            match = matches[0]
            home = match.get("home", {})
            away = match.get("away", {})
            required_team_fields = ["name", "team_id", "logo_url"]
            
            home_missing = [f for f in required_team_fields if f not in home]
            away_missing = [f for f in required_team_fields if f not in away]
            
            if not home_missing and not away_missing:
                results.add_pass("Team objects have required fields", "home and away teams validated")
            else:
                missing = []
                if home_missing:
                    missing.append(f"home: {', '.join(home_missing)}")
                if away_missing:
                    missing.append(f"away: {', '.join(away_missing)}")
                results.add_fail("Team objects have required fields", "; ".join(missing))
    except Exception as e:
        results.add_fail("Team objects have required fields", str(e))

def test_market_team_linkage():
    """Test 2: /market team linkage and logo display"""
    print("\n" + "="*60)
    print("TEST SUITE 2: /market Team Linkage & Logo Display")
    print("="*60)
    
    try:
        response = requests.get(f"{BASE_URL}/market?limit=20", headers=HEADERS)
        data = response.json()
        matches = data.get("matches", [])
        
        # Test 2.1: No TBD fixtures
        tbd_count = 0
        for match in matches:
            home_name = match.get("home", {}).get("name", "")
            away_name = match.get("away", {}).get("name", "")
            if "TBD" in home_name or "TBD" in away_name:
                tbd_count += 1
        
        if tbd_count == 0:
            results.add_pass("No TBD fixtures in upcoming matches", f"Checked {len(matches)} matches")
        else:
            results.add_fail("No TBD fixtures in upcoming matches", f"Found {tbd_count} TBD matches")
        
        # Test 2.2: All matches have team_id linkage
        unlinked_count = 0
        for match in matches:
            home_id = match.get("home", {}).get("team_id")
            away_id = match.get("away", {}).get("team_id")
            if not home_id or not away_id:
                unlinked_count += 1
        
        if unlinked_count == 0:
            results.add_pass("All matches have team_id linkage", f"{len(matches)} matches fully linked")
        else:
            results.add_fail("All matches have team_id linkage", f"{unlinked_count} matches missing team_ids")
        
        # Test 2.3: Logo coverage analysis
        matches_with_logos = 0
        teams_with_logos = 0
        total_teams = 0
        
        for match in matches:
            home_logo = match.get("home", {}).get("logo_url")
            away_logo = match.get("away", {}).get("logo_url")
            
            if home_logo or away_logo:
                matches_with_logos += 1
            if home_logo:
                teams_with_logos += 1
            if away_logo:
                teams_with_logos += 1
            total_teams += 2
        
        logo_coverage = (teams_with_logos / total_teams * 100) if total_teams > 0 else 0
        match_coverage = (matches_with_logos / len(matches) * 100) if matches else 0
        
        if logo_coverage >= 10:
            results.add_pass("Logo coverage acceptable", f"{logo_coverage:.1f}% teams, {match_coverage:.1f}% matches")
        elif logo_coverage > 0:
            results.add_warning("Logo coverage low", f"{logo_coverage:.1f}% teams have logos")
        else:
            results.add_fail("Logo coverage acceptable", "No logos found in any matches")
        
    except Exception as e:
        results.add_fail("Team linkage validation", str(e))

def test_market_query_params():
    """Test 3: /market query parameters"""
    print("\n" + "="*60)
    print("TEST SUITE 3: /market Query Parameters")
    print("="*60)
    
    # Test 3.1: Limit parameter
    try:
        response = requests.get(f"{BASE_URL}/market?limit=5", headers=HEADERS)
        data = response.json()
        matches = data.get("matches", [])
        if len(matches) <= 5:
            results.add_pass("Limit parameter works", f"Requested 5, got {len(matches)}")
        else:
            results.add_fail("Limit parameter works", f"Requested 5, got {len(matches)}")
    except Exception as e:
        results.add_fail("Limit parameter works", str(e))
    
    # Test 3.2: League filter
    try:
        response = requests.get(f"{BASE_URL}/market?league_id=39", headers=HEADERS)
        data = response.json()
        matches = data.get("matches", [])
        
        if matches:
            wrong_league = [m for m in matches if m.get("league", {}).get("id") != 39]
            if not wrong_league:
                results.add_pass("League filter works", f"All {len(matches)} matches from league 39")
            else:
                results.add_fail("League filter works", f"{len(wrong_league)} matches from wrong league")
        else:
            results.add_warning("League filter works", "No matches found for league 39")
    except Exception as e:
        results.add_fail("League filter works", str(e))

def test_teams_api():
    """Test 4: /teams API functionality"""
    print("\n" + "="*60)
    print("TEST SUITE 4: /teams API Functionality")
    print("="*60)
    
    # Test 4.1: Basic request
    try:
        response = requests.get(f"{BASE_URL}/teams", headers=HEADERS)
        if response.status_code == 200:
            results.add_pass("Teams API returns 200 OK")
        else:
            results.add_fail("Teams API returns 200 OK", f"Got status {response.status_code}")
    except Exception as e:
        results.add_fail("Teams API returns 200 OK", str(e))
    
    # Test 4.2: Response structure
    try:
        data = response.json()
        required_fields = ["teams", "count"]
        missing = [f for f in required_fields if f not in data]
        if not missing:
            results.add_pass("Teams response has required fields")
        else:
            results.add_fail("Teams response has required fields", f"Missing: {', '.join(missing)}")
    except Exception as e:
        results.add_fail("Teams response has required fields", str(e))
    
    # Test 4.3: Team object structure
    try:
        teams = data.get("teams", [])
        if teams:
            team = teams[0]
            required_team_fields = ["team_id", "name", "logo_url", "country", "slug"]
            missing = [f for f in required_team_fields if f not in team]
            if not missing:
                results.add_pass("Team objects have required fields", f"{len(teams)} teams validated")
            else:
                results.add_fail("Team objects have required fields", f"Missing: {', '.join(missing)}")
        else:
            results.add_fail("Team objects have required fields", "No teams returned")
    except Exception as e:
        results.add_fail("Team objects have required fields", str(e))
    
    # Test 4.4: Search functionality
    try:
        response = requests.get(f"{BASE_URL}/teams?search=Manchester", headers=HEADERS)
        data = response.json()
        teams = data.get("teams", [])
        
        if teams:
            # Check all teams contain "Manchester"
            non_matching = [t for t in teams if "manchester" not in t.get("name", "").lower()]
            if not non_matching:
                results.add_pass("Team name search works", f"Found {len(teams)} Manchester teams")
            else:
                results.add_fail("Team name search works", f"{len(non_matching)} teams don't match search")
        else:
            results.add_warning("Team name search works", "No teams found for 'Manchester'")
    except Exception as e:
        results.add_fail("Team name search works", str(e))
    
    # Test 4.5: Logo availability filter
    try:
        response = requests.get(f"{BASE_URL}/teams?has_logo=true&limit=20", headers=HEADERS)
        data = response.json()
        teams = data.get("teams", [])
        
        if teams:
            without_logo = [t for t in teams if not t.get("logo_url")]
            if not without_logo:
                results.add_pass("Logo filter works", f"All {len(teams)} teams have logos")
            else:
                results.add_fail("Logo filter works", f"{len(without_logo)} teams missing logos")
        else:
            results.add_warning("Logo filter works", "No teams with logos found")
    except Exception as e:
        results.add_fail("Logo filter works", str(e))

def test_authentication():
    """Test 5: Authentication and security"""
    print("\n" + "="*60)
    print("TEST SUITE 5: Authentication & Security")
    print("="*60)
    
    # Test 5.1: Missing auth header
    try:
        response = requests.get(f"{BASE_URL}/market")
        if response.status_code in [401, 403]:
            results.add_pass("Missing auth blocked (401/403)", "Unauthorized access blocked")
        else:
            results.add_fail("Missing auth blocked", f"Got status {response.status_code}")
    except Exception as e:
        results.add_fail("Missing auth blocked", str(e))
    
    # Test 5.2: Invalid API key
    try:
        bad_headers = {"Authorization": "Bearer invalid_key_12345"}
        response = requests.get(f"{BASE_URL}/market", headers=bad_headers)
        if response.status_code in [401, 403]:
            results.add_pass("Invalid API key blocked (401/403)", "Bad credentials rejected")
        else:
            results.add_fail("Invalid API key blocked", f"Got status {response.status_code}")
    except Exception as e:
        results.add_fail("Invalid API key blocked", str(e))

def test_performance():
    """Test 6: Performance validation"""
    print("\n" + "="*60)
    print("TEST SUITE 6: Performance Validation")
    print("="*60)
    
    # Test 6.1: /market response time
    try:
        start = time.time()
        response = requests.get(f"{BASE_URL}/market?limit=10", headers=HEADERS)
        duration = (time.time() - start) * 1000  # ms
        
        if duration < 1000:
            results.add_pass("Market API response time < 1s", f"{duration:.0f}ms")
        elif duration < 2000:
            results.add_warning("Market API response time slow", f"{duration:.0f}ms (target: <1000ms)")
        else:
            results.add_fail("Market API response time acceptable", f"{duration:.0f}ms (too slow)")
    except Exception as e:
        results.add_fail("Market API response time", str(e))
    
    # Test 6.2: /teams response time
    try:
        start = time.time()
        response = requests.get(f"{BASE_URL}/teams?limit=50", headers=HEADERS)
        duration = (time.time() - start) * 1000  # ms
        
        if duration < 500:
            results.add_pass("Teams API response time < 500ms", f"{duration:.0f}ms")
        elif duration < 1000:
            results.add_warning("Teams API response time slow", f"{duration:.0f}ms (target: <500ms)")
        else:
            results.add_fail("Teams API response time acceptable", f"{duration:.0f}ms (too slow)")
    except Exception as e:
        results.add_fail("Teams API response time", str(e))

def test_data_quality():
    """Test 7: Data quality validation"""
    print("\n" + "="*60)
    print("TEST SUITE 7: Data Quality Validation")
    print("="*60)
    
    # Test 7.1: Valid URLs for logos
    try:
        response = requests.get(f"{BASE_URL}/teams?has_logo=true&limit=20", headers=HEADERS)
        data = response.json()
        teams = data.get("teams", [])
        
        invalid_urls = []
        for team in teams:
            logo_url = team.get("logo_url")
            if logo_url and not (logo_url.startswith("http://") or logo_url.startswith("https://")):
                invalid_urls.append(f"{team.get('name')}: {logo_url}")
        
        if not invalid_urls:
            results.add_pass("Logo URLs are valid", f"Checked {len(teams)} teams")
        else:
            results.add_fail("Logo URLs are valid", f"{len(invalid_urls)} invalid URLs found")
    except Exception as e:
        results.add_fail("Logo URLs are valid", str(e))
    
    # Test 7.2: Team names are non-empty
    try:
        response = requests.get(f"{BASE_URL}/market?limit=20", headers=HEADERS)
        data = response.json()
        matches = data.get("matches", [])
        
        empty_names = 0
        for match in matches:
            home_name = match.get("home", {}).get("name", "")
            away_name = match.get("away", {}).get("name", "")
            if not home_name.strip() or not away_name.strip():
                empty_names += 1
        
        if empty_names == 0:
            results.add_pass("All team names are non-empty", f"Checked {len(matches)*2} teams")
        else:
            results.add_fail("All team names are non-empty", f"Found {empty_names} empty names")
    except Exception as e:
        results.add_fail("All team names are non-empty", str(e))
    
    # Test 7.3: Kickoff times are in future
    try:
        response = requests.get(f"{BASE_URL}/market?limit=20", headers=HEADERS)
        data = response.json()
        matches = data.get("matches", [])
        
        from datetime import datetime
        now = datetime.utcnow()
        past_matches = 0
        
        for match in matches:
            kickoff = match.get("kickoff_at", "")
            if kickoff:
                try:
                    kickoff_dt = datetime.fromisoformat(kickoff.replace("Z", "+00:00"))
                    if kickoff_dt.replace(tzinfo=None) < now:
                        past_matches += 1
                except:
                    pass
        
        if past_matches == 0:
            results.add_pass("All kickoff times are in future", f"Checked {len(matches)} matches")
        else:
            results.add_warning("All kickoff times in future", f"Found {past_matches} past matches")
    except Exception as e:
        results.add_fail("All kickoff times are in future", str(e))

if __name__ == "__main__":
    print("\n" + "="*60)
    print("BETGENIUS AI - PHASE 2 QA TEST SUITE")
    print("Testing /market and /teams APIs")
    print("="*60)
    
    # Run all test suites
    test_market_basic_functionality()
    test_market_team_linkage()
    test_market_query_params()
    test_teams_api()
    test_authentication()
    test_performance()
    test_data_quality()
    
    # Print summary
    success = results.summary()
    
    # Write results to file
    with open("test_results.json", "w") as f:
        json.dump({
            "summary": {
                "total": results.passed + results.failed + results.warnings,
                "passed": results.passed,
                "failed": results.failed,
                "warnings": results.warnings,
                "success_rate": f"{results.passed/(results.passed + results.failed + results.warnings)*100:.1f}%"
            },
            "tests": results.tests
        }, f, indent=2)
    
    print(f"\n📊 Detailed results saved to: test_results.json")
    
    # Exit with appropriate code
    exit(0 if success else 1)
