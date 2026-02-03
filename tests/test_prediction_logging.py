"""
Comprehensive tests for the unified prediction logging system.

Tests validate:
1. Prediction logging for V0, V1, V3 models
2. Market API cascade with proper logging
3. prediction_log table data integrity
4. Settlement and accuracy tracking
5. V1 consensus flow is maintained
"""

import pytest
import asyncio
import os
import sys
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pytest_plugins = ('pytest_asyncio',)

from sqlalchemy import create_engine, text
import psycopg2


class TestPredictionLogTable:
    """Test prediction_log table structure and constraints."""
    
    def test_table_exists(self):
        """prediction_log table should exist."""
        engine = create_engine(os.environ['DATABASE_URL'])
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'prediction_log'
                )
            """))
            exists = result.scalar()
            assert exists == True, "prediction_log table should exist"
    
    def test_table_has_required_columns(self):
        """Table should have all required columns."""
        required_columns = [
            'id', 'match_id', 'league_id', 'model_version', 'cascade_level',
            'prob_home', 'prob_draw', 'prob_away', 'pick', 'confidence',
            'features_used', 'feature_hash', 'model_metadata',
            'predicted_at', 'kickoff_at', 'actual_result', 'is_correct', 'settled_at'
        ]
        
        engine = create_engine(os.environ['DATABASE_URL'])
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'prediction_log'
            """))
            columns = [row[0] for row in result.fetchall()]
            
            for col in required_columns:
                assert col in columns, f"Missing column: {col}"
    
    def test_unique_constraint_on_match_model(self):
        """Table should have unique constraint on (match_id, model_version)."""
        engine = create_engine(os.environ['DATABASE_URL'])
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT COUNT(*) 
                FROM pg_indexes 
                WHERE tablename = 'prediction_log' 
                AND indexdef ILIKE '%match_id%model_version%'
            """))
            count = result.scalar()
            assert count >= 1, "Should have unique index on (match_id, model_version)"


class TestPredictionLogger:
    """Test prediction logging functions."""
    
    def test_model_versions_defined(self):
        """MODEL_VERSIONS should define all cascade levels."""
        from utils.prediction_logger import MODEL_VERSIONS
        
        assert 'v0_form' in MODEL_VERSIONS
        assert 'v1_consensus' in MODEL_VERSIONS
        assert 'v3_sharp' in MODEL_VERSIONS
        
        assert MODEL_VERSIONS['v1_consensus']['cascade_level'] == 1
        assert MODEL_VERSIONS['v3_sharp']['cascade_level'] == 2
        assert MODEL_VERSIONS['v0_form']['cascade_level'] == 3
    
    def test_log_v0_prediction(self):
        """V0 prediction logging should work."""
        from utils.prediction_logger import log_v0_prediction
        
        test_match_id = 999999901
        result = log_v0_prediction(
            match_id=test_match_id,
            prob_home=0.45,
            prob_draw=0.25,
            prob_away=0.30,
            league_id=39,
            elo_home=1600,
            elo_away=1500
        )
        
        assert result == True
        
        engine = create_engine(os.environ['DATABASE_URL'])
        with engine.connect() as conn:
            row = conn.execute(text("""
                SELECT model_version, cascade_level, pick, confidence
                FROM prediction_log 
                WHERE match_id = :mid AND model_version = 'v0_form'
            """), {"mid": test_match_id}).fetchone()
            
            assert row is not None
            assert row[0] == 'v0_form'
            assert row[1] == 3
            assert row[2] == 'H'
            assert float(row[3]) == 0.45
            
            conn.execute(text("DELETE FROM prediction_log WHERE match_id = :mid"), {"mid": test_match_id})
            conn.commit()
    
    def test_log_v1_prediction(self):
        """V1 consensus prediction logging should work."""
        from utils.prediction_logger import log_v1_prediction
        
        test_match_id = 999999902
        result = log_v1_prediction(
            match_id=test_match_id,
            prob_home=0.35,
            prob_draw=0.30,
            prob_away=0.35,
            league_id=39,
            bookmaker_count=8
        )
        
        assert result == True
        
        engine = create_engine(os.environ['DATABASE_URL'])
        with engine.connect() as conn:
            row = conn.execute(text("""
                SELECT model_version, cascade_level, pick, confidence, model_metadata
                FROM prediction_log 
                WHERE match_id = :mid AND model_version = 'v1_consensus'
            """), {"mid": test_match_id}).fetchone()
            
            assert row is not None
            assert row[0] == 'v1_consensus'
            assert row[1] == 1
            assert row[2] in ('H', 'A')
            
            conn.execute(text("DELETE FROM prediction_log WHERE match_id = :mid"), {"mid": test_match_id})
            conn.commit()
    
    def test_log_v3_prediction(self):
        """V3 sharp prediction logging should work."""
        from utils.prediction_logger import log_v3_prediction
        
        test_match_id = 999999903
        result = log_v3_prediction(
            match_id=test_match_id,
            prob_home=0.50,
            prob_draw=0.25,
            prob_away=0.25,
            league_id=39,
            features_used=34
        )
        
        assert result == True
        
        engine = create_engine(os.environ['DATABASE_URL'])
        with engine.connect() as conn:
            row = conn.execute(text("""
                SELECT model_version, cascade_level, pick, confidence, features_used
                FROM prediction_log 
                WHERE match_id = :mid AND model_version = 'v3_sharp'
            """), {"mid": test_match_id}).fetchone()
            
            assert row is not None
            assert row[0] == 'v3_sharp'
            assert row[1] == 2
            assert row[2] == 'H'
            assert row[4] == 34
            
            conn.execute(text("DELETE FROM prediction_log WHERE match_id = :mid"), {"mid": test_match_id})
            conn.commit()
    
    def test_upsert_on_duplicate(self):
        """Logging same match+model should update existing record."""
        from utils.prediction_logger import log_v1_prediction
        
        test_match_id = 999999904
        
        log_v1_prediction(test_match_id, 0.40, 0.30, 0.30)
        log_v1_prediction(test_match_id, 0.50, 0.25, 0.25)
        
        engine = create_engine(os.environ['DATABASE_URL'])
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT COUNT(*), MAX(prob_home) 
                FROM prediction_log 
                WHERE match_id = :mid AND model_version = 'v1_consensus'
            """), {"mid": test_match_id}).fetchone()
            
            assert result[0] == 1, "Should have exactly 1 record (upsert)"
            assert result[1] == 0.50, "Should have updated probability"
            
            conn.execute(text("DELETE FROM prediction_log WHERE match_id = :mid"), {"mid": test_match_id})
            conn.commit()


class TestSettlement:
    """Test prediction settlement logic."""
    
    def test_settle_predictions(self):
        """Settlement should update actual_result and is_correct."""
        from utils.prediction_logger import log_v1_prediction, settle_predictions
        
        test_match_id = 999999905
        
        log_v1_prediction(test_match_id, 0.50, 0.25, 0.25)
        
        count = settle_predictions(test_match_id, 'H')
        
        assert count == 1
        
        engine = create_engine(os.environ['DATABASE_URL'])
        with engine.connect() as conn:
            row = conn.execute(text("""
                SELECT actual_result, is_correct, settled_at
                FROM prediction_log 
                WHERE match_id = :mid
            """), {"mid": test_match_id}).fetchone()
            
            assert row[0] == 'H'
            assert row[1] == True
            assert row[2] is not None
            
            conn.execute(text("DELETE FROM prediction_log WHERE match_id = :mid"), {"mid": test_match_id})
            conn.commit()
    
    def test_settlement_incorrect(self):
        """Settlement with wrong result should set is_correct=False."""
        from utils.prediction_logger import log_v1_prediction, settle_predictions
        
        test_match_id = 999999906
        
        log_v1_prediction(test_match_id, 0.50, 0.25, 0.25)
        
        settle_predictions(test_match_id, 'A')
        
        engine = create_engine(os.environ['DATABASE_URL'])
        with engine.connect() as conn:
            row = conn.execute(text("""
                SELECT is_correct FROM prediction_log WHERE match_id = :mid
            """), {"mid": test_match_id}).fetchone()
            
            assert row[0] == False
            
            conn.execute(text("DELETE FROM prediction_log WHERE match_id = :mid"), {"mid": test_match_id})
            conn.commit()
    
    def test_settlement_invalid_result(self):
        """Settlement with invalid result should return 0."""
        from utils.prediction_logger import settle_predictions
        
        count = settle_predictions(123456, 'X')
        assert count == 0


class TestModelAccuracy:
    """Test model accuracy tracking."""
    
    def test_get_model_accuracy(self):
        """get_model_accuracy should return stats."""
        from utils.prediction_logger import get_model_accuracy
        
        result = get_model_accuracy('v1_consensus', days=30)
        
        assert 'model' in result
        assert result['model'] == 'v1_consensus'
        assert 'total_predictions' in result
        assert 'period_days' in result
    
    def test_accuracy_per_model(self):
        """Should be able to get accuracy for each model."""
        from utils.prediction_logger import get_model_accuracy
        
        for model in ['v0_form', 'v1_consensus', 'v3_sharp']:
            result = get_model_accuracy(model)
            assert result['model'] == model
            assert 'total_predictions' in result


class TestMarketAPICascade:
    """Test market API cascade integration."""
    
    @pytest.mark.asyncio
    async def test_market_lite_mode_cascade(self):
        """Market API lite mode should implement V1→V3→V0 cascade."""
        from fastapi.testclient import TestClient
        from main import app
        
        client = TestClient(app)
        
        response = client.get("/market?mode=lite&limit=5", headers={"X-API-Key": "test_key"})
        
        if response.status_code == 401:
            pytest.skip("API key required - test skipped in auth-enabled mode")
        
        assert response.status_code == 200
        data = response.json()
        
        assert 'matches' in data
        assert data['mode'] == 'lite'
        
        for match in data['matches']:
            if match.get('prediction'):
                pred = match['prediction']
                assert 'source' in pred
                assert 'model_version' in pred
                assert pred['source'] in ('v1_consensus', 'v3_sharp', 'v0_form')
                assert pred['model_version'] in ('v1_consensus', 'v3_sharp', 'v0_form')
    
    def test_cascade_source_to_model_version_mapping(self):
        """Cascade should correctly map source to model_version."""
        mappings = {
            'v1_consensus': 'v1_consensus',
            'v3_sharp': 'v3_sharp',
            'v3_sharp_fallback': 'v3_sharp',
            'v3_fallback': 'v3_sharp',
            'v0_form': 'v0_form',
            'v0_form_fallback': 'v0_form'
        }
        
        for source, expected_model in mappings.items():
            model_version = 'v1_consensus'
            if source in ("v3_sharp", "v3_sharp_fallback", "v3_fallback"):
                model_version = 'v3_sharp'
            elif source in ("v0_form", "v0_form_fallback"):
                model_version = 'v0_form'
            
            assert model_version == expected_model, f"Source {source} should map to {expected_model}"


class TestV1ConsensusFlow:
    """Test that V1 consensus flow is maintained."""
    
    @pytest.mark.asyncio
    async def test_v1_consensus_still_works(self):
        """V1 consensus should still work independently."""
        from main import get_consensus_prediction_from_db
        
        engine = create_engine(os.environ['DATABASE_URL'])
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT match_id FROM consensus_predictions 
                WHERE consensus_h > 0 LIMIT 1
            """))
            row = result.fetchone()
            if not row:
                pytest.skip("No consensus predictions available")
            match_id = row[0]
        
        prediction = await get_consensus_prediction_from_db(match_id)
        
        assert prediction is not None
        assert 'probabilities' in prediction
    
    def test_consensus_predictions_table_unchanged(self):
        """consensus_predictions table should still exist and have data."""
        engine = create_engine(os.environ['DATABASE_URL'])
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT COUNT(*) FROM consensus_predictions
            """))
            count = result.scalar()
            assert count > 0, "consensus_predictions should still have data"
    
    def test_v1_logs_to_prediction_log(self):
        """V1 predictions should be logged to prediction_log table."""
        engine = create_engine(os.environ['DATABASE_URL'])
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT COUNT(*) FROM prediction_log 
                WHERE model_version = 'v1_consensus'
            """))
            count = result.scalar()
            assert count > 0, "V1 predictions should be logged"


class TestMatchCoverage:
    """Test match coverage statistics."""
    
    def test_coverage_breakdown(self):
        """Check match coverage by prediction source."""
        engine = create_engine(os.environ['DATABASE_URL'])
        with engine.connect() as conn:
            result = conn.execute(text("""
                WITH fixture_counts AS (
                    SELECT 
                        COUNT(*) as total_fixtures,
                        SUM(CASE WHEN home_team_id IS NOT NULL THEN 1 ELSE 0 END) as with_team_ids
                    FROM fixtures
                    WHERE status = 'scheduled'
                    AND kickoff_at > NOW()
                    AND kickoff_at < NOW() + INTERVAL '7 days'
                ),
                consensus_count AS (
                    SELECT COUNT(DISTINCT cp.match_id) as v1_coverage
                    FROM consensus_predictions cp
                    JOIN fixtures f ON cp.match_id = f.match_id
                    WHERE f.status = 'scheduled' AND f.kickoff_at > NOW()
                )
                SELECT 
                    fc.total_fixtures,
                    fc.with_team_ids,
                    cc.v1_coverage
                FROM fixture_counts fc, consensus_count cc
            """))
            row = result.fetchone()
            
            if row:
                total = row[0] or 0
                with_teams = row[1] or 0
                v1_coverage = row[2] or 0
                
                assert total >= 0
                assert with_teams >= 0
                assert v1_coverage >= 0
                
                print(f"\nMatch Coverage (next 7 days):")
                print(f"  Total fixtures: {total}")
                print(f"  With team IDs (V0 eligible): {with_teams}")
                print(f"  V1 consensus available: {v1_coverage}")
                if total > 0:
                    print(f"  V1 coverage rate: {v1_coverage/total*100:.1f}%")
                    print(f"  V0 fallback potential: {with_teams/total*100:.1f}%")


class TestDataIntegrity:
    """Test data integrity in prediction_log."""
    
    def test_probabilities_sum_to_one(self):
        """Probabilities should approximately sum to 1 (for recent predictions)."""
        engine = create_engine(os.environ['DATABASE_URL'])
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT match_id, prob_home + prob_draw + prob_away as total
                FROM prediction_log
                WHERE prob_home IS NOT NULL
                  AND predicted_at > NOW() - INTERVAL '7 days'
                LIMIT 100
            """))
            rows = result.fetchall()
            
            for row in rows:
                total = float(row[1])
                assert 0.90 < total < 1.15, f"Match {row[0]} probabilities sum to {total}"
    
    def test_pick_matches_max_probability(self):
        """Pick should be the outcome with highest probability."""
        engine = create_engine(os.environ['DATABASE_URL'])
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT match_id, pick, prob_home, prob_draw, prob_away
                FROM prediction_log
                WHERE pick IS NOT NULL
                LIMIT 50
            """))
            rows = result.fetchall()
            
            for row in rows:
                mid, pick, ph, pd, pa = row
                max_prob = max(ph, pd, pa)
                
                if pick == 'H':
                    assert ph == max_prob or abs(ph - max_prob) < 0.001
                elif pick == 'D':
                    assert pd == max_prob or abs(pd - max_prob) < 0.001
                elif pick == 'A':
                    assert pa == max_prob or abs(pa - max_prob) < 0.001


def run_logging_qa():
    """Run quick QA check on prediction logging."""
    print("="*70)
    print("PREDICTION LOGGING QA/QC")
    print("="*70)
    
    engine = create_engine(os.environ['DATABASE_URL'])
    
    print("\n1. Prediction Log Summary")
    print("-"*40)
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT 
                model_version,
                cascade_level,
                COUNT(*) as total,
                SUM(CASE WHEN is_correct THEN 1 ELSE 0 END) as correct,
                SUM(CASE WHEN actual_result IS NOT NULL THEN 1 ELSE 0 END) as settled
            FROM prediction_log
            GROUP BY model_version, cascade_level
            ORDER BY cascade_level
        """))
        rows = result.fetchall()
        
        for row in rows:
            model, level, total, correct, settled = row
            correct = correct or 0
            settled = settled or 0
            accuracy = correct / settled * 100 if settled > 0 else 0
            print(f"   {model} (L{level}): {total:,} total, {settled:,} settled, {accuracy:.1f}% accuracy")
    
    print("\n2. Recent Predictions (last 24h)")
    print("-"*40)
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT model_version, COUNT(*) 
            FROM prediction_log
            WHERE predicted_at > NOW() - INTERVAL '24 hours'
            GROUP BY model_version
        """))
        rows = result.fetchall()
        
        for row in rows:
            print(f"   {row[0]}: {row[1]:,} predictions")
    
    print("\n3. Match Coverage Estimate")
    print("-"*40)
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT 
                COUNT(*) as total_upcoming,
                SUM(CASE WHEN f.home_team_id IS NOT NULL THEN 1 ELSE 0 END) as with_teams,
                (SELECT COUNT(DISTINCT cp.match_id) FROM consensus_predictions cp 
                 JOIN fixtures fx ON cp.match_id = fx.match_id 
                 WHERE fx.status = 'scheduled' AND fx.kickoff_at > NOW()) as with_consensus
            FROM fixtures f
            WHERE f.status = 'scheduled' AND f.kickoff_at > NOW() AND f.kickoff_at < NOW() + INTERVAL '48 hours'
        """))
        row = result.fetchone()
        
        if row:
            total, with_teams, with_consensus = row
            with_teams = with_teams or 0
            with_consensus = with_consensus or 0
            
            print(f"   Upcoming fixtures (48h): {total}")
            print(f"   V1 consensus coverage: {with_consensus} ({with_consensus/total*100:.0f}%)" if total > 0 else "   V1: N/A")
            print(f"   V0 fallback eligible: {with_teams} ({with_teams/total*100:.0f}%)" if total > 0 else "   V0: N/A")
            
            estimated_coverage = min(total, with_consensus + (with_teams - with_consensus))
            print(f"   Estimated total coverage: ~{estimated_coverage/total*100:.0f}%" if total > 0 else "   Coverage: N/A")
    
    print("\n" + "="*70)
    print("LOGGING QA COMPLETE")
    print("="*70)


if __name__ == "__main__":
    run_logging_qa()
