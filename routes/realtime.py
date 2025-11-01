"""
Phase 2 - Real-time WebSocket Streaming
Provides live updates for match data via WebSocket connections
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException
from typing import Dict, Set
import logging
import json
import asyncio

logger = logging.getLogger(__name__)

router = APIRouter()

# Active WebSocket connections by match_id
active_connections: Dict[int, Set[WebSocket]] = {}


@router.websocket("/ws/live/{match_id}")
async def live_feed(websocket: WebSocket, match_id: int):
    """
    WebSocket endpoint for live match updates
    
    Streams delta payloads when:
    - Live match stats update
    - Odds velocity changes
    - Momentum scores update
    - Model markets update
    - Match events occur
    
    Payload format:
    {
        "t": "upd",               // update type
        "match_id": 1478060,
        "minute": 67,
        "score": [1, 2],
        "mom": [64, 38],          // momentum [home, away]
        "odv": {                   // odds velocity
            "home": -0.03,
            "draw": +0.01,
            "away": +0.02
        },
        "mkt": {                   // model markets (WDW)
            "home": 0.41,
            "draw": 0.30,
            "away": 0.29
        }
    }
    """
    await websocket.accept()
    
    # Add to active connections
    if match_id not in active_connections:
        active_connections[match_id] = set()
    active_connections[match_id].add(websocket)
    
    logger.info(f"WebSocket client connected for match {match_id} "
                f"({len(active_connections[match_id])} total)")
    
    try:
        while True:
            # Keep connection alive with ping/pong
            data = await websocket.receive_text()
            
            # Echo back pings
            if data == "ping":
                await websocket.send_text("pong")
    
    except WebSocketDisconnect:
        # Client disconnected
        if match_id in active_connections:
            active_connections[match_id].discard(websocket)
            
            # Clean up empty sets
            if not active_connections[match_id]:
                del active_connections[match_id]
        
        logger.info(f"WebSocket client disconnected from match {match_id}")
    
    except Exception as e:
        logger.error(f"WebSocket error for match {match_id}: {e}")
        if match_id in active_connections:
            active_connections[match_id].discard(websocket)


async def push_update(match_id: int, payload: Dict):
    """
    Push update to all clients watching a match
    
    Called by backend jobs when new data is available:
    - Live data collector
    - Momentum calculator
    - Live market engine
    - Odds velocity calculator
    
    Args:
        match_id: Match ID to push update for
        payload: Delta payload to broadcast
    """
    if match_id not in active_connections:
        return
    
    disconnected = set()
    
    for websocket in list(active_connections[match_id]):
        try:
            await websocket.send_json(payload)
        except Exception as e:
            logger.warning(f"Failed to send to WebSocket client: {e}")
            disconnected.add(websocket)
    
    # Clean up disconnected clients
    for ws in disconnected:
        active_connections[match_id].discard(ws)
    
    if not active_connections[match_id]:
        del active_connections[match_id]


def get_connection_stats() -> Dict:
    """Get statistics on active WebSocket connections"""
    return {
        "total_matches": len(active_connections),
        "total_clients": sum(len(clients) for clients in active_connections.values()),
        "matches": {
            match_id: len(clients)
            for match_id, clients in active_connections.items()
        }
    }


@router.get("/ws/stats")
async def websocket_stats():
    """
    Get WebSocket connection statistics
    Returns: {total_matches, total_clients, matches: {...}}
    """
    return get_connection_stats()
