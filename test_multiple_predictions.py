#!/usr/bin/env python3
"""
Test script to evaluate prediction quality across multiple matches
"""
import requests
import json
import sys
import time
from typing import Dict, List

def test_prediction(match_id: int, base_url: str = "http://127.0.0.1:8000") -> Dict:
    """Test prediction for a specific match"""
    try:
        response = requests.post(
            f"{base_url}/predict",
            json={"match_id": match_id},
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer betgenius_secure_key_2024"
            },
            timeout=30
        )
        
        if response.status_code == 200:
            return response.json()
        else:
            return {"error": f"HTTP {response.status_code}: {response.text}"}
            
    except Exception as e:
        return {"error": f"Request failed: {str(e)}"}

def rate_prediction_quality(prediction: Dict) -> Dict:
    """Rate the quality of a prediction"""
    if "error" in prediction:
        return {"rating": "ERROR", "score": 0, "issues": [prediction["error"]]}
    
    issues = []
    score = 10  # Start with perfect score
    
    # Extract predictions
    preds = prediction.get("predictions", {})
    home_win = preds.get("home_win", 0)
    draw = preds.get("draw", 0) 
    away_win = preds.get("away_win", 0)
    confidence = preds.get("confidence", 0)
    
    # Check if probabilities sum to 1 (or close to it)
    total_prob = home_win + draw + away_win
    if abs(total_prob - 1.0) > 0.05:
        issues.append(f"Probabilities don't sum to 1.0 (sum: {total_prob:.3f})")
        score -= 3
    
    # Check for zero probabilities (problematic)
    zero_probs = sum([1 for p in [home_win, draw, away_win] if p == 0])
    if zero_probs >= 2:
        issues.append(f"Too many zero probabilities ({zero_probs}/3)")
        score -= 4
    
    # Check confidence level
    if confidence == 0:
        issues.append("Zero confidence - no real odds data")
        score = 0
    elif confidence < 0.1:
        issues.append("Very low confidence (<10%)")
        score -= 2
    elif confidence > 0.8:
        issues.append("Suspiciously high confidence (>80%)")
        score -= 1
    
    # Check if recommended bet makes sense
    recommended = preds.get("recommended_bet", "")
    if recommended == "Home" and home_win <= draw and home_win <= away_win:
        issues.append("Recommended bet doesn't match highest probability")
        score -= 2
    elif recommended == "Draw" and draw <= home_win and draw <= away_win:
        issues.append("Recommended bet doesn't match highest probability")
        score -= 2
    elif recommended == "Away" and away_win <= home_win and away_win <= draw:
        issues.append("Recommended bet doesn't match highest probability")
        score -= 2
    
    # Determine rating
    if score >= 9:
        rating = "EXCELLENT"
    elif score >= 7:
        rating = "GOOD"
    elif score >= 5:
        rating = "FAIR"
    elif score >= 3:
        rating = "POOR"
    else:
        rating = "CRITICAL"
    
    return {
        "rating": rating,
        "score": max(0, score),
        "issues": issues,
        "total_probability": total_prob,
        "zero_probabilities": zero_probs
    }

def main():
    # Test matches with different coverage levels
    test_matches = [
        {"match_id": 1378988, "coverage": "252 bookmakers"},
        {"match_id": 1387713, "coverage": "234 bookmakers"}, 
        {"match_id": 1390826, "coverage": "156 bookmakers"},
        {"match_id": 1377867, "coverage": "63 bookmakers"},
        {"match_id": 1387723, "coverage": "63 bookmakers (user test)"}
    ]
    
    print("🔍 Testing Prediction Quality Across Multiple Matches")
    print("=" * 60)
    
    results = []
    for test_match in test_matches:
        match_id = test_match["match_id"]
        coverage = test_match["coverage"]
        
        print(f"\n📊 Testing Match {match_id} ({coverage})...")
        
        # Test the prediction
        result = test_prediction(match_id)
        
        # Rate the quality
        quality = rate_prediction_quality(result)
        
        # Store results
        test_result = {
            "match_id": match_id,
            "coverage": coverage,
            "prediction": result,
            "quality": quality
        }
        results.append(test_result)
        
        # Display results
        if "error" not in result:
            preds = result.get("predictions", {})
            match_info = result.get("match_info", {})
            
            print(f"   🏟️  {match_info.get('home_team', 'Unknown')} vs {match_info.get('away_team', 'Unknown')}")
            print(f"   📈 Probabilities: H:{preds.get('home_win', 0):.3f} | D:{preds.get('draw', 0):.3f} | A:{preds.get('away_win', 0):.3f}")
            print(f"   🎯 Confidence: {preds.get('confidence', 0):.3f} ({preds.get('confidence', 0)*100:.1f}%)")
            print(f"   💡 Recommended: {preds.get('recommended_bet', 'N/A')}")
            print(f"   ⭐ Quality: {quality['rating']} ({quality['score']}/10)")
            
            if quality['issues']:
                print(f"   ⚠️  Issues: {', '.join(quality['issues'])}")
        else:
            print(f"   ❌ ERROR: {result['error']}")
            print(f"   ⭐ Quality: {quality['rating']} ({quality['score']}/10)")
    
    # Summary
    print("\n" + "=" * 60)
    print("📋 PREDICTION QUALITY SUMMARY")
    print("=" * 60)
    
    ratings = [r["quality"]["rating"] for r in results]
    avg_score = sum([r["quality"]["score"] for r in results]) / len(results)
    
    print(f"Average Quality Score: {avg_score:.1f}/10")
    print(f"Ratings Distribution: {dict([(r, ratings.count(r)) for r in set(ratings)])}")
    
    # Detailed analysis
    working_predictions = [r for r in results if "error" not in r["prediction"]]
    if working_predictions:
        print(f"\n✅ Working Predictions: {len(working_predictions)}/{len(results)}")
        
        # Check for common issues
        all_issues = []
        for r in working_predictions:
            all_issues.extend(r["quality"]["issues"])
        
        if all_issues:
            issue_counts = {}
            for issue in all_issues:
                issue_counts[issue] = issue_counts.get(issue, 0) + 1
            
            print("\n🔍 Most Common Issues:")
            for issue, count in sorted(issue_counts.items(), key=lambda x: x[1], reverse=True):
                print(f"   • {issue}: {count} matches")
    
    print(f"\n❌ Failed Predictions: {len(results) - len(working_predictions)}/{len(results)}")

if __name__ == "__main__":
    main()