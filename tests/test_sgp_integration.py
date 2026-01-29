"""
QA/QC Tests for SGP Integration in Predict API
================================================

Tests for:
1. SGP field presence in predict response when requested
2. SGP structure validation
3. SGP availability logic
"""

import pytest
import os
from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv('DATABASE_URL')


@pytest.fixture
def db_engine():
    """Create database engine for tests."""
    if not DATABASE_URL:
        pytest.skip("DATABASE_URL not set")
    return create_engine(DATABASE_URL)


class TestSGPIntegration:
    """Tests for SGP integration in predict API."""
    
    def test_get_sgp_for_match_returns_correct_structure(self, db_engine):
        """Test that get_sgp_for_match returns correct structure when SGP is available."""
        from models.quality_parlay_generator import QualityParlayGenerator
        
        gen = QualityParlayGenerator()
        
        with db_engine.connect() as conn:
            result = conn.execute(text("""
                SELECT f.match_id 
                FROM fixtures f
                JOIN odds_consensus oc ON f.match_id = oc.match_id
                WHERE f.kickoff_at > NOW()
                AND oc.ph_cons IS NOT NULL
                LIMIT 5
            """))
            match_ids = [row.match_id for row in result]
        
        for match_id in match_ids:
            sgp = gen.get_sgp_for_match(match_id)
            
            if sgp:
                assert 'parlay_type' in sgp, "SGP should have parlay_type"
                assert 'leg_count' in sgp, "SGP should have leg_count"
                assert 'combined_odds' in sgp, "SGP should have combined_odds"
                assert 'raw_prob_pct' in sgp, "SGP should have raw_prob_pct"
                assert 'legs' in sgp, "SGP should have legs"
                assert isinstance(sgp['legs'], list), "legs should be a list"
                
                for leg in sgp['legs']:
                    assert 'leg_type' in leg, "Leg should have leg_type"
                    assert 'match_id' in leg, "Leg should have match_id"
                    assert 'market_name' in leg, "Leg should have market_name"
                    assert 'decimal_odds' in leg, "Leg should have decimal_odds"
                    assert 'model_prob' in leg, "Leg should have model_prob"
                    
                    assert 0 < leg['model_prob'] <= 1, "model_prob should be between 0 and 1"
                    assert leg['decimal_odds'] > 1, "decimal_odds should be > 1"
    
    def test_sgp_quality_thresholds(self):
        """Test that SGP respects quality thresholds."""
        from models.quality_parlay_generator import QualityParlayGenerator
        
        gen = QualityParlayGenerator()
        
        assert gen.MIN_LEG_PROB_VALUE == 0.50, "MIN_LEG_PROB_VALUE should be 0.50"
        assert gen.MIN_PARLAY_PROB_VALUE == 0.12, "MIN_PARLAY_PROB_VALUE should be 0.12"
    
    def test_sgp_generator_initializes(self):
        """Test that QualityParlayGenerator initializes correctly."""
        from models.quality_parlay_generator import QualityParlayGenerator
        
        gen = QualityParlayGenerator()
        
        assert gen.engine is not None, "Engine should be initialized"
        assert gen.Session is not None, "Session should be initialized"


class TestSGPTemplates:
    """Tests for SGP template logic."""
    
    def test_sgp_templates_exist(self):
        """Test that SGP templates are defined."""
        from models.quality_parlay_generator import QualityParlayGenerator
        
        gen = QualityParlayGenerator()
        
        assert hasattr(gen, 'SGP_TEMPLATES'), "Should have SGP_TEMPLATES"
        assert len(gen.SGP_TEMPLATES) >= 3, "Should have at least 3 templates"
        
        expected_templates = ['home_dominance', 'away_dominance', 'tight_draw']
        for template in expected_templates:
            assert template in gen.SGP_TEMPLATES, f"Should have {template} template"
    
    def test_sgp_templates_have_required_fields(self):
        """Test that SGP templates have required fields."""
        from models.quality_parlay_generator import QualityParlayGenerator
        
        gen = QualityParlayGenerator()
        
        for name, template in gen.SGP_TEMPLATES.items():
            assert 'result' in template, f"{name} should have result field"
            assert 'totals' in template, f"{name} should have totals field"
            assert template['result'] in ['H', 'D', 'A'], f"{name} result should be H/D/A"
            assert isinstance(template['totals'], list), f"{name} totals should be a list"


class TestLegQualityScore:
    """Tests for Leg Quality Score calculation."""
    
    def test_leg_quality_score_calculation(self):
        """Test LQS calculation logic."""
        from models.quality_parlay_generator import QualityParlayGenerator
        
        gen = QualityParlayGenerator()
        
        lqs = gen.compute_leg_quality_score(
            model_prob=0.60,
            decimal_odds=2.0,
            edge_pct=5.0
        )
        
        assert isinstance(lqs, float), "LQS should be a float"
        assert -1 < lqs < 1, f"LQS should be reasonable: {lqs}"
    
    def test_lqs_low_probability_penalty(self):
        """Test that low probability legs get penalized."""
        from models.quality_parlay_generator import QualityParlayGenerator
        
        gen = QualityParlayGenerator()
        
        lqs_high_prob = gen.compute_leg_quality_score(0.60, 2.0, 5.0)
        lqs_low_prob = gen.compute_leg_quality_score(0.40, 2.0, 5.0)
        
        assert lqs_high_prob > lqs_low_prob, "Lower probability legs should have lower LQS"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
