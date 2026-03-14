"""
Tests for Multisport V3 Feature Builder, Backfill, and Predictor
"""

import json
import os
import pytest
import math
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch


# ── Section 1: Feature Builder Constants ─────────────────────────────────────

class TestMultisportFeatureBuilderConstants:

    def test_total_feature_count_is_46(self):
        from features.multisport_feature_builder import MultisportFeatureBuilder
        assert len(MultisportFeatureBuilder.ALL_FEATURE_NAMES) == 46

    def test_no_duplicate_feature_names(self):
        from features.multisport_feature_builder import MultisportFeatureBuilder
        names = MultisportFeatureBuilder.ALL_FEATURE_NAMES
        assert len(names) == len(set(names)), "Duplicate feature names found"

    def test_odds_group_count(self):
        from features.multisport_feature_builder import MultisportFeatureBuilder
        assert len(MultisportFeatureBuilder.ODDS_FEATURE_NAMES) == 13

    def test_spread_group_count(self):
        from features.multisport_feature_builder import MultisportFeatureBuilder
        assert len(MultisportFeatureBuilder.SPREAD_FEATURE_NAMES) == 10

    def test_rest_group_count(self):
        from features.multisport_feature_builder import MultisportFeatureBuilder
        assert len(MultisportFeatureBuilder.REST_FEATURE_NAMES) == 6

    def test_form_group_count(self):
        from features.multisport_feature_builder import MultisportFeatureBuilder
        assert len(MultisportFeatureBuilder.FORM_FEATURE_NAMES) == 9

    def test_elo_group_count(self):
        from features.multisport_feature_builder import MultisportFeatureBuilder
        assert len(MultisportFeatureBuilder.ELO_FEATURE_NAMES) == 4

    def test_h2h_group_count(self):
        from features.multisport_feature_builder import MultisportFeatureBuilder
        assert len(MultisportFeatureBuilder.H2H_FEATURE_NAMES) == 2

    def test_season_group_count(self):
        from features.multisport_feature_builder import MultisportFeatureBuilder
        assert len(MultisportFeatureBuilder.SEASON_FEATURE_NAMES) == 2

    def test_get_feature_names_returns_46(self):
        from features.multisport_feature_builder import MultisportFeatureBuilder
        assert len(MultisportFeatureBuilder.get_feature_names()) == 46

    def test_all_groups_sum_to_total(self):
        from features.multisport_feature_builder import MultisportFeatureBuilder as B
        total = (len(B.ODDS_FEATURE_NAMES) + len(B.SPREAD_FEATURE_NAMES) +
                 len(B.REST_FEATURE_NAMES) + len(B.FORM_FEATURE_NAMES) +
                 len(B.ELO_FEATURE_NAMES) + len(B.H2H_FEATURE_NAMES) +
                 len(B.SEASON_FEATURE_NAMES))
        assert total == 46

    def test_key_feature_names_present(self):
        from features.multisport_feature_builder import MultisportFeatureBuilder
        names = MultisportFeatureBuilder.ALL_FEATURE_NAMES
        for expected in ['prob_home', 'spread_line', 'home_rest_days', 'home_is_b2b',
                         'home_win_rate_l10', 'home_elo', 'elo_diff',
                         'h2h_home_win_rate', 'season_progress']:
            assert expected in names, f"Missing: {expected}"


# ── Section 2: FastBatchBuilder ───────────────────────────────────────────────

class TestFastBatchBuilder:

    def _make_builder(self, sport_key='basketball_nba'):
        from jobs.backfill_multisport_features import FastBatchBuilder
        return FastBatchBuilder(sport_key, 'mock://')

    def test_empty_records_returns_empty(self):
        b = self._make_builder()
        results, errors = b.build_all.__func__(b, [])
        assert results == []
        assert errors == 0

    def test_elo_starts_at_default(self):
        from features.multisport_feature_builder import ELO_START
        b = self._make_builder()
        # ELO state starts empty → teams get ELO_START
        elo_state = {}
        rec = {
            'event_id': 'e1', 'home_team': 'Lakers', 'away_team': 'Celtics',
            'match_date': date(2026, 1, 15),
        }
        feats = b._compute_features(
            rec=rec,
            cutoff=date(2026, 1, 15),
            odds_row=None,
            elo_state=elo_state,
            team_history={},
            fixture_lookup={},
        )
        assert feats['home_elo'] == pytest.approx(ELO_START)
        assert feats['away_elo'] == pytest.approx(ELO_START)

    def test_elo_diff_is_home_minus_away_plus_advantage(self):
        from features.multisport_feature_builder import ELO_START, ELO_HOME_ADV
        b = self._make_builder()
        elo_state = {'Lakers': 1550.0, 'Celtics': 1480.0}
        rec = {'event_id': 'e1', 'home_team': 'Lakers', 'away_team': 'Celtics',
               'match_date': date(2026, 1, 15)}
        feats = b._compute_features(rec, date(2026, 1, 15), None, elo_state, {}, {})
        expected_diff = 1550.0 + ELO_HOME_ADV - 1480.0
        assert feats['elo_diff'] == pytest.approx(expected_diff)

    def test_rest_days_computed_correctly(self):
        b = self._make_builder()
        from datetime import timezone as tz
        game_dt = datetime(2026, 1, 15, 0, 0, tzinfo=tz.utc)
        last_dt  = datetime(2026, 1, 13, 0, 0, tzinfo=tz.utc)
        fixture_lookup = {'Lakers': [last_dt], 'Celtics': []}
        rec = {'event_id': 'e1', 'home_team': 'Lakers', 'away_team': 'Celtics',
               'match_date': date(2026, 1, 15)}
        feats = b._compute_features(rec, date(2026, 1, 15), None, {}, {}, fixture_lookup)
        assert feats['home_rest_days'] == pytest.approx(2.0)

    def test_back_to_back_detected(self):
        from datetime import timezone as tz
        b = self._make_builder()
        yesterday = datetime(2026, 1, 14, 20, 0, tzinfo=tz.utc)   # ~20 hours ago
        game_date = date(2026, 1, 15)
        cutoff_dt = datetime(2026, 1, 15, 16, 0, tzinfo=tz.utc)
        fixture_lookup = {'Lakers': [yesterday], 'Celtics': []}
        rec = {'event_id': 'e1', 'home_team': 'Lakers', 'away_team': 'Celtics',
               'match_date': game_date}
        feats = b._compute_features(rec, game_date, None, {}, {}, fixture_lookup)
        assert feats['home_is_b2b'] == 1.0

    def test_no_b2b_when_rested(self):
        from datetime import timezone as tz
        b = self._make_builder()
        three_days_ago = datetime(2026, 1, 12, 0, 0, tzinfo=tz.utc)
        fixture_lookup = {'Lakers': [three_days_ago], 'Celtics': []}
        rec = {'event_id': 'e1', 'home_team': 'Lakers', 'away_team': 'Celtics',
               'match_date': date(2026, 1, 15)}
        feats = b._compute_features(rec, date(2026, 1, 15), None, {}, {}, fixture_lookup)
        assert feats['home_is_b2b'] == 0.0

    def test_rest_advantage_sign(self):
        from datetime import timezone as tz
        b = self._make_builder()
        fixture_lookup = {
            'Lakers':  [datetime(2026, 1, 14, 0, 0, tzinfo=tz.utc)],  # 1 day rest
            'Celtics': [datetime(2026, 1, 12, 0, 0, tzinfo=tz.utc)],  # 3 days rest
        }
        rec = {'event_id': 'e1', 'home_team': 'Lakers', 'away_team': 'Celtics',
               'match_date': date(2026, 1, 15)}
        feats = b._compute_features(rec, date(2026, 1, 15), None, {}, {}, fixture_lookup)
        # home less rested → rest_advantage should be negative
        assert feats['rest_advantage'] < 0

    def test_form_50pct_with_no_history(self):
        b = self._make_builder()
        rec = {'event_id': 'e1', 'home_team': 'Lakers', 'away_team': 'Celtics',
               'match_date': date(2026, 1, 15)}
        feats = b._compute_features(rec, date(2026, 1, 15), None, {}, {}, {})
        assert feats['home_win_rate_l10'] == pytest.approx(0.5)
        assert feats['away_win_rate_l10'] == pytest.approx(0.5)

    def test_h2h_defaults_to_0_5_with_no_history(self):
        b = self._make_builder()
        rec = {'event_id': 'e1', 'home_team': 'Lakers', 'away_team': 'Celtics',
               'match_date': date(2026, 1, 15)}
        feats = b._compute_features(rec, date(2026, 1, 15), None, {}, {}, {})
        assert feats['h2h_home_win_rate'] == pytest.approx(0.5)
        assert feats['h2h_matches_used'] == 0.0

    def test_season_progress_mid_season(self):
        b = self._make_builder('basketball_nba')
        rec = {'event_id': 'e1', 'home_team': 'A', 'away_team': 'B',
               'match_date': date(2026, 1, 15)}   # ~mid-NBA-season
        feats = b._compute_features(rec, date(2026, 1, 15), None, {}, {}, {})
        # Jan 15 is roughly 50% through the Oct→Apr season
        assert 0.3 < feats['season_progress'] < 0.8

    def test_all_46_features_present_in_output(self):
        from features.multisport_feature_builder import MultisportFeatureBuilder
        b = self._make_builder()
        rec = {'event_id': 'e1', 'home_team': 'A', 'away_team': 'B',
               'match_date': date(2026, 1, 15)}
        feats = b._compute_features(rec, date(2026, 1, 15), None, {}, {}, {})
        for name in MultisportFeatureBuilder.get_feature_names():
            assert name in feats, f"Missing feature: {name}"

    def test_elo_win_prob_bounded(self):
        b = self._make_builder()
        elo_state = {'A': 1700.0, 'B': 1300.0}   # large difference
        rec = {'event_id': 'e1', 'home_team': 'A', 'away_team': 'B',
               'match_date': date(2026, 1, 15)}
        feats = b._compute_features(rec, date(2026, 1, 15), None, elo_state, {}, {})
        assert 0.0 < feats['elo_home_win_prob'] < 1.0

    def test_pts_diff_clamped_to_30(self):
        """Points diff must be clamped to ±30 to prevent extreme outliers."""
        b = self._make_builder()
        # 20 wins by 40 each = avg pts_diff of 40 → should clamp to 30
        history = {
            'A': [('A', 'X', 'H', 140, 100, date(2025, 12, i)) for i in range(1, 21)],
        }
        rec = {'event_id': 'e1', 'home_team': 'A', 'away_team': 'B',
               'match_date': date(2026, 1, 15)}
        feats = b._compute_features(rec, date(2026, 1, 15), None, {}, history, {})
        assert feats['home_pts_diff_avg'] <= 30.0


# ── Section 3: ELO Mechanics ──────────────────────────────────────────────────

class TestEloMechanics:

    def test_winner_gains_elo_loser_loses(self):
        from features.multisport_feature_builder import ELO_START, ELO_K
        b_class = __import__('jobs.backfill_multisport_features',
                              fromlist=['FastBatchBuilder']).FastBatchBuilder
        elo_state = {}

        # Simulate one game: A wins at home
        hr = elo_state.get('A', float(ELO_START))
        ar = elo_state.get('B', float(ELO_START))
        expected_h = 1.0 / (1.0 + 10 ** ((ar - hr) / 400))
        elo_state['A'] = hr + ELO_K * (1.0 - expected_h)
        elo_state['B'] = ar + ELO_K * (0.0 - (1 - expected_h))

        assert elo_state['A'] > ELO_START, "Winner should gain ELO"
        assert elo_state['B'] < ELO_START, "Loser should lose ELO"

    def test_elo_sum_conserved(self):
        from features.multisport_feature_builder import ELO_START, ELO_K
        hr = float(ELO_START)
        ar = float(ELO_START)
        expected_h = 1.0 / (1.0 + 10 ** ((ar - hr) / 400))
        new_hr = hr + ELO_K * (1.0 - expected_h)
        new_ar = ar + ELO_K * (0.0 - (1 - expected_h))
        assert abs((new_hr + new_ar) - (hr + ar)) < 0.001

    def test_equal_teams_50pct_win_prob(self):
        from features.multisport_feature_builder import ELO_START, ELO_HOME_ADV
        diff  = ELO_START + ELO_HOME_ADV - ELO_START
        prob  = 1.0 / (1.0 + 10 ** (-diff / 400))
        # With home advantage, home team should be > 50%
        assert prob > 0.5

    def test_large_elo_gap_near_certain(self):
        from features.multisport_feature_builder import ELO_HOME_ADV
        diff = 1800 + ELO_HOME_ADV - 1200
        prob = 1.0 / (1.0 + 10 ** (-diff / 400))
        assert prob > 0.95


# ── Section 4: Team Stats Collection ─────────────────────────────────────────

class TestTeamStatsCollection:

    def test_parse_record_string(self):
        from jobs.collect_multisport_team_stats import parse_record
        assert parse_record('24-10') == (24, 10)
        assert parse_record('0-0')   == (0, 0)
        assert parse_record(None)    == (0, 0)
        assert parse_record('')      == (0, 0)

    def test_nba_standings_computed_from_results(self):
        """NBA standings computation logic produces correct win rates."""
        import os
        db_url = os.getenv('DATABASE_URL')
        if not db_url:
            pytest.skip("No DATABASE_URL")

        from jobs.collect_multisport_team_stats import run_collection
        result = run_collection()
        assert 'basketball_nba' in result
        assert result['basketball_nba']['saved'] >= 20, "Expected 20+ NBA teams"

    def test_nhl_collection_returns_rows(self):
        """NHL collection should save 30+ teams (32-team league)."""
        import os
        if not os.getenv('DATABASE_URL'):
            pytest.skip("No DATABASE_URL")
        if not (os.getenv('API_SPORTS_KEY') or os.getenv('RAPIDAPI_KEY')):
            pytest.skip("No API key")

        from jobs.collect_multisport_team_stats import run_collection
        result = run_collection()
        assert result['icehockey_nhl']['saved'] > 0


# ── Section 5: Predictor Contract ─────────────────────────────────────────────

class TestMultisportPredictorContract:

    def _load_predictor(self, sport_key='basketball_nba'):
        from models.multisport_v3_predictor import MultisportV3Predictor
        try:
            return MultisportV3Predictor(sport_key)
        except FileNotFoundError:
            pytest.skip(f"Model not yet trained for {sport_key}")

    def test_predictor_loads_nba(self):
        pred = self._load_predictor('basketball_nba')
        assert pred is not None

    def test_predictor_loads_nhl(self):
        pred = self._load_predictor('icehockey_nhl')
        assert pred is not None

    def test_feature_count_is_46(self):
        pred = self._load_predictor()
        assert len(pred.feature_names) == 46

    def test_model_info_has_required_keys(self):
        pred = self._load_predictor()
        info = pred.get_model_info()
        for key in ['sport_key', 'version', 'n_features', 'accuracy', 'logloss', 'trained_at']:
            assert key in info

    def test_accuracy_above_55_pct(self):
        pred = self._load_predictor('basketball_nba')
        assert pred.accuracy > 0.55, f"NBA accuracy too low: {pred.accuracy:.3f}"

    def test_nhl_accuracy_above_55_pct(self):
        pred = self._load_predictor('icehockey_nhl')
        assert pred.accuracy > 0.55, f"NHL accuracy too low: {pred.accuracy:.3f}"

    def test_predict_from_features_returns_probs_sum_to_1(self):
        pred = self._load_predictor()
        from features.multisport_feature_builder import MultisportFeatureBuilder
        feats = {f: 0.5 for f in MultisportFeatureBuilder.get_feature_names()}
        feats['prob_home'] = 0.65; feats['prob_away'] = 0.35
        result = pred.predict_from_features(feats)
        assert abs(result['prob_home'] + result['prob_away'] - 1.0) < 0.01

    def test_predict_from_features_pick_is_h_or_a(self):
        pred = self._load_predictor()
        feats = {f: 0.0 for f in __import__('features.multisport_feature_builder',
                 fromlist=['MultisportFeatureBuilder']).MultisportFeatureBuilder.get_feature_names()}
        result = pred.predict_from_features(feats)
        assert result['pick'] in ('H', 'A')

    def test_predict_from_features_confidence_bounds(self):
        pred = self._load_predictor()
        feats = {f: 0.5 for f in __import__('features.multisport_feature_builder',
                 fromlist=['MultisportFeatureBuilder']).MultisportFeatureBuilder.get_feature_names()}
        result = pred.predict_from_features(feats)
        assert 0.5 <= result['confidence'] <= 1.0

    def test_heavy_favorite_wins_prediction(self):
        """When prob_home=0.95, model should strongly predict home win."""
        pred = self._load_predictor()
        feats = {f: 0.0 for f in __import__('features.multisport_feature_builder',
                 fromlist=['MultisportFeatureBuilder']).MultisportFeatureBuilder.get_feature_names()}
        feats['prob_home']    = 0.95
        feats['prob_away']    = 0.05
        feats['prob_diff']    = 0.90
        feats['spread_line']  = -12.0
        feats['elo_diff']     = 200.0
        result = pred.predict_from_features(feats)
        assert result['pick'] == 'H', "Heavy home favorite should predict H"


# ── Section 6: Backfill Idempotency ──────────────────────────────────────────

class TestBackfillIdempotency:

    def test_backfill_run_on_empty_returns_zero(self):
        """Running backfill when nothing is missing should process 0 records."""
        import os
        if not os.getenv('DATABASE_URL'):
            pytest.skip("No DATABASE_URL")
        from jobs.backfill_multisport_features import get_unfeaturised_records
        import psycopg2
        conn = psycopg2.connect(os.getenv('DATABASE_URL'))
        # NBA should have no unfeaturised records after backfill
        recs = get_unfeaturised_records(conn, 'basketball_nba')
        conn.close()
        assert len(recs) == 0, f"Expected 0 unfeaturised NBA records, got {len(recs)}"

    def test_backfill_nhl_empty_after_run(self):
        import os
        if not os.getenv('DATABASE_URL'):
            pytest.skip("No DATABASE_URL")
        from jobs.backfill_multisport_features import get_unfeaturised_records
        import psycopg2
        conn = psycopg2.connect(os.getenv('DATABASE_URL'))
        recs = get_unfeaturised_records(conn, 'icehockey_nhl')
        conn.close()
        assert len(recs) == 0, f"Expected 0 unfeaturised NHL records, got {len(recs)}"
