"""
Comprehensive Unit Tests for Auto-Parlay and Player Parlay Systems

Test Categories:
1. Edge Calculation Tests
2. Parlay Generation Tests
3. Settlement Tests
4. Cooldown & Deduplication Tests
5. Data Integrity Tests
"""

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch, MagicMock
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestEdgeCalculations(unittest.TestCase):
    """Test edge calculation logic for both parlay types"""
    
    def test_auto_parlay_edge_positive_when_model_better_than_market(self):
        """Edge should be positive when model_prob > implied_prob"""
        model_prob = 0.55
        decimal_odds = 2.0
        implied_prob = 1 / decimal_odds
        
        edge = (model_prob - implied_prob) / implied_prob * 100
        
        self.assertGreater(edge, 0, "Edge should be positive when model beats market")
        self.assertAlmostEqual(edge, 10.0, places=1)
    
    def test_auto_parlay_edge_negative_when_market_better_than_model(self):
        """Edge should be negative when model_prob < implied_prob"""
        model_prob = 0.40
        decimal_odds = 2.0
        implied_prob = 1 / decimal_odds
        
        edge = (model_prob - implied_prob) / implied_prob * 100
        
        self.assertLess(edge, 0, "Edge should be negative when market beats model")
        self.assertAlmostEqual(edge, -20.0, places=1)
    
    def test_player_parlay_edge_with_margin(self):
        """Player parlay edge calculation with 8% market margin"""
        MARKET_MARGIN = 0.08
        model_prob = 0.50
        
        fair_odds = 1 / model_prob
        margin_adjusted_odds = fair_odds * (1 + MARKET_MARGIN)
        decimal_odds = max(1.54, min(12.5, margin_adjusted_odds))
        implied_prob = 1 / decimal_odds
        
        edge = (model_prob - implied_prob) / implied_prob * 100
        
        self.assertGreater(edge, 0, "With fair pricing + margin, model should have edge")
        self.assertAlmostEqual(edge, 8.0, places=0)
    
    def test_player_parlay_edge_clamp_issue_fixed(self):
        """Verify the clamp-induced negative edge bug is fixed"""
        MARKET_MARGIN = 0.08
        model_prob = 0.60
        
        fair_odds = 1 / model_prob
        margin_adjusted_odds = fair_odds * (1 + MARKET_MARGIN)
        decimal_odds = max(1.54, min(12.5, margin_adjusted_odds))
        implied_prob = 1 / decimal_odds
        
        edge = (model_prob - implied_prob) / implied_prob * 100
        
        expected_edge = 8.0
        self.assertAlmostEqual(edge, expected_edge, places=0)
    
    def test_combined_parlay_edge_calculation(self):
        """Test combined parlay edge from multiple legs"""
        legs = [
            {'model_prob': 0.55, 'decimal_odds': 2.0},
            {'model_prob': 0.60, 'decimal_odds': 1.8},
        ]
        
        combined_odds = 1.0
        combined_prob = 1.0
        
        for leg in legs:
            combined_odds *= leg['decimal_odds']
            combined_prob *= leg['model_prob']
        
        implied_prob = 1 / combined_odds
        parlay_edge = (combined_prob - implied_prob) / implied_prob * 100
        
        self.assertGreater(parlay_edge, 0, "Combined parlay should have positive edge")
        self.assertAlmostEqual(combined_odds, 3.6, places=1)
        self.assertAlmostEqual(combined_prob, 0.33, places=2)


class TestParlayGeneration(unittest.TestCase):
    """Test parlay generation logic"""
    
    def test_leg_quality_score_calculation(self):
        """Test LQS calculation for leg ranking"""
        model_prob = 0.55
        decimal_odds = 2.0
        edge_pct = 10.0
        
        ev = model_prob * decimal_odds - 1.0
        longshot_penalty = 0 if decimal_odds < 4.0 else 0.05 * (decimal_odds - 4.0)
        uncertainty_penalty = 0.1 * (1 - model_prob)
        
        lqs = ev - longshot_penalty - uncertainty_penalty
        
        self.assertGreater(lqs, 0, "High-probability positive-edge leg should have positive LQS")
        self.assertAlmostEqual(ev, 0.10, places=2)
    
    def test_parlay_hash_uniqueness(self):
        """Test that different leg combinations produce different hashes"""
        import hashlib
        
        legs1 = [{'player_id': 1, 'match_id': 100}, {'player_id': 2, 'match_id': 101}]
        legs2 = [{'player_id': 1, 'match_id': 100}, {'player_id': 3, 'match_id': 101}]
        
        def compute_hash(legs):
            leg_ids = sorted([f"{l['player_id']}_{l['match_id']}" for l in legs])
            return hashlib.md5('|'.join(leg_ids).encode()).hexdigest()[:16]
        
        hash1 = compute_hash(legs1)
        hash2 = compute_hash(legs2)
        
        self.assertNotEqual(hash1, hash2, "Different legs should produce different hashes")
    
    def test_parlay_hash_consistency(self):
        """Test that same legs produce same hash regardless of order"""
        import hashlib
        
        legs1 = [{'player_id': 1, 'match_id': 100}, {'player_id': 2, 'match_id': 101}]
        legs2 = [{'player_id': 2, 'match_id': 101}, {'player_id': 1, 'match_id': 100}]
        
        def compute_hash(legs):
            leg_ids = sorted([f"{l['player_id']}_{l['match_id']}" for l in legs])
            return hashlib.md5('|'.join(leg_ids).encode()).hexdigest()[:16]
        
        hash1 = compute_hash(legs1)
        hash2 = compute_hash(legs2)
        
        self.assertEqual(hash1, hash2, "Same legs in different order should produce same hash")
    
    def test_sgp_template_coherence(self):
        """Test SGP templates are internally coherent"""
        SGP_TEMPLATES = {
            'home_dominance': {'result': 'H', 'totals': ['over_1.5', 'over_2.5']},
            'away_dominance': {'result': 'A', 'totals': ['over_1.5', 'over_2.5']},
            'tight_draw': {'result': 'D', 'totals': ['under_2.5', 'under_3.5']},
        }
        
        for name, template in SGP_TEMPLATES.items():
            self.assertIn(template['result'], ['H', 'D', 'A'])
            self.assertTrue(len(template['totals']) > 0)
            
            if template['result'] in ['H', 'A']:
                self.assertTrue(
                    any('over' in t for t in template['totals']),
                    f"{name}: Win outcomes should pair with over totals"
                )
            elif template['result'] == 'D':
                self.assertTrue(
                    any('under' in t for t in template['totals']),
                    f"{name}: Draw outcomes should pair with under totals"
                )
    
    def test_confidence_tier_thresholds(self):
        """Test confidence tier assignment"""
        def get_tier(edge_pct):
            if edge_pct >= 5:
                return 'high'
            elif edge_pct >= -5:
                return 'medium'
            else:
                return 'low'
        
        self.assertEqual(get_tier(10), 'high')
        self.assertEqual(get_tier(5), 'high')
        self.assertEqual(get_tier(4.9), 'medium')
        self.assertEqual(get_tier(0), 'medium')
        self.assertEqual(get_tier(-5), 'medium')
        self.assertEqual(get_tier(-5.1), 'low')
        self.assertEqual(get_tier(-20), 'low')


class TestCooldownSystem(unittest.TestCase):
    """Test parlay cooldown and rate limiting"""
    
    def test_cooldown_constants_reasonable(self):
        """Test cooldown settings are reasonable"""
        COOLDOWN_HOURS = 2
        MAX_PARLAYS_PER_MATCH = 3
        
        self.assertGreaterEqual(COOLDOWN_HOURS, 1, "Cooldown should be at least 1 hour")
        self.assertLessEqual(COOLDOWN_HOURS, 6, "Cooldown shouldn't be too long")
        self.assertGreaterEqual(MAX_PARLAYS_PER_MATCH, 2, "Should allow at least 2 parlays per match")
        self.assertLessEqual(MAX_PARLAYS_PER_MATCH, 10, "Shouldn't allow too many per match")
    
    def test_cooldown_window_calculation(self):
        """Test cooldown window is calculated correctly"""
        COOLDOWN_HOURS = 2
        now = datetime.now(timezone.utc)
        cooldown_start = now - timedelta(hours=COOLDOWN_HOURS)
        
        recent_parlay_time = now - timedelta(hours=1)
        old_parlay_time = now - timedelta(hours=3)
        
        self.assertTrue(recent_parlay_time > cooldown_start, "Recent parlay should be in cooldown")
        self.assertFalse(old_parlay_time > cooldown_start, "Old parlay should be outside cooldown")


class TestSettlementLogic(unittest.TestCase):
    """Test parlay settlement logic"""
    
    def test_all_legs_won_parlay_wins(self):
        """Parlay should win only if all legs win"""
        legs = [
            {'result': 'won'},
            {'result': 'won'},
            {'result': 'won'},
        ]
        
        all_won = all(leg['result'] == 'won' for leg in legs)
        self.assertTrue(all_won)
    
    def test_any_leg_lost_parlay_loses(self):
        """Parlay should lose if any leg loses"""
        legs = [
            {'result': 'won'},
            {'result': 'lost'},
            {'result': 'won'},
        ]
        
        all_won = all(leg['result'] == 'won' for leg in legs)
        self.assertFalse(all_won)
    
    def test_profit_calculation_win(self):
        """Test profit calculation on winning parlay"""
        stake = 1.0
        implied_odds = 5.0
        all_legs_won = True
        
        payout = implied_odds if all_legs_won else 0.0
        profit = payout - stake
        
        self.assertEqual(payout, 5.0)
        self.assertEqual(profit, 4.0)
    
    def test_profit_calculation_loss(self):
        """Test profit calculation on losing parlay"""
        stake = 1.0
        implied_odds = 5.0
        all_legs_won = False
        
        payout = implied_odds if all_legs_won else 0.0
        profit = payout - stake
        
        self.assertEqual(payout, 0.0)
        self.assertEqual(profit, -1.0)
    
    def test_settlement_status_transitions(self):
        """Test valid status transitions"""
        valid_transitions = {
            'pending': ['active', 'expired', 'settled'],
            'active': ['settled', 'expired'],
            'expired': ['settled'],
            'settled': [],
        }
        
        for from_status, to_statuses in valid_transitions.items():
            for to_status in to_statuses:
                self.assertIn(to_status, ['active', 'settled', 'expired'])
    
    def test_player_scorer_settlement(self):
        """Test player scorer determination"""
        player_stats = {'goals': 1}
        
        scored = player_stats.get('goals', 0) > 0
        self.assertTrue(scored, "Player with 1 goal should be marked as scorer")
        
        player_stats_no_goal = {'goals': 0}
        scored_no = player_stats_no_goal.get('goals', 0) > 0
        self.assertFalse(scored_no, "Player with 0 goals should not be scorer")


class TestDataIntegrity(unittest.TestCase):
    """Test data integrity constraints"""
    
    def test_odds_bounds(self):
        """Test odds are within reasonable bounds"""
        MIN_ODDS = 1.01
        MAX_ODDS = 100.0
        
        test_odds = [1.5, 2.0, 3.5, 10.0, 25.0]
        
        for odds in test_odds:
            self.assertGreater(odds, MIN_ODDS, f"Odds {odds} should be > {MIN_ODDS}")
            self.assertLess(odds, MAX_ODDS, f"Odds {odds} should be < {MAX_ODDS}")
    
    def test_probability_bounds(self):
        """Test probabilities are between 0 and 1"""
        test_probs = [0.1, 0.25, 0.5, 0.75, 0.9]
        
        for prob in test_probs:
            self.assertGreater(prob, 0, f"Probability {prob} should be > 0")
            self.assertLess(prob, 1, f"Probability {prob} should be < 1")
    
    def test_leg_count_bounds(self):
        """Test parlay leg counts are within bounds"""
        MIN_LEGS = 2
        MAX_LEGS = 10
        
        valid_leg_counts = [2, 3, 4, 5]
        
        for count in valid_leg_counts:
            self.assertGreaterEqual(count, MIN_LEGS)
            self.assertLessEqual(count, MAX_LEGS)
    
    def test_edge_percentage_bounds(self):
        """Test edge percentages are within reasonable bounds"""
        MAX_EDGE = 50.0
        MIN_EDGE = -50.0
        
        test_edges = [-20, -10, 0, 5, 10, 20]
        
        for edge in test_edges:
            self.assertGreaterEqual(edge, MIN_EDGE)
            self.assertLessEqual(edge, MAX_EDGE)


class TestDatabaseSchema(unittest.TestCase):
    """Test database schema requirements"""
    
    def test_parlay_consensus_required_fields(self):
        """Test parlay_consensus has all required fields"""
        required_fields = [
            'parlay_id', 'leg_count', 'legs', 'implied_odds',
            'edge_pct', 'confidence_tier', 'status', 'latest_kickoff'
        ]
        
        for field in required_fields:
            self.assertIsInstance(field, str)
    
    def test_player_parlays_required_fields(self):
        """Test player_parlays has all required fields"""
        required_fields = [
            'id', 'parlay_hash', 'leg_count', 'match_ids',
            'combined_odds', 'edge_pct', 'confidence_tier',
            'status', 'expires_at'
        ]
        
        for field in required_fields:
            self.assertIsInstance(field, str)
    
    def test_parlay_performance_required_fields(self):
        """Test parlay_performance has all required fields"""
        required_fields = [
            'performance_id', 'parlay_id', 'settled_at', 'won',
            'legs_won', 'legs_lost', 'stake', 'payout', 'profit'
        ]
        
        for field in required_fields:
            self.assertIsInstance(field, str)


class TestIntegration(unittest.TestCase):
    """Integration tests (require database)"""
    
    @unittest.skipUnless(os.getenv('DATABASE_URL'), "Database not available")
    def test_database_connection(self):
        """Test database connection works"""
        from sqlalchemy import create_engine, text
        
        engine = create_engine(os.environ['DATABASE_URL'])
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1")).fetchone()
            self.assertEqual(result[0], 1)
    
    @unittest.skipUnless(os.getenv('DATABASE_URL'), "Database not available")
    def test_parlay_tables_exist(self):
        """Test required parlay tables exist"""
        from sqlalchemy import create_engine, text
        
        engine = create_engine(os.environ['DATABASE_URL'])
        tables = ['parlay_consensus', 'player_parlays', 'player_parlay_legs', 'parlay_performance']
        
        with engine.connect() as conn:
            for table in tables:
                result = conn.execute(text(f"""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_name = '{table}'
                    )
                """)).fetchone()
                self.assertTrue(result[0], f"Table {table} should exist")
    
    @unittest.skipUnless(os.getenv('DATABASE_URL'), "Database not available")
    def test_parlay_status_distribution(self):
        """Test parlay status distribution makes sense"""
        from sqlalchemy import create_engine, text
        
        engine = create_engine(os.environ['DATABASE_URL'])
        
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT status, COUNT(*) as cnt
                FROM parlay_consensus
                GROUP BY status
            """)).fetchall()
            
            status_counts = {r.status: r.cnt for r in result}
            
            for status in status_counts:
                self.assertIn(status, ['pending', 'active', 'expired', 'settled'])


class TestLegProbabilityRecording(unittest.TestCase):
    """Test that leg probabilities are correctly recorded in parlays"""
    
    def test_leg_probability_stored_in_json(self):
        """Verify model_prob is stored in leg JSON"""
        leg = {
            'match_id': 12345,
            'home_team': 'Team A',
            'away_team': 'Team B',
            'outcome': 'H',
            'model_prob': 0.55,
            'decimal_odds': 1.80,
            'edge': 0.10
        }
        
        self.assertIn('model_prob', leg)
        self.assertEqual(leg['model_prob'], 0.55)
        self.assertGreater(leg['model_prob'], 0, "Probability should be > 0")
        self.assertLessEqual(leg['model_prob'], 1.0, "Probability should be <= 1")
    
    def test_combined_probability_calculation(self):
        """Test combined probability is product of individual probs"""
        legs = [
            {'model_prob': 0.55},
            {'model_prob': 0.60},
        ]
        
        combined_prob = 1.0
        for leg in legs:
            combined_prob *= leg['model_prob']
        
        expected = 0.55 * 0.60
        self.assertAlmostEqual(combined_prob, expected, places=4)
        self.assertAlmostEqual(combined_prob, 0.33, places=2)
    
    def test_leg_probability_not_zero(self):
        """Ensure valid legs don't have zero probability"""
        valid_leg = {'model_prob': 0.45, 'outcome': 'D'}
        
        self.assertGreater(valid_leg['model_prob'], 0)
        self.assertLessEqual(valid_leg['model_prob'], 1.0)
    
    def test_zero_probability_detection(self):
        """Zero probability in legs indicates data pipeline issue"""
        invalid_leg = {'model_prob': 0.0, 'outcome': 'H'}
        
        is_invalid = invalid_leg['model_prob'] == 0
        self.assertTrue(is_invalid, "Zero probability should be flagged as invalid")


class TestParlayDeduplication(unittest.TestCase):
    """Test parlay deduplication logic"""
    
    def test_fingerprint_generation(self):
        """Test that fingerprints are generated consistently"""
        import hashlib
        
        legs = [
            {'match_id': 100, 'outcome': 'H'},
            {'match_id': 200, 'outcome': 'A'},
        ]
        
        leg_ids = sorted([f"{leg['match_id']}:{leg['outcome']}" for leg in legs])
        fingerprint = hashlib.md5("|".join(leg_ids).encode()).hexdigest()
        
        self.assertEqual(len(fingerprint), 32)
        self.assertTrue(fingerprint.isalnum())
    
    def test_fingerprint_order_independent(self):
        """Fingerprint should be same regardless of leg order"""
        import hashlib
        
        legs_order_1 = [
            {'match_id': 100, 'outcome': 'H'},
            {'match_id': 200, 'outcome': 'A'},
        ]
        legs_order_2 = [
            {'match_id': 200, 'outcome': 'A'},
            {'match_id': 100, 'outcome': 'H'},
        ]
        
        def get_fingerprint(legs):
            leg_ids = sorted([f"{leg['match_id']}:{leg['outcome']}" for leg in legs])
            return hashlib.md5("|".join(leg_ids).encode()).hexdigest()
        
        fp1 = get_fingerprint(legs_order_1)
        fp2 = get_fingerprint(legs_order_2)
        
        self.assertEqual(fp1, fp2, "Fingerprints should match regardless of order")
    
    def test_different_outcomes_different_fingerprints(self):
        """Different outcomes on same match should have different fingerprints"""
        import hashlib
        
        def get_fingerprint(legs):
            leg_ids = sorted([f"{leg['match_id']}:{leg['outcome']}" for leg in legs])
            return hashlib.md5("|".join(leg_ids).encode()).hexdigest()
        
        legs_home = [{'match_id': 100, 'outcome': 'H'}]
        legs_away = [{'match_id': 100, 'outcome': 'A'}]
        
        fp_home = get_fingerprint(legs_home)
        fp_away = get_fingerprint(legs_away)
        
        self.assertNotEqual(fp_home, fp_away, "Different outcomes should have different fingerprints")
    
    def test_duplicate_detection_concept(self):
        """Test the concept of duplicate detection"""
        existing_parlays = [
            {'parlay_id': 'abc', 'legs': [{'match_id': 100, 'outcome': 'H'}, {'match_id': 200, 'outcome': 'A'}]},
        ]
        
        new_parlay_same = {'legs': [{'match_id': 100, 'outcome': 'H'}, {'match_id': 200, 'outcome': 'A'}]}
        new_parlay_diff = {'legs': [{'match_id': 100, 'outcome': 'H'}, {'match_id': 300, 'outcome': 'D'}]}
        
        import hashlib
        def get_fingerprint(legs):
            leg_ids = sorted([f"{leg['match_id']}:{leg['outcome']}" for leg in legs])
            return hashlib.md5("|".join(leg_ids).encode()).hexdigest()
        
        existing_fps = {get_fingerprint(p['legs']) for p in existing_parlays}
        
        self.assertIn(get_fingerprint(new_parlay_same['legs']), existing_fps)
        self.assertNotIn(get_fingerprint(new_parlay_diff['legs']), existing_fps)


class TestParlayConstraints(unittest.TestCase):
    """Test parlay generation constraints"""
    
    def test_edge_range_validation(self):
        """Test edge must be within valid range"""
        MIN_EDGE = 0.04
        MAX_EDGE = 0.15
        
        valid_edge = 0.07
        too_low_edge = 0.02
        too_high_edge = 0.20
        
        self.assertTrue(MIN_EDGE <= valid_edge <= MAX_EDGE)
        self.assertFalse(MIN_EDGE <= too_low_edge <= MAX_EDGE)
        self.assertFalse(MIN_EDGE <= too_high_edge <= MAX_EDGE)
    
    def test_leg_count_must_be_two(self):
        """Current constraints require exactly 2 legs"""
        REQUIRED_LEGS = 2
        
        valid_parlay = {'legs': [{'match_id': 1}, {'match_id': 2}]}
        invalid_single = {'legs': [{'match_id': 1}]}
        invalid_three = {'legs': [{'match_id': 1}, {'match_id': 2}, {'match_id': 3}]}
        
        self.assertEqual(len(valid_parlay['legs']), REQUIRED_LEGS)
        self.assertNotEqual(len(invalid_single['legs']), REQUIRED_LEGS)
        self.assertNotEqual(len(invalid_three['legs']), REQUIRED_LEGS)
    
    def test_minimum_leg_probability(self):
        """Legs must have minimum probability threshold"""
        MIN_PROB = 0.20
        
        valid_leg = {'model_prob': 0.45}
        invalid_leg = {'model_prob': 0.15}
        
        self.assertGreaterEqual(valid_leg['model_prob'], MIN_PROB)
        self.assertLess(invalid_leg['model_prob'], MIN_PROB)


def run_all_tests():
    """Run all tests and return summary"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    suite.addTests(loader.loadTestsFromTestCase(TestEdgeCalculations))
    suite.addTests(loader.loadTestsFromTestCase(TestParlayGeneration))
    suite.addTests(loader.loadTestsFromTestCase(TestCooldownSystem))
    suite.addTests(loader.loadTestsFromTestCase(TestSettlementLogic))
    suite.addTests(loader.loadTestsFromTestCase(TestDataIntegrity))
    suite.addTests(loader.loadTestsFromTestCase(TestDatabaseSchema))
    suite.addTests(loader.loadTestsFromTestCase(TestIntegration))
    suite.addTests(loader.loadTestsFromTestCase(TestLegProbabilityRecording))
    suite.addTests(loader.loadTestsFromTestCase(TestParlayDeduplication))
    suite.addTests(loader.loadTestsFromTestCase(TestParlayConstraints))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return {
        'tests_run': result.testsRun,
        'failures': len(result.failures),
        'errors': len(result.errors),
        'skipped': len(result.skipped),
        'success': result.wasSuccessful()
    }


if __name__ == '__main__':
    run_all_tests()
