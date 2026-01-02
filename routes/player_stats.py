"""
Player Statistics API Routes

Multi-sport player statistics endpoints for Soccer, NBA, NHL.
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional, List
from pydantic import BaseModel
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/players", tags=["Player Statistics"])


class PlayerStats(BaseModel):
    player_name: str
    position: Optional[str]
    team_name: Optional[str]
    games_played: Optional[int]
    primary_stat: Optional[int]
    assists: Optional[int]
    stats: Optional[dict]


class TopScorersResponse(BaseModel):
    sport: str
    season: int
    players: List[dict]
    count: int


class PlayerSearchResponse(BaseModel):
    sport: str
    query: Optional[str]
    results: List[dict]
    count: int


@router.get("/top-scorers/{sport}")
async def get_top_scorers(
    sport: str,
    season: int = Query(default=2024, description="Season year"),
    limit: int = Query(default=20, ge=1, le=100, description="Number of results")
) -> TopScorersResponse:
    """
    Get top scorers for a sport and season.
    
    - **sport**: soccer, nba, or nhl
    - **season**: Year (e.g., 2024)
    - **limit**: Number of players to return (max 100)
    """
    from models.multisport_player_collector import MultiSportPlayerCollector
    
    if sport not in ['soccer', 'nba', 'nhl']:
        raise HTTPException(status_code=400, detail=f"Invalid sport: {sport}. Use: soccer, nba, nhl")
    
    try:
        collector = MultiSportPlayerCollector()
        players = collector.get_top_scorers(sport, season, limit)
        
        return TopScorersResponse(
            sport=sport,
            season=season,
            players=[dict(p) for p in players],
            count=len(players)
        )
    except Exception as e:
        logger.error(f"Error fetching top scorers: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/search/{sport}")
async def search_players(
    sport: str,
    name: Optional[str] = Query(default=None, description="Player name to search"),
    team_id: Optional[int] = Query(default=None, description="Filter by team ID"),
    season: Optional[int] = Query(default=None, description="Filter by season"),
    limit: int = Query(default=50, ge=1, le=100, description="Number of results")
) -> PlayerSearchResponse:
    """
    Search for players by name, team, or season.
    
    - **sport**: soccer, nba, or nhl
    - **name**: Partial player name to search
    - **team_id**: Filter by specific team
    - **season**: Filter by season year
    """
    from models.multisport_player_collector import MultiSportPlayerCollector
    
    if sport not in ['soccer', 'nba', 'nhl']:
        raise HTTPException(status_code=400, detail=f"Invalid sport: {sport}")
    
    try:
        collector = MultiSportPlayerCollector()
        players = collector.get_player_stats(
            sport=sport,
            player_name=name,
            team_id=team_id,
            season=season,
            limit=limit
        )
        
        return PlayerSearchResponse(
            sport=sport,
            query=name,
            results=[dict(p) for p in players],
            count=len(players)
        )
    except Exception as e:
        logger.error(f"Error searching players: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats/{sport}/{season}")
async def get_player_season_stats(
    sport: str,
    season: int,
    league_id: Optional[int] = Query(default=None, description="Filter by league"),
    position: Optional[str] = Query(default=None, description="Filter by position"),
    min_games: int = Query(default=1, description="Minimum games played"),
    limit: int = Query(default=100, ge=1, le=500, description="Number of results")
) -> dict:
    """
    Get player statistics for a sport and season with optional filters.
    """
    import psycopg2
    from psycopg2.extras import RealDictCursor
    import os
    
    if sport not in ['soccer', 'nba', 'nhl']:
        raise HTTPException(status_code=400, detail=f"Invalid sport: {sport}")
    
    try:
        conn = psycopg2.connect(os.environ.get('DATABASE_URL'))
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        primary_stat = 'goals' if sport in ['soccer', 'nhl'] else 'points'
        
        query = f"""
            SELECT 
                p.player_name,
                p.position,
                p.nationality,
                s.team_name,
                s.league_name,
                s.games_played,
                s.minutes_played,
                (s.stats->>'{primary_stat}')::int as primary_stat,
                (s.stats->>'assists')::int as assists,
                s.stats
            FROM player_season_stats s
            JOIN players_unified p ON s.player_id = p.player_id
            WHERE s.sport_key = %s AND s.season = %s AND s.games_played >= %s
        """
        params = [sport, season, min_games]
        
        if league_id:
            query += " AND s.league_id = %s"
            params.append(league_id)
        
        if position:
            query += " AND p.position ILIKE %s"
            params.append(f"%{position}%")
        
        query += f" ORDER BY (s.stats->>'{primary_stat}')::int DESC NULLS LAST LIMIT %s"
        params.append(limit)
        
        cur.execute(query, params)
        results = cur.fetchall()
        conn.close()
        
        return {
            'sport': sport,
            'season': season,
            'filters': {
                'league_id': league_id,
                'position': position,
                'min_games': min_games
            },
            'players': [dict(r) for r in results],
            'count': len(results)
        }
        
    except Exception as e:
        logger.error(f"Error fetching player stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/summary")
async def get_collection_summary() -> dict:
    """
    Get summary of collected player data across all sports.
    """
    from models.multisport_player_collector import MultiSportPlayerCollector
    
    try:
        collector = MultiSportPlayerCollector()
        summary = collector.get_collection_summary()
        
        return {
            'status': 'ok',
            'by_sport': [dict(s) for s in summary.get('by_sport', [])],
            'available_sports': ['soccer', 'nba', 'nhl'],
            'stat_metrics': {
                'soccer': ['goals', 'assists', 'shots_total', 'passes_accuracy', 'tackles', 'yellow_cards'],
                'nba': ['points', 'rebounds', 'assists', 'steals', 'blocks', 'fg_pct'],
                'nhl': ['goals', 'assists', 'points', 'plus_minus', 'penalty_minutes', 'shots']
            }
        }
    except Exception as e:
        logger.error(f"Error fetching summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/collect/{sport}")
async def trigger_collection(
    sport: str,
    league_id: int = Query(..., description="League ID to collect"),
    season: int = Query(default=2024, description="Season year"),
    team_id: Optional[int] = Query(default=None, description="Specific team (optional)")
) -> dict:
    """
    Trigger player stats collection for a sport/league.
    
    Note: This is an admin endpoint - collection may take time.
    """
    from models.multisport_player_collector import MultiSportPlayerCollector
    
    if sport not in ['soccer', 'nba', 'nhl']:
        raise HTTPException(status_code=400, detail=f"Invalid sport: {sport}")
    
    try:
        collector = MultiSportPlayerCollector()
        
        if sport == 'soccer':
            result = collector.collect_soccer_player_stats(league_id, season, team_id)
        elif sport == 'nba':
            season_str = f"{season}-{season+1}"
            result = collector.collect_nba_player_stats(league_id, season_str, team_id)
        elif sport == 'nhl':
            result = collector.collect_nhl_player_stats(league_id, season, team_id)
        else:
            raise HTTPException(status_code=400, detail=f"Collection not implemented for {sport}")
        
        return {
            'status': 'success',
            'sport': sport,
            'league_id': league_id,
            'season': season,
            'result': result
        }
        
    except Exception as e:
        logger.error(f"Error triggering collection: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/collect-game-stats")
async def collect_game_stats(
    fixture_id: Optional[int] = Query(default=None, description="Specific fixture ID"),
    batch: bool = Query(default=False, description="Batch collect recent fixtures"),
    limit: int = Query(default=50, ge=1, le=200, description="Batch limit"),
    days_back: int = Query(default=30, ge=1, le=365, description="Days to look back for batch")
) -> dict:
    """
    Collect player game-by-game statistics for soccer matches.
    
    Either provide a specific fixture_id or set batch=True for bulk collection.
    This data is essential for player form features in prediction models.
    """
    from models.multisport_player_collector import MultiSportPlayerCollector
    
    try:
        collector = MultiSportPlayerCollector()
        
        if fixture_id:
            result = collector.collect_soccer_game_stats(fixture_id)
            return {
                'status': 'success',
                'mode': 'single',
                'fixture_id': fixture_id,
                'players_collected': result.get('players', 0)
            }
        elif batch:
            result = collector.collect_soccer_game_stats_batch(limit=limit, days_back=days_back)
            return {
                'status': 'success',
                'mode': 'batch',
                'fixtures_processed': result.get('fixtures_processed', 0),
                'players_collected': result.get('players_collected', 0)
            }
        else:
            raise HTTPException(
                status_code=400, 
                detail="Provide fixture_id for single collection or set batch=True"
            )
        
    except Exception as e:
        logger.error(f"Error collecting game stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/game-history/{player_id}")
async def get_player_game_history(
    player_id: int,
    sport: str = Query(default="soccer", description="Sport key"),
    limit: int = Query(default=20, ge=1, le=100, description="Number of games")
) -> dict:
    """
    Get a player's game-by-game statistics history.
    
    Returns recent games with detailed stats for form analysis.
    """
    import psycopg2
    from psycopg2.extras import RealDictCursor
    import os
    
    try:
        conn = psycopg2.connect(os.getenv('DATABASE_URL'))
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        cur.execute("""
            SELECT 
                pgs.game_id,
                pgs.game_date,
                pgs.team_name,
                pgs.opponent_name,
                pgs.is_home,
                pgs.is_starter,
                pgs.minutes_played,
                pgs.rating,
                pgs.stats
            FROM player_game_stats pgs
            WHERE pgs.player_id = %s AND pgs.sport_key = %s
            ORDER BY pgs.game_date DESC
            LIMIT %s
        """, (player_id, sport, limit))
        
        games = cur.fetchall()
        
        cur.execute("""
            SELECT player_name, position, team_name
            FROM players_unified
            WHERE player_id = %s
        """, (player_id,))
        
        player = cur.fetchone()
        
        conn.close()
        
        return {
            'player_id': player_id,
            'player_name': player['player_name'] if player else None,
            'position': player['position'] if player else None,
            'current_team': player['team_name'] if player else None,
            'games': [dict(g) for g in games],
            'count': len(games)
        }
        
    except Exception as e:
        logger.error(f"Error fetching player game history: {e}")
        raise HTTPException(status_code=500, detail=str(e))
