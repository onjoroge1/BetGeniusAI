"""
NBA Predictions API Routes
Endpoints for V2-NBA model predictions
"""

from fastapi import APIRouter, Query, HTTPException
from typing import Optional
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/nba", tags=["NBA Predictions"])

predictor = None

def get_predictor():
    global predictor
    if predictor is None:
        from models.v2_nba_predictor import V2NBAPredictor
        predictor = V2NBAPredictor()
    return predictor


@router.get("/predict")
async def predict_upcoming_nba(
    limit: int = Query(20, le=50, description="Max games to return")
):
    """Get predictions for all upcoming NBA games"""
    try:
        pred = get_predictor()
        predictions = pred.predict_all_upcoming(limit=limit)
        
        return {
            "count": len(predictions),
            "model_status": pred.get_model_status(),
            "predictions": predictions
        }
    except Exception as e:
        logger.error(f"NBA prediction failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/predict/matchup")
async def predict_nba_matchup(
    home: str = Query(..., description="Home team name (e.g., 'cavaliers', 'cleveland')"),
    away: str = Query(..., description="Away team name (e.g., 'thunder', 'okc')")
):
    """Predict a specific NBA matchup"""
    try:
        pred = get_predictor()
        result = pred.predict_matchup(home, away)
        
        if not result:
            raise HTTPException(status_code=404, detail=f"No upcoming game found for {home} vs {away}")
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"NBA matchup prediction failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/model-status")
async def get_nba_model_status():
    """Get V2-NBA model status and info"""
    try:
        pred = get_predictor()
        return pred.get_model_status()
    except Exception as e:
        logger.error(f"Failed to get model status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/train")
async def trigger_nba_training():
    """Trigger V2-NBA model retraining"""
    try:
        import subprocess
        import sys
        
        result = subprocess.run(
            [sys.executable, 'training/train_v2_nba.py'],
            capture_output=True,
            text=True,
            timeout=300
        )
        
        if result.returncode != 0:
            return {
                "success": False,
                "error": result.stderr,
                "output": result.stdout
            }
        
        global predictor
        predictor = None
        
        return {
            "success": True,
            "message": "V2-NBA model retrained successfully",
            "output": result.stdout
        }
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Training timed out")
    except Exception as e:
        logger.error(f"NBA training failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
