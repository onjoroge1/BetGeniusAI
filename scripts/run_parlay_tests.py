#!/usr/bin/env python3
"""
Parlay System Unit Test Runner

Usage:
    python scripts/run_parlay_tests.py
    python scripts/run_parlay_tests.py --verbose
    python scripts/run_parlay_tests.py --integration
"""

import os
import sys
import argparse
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def print_header(title: str):
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def print_section(title: str):
    print(f"\n--- {title} ---")


def run_unit_tests(verbose: bool = False) -> dict:
    """Run all unit tests"""
    from tests.test_parlays import (
        TestEdgeCalculations,
        TestParlayGeneration,
        TestCooldownSystem,
        TestSettlementLogic,
        TestDataIntegrity,
        TestDatabaseSchema,
    )
    
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    test_classes = [
        TestEdgeCalculations,
        TestParlayGeneration,
        TestCooldownSystem,
        TestSettlementLogic,
        TestDataIntegrity,
        TestDatabaseSchema,
    ]
    
    for test_class in test_classes:
        suite.addTests(loader.loadTestsFromTestCase(test_class))
    
    verbosity = 2 if verbose else 1
    runner = unittest.TextTestRunner(verbosity=verbosity)
    result = runner.run(suite)
    
    return {
        'tests_run': result.testsRun,
        'failures': len(result.failures),
        'errors': len(result.errors),
        'skipped': len(result.skipped),
        'success': result.wasSuccessful(),
        'failure_details': result.failures,
        'error_details': result.errors
    }


def run_integration_tests(verbose: bool = False) -> dict:
    """Run integration tests (requires database)"""
    from tests.test_parlays import TestIntegration
    
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestIntegration))
    
    verbosity = 2 if verbose else 1
    runner = unittest.TextTestRunner(verbosity=verbosity)
    result = runner.run(suite)
    
    return {
        'tests_run': result.testsRun,
        'failures': len(result.failures),
        'errors': len(result.errors),
        'skipped': len(result.skipped),
        'success': result.wasSuccessful()
    }


def run_live_edge_calculation_test():
    """Test edge calculation with actual database values"""
    print_section("Live Edge Calculation Test")
    
    try:
        from sqlalchemy import create_engine, text
        
        db_url = os.getenv('DATABASE_URL')
        if not db_url:
            print("  SKIP: DATABASE_URL not set")
            return None
        
        engine = create_engine(db_url)
        
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT 
                    confidence_tier,
                    COUNT(*) as cnt,
                    ROUND(AVG(edge_pct)::numeric, 2) as avg_edge,
                    ROUND(MIN(edge_pct)::numeric, 2) as min_edge,
                    ROUND(MAX(edge_pct)::numeric, 2) as max_edge
                FROM player_parlays
                WHERE status = 'pending'
                GROUP BY confidence_tier
                ORDER BY confidence_tier
            """)).fetchall()
            
            print(f"  {'Tier':<10} {'Count':<8} {'Avg Edge':<10} {'Min':<8} {'Max':<8}")
            print(f"  {'-'*44}")
            
            for row in result:
                print(f"  {row.confidence_tier:<10} {row.cnt:<8} {row.avg_edge:<10} {row.min_edge:<8} {row.max_edge:<8}")
            
            negative_edges = sum(1 for r in result if r.avg_edge < 0)
            
            return {
                'tiers': len(result),
                'negative_edge_tiers': negative_edges,
                'pass': negative_edges == 0
            }
            
    except Exception as e:
        print(f"  ERROR: {e}")
        return {'error': str(e)}


def run_settlement_readiness_test():
    """Test if parlays are ready to be settled"""
    print_section("Settlement Readiness Test")
    
    try:
        from sqlalchemy import create_engine, text
        
        db_url = os.getenv('DATABASE_URL')
        if not db_url:
            print("  SKIP: DATABASE_URL not set")
            return None
        
        engine = create_engine(db_url)
        
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT 
                    status,
                    COUNT(*) as total,
                    COUNT(*) FILTER (WHERE latest_kickoff < NOW() - INTERVAL '3 hours') as settleable
                FROM parlay_consensus
                GROUP BY status
            """)).fetchall()
            
            print(f"  {'Status':<12} {'Total':<10} {'Settleable':<10}")
            print(f"  {'-'*32}")
            
            for row in result:
                print(f"  {row.status:<12} {row.total:<10} {row.settleable:<10}")
            
            return {
                'statuses': len(result),
                'data': [{
                    'status': r.status,
                    'total': r.total,
                    'settleable': r.settleable
                } for r in result]
            }
            
    except Exception as e:
        print(f"  ERROR: {e}")
        return {'error': str(e)}


def run_player_parlay_data_test():
    """Test player parlay data quality"""
    print_section("Player Parlay Data Quality Test")
    
    try:
        from sqlalchemy import create_engine, text
        
        db_url = os.getenv('DATABASE_URL')
        if not db_url:
            print("  SKIP: DATABASE_URL not set")
            return None
        
        engine = create_engine(db_url)
        
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT 
                    COUNT(*) as total_parlays,
                    COUNT(*) FILTER (WHERE leg_count = 2) as two_leg,
                    COUNT(*) FILTER (WHERE leg_count = 3) as three_leg,
                    COUNT(*) FILTER (WHERE leg_count = 4) as four_leg,
                    COUNT(*) FILTER (WHERE leg_count = 5) as five_leg,
                    COUNT(*) FILTER (WHERE edge_pct > 0) as positive_edge,
                    COUNT(*) FILTER (WHERE edge_pct < 0) as negative_edge
                FROM player_parlays
                WHERE status = 'pending'
            """)).fetchone()
            
            print(f"  Total Parlays: {result.total_parlays}")
            print(f"  2-leg: {result.two_leg}, 3-leg: {result.three_leg}, 4-leg: {result.four_leg}, 5-leg: {result.five_leg}")
            print(f"  Positive Edge: {result.positive_edge}, Negative Edge: {result.negative_edge}")
            
            positive_pct = result.positive_edge / result.total_parlays * 100 if result.total_parlays > 0 else 0
            
            return {
                'total': result.total_parlays,
                'positive_edge_pct': round(positive_pct, 1),
                'pass': positive_pct >= 50
            }
            
    except Exception as e:
        print(f"  ERROR: {e}")
        return {'error': str(e)}


def print_recommendations(results: dict):
    """Print recommendations based on test results"""
    print_header("RECOMMENDATIONS")
    
    recommendations = []
    
    if not results.get('unit', {}).get('success', True):
        recommendations.append("CRITICAL: Fix failing unit tests before deployment")
    
    if results.get('edge_test', {}).get('negative_edge_tiers', 0) > 0:
        recommendations.append("WARNING: Some confidence tiers have negative average edge - review edge calculation")
    
    if results.get('player_data', {}).get('positive_edge_pct', 100) < 50:
        recommendations.append("WARNING: Less than 50% of player parlays have positive edge - check model calibration")
    
    settlement_data = results.get('settlement', {}).get('data', [])
    expired_count = sum(s['settleable'] for s in settlement_data if s['status'] == 'expired')
    if expired_count > 1000:
        recommendations.append(f"ACTION: {expired_count} parlays are ready for settlement - run settlement job")
    
    if not recommendations:
        recommendations.append("All tests passed - system is healthy")
    
    for i, rec in enumerate(recommendations, 1):
        print(f"  {i}. {rec}")


def main():
    parser = argparse.ArgumentParser(description='Run Parlay System Tests')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    parser.add_argument('--integration', '-i', action='store_true', help='Run integration tests')
    parser.add_argument('--all', '-a', action='store_true', help='Run all tests including live data tests')
    args = parser.parse_args()
    
    print_header(f"PARLAY SYSTEM TEST SUITE - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    results = {}
    
    print_section("Unit Tests")
    results['unit'] = run_unit_tests(args.verbose)
    
    if args.integration or args.all:
        print_section("Integration Tests")
        results['integration'] = run_integration_tests(args.verbose)
    
    if args.all:
        results['edge_test'] = run_live_edge_calculation_test()
        results['settlement'] = run_settlement_readiness_test()
        results['player_data'] = run_player_parlay_data_test()
    
    print_header("TEST SUMMARY")
    
    unit = results['unit']
    print(f"  Unit Tests: {unit['tests_run']} run, {unit['failures']} failures, {unit['errors']} errors")
    print(f"  Status: {'PASS' if unit['success'] else 'FAIL'}")
    
    if 'integration' in results:
        integ = results['integration']
        print(f"  Integration Tests: {integ['tests_run']} run, {integ['failures']} failures, {integ['skipped']} skipped")
    
    if args.all:
        print_recommendations(results)
    
    overall_success = results['unit']['success']
    if 'integration' in results:
        overall_success = overall_success and results['integration']['success']
    
    return 0 if overall_success else 1


if __name__ == '__main__':
    sys.exit(main())
