"""
Shadow Inference Coordinator
Runs both V1 and V2 models in parallel, logs predictions for A/B testing
"""

import os
import psycopg2
from datetime import datetime, timezone
from typing import Dict, Tuple, Optional
import logging
import time

from models.v2_predictor import V2Predictor

logger = logging.getLogger(__name__)

class ShadowInferenceCoordinator:
    """
    Coordinates shadow inference for V1 vs V2 A/B testing
    
    - Runs both models in parallel
    - Logs predictions to model_inference_logs
    - Returns primary model prediction based on config
    """
    
    def __init__(self):
        self.database_url = os.environ.get('DATABASE_URL')
        self.v2_predictor = V2Predictor()
        
    def _get_config(self, key: str, default: str = "") -> str:
        """Get config value from model_config table"""
        try:
            with psycopg2.connect(self.database_url) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT config_value FROM model_config WHERE config_key = %s",
                    (key,)
                )
                result = cursor.fetchone()
                return result[0] if result else default
        except Exception as e:
            logger.error(f"Error reading config {key}: {e}")
            return default
    
    def get_primary_model(self) -> str:
        """Get current primary model version"""
        return self._get_config('PRIMARY_MODEL_VERSION', 'v1')
    
    def is_shadow_enabled(self) -> bool:
        """Check if shadow V2 testing is enabled"""
        return self._get_config('ENABLE_SHADOW_V2', 'false').lower() == 'true'
    
    async def predict_with_shadow(
        self,
        match_id: int,
        v1_prediction: Dict,
        features: Dict
    ) -> Dict:
        """
        Run shadow inference for both v1 and v2
        
        Args:
            match_id: Match identifier
            v1_prediction: Existing v1 prediction dict with prob_home, prob_draw, prob_away
            features: Feature dict for v2 model
        
        Returns:
            Primary model prediction + metadata
        """
        
        primary_model = self.get_primary_model()
        shadow_enabled = self.is_shadow_enabled()
        
        start_time = time.time()
        
        # Extract V1 probabilities from prediction result structure
        v1_probs = v1_prediction.get('probabilities', {})
        
        v1_pred = {
            'p_home': v1_probs.get('home', 0.33),
            'p_draw': v1_probs.get('draw', 0.33),
            'p_away': v1_probs.get('away', 0.33),
            'model_version': 'v1',
            'reason_code': 'WEIGHTED_CONSENSUS'
        }
        
        if shadow_enabled:
            ph_v2, pd_v2, pa_v2, reason_v2 = self.v2_predictor.predict(features)
            
            v2_pred = {
                'p_home': ph_v2,
                'p_draw': pd_v2,
                'p_away': pa_v2,
                'model_version': 'v2',
                'reason_code': reason_v2
            }
            
            latency_ms = int((time.time() - start_time) * 1000)
            
            self._log_predictions(match_id, features.get('league_id', 0), v1_pred, latency_ms)
            self._log_predictions(match_id, features.get('league_id', 0), v2_pred, latency_ms)
        else:
            v2_pred = None
        
        if primary_model == 'v2' and v2_pred:
            return {
                **v2_pred,
                'shadow_logged': shadow_enabled,
                'primary_model': 'v2'
            }
        else:
            return {
                **v1_pred,
                'shadow_logged': shadow_enabled,
                'primary_model': 'v1'
            }
    
    def _log_predictions(
        self,
        match_id: int,
        league_id: int,
        prediction: Dict,
        latency_ms: int
    ):
        """
        Log prediction to model_inference_logs table
        
        Args:
            match_id: Match identifier
            league_id: League identifier
            prediction: Dict with model_version, p_home, p_draw, p_away, reason_code
            latency_ms: Inference latency in milliseconds
        """
        
        try:
            with psycopg2.connect(self.database_url) as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    INSERT INTO model_inference_logs (
                        match_id, league_id, model_version,
                        p_home, p_draw, p_away,
                        latency_ms, reason_code, scored_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (match_id, model_version) DO UPDATE SET
                        p_home = EXCLUDED.p_home,
                        p_draw = EXCLUDED.p_draw,
                        p_away = EXCLUDED.p_away,
                        latency_ms = EXCLUDED.latency_ms,
                        reason_code = EXCLUDED.reason_code,
                        scored_at = NOW()
                """, (
                    match_id,
                    league_id,
                    prediction['model_version'],
                    prediction['p_home'],
                    prediction['p_draw'],
                    prediction['p_away'],
                    latency_ms,
                    prediction.get('reason_code', '')
                ))
                
                conn.commit()
                
                logger.debug(
                    f"Logged {prediction['model_version']} prediction for match {match_id}: "
                    f"H={prediction['p_home']:.3f} D={prediction['p_draw']:.3f} A={prediction['p_away']:.3f}"
                )
                
        except Exception as e:
            logger.error(f"Error logging prediction for match {match_id}: {e}")
