#!/usr/bin/env python3
"""
Comprehensive QA/QC Report for Odds Collection System
======================================================

Run this script to generate a detailed report of the odds collection
and consensus calculation system status.

Usage:
    python scripts/qa_odds_collection_report.py
"""

import os
from datetime import datetime
from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv('DATABASE_URL')

def generate_report():
    """Generate comprehensive QA/QC report."""
    
    if not DATABASE_URL:
        print("ERROR: DATABASE_URL not set")
        return
    
    engine = create_engine(DATABASE_URL)
    
    print("="*70)
    print("ODDS COLLECTION QA/QC REPORT")
    print(f"Generated: {datetime.utcnow().isoformat()}")
    print("="*70)
    
    with engine.connect() as conn:
        
        # Section 1: Overall Summary
        print("\n" + "="*70)
        print("1. OVERALL SUMMARY")
        print("="*70)
        
        result = conn.execute(text("""
            SELECT 
                (SELECT COUNT(*) FROM odds_snapshots) as total_snapshots,
                (SELECT COUNT(DISTINCT match_id) FROM odds_snapshots) as unique_matches_odds,
                (SELECT COUNT(*) FROM consensus_predictions) as total_consensus,
                (SELECT COUNT(DISTINCT match_id) FROM consensus_predictions) as unique_matches_consensus,
                (SELECT COUNT(*) FROM fixtures) as total_fixtures,
                (SELECT COUNT(*) FROM multisport_odds_snapshots) as multisport_snapshots
        """))
        row = result.fetchone()
        print(f"  Total odds_snapshots: {row.total_snapshots:,}")
        print(f"  Unique matches with odds: {row.unique_matches_odds:,}")
        print(f"  Total consensus_predictions: {row.total_consensus:,}")
        print(f"  Unique matches with consensus: {row.unique_matches_consensus:,}")
        print(f"  Total fixtures: {row.total_fixtures:,}")
        print(f"  Multi-sport snapshots: {row.multisport_snapshots:,}")
        
        # Section 2: Data Sources
        print("\n" + "="*70)
        print("2. DATA SOURCES")
        print("="*70)
        
        result = conn.execute(text("""
            SELECT 
                source,
                COUNT(*) as total,
                COUNT(DISTINCT match_id) as matches,
                MIN(created_at) as oldest,
                MAX(created_at) as newest
            FROM odds_snapshots
            GROUP BY source
            ORDER BY total DESC
        """))
        for row in result:
            print(f"\n  {row.source or 'NULL'}:")
            print(f"    Total snapshots: {row.total:,}")
            print(f"    Unique matches: {row.matches:,}")
            print(f"    Date range: {row.oldest} to {row.newest}")
        
        # Section 3: Recent Collection Activity
        print("\n" + "="*70)
        print("3. RECENT COLLECTION ACTIVITY")
        print("="*70)
        
        result = conn.execute(text("""
            SELECT 
                source,
                COUNT(CASE WHEN created_at > NOW() - INTERVAL '24 hours' THEN 1 END) as last_24h,
                COUNT(CASE WHEN created_at > NOW() - INTERVAL '7 days' THEN 1 END) as last_7d,
                MAX(created_at) as latest
            FROM odds_snapshots
            GROUP BY source
        """))
        for row in result:
            print(f"\n  {row.source}:")
            print(f"    Last 24h: {row.last_24h:,}")
            print(f"    Last 7d: {row.last_7d:,}")
            print(f"    Latest collection: {row.latest}")
        
        # Section 4: Consensus Quality
        print("\n" + "="*70)
        print("4. CONSENSUS QUALITY")
        print("="*70)
        
        result = conn.execute(text("""
            SELECT 
                COUNT(*) as total,
                AVG(n_books) as avg_books,
                MIN(n_books) as min_books,
                MAX(n_books) as max_books
            FROM consensus_predictions
            WHERE n_books IS NOT NULL
        """))
        row = result.fetchone()
        print(f"  Total records: {row.total:,}")
        print(f"  Avg bookmakers: {row.avg_books:.1f}")
        print(f"  Min bookmakers: {row.min_books}")
        print(f"  Max bookmakers: {row.max_books}")
        
        # Probability sum distribution
        result = conn.execute(text("""
            SELECT 
                CASE 
                    WHEN (consensus_h + consensus_d + consensus_a) < 0.99 THEN '<0.99'
                    WHEN (consensus_h + consensus_d + consensus_a) <= 1.01 THEN '0.99-1.01'
                    WHEN (consensus_h + consensus_d + consensus_a) < 1.1 THEN '1.01-1.1'
                    ELSE '>1.1'
                END as range,
                COUNT(*) as cnt
            FROM consensus_predictions
            WHERE consensus_h IS NOT NULL
            GROUP BY range
            ORDER BY range
        """))
        print("\n  Probability sum distribution:")
        for row in result:
            print(f"    {row.range}: {row.cnt:,}")
        
        # Section 5: Time Bucket Coverage
        print("\n" + "="*70)
        print("5. TIME BUCKET COVERAGE")
        print("="*70)
        
        result = conn.execute(text("""
            SELECT time_bucket, COUNT(*) as cnt, AVG(n_books) as avg_books
            FROM consensus_predictions
            GROUP BY time_bucket
            ORDER BY cnt DESC
        """))
        for row in result:
            print(f"  {row.time_bucket}: {row.cnt:,} records (avg {row.avg_books:.1f} books)")
        
        # Section 6: Multi-Sport Coverage
        print("\n" + "="*70)
        print("6. MULTI-SPORT COVERAGE")
        print("="*70)
        
        result = conn.execute(text("""
            SELECT sport, COUNT(*) as cnt
            FROM multisport_odds_snapshots
            GROUP BY sport
            ORDER BY cnt DESC
        """))
        for row in result:
            print(f"  {row.sport}: {row.cnt:,} snapshots")
        
        # Section 7: Upcoming Coverage
        print("\n" + "="*70)
        print("7. UPCOMING FIXTURES COVERAGE")
        print("="*70)
        
        result = conn.execute(text("""
            SELECT 
                COUNT(*) as total,
                COUNT(CASE WHEN EXISTS (
                    SELECT 1 FROM odds_snapshots os WHERE os.match_id = f.match_id
                ) THEN 1 END) as with_odds
            FROM fixtures f
            WHERE f.kickoff_at > NOW() 
            AND f.kickoff_at < NOW() + INTERVAL '7 days'
        """))
        row = result.fetchone()
        coverage = (row.with_odds / row.total * 100) if row.total > 0 else 0
        print(f"  Upcoming fixtures (7 days): {row.total}")
        print(f"  With odds collected: {row.with_odds}")
        print(f"  Coverage: {coverage:.1f}%")
        
        # Section 8: Data Quality Issues
        print("\n" + "="*70)
        print("8. DATA QUALITY ISSUES")
        print("="*70)
        
        issues = []
        
        # Check for NULL match_ids
        result = conn.execute(text("""
            SELECT COUNT(*) as cnt FROM odds_snapshots WHERE match_id IS NULL
        """))
        null_ids = result.fetchone().cnt
        if null_ids > 0:
            issues.append(f"NULL match_ids in odds_snapshots: {null_ids}")
        
        # Check for invalid probabilities
        result = conn.execute(text("""
            SELECT COUNT(*) as cnt FROM odds_snapshots
            WHERE implied_prob < 0 OR implied_prob > 1
        """))
        invalid_probs = result.fetchone().cnt
        if invalid_probs > 0:
            issues.append(f"Invalid implied probabilities: {invalid_probs}")
        
        # Check for extreme probability sums
        result = conn.execute(text("""
            SELECT COUNT(*) as cnt FROM consensus_predictions
            WHERE (consensus_h + consensus_d + consensus_a) < 0.9
               OR (consensus_h + consensus_d + consensus_a) > 1.2
        """))
        extreme_sums = result.fetchone().cnt
        if extreme_sums > 0:
            issues.append(f"Extreme probability sums in consensus: {extreme_sums}")
        
        if issues:
            for issue in issues:
                print(f"  ⚠️ {issue}")
        else:
            print("  ✅ No significant data quality issues detected")
        
        # Section 9: Bookmaker Distribution
        print("\n" + "="*70)
        print("9. TOP BOOKMAKERS")
        print("="*70)
        
        result = conn.execute(text("""
            SELECT book_id, COUNT(*) as cnt
            FROM odds_snapshots
            GROUP BY book_id
            ORDER BY cnt DESC
            LIMIT 10
        """))
        print("  Top 10 bookmakers by snapshot count:")
        for row in result:
            print(f"    {row.book_id}: {row.cnt:,}")
        
        print("\n" + "="*70)
        print("END OF REPORT")
        print("="*70)


if __name__ == '__main__':
    generate_report()
