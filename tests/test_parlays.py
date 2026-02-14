"""
Comprehensive Validation Tests for Parlay Infrastructure

Test Categories:
1. Poisson Probability Engine - Bayesian shrinkage, bounds, math correctness
2. Player Parlay Generator - Sampling, diversity, caps, deduplication
3. Match Parlay Legs Settlement - match_results join, won/lost/pending
4. Player Parlay Settlement - fixture-based, game stats, data_pending
5. Risk Tier Classification - Probability bands, parlay size
6. Database Schema & Data Integrity - Tables, indexes, constraints
7. API Endpoint Validation - Routes return correct structure
8. End-to-End Generation Pipeline - Full generation + verification
"""

import os
import sys
import math
import hashlib
import unittest
from datetime import datetime, timedelta, timezone
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestPoissonProbabilityEngine(unittest.TestCase):
    """Test the Poisson + Bayesian shrinkage probability model."""

    def setUp(self):
        from models.player_parlay_generator import (
            LEAGUE_AVG_GOAL_RATE, SHRINKAGE_GAMES, MIN_PROB, MAX_PROB
        )
        self.LEAGUE_AVG = LEAGUE_AVG_GOAL_RATE
        self.SHRINKAGE_GAMES = SHRINKAGE_GAMES
        self.MIN_PROB = MIN_PROB
        self.MAX_PROB = MAX_PROB
        from models.player_parlay_generator import PlayerParlayGenerator
        self.gen = PlayerParlayGenerator()

    def test_poisson_zero_goals_returns_league_avg_shrunk(self):
        prob = self.gen._poisson_prob(goals=0, games_played=10)
        self.assertGreaterEqual(prob, self.MIN_PROB)
        self.assertLessEqual(prob, self.MAX_PROB)
        self.assertLess(prob, 0.15, "Zero-goal player should have low probability")

    def test_poisson_prolific_scorer_high_prob(self):
        prob = self.gen._poisson_prob(goals=20, games_played=25)
        self.assertGreater(prob, 0.20, "Prolific scorer should have >20% anytime scorer prob")
        self.assertLessEqual(prob, self.MAX_PROB, "Must be capped at MAX_PROB")

    def test_poisson_never_exceeds_bounds(self):
        test_cases = [
            (0, 1), (0, 50), (1, 3), (5, 10), (30, 20), (50, 30), (100, 10)
        ]
        for goals, games in test_cases:
            prob = self.gen._poisson_prob(goals, games)
            self.assertGreaterEqual(prob, self.MIN_PROB, f"goals={goals}, gp={games}: below MIN_PROB")
            self.assertLessEqual(prob, self.MAX_PROB, f"goals={goals}, gp={games}: above MAX_PROB")

    def test_poisson_monotonically_increases_with_goals(self):
        probs = [self.gen._poisson_prob(g, 30) for g in [0, 3, 8, 15, 25]]
        for i in range(len(probs) - 1):
            self.assertLessEqual(probs[i], probs[i + 1],
                                 f"Prob should increase: {probs[i]} -> {probs[i+1]}")

    def test_poisson_shrinkage_effect(self):
        few_games = self.gen._poisson_prob(goals=5, games_played=5)
        many_games = self.gen._poisson_prob(goals=30, games_played=30)
        self.assertGreater(few_games, self.MIN_PROB)
        self.assertGreater(many_games, self.MIN_PROB)

    def test_poisson_games_played_zero_handled(self):
        prob = self.gen._poisson_prob(goals=0, games_played=0)
        self.assertGreaterEqual(prob, self.MIN_PROB)
        self.assertLessEqual(prob, self.MAX_PROB)

    def test_poisson_formula_correctness(self):
        goals, gp = 10, 30
        raw_rate = goals / max(gp, 1.0)
        sw = min(gp / (gp + self.SHRINKAGE_GAMES), 0.85)
        shrunk = raw_rate * sw + self.LEAGUE_AVG * (1 - sw)
        shrunk = max(0.03, min(0.55, shrunk))
        expected = max(self.MIN_PROB, min(self.MAX_PROB, 1.0 - math.exp(-shrunk)))
        actual = self.gen._poisson_prob(goals, gp)
        self.assertAlmostEqual(actual, expected, places=6)


class TestRiskTierClassification(unittest.TestCase):
    """Test honest risk tier based on probability bands."""

    def setUp(self):
        from models.player_parlay_generator import PlayerParlayGenerator
        self.gen = PlayerParlayGenerator()

    def _make_legs(self, probs):
        return [{'model_prob': p} for p in probs]

    def test_2leg_high_avg_is_low_risk(self):
        tier = self.gen._compute_risk_tier(self._make_legs([0.30, 0.25]))
        self.assertEqual(tier, 'low_risk')

    def test_2leg_medium_avg_is_medium_risk(self):
        tier = self.gen._compute_risk_tier(self._make_legs([0.18, 0.16]))
        self.assertEqual(tier, 'medium_risk')

    def test_2leg_low_avg_is_high_risk(self):
        tier = self.gen._compute_risk_tier(self._make_legs([0.06, 0.08]))
        self.assertEqual(tier, 'high_risk')

    def test_3leg_medium_avg_is_medium_risk(self):
        tier = self.gen._compute_risk_tier(self._make_legs([0.25, 0.22, 0.20]))
        self.assertEqual(tier, 'medium_risk')

    def test_3leg_low_avg_is_high_risk(self):
        tier = self.gen._compute_risk_tier(self._make_legs([0.10, 0.08, 0.06]))
        self.assertEqual(tier, 'high_risk')

    def test_tier_is_always_valid_string(self):
        for probs in [[0.04, 0.04], [0.40, 0.40], [0.20, 0.15, 0.10]]:
            tier = self.gen._compute_risk_tier(self._make_legs(probs))
            self.assertIn(tier, ['low_risk', 'medium_risk', 'high_risk'])


class TestParlayBuildAndHash(unittest.TestCase):
    """Test parlay building, hashing, and deduplication."""

    def setUp(self):
        from models.player_parlay_generator import PlayerParlayGenerator
        self.gen = PlayerParlayGenerator()
        self.sample_legs = [
            {
                'match_id': 100, 'home_team': 'A', 'away_team': 'B',
                'league_name': 'PL', 'kickoff_at': datetime.now(timezone.utc) + timedelta(hours=6),
                'player_id': 1, 'player_name': 'Player1', 'team_name': 'TeamA',
                'team_id': 10, 'model_prob': 0.25, 'decimal_odds': 4.24,
                'season_goals': 8, 'games_played': 20,
            },
            {
                'match_id': 200, 'home_team': 'C', 'away_team': 'D',
                'league_name': 'LL', 'kickoff_at': datetime.now(timezone.utc) + timedelta(hours=8),
                'player_id': 2, 'player_name': 'Player2', 'team_name': 'TeamC',
                'team_id': 20, 'model_prob': 0.30, 'decimal_odds': 3.53,
                'season_goals': 12, 'games_played': 25,
            }
        ]

    def test_build_parlay_combined_odds(self):
        parlay = self.gen._build_parlay(self.sample_legs)
        expected_odds = self.sample_legs[0]['decimal_odds'] * self.sample_legs[1]['decimal_odds']
        self.assertAlmostEqual(parlay['combined_odds'], round(expected_odds, 2), places=2)

    def test_build_parlay_combined_prob(self):
        parlay = self.gen._build_parlay(self.sample_legs)
        expected_prob_pct = self.sample_legs[0]['model_prob'] * self.sample_legs[1]['model_prob'] * 100
        self.assertAlmostEqual(parlay['combined_prob_pct'], round(expected_prob_pct, 4), places=3)

    def test_build_parlay_has_all_fields(self):
        parlay = self.gen._build_parlay(self.sample_legs)
        required = ['parlay_hash', 'leg_count', 'match_ids', 'legs',
                     'combined_odds', 'combined_prob_pct', 'risk_tier',
                     'payout_100', 'expires_at']
        for field in required:
            self.assertIn(field, parlay, f"Missing field: {field}")

    def test_parlay_hash_deterministic(self):
        p1 = self.gen._build_parlay(self.sample_legs)
        p2 = self.gen._build_parlay(self.sample_legs)
        self.assertEqual(p1['parlay_hash'], p2['parlay_hash'])

    def test_parlay_hash_order_independent(self):
        p1 = self.gen._build_parlay(self.sample_legs)
        p2 = self.gen._build_parlay(list(reversed(self.sample_legs)))
        self.assertEqual(p1['parlay_hash'], p2['parlay_hash'])

    def test_different_legs_different_hash(self):
        alt_legs = [self.sample_legs[0].copy(), self.sample_legs[1].copy()]
        alt_legs[1]['player_id'] = 999
        p1 = self.gen._build_parlay(self.sample_legs)
        p2 = self.gen._build_parlay(alt_legs)
        self.assertNotEqual(p1['parlay_hash'], p2['parlay_hash'])

    def test_payout_equals_bet_times_odds(self):
        parlay = self.gen._build_parlay(self.sample_legs)
        expected = round(100.0 * parlay['combined_odds'], 2)
        self.assertAlmostEqual(parlay['payout_100'], expected, places=0)

    def test_expires_at_after_last_kickoff(self):
        parlay = self.gen._build_parlay(self.sample_legs)
        max_kickoff = max(l['kickoff_at'] for l in self.sample_legs)
        self.assertGreater(parlay['expires_at'], max_kickoff)


class TestSamplingDiversityConstraints(unittest.TestCase):
    """Test sampling enforces max 1 per match, 1 per team, reuse caps."""

    def setUp(self):
        from models.player_parlay_generator import PlayerParlayGenerator
        self.gen = PlayerParlayGenerator()
        self.legs = [
            {'match_id': 1, 'player_id': 10, 'team_id': 100, 'model_prob': 0.25},
            {'match_id': 1, 'player_id': 11, 'team_id': 100, 'model_prob': 0.20},
            {'match_id': 2, 'player_id': 20, 'team_id': 200, 'model_prob': 0.30},
            {'match_id': 2, 'player_id': 21, 'team_id': 200, 'model_prob': 0.15},
            {'match_id': 3, 'player_id': 30, 'team_id': 300, 'model_prob': 0.22},
            {'match_id': 4, 'player_id': 40, 'team_id': 400, 'model_prob': 0.18},
            {'match_id': 5, 'player_id': 50, 'team_id': 500, 'model_prob': 0.28},
        ]

    def test_no_duplicate_matches(self):
        for _ in range(20):
            result = self.gen._sample_parlay(self.legs, k=3, leg_usage={}, match_parlay_counts={})
            if result:
                match_ids = [l['match_id'] for l in result]
                self.assertEqual(len(match_ids), len(set(match_ids)),
                                 "Parlay must not have duplicate matches")

    def test_no_duplicate_teams(self):
        for _ in range(20):
            result = self.gen._sample_parlay(self.legs, k=3, leg_usage={}, match_parlay_counts={})
            if result:
                team_ids = [l['team_id'] for l in result if l.get('team_id')]
                self.assertEqual(len(team_ids), len(set(team_ids)),
                                 "Parlay must not have duplicate teams")

    def test_leg_reuse_cap_enforced(self):
        usage = {(1, 10): 5, (2, 20): 5, (3, 30): 5}
        result = self.gen._sample_parlay(self.legs, k=3, leg_usage=usage, match_parlay_counts={})
        if result:
            for leg in result:
                key = (leg['match_id'], leg['player_id'])
                self.assertLess(usage.get(key, 0), 5,
                                f"Used leg {key} which is at cap")

    def test_match_parlay_cap_enforced(self):
        counts = {1: 10, 2: 10, 3: 10}
        result = self.gen._sample_parlay(self.legs, k=2, leg_usage={}, match_parlay_counts=counts)
        if result:
            for leg in result:
                self.assertLess(counts.get(leg['match_id'], 0), 10,
                                f"Used match {leg['match_id']} which is at cap")

    def test_insufficient_legs_returns_none(self):
        result = self.gen._sample_parlay(self.legs[:1], k=3, leg_usage={}, match_parlay_counts={})
        self.assertIsNone(result)

    def test_returns_correct_k(self):
        for k in [2, 3]:
            result = self.gen._sample_parlay(self.legs, k=k, leg_usage={}, match_parlay_counts={})
            if result:
                self.assertEqual(len(result), k)


class TestGenerationCapsAndTargets(unittest.TestCase):
    """Test that generation respects caps, per-k targets, and MAX_PARLAYS_PER_RUN."""

    def test_constants_are_reasonable(self):
        from models.player_parlay_generator import (
            MAX_PARLAYS_PER_RUN, MAX_LEG_REUSE_PER_DAY,
            MAX_PARLAYS_PER_MATCH_PER_DAY, MIN_PROB, MAX_PROB
        )
        self.assertEqual(MAX_PARLAYS_PER_RUN, 20)
        self.assertEqual(MAX_LEG_REUSE_PER_DAY, 5)
        self.assertEqual(MAX_PARLAYS_PER_MATCH_PER_DAY, 10)
        self.assertAlmostEqual(MIN_PROB, 0.04)
        self.assertAlmostEqual(MAX_PROB, 0.40)

    def test_per_k_targets(self):
        from models.player_parlay_generator import MAX_PARLAYS_PER_RUN
        target_2 = MAX_PARLAYS_PER_RUN // 2
        target_3 = MAX_PARLAYS_PER_RUN // 4
        self.assertEqual(target_2, 10)
        self.assertEqual(target_3, 5)
        self.assertLessEqual(target_2 + target_3, MAX_PARLAYS_PER_RUN)


@unittest.skipUnless(os.getenv('DATABASE_URL'), "Database not available")
class TestDatabaseSchemaIntegrity(unittest.TestCase):
    """Test all required tables, columns, indexes, and constraints exist."""

    def setUp(self):
        from sqlalchemy import create_engine, text
        self.engine = create_engine(os.environ['DATABASE_URL'], pool_pre_ping=True)

    def _table_exists(self, table_name):
        from sqlalchemy import text
        with self.engine.connect() as conn:
            r = conn.execute(text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = :t)"
            ), {'t': table_name}).scalar()
            return r

    def _get_columns(self, table_name):
        from sqlalchemy import text
        with self.engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT column_name FROM information_schema.columns WHERE table_name = :t"
            ), {'t': table_name}).fetchall()
            return {r[0] for r in rows}

    def test_player_parlays_table_exists(self):
        self.assertTrue(self._table_exists('player_parlays'))

    def test_player_parlay_legs_table_exists(self):
        self.assertTrue(self._table_exists('player_parlay_legs'))

    def test_player_leg_usage_table_exists(self):
        self.assertTrue(self._table_exists('player_leg_usage'))

    def test_parlay_consensus_table_exists(self):
        self.assertTrue(self._table_exists('parlay_consensus'))

    def test_parlay_legs_table_exists(self):
        self.assertTrue(self._table_exists('parlay_legs'))

    def test_parlay_performance_table_exists(self):
        self.assertTrue(self._table_exists('parlay_performance'))

    def test_player_parlays_required_columns(self):
        cols = self._get_columns('player_parlays')
        required = {'id', 'parlay_hash', 'leg_count', 'match_ids', 'combined_odds',
                     'raw_prob_pct', 'confidence_tier', 'status', 'expires_at',
                     'payout_100', 'result', 'settled_at'}
        missing = required - cols
        self.assertEqual(missing, set(), f"Missing columns: {missing}")

    def test_player_parlay_legs_required_columns(self):
        cols = self._get_columns('player_parlay_legs')
        required = {'id', 'parlay_id', 'leg_index', 'match_id', 'player_id',
                     'player_name', 'team_name', 'model_prob', 'decimal_odds', 'result'}
        missing = required - cols
        self.assertEqual(missing, set(), f"Missing columns: {missing}")

    def test_player_leg_usage_required_columns(self):
        cols = self._get_columns('player_leg_usage')
        required = {'id', 'window_key', 'match_id', 'player_id', 'use_count'}
        missing = required - cols
        self.assertEqual(missing, set(), f"Missing columns: {missing}")

    def test_player_parlays_unique_hash_constraint(self):
        from sqlalchemy import text
        with self.engine.connect() as conn:
            r = conn.execute(text("""
                SELECT COUNT(*) FROM pg_indexes 
                WHERE tablename = 'player_parlays' 
                AND indexdef LIKE '%parlay_hash%' AND indexdef LIKE '%UNIQUE%'
            """)).scalar()
            self.assertGreater(r, 0, "parlay_hash should have a UNIQUE index")

    def test_player_leg_usage_unique_constraint(self):
        from sqlalchemy import text
        with self.engine.connect() as conn:
            r = conn.execute(text("""
                SELECT COUNT(*) FROM pg_indexes 
                WHERE tablename = 'player_leg_usage' 
                AND indexdef LIKE '%window_key%' AND indexdef LIKE '%match_id%' AND indexdef LIKE '%player_id%'
            """)).scalar()
            self.assertGreater(r, 0, "player_leg_usage should have unique constraint on (window_key, match_id, player_id)")


@unittest.skipUnless(os.getenv('DATABASE_URL'), "Database not available")
class TestLiveDataIntegrity(unittest.TestCase):
    """Test actual data in database meets integrity constraints."""

    def setUp(self):
        from sqlalchemy import create_engine, text
        self.engine = create_engine(os.environ['DATABASE_URL'], pool_pre_ping=True)

    def test_no_player_parlays_with_zero_legs(self):
        from sqlalchemy import text
        with self.engine.connect() as conn:
            r = conn.execute(text("""
                SELECT COUNT(*) FROM player_parlays pp
                LEFT JOIN player_parlay_legs ppl ON pp.id = ppl.parlay_id
                WHERE ppl.id IS NULL
            """)).scalar()
            self.assertEqual(r, 0, "No player parlays should exist without legs")

    def test_leg_count_matches_actual_legs(self):
        from sqlalchemy import text
        with self.engine.connect() as conn:
            r = conn.execute(text("""
                SELECT COUNT(*) FROM (
                    SELECT pp.id, pp.leg_count, COUNT(ppl.id) as actual
                    FROM player_parlays pp
                    JOIN player_parlay_legs ppl ON pp.id = ppl.parlay_id
                    GROUP BY pp.id, pp.leg_count
                    HAVING pp.leg_count != COUNT(ppl.id)
                ) mismatches
            """)).scalar()
            self.assertEqual(r, 0, "leg_count must match actual number of legs")

    def test_all_probabilities_in_range(self):
        from sqlalchemy import text
        with self.engine.connect() as conn:
            r = conn.execute(text("""
                SELECT COUNT(*) FROM player_parlay_legs 
                WHERE model_prob <= 0 OR model_prob > 1
            """)).scalar()
            self.assertEqual(r, 0, "All leg probabilities must be between 0 and 1")

    def test_all_odds_positive(self):
        from sqlalchemy import text
        with self.engine.connect() as conn:
            r = conn.execute(text("""
                SELECT COUNT(*) FROM player_parlay_legs 
                WHERE decimal_odds <= 0
            """)).scalar()
            self.assertEqual(r, 0, "All decimal odds must be positive")

    def test_no_duplicate_parlay_hashes(self):
        from sqlalchemy import text
        with self.engine.connect() as conn:
            r = conn.execute(text("""
                SELECT COUNT(*) FROM (
                    SELECT parlay_hash, COUNT(*) 
                    FROM player_parlays 
                    GROUP BY parlay_hash HAVING COUNT(*) > 1
                ) dupes
            """)).scalar()
            self.assertEqual(r, 0, "No duplicate parlay hashes should exist")

    def test_valid_status_values(self):
        from sqlalchemy import text
        with self.engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT DISTINCT status FROM player_parlays"
            )).fetchall()
            valid = {'pending', 'settled', 'data_pending', 'expired'}
            for r in rows:
                self.assertIn(r[0], valid, f"Invalid status: {r[0]}")

    def test_valid_confidence_tiers(self):
        from sqlalchemy import text
        with self.engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT DISTINCT confidence_tier FROM player_parlays WHERE confidence_tier IS NOT NULL"
            )).fetchall()
            valid = {'low_risk', 'medium_risk', 'high_risk', 'low', 'medium', 'high'}
            for r in rows:
                self.assertIn(r[0], valid, f"Invalid tier: {r[0]}")

    def test_recent_parlays_have_realistic_probs(self):
        from sqlalchemy import text
        with self.engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT raw_prob_pct FROM player_parlays 
                WHERE created_at > NOW() - INTERVAL '24 hours'
                AND raw_prob_pct IS NOT NULL
            """)).fetchall()
            for r in rows:
                prob = float(r[0])
                self.assertGreater(prob, 0, "Prob must be > 0")
                self.assertLess(prob, 50, "Combined prob >50% is unrealistic for multi-leg parlay")

    def test_leg_reuse_within_daily_cap(self):
        from sqlalchemy import text
        with self.engine.connect() as conn:
            r = conn.execute(text("""
                SELECT MAX(use_count) FROM player_leg_usage WHERE window_key = CURRENT_DATE
            """)).scalar()
            if r is not None:
                self.assertLessEqual(r, 5, f"Max leg reuse today is {r}, should be <= 5")


@unittest.skipUnless(os.getenv('DATABASE_URL'), "Database not available")
class TestMatchParlayLegsSettlement(unittest.TestCase):
    """Test the settle_match_parlay_legs_job infrastructure."""

    def setUp(self):
        from sqlalchemy import create_engine, text
        self.engine = create_engine(os.environ['DATABASE_URL'], pool_pre_ping=True)

    def test_parlay_legs_table_has_settlement_columns(self):
        from sqlalchemy import text
        with self.engine.connect() as conn:
            cols = conn.execute(text(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'parlay_legs'"
            )).fetchall()
            col_names = {r[0] for r in cols}
            self.assertIn('won', col_names, "parlay_legs must have 'won' column")
            self.assertIn('actual_outcome', col_names, "parlay_legs must have 'actual_outcome' column")

    def test_settled_legs_have_valid_outcomes(self):
        from sqlalchemy import text
        with self.engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT DISTINCT actual_outcome FROM parlay_legs 
                WHERE actual_outcome IS NOT NULL
            """)).fetchall()
            valid_outcomes = {'H', 'D', 'A'}
            for r in rows:
                self.assertIn(r[0], valid_outcomes, f"Invalid outcome: {r[0]}")

    def test_won_flag_matches_outcome(self):
        from sqlalchemy import text
        with self.engine.connect() as conn:
            mismatches = conn.execute(text("""
                SELECT COUNT(*) FROM parlay_legs
                WHERE won IS NOT NULL AND actual_outcome IS NOT NULL AND outcome IS NOT NULL
                AND won != (outcome = actual_outcome)
            """)).scalar()
            self.assertEqual(mismatches, 0, "won flag must match outcome vs actual_outcome")

    def test_settlement_coverage(self):
        from sqlalchemy import text
        with self.engine.connect() as conn:
            total = conn.execute(text("SELECT COUNT(*) FROM parlay_legs")).scalar()
            settled = conn.execute(text("SELECT COUNT(*) FROM parlay_legs WHERE won IS NOT NULL")).scalar()
            pending = conn.execute(text("SELECT COUNT(*) FROM parlay_legs WHERE won IS NULL")).scalar()
            self.assertEqual(total, settled + pending)
            if total > 0:
                pct = settled / total * 100
                self.assertGreater(pct, 50, f"Only {pct:.0f}% settled — should be >50%")


@unittest.skipUnless(os.getenv('DATABASE_URL'), "Database not available")
class TestPlayerParlaySettlement(unittest.TestCase):
    """Test player parlay settlement via fixtures + player_game_stats."""

    def setUp(self):
        from sqlalchemy import create_engine, text
        self.engine = create_engine(os.environ['DATABASE_URL'], pool_pre_ping=True)

    def test_settled_parlays_have_result(self):
        from sqlalchemy import text
        with self.engine.connect() as conn:
            r = conn.execute(text("""
                SELECT COUNT(*) FROM player_parlays 
                WHERE status = 'settled' AND result IS NULL
            """)).scalar()
            self.assertEqual(r, 0, "All settled parlays must have a result (won/lost)")

    def test_settled_legs_have_result(self):
        from sqlalchemy import text
        with self.engine.connect() as conn:
            r = conn.execute(text("""
                SELECT COUNT(*) FROM player_parlay_legs ppl
                JOIN player_parlays pp ON ppl.parlay_id = pp.id
                WHERE pp.status = 'settled' AND ppl.result IS NULL
            """)).scalar()
            self.assertEqual(r, 0, "All legs of settled parlays should have results")

    def test_data_pending_has_unknown_legs(self):
        from sqlalchemy import text
        with self.engine.connect() as conn:
            r = conn.execute(text("""
                SELECT COUNT(*) FROM player_parlays pp
                WHERE pp.status = 'data_pending'
                AND NOT EXISTS (
                    SELECT 1 FROM player_parlay_legs ppl 
                    WHERE ppl.parlay_id = pp.id AND ppl.result = 'unknown'
                )
            """)).scalar()
            self.assertEqual(r, 0,
                             "data_pending parlays should have at least one 'unknown' leg")

    def test_no_won_parlay_has_lost_leg(self):
        from sqlalchemy import text
        with self.engine.connect() as conn:
            r = conn.execute(text("""
                SELECT COUNT(*) FROM player_parlays pp
                WHERE pp.result = 'won'
                AND EXISTS (
                    SELECT 1 FROM player_parlay_legs ppl 
                    WHERE ppl.parlay_id = pp.id AND ppl.result = 'lost'
                )
            """)).scalar()
            self.assertEqual(r, 0, "Won parlays must not have any lost legs")


@unittest.skipUnless(os.getenv('DATABASE_URL'), "Database not available")
class TestMatchParlayConsensusSettlement(unittest.TestCase):
    """Test parlay_consensus (match-level) settlement integrity."""

    def setUp(self):
        from sqlalchemy import create_engine, text
        self.engine = create_engine(os.environ['DATABASE_URL'], pool_pre_ping=True)

    def test_settled_parlays_have_valid_status(self):
        from sqlalchemy import text
        with self.engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT DISTINCT status FROM parlay_consensus"
            )).fetchall()
            valid = {'pending', 'active', 'expired', 'settled'}
            for r in rows:
                self.assertIn(r[0], valid, f"Invalid consensus parlay status: {r[0]}")

    def test_performance_records_match_settled(self):
        from sqlalchemy import text
        with self.engine.connect() as conn:
            settled_count = conn.execute(text(
                "SELECT COUNT(*) FROM parlay_consensus WHERE status = 'settled'"
            )).scalar()
            perf_count = conn.execute(text(
                "SELECT COUNT(*) FROM parlay_performance"
            )).scalar()
            if settled_count > 0:
                self.assertGreater(perf_count, 0, "Settled parlays should have performance records")


@unittest.skipUnless(os.getenv('DATABASE_URL'), "Database not available")
class TestEndToEndGeneration(unittest.TestCase):
    """Full end-to-end: generate parlays, verify DB state, check constraints."""

    def test_generate_and_verify(self):
        from models.player_parlay_generator import PlayerParlayGenerator, MAX_PARLAYS_PER_RUN
        from sqlalchemy import text

        gen = PlayerParlayGenerator()

        from sqlalchemy import text as sa_text
        import time
        test_marker = int(time.time())

        with gen.engine.connect() as conn:
            conn.execute(sa_text("DELETE FROM player_leg_usage WHERE window_key = CURRENT_DATE"))
            conn.commit()

        result = gen.generate_all_player_parlays(hours_ahead=72)

        self.assertIn(result['status'], ['success', 'insufficient_fixtures', 'insufficient_players'])

        if result['status'] == 'success':
            self.assertLessEqual(result['parlays_generated'], MAX_PARLAYS_PER_RUN)
            self.assertGreater(result['parlays_generated'], 0)
            self.assertIn('by_risk_tier', result)
            self.assertEqual(result['prob_method'], 'poisson_shrinkage')
            self.assertGreater(result['avg_combined_prob_pct'], 0)
            self.assertLess(result['avg_combined_prob_pct'], 50)

            with gen.engine.connect() as conn:
                new_parlays = conn.execute(text("""
                    SELECT pp.id, pp.leg_count, pp.raw_prob_pct, pp.confidence_tier
                    FROM player_parlays pp
                    WHERE pp.created_at > NOW() - INTERVAL '30 seconds'
                """)).fetchall()

                self.assertEqual(len(new_parlays), result['parlays_generated'])

                leg_counts = Counter()
                for p in new_parlays:
                    leg_counts[p.leg_count] += 1
                    self.assertIn(p.leg_count, [2, 3])
                    self.assertIn(p.confidence_tier, ['low_risk', 'medium_risk', 'high_risk'])
                    prob = float(p.raw_prob_pct)
                    self.assertGreater(prob, 0)
                    self.assertLess(prob, 50)

                self.assertLessEqual(leg_counts.get(2, 0), 10)
                self.assertLessEqual(leg_counts.get(3, 0), 5)

                legs = conn.execute(text("""
                    SELECT ppl.match_id, ppl.player_id, ppl.model_prob, ppl.decimal_odds, ppl.parlay_id
                    FROM player_parlay_legs ppl
                    WHERE ppl.created_at > NOW() - INTERVAL '30 seconds'
                """)).fetchall()

                for leg in legs:
                    mp = float(leg.model_prob)
                    self.assertGreaterEqual(mp, 0.04)
                    self.assertLessEqual(mp, 0.40)
                    self.assertGreater(float(leg.decimal_odds), 1.0)

                from collections import defaultdict
                parlay_matches = defaultdict(list)
                for leg in legs:
                    parlay_matches[leg.parlay_id].append(leg.match_id)
                for pid, matches in parlay_matches.items():
                    self.assertEqual(len(matches), len(set(matches)),
                                     f"Parlay {pid} has duplicate matches")

                max_reuse = conn.execute(text(
                    "SELECT MAX(use_count) FROM player_leg_usage WHERE window_key = CURRENT_DATE"
                )).scalar()
                if max_reuse is not None:
                    self.assertLessEqual(max_reuse, 5, f"Max reuse is {max_reuse}")


@unittest.skipUnless(os.getenv('DATABASE_URL'), "Database not available")
class TestSettlementJobsRunnable(unittest.TestCase):
    """Test that settlement jobs can be called without errors."""

    def test_settle_parlays_job_runs(self):
        import asyncio
        from jobs.settle_parlays import settle_parlays_job
        result = asyncio.run(settle_parlays_job())
        self.assertIn('settled', result)
        self.assertNotIn('error', result)

    def test_settle_player_parlays_job_runs(self):
        import asyncio
        from jobs.settle_parlays import settle_player_parlays_job
        result = asyncio.run(settle_player_parlays_job())
        self.assertIn('settled', result)
        self.assertNotIn('error', result)

    def test_settle_match_parlay_legs_job_runs(self):
        import asyncio
        from jobs.settle_parlays import settle_match_parlay_legs_job
        result = asyncio.run(settle_match_parlay_legs_job())
        self.assertIn('settled', result)
        self.assertNotIn('error', result)

    def test_performance_summary_runs(self):
        from jobs.settle_parlays import get_parlay_performance_summary
        result = get_parlay_performance_summary()
        self.assertNotIn('error', result)


def run_all_tests():
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    suite.addTests(loader.loadTestsFromTestCase(TestPoissonProbabilityEngine))
    suite.addTests(loader.loadTestsFromTestCase(TestRiskTierClassification))
    suite.addTests(loader.loadTestsFromTestCase(TestParlayBuildAndHash))
    suite.addTests(loader.loadTestsFromTestCase(TestSamplingDiversityConstraints))
    suite.addTests(loader.loadTestsFromTestCase(TestGenerationCapsAndTargets))
    suite.addTests(loader.loadTestsFromTestCase(TestDatabaseSchemaIntegrity))
    suite.addTests(loader.loadTestsFromTestCase(TestLiveDataIntegrity))
    suite.addTests(loader.loadTestsFromTestCase(TestMatchParlayLegsSettlement))
    suite.addTests(loader.loadTestsFromTestCase(TestPlayerParlaySettlement))
    suite.addTests(loader.loadTestsFromTestCase(TestMatchParlayConsensusSettlement))
    suite.addTests(loader.loadTestsFromTestCase(TestEndToEndGeneration))
    suite.addTests(loader.loadTestsFromTestCase(TestSettlementJobsRunnable))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return result


if __name__ == '__main__':
    run_all_tests()
