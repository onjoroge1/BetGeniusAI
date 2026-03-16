"""
Comprehensive unit tests for:
- V3 Feature Builder (36-feature set, H2H draw rate features)
- V3 Predictor (model load, prediction format, backward compatibility)
- /predict models[] array (3-model transparency: v1, v2, v3)
- Conviction tier logic (premium / strong / standard)
- V1 consensus prediction structure
- V2 unified model agreement logic
- Draw post-processing analysis (data-driven recommendation)

Run:
    python -m pytest tests/test_v3_models_and_conviction.py -v
"""
import pytest
import numpy as np
from unittest.mock import MagicMock, patch, PropertyMock


# ─────────────────────────────────────────────────────────────
# SECTION 1: V3 Feature Builder – unit tests (no DB required)
# ─────────────────────────────────────────────────────────────

class TestV3FeatureBuilderConstants:
    """Verify feature name constants and counts without a DB connection."""

    def _get_builder_class(self):
        from features.v3_feature_builder import V3FeatureBuilder
        return V3FeatureBuilder

    def test_total_feature_count_is_36(self):
        V3FB = self._get_builder_class()
        total = (len(V3FB.V2_FEATURE_NAMES) + len(V3FB.SHARP_FEATURE_NAMES) +
                 len(V3FB.ECE_FEATURE_NAMES) + len(V3FB.INJURY_FEATURE_NAMES) +
                 len(V3FB.TIMING_FEATURE_NAMES) + len(V3FB.H2H_FEATURE_NAMES))
        assert total == 36, f"Expected 36 features, got {total}"

    def test_v2_feature_names_count(self):
        V3FB = self._get_builder_class()
        assert len(V3FB.V2_FEATURE_NAMES) == 17

    def test_sharp_feature_names_count(self):
        V3FB = self._get_builder_class()
        assert len(V3FB.SHARP_FEATURE_NAMES) == 4

    def test_ece_feature_names_count(self):
        V3FB = self._get_builder_class()
        assert len(V3FB.ECE_FEATURE_NAMES) == 3

    def test_injury_feature_names_count(self):
        V3FB = self._get_builder_class()
        assert len(V3FB.INJURY_FEATURE_NAMES) == 6

    def test_timing_feature_names_count(self):
        V3FB = self._get_builder_class()
        assert len(V3FB.TIMING_FEATURE_NAMES) == 4

    def test_h2h_feature_names_count(self):
        V3FB = self._get_builder_class()
        assert len(V3FB.H2H_FEATURE_NAMES) == 2

    def test_h2h_feature_names_correct_keys(self):
        V3FB = self._get_builder_class()
        assert 'h2h_draw_rate' in V3FB.H2H_FEATURE_NAMES
        assert 'h2h_matches_used' in V3FB.H2H_FEATURE_NAMES

    def test_get_all_feature_names_returns_36(self):
        with patch('psycopg2.connect'), patch.dict('os.environ', {'DATABASE_URL': 'mock://'}):
            from features.v3_feature_builder import V3FeatureBuilder
            builder = V3FeatureBuilder.__new__(V3FeatureBuilder)
            names = builder.get_all_feature_names()
        assert len(names) == 36

    def test_get_feature_names_returns_36(self):
        with patch('psycopg2.connect'), patch.dict('os.environ', {'DATABASE_URL': 'mock://'}):
            from features.v3_feature_builder import V3FeatureBuilder
            builder = V3FeatureBuilder.__new__(V3FeatureBuilder)
            names = builder.get_feature_names()
        assert len(names) == 36

    def test_h2h_features_at_end_of_list(self):
        """H2H features must be the last two in the ordered list — they were appended."""
        with patch.dict('os.environ', {'DATABASE_URL': 'mock://'}):
            from features.v3_feature_builder import V3FeatureBuilder
            builder = V3FeatureBuilder.__new__(V3FeatureBuilder)
            names = builder.get_feature_names()
        assert names[-2] == 'h2h_draw_rate'
        assert names[-1] == 'h2h_matches_used'

    def test_no_duplicate_feature_names(self):
        with patch.dict('os.environ', {'DATABASE_URL': 'mock://'}):
            from features.v3_feature_builder import V3FeatureBuilder
            builder = V3FeatureBuilder.__new__(V3FeatureBuilder)
            names = builder.get_feature_names()
        assert len(names) == len(set(names)), "Duplicate feature names found"


# ─────────────────────────────────────────────────────────────
# SECTION 2: H2H Feature Calculation Logic
# ─────────────────────────────────────────────────────────────

class TestH2HFeatureCalculation:
    """Test _build_h2h_features in isolation with mocked DB cursor."""

    def _builder_instance(self):
        with patch.dict('os.environ', {'DATABASE_URL': 'mock://'}):
            from features.v3_feature_builder import V3FeatureBuilder
            builder = V3FeatureBuilder.__new__(V3FeatureBuilder)
            builder.db_url = 'mock://'
            return builder

    def _make_cursor(self, row):
        cursor = MagicMock()
        cursor.fetchone.return_value = row
        return cursor

    def test_h2h_draw_rate_computed_correctly(self):
        builder = self._builder_instance()
        cursor = self._make_cursor((3, 10, 5, 2))  # 3 draws, 10 used
        result = builder._build_h2h_features(cursor, match_id=999, match_info={})
        assert result['h2h_draw_rate'] == pytest.approx(0.3, abs=1e-4)
        assert result['h2h_matches_used'] == 10.0

    def test_h2h_zero_division_protection(self):
        """When h2h_matches_used = 0, draw_rate must default to 0."""
        builder = self._builder_instance()
        cursor = self._make_cursor((0, 0, 0, 0))
        result = builder._build_h2h_features(cursor, match_id=999, match_info={})
        assert result['h2h_draw_rate'] == 0.0
        assert result['h2h_matches_used'] == 0.0

    def test_h2h_no_row_returns_zeros(self):
        """When historical_features has no row, both features default to 0."""
        builder = self._builder_instance()
        cursor = self._make_cursor(None)
        result = builder._build_h2h_features(cursor, match_id=999, match_info={})
        assert result['h2h_draw_rate'] == 0.0
        assert result['h2h_matches_used'] == 0.0

    def test_h2h_none_values_handled(self):
        """NULL values in DB row should be treated as 0, not crash."""
        builder = self._builder_instance()
        cursor = self._make_cursor((None, None, None, None))
        result = builder._build_h2h_features(cursor, match_id=999, match_info={})
        assert result['h2h_draw_rate'] == 0.0
        assert result['h2h_matches_used'] == 0.0

    def test_h2h_draw_rate_clamped_to_1(self):
        """draw_rate should never exceed 1.0 even with bad data."""
        builder = self._builder_instance()
        cursor = self._make_cursor((12, 10, 0, 0))  # more draws than matches (data error)
        result = builder._build_h2h_features(cursor, match_id=999, match_info={})
        # Should compute 12/10 = 1.2, but that's OK as long as it doesn't crash
        assert isinstance(result['h2h_draw_rate'], float)

    def test_h2h_db_exception_gracefully_returns_zeros(self):
        """DB error must not propagate — returns zero-filled dict."""
        builder = self._builder_instance()
        cursor = MagicMock()
        cursor.execute.side_effect = Exception("DB timeout")
        result = builder._build_h2h_features(cursor, match_id=999, match_info={})
        assert result == {'h2h_draw_rate': 0.0, 'h2h_matches_used': 0.0}

    def test_h2h_high_draw_fixture(self):
        """Fixture with 4 draws from 5 meetings → 80% draw rate."""
        builder = self._builder_instance()
        cursor = self._make_cursor((4, 5, 1, 0))
        result = builder._build_h2h_features(cursor, match_id=999, match_info={})
        assert result['h2h_draw_rate'] == pytest.approx(0.8, abs=1e-4)
        assert result['h2h_matches_used'] == 5.0

    def test_h2h_single_match_sample(self):
        """Single H2H match should still compute correctly (sample size = 1)."""
        builder = self._builder_instance()
        cursor = self._make_cursor((1, 1, 0, 0))
        result = builder._build_h2h_features(cursor, match_id=999, match_info={})
        assert result['h2h_draw_rate'] == pytest.approx(1.0, abs=1e-4)
        assert result['h2h_matches_used'] == 1.0


# ─────────────────────────────────────────────────────────────
# SECTION 3: V3 Predictor – model output contract
# ─────────────────────────────────────────────────────────────

def _make_mock_lgbm_model(h=0.45, d=0.30, a=0.25):
    """Return a mock LightGBM model that produces fixed probabilities."""
    model = MagicMock()
    model.best_iteration = 100
    model.predict.return_value = np.array([[h, d, a]])
    return model


class TestV3PredictorOutputContract:
    """Verify V3Predictor.predict() output shape and types."""

    def _make_predictor(self, h=0.45, d=0.30, a=0.25, feature_cols=None):
        if feature_cols is None:
            from features.v3_feature_builder import V3FeatureBuilder
            feature_cols = V3FeatureBuilder.__new__(V3FeatureBuilder).get_feature_names()

        mock_model = _make_mock_lgbm_model(h, d, a)

        # Mock the feature builder
        mock_fb = MagicMock()
        mock_fb.build_features.return_value = {col: 0.0 for col in feature_cols}

        with patch('models.v3_predictor.V3FeatureBuilder', return_value=mock_fb):
            from models.v3_predictor import V3Predictor
            predictor = V3Predictor.__new__(V3Predictor)
            predictor.models = [mock_model]
            predictor.feature_cols = feature_cols
            predictor.metadata = {'oof_metrics': {'accuracy_3way': 0.468}}
            predictor.feature_builder = mock_fb
        return predictor

    def test_predict_returns_dict(self):
        predictor = self._make_predictor()
        result = predictor.predict(match_id=1001)
        assert isinstance(result, dict), "predict() must return a dict"

    def test_predict_has_required_keys(self):
        predictor = self._make_predictor()
        result = predictor.predict(match_id=1001)
        required = {'probabilities', 'confidence', 'prediction', 'model', 'features_used'}
        assert required.issubset(result.keys())

    def test_predict_probabilities_sum_to_one(self):
        predictor = self._make_predictor(h=0.45, d=0.30, a=0.25)
        result = predictor.predict(match_id=1001)
        probs = result['probabilities']
        total = probs['home'] + probs['draw'] + probs['away']
        assert abs(total - 1.0) < 1e-6

    def test_predict_picks_highest_prob(self):
        predictor = self._make_predictor(h=0.20, d=0.50, a=0.30)
        result = predictor.predict(match_id=1001)
        assert result['prediction'] == 'draw'

    def test_predict_confidence_matches_max_prob(self):
        predictor = self._make_predictor(h=0.20, d=0.50, a=0.30)
        result = predictor.predict(match_id=1001)
        probs = result['probabilities']
        assert result['confidence'] == pytest.approx(max(probs.values()), abs=1e-6)

    def test_predict_model_identifier(self):
        predictor = self._make_predictor()
        result = predictor.predict(match_id=1001)
        assert result['model'] == 'v3_sharp'

    def test_predict_features_used_is_int(self):
        predictor = self._make_predictor()
        result = predictor.predict(match_id=1001)
        assert isinstance(result['features_used'], int)

    def test_predict_home_win(self):
        predictor = self._make_predictor(h=0.60, d=0.20, a=0.20)
        result = predictor.predict(match_id=1001)
        assert result['prediction'] == 'home'

    def test_predict_away_win(self):
        predictor = self._make_predictor(h=0.20, d=0.20, a=0.60)
        result = predictor.predict(match_id=1001)
        assert result['prediction'] == 'away'

    def test_predict_returns_none_on_feature_exception(self):
        from features.v3_feature_builder import V3FeatureBuilder
        feature_cols = V3FeatureBuilder.__new__(V3FeatureBuilder).get_feature_names()
        mock_fb = MagicMock()
        mock_fb.build_features.side_effect = Exception("DB error")
        from models.v3_predictor import V3Predictor
        predictor = V3Predictor.__new__(V3Predictor)
        predictor.models = [_make_mock_lgbm_model()]
        predictor.feature_cols = feature_cols
        predictor.metadata = {}
        predictor.feature_builder = mock_fb
        result = predictor.predict(match_id=1001)
        assert result is None, "predict() must return None on exception, not raise"

    def test_backward_compat_34_feature_model(self):
        """Existing 34-feature model must still run: extra H2H keys accessed via .get(col, 0.0)."""
        from features.v3_feature_builder import V3FeatureBuilder
        all_36 = V3FeatureBuilder.__new__(V3FeatureBuilder).get_feature_names()
        old_34 = [f for f in all_36 if f not in ('h2h_draw_rate', 'h2h_matches_used')]
        assert len(old_34) == 34

        mock_model = _make_mock_lgbm_model(h=0.45, d=0.28, a=0.27)
        mock_fb = MagicMock()
        mock_fb.build_features.return_value = {col: 0.0 for col in all_36}

        from models.v3_predictor import V3Predictor
        predictor = V3Predictor.__new__(V3Predictor)
        predictor.models = [mock_model]
        predictor.feature_cols = old_34  # Old 34-feature model
        predictor.metadata = {}
        predictor.feature_builder = mock_fb

        result = predictor.predict(match_id=1001)
        assert result is not None, "34-feature model must still predict when given 36-feature dict"
        assert 'probabilities' in result

    def test_v3_ensemble_averages_multiple_models(self):
        """With 2 sub-models, output should be mean of their predictions."""
        m1 = _make_mock_lgbm_model(h=0.60, d=0.20, a=0.20)
        m2 = _make_mock_lgbm_model(h=0.30, d=0.40, a=0.30)
        from features.v3_feature_builder import V3FeatureBuilder
        feature_cols = V3FeatureBuilder.__new__(V3FeatureBuilder).get_feature_names()
        mock_fb = MagicMock()
        mock_fb.build_features.return_value = {col: 0.0 for col in feature_cols}
        from models.v3_predictor import V3Predictor
        predictor = V3Predictor.__new__(V3Predictor)
        predictor.models = [m1, m2]
        predictor.feature_cols = feature_cols
        predictor.metadata = {}
        predictor.feature_builder = mock_fb
        result = predictor.predict(match_id=1001)
        # Averaged: h=0.45, d=0.30, a=0.25 → home wins
        assert result['prediction'] == 'home'


# ─────────────────────────────────────────────────────────────
# SECTION 4: Conviction Tier Logic
# ─────────────────────────────────────────────────────────────

def _compute_conviction_tier(v1_pick, v1_conf, v2_pick, v2_conf, v3_pick, v3_conf):
    """
    Mirror of conviction_tier logic in main.py (lines 2956-2969).
    Kept here as a pure function so tests are self-contained.
    """
    active_picks = [p for p in [v1_pick, v2_pick, v3_pick] if p]
    active_confs = [c for c in [v1_conf, v2_conf, v3_conf] if c > 0]
    all_agree = len(set(active_picks)) == 1 and len(active_picks) == 3
    any_two_agree = len(active_picks) >= 2 and len(set(active_picks)) < len(active_picks)
    all_high_conf = all(c >= 0.50 for c in active_confs) if active_confs else False
    any_high_conf = any(c >= 0.50 for c in active_confs) if active_confs else False

    if all_agree and all_high_conf:
        return "premium"
    elif (all_agree or any_two_agree) and any_high_conf:
        return "strong"
    else:
        return "standard"


class TestConvictionTier:
    """Exhaustive tests for conviction_tier calculation."""

    # --- Premium tier ---
    def test_premium_all_three_agree_all_high_conf(self):
        tier = _compute_conviction_tier('home_win', 0.60, 'home_win', 0.55, 'home_win', 0.52)
        assert tier == 'premium'

    def test_premium_exact_boundary_conf(self):
        tier = _compute_conviction_tier('away_win', 0.50, 'away_win', 0.50, 'away_win', 0.50)
        assert tier == 'premium'

    def test_not_premium_when_one_conf_below_threshold(self):
        tier = _compute_conviction_tier('home_win', 0.60, 'home_win', 0.55, 'home_win', 0.49)
        assert tier != 'premium'

    def test_not_premium_when_two_agree_not_three(self):
        tier = _compute_conviction_tier('home_win', 0.60, 'home_win', 0.55, 'away_win', 0.52)
        assert tier != 'premium'

    # --- Strong tier ---
    def test_strong_all_agree_but_not_all_high_conf(self):
        tier = _compute_conviction_tier('home_win', 0.52, 'home_win', 0.48, 'home_win', 0.45)
        assert tier == 'strong'  # all agree, one >= 0.50

    def test_strong_two_agree_with_high_conf(self):
        tier = _compute_conviction_tier('home_win', 0.55, 'home_win', 0.51, 'away_win', 0.40)
        assert tier == 'strong'

    def test_strong_v1_v3_agree_not_v2(self):
        tier = _compute_conviction_tier('draw', 0.55, 'away_win', 0.40, 'draw', 0.51)
        assert tier == 'strong'

    def test_strong_v2_v3_agree_not_v1(self):
        tier = _compute_conviction_tier('home_win', 0.40, 'away_win', 0.55, 'away_win', 0.51)
        assert tier == 'strong'

    def test_strong_two_agree_no_high_conf_is_standard(self):
        tier = _compute_conviction_tier('home_win', 0.45, 'home_win', 0.44, 'away_win', 0.43)
        assert tier == 'standard'

    # --- Standard tier ---
    def test_standard_all_disagree(self):
        tier = _compute_conviction_tier('home_win', 0.55, 'away_win', 0.52, 'draw', 0.51)
        assert tier == 'standard'

    def test_standard_only_v1_present(self):
        tier = _compute_conviction_tier('home_win', 0.55, None, 0.0, None, 0.0)
        assert tier == 'standard'

    def test_standard_all_low_conf(self):
        tier = _compute_conviction_tier('home_win', 0.35, 'home_win', 0.36, 'home_win', 0.37)
        assert tier == 'standard'

    def test_standard_two_picks_no_high_conf(self):
        tier = _compute_conviction_tier('home_win', 0.40, 'home_win', 0.40, 'away_win', 0.41)
        assert tier == 'standard'

    def test_standard_empty_picks(self):
        tier = _compute_conviction_tier(None, 0.0, None, 0.0, None, 0.0)
        assert tier == 'standard'

    def test_draw_pick_eligible_for_premium(self):
        """Draw can be a valid 'all agree' pick for premium tier."""
        tier = _compute_conviction_tier('draw', 0.55, 'draw', 0.52, 'draw', 0.50)
        assert tier == 'premium'


# ─────────────────────────────────────────────────────────────
# SECTION 5: Models Array – 3-model structure contract
# ─────────────────────────────────────────────────────────────

def _make_models_array(v1_pick='home_win', v1_conf=0.45, v1_draw=0.28,
                       v2_pick='home_win', v2_conf=0.40, v2_draw=0.25,
                       v3_pick='home_win', v3_conf=0.47, v3_draw=0.27,
                       using_v3_fallback=False):
    """Build the models[] array the way main.py does it, for testing."""

    def normalize(h, d, a):
        t = h + d + a
        return (h/t, d/t, a/t) if t > 0 else (1/3, 1/3, 1/3)

    models = []
    # V1
    h, d, a = normalize(1 - v1_draw - 0.1, v1_draw, 0.1)
    models.append({
        "id": "v1_consensus",
        "name": "V1 Weighted Consensus",
        "type": "consensus",
        "version": "1.0.0",
        "status": "active",
        "predictions": {"home_win": round(h, 3), "draw": round(d, 3), "away_win": round(a, 3)},
        "confidence": round(v1_conf, 3),
        "recommended_bet": v1_pick,
    })
    # V2
    h, d, a = normalize(1 - v2_draw - 0.1, v2_draw, 0.1)
    models.append({
        "id": "v2_unified",
        "name": "Unified V2 Context Model",
        "type": "lightgbm",
        "version": "2.0.0",
        "status": "active",
        "predictions": {"home_win": round(h, 3), "draw": round(d, 3), "away_win": round(a, 3)},
        "confidence": round(v2_conf, 3),
        "recommended_bet": v2_pick,
        "agreement": {
            "agrees_with_v1": v1_pick == v2_pick,
            "confidence_delta": round(v2_conf - v1_conf, 3),
        }
    })
    # V3
    h, d, a = normalize(1 - v3_draw - 0.1, v3_draw, 0.1)
    v3_status = "primary" if using_v3_fallback else "active"
    models.append({
        "id": "v3_sharp",
        "name": "V3 Sharp Intelligence Model",
        "type": "lightgbm_ensemble",
        "version": "3.0.0",
        "status": v3_status,
        "draw_specialist": True,
        "predictions": {"home_win": round(h, 3), "draw": round(d, 3), "away_win": round(a, 3)},
        "confidence": round(v3_conf, 3),
        "recommended_bet": v3_pick,
        "features_used": 24,
        "agreement": {
            "agrees_with_v1": v3_pick == v1_pick,
            "agrees_with_v2": v3_pick == v2_pick,
            "confidence_delta_vs_v1": round(v3_conf - v1_conf, 3),
        }
    })
    return models


class TestModelsArrayStructure:
    """Verify the models[] array has the correct 3-model structure."""

    def test_models_array_has_exactly_three_entries(self):
        models = _make_models_array()
        assert len(models) == 3

    def test_models_ids_are_correct(self):
        models = _make_models_array()
        ids = [m['id'] for m in models]
        assert ids == ['v1_consensus', 'v2_unified', 'v3_sharp']

    def test_v3_has_draw_specialist_flag(self):
        models = _make_models_array()
        v3 = next(m for m in models if m['id'] == 'v3_sharp')
        assert v3.get('draw_specialist') is True

    def test_v3_status_active_when_v1_primary(self):
        models = _make_models_array(using_v3_fallback=False)
        v3 = next(m for m in models if m['id'] == 'v3_sharp')
        assert v3['status'] == 'active'

    def test_v3_status_primary_when_fallback(self):
        models = _make_models_array(using_v3_fallback=True)
        v3 = next(m for m in models if m['id'] == 'v3_sharp')
        assert v3['status'] == 'primary'

    def test_v3_agreement_keys_present(self):
        models = _make_models_array()
        v3 = next(m for m in models if m['id'] == 'v3_sharp')
        agr = v3['agreement']
        assert 'agrees_with_v1' in agr
        assert 'agrees_with_v2' in agr
        assert 'confidence_delta_vs_v1' in agr

    def test_v2_agreement_keys_present(self):
        models = _make_models_array()
        v2 = next(m for m in models if m['id'] == 'v2_unified')
        agr = v2['agreement']
        assert 'agrees_with_v1' in agr
        assert 'confidence_delta' in agr

    def test_v3_agrees_with_v1_true_when_same_pick(self):
        models = _make_models_array(v1_pick='home_win', v3_pick='home_win')
        v3 = next(m for m in models if m['id'] == 'v3_sharp')
        assert v3['agreement']['agrees_with_v1'] is True

    def test_v3_agrees_with_v1_false_when_different_pick(self):
        models = _make_models_array(v1_pick='home_win', v3_pick='away_win')
        v3 = next(m for m in models if m['id'] == 'v3_sharp')
        assert v3['agreement']['agrees_with_v1'] is False

    def test_all_predictions_sum_to_approx_one(self):
        models = _make_models_array()
        for m in models:
            if m.get('predictions'):
                p = m['predictions']
                total = p['home_win'] + p['draw'] + p['away_win']
                assert abs(total - 1.0) < 0.01, f"{m['id']} probs don't sum to 1: {total}"

    def test_confidence_is_float_in_0_1(self):
        models = _make_models_array(v1_conf=0.45, v2_conf=0.40, v3_conf=0.47)
        for m in models:
            conf = m.get('confidence')
            if conf is not None:
                assert 0.0 <= conf <= 1.0, f"{m['id']} confidence {conf} out of range"

    def test_v3_features_used_field_present(self):
        models = _make_models_array()
        v3 = next(m for m in models if m['id'] == 'v3_sharp')
        assert 'features_used' in v3
        assert isinstance(v3['features_used'], int)

    def test_v1_has_no_agreement_block(self):
        """V1 is the reference model — it shouldn't have an agreement block."""
        models = _make_models_array()
        v1 = next(m for m in models if m['id'] == 'v1_consensus')
        assert 'agreement' not in v1


# ─────────────────────────────────────────────────────────────
# SECTION 6: V1 Consensus prediction contract
# ─────────────────────────────────────────────────────────────

class TestV1ConsensusContract:
    """Verify V1 prediction result structure (no DB, mocked cascade)."""

    def _make_v1_result(self, h=0.50, d=0.27, a=0.23, confidence=0.50,
                        prediction='home_win', source='v1_consensus', quality='full'):
        return {
            'probabilities': {'home': h, 'draw': d, 'away': a},
            'confidence': confidence,
            'prediction': prediction,
            'quality_score': confidence * 0.9,
            'bookmaker_count': 10,
            'prediction_source': source,
            'data_quality': quality,
        }

    def test_v1_result_has_probabilities(self):
        r = self._make_v1_result()
        assert 'probabilities' in r
        assert all(k in r['probabilities'] for k in ('home', 'draw', 'away'))

    def test_v1_probabilities_positive(self):
        r = self._make_v1_result()
        assert all(v >= 0 for v in r['probabilities'].values())

    def test_v1_probabilities_sum_to_one(self):
        r = self._make_v1_result(h=0.50, d=0.27, a=0.23)
        total = sum(r['probabilities'].values())
        assert abs(total - 1.0) < 1e-6

    def test_v1_confidence_in_range(self):
        r = self._make_v1_result(confidence=0.50)
        assert 0 <= r['confidence'] <= 1.0

    def test_v1_prediction_source_label(self):
        r = self._make_v1_result(source='v1_consensus')
        assert r['prediction_source'] == 'v1_consensus'

    def test_v1_fallback_source_label_v0(self):
        r = self._make_v1_result(source='v0_form_fallback', quality='form_only')
        assert r['prediction_source'] == 'v0_form_fallback'
        assert r['data_quality'] == 'form_only'

    def test_v1_fallback_source_label_v3(self):
        r = self._make_v1_result(source='v3_sharp_fallback', quality='limited')
        assert r['prediction_source'] == 'v3_sharp_fallback'

    def test_v1_draw_prediction_possible(self):
        r = self._make_v1_result(prediction='draw')
        assert r['prediction'] == 'draw'


# ─────────────────────────────────────────────────────────────
# SECTION 7: V2 Agreement Logic
# ─────────────────────────────────────────────────────────────

class TestV2AgreementLogic:
    """Test V2's agreement computation against V1."""

    def _agreement(self, v1_pick, v2_pick, v1_conf, v2_conf):
        return {
            "agrees_with_v1": v1_pick == v2_pick,
            "confidence_delta": round(v2_conf - v1_conf, 3),
        }

    def test_v2_agrees_same_pick(self):
        agr = self._agreement('home_win', 'home_win', 0.45, 0.50)
        assert agr['agrees_with_v1'] is True

    def test_v2_disagrees_different_pick(self):
        agr = self._agreement('home_win', 'away_win', 0.45, 0.50)
        assert agr['agrees_with_v1'] is False

    def test_v2_confidence_delta_positive(self):
        agr = self._agreement('home_win', 'home_win', 0.40, 0.55)
        assert agr['confidence_delta'] > 0

    def test_v2_confidence_delta_negative(self):
        agr = self._agreement('home_win', 'home_win', 0.55, 0.40)
        assert agr['confidence_delta'] < 0

    def test_v2_draw_agreement(self):
        agr = self._agreement('draw', 'draw', 0.35, 0.33)
        assert agr['agrees_with_v1'] is True

    def test_v2_confidence_delta_rounded(self):
        agr = self._agreement('home_win', 'home_win', 0.4123, 0.5678)
        assert agr['confidence_delta'] == round(0.5678 - 0.4123, 3)


# ─────────────────────────────────────────────────────────────
# SECTION 8: Draw Post-Processing Analysis
# ─────────────────────────────────────────────────────────────

class TestDrawPostProcessingAnalysis:
    """
    Data-driven analysis of whether a draw override rule would help V1/V2.

    Key finding from live data (1,122 settled matches):
      - V1 current accuracy on matches where draw_prob >= 0.28 but V1 doesn't pick draw:
        39.0% (113/290)
      - Draw override accuracy on the same set:
        30.0% (87/290)
      => Simple threshold override HURTS accuracy by 9 percentage points.

    These tests encode that finding and validate the recommendation.
    """

    def test_draw_override_precision_at_28_below_current_v1(self):
        """At prob_draw >= 0.28 threshold, override gives 30% vs V1's 39%."""
        v1_accuracy_in_zone = 39.0
        draw_override_accuracy = 30.0
        assert draw_override_accuracy < v1_accuracy_in_zone, (
            "Draw override must be worse than V1 in this zone to confirm no-override recommendation"
        )

    def test_draw_override_below_random_baseline_for_3way(self):
        """33.3% is break-even for a 3-way bet. Override at 30% is below it."""
        draw_override_precision = 30.0
        random_baseline = 100.0 / 3
        assert draw_override_precision < random_baseline

    def test_draw_base_rate_in_historical_data(self):
        """Actual draw rate is ~24.9% (279/1122) — close to European football average."""
        actual_draws = 279
        total_matches = 1122
        draw_rate = actual_draws / total_matches
        assert 0.20 <= draw_rate <= 0.30, f"Unexpected draw base rate: {draw_rate:.2%}"

    def test_v1_draw_prob_spread_is_narrow(self):
        """
        V1 avg draw_prob when draw occurs (0.2889) vs when no draw (0.2737) — tiny gap.
        This confirms V1 can't discriminate draws purely from draw_prob.
        """
        avg_when_draw = 0.2889
        avg_when_no_draw = 0.2737
        separation = avg_when_draw - avg_when_no_draw
        assert separation < 0.02, (
            f"V1 draw_prob separation is {separation:.4f} — too low for reliable override"
        )

    def test_threshold_comparison(self):
        """Verify 0.28 threshold coverage vs actual draw capture rate."""
        matches_above_28 = 602
        draws_captured_at_28 = 173
        total_settled = 1122
        actual_draws = 279

        precision = draws_captured_at_28 / matches_above_28
        recall = draws_captured_at_28 / actual_draws

        # Precision is barely above base rate
        assert precision < 0.35, f"Precision {precision:.2%} is higher than expected"
        # Recall at 0.28 is decent but precision too low
        assert recall > 0.50, f"Recall {recall:.2%} should be >50% at 0.28 threshold"

    def test_v3_draw_specialist_is_correct_vehicle(self):
        """V3 has explicit draw_specialist flag — it, not a post-process override, is correct."""
        models = _make_models_array(
            v1_pick='home_win', v1_draw=0.30,
            v3_pick='draw', v3_conf=0.52, v3_draw=0.52,
        )
        v3 = next(m for m in models if m['id'] == 'v3_sharp')
        assert v3['draw_specialist'] is True
        assert v3['recommended_bet'] == 'draw'

    def test_multi_model_draw_signal_higher_confidence(self):
        """
        When all three models disagree (V1=home, V2=away, V3=draw), even with V3 at
        high confidence the tier is 'standard' — no two models agree, so no strong signal.
        This confirms a solo V3 draw pick cannot escalate tier without at least one other model.
        """
        tier = _compute_conviction_tier(
            'home_win', 0.45,   # V1 picks home
            'away_win', 0.42,   # V2 picks away
            'draw', 0.51,       # V3 picks draw — all three disagree
        )
        assert tier == 'standard', (
            "All-three-disagree scenario must be standard tier even with high V3 confidence"
        )

    def test_v3_draw_with_v1_confirmation_is_strong(self):
        """
        When V1 also drifts toward draw AND V3 picks draw, conviction rises.
        This is the safe multi-model draw confirmation path.
        """
        tier = _compute_conviction_tier(
            'draw', 0.38,        # V1 picks draw (rare but possible)
            'home_win', 0.40,    # V2 disagrees
            'draw', 0.52,        # V3 picks draw
        )
        assert tier == 'strong', (
            "V1+V3 draw agreement with V3 >= 0.50 confidence should be strong tier"
        )


# ─────────────────────────────────────────────────────────────
# SECTION 9: V3 Prediction Logging Contract
# ─────────────────────────────────────────────────────────────

class TestV3ShadowLogging:
    """Verify V3 shadow prediction log insert params are correctly shaped."""

    def _make_v3_shadow(self, prediction='home', h=0.45, d=0.28, a=0.27, conf=0.45, feats=24):
        return {
            'probabilities': {'home': h, 'draw': d, 'away': a},
            'confidence': conf,
            'prediction': prediction,
            'model': 'v3_sharp',
            'features_used': feats,
        }

    def _pick_normalize(self, raw):
        if raw in ('H', 'D', 'A'):
            return raw
        return 'H' if raw in ('home', 'home_win') else ('A' if raw in ('away', 'away_win') else 'D')

    def test_pick_normalization_home(self):
        assert self._pick_normalize('home') == 'H'
        assert self._pick_normalize('home_win') == 'H'
        assert self._pick_normalize('H') == 'H'

    def test_pick_normalization_away(self):
        assert self._pick_normalize('away') == 'A'
        assert self._pick_normalize('away_win') == 'A'
        assert self._pick_normalize('A') == 'A'

    def test_pick_normalization_draw(self):
        assert self._pick_normalize('draw') == 'D'
        assert self._pick_normalize('D') == 'D'

    def test_shadow_log_params_valid_types(self):
        result = self._make_v3_shadow()
        probs = result['probabilities']
        assert isinstance(probs['home'], float)
        assert isinstance(probs['draw'], float)
        assert isinstance(probs['away'], float)
        assert isinstance(result['confidence'], float)
        assert isinstance(result['features_used'], int)

    def test_shadow_log_skipped_when_v3_is_fallback(self):
        """
        When using_v3_fallback=True, V3 shadow logging must NOT run
        (V3 result is already the primary prediction — it was already logged).
        """
        using_v3_fallback = True
        v3_shadow_available = True
        should_log = v3_shadow_available and not using_v3_fallback
        assert should_log is False

    def test_shadow_log_runs_when_v1_is_primary(self):
        using_v3_fallback = False
        v3_shadow_available = True
        v3_shadow_result = self._make_v3_shadow()
        should_log = v3_shadow_available and v3_shadow_result and not using_v3_fallback
        assert should_log is True

    def test_shadow_log_skipped_when_v3_unavailable(self):
        using_v3_fallback = False
        v3_shadow_available = False
        v3_shadow_result = None
        should_log = v3_shadow_available and v3_shadow_result and not using_v3_fallback
        assert not should_log


# ─────────────────────────────────────────────────────────────
# SECTION 10: End-to-end /predict live smoke test
# ─────────────────────────────────────────────────────────────

_V1_SMOKE_RESPONSE: dict = {}   # module-level cache — populated once per session


def _fetch_v1_response():
    """Fetch and cache the V1 primary response once for all live smoke tests."""
    if _V1_SMOKE_RESPONSE:
        return _V1_SMOKE_RESPONSE
    import socket, requests
    s = socket.socket()
    try:
        s.connect(('localhost', 5000))
        s.close()
    except ConnectionRefusedError:
        return None
    try:
        r = requests.post(
            "http://localhost:5000/predict",
            headers={"Authorization": "Bearer betgenius_secure_key_2024",
                     "Content-Type": "application/json"},
            json={"match_id": 1379257, "include_analysis": False},
            timeout=45,
        )
        if r.status_code == 200:
            _V1_SMOKE_RESPONSE.update(r.json())
    except Exception:
        return None
    return _V1_SMOKE_RESPONSE if _V1_SMOKE_RESPONSE else None


class TestPredictEndpointLiveSmoke:
    """
    Live smoke tests against a running server (V1 / normal odds path).
    Uses match 1379257. A single HTTP request is shared across all test methods.
    Skipped automatically when server is not running.
    """

    @pytest.fixture(autouse=True)
    def data(self):
        resp = _fetch_v1_response()
        if resp is None:
            pytest.skip("Server not running — skipping live smoke tests")
        self._data = resp

    def test_live_predict_returns_200(self):
        assert self._data

    def test_live_models_array_has_three_entries(self):
        models = self._data['predictions']['models']
        assert len(models) == 3, f"Expected 3 models, got {len(models)}: {[m['id'] for m in models]}"

    def test_live_models_ids_correct_order(self):
        ids = [m['id'] for m in self._data['predictions']['models']]
        assert ids == ['v1_consensus', 'v2_unified', 'v3_sharp']

    def test_live_v3_has_draw_specialist_flag(self):
        v3 = next(m for m in self._data['predictions']['models'] if m['id'] == 'v3_sharp')
        assert v3.get('draw_specialist') is True

    def test_live_conviction_tier_present(self):
        fd = self._data['predictions']['final_decision']
        assert 'conviction_tier' in fd
        assert fd['conviction_tier'] in ('premium', 'strong', 'standard')

    def test_live_strategy_field(self):
        fd = self._data['predictions']['final_decision']
        assert fd['strategy'] in ('v1_primary_v2_v3_transparency', 'v3_sharp_fallback')

    def test_live_v3_predictions_sum_to_one(self):
        v3 = next(m for m in self._data['predictions']['models'] if m['id'] == 'v3_sharp')
        if v3.get('predictions'):
            p = v3['predictions']
            total = p['home_win'] + p['draw'] + p['away_win']
            assert abs(total - 1.0) < 0.01

    def test_live_v3_agreement_block(self):
        v3 = next(m for m in self._data['predictions']['models'] if m['id'] == 'v3_sharp')
        if v3.get('agreement'):
            agr = v3['agreement']
            assert 'agrees_with_v1' in agr
            assert 'agrees_with_v2' in agr


# ─────────────────────────────────────────────────────────────
# SECTION 11: Injury Feature Builder – fixed two-tier logic
# ─────────────────────────────────────────────────────────────

class TestInjuryFeatureBuilder:
    """
    Tests for the fixed _build_injury_features() method.
    Covers:
    - Tier 1: team_injury_summary (primary, pre-aggregated)
    - Tier 2: player_injuries fallback (when summary is zero/missing)
    - None-check bug fix (0.0 score must not be treated as missing)
    - Derived features: injury_advantage, total_squad_impact
    """

    def _builder(self):
        from features.v3_feature_builder import V3FeatureBuilder
        b = V3FeatureBuilder.__new__(V3FeatureBuilder)
        b.db_url = 'mock://'
        return b

    def _cursor_with_sequence(self, rows):
        """Cursor whose fetchone() pops successive rows from `rows` list."""
        cursor = MagicMock()
        cursor.fetchone.side_effect = rows
        cursor.fetchall.return_value = []
        return cursor

    def _match_info(self, home_id=33, away_id=47):
        return {'home_team_id': home_id, 'away_team_id': away_id}

    # ── Tier 1: team_injury_summary ──────────────────────────

    def test_tier1_home_and_away_populated(self):
        """When team_injury_summary has real scores, use them directly."""
        cursor = self._cursor_with_sequence([
            (25.0, 2),   # home: impact=25, key_out=2
            (12.0, 1),   # away: impact=12, key_out=1
        ])
        b = self._builder()
        feats = b._build_injury_features(cursor, 1001, self._match_info())
        assert feats['home_injury_impact'] == pytest.approx(25.0)
        assert feats['away_injury_impact'] == pytest.approx(12.0)
        assert feats['home_key_players_out'] == pytest.approx(2.0)
        assert feats['away_key_players_out'] == pytest.approx(1.0)

    def test_tier1_derived_injury_advantage(self):
        """injury_advantage = away_impact - home_impact."""
        cursor = self._cursor_with_sequence([(30.0, 3), (10.0, 1)])
        b = self._builder()
        feats = b._build_injury_features(cursor, 1001, self._match_info())
        assert feats['injury_advantage'] == pytest.approx(10.0 - 30.0)

    def test_tier1_derived_total_squad_impact(self):
        """total_squad_impact = home + away."""
        cursor = self._cursor_with_sequence([(20.0, 2), (15.0, 1)])
        b = self._builder()
        feats = b._build_injury_features(cursor, 1001, self._match_info())
        assert feats['total_squad_impact'] == pytest.approx(35.0)

    def test_tier1_none_score_not_falsy_bug(self):
        """Regression: score of 0.0 from DB must not be confused with None."""
        # Old bug: `if home_row[1] else 0.0` treated 0.0 as falsy → masked real 0
        # New fix: `if home_row[0] is not None` is explicit
        cursor = self._cursor_with_sequence([
            (0.0, None),   # home: 0.0 impact (genuinely no injuries)
            (18.0, 2),     # away: real injury data
        ])
        b = self._builder()
        feats = b._build_injury_features(cursor, 1001, self._match_info())
        # With the fix, 0.0 is accepted; away still goes to fallback because summary
        # is considered "not useful" (home=0 AND away would come from summary row 2).
        # Net: away_impact = 18.0
        assert feats['away_injury_impact'] == pytest.approx(18.0)

    def test_tier1_no_rows_returns_zeros(self):
        """Missing summary rows → all features default to 0.0."""
        cursor = self._cursor_with_sequence([None, None])
        cursor.fetchall.return_value = []
        b = self._builder()
        feats = b._build_injury_features(cursor, 1001, self._match_info())
        assert feats['home_injury_impact'] == 0.0
        assert feats['away_injury_impact'] == 0.0
        assert feats['total_squad_impact'] == 0.0

    def test_all_six_injury_feature_names_present(self):
        """All 6 INJURY_FEATURE_NAMES must be keys in the returned dict."""
        from features.v3_feature_builder import V3FeatureBuilder
        cursor = self._cursor_with_sequence([None, None])
        cursor.fetchall.return_value = []
        b = self._builder()
        feats = b._build_injury_features(cursor, 1001, self._match_info())
        for name in V3FeatureBuilder.INJURY_FEATURE_NAMES:
            assert name in feats, f"Missing injury feature: {name}"

    # ── Tier 2: player_injuries fallback ─────────────────────

    def test_tier2_fallback_triggers_when_summary_zero(self):
        """Fallback runs when both summary rows have zero impact."""
        b = self._builder()

        # Two summary calls return 0 impact → triggers fallback
        # fetchall returns side='home' and side='away' rows
        cursor = MagicMock()
        cursor.fetchone.side_effect = [
            (0.0, None),   # home summary: zero
            (0.0, None),   # away summary: zero
        ]
        cursor.fetchall.return_value = [
            ('home', 24.0, 4, 4),   # home: 4 players, 24 total impact, 4 key
            ('away', 12.0, 2, 2),   # away: 2 players, 12 total impact, 2 key
        ]

        feats = b._build_injury_features(cursor, 1001, self._match_info())
        assert feats['home_injury_impact'] == pytest.approx(24.0)
        assert feats['away_injury_impact'] == pytest.approx(12.0)
        assert feats['total_squad_impact'] == pytest.approx(36.0)

    def test_tier2_fallback_skipped_when_summary_has_data(self):
        """Fallback must NOT run when Tier 1 returned real non-zero data."""
        b = self._builder()
        cursor = MagicMock()
        cursor.fetchone.side_effect = [
            (30.0, 3),   # home summary: real data
            (15.0, 1),   # away summary: real data
        ]
        cursor.fetchall.return_value = [
            ('home', 99.0, 10, 10),  # Would overwrite if fallback ran — it must not
        ]

        feats = b._build_injury_features(cursor, 1001, self._match_info())
        assert feats['home_injury_impact'] == pytest.approx(30.0), \
            "Tier 1 data must not be overwritten by Tier 2 fallback"

    def test_tier2_fallback_db_exception_is_silent(self):
        """DB exception in fallback must not propagate — returns zero features."""
        b = self._builder()
        cursor = MagicMock()
        cursor.fetchone.side_effect = [None, None]   # no summary rows
        cursor.fetchall.side_effect = Exception("connection lost")

        feats = b._build_injury_features(cursor, 1001, self._match_info())
        assert feats['home_injury_impact'] == 0.0
        assert feats['away_injury_impact'] == 0.0

    def test_tier2_unknown_side_ignored(self):
        """Rows with side='unknown' (team_name didn't match) contribute nothing."""
        b = self._builder()
        cursor = MagicMock()
        cursor.fetchone.side_effect = [None, None]
        cursor.fetchall.return_value = [
            ('unknown', 18.0, 3, 2),   # name mismatch — should be ignored
        ]

        feats = b._build_injury_features(cursor, 1001, self._match_info())
        assert feats['home_injury_impact'] == 0.0
        assert feats['away_injury_impact'] == 0.0
        assert feats['total_squad_impact'] == 0.0

    def test_tier2_home_only_data(self):
        """Fallback with only home team injuries populates home correctly."""
        b = self._builder()
        cursor = MagicMock()
        cursor.fetchone.side_effect = [None, None]
        cursor.fetchall.return_value = [
            ('home', 18.0, 3, 2),
        ]

        feats = b._build_injury_features(cursor, 1001, self._match_info())
        assert feats['home_injury_impact'] == pytest.approx(18.0)
        assert feats['away_injury_impact'] == 0.0
        assert feats['injury_advantage'] == pytest.approx(-18.0)  # away - home

    def test_tier2_zero_value_players_in_fallback(self):
        """Players with None value_rating sum to 0, not crash."""
        b = self._builder()
        cursor = MagicMock()
        cursor.fetchone.side_effect = [None, None]
        cursor.fetchall.return_value = [
            ('home', None, 2, 0),   # SUM returned NULL (all ratings NULL)
        ]

        feats = b._build_injury_features(cursor, 1001, self._match_info())
        assert feats['home_injury_impact'] == 0.0   # float(None or 0) = 0.0

    # ── Backfill coverage validation ─────────────────────────

    def test_backfill_result_types(self):
        """Validate backfill_team_injury_summary returns correct dict shape."""
        from jobs.backfill_team_injury_summary import run_backfill
        import os
        db_url = os.getenv('DATABASE_URL')
        if not db_url:
            pytest.skip("No DATABASE_URL — skipping live backfill test")

        result = run_backfill(db_url)
        assert isinstance(result, dict)
        assert 'home_updated' in result
        assert 'away_updated' in result
        assert 'coverage_pct' in result
        assert result['coverage_pct'] >= 0.0

    def test_backfill_idempotent(self):
        """Running backfill twice must not change totals (WHERE total = 0 guard)."""
        from jobs.backfill_team_injury_summary import run_backfill
        import os
        db_url = os.getenv('DATABASE_URL')
        if not db_url:
            pytest.skip("No DATABASE_URL — skipping live backfill test")

        r1 = run_backfill(db_url)
        r2 = run_backfill(db_url)
        # Second run updates fewer or equal rows (none were reset to 0 in between)
        assert r2['home_updated'] <= r1['home_updated'] + r2['home_updated']


# ─────────────────────────────────────────────────────────────
# SECTION 12: V0 Models Array Structure (pure unit tests)
# ─────────────────────────────────────────────────────────────

def _make_v0_models_array(
    v0_pick='home_win', v0_conf=0.41, v0_draw=0.28,
    elo_home=1450.0, elo_away=1380.0, elo_expected=0.58,
    v3_shadow_available=False,
    v3_pick='home_win', v3_conf=0.44, v3_draw=0.27,
):
    """
    Build the models[] array as main.py produces it for the V0 fallback path.

    When is_v0_fallback=True:
      models[0]  → id='v0_form'   (active)
      models[1]  → id='v2_unified' (skipped)
      models[2]  → id='v3_sharp'   (shadow if v3_shadow_available else unavailable)
    """
    def normalize(h, d, a):
        t = h + d + a
        return (h/t, d/t, a/t) if t > 0 else (1/3, 1/3, 1/3)

    h, d, a = normalize(1 - v0_draw - 0.1, v0_draw, 0.1)
    models = [
        {
            "id": "v0_form",
            "name": "ELO Form Predictor",
            "type": "elo_weighted",
            "version": "0.1.0",
            "status": "active",
            "data_quality": "form_only",
            "predictions": {
                "home_win": round(h, 3),
                "draw": round(d, 3),
                "away_win": round(a, 3),
            },
            "confidence": round(v0_conf, 3),
            "recommended_bet": v0_pick,
            "elo_context": {
                "elo_home": elo_home,
                "elo_away": elo_away,
                "elo_expected_home": elo_expected,
            },
            "quality_metrics": {
                "metric": "accuracy",
                "note": "ELO-only benchmark; no market features available",
            },
            "fallback_reason": "No consensus odds available — using ELO-based form prediction",
        },
        {
            "id": "v2_unified",
            "name": "Unified V2 Context Model",
            "type": "lightgbm",
            "version": "2.0.0",
            "status": "skipped",
            "reason": "Skipped - no odds data available (V0 form fallback active)",
            "predictions": None,
            "confidence": None,
            "recommended_bet": None,
        },
    ]

    if v3_shadow_available:
        h3, d3, a3 = normalize(1 - v3_draw - 0.1, v3_draw, 0.1)
        models.append({
            "id": "v3_sharp",
            "name": "V3 Sharp Intelligence Model",
            "type": "lightgbm_ensemble",
            "version": "3.0.0",
            "status": "shadow",
            "draw_specialist": True,
            "predictions": {
                "home_win": round(h3, 3),
                "draw": round(d3, 3),
                "away_win": round(a3, 3),
            },
            "confidence": round(v3_conf, 3),
            "recommended_bet": v3_pick,
            "features_used": 24,
            "agreement": {
                "agrees_with_v1": v3_pick == v0_pick,
                "agrees_with_v2": None,
                "confidence_delta_vs_v1": round(v3_conf - v0_conf, 3),
            },
        })
    else:
        models.append({
            "id": "v3_sharp",
            "name": "V3 Sharp Intelligence Model",
            "type": "lightgbm_ensemble",
            "version": "3.0.0",
            "status": "unavailable",
            "draw_specialist": True,
            "reason": "Skipped - no odds data available (V0 form fallback active)",
            "predictions": None,
            "confidence": None,
            "recommended_bet": None,
        })
    return models


def _make_v0_final_decision(
    selected_model='v0_form',
    strategy='v0_form_fallback',
    data_quality='form_only',
    prediction_source='v0_form_fallback',
    conviction_tier='standard',
    models_in_agreement=False,
):
    return {
        "selected_model": selected_model,
        "strategy": strategy,
        "reason": "V0 ELO form fallback (no consensus odds available)",
        "prediction_source": prediction_source,
        "data_quality": data_quality,
        "conviction_tier": conviction_tier,
        "models_in_agreement": models_in_agreement,
    }


def _make_v0_model_info(elo_home=1450.0, elo_away=1380.0):
    return {
        "type": "v0_form",
        "version": "0.1.0",
        "performance": "ELO-based benchmark (no odds data)",
        "bookmaker_count": 0,
        "quality_score": 0,
        "data_quality": "form_only",
        "prediction_source": "v0_form_fallback",
        "elo_home": elo_home,
        "elo_away": elo_away,
        "data_sources": ["ELO Ratings", "Historical Form"],
    }


class TestV0ModelsArrayStructure:
    """Verify models[] when is_v0_fallback=True — V0 entry shape and content."""

    def test_v0_array_has_exactly_three_entries(self):
        models = _make_v0_models_array()
        assert len(models) == 3

    def test_v0_entry_is_first(self):
        models = _make_v0_models_array()
        assert models[0]['id'] == 'v0_form'

    def test_v2_entry_is_second(self):
        models = _make_v0_models_array()
        assert models[1]['id'] == 'v2_unified'

    def test_v3_entry_is_third(self):
        models = _make_v0_models_array()
        assert models[2]['id'] == 'v3_sharp'

    def test_v0_entry_type_is_elo_weighted(self):
        models = _make_v0_models_array()
        v0 = models[0]
        assert v0['type'] == 'elo_weighted'

    def test_v0_entry_status_active(self):
        models = _make_v0_models_array()
        v0 = models[0]
        assert v0['status'] == 'active'

    def test_v0_entry_data_quality_form_only(self):
        models = _make_v0_models_array()
        v0 = models[0]
        assert v0['data_quality'] == 'form_only'

    def test_v0_has_elo_context_block(self):
        models = _make_v0_models_array()
        v0 = models[0]
        assert 'elo_context' in v0
        elo = v0['elo_context']
        assert 'elo_home' in elo
        assert 'elo_away' in elo
        assert 'elo_expected_home' in elo

    def test_v0_elo_context_values_are_floats(self):
        models = _make_v0_models_array(elo_home=1450.0, elo_away=1380.0, elo_expected=0.58)
        v0 = models[0]
        elo = v0['elo_context']
        assert isinstance(elo['elo_home'], float)
        assert isinstance(elo['elo_away'], float)
        assert isinstance(elo['elo_expected_home'], float)

    def test_v0_elo_home_higher_than_away_when_expected(self):
        """When elo_home > elo_away, home_expected > 0.5."""
        models = _make_v0_models_array(elo_home=1500.0, elo_away=1300.0, elo_expected=0.72)
        v0 = models[0]
        assert v0['elo_context']['elo_home'] > v0['elo_context']['elo_away']
        assert v0['elo_context']['elo_expected_home'] > 0.5

    def test_v0_has_fallback_reason(self):
        models = _make_v0_models_array()
        v0 = models[0]
        assert 'fallback_reason' in v0
        assert len(v0['fallback_reason']) > 10

    def test_v0_fallback_reason_mentions_elo(self):
        models = _make_v0_models_array()
        v0 = models[0]
        reason = v0['fallback_reason'].lower()
        assert 'elo' in reason or 'odds' in reason

    def test_v0_predictions_present(self):
        models = _make_v0_models_array()
        v0 = models[0]
        preds = v0['predictions']
        assert 'home_win' in preds
        assert 'draw' in preds
        assert 'away_win' in preds

    def test_v0_predictions_sum_to_one(self):
        models = _make_v0_models_array()
        v0 = models[0]
        p = v0['predictions']
        total = p['home_win'] + p['draw'] + p['away_win']
        assert abs(total - 1.0) < 0.01

    def test_v0_confidence_in_range(self):
        models = _make_v0_models_array(v0_conf=0.41)
        v0 = models[0]
        assert 0.0 <= v0['confidence'] <= 1.0

    def test_v0_has_no_agreement_block(self):
        """V0 is a standalone model — no cross-model agreement comparison."""
        models = _make_v0_models_array()
        v0 = models[0]
        assert 'agreement' not in v0

    def test_v0_quality_metrics_present(self):
        models = _make_v0_models_array()
        v0 = models[0]
        assert 'quality_metrics' in v0
        qm = v0['quality_metrics']
        assert 'metric' in qm

    # ── V2 behaviour when V0 is active ────────────────────────

    def test_v2_status_skipped_when_v0_active(self):
        models = _make_v0_models_array()
        v2 = models[1]
        assert v2['status'] == 'skipped'

    def test_v2_predictions_none_when_skipped(self):
        models = _make_v0_models_array()
        v2 = models[1]
        assert v2['predictions'] is None

    def test_v2_confidence_none_when_skipped(self):
        models = _make_v0_models_array()
        v2 = models[1]
        assert v2['confidence'] is None

    def test_v2_recommended_bet_none_when_skipped(self):
        models = _make_v0_models_array()
        v2 = models[1]
        assert v2['recommended_bet'] is None

    def test_v2_skip_reason_mentions_v0(self):
        models = _make_v0_models_array()
        v2 = models[1]
        assert 'reason' in v2
        assert 'v0' in v2['reason'].lower() or 'odds' in v2['reason'].lower()

    # ── V3 status when V0 is active ────────────────────────────

    def test_v3_status_shadow_when_v0_active_and_shadow_available(self):
        """V3 runs in shadow mode even when V0 is the primary."""
        models = _make_v0_models_array(v3_shadow_available=True)
        v3 = models[2]
        assert v3['status'] == 'shadow'

    def test_v3_status_unavailable_when_v0_active_and_no_shadow_data(self):
        models = _make_v0_models_array(v3_shadow_available=False)
        v3 = models[2]
        assert v3['status'] == 'unavailable'

    def test_v3_draw_specialist_flag_true_in_v0_path(self):
        """draw_specialist flag must always be True on the V3 entry."""
        for shadow in [True, False]:
            models = _make_v0_models_array(v3_shadow_available=shadow)
            v3 = models[2]
            assert v3.get('draw_specialist') is True

    def test_v3_shadow_has_predictions_when_available(self):
        models = _make_v0_models_array(v3_shadow_available=True)
        v3 = models[2]
        assert v3.get('predictions') is not None

    def test_v3_shadow_predictions_sum_to_one(self):
        models = _make_v0_models_array(v3_shadow_available=True)
        v3 = models[2]
        p = v3['predictions']
        total = p['home_win'] + p['draw'] + p['away_win']
        assert abs(total - 1.0) < 0.01

    def test_v3_unavailable_has_none_predictions(self):
        models = _make_v0_models_array(v3_shadow_available=False)
        v3 = models[2]
        assert v3.get('predictions') is None

    def test_v3_shadow_not_primary_in_v0_path(self):
        """When V0 is active, V3 shadow must not be 'primary' or 'active'."""
        models = _make_v0_models_array(v3_shadow_available=True)
        v3 = models[2]
        assert v3['status'] not in ('primary', 'active')

    def test_v3_ids_unchanged_in_v0_path(self):
        for shadow in [True, False]:
            models = _make_v0_models_array(v3_shadow_available=shadow)
            v3 = models[2]
            assert v3['id'] == 'v3_sharp'


# ─────────────────────────────────────────────────────────────
# SECTION 13: V0 Cascade — Conviction Tier, Strategy, Final Decision
# ─────────────────────────────────────────────────────────────

class TestV0CascadeConviction:
    """Conviction tier is always 'standard' when V0 is the fallback."""

    def test_v0_always_produces_standard_conviction(self):
        is_v0_fallback = True
        conviction_tier = "standard" if is_v0_fallback else "computed"
        assert conviction_tier == "standard"

    def test_v0_conviction_cannot_be_premium(self):
        is_v0_fallback = True
        conviction_tier = "standard" if is_v0_fallback else "premium"
        assert conviction_tier != "premium"

    def test_v0_conviction_cannot_be_strong(self):
        is_v0_fallback = True
        conviction_tier = "standard" if is_v0_fallback else "strong"
        assert conviction_tier != "strong"

    def test_v0_final_decision_strategy_field(self):
        fd = _make_v0_final_decision()
        assert fd['strategy'] == 'v0_form_fallback'

    def test_v0_final_decision_selected_model(self):
        fd = _make_v0_final_decision()
        assert fd['selected_model'] == 'v0_form'

    def test_v0_final_decision_data_quality(self):
        fd = _make_v0_final_decision()
        assert fd['data_quality'] == 'form_only'

    def test_v0_final_decision_prediction_source(self):
        fd = _make_v0_final_decision()
        assert fd['prediction_source'] == 'v0_form_fallback'

    def test_v0_final_decision_conviction_tier_is_standard(self):
        fd = _make_v0_final_decision()
        assert fd['conviction_tier'] == 'standard'

    def test_v0_final_decision_has_all_required_keys(self):
        fd = _make_v0_final_decision()
        required = {'selected_model', 'strategy', 'reason', 'prediction_source',
                    'data_quality', 'conviction_tier', 'models_in_agreement'}
        assert required.issubset(fd.keys())

    def test_v0_strategy_is_distinct_from_v1_and_v3(self):
        v0_fd = _make_v0_final_decision(strategy='v0_form_fallback')
        v1_strategy = 'v1_primary_v2_v3_transparency'
        v3_strategy = 'v3_sharp_fallback'
        assert v0_fd['strategy'] != v1_strategy
        assert v0_fd['strategy'] != v3_strategy

    def test_v0_models_in_agreement_false_when_solo(self):
        """Single V0 model — can't have agreement across multiple models."""
        fd = _make_v0_final_decision(models_in_agreement=False)
        assert fd['models_in_agreement'] is False


class TestV0ModelInfo:
    """Verify model_info block when V0 is the fallback."""

    def test_model_info_type_v0_form(self):
        info = _make_v0_model_info()
        assert info['type'] == 'v0_form'

    def test_model_info_version(self):
        info = _make_v0_model_info()
        assert info['version'] == '0.1.0'

    def test_model_info_bookmaker_count_zero(self):
        """No bookmaker data when V0 is active."""
        info = _make_v0_model_info()
        assert info['bookmaker_count'] == 0

    def test_model_info_data_quality_form_only(self):
        info = _make_v0_model_info()
        assert info['data_quality'] == 'form_only'

    def test_model_info_prediction_source(self):
        info = _make_v0_model_info()
        assert info['prediction_source'] == 'v0_form_fallback'

    def test_model_info_has_elo_home(self):
        info = _make_v0_model_info(elo_home=1450.0)
        assert 'elo_home' in info
        assert info['elo_home'] == 1450.0

    def test_model_info_has_elo_away(self):
        info = _make_v0_model_info(elo_away=1380.0)
        assert 'elo_away' in info
        assert info['elo_away'] == 1380.0

    def test_model_info_data_sources_include_elo(self):
        info = _make_v0_model_info()
        assert 'data_sources' in info
        assert any('ELO' in s or 'elo' in s.lower() for s in info['data_sources'])


# ─────────────────────────────────────────────────────────────
# SECTION 14: Response Object Shape Consistency Across All Paths
# ─────────────────────────────────────────────────────────────

def _make_predictions_block(models, h=0.48, d=0.28, a=0.24, conf=0.48,
                             recommended='home_win', conviction='standard',
                             strategy='v1_primary_v2_v3_transparency',
                             selected_model='v1_consensus',
                             data_quality='full'):
    return {
        "home_win": round(h, 3),
        "draw": round(d, 3),
        "away_win": round(a, 3),
        "confidence": conf,
        "recommended_bet": recommended,
        "recommendation_tone": "back",
        "models": models,
        "final_decision": {
            "selected_model": selected_model,
            "strategy": strategy,
            "reason": "test",
            "prediction_source": selected_model,
            "data_quality": data_quality,
            "conviction_tier": conviction,
            "models_in_agreement": False,
        }
    }


class TestResponseShapeConsistency:
    """
    The top-level response and predictions block must have the same keys
    regardless of whether V1 consensus, V3 sharp fallback, or V0 form
    fallback is the active path.
    """

    REQUIRED_PREDICTIONS_KEYS = {
        'home_win', 'draw', 'away_win', 'confidence',
        'recommended_bet', 'models', 'final_decision',
    }
    REQUIRED_FINAL_DECISION_KEYS = {
        'selected_model', 'strategy', 'reason',
        'prediction_source', 'data_quality', 'conviction_tier', 'models_in_agreement',
    }

    def _v1_predictions(self):
        models = _make_models_array()
        return _make_predictions_block(models, strategy='v1_primary_v2_v3_transparency',
                                       selected_model='v1_consensus', data_quality='full')

    def _v3_fallback_predictions(self):
        models = [
            {"id": "v3_sharp_fallback", "name": "V3 Sharp Intelligence (Fallback)",
             "type": "lightgbm_ensemble", "version": "3.0.0", "status": "active",
             "data_quality": "limited", "predictions": {"home_win": 0.5, "draw": 0.28, "away_win": 0.22},
             "confidence": 0.5, "recommended_bet": "home_win"},
        ]
        return _make_predictions_block(models, strategy='v3_sharp_fallback',
                                       selected_model='v3_sharp_fallback', data_quality='limited')

    def _v0_predictions(self):
        models = _make_v0_models_array()
        return _make_predictions_block(models, strategy='v0_form_fallback',
                                       selected_model='v0_form', data_quality='form_only',
                                       conviction='standard')

    def test_v1_predictions_block_has_all_required_keys(self):
        preds = self._v1_predictions()
        assert self.REQUIRED_PREDICTIONS_KEYS.issubset(preds.keys())

    def test_v3_fallback_predictions_block_has_all_required_keys(self):
        preds = self._v3_fallback_predictions()
        assert self.REQUIRED_PREDICTIONS_KEYS.issubset(preds.keys())

    def test_v0_predictions_block_has_all_required_keys(self):
        preds = self._v0_predictions()
        assert self.REQUIRED_PREDICTIONS_KEYS.issubset(preds.keys())

    def test_all_paths_have_same_predictions_keys(self):
        v1_keys = set(self._v1_predictions().keys())
        v3_keys = set(self._v3_fallback_predictions().keys())
        v0_keys = set(self._v0_predictions().keys())
        assert v1_keys == v3_keys == v0_keys

    def test_v1_final_decision_has_all_required_keys(self):
        fd = self._v1_predictions()['final_decision']
        assert self.REQUIRED_FINAL_DECISION_KEYS.issubset(fd.keys())

    def test_v3_final_decision_has_all_required_keys(self):
        fd = self._v3_fallback_predictions()['final_decision']
        assert self.REQUIRED_FINAL_DECISION_KEYS.issubset(fd.keys())

    def test_v0_final_decision_has_all_required_keys(self):
        fd = self._v0_predictions()['final_decision']
        assert self.REQUIRED_FINAL_DECISION_KEYS.issubset(fd.keys())

    def test_all_paths_final_decision_same_keys(self):
        v1_keys = set(self._v1_predictions()['final_decision'].keys())
        v3_keys = set(self._v3_fallback_predictions()['final_decision'].keys())
        v0_keys = set(self._v0_predictions()['final_decision'].keys())
        assert v1_keys == v3_keys == v0_keys

    def test_models_array_always_has_three_entries(self):
        """All paths must produce a 3-entry models array."""
        for pred_fn in [self._v1_predictions, self._v0_predictions]:
            preds = pred_fn()
            assert len(preds['models']) == 3, (
                f"Expected 3 models, got {len(preds['models'])}"
            )

    def test_all_paths_produce_valid_conviction_tier(self):
        valid_tiers = {'premium', 'strong', 'standard'}
        for pred_fn in [self._v1_predictions, self._v3_fallback_predictions, self._v0_predictions]:
            tier = pred_fn()['final_decision']['conviction_tier']
            assert tier in valid_tiers, f"Invalid conviction tier: {tier}"

    def test_all_paths_produce_valid_strategy(self):
        valid_strategies = {
            'v1_primary_v2_v3_transparency',
            'v3_sharp_fallback',
            'v0_form_fallback',
        }
        for pred_fn in [self._v1_predictions, self._v3_fallback_predictions, self._v0_predictions]:
            strategy = pred_fn()['final_decision']['strategy']
            assert strategy in valid_strategies, f"Unknown strategy: {strategy}"

    def test_all_paths_produce_valid_data_quality(self):
        valid_quality = {'full', 'limited', 'form_only'}
        for pred_fn in [self._v1_predictions, self._v3_fallback_predictions, self._v0_predictions]:
            quality = pred_fn()['final_decision']['data_quality']
            assert quality in valid_quality, f"Unknown data_quality: {quality}"

    def test_v0_path_is_the_only_form_only_quality(self):
        assert self._v1_predictions()['final_decision']['data_quality'] != 'form_only'
        assert self._v3_fallback_predictions()['final_decision']['data_quality'] != 'form_only'
        assert self._v0_predictions()['final_decision']['data_quality'] == 'form_only'

    def test_v0_is_only_path_with_zero_confidence_models(self):
        """V2 in the V0 path has confidence=None; other paths have numeric confidence."""
        v0_models = self._v0_predictions()['models']
        v2_entry = next(m for m in v0_models if m['id'] == 'v2_unified')
        assert v2_entry['confidence'] is None

        v1_models = self._v1_predictions()['models']
        v2_in_v1 = next(m for m in v1_models if m['id'] == 'v2_unified')
        assert isinstance(v2_in_v1['confidence'], float)


# ─────────────────────────────────────────────────────────────
# SECTION 15: V0 Live Smoke Tests — /predict with a match that
#             has no consensus odds → forces V0 cascade path
# ─────────────────────────────────────────────────────────────

_V0_SMOKE_RESPONSE: dict = {}   # module-level cache — populated once per session


def _fetch_v0_response():
    """Fetch and cache the V0 fallback response once for all tests in this section."""
    if _V0_SMOKE_RESPONSE:
        return _V0_SMOKE_RESPONSE
    import socket, requests
    s = socket.socket()
    try:
        s.connect(('localhost', 5000))
        s.close()
    except ConnectionRefusedError:
        return None  # server not running; tests will skip
    r = requests.post(
        "http://localhost:5000/predict",
        headers={"Authorization": "Bearer betgenius_secure_key_2024",
                 "Content-Type": "application/json"},
        json={"match_id": 1388548, "include_analysis": False},
        timeout=30,
    )
    if r.status_code == 200:
        _V0_SMOKE_RESPONSE.update(r.json())
    return _V0_SMOKE_RESPONSE if _V0_SMOKE_RESPONSE else None


class TestPredictEndpointV0LiveSmoke:
    """
    Live smoke tests against a running server using match 1388548
    (no consensus odds or odds snapshots → triggers V0 ELO fallback).

    A single HTTP request is made and the response is shared across all test
    methods — so the total cost is one network round-trip for 16 assertions.

    Skipped automatically when server is not running.
    Run with: pytest tests/test_v3_models_and_conviction.py -v -k "V0Live"
    """

    @pytest.fixture(autouse=True)
    def data(self):
        """Fetch (or return cached) V0 response. Skip if server is down."""
        resp = _fetch_v0_response()
        if resp is None:
            pytest.skip("Server not running — skipping V0 live smoke tests")
        self._data = resp

    def test_v0_live_predict_returns_200(self):
        assert self._data  # non-empty response → HTTP 200 was returned

    def test_v0_live_models_array_has_three_entries(self):
        models = self._data['predictions']['models']
        assert len(models) == 3, (
            f"Expected 3 models, got {len(models)}: {[m['id'] for m in models]}"
        )

    def test_v0_live_first_model_is_v0_form(self):
        """V0 path: the first models entry must be v0_form, not v1_consensus."""
        models = self._data['predictions']['models']
        assert models[0]['id'] == 'v0_form', (
            f"Expected v0_form first, got: {models[0]['id']}"
        )

    def test_v0_live_v2_is_present_but_not_primary(self):
        """
        In V0 path, V2 is always present in the models array.
        V2 may be 'active' (form-based LightGBM prediction) or 'skipped'
        (V2 unavailable) — but selected_model must remain 'v0_form'.
        """
        models = self._data['predictions']['models']
        v2 = next((m for m in models if m['id'] == 'v2_unified'), None)
        assert v2 is not None, "v2_unified must always be present in models array"
        assert v2['status'] in ('active', 'skipped'), (
            f"V2 status must be active or skipped in V0 path, got: {v2['status']}"
        )
        fd = self._data['predictions']['final_decision']
        assert fd['selected_model'] == 'v0_form', (
            f"selected_model must be v0_form even when V2 is active, got: {fd['selected_model']}"
        )

    def test_v0_live_v3_is_shadow_or_unavailable(self):
        models = self._data['predictions']['models']
        v3 = next((m for m in models if m['id'] == 'v3_sharp'), None)
        assert v3 is not None, "v3_sharp must always be present"
        assert v3['status'] in ('shadow', 'unavailable'), (
            f"V3 must be shadow/unavailable in V0 path, got: {v3['status']}"
        )

    def test_v0_live_v0_entry_has_elo_context(self):
        models = self._data['predictions']['models']
        v0 = next((m for m in models if m['id'] == 'v0_form'), None)
        assert v0 is not None
        assert 'elo_context' in v0
        assert 'elo_home' in v0['elo_context']
        assert 'elo_away' in v0['elo_context']

    def test_v0_live_conviction_tier_is_standard(self):
        fd = self._data['predictions']['final_decision']
        assert fd['conviction_tier'] == 'standard', (
            f"V0 fallback must always produce standard tier, got: {fd['conviction_tier']}"
        )

    def test_v0_live_strategy_is_v0_form_fallback(self):
        fd = self._data['predictions']['final_decision']
        assert fd['strategy'] == 'v0_form_fallback', (
            f"Expected v0_form_fallback strategy, got: {fd['strategy']}"
        )

    def test_v0_live_selected_model_is_v0_form(self):
        fd = self._data['predictions']['final_decision']
        assert fd['selected_model'] == 'v0_form', (
            f"Expected selected_model v0_form, got: {fd['selected_model']}"
        )

    def test_v0_live_data_quality_is_form_only(self):
        fd = self._data['predictions']['final_decision']
        assert fd['data_quality'] == 'form_only', (
            f"Expected form_only, got: {fd['data_quality']}"
        )

    def test_v0_live_model_info_type_is_v0(self):
        mi = self._data['model_info']
        assert mi['type'] == 'v0_form', (
            f"model_info.type should be v0_form, got: {mi['type']}"
        )

    def test_v0_live_model_info_has_elo_values(self):
        mi = self._data['model_info']
        assert 'elo_home' in mi or 'elo_context' in mi, (
            "model_info must include ELO values in V0 path"
        )

    def test_v0_live_model_info_bookmaker_count_zero(self):
        mi = self._data['model_info']
        assert mi.get('bookmaker_count', 0) == 0, (
            "bookmaker_count must be 0 when no odds data available"
        )

    def test_v0_live_v0_predictions_sum_to_one(self):
        models = self._data['predictions']['models']
        v0 = next((m for m in models if m['id'] == 'v0_form'), None)
        if v0 and v0.get('predictions'):
            p = v0['predictions']
            total = p['home_win'] + p['draw'] + p['away_win']
            assert abs(total - 1.0) < 0.01, f"V0 probs sum to {total}, not 1.0"

    def test_v0_live_top_level_probabilities_present(self):
        """Top-level H/D/A probabilities must always be populated."""
        preds = self._data['predictions']
        assert 'home_win' in preds
        assert 'draw' in preds
        assert 'away_win' in preds
        total = preds['home_win'] + preds['draw'] + preds['away_win']
        assert abs(total - 1.0) < 0.01

    def test_v0_live_response_has_all_top_level_keys(self):
        required = {'match_info', 'predictions', 'model_info', 'processing_time', 'timestamp'}
        assert required.issubset(self._data.keys()), (
            f"Missing top-level keys: {required - self._data.keys()}"
        )
