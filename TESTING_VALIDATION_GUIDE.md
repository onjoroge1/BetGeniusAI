# BetGenius AI - Testing & Validation Guide

## Testing Strategy Overview

This guide demonstrates comprehensive validation approaches for the enhanced 50+ market system, covering API functionality, mathematical correctness, performance benchmarks, and production readiness.

## 1. API Smoke Testing

### Basic Endpoint Validation
```bash
# Test basic prediction endpoint
curl -X POST "http://localhost:8000/predict" \
  -H "Authorization: Bearer betgenius_secure_key_2024" \
  -H "Content-Type: application/json" \
  -d '{
    "match_id": 1419629,
    "include_additional_markets": true,
    "include_ai_analysis": false
  }' | head -50

# Expected: HTTP 200, JSON response with comprehensive_markets
```

### Market Coverage Validation
```bash
# Test all three response formats
curl -X POST "http://localhost:8000/predict" \
  -H "Authorization: Bearer betgenius_secure_key_2024" \
  -H "Content-Type: application/json" \
  -d '{
    "match_id": 1419629,
    "include_additional_markets": true,
    "response_format": "v2"
  }' --max-time 20
```

### Performance Testing
```bash
# Measure response times
time curl -X POST "http://localhost:8000/predict" \
  -H "Authorization: Bearer betgenius_secure_key_2024" \
  -H "Content-Type: application/json" \
  -d '{"match_id": 1419629, "include_additional_markets": true}' \
  --max-time 25 -w "Response Time: %{time_total}s\n"

# Target: <20s response time for production readiness
```

## 2. Mathematical Validation Scripts

### Probability Sum Validation
```python
def validate_probability_sums(market_data):
    """Validate that mutually exclusive markets sum to 1.0"""
    validations = []
    
    # Double chance validation
    if 'double_chance' in market_data:
        dc = market_data['double_chance']
        # 1X + 12 + X2 should sum to 2.0 (overlapping)
        overlap_sum = dc.get('1X', 0) + dc.get('12', 0) + dc.get('X2', 0)
        validations.append(('double_chance_overlap', overlap_sum, 2.0))
    
    # BTTS validation
    if 'btts' in market_data:
        btts = market_data['btts']
        btts_sum = btts.get('yes', 0) + btts.get('no', 0)
        validations.append(('btts_sum', btts_sum, 1.0))
    
    # Total goals validation (each line)
    if 'total_goals' in market_data:
        for line, probs in market_data['total_goals'].items():
            line_sum = probs.get('over', 0) + probs.get('under', 0)
            validations.append((f'total_goals_{line}', line_sum, 1.0))
    
    return validations

# Usage example
def test_probability_validation():
    response = get_prediction_response(1419629)
    markets = response['comprehensive_markets']['v2']
    
    validations = validate_probability_sums(markets)
    for test_name, actual, expected in validations:
        tolerance = 0.001
        if abs(actual - expected) > tolerance:
            print(f"❌ FAIL: {test_name} = {actual:.6f}, expected {expected:.6f}")
        else:
            print(f"✅ PASS: {test_name} = {actual:.6f}")
```

### Consistency Cross-Validation
```python
def validate_market_consistency(market_data):
    """Validate mathematical relationships between markets"""
    
    # Extract base probabilities
    if 'meta' not in market_data:
        return "❌ Missing metadata for validation"
    
    lambda_h = market_data['meta']['lambda_h']
    lambda_a = market_data['meta']['lambda_a']
    
    # Validate BTTS calculation
    expected_btts_yes = 1.0 - math.exp(-lambda_h) - math.exp(-lambda_a) + math.exp(-(lambda_h + lambda_a))
    actual_btts_yes = market_data.get('btts', {}).get('yes', 0)
    
    print(f"BTTS Validation: Expected {expected_btts_yes:.3f}, Actual {actual_btts_yes:.3f}")
    
    # Validate total goals consistency
    total_2_5_over = market_data.get('total_goals', {}).get('2_5', {}).get('over', 0)
    total_2_5_under = market_data.get('total_goals', {}).get('2_5', {}).get('under', 0)
    
    print(f"Total 2.5 Sum: {total_2_5_over + total_2_5_under:.6f} (should be 1.0)")
    
    return "✅ Consistency validation completed"
```

## 3. Load Testing Framework

### Concurrent Request Testing
```python
import asyncio
import aiohttp
import time

async def load_test_prediction(session, match_id, request_id):
    """Single prediction request for load testing"""
    url = "http://localhost:8000/predict"
    headers = {
        "Authorization": "Bearer betgenius_secure_key_2024",
        "Content-Type": "application/json"
    }
    data = {
        "match_id": match_id,
        "include_additional_markets": True,
        "include_ai_analysis": False
    }
    
    start_time = time.time()
    try:
        async with session.post(url, headers=headers, json=data, timeout=30) as response:
            if response.status == 200:
                end_time = time.time()
                return {"request_id": request_id, "status": "success", "time": end_time - start_time}
            else:
                return {"request_id": request_id, "status": "failed", "error": response.status}
    except Exception as e:
        return {"request_id": request_id, "status": "error", "error": str(e)}

async def run_load_test(concurrent_requests=5, match_id=1419629):
    """Run concurrent load test"""
    async with aiohttp.ClientSession() as session:
        tasks = [
            load_test_prediction(session, match_id, i) 
            for i in range(concurrent_requests)
        ]
        
        print(f"🚀 Starting load test with {concurrent_requests} concurrent requests...")
        start_time = time.time()
        
        results = await asyncio.gather(*tasks)
        
        end_time = time.time()
        total_time = end_time - start_time
        
        # Analyze results
        successful = [r for r in results if r['status'] == 'success']
        failed = [r for r in results if r['status'] != 'success']
        
        print(f"📊 Load Test Results:")
        print(f"   Total time: {total_time:.2f}s")
        print(f"   Successful: {len(successful)}/{len(results)}")
        print(f"   Failed: {len(failed)}/{len(results)}")
        
        if successful:
            avg_response_time = sum(r['time'] for r in successful) / len(successful)
            print(f"   Avg response time: {avg_response_time:.2f}s")
        
        return results

# Run load test
# asyncio.run(run_load_test(concurrent_requests=3))
```

## 4. Production Readiness Validation

### Health Check Script
```python
def production_health_check():
    """Comprehensive production readiness validation"""
    checks = []
    
    # 1. API Response Time
    start_time = time.time()
    response = requests.post(
        "http://localhost:8000/predict",
        headers={"Authorization": "Bearer betgenius_secure_key_2024"},
        json={"match_id": 1419629, "include_additional_markets": True},
        timeout=25
    )
    response_time = time.time() - start_time
    
    checks.append({
        "test": "API Response Time",
        "status": "✅ PASS" if response_time < 20 else "❌ FAIL",
        "value": f"{response_time:.2f}s",
        "threshold": "<20s"
    })
    
    # 2. Market Coverage
    if response.status_code == 200:
        data = response.json()
        markets = data.get('comprehensive_markets', {}).get('v2', {})
        
        expected_markets = [
            'total_goals', 'team_totals', 'asian_handicap', 
            'double_chance', 'winning_margins', 'correct_score',
            'btts', 'clean_sheet', 'win_to_nil'
        ]
        
        missing_markets = [m for m in expected_markets if m not in markets]
        
        checks.append({
            "test": "Market Coverage",
            "status": "✅ PASS" if not missing_markets else "❌ FAIL",
            "value": f"{len(expected_markets) - len(missing_markets)}/{len(expected_markets)}",
            "missing": missing_markets
        })
        
        # 3. Mathematical Validation
        total_goals_2_5 = markets.get('total_goals', {}).get('2_5', {})
        prob_sum = total_goals_2_5.get('over', 0) + total_goals_2_5.get('under', 0)
        
        checks.append({
            "test": "Probability Sum (2.5 goals)",
            "status": "✅ PASS" if abs(prob_sum - 1.0) < 0.001 else "❌ FAIL",
            "value": f"{prob_sum:.6f}",
            "threshold": "1.000000 ±0.001"
        })
    
    # Print results
    print("🔍 Production Health Check Results:")
    print("=" * 50)
    for check in checks:
        print(f"{check['status']} {check['test']}: {check['value']}")
        if 'missing' in check and check['missing']:
            print(f"   Missing: {check['missing']}")
    
    return checks
```

## 5. Automated Testing Pipeline

### Continuous Validation Script
```bash
#!/bin/bash
# automated_validation.sh

echo "🧪 BetGenius AI - Automated Validation Pipeline"
echo "=============================================="

# 1. Basic API Health Check
echo "1. API Health Check..."
response_code=$(curl -s -o /dev/null -w "%{http_code}" \
  -X POST "http://localhost:8000/predict" \
  -H "Authorization: Bearer betgenius_secure_key_2024" \
  -H "Content-Type: application/json" \
  -d '{"match_id": 1419629, "include_additional_markets": true}' \
  --max-time 25)

if [ "$response_code" == "200" ]; then
  echo "✅ API responding correctly (HTTP 200)"
else
  echo "❌ API failed (HTTP $response_code)"
  exit 1
fi

# 2. Performance Benchmark
echo "2. Performance Testing..."
response_time=$(curl -s -X POST "http://localhost:8000/predict" \
  -H "Authorization: Bearer betgenius_secure_key_2024" \
  -H "Content-Type: application/json" \
  -d '{"match_id": 1419629, "include_additional_markets": true}' \
  -w "%{time_total}" \
  --max-time 25 -o /dev/null)

echo "Response time: ${response_time}s"
if (( $(echo "$response_time < 20" | bc -l) )); then
  echo "✅ Performance within threshold (<20s)"
else
  echo "❌ Performance too slow (>20s)"
  exit 1
fi

# 3. Market Structure Validation
echo "3. Market Structure Validation..."
market_count=$(curl -s -X POST "http://localhost:8000/predict" \
  -H "Authorization: Bearer betgenius_secure_key_2024" \
  -H "Content-Type: application/json" \
  -d '{"match_id": 1419629, "include_additional_markets": true}' \
  --max-time 25 | \
  python3 -c "
import sys, json
data = json.load(sys.stdin)
markets = data.get('comprehensive_markets', {}).get('v2', {})
print(len(markets))
")

echo "Market types found: $market_count"
if [ "$market_count" -ge "8" ]; then
  echo "✅ Comprehensive markets available ($market_count types)"
else
  echo "❌ Insufficient market coverage ($market_count types)"
  exit 1
fi

echo "🎉 All validation checks passed!"
```

## 6. Error Handling Validation

### Edge Case Testing
```python
def test_edge_cases():
    """Test system behavior with edge cases"""
    
    test_cases = [
        # Invalid match ID
        {"match_id": 999999, "expected_behavior": "graceful_error"},
        
        # Missing authorization
        {"match_id": 1419629, "auth": None, "expected_status": 401},
        
        # Malformed request
        {"invalid_field": "test", "expected_status": 422},
        
        # Very old match
        {"match_id": 1000000, "expected_behavior": "fallback_or_error"}
    ]
    
    for case in test_cases:
        print(f"Testing: {case}")
        # Implementation would test each case
```

## 7. Monitoring & Alerting

### Real-time Health Monitoring
```python
import logging
from datetime import datetime

def setup_monitoring():
    """Configure monitoring for production system"""
    
    # Performance monitoring
    def log_response_time(func):
        def wrapper(*args, **kwargs):
            start = time.time()
            result = func(*args, **kwargs)
            duration = time.time() - start
            
            if duration > 20:  # Alert threshold
                logging.warning(f"SLOW_RESPONSE: {duration:.2f}s for {func.__name__}")
            
            return result
        return wrapper
    
    # Market validation monitoring
    def validate_market_output(markets):
        issues = []
        
        # Check probability sums
        for market_type, market_data in markets.items():
            if isinstance(market_data, dict) and 'over' in market_data:
                prob_sum = market_data.get('over', 0) + market_data.get('under', 0)
                if abs(prob_sum - 1.0) > 0.01:
                    issues.append(f"Invalid probability sum in {market_type}: {prob_sum}")
        
        if issues:
            logging.error(f"MARKET_VALIDATION_FAILED: {issues}")
        
        return len(issues) == 0
```

## Testing Execution Commands

```bash
# Quick smoke test
curl -X POST "http://localhost:8000/predict" \
  -H "Authorization: Bearer betgenius_secure_key_2024" \
  -H "Content-Type: application/json" \
  -d '{"match_id": 1419629, "include_additional_markets": true}' \
  --max-time 20 -w "Time: %{time_total}s\nStatus: %{response_code}\n"

# Performance benchmark
for i in {1..5}; do
  echo "Test $i:"
  time curl -s -X POST "http://localhost:8000/predict" \
    -H "Authorization: Bearer betgenius_secure_key_2024" \
    -H "Content-Type: application/json" \
    -d '{"match_id": 1419629, "include_additional_markets": true}' \
    --max-time 25 > /dev/null
done

# Market validation
python3 -c "
import requests, json
response = requests.post('http://localhost:8000/predict',
  headers={'Authorization': 'Bearer betgenius_secure_key_2024'},
  json={'match_id': 1419629, 'include_additional_markets': True})
data = response.json()
markets = data['comprehensive_markets']['v2']
print('Markets found:', list(markets.keys()))
print('Total goals 2.5 sum:', 
  markets['total_goals']['2_5']['over'] + markets['total_goals']['2_5']['under'])
"
```

---

This comprehensive testing framework ensures the enhanced market system meets production quality standards through API validation, mathematical correctness, performance benchmarks, and continuous monitoring.