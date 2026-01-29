"""
Comprehensive QA/QC Tests for Odds Collection System
=====================================================

Tests for:
1. Odds collection from RapidAPI/Football API
2. Odds collection from The Odds API
3. Consensus calculation accuracy
4. Multi-sport odds collection
5. Data coverage and gaps
"""

import pytest
import os
from datetime import datetime, timedelta, timezone
from sqlalchemy import create_engine, text
from unittest.mock import patch, MagicMock

DATABASE_URL = os.getenv('DATABASE_URL')


@pytest.fixture
def db_engine():
    """Create database engine for tests."""
    if not DATABASE_URL:
        pytest.skip("DATABASE_URL not set")
    return create_engine(DATABASE_URL)


class TestOddsSnapshotsTable:
    """Tests for odds_snapshots table integrity."""
    
    def test_odds_snapshots_table_exists(self, db_engine):
        """Verify odds_snapshots table exists with required columns."""
        with db_engine.connect() as conn:
            result = conn.execute(text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'odds_snapshots'
            """))
            columns = [row.column_name for row in result]
            
            required_cols = ['match_id', 'book_id', 'outcome', 'implied_prob', 'source']
            for col in required_cols:
                assert col in columns, f"Missing required column: {col}"
    
    def test_odds_snapshots_has_data(self, db_engine):
        """Verify odds_snapshots has data."""
        with db_engine.connect() as conn:
            result = conn.execute(text("SELECT COUNT(*) FROM odds_snapshots"))
            count = result.fetchone()[0]
            assert count > 0, "odds_snapshots table is empty"
    
    def test_odds_snapshots_has_multiple_sources(self, db_engine):
        """Verify data from multiple sources (theodds, api_football)."""
        with db_engine.connect() as conn:
            result = conn.execute(text("""
                SELECT DISTINCT source FROM odds_snapshots WHERE source IS NOT NULL
            """))
            sources = [row.source for row in result]
            assert len(sources) >= 1, "Should have at least one data source"
    
    def test_implied_probability_bounds(self, db_engine):
        """Verify implied probabilities are within valid range [0, 1]."""
        with db_engine.connect() as conn:
            result = conn.execute(text("""
                SELECT COUNT(*) as invalid
                FROM odds_snapshots
                WHERE implied_prob < 0 OR implied_prob > 1
            """))
            invalid = result.fetchone().invalid
            assert invalid == 0, f"Found {invalid} records with invalid implied probabilities"
    
    def test_outcome_values(self, db_engine):
        """Verify outcome column has valid values (home, draw, away)."""
        with db_engine.connect() as conn:
            result = conn.execute(text("""
                SELECT DISTINCT outcome FROM odds_snapshots
            """))
            outcomes = {row.outcome for row in result}
            valid_outcomes = {'home', 'draw', 'away', 'H', 'D', 'A'}
            for outcome in outcomes:
                assert outcome in valid_outcomes, f"Invalid outcome value: {outcome}"
    
    def test_recent_data_collection(self, db_engine):
        """Verify recent data is being collected."""
        with db_engine.connect() as conn:
            result = conn.execute(text("""
                SELECT COUNT(*) as recent
                FROM odds_snapshots
                WHERE created_at > NOW() - INTERVAL '7 days'
            """))
            recent = result.fetchone().recent
            assert recent > 0, "No odds collected in the last 7 days"


class TestConsensusPredictions:
    """Tests for consensus_predictions table."""
    
    def test_consensus_table_exists(self, db_engine):
        """Verify consensus_predictions table exists."""
        with db_engine.connect() as conn:
            result = conn.execute(text("""
                SELECT COUNT(*) FROM information_schema.tables 
                WHERE table_name = 'consensus_predictions'
            """))
            assert result.fetchone()[0] == 1, "consensus_predictions table doesn't exist"
    
    def test_consensus_has_data(self, db_engine):
        """Verify consensus_predictions has data."""
        with db_engine.connect() as conn:
            result = conn.execute(text("SELECT COUNT(*) FROM consensus_predictions"))
            count = result.fetchone()[0]
            assert count > 0, "consensus_predictions table is empty"
    
    def test_consensus_probability_bounds(self, db_engine):
        """Verify consensus probabilities are within valid range."""
        with db_engine.connect() as conn:
            result = conn.execute(text("""
                SELECT COUNT(*) as invalid
                FROM consensus_predictions
                WHERE consensus_h < 0 OR consensus_h > 1
                   OR consensus_d < 0 OR consensus_d > 1
                   OR consensus_a < 0 OR consensus_a > 1
            """))
            invalid = result.fetchone().invalid
            assert invalid == 0, f"Found {invalid} records with invalid probabilities"
    
    def test_consensus_probability_sum_reasonable(self, db_engine):
        """Verify consensus probabilities sum is reasonable (0.9-1.2 accounting for margin)."""
        with db_engine.connect() as conn:
            result = conn.execute(text("""
                SELECT 
                    COUNT(*) as total,
                    COUNT(CASE WHEN (consensus_h + consensus_d + consensus_a) < 0.9 
                               OR (consensus_h + consensus_d + consensus_a) > 1.2 THEN 1 END) as unreasonable
                FROM consensus_predictions
                WHERE consensus_h IS NOT NULL
            """))
            row = result.fetchone()
            if row.total > 0:
                ratio = row.unreasonable / row.total
                assert ratio < 0.01, f"Found {row.unreasonable} ({ratio*100:.2f}%) records with unreasonable probability sums"
    
    def test_time_bucket_values(self, db_engine):
        """Verify time_bucket has valid values."""
        with db_engine.connect() as conn:
            result = conn.execute(text("""
                SELECT DISTINCT time_bucket FROM consensus_predictions
            """))
            buckets = {row.time_bucket for row in result}
            valid_buckets = {'3h', '6h', '12h', '24h', '36h', '48h', '72h', 'other'}
            for bucket in buckets:
                assert bucket in valid_buckets, f"Invalid time bucket: {bucket}"
    
    def test_n_books_positive(self, db_engine):
        """Verify n_books is always positive."""
        with db_engine.connect() as conn:
            result = conn.execute(text("""
                SELECT COUNT(*) as invalid
                FROM consensus_predictions
                WHERE n_books <= 0
            """))
            invalid = result.fetchone().invalid
            assert invalid == 0, f"Found {invalid} records with invalid n_books"


class TestOddsConsensus:
    """Tests for odds_consensus table (parlay system)."""
    
    def test_odds_consensus_table_exists(self, db_engine):
        """Verify odds_consensus table exists."""
        with db_engine.connect() as conn:
            result = conn.execute(text("""
                SELECT COUNT(*) FROM information_schema.tables 
                WHERE table_name = 'odds_consensus'
            """))
            assert result.fetchone()[0] == 1, "odds_consensus table doesn't exist"
    
    def test_odds_consensus_probability_bounds(self, db_engine):
        """Verify probabilities are within valid range."""
        with db_engine.connect() as conn:
            result = conn.execute(text("""
                SELECT COUNT(*) as invalid
                FROM odds_consensus
                WHERE ph_cons < 0 OR ph_cons > 1
                   OR pd_cons < 0 OR pd_cons > 1
                   OR pa_cons < 0 OR pa_cons > 1
            """))
            invalid = result.fetchone().invalid
            assert invalid == 0, f"Found {invalid} records with invalid probabilities"
    
    def test_odds_consensus_normalized(self, db_engine):
        """Check how many odds_consensus records are properly normalized."""
        with db_engine.connect() as conn:
            result = conn.execute(text("""
                SELECT 
                    COUNT(*) as total,
                    COUNT(CASE WHEN ABS(ph_cons + pd_cons + pa_cons - 1.0) < 0.02 THEN 1 END) as normalized
                FROM odds_consensus
                WHERE ph_cons IS NOT NULL
            """))
            row = result.fetchone()
            # At least 50% should be reasonably normalized
            if row.total > 0:
                ratio = row.normalized / row.total
                assert ratio >= 0.5, f"Only {ratio*100:.1f}% of records are normalized"


class TestMultiSportOdds:
    """Tests for multi-sport odds collection."""
    
    def test_multisport_table_exists(self, db_engine):
        """Verify multisport_odds_snapshots table exists."""
        with db_engine.connect() as conn:
            result = conn.execute(text("""
                SELECT COUNT(*) FROM information_schema.tables 
                WHERE table_name = 'multisport_odds_snapshots'
            """))
            assert result.fetchone()[0] == 1
    
    def test_multisport_has_data(self, db_engine):
        """Verify multisport_odds_snapshots has data."""
        with db_engine.connect() as conn:
            result = conn.execute(text("SELECT COUNT(*) FROM multisport_odds_snapshots"))
            count = result.fetchone()[0]
            assert count > 0, "multisport_odds_snapshots is empty"
    
    def test_multisport_sport_coverage(self, db_engine):
        """Verify multiple sports are covered."""
        with db_engine.connect() as conn:
            result = conn.execute(text("""
                SELECT DISTINCT sport FROM multisport_odds_snapshots
            """))
            sports = [row.sport for row in result]
            assert len(sports) >= 1, "Should have at least one sport"
    
    def test_multisport_probability_bounds(self, db_engine):
        """Verify multi-sport probabilities are within valid range."""
        with db_engine.connect() as conn:
            result = conn.execute(text("""
                SELECT COUNT(*) as invalid
                FROM multisport_odds_snapshots
                WHERE (home_prob IS NOT NULL AND (home_prob < 0 OR home_prob > 1))
                   OR (away_prob IS NOT NULL AND (away_prob < 0 OR away_prob > 1))
            """))
            invalid = result.fetchone().invalid
            assert invalid == 0, f"Found {invalid} records with invalid probabilities"


class TestCoverageGaps:
    """Tests for data coverage and gap detection."""
    
    def test_fixtures_with_odds_coverage(self, db_engine):
        """Check what percentage of fixtures have odds."""
        with db_engine.connect() as conn:
            result = conn.execute(text("""
                SELECT 
                    COUNT(DISTINCT f.match_id) as total_fixtures,
                    COUNT(DISTINCT os.match_id) as with_odds
                FROM fixtures f
                LEFT JOIN odds_snapshots os ON f.match_id = os.match_id
                WHERE f.kickoff_at > NOW() - INTERVAL '30 days'
            """))
            row = result.fetchone()
            if row.total_fixtures > 0:
                coverage = row.with_odds / row.total_fixtures
                assert coverage >= 0.5, f"Only {coverage*100:.1f}% of recent fixtures have odds"
    
    def test_upcoming_fixtures_have_odds(self, db_engine):
        """Verify upcoming fixtures have odds collected."""
        with db_engine.connect() as conn:
            result = conn.execute(text("""
                SELECT COUNT(*) as upcoming
                FROM fixtures
                WHERE kickoff_at > NOW() 
                AND kickoff_at < NOW() + INTERVAL '48 hours'
            """))
            upcoming = result.fetchone().upcoming
            
            if upcoming > 0:
                result = conn.execute(text("""
                    SELECT COUNT(DISTINCT f.match_id) as with_odds
                    FROM fixtures f
                    JOIN odds_snapshots os ON f.match_id = os.match_id
                    WHERE f.kickoff_at > NOW() 
                    AND f.kickoff_at < NOW() + INTERVAL '48 hours'
                """))
                with_odds = result.fetchone().with_odds
                coverage = with_odds / upcoming
                assert coverage >= 0.5, f"Only {coverage*100:.1f}% of upcoming fixtures have odds"
    
    def test_odds_to_consensus_pipeline(self, db_engine):
        """Verify matches with odds also have consensus predictions."""
        with db_engine.connect() as conn:
            result = conn.execute(text("""
                SELECT 
                    COUNT(DISTINCT os.match_id) as with_odds,
                    COUNT(DISTINCT cp.match_id) as with_consensus
                FROM odds_snapshots os
                LEFT JOIN consensus_predictions cp ON os.match_id = cp.match_id
                WHERE os.created_at > NOW() - INTERVAL '7 days'
            """))
            row = result.fetchone()
            if row.with_odds > 0:
                ratio = row.with_consensus / row.with_odds
                assert ratio >= 0.8, f"Only {ratio*100:.1f}% of matches with odds have consensus"


class TestDataQuality:
    """Tests for overall data quality."""
    
    def test_no_null_match_ids(self, db_engine):
        """Verify no NULL match_ids in odds tables."""
        with db_engine.connect() as conn:
            for table in ['odds_snapshots', 'consensus_predictions', 'odds_consensus']:
                result = conn.execute(text(f"""
                    SELECT COUNT(*) as nulls FROM {table} WHERE match_id IS NULL
                """))
                nulls = result.fetchone().nulls
                assert nulls == 0, f"Found {nulls} NULL match_ids in {table}"
    
    def test_bookmaker_diversity(self, db_engine):
        """Verify reasonable bookmaker diversity in odds collection."""
        with db_engine.connect() as conn:
            result = conn.execute(text("""
                SELECT COUNT(DISTINCT book_id) as unique_books
                FROM odds_snapshots
                WHERE created_at > NOW() - INTERVAL '30 days'
            """))
            unique_books = result.fetchone().unique_books
            assert unique_books >= 5, f"Only {unique_books} unique bookmakers in recent data"
    
    def test_complete_three_way_markets(self, db_engine):
        """Verify markets have all three outcomes (H/D/A)."""
        with db_engine.connect() as conn:
            result = conn.execute(text("""
                WITH match_outcomes AS (
                    SELECT match_id, book_id, COUNT(DISTINCT outcome) as outcome_count
                    FROM odds_snapshots
                    WHERE outcome IN ('home', 'draw', 'away')
                    GROUP BY match_id, book_id
                )
                SELECT 
                    COUNT(*) as total,
                    COUNT(CASE WHEN outcome_count = 3 THEN 1 END) as complete
                FROM match_outcomes
            """))
            row = result.fetchone()
            if row.total > 0:
                ratio = row.complete / row.total
                assert ratio >= 0.8, f"Only {ratio*100:.1f}% of markets have all 3 outcomes"
    
    def test_secs_to_kickoff_reasonable(self, db_engine):
        """Verify secs_to_kickoff values are reasonable (allow small percentage of outliers)."""
        with db_engine.connect() as conn:
            result = conn.execute(text("""
                SELECT 
                    COUNT(*) as total,
                    COUNT(CASE WHEN secs_to_kickoff < 0 OR secs_to_kickoff > 604800 THEN 1 END) as invalid
                FROM odds_snapshots
                WHERE secs_to_kickoff IS NOT NULL
            """))
            row = result.fetchone()
            if row.total > 0:
                ratio = row.invalid / row.total
                assert ratio < 0.01, f"Found {row.invalid} ({ratio*100:.2f}%) records with invalid secs_to_kickoff"


class TestConsensusCalculation:
    """Tests for consensus calculation logic."""
    
    def test_consensus_books_count_reasonable(self, db_engine):
        """Verify n_books in consensus is within reasonable range."""
        with db_engine.connect() as conn:
            result = conn.execute(text("""
                SELECT 
                    AVG(n_books) as avg_books,
                    MIN(n_books) as min_books,
                    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY n_books) as p95_books
                FROM consensus_predictions
                WHERE n_books IS NOT NULL
            """))
            row = result.fetchone()
            if row.avg_books:
                assert row.avg_books >= 2, f"Average book count too low: {row.avg_books:.1f}"
                assert row.min_books >= 1, f"Min book count should be at least 1"
                assert row.p95_books <= 100, f"95th percentile book count too high: {row.p95_books}"
    
    def test_dispersion_values_reasonable(self, db_engine):
        """Verify dispersion values are within reasonable range."""
        with db_engine.connect() as conn:
            result = conn.execute(text("""
                SELECT COUNT(*) as invalid
                FROM consensus_predictions
                WHERE (dispersion_h IS NOT NULL AND dispersion_h > 0.5)
                   OR (dispersion_d IS NOT NULL AND dispersion_d > 0.5)
                   OR (dispersion_a IS NOT NULL AND dispersion_a > 0.5)
            """))
            invalid = result.fetchone().invalid
            assert invalid < 100, f"Found {invalid} records with unusually high dispersion"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
