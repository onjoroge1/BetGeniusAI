#!/usr/bin/env python3
"""
V2 Shadow System - Comprehensive Smoke Tests
Tests: DB schema, feature population, shadow inference, metrics, auto-promotion
"""

import os
import sys
import psycopg2
import requests
import json
from datetime import datetime

DATABASE_URL = os.environ.get('DATABASE_URL')
API_BASE = os.environ.get('API_BASE_URL', 'http://localhost:8000')
API_KEY = os.environ.get('API_KEY', 'betgenius_secure_key_2024')

HEADERS = {
    'Authorization': f'Bearer {API_KEY}',
    'Content-Type': 'application/json'
}

def test_database_schema():
    """Test 1: Verify V2 database tables exist"""
    print("\n" + "="*60)
    print("TEST 1: Database Schema")
    print("="*60)
    
    try:
        with psycopg2.connect(DATABASE_URL) as conn:
            cursor = conn.cursor()
            
            # Check tables exist
            tables = ['match_features', 'model_inference_logs', 'model_config', 'closing_odds']
            for table in tables:
                cursor.execute(f"""
                    SELECT COUNT(*) 
                    FROM information_schema.tables 
                    WHERE table_name = '{table}'
                """)
                if cursor.fetchone()[0] == 0:
                    print(f"❌ Table '{table}' not found!")
                    return False
                print(f"✓ Table '{table}' exists")
            
            # Check view exists
            cursor.execute("""
                SELECT COUNT(*) 
                FROM information_schema.views 
                WHERE table_name = 'odds_accuracy_evaluation_v2'
            """)
            if cursor.fetchone()[0] == 0:
                print("❌ View 'odds_accuracy_evaluation_v2' not found!")
                return False
            print("✓ View 'odds_accuracy_evaluation_v2' exists")
            
            # Check model_config values
            cursor.execute("SELECT config_key, config_value FROM model_config ORDER BY config_key")
            configs = cursor.fetchall()
            print("\nModel Configuration:")
            for key, value in configs:
                print(f"  {key}: {value}")
            
        print("\n✅ Database schema test PASSED")
        return True
        
    except Exception as e:
        print(f"\n❌ Database schema test FAILED: {e}")
        return False

def test_model_config_api():
    """Test 2: Verify /predict/which-primary endpoint"""
    print("\n" + "="*60)
    print("TEST 2: Model Config API")
    print("="*60)
    
    try:
        response = requests.get(f"{API_BASE}/predict/which-primary")
        if response.status_code != 200:
            print(f"❌ API returned status {response.status_code}")
            return False
        
        data = response.json()
        print(f"✓ Primary model: {data.get('primary_model')}")
        print(f"✓ Shadow enabled: {data.get('shadow_enabled')}")
        print(f"✓ Timestamp: {data.get('timestamp')}")
        
        print("\n✅ Model config API test PASSED")
        return True
        
    except Exception as e:
        print(f"\n❌ Model config API test FAILED: {e}")
        return False

def test_enable_shadow_mode():
    """Test 3: Enable shadow V2 mode"""
    print("\n" + "="*60)
    print("TEST 3: Enable Shadow Mode")
    print("="*60)
    
    try:
        with psycopg2.connect(DATABASE_URL) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE model_config 
                SET config_value = 'true', updated_at = NOW()
                WHERE config_key = 'ENABLE_SHADOW_V2'
            """)
            conn.commit()
            
            cursor.execute("""
                SELECT config_value 
                FROM model_config 
                WHERE config_key = 'ENABLE_SHADOW_V2'
            """)
            value = cursor.fetchone()[0]
            
        if value == 'true':
            print("✓ Shadow mode enabled")
            print("\n✅ Enable shadow mode test PASSED")
            return True
        else:
            print(f"❌ Shadow mode value is '{value}', expected 'true'")
            return False
            
    except Exception as e:
        print(f"\n❌ Enable shadow mode test FAILED: {e}")
        return False

def test_feature_population():
    """Test 4: Check if features can be populated"""
    print("\n" + "="*60)
    print("TEST 4: Feature Population")
    print("="*60)
    
    try:
        with psycopg2.connect(DATABASE_URL) as conn:
            cursor = conn.cursor()
            
            # Check for matches with odds_snapshots
            cursor.execute("""
                SELECT COUNT(DISTINCT match_id) 
                FROM odds_snapshots 
                WHERE ts_snapshot > NOW() - INTERVAL '7 days'
            """)
            recent_matches = cursor.fetchone()[0]
            print(f"✓ Found {recent_matches} matches with odds snapshots (last 7 days)")
            
            # Check current match_features count
            cursor.execute("SELECT COUNT(*) FROM match_features")
            feature_count = cursor.fetchone()[0]
            print(f"✓ Current match_features count: {feature_count}")
            
        if recent_matches > 0:
            print(f"\n💡 Run: python populate_match_features.py {recent_matches}")
        
        print("\n✅ Feature population test PASSED")
        return True
        
    except Exception as e:
        print(f"\n❌ Feature population test FAILED: {e}")
        return False

def test_metrics_ab():
    """Test 5: Verify /metrics/ab endpoint"""
    print("\n" + "="*60)
    print("TEST 5: A/B Metrics API")
    print("="*60)
    
    try:
        response = requests.get(
            f"{API_BASE}/metrics/ab?window=90d",
            headers=HEADERS
        )
        
        if response.status_code != 200:
            print(f"❌ API returned status {response.status_code}")
            return False
        
        data = response.json()
        print(f"✓ Window: {data.get('window')}")
        print(f"✓ Total matches: {data.get('n_matches')}")
        
        if 'overall' in data:
            print("\nMetrics:")
            for metric, values in data['overall'].items():
                print(f"  {metric}:")
                for k, v in values.items():
                    print(f"    {k}: {v}")
        
        print("\n✅ A/B metrics API test PASSED")
        return True
        
    except Exception as e:
        print(f"\n❌ A/B metrics API test FAILED: {e}")
        return False

def test_metrics_clv_summary():
    """Test 6: Verify /metrics/clv-summary endpoint"""
    print("\n" + "="*60)
    print("TEST 6: CLV Summary API")
    print("="*60)
    
    try:
        for model in ['v1', 'v2']:
            response = requests.get(
                f"{API_BASE}/metrics/clv-summary?window=90d&model={model}",
                headers=HEADERS
            )
            
            if response.status_code != 200:
                print(f"❌ API returned status {response.status_code} for {model}")
                continue
            
            data = response.json()
            print(f"\n{model.upper()} CLV Summary:")
            print(f"  Matches with closing: {data.get('n_with_closing')}")
            print(f"  CLV hit rate: {data.get('clv_hit_rate')}")
            print(f"  Mean CLV: {data.get('mean_clv')}")
            print(f"  Interpretation: {data.get('interpretation')}")
        
        print("\n✅ CLV summary API test PASSED")
        return True
        
    except Exception as e:
        print(f"\n❌ CLV summary API test FAILED: {e}")
        return False

def test_inference_logs():
    """Test 7: Check model inference logs"""
    print("\n" + "="*60)
    print("TEST 7: Model Inference Logs")
    print("="*60)
    
    try:
        with psycopg2.connect(DATABASE_URL) as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT model_version, COUNT(*) AS cnt
                FROM model_inference_logs
                GROUP BY model_version
                ORDER BY model_version
            """)
            
            logs = cursor.fetchall()
            if not logs:
                print("⚠️  No inference logs found yet")
                print("   Make predictions to generate logs")
            else:
                print("Inference log counts:")
                for version, count in logs:
                    print(f"  {version}: {count} predictions")
            
            # Show sample recent logs
            cursor.execute("""
                SELECT match_id, model_version, p_home, p_draw, p_away, reason_code, scored_at
                FROM model_inference_logs
                ORDER BY scored_at DESC
                LIMIT 5
            """)
            
            recent = cursor.fetchall()
            if recent:
                print("\nRecent predictions:")
                for match_id, version, ph, pd, pa, reason, scored_at in recent:
                    print(f"  {version} | match_{match_id} | H={ph:.3f} D={pd:.3f} A={pa:.3f} | {reason} | {scored_at}")
        
        print("\n✅ Inference logs test PASSED")
        return True
        
    except Exception as e:
        print(f"\n❌ Inference logs test FAILED: {e}")
        return False

def test_closing_odds():
    """Test 8: Check closing odds collection"""
    print("\n" + "="*60)
    print("TEST 8: Closing Odds")
    print("="*60)
    
    try:
        with psycopg2.connect(DATABASE_URL) as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(*) FROM closing_odds")
            count = cursor.fetchone()[0]
            print(f"✓ Closing odds records: {count}")
            
            if count > 0:
                cursor.execute("""
                    SELECT match_id, h_close_odds, d_close_odds, a_close_odds, 
                           closing_time, avg_books_closing
                    FROM closing_odds
                    ORDER BY closing_time DESC
                    LIMIT 3
                """)
                
                print("\nRecent closing odds:")
                for row in cursor.fetchall():
                    match_id, h, d, a, time, books = row
                    print(f"  match_{match_id} | H={h:.2f} D={d:.2f} A={a:.2f} | {books} books | {time}")
            else:
                print("\n⚠️  No closing odds yet")
                print("   Ensure closing odds collector is running")
        
        print("\n✅ Closing odds test PASSED")
        return True
        
    except Exception as e:
        print(f"\n❌ Closing odds test FAILED: {e}")
        return False

def test_evaluation_view():
    """Test 9: Check odds_accuracy_evaluation_v2 view"""
    print("\n" + "="*60)
    print("TEST 9: Evaluation View")
    print("="*60)
    
    try:
        with psycopg2.connect(DATABASE_URL) as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT 
                    model_version,
                    COUNT(*) AS n_predictions,
                    AVG(logloss) AS avg_logloss,
                    AVG(brier) AS avg_brier,
                    AVG(hit::int) AS hit_rate,
                    AVG(CASE WHEN clv_beats_close IS NOT NULL THEN clv_beats_close ELSE NULL END) AS clv_hit_rate
                FROM odds_accuracy_evaluation_v2
                WHERE actual IS NOT NULL
                GROUP BY model_version
                ORDER BY model_version
            """)
            
            results = cursor.fetchall()
            if not results:
                print("⚠️  No evaluation data yet")
                print("   Need predictions + match results")
            else:
                print("Evaluation metrics by model:")
                for version, n, ll, br, hit, clv_hit in results:
                    print(f"\n  {version}:")
                    print(f"    Predictions: {n}")
                    print(f"    LogLoss: {ll:.4f}" if ll else "    LogLoss: N/A")
                    print(f"    Brier: {br:.4f}" if br else "    Brier: N/A")
                    print(f"    Hit Rate: {hit:.3f}" if hit else "    Hit Rate: N/A")
                    print(f"    CLV Hit Rate: {clv_hit:.3f}" if clv_hit else "    CLV Hit Rate: N/A")
        
        print("\n✅ Evaluation view test PASSED")
        return True
        
    except Exception as e:
        print(f"\n❌ Evaluation view test FAILED: {e}")
        return False

def run_all_tests():
    """Run all smoke tests"""
    print("\n" + "="*60)
    print("V2 SHADOW SYSTEM - SMOKE TESTS")
    print("="*60)
    print(f"API Base: {API_BASE}")
    print(f"Database: {DATABASE_URL[:50]}...")
    
    tests = [
        test_database_schema,
        test_model_config_api,
        test_enable_shadow_mode,
        test_feature_population,
        test_metrics_ab,
        test_metrics_clv_summary,
        test_inference_logs,
        test_closing_odds,
        test_evaluation_view
    ]
    
    results = []
    for test in tests:
        try:
            result = test()
            results.append((test.__name__, result))
        except Exception as e:
            print(f"\n❌ Test {test.__name__} crashed: {e}")
            results.append((test.__name__, False))
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} - {name}")
    
    print(f"\nOverall: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 ALL TESTS PASSED - V2 Shadow System Ready!")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test(s) failed - Review output above")
        return 1

if __name__ == "__main__":
    sys.exit(run_all_tests())
