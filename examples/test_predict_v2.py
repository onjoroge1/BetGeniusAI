"""
Test script for /predict-v2 endpoint
Demonstrates API usage, error handling, and response parsing
"""
import requests
import json
from datetime import datetime

# Configuration
BASE_URL = "http://localhost:8000"  # Change to your deployed URL
API_KEY = "your_api_key_here"  # Replace with actual API key

def test_predict_v2_single_match():
    """
    Test V2 prediction for a single match
    V2 SELECT: Only returns high-confidence predictions (conf >= 0.62, EV > 0)
    """
    print("\n" + "="*60)
    print("TEST 1: Single Match V2 Prediction")
    print("="*60)
    
    # Example: Get upcoming matches first
    matches_response = requests.get(
        f"{BASE_URL}/market",
        headers={"X-API-Key": API_KEY}
    )
    
    if matches_response.status_code != 200:
        print(f"❌ Failed to fetch matches: {matches_response.status_code}")
        return
    
    matches = matches_response.json()
    print(f"📊 Found {len(matches)} upcoming matches")
    
    if not matches:
        print("⚠️  No upcoming matches available")
        return
    
    # Take first match
    match = matches[0]
    match_id = match['match_id']
    
    print(f"\n🎯 Testing match: {match['home_team']} vs {match['away_team']}")
    print(f"   Match ID: {match_id}")
    print(f"   Kickoff: {match['kickoff_at']}")
    
    # Call /predict-v2
    response = requests.get(
        f"{BASE_URL}/predict-v2",
        params={"match_id": match_id},
        headers={"X-API-Key": API_KEY}
    )
    
    print(f"\n📡 Response Status: {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        print("\n✅ V2 PREDICTION RECEIVED:")
        print(json.dumps(data, indent=2))
        
        # Parse prediction
        prediction = data.get('prediction', {})
        print("\n📈 Prediction Summary:")
        print(f"   Predicted Outcome: {prediction.get('predicted_outcome')}")
        print(f"   Confidence: {prediction.get('confidence', 0)*100:.1f}%")
        print(f"   Expected Value: {prediction.get('expected_value', 0)*100:.2f}%")
        
        print("\n🎲 Full Probabilities:")
        probs = prediction.get('probabilities', {})
        print(f"   Home Win:  {probs.get('home', 0)*100:.1f}%")
        print(f"   Draw:      {probs.get('draw', 0)*100:.1f}%")
        print(f"   Away Win:  {probs.get('away', 0)*100:.1f}%")
        
        # AI Analysis
        ai = data.get('ai_analysis')
        if ai:
            print(f"\n🤖 AI Analysis: {ai.get('summary', 'N/A')}")
        
    elif response.status_code == 404:
        print("\n⚠️  NO V2 PREDICTION AVAILABLE")
        print("   Reason: Match doesn't meet V2 SELECT criteria")
        print("   - Confidence must be >= 62%")
        print("   - Expected Value must be > 0%")
        print("   💡 Tip: Try /predict endpoint for V1 prediction")
        
    elif response.status_code == 429:
        print("\n⏱️  RATE LIMIT EXCEEDED")
        print(f"   Message: {response.json().get('error')}")
        print("   💡 Tip: Wait before retrying")
        
    else:
        print(f"\n❌ ERROR: {response.status_code}")
        print(f"   {response.text}")


def test_predict_v2_batch():
    """
    Test V2 predictions for multiple matches
    Shows how to handle selective availability
    """
    print("\n" + "="*60)
    print("TEST 2: Batch V2 Prediction Testing")
    print("="*60)
    
    # Get all upcoming matches
    matches_response = requests.get(
        f"{BASE_URL}/market",
        headers={"X-API-Key": API_KEY}
    )
    
    if matches_response.status_code != 200:
        print(f"❌ Failed to fetch matches: {matches_response.status_code}")
        return
    
    matches = matches_response.json()
    print(f"\n📊 Testing {len(matches)} matches...")
    
    v2_available = 0
    v2_unavailable = 0
    results = []
    
    for match in matches[:10]:  # Test first 10 matches
        match_id = match['match_id']
        
        response = requests.get(
            f"{BASE_URL}/predict-v2",
            params={"match_id": match_id},
            headers={"X-API-Key": API_KEY}
        )
        
        if response.status_code == 200:
            v2_available += 1
            data = response.json()
            pred = data.get('prediction', {})
            
            results.append({
                'match': f"{match['home_team']} vs {match['away_team']}",
                'outcome': pred.get('predicted_outcome'),
                'confidence': pred.get('confidence', 0) * 100,
                'ev': pred.get('expected_value', 0) * 100,
                'available': True
            })
        else:
            v2_unavailable += 1
            results.append({
                'match': f"{match['home_team']} vs {match['away_team']}",
                'available': False
            })
    
    print(f"\n📈 Results Summary:")
    print(f"   V2 Available: {v2_available}")
    print(f"   V2 Unavailable: {v2_unavailable}")
    print(f"   Availability Rate: {v2_available/(v2_available+v2_unavailable)*100:.1f}%")
    
    print(f"\n✅ V2 SELECT Predictions:")
    for r in results:
        if r['available']:
            print(f"   {r['match']}")
            print(f"      → {r['outcome']} (Conf: {r['confidence']:.1f}%, EV: {r['ev']:.2f}%)")


def test_v1_vs_v2_comparison():
    """
    Compare V1 and V2 predictions side-by-side
    Demonstrates premium feature value
    """
    print("\n" + "="*60)
    print("TEST 3: V1 vs V2 Comparison")
    print("="*60)
    
    # Get market data (includes both V1 and V2)
    response = requests.get(
        f"{BASE_URL}/market",
        headers={"X-API-Key": API_KEY}
    )
    
    if response.status_code != 200:
        print(f"❌ Failed to fetch market: {response.status_code}")
        return
    
    matches = response.json()
    
    print(f"\n📊 Comparing predictions for {len(matches)} matches:\n")
    
    for match in matches[:5]:  # Show first 5
        print(f"⚽ {match['home_team']} vs {match['away_team']}")
        print(f"   Kickoff: {match['kickoff_at']}")
        
        # V1 Prediction (from market endpoint)
        v1 = match.get('v1_prediction', {})
        if v1:
            print(f"\n   🥈 V1 (Consensus):")
            print(f"      Outcome: {v1.get('predicted_outcome')}")
            print(f"      Home: {v1.get('home_prob', 0)*100:.1f}%")
            print(f"      Draw: {v1.get('draw_prob', 0)*100:.1f}%")
            print(f"      Away: {v1.get('away_prob', 0)*100:.1f}%")
        
        # V2 Prediction (from market endpoint)
        v2 = match.get('v2_prediction', {})
        if v2:
            print(f"\n   🥇 V2 (LightGBM SELECT):")
            print(f"      Outcome: {v2.get('predicted_outcome')}")
            print(f"      Confidence: {v2.get('confidence', 0)*100:.1f}%")
            print(f"      EV: {v2.get('expected_value', 0)*100:.2f}%")
            print(f"      Home: {v2.get('home_prob', 0)*100:.1f}%")
            print(f"      Draw: {v2.get('draw_prob', 0)*100:.1f}%")
            print(f"      Away: {v2.get('away_prob', 0)*100:.1f}%")
        else:
            print(f"\n   ⚠️  V2: Not available (below quality threshold)")
        
        print(f"\n   📊 Best Odds:")
        odds = match.get('best_odds', {})
        print(f"      Home: {odds.get('home', 0):.2f}")
        print(f"      Draw: {odds.get('draw', 0):.2f}")
        print(f"      Away: {odds.get('away', 0):.2f}")
        
        print("\n" + "-"*60 + "\n")


def test_error_handling():
    """
    Test error scenarios and edge cases
    """
    print("\n" + "="*60)
    print("TEST 4: Error Handling")
    print("="*60)
    
    # Test 1: Invalid match ID
    print("\n1️⃣ Testing invalid match_id...")
    response = requests.get(
        f"{BASE_URL}/predict-v2",
        params={"match_id": 999999999},
        headers={"X-API-Key": API_KEY}
    )
    print(f"   Status: {response.status_code}")
    print(f"   Response: {response.json()}")
    
    # Test 2: Missing API key
    print("\n2️⃣ Testing missing API key...")
    response = requests.get(
        f"{BASE_URL}/predict-v2",
        params={"match_id": 1379062}
    )
    print(f"   Status: {response.status_code}")
    print(f"   Response: {response.json()}")
    
    # Test 3: Invalid API key
    print("\n3️⃣ Testing invalid API key...")
    response = requests.get(
        f"{BASE_URL}/predict-v2",
        params={"match_id": 1379062},
        headers={"X-API-Key": "invalid_key_123"}
    )
    print(f"   Status: {response.status_code}")
    print(f"   Response: {response.json()}")


if __name__ == "__main__":
    print("\n🚀 BetGenius AI - V2 Prediction API Test Suite")
    print("="*60)
    
    # Run all tests
    test_predict_v2_single_match()
    test_predict_v2_batch()
    test_v1_vs_v2_comparison()
    test_error_handling()
    
    print("\n" + "="*60)
    print("✅ Test suite complete!")
    print("="*60 + "\n")
