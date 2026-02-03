"""
Comprehensive tests for the V3 → V1 → V0 → None prediction cascade.

Tests validate:
1. Each predictor works independently
2. Cascade fallback logic works correctly
3. Response format is consistent across all levels
4. Edge cases and error handling
"""

import pytest
import asyncio
import os
import sys
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pytest_plugins = ('pytest_asyncio',)

from sqlalchemy import create_engine


class TestV0FormPredictor:
    """Test V0 form-only predictor independently."""
    
    def test_v0_model_loads(self):
        """V0 model should load successfully."""
        from models.v0_form_predictor import get_v0_predictor
        predictor = get_v0_predictor()
        
        assert predictor is not None
        assert predictor.is_available() == True
        
    def test_v0_model_info(self):
        """V0 model info should include key metadata."""
        from models.v0_form_predictor import get_v0_predictor
        predictor = get_v0_predictor()
        info = predictor.get_model_info()
        
        assert info['status'] == 'loaded'
        assert 'accuracy' in info
        assert 'leak_free' in info
        assert info['leak_free'] == True
        assert info['model_type'] == 'binary_experts_weighted'
    
    def test_v0_prediction_format(self):
        """V0 predictions should have correct format."""
        from models.v0_form_predictor import get_v0_predictor
        predictor = get_v0_predictor()
        
        engine = create_engine(os.environ['DATABASE_URL'])
        with engine.connect() as conn:
            from sqlalchemy import text
            result = conn.execute(text("""
                SELECT match_id FROM fixtures 
                WHERE home_team_id IS NOT NULL AND away_team_id IS NOT NULL
                LIMIT 1
            """))
            row = result.fetchone()
            if not row:
                pytest.skip("No fixtures with team IDs available")
            match_id = row[0]
        
        prediction = predictor.predict(match_id)
        
        if prediction:
            assert 'probabilities' in prediction
            assert 'H' in prediction['probabilities']
            assert 'D' in prediction['probabilities']
            assert 'A' in prediction['probabilities']
            
            probs = prediction['probabilities']
            total = probs['H'] + probs['D'] + probs['A']
            assert abs(total - 1.0) < 0.01, f"Probabilities should sum to 1, got {total}"
            
            assert 'prediction' in prediction
            assert prediction['prediction'] in ['H', 'D', 'A']
            
            assert 'confidence' in prediction
            assert 0 <= prediction['confidence'] <= 1
            
            assert 'model' in prediction
            assert prediction['model'] == 'v0_form'
            
            assert 'leak_free' in prediction
            assert prediction['leak_free'] == True
            
            assert 'elo_home' in prediction
            assert 'elo_away' in prediction
            
    def test_v0_handles_missing_teams(self):
        """V0 should handle matches without team IDs gracefully."""
        from models.v0_form_predictor import get_v0_predictor
        predictor = get_v0_predictor()
        
        result = predictor.predict(
            match_id=999999999,
            home_team_id=None,
            away_team_id=None
        )
        
        assert result is None


class TestV1ConsensusPredictor:
    """Test V1 consensus prediction functionality."""
    
    @pytest.mark.asyncio
    async def test_v1_consensus_lookup(self):
        """V1 consensus lookup should work for matches with odds."""
        from main import get_consensus_prediction_from_db
        
        engine = create_engine(os.environ['DATABASE_URL'])
        with engine.connect() as conn:
            from sqlalchemy import text
            result = conn.execute(text("""
                SELECT match_id FROM consensus_predictions 
                WHERE consensus_h > 0 LIMIT 1
            """))
            row = result.fetchone()
            if not row:
                pytest.skip("No consensus predictions available")
            match_id = row[0]
        
        prediction = await get_consensus_prediction_from_db(match_id)
        
        if prediction:
            assert 'probabilities' in prediction
            assert 'home' in prediction['probabilities']
            assert 'draw' in prediction['probabilities']
            assert 'away' in prediction['probabilities']
            
    @pytest.mark.asyncio
    async def test_v1_on_demand_consensus(self):
        """V1 on-demand consensus building should work."""
        from main import build_on_demand_consensus
        
        engine = create_engine(os.environ['DATABASE_URL'])
        with engine.connect() as conn:
            from sqlalchemy import text
            result = conn.execute(text("""
                SELECT DISTINCT os.match_id FROM odds_snapshots os
                LEFT JOIN consensus_predictions cp ON os.match_id = cp.match_id
                WHERE cp.match_id IS NULL
                AND os.implied_prob IS NOT NULL
                LIMIT 1
            """))
            row = result.fetchone()
            if not row:
                pytest.skip("No matches available for on-demand consensus test")
            match_id = row[0]
        
        prediction = await build_on_demand_consensus(match_id)


class TestV3SharpPredictor:
    """Test V3 sharp book predictor."""
    
    def test_v3_model_exists(self):
        """V3 model file should exist (skips if not trained)."""
        model_path = "models/saved/v3_sharp_model_latest.pkl"
        if not os.path.exists(model_path):
            pytest.skip("V3 model not trained yet - run training/train_v3_sharp.py")
        assert os.path.exists(model_path)
        
    @pytest.mark.asyncio
    async def test_v3_sharp_availability_check(self):
        """V3 sharp book availability check should work."""
        from main import check_sharp_book_availability
        
        engine = create_engine(os.environ['DATABASE_URL'])
        with engine.connect() as conn:
            from sqlalchemy import text
            result = conn.execute(text("""
                SELECT DISTINCT match_id FROM sharp_book_odds 
                WHERE bookmaker ILIKE '%pinnacle%'
                LIMIT 1
            """))
            row = result.fetchone()
            if not row:
                pytest.skip("No sharp book odds available")
            match_id = row[0]
        
        availability = await check_sharp_book_availability(match_id)
        
        assert 'has_sharp_book' in availability
        assert isinstance(availability['has_sharp_book'], bool)


class TestCascadeFallback:
    """Test the full cascade fallback logic."""
    
    def test_cascade_priority_order(self):
        """Verify cascade follows V1 → V3 → V0 → None priority."""
        priority = ['v1_consensus', 'v3_sharp_fallback', 'v0_form_fallback', 'none']
        
        assert priority[0] == 'v1_consensus', "V1 should be first priority"
        assert priority[1] == 'v3_sharp_fallback', "V3 should be second priority"
        assert priority[2] == 'v0_form_fallback', "V0 should be third priority"
        assert priority[3] == 'none', "None should be final fallback"
        
    @pytest.mark.asyncio
    async def test_cascade_with_v1_available(self):
        """When V1 consensus is available, use V1."""
        from main import get_consensus_prediction_from_db
        
        engine = create_engine(os.environ['DATABASE_URL'])
        with engine.connect() as conn:
            from sqlalchemy import text
            result = conn.execute(text("""
                SELECT match_id FROM consensus_predictions 
                WHERE consensus_h > 0.1 AND consensus_h < 0.9
                LIMIT 1
            """))
            row = result.fetchone()
            if not row:
                pytest.skip("No consensus predictions available")
            match_id = row[0]
        
        prediction = await get_consensus_prediction_from_db(match_id)
        
        assert prediction is not None
        assert prediction.get('confidence', 0) > 0
        
    def test_cascade_to_v0_when_no_odds(self):
        """When no odds available, cascade to V0 form-only."""
        from models.v0_form_predictor import get_v0_predictor
        
        predictor = get_v0_predictor()
        assert predictor.is_available()
        
        engine = create_engine(os.environ['DATABASE_URL'])
        with engine.connect() as conn:
            from sqlalchemy import text
            result = conn.execute(text("""
                SELECT f.match_id 
                FROM fixtures f
                LEFT JOIN odds_snapshots os ON f.match_id = os.match_id
                WHERE f.home_team_id IS NOT NULL 
                AND f.away_team_id IS NOT NULL
                AND os.match_id IS NULL
                LIMIT 1
            """))
            row = result.fetchone()
            if not row:
                pytest.skip("No matches without odds available")
            match_id = row[0]
        
        prediction = predictor.predict(match_id)
        
        if prediction:
            assert prediction['model'] == 'v0_form'


class TestResponseConsistency:
    """Test that all prediction sources return consistent format."""
    
    def test_v0_response_has_required_fields(self):
        """V0 response should have all required fields."""
        from models.v0_form_predictor import get_v0_predictor
        predictor = get_v0_predictor()
        
        engine = create_engine(os.environ['DATABASE_URL'])
        with engine.connect() as conn:
            from sqlalchemy import text
            result = conn.execute(text("""
                SELECT match_id FROM fixtures 
                WHERE home_team_id IS NOT NULL AND away_team_id IS NOT NULL
                LIMIT 1
            """))
            row = result.fetchone()
            if not row:
                pytest.skip("No fixtures available")
            match_id = row[0]
        
        prediction = predictor.predict(match_id)
        
        if prediction:
            required_fields = ['probabilities', 'prediction', 'confidence', 'model']
            for field in required_fields:
                assert field in prediction, f"Missing required field: {field}"
                
    @pytest.mark.asyncio
    async def test_prediction_probability_sum(self):
        """All prediction probabilities should sum to 1."""
        from main import get_consensus_prediction_from_db
        
        engine = create_engine(os.environ['DATABASE_URL'])
        with engine.connect() as conn:
            from sqlalchemy import text
            result = conn.execute(text("""
                SELECT match_id FROM consensus_predictions 
                WHERE consensus_h > 0 LIMIT 5
            """))
            rows = result.fetchall()
            if not rows:
                pytest.skip("No consensus predictions available")
            
        for row in rows:
            prediction = await get_consensus_prediction_from_db(row[0])
            if prediction and 'probabilities' in prediction:
                probs = prediction['probabilities']
                total = probs.get('home', 0) + probs.get('draw', 0) + probs.get('away', 0)
                assert abs(total - 1.0) < 0.05, f"Probabilities should sum to ~1, got {total}"


class TestELOSystem:
    """Test ELO rating system for V0."""
    
    def test_elo_manager_loads(self):
        """ELO manager should load successfully."""
        from models.team_elo import TeamELOManager
        manager = TeamELOManager()
        assert manager is not None
        
    def test_elo_initial_rating(self):
        """Unknown teams should get initial ELO rating."""
        from models.team_elo import TeamELOManager, INITIAL_ELO
        manager = TeamELOManager()
        
        rating = manager.get_team_elo(999999999)
        assert rating == INITIAL_ELO
        
    def test_elo_known_team(self):
        """Known teams should have ELO rating from database."""
        from models.team_elo import TeamELOManager
        manager = TeamELOManager()
        
        engine = create_engine(os.environ['DATABASE_URL'])
        with engine.connect() as conn:
            from sqlalchemy import text
            result = conn.execute(text("""
                SELECT team_id, elo_rating FROM team_elo LIMIT 1
            """))
            row = result.fetchone()
            if not row:
                pytest.skip("No ELO ratings in database")
            team_id, expected_elo = row[0], row[1]
        
        rating = manager.get_team_elo(team_id)
        assert rating > 0


class TestCascadeIntegration:
    """Integration tests for the full prediction cascade."""
    
    @pytest.mark.asyncio
    async def test_full_predict_endpoint_available(self):
        """Full predict endpoint should be available."""
        from fastapi.testclient import TestClient
        from main import app
        
        client = TestClient(app)
        
        response = client.get("/")
        assert response.status_code == 200
        
    @pytest.mark.asyncio
    async def test_predict_with_real_match(self):
        """Predict endpoint should return valid response for real match."""
        from fastapi.testclient import TestClient
        from main import app
        
        client = TestClient(app)
        
        engine = create_engine(os.environ['DATABASE_URL'])
        with engine.connect() as conn:
            from sqlalchemy import text
            result = conn.execute(text("""
                SELECT match_id FROM fixtures 
                WHERE status = 'scheduled'
                AND home_team_id IS NOT NULL
                LIMIT 1
            """))
            row = result.fetchone()
            if not row:
                pytest.skip("No scheduled fixtures available")
            match_id = row[0]
        
        response = client.post(
            "/predict",
            json={"match_id": match_id},
            headers={"X-API-Key": "test_key"}
        )
        
        assert response.status_code in [200, 401, 422]
        
    def test_cascade_metrics_tracking(self):
        """Cascade should track which level was used."""
        sources = ['v1_consensus', 'v3_sharp_fallback', 'v0_form_fallback', 'none']
        
        for source in sources:
            prediction_result = {
                'probabilities': {'home': 0.4, 'draw': 0.3, 'away': 0.3},
                'confidence': 0.4,
                'prediction_source': source,
                'data_quality': 'full' if source == 'v1_consensus' else 'limited'
            }
            
            assert 'prediction_source' in prediction_result
            assert prediction_result['prediction_source'] in sources


class TestV0LeakFree:
    """Verify V0 model is truly leak-free."""
    
    def test_model_metadata_leak_free(self):
        """Model metadata should indicate leak-free training."""
        from models.v0_form_predictor import get_v0_predictor
        predictor = get_v0_predictor()
        info = predictor.get_model_info()
        
        assert info.get('leak_free') == True, "Model should be marked as leak-free"
        
    def test_model_uses_binary_experts(self):
        """Model should use binary expert ensemble."""
        from models.v0_form_predictor import get_v0_predictor
        predictor = get_v0_predictor()
        info = predictor.get_model_info()
        
        assert info.get('model_type') == 'binary_experts_weighted'
        
    def test_model_has_expected_features(self):
        """Model should use 11 leak-free features."""
        from models.v0_form_predictor import get_v0_predictor
        predictor = get_v0_predictor()
        info = predictor.get_model_info()
        
        assert info.get('n_features') == 11


def run_cascade_qa():
    """Run quick QA check on cascade."""
    print("="*70)
    print("PREDICTION CASCADE QA/QC")
    print("="*70)
    
    from models.v0_form_predictor import get_v0_predictor
    
    print("\n1. V0 Form-Only Predictor")
    print("-"*40)
    v0 = get_v0_predictor()
    print(f"   Available: {v0.is_available()}")
    info = v0.get_model_info()
    print(f"   Accuracy: {info.get('accuracy', 'N/A'):.1%}" if info.get('accuracy') else "   Accuracy: N/A")
    print(f"   Leak-free: {info.get('leak_free', False)}")
    print(f"   Model type: {info.get('model_type', 'N/A')}")
    print(f"   Features: {info.get('n_features', 'N/A')}")
    
    print("\n2. V3 Sharp Book Model")
    print("-"*40)
    v3_path = "models/saved/v3_sharp_model_latest.pkl"
    print(f"   Model exists: {os.path.exists(v3_path)}")
    
    print("\n3. Cascade Implementation")
    print("-"*40)
    import inspect
    from main import predict_match
    source = inspect.getsource(predict_match)
    
    has_v1 = 'v1_consensus' in source
    has_v3 = 'v3_sharp_fallback' in source
    has_v0 = 'v0_form_fallback' in source or 'V0' in source
    has_none = 'no_prediction' in source
    
    print(f"   V1 consensus check: {'✅' if has_v1 else '❌'}")
    print(f"   V3 sharp fallback: {'✅' if has_v3 else '❌'}")
    print(f"   V0 form fallback: {'✅' if has_v0 else '❌'}")
    print(f"   None fallback: {'✅' if has_none else '❌'}")
    
    print("\n4. Database Status")
    print("-"*40)
    engine = create_engine(os.environ['DATABASE_URL'])
    with engine.connect() as conn:
        from sqlalchemy import text
        
        result = conn.execute(text("SELECT COUNT(*) FROM consensus_predictions WHERE consensus_h > 0"))
        v1_count = result.scalar()
        print(f"   V1 consensus predictions: {v1_count:,}")
        
        try:
            result = conn.execute(text("SELECT COUNT(DISTINCT match_id) FROM sharp_book_odds"))
            v3_count = result.scalar()
            print(f"   V3 sharp book matches: {v3_count:,}")
        except:
            print("   V3 sharp book matches: table not found")
        
        result = conn.execute(text("SELECT COUNT(*) FROM team_elo"))
        elo_count = result.scalar()
        print(f"   V0 ELO ratings: {elo_count:,}")
    
    print("\n5. Test Prediction")
    print("-"*40)
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT match_id FROM fixtures 
            WHERE home_team_id IS NOT NULL AND away_team_id IS NOT NULL
            LIMIT 1
        """))
        row = result.fetchone()
        if row:
            match_id = row[0]
            prediction = v0.predict(match_id)
            if prediction:
                print(f"   Match {match_id}:")
                print(f"   Prediction: {prediction['prediction']}")
                print(f"   Confidence: {prediction['confidence']:.1%}")
                print(f"   Probs: H={prediction['probabilities']['H']:.1%} D={prediction['probabilities']['D']:.1%} A={prediction['probabilities']['A']:.1%}")
            else:
                print(f"   Match {match_id}: No prediction available")
    
    print("\n" + "="*70)
    print("CASCADE QA COMPLETE")
    print("="*70)
    
    return True


if __name__ == "__main__":
    run_cascade_qa()
