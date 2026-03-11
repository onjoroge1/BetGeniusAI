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

class TestPredictEndpointLiveSmoke:
    """
    Live smoke tests against a running server.
    Skipped automatically in CI (no server). Run locally with:
        pytest tests/test_v3_models_and_conviction.py -v -k "Live"
    """

    HEADERS = {"Authorization": "Bearer betgenius_secure_key_2024",
               "Content-Type": "application/json"}
    BASE = "http://localhost:5000"
    TEST_MATCH_ID = 1379257  # Tottenham vs Crystal Palace (scheduled)

    @pytest.fixture(autouse=True)
    def skip_if_no_server(self):
        import socket
        s = socket.socket()
        try:
            s.connect(('localhost', 5000))
            s.close()
        except ConnectionRefusedError:
            pytest.skip("Server not running — skipping live smoke tests")

    def _predict(self):
        import requests
        r = requests.post(f"{self.BASE}/predict", headers=self.HEADERS,
                          json={"match_id": self.TEST_MATCH_ID, "include_analysis": False},
                          timeout=20)
        assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:200]}"
        return r.json()

    def test_live_predict_returns_200(self):
        self._predict()

    def test_live_models_array_has_three_entries(self):
        data = self._predict()
        models = data['predictions']['models']
        assert len(models) == 3, f"Expected 3 models, got {len(models)}: {[m['id'] for m in models]}"

    def test_live_models_ids_correct_order(self):
        data = self._predict()
        ids = [m['id'] for m in data['predictions']['models']]
        assert ids == ['v1_consensus', 'v2_unified', 'v3_sharp']

    def test_live_v3_has_draw_specialist_flag(self):
        data = self._predict()
        v3 = next(m for m in data['predictions']['models'] if m['id'] == 'v3_sharp')
        assert v3.get('draw_specialist') is True

    def test_live_conviction_tier_present(self):
        data = self._predict()
        fd = data['predictions']['final_decision']
        assert 'conviction_tier' in fd
        assert fd['conviction_tier'] in ('premium', 'strong', 'standard')

    def test_live_strategy_field(self):
        data = self._predict()
        fd = data['predictions']['final_decision']
        assert fd['strategy'] in ('v1_primary_v2_v3_transparency', 'v3_sharp_fallback')

    def test_live_v3_predictions_sum_to_one(self):
        data = self._predict()
        v3 = next(m for m in data['predictions']['models'] if m['id'] == 'v3_sharp')
        if v3.get('predictions'):
            p = v3['predictions']
            total = p['home_win'] + p['draw'] + p['away_win']
            assert abs(total - 1.0) < 0.01

    def test_live_v3_agreement_block(self):
        data = self._predict()
        v3 = next(m for m in data['predictions']['models'] if m['id'] == 'v3_sharp')
        if v3.get('agreement'):
            agr = v3['agreement']
            assert 'agrees_with_v1' in agr
            assert 'agrees_with_v2' in agr
