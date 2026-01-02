"""
Player Prediction API Routes

Endpoints for predicting player performance (goals, assists, involvement).
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List, Dict
from datetime import datetime, timezone
import logging
import os
import pickle
import json
from pathlib import Path
import numpy as np

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/predict-player", tags=["Player Predictions"])

MODEL_DIR = Path("artifacts/models/player_v2")


class PlayerPredictionRequest(BaseModel):
    player_id: int
    match_id: int
    

class PlayerPrediction(BaseModel):
    player_id: int
    player_name: Optional[str]
    position: Optional[str]
    team_name: Optional[str]
    match_id: int
    goal_involvement_probability: float
    predicted_goals: float
    predicted_assists: float
    confidence: str
    key_factors: List[str]


class PlayerPredictionResponse(BaseModel):
    status: str
    prediction: PlayerPrediction
    model_version: Optional[str]


def load_models():
    """Load the latest trained models."""
    latest_path = MODEL_DIR / "latest.json"
    if not latest_path.exists():
        return None, None, None
    
    with open(latest_path) as f:
        latest = json.load(f)
        version = latest.get('version')
    
    classification_path = MODEL_DIR / f"goal_involvement_{version}.pkl"
    regression_path = MODEL_DIR / f"goals_regression_{version}.pkl"
    
    if not classification_path.exists() or not regression_path.exists():
        return None, None, None
    
    with open(classification_path, 'rb') as f:
        classification_model = pickle.load(f)
    
    with open(regression_path, 'rb') as f:
        regression_model = pickle.load(f)
    
    return classification_model, regression_model, version


@router.post("/", response_model=PlayerPredictionResponse)
async def predict_player_performance(request: PlayerPredictionRequest) -> PlayerPredictionResponse:
    """
    Predict a player's performance in an upcoming match.
    
    Returns:
    - goal_involvement_probability: Chance of scoring or assisting
    - predicted_goals: Expected goals
    - predicted_assists: Expected assists (estimated from involvement)
    """
    from features.player_v2_feature_builder import PlayerV2FeatureBuilder
    import psycopg2
    from psycopg2.extras import RealDictCursor
    
    classification_model, regression_model, version = load_models()
    
    if not classification_model:
        raise HTTPException(
            status_code=503, 
            detail="Player prediction models not trained yet. Run training first."
        )
    
    try:
        conn = psycopg2.connect(os.getenv('DATABASE_URL'))
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        cur.execute("""
            SELECT player_name, position, team_name
            FROM players_unified
            WHERE player_id = %s
        """, (request.player_id,))
        player = cur.fetchone()
        
        cur.execute("""
            SELECT kickoff_at FROM fixtures 
            WHERE match_id = %s OR api_football_id = %s
            LIMIT 1
        """, (request.match_id, request.match_id))
        match = cur.fetchone()
        
        conn.close()
        
        if not player:
            raise HTTPException(status_code=404, detail=f"Player {request.player_id} not found")
        
        cutoff_time = match['kickoff_at'] if match else datetime.now(timezone.utc)
        
        builder = PlayerV2FeatureBuilder()
        features = builder.build_features(
            player_id=request.player_id,
            match_id=request.match_id,
            cutoff_time=cutoff_time
        )
        
        feature_cols = classification_model['feature_cols']
        X = np.array([[features.get(f, 0) for f in feature_cols]])
        
        involvement_probs = []
        for model in classification_model['models']:
            pred = model.predict(X, num_iteration=model.best_iteration)[0]
            involvement_probs.append(pred)
        involvement_prob = np.mean(involvement_probs)
        
        goals_preds = []
        for model in regression_model['models']:
            pred = model.predict(X, num_iteration=model.best_iteration)[0]
            goals_preds.append(max(pred, 0))
        predicted_goals = np.mean(goals_preds)
        
        predicted_assists = max(0, involvement_prob * 0.4 - predicted_goals * 0.3)
        
        if involvement_prob >= 0.5:
            confidence = "High"
        elif involvement_prob >= 0.3:
            confidence = "Medium"
        else:
            confidence = "Low"
        
        key_factors = []
        if features.get('goals_last_5', 0) >= 2:
            key_factors.append(f"Hot form: {features['goals_last_5']} goals in last 5 games")
        if features.get('position_encoded', 0) == 3:
            key_factors.append("Forward position - higher goal probability")
        if features.get('is_home_game', 0) == 1:
            key_factors.append("Home advantage")
        if features.get('opponent_goals_conceded_avg', 0) >= 1.5:
            key_factors.append(f"Opponent concedes {features['opponent_goals_conceded_avg']:.1f} goals/game")
        if features.get('is_first_choice', 0) == 1:
            key_factors.append("First choice starter")
        
        if not key_factors:
            key_factors.append("Standard prediction based on historical data")
        
        prediction = PlayerPrediction(
            player_id=request.player_id,
            player_name=player['player_name'],
            position=player['position'],
            team_name=player['team_name'],
            match_id=request.match_id,
            goal_involvement_probability=round(involvement_prob, 3),
            predicted_goals=round(predicted_goals, 3),
            predicted_assists=round(predicted_assists, 3),
            confidence=confidence,
            key_factors=key_factors[:5]
        )
        
        return PlayerPredictionResponse(
            status='success',
            prediction=prediction,
            model_version=version
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Prediction error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/top-picks")
async def get_top_player_picks(
    match_id: Optional[int] = Query(default=None, description="Specific match ID"),
    limit: int = Query(default=10, ge=1, le=50, description="Number of players to return")
) -> Dict:
    """
    Get top player picks for scoring/assisting in upcoming matches.
    
    Returns players with highest goal involvement probability.
    """
    import psycopg2
    from psycopg2.extras import RealDictCursor
    
    classification_model, regression_model, version = load_models()
    
    if not classification_model:
        return {
            'status': 'error',
            'message': 'Models not trained yet',
            'players': []
        }
    
    try:
        conn = psycopg2.connect(os.getenv('DATABASE_URL'))
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        if match_id:
            cur.execute("""
                SELECT DISTINCT pgs.player_id, p.player_name, p.position, p.team_name
                FROM player_game_stats pgs
                JOIN players_unified p ON pgs.player_id = p.player_id
                WHERE pgs.team_id IN (
                    SELECT home_team_id FROM fixtures WHERE match_id = %s OR api_football_id = %s
                    UNION
                    SELECT away_team_id FROM fixtures WHERE match_id = %s OR api_football_id = %s
                )
                AND p.position NOT ILIKE '%%G%%'
                LIMIT %s
            """, (match_id, match_id, match_id, match_id, limit * 2))
        else:
            cur.execute("""
                SELECT DISTINCT p.player_id, p.player_name, p.position, p.team_name,
                       (pss.stats->>'goals')::int as season_goals
                FROM players_unified p
                JOIN player_season_stats pss ON p.player_id = pss.player_id
                WHERE p.position NOT ILIKE '%%G%%'
                  AND pss.sport_key = 'soccer'
                  AND pss.season = 2024
                ORDER BY (pss.stats->>'goals')::int DESC NULLS LAST
                LIMIT %s
            """, (limit * 2,))
        
        players = cur.fetchall()
        conn.close()
        
        return {
            'status': 'success',
            'message': 'Use POST /api/v1/predict-player with player_id and match_id for predictions',
            'available_players': [dict(p) for p in players[:limit]],
            'model_version': version
        }
        
    except Exception as e:
        logger.error(f"Error getting top picks: {e}")
        return {'status': 'error', 'message': str(e), 'players': []}


@router.get("/model-status")
async def get_model_status() -> Dict:
    """Get status of trained player prediction models."""
    
    classification_model, regression_model, version = load_models()
    
    if not classification_model:
        return {
            'status': 'not_trained',
            'message': 'Player models not yet trained',
            'training_command': 'python training/train_player_v2.py',
            'data_collection_command': 'POST /api/v1/players/collect-game-stats?batch=True&limit=100'
        }
    
    metadata_path = MODEL_DIR / f"player_v2_metadata_{version}.json"
    metadata = {}
    if metadata_path.exists():
        with open(metadata_path) as f:
            metadata = json.load(f)
    
    return {
        'status': 'ready',
        'version': version,
        'goal_involvement_metrics': metadata.get('goal_involvement', {}).get('metrics', {}),
        'goals_regression_metrics': metadata.get('goals_regression', {}).get('metrics', {}),
        'top_features': [f['feature'] for f in metadata.get('goal_involvement', {}).get('feature_importance', [])[:10]]
    }
