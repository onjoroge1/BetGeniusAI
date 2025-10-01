#!/usr/bin/env python3
"""
API-Football Odds Exploration Script
Phase 1: Test endpoints, verify data format, and compare bookmaker coverage
"""

import os
import requests
import json
from datetime import datetime, timedelta
import psycopg2
from typing import Dict, List, Any

class APIFootballOddsExplorer:
    """Explore API-Football odds endpoints and capabilities"""
    
    def __init__(self):
        self.rapidapi_key = os.environ.get('RAPIDAPI_KEY')
        self.base_url = "https://api-football-v1.p.rapidapi.com/v3"
        self.headers = {
            "X-RapidAPI-Key": self.rapidapi_key,
            "X-RapidAPI-Host": "api-football-v1.p.rapidapi.com"
        }
        self.database_url = os.environ.get('DATABASE_URL')
    
    def test_bookmakers_endpoint(self) -> Dict[str, Any]:
        """Test /odds/bookmakers endpoint to see available bookmakers"""
        print("\n📚 TESTING BOOKMAKERS ENDPOINT")
        print("=" * 60)
        
        url = f"{self.base_url}/odds/bookmakers"
        
        try:
            response = requests.get(url, headers=self.headers, timeout=30)
            print(f"Status Code: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                bookmakers = data.get('response', [])
                
                print(f"\n✅ Found {len(bookmakers)} bookmakers:")
                print(f"{'ID':<6} {'Name':<30}")
                print("-" * 38)
                
                for book in bookmakers[:20]:  # Show first 20
                    print(f"{book['id']:<6} {book['name']:<30}")
                
                if len(bookmakers) > 20:
                    print(f"... and {len(bookmakers) - 20} more")
                
                return {"success": True, "bookmakers": bookmakers}
            else:
                print(f"❌ Error: {response.status_code}")
                print(f"Response: {response.text}")
                return {"success": False, "error": response.text}
                
        except Exception as e:
            print(f"❌ Request failed: {e}")
            return {"success": False, "error": str(e)}
    
    def test_odds_endpoint_sample(self) -> Dict[str, Any]:
        """Test /odds endpoint with a recent fixture"""
        print("\n🎲 TESTING ODDS ENDPOINT")
        print("=" * 60)
        
        # First, get a recent fixture to test
        fixtures_url = f"{self.base_url}/fixtures"
        
        # Get fixtures from last 7 days
        date_from = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")
        date_to = datetime.utcnow().strftime("%Y-%m-%d")
        
        params = {
            "league": "39",  # Premier League
            "season": "2024",
            "from": date_from,
            "to": date_to,
            "status": "FT"
        }
        
        try:
            # Get sample fixture
            print(f"Fetching recent Premier League fixtures...")
            response = requests.get(fixtures_url, headers=self.headers, params=params, timeout=30)
            
            if response.status_code != 200:
                print(f"❌ Fixtures endpoint failed: {response.status_code}")
                return {"success": False}
            
            fixtures_data = response.json()
            fixtures = fixtures_data.get('response', [])
            
            if not fixtures:
                print("⚠️  No recent fixtures found")
                return {"success": False, "message": "No fixtures"}
            
            # Use first fixture
            sample_fixture = fixtures[0]
            fixture_id = sample_fixture['fixture']['id']
            home_team = sample_fixture['teams']['home']['name']
            away_team = sample_fixture['teams']['away']['name']
            
            print(f"\n📊 Sample Fixture: {home_team} vs {away_team} (ID: {fixture_id})")
            
            # Now get odds for this fixture
            odds_url = f"{self.base_url}/odds"
            odds_params = {
                "fixture": str(fixture_id)
            }
            
            print(f"Fetching odds for fixture {fixture_id}...")
            odds_response = requests.get(odds_url, headers=self.headers, params=odds_params, timeout=30)
            
            print(f"Status Code: {odds_response.status_code}")
            
            if odds_response.status_code == 200:
                odds_data = odds_response.json()
                odds_list = odds_data.get('response', [])
                
                if odds_list:
                    print(f"\n✅ Odds Data Retrieved Successfully")
                    print(f"Number of odds entries: {len(odds_list)}")
                    
                    # Analyze first odds entry
                    first_entry = odds_list[0]
                    print(f"\nSample Odds Structure:")
                    print(f"  League: {first_entry.get('league', {}).get('name', 'N/A')}")
                    print(f"  Fixture ID: {first_entry.get('fixture', {}).get('id', 'N/A')}")
                    print(f"  Number of bookmakers: {len(first_entry.get('bookmakers', []))}")
                    
                    # Show bookmakers and their odds
                    print(f"\n📖 Bookmakers with odds:")
                    for bookmaker in first_entry.get('bookmakers', [])[:5]:
                        book_name = bookmaker['name']
                        bets = bookmaker.get('bets', [])
                        
                        # Find match winner market
                        match_winner = next((bet for bet in bets if bet['name'] == 'Match Winner'), None)
                        
                        if match_winner:
                            values = match_winner.get('values', [])
                            odds_str = " | ".join([f"{v['value']}: {v['odd']}" for v in values[:3]])
                            print(f"  • {book_name:<20} {odds_str}")
                    
                    return {
                        "success": True,
                        "fixture_id": fixture_id,
                        "odds_data": odds_list[0],
                        "bookmakers_count": len(first_entry.get('bookmakers', []))
                    }
                else:
                    print("⚠️  No odds data available for this fixture")
                    return {"success": False, "message": "No odds data"}
            else:
                print(f"❌ Odds endpoint failed: {odds_response.status_code}")
                print(f"Response: {odds_response.text}")
                return {"success": False, "error": odds_response.text}
                
        except Exception as e:
            print(f"❌ Request failed: {e}")
            return {"success": False, "error": str(e)}
    
    def compare_with_theodds_coverage(self) -> Dict[str, Any]:
        """Compare bookmaker coverage with The Odds API"""
        print("\n🔍 COMPARING BOOKMAKER COVERAGE")
        print("=" * 60)
        
        # Get bookmakers from API-Football
        bookmakers_result = self.test_bookmakers_endpoint()
        
        if not bookmakers_result.get('success'):
            return {"success": False}
        
        api_football_books = {b['name'] for b in bookmakers_result['bookmakers']}
        
        # Known bookmakers from The Odds API (from your current system)
        theodds_books = {
            'Bet365', 'Pinnacle', 'William Hill', 'Betway', '1xBet',
            'Unibet', 'Parions Sport', 'Betclic', 'Marathon Bet',
            'Coral', 'Ladbrokes', '888sport', 'BetVictor'
        }
        
        print(f"\n📊 Coverage Comparison:")
        print(f"  API-Football: {len(api_football_books)} bookmakers")
        print(f"  The Odds API: {len(theodds_books)} bookmakers (from current system)")
        
        # Find overlap
        overlap = api_football_books.intersection(theodds_books)
        api_football_only = api_football_books - theodds_books
        theodds_only = theodds_books - api_football_books
        
        print(f"\n✅ Overlap ({len(overlap)} bookmakers):")
        for book in sorted(list(overlap)[:10]):
            print(f"  • {book}")
        
        if api_football_only:
            print(f"\n🆕 API-Football Exclusive ({len(api_football_only)} bookmakers):")
            for book in sorted(list(api_football_only)[:10]):
                print(f"  • {book}")
        
        if theodds_only:
            print(f"\n🎯 The Odds API Exclusive ({len(theodds_only)} bookmakers):")
            for book in sorted(list(theodds_only)):
                print(f"  • {book}")
        
        return {
            "success": True,
            "api_football_count": len(api_football_books),
            "theodds_count": len(theodds_books),
            "overlap_count": len(overlap),
            "overlap": list(overlap)
        }
    
    def analyze_gap_in_training_matches(self) -> Dict[str, Any]:
        """Analyze how many training matches lack odds data"""
        print("\n🔎 ANALYZING ODDS GAPS IN TRAINING MATCHES")
        print("=" * 60)
        
        try:
            conn = psycopg2.connect(self.database_url)
            cursor = conn.cursor()
            
            # Total training matches
            cursor.execute("SELECT COUNT(*) FROM training_matches")
            total_matches = cursor.fetchone()[0]
            
            # Matches with odds_snapshots
            cursor.execute("""
                SELECT COUNT(DISTINCT tm.match_id)
                FROM training_matches tm
                INNER JOIN odds_snapshots os ON tm.match_id = os.match_id
            """)
            with_snapshots = cursor.fetchone()[0]
            
            # Matches with odds_consensus
            cursor.execute("""
                SELECT COUNT(DISTINCT tm.match_id)
                FROM training_matches tm
                INNER JOIN odds_consensus oc ON tm.match_id = oc.match_id
            """)
            with_consensus = cursor.fetchone()[0]
            
            # Gap by league
            cursor.execute("""
                SELECT 
                    lm.league_name,
                    COUNT(tm.match_id) as total,
                    COUNT(os.match_id) as with_odds,
                    COUNT(tm.match_id) - COUNT(os.match_id) as gap
                FROM training_matches tm
                LEFT JOIN league_map lm ON tm.league_id = lm.league_id
                LEFT JOIN odds_snapshots os ON tm.match_id = os.match_id
                GROUP BY lm.league_name
                ORDER BY gap DESC
                LIMIT 15
            """)
            
            league_gaps = cursor.fetchall()
            
            cursor.close()
            conn.close()
            
            print(f"\n📊 Overall Gap Analysis:")
            print(f"  Total training matches: {total_matches:,}")
            print(f"  With odds_snapshots: {with_snapshots:,} ({with_snapshots/total_matches*100:.1f}%)")
            print(f"  With odds_consensus: {with_consensus:,} ({with_consensus/total_matches*100:.1f}%)")
            print(f"  Gap (no odds): {total_matches - with_snapshots:,} ({(total_matches-with_snapshots)/total_matches*100:.1f}%)")
            
            print(f"\n📋 Gap by League (Top 15):")
            print(f"{'League':<30} {'Total':<10} {'With Odds':<12} {'Gap':<10}")
            print("-" * 65)
            
            for league, total, with_odds, gap in league_gaps:
                league_name = league if league else "Unknown"
                print(f"{league_name:<30} {total:<10} {with_odds:<12} {gap:<10}")
            
            return {
                "success": True,
                "total_matches": total_matches,
                "with_odds": with_snapshots,
                "gap": total_matches - with_snapshots,
                "gap_percentage": (total_matches - with_snapshots) / total_matches * 100 if total_matches > 0 else 0
            }
            
        except Exception as e:
            print(f"❌ Database query failed: {e}")
            return {"success": False, "error": str(e)}
    
    def run_full_exploration(self):
        """Run complete Phase 1 exploration"""
        print("\n" + "=" * 70)
        print("  API-FOOTBALL ODDS EXPLORATION - PHASE 1")
        print("=" * 70)
        
        results = {}
        
        # Test 1: Bookmakers endpoint
        results['bookmakers'] = self.test_bookmakers_endpoint()
        
        # Test 2: Odds endpoint with sample
        results['odds_sample'] = self.test_odds_endpoint_sample()
        
        # Test 3: Coverage comparison
        results['coverage'] = self.compare_with_theodds_coverage()
        
        # Test 4: Gap analysis
        results['gap_analysis'] = self.analyze_gap_in_training_matches()
        
        # Summary
        print("\n" + "=" * 70)
        print("  EXPLORATION SUMMARY")
        print("=" * 70)
        
        if results['bookmakers'].get('success'):
            print(f"✅ Bookmakers Endpoint: Working ({len(results['bookmakers']['bookmakers'])} bookmakers)")
        else:
            print(f"❌ Bookmakers Endpoint: Failed")
        
        if results['odds_sample'].get('success'):
            print(f"✅ Odds Endpoint: Working ({results['odds_sample'].get('bookmakers_count', 0)} bookmakers per match)")
        else:
            print(f"❌ Odds Endpoint: Failed or No Data")
        
        if results['coverage'].get('success'):
            print(f"✅ Coverage Analysis: {results['coverage']['overlap_count']} overlapping bookmakers")
        
        if results['gap_analysis'].get('success'):
            gap_pct = results['gap_analysis']['gap_percentage']
            print(f"⚠️  Odds Gap: {results['gap_analysis']['gap']:,} matches ({gap_pct:.1f}%) missing odds")
        
        print("\n💡 Recommendations:")
        if results['gap_analysis'].get('gap', 0) > 5000:
            print("  • High priority: Use API-Football to backfill historical odds")
            print("  • Potential accuracy improvement: 2-3% with authentic training data")
        
        if results['coverage'].get('overlap_count', 0) > 5:
            print("  • Multi-source consensus viable: Good bookmaker overlap")
        
        print("\n")
        
        return results

if __name__ == "__main__":
    explorer = APIFootballOddsExplorer()
    explorer.run_full_exploration()
