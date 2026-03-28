"""
Multi-Sport Player Statistics Collector

Collects player stats for Soccer, NBA, and NHL with extensible design.
Stores data in unified tables with JSONB for sport-specific metrics.
"""

import os
import logging
import requests
import psycopg2
import psycopg2.extras
from psycopg2.extras import RealDictCursor, Json
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
import time

logger = logging.getLogger(__name__)


class MultiSportPlayerCollector:
    """
    Unified player statistics collector for multiple sports.
    Supports Soccer (API-Football), NBA, and NHL (API-Sports).
    """
    
    SPORT_CONFIGS = {
        'soccer': {
            'base_url': 'https://api-football-v1.p.rapidapi.com/v3',
            'host': 'api-football-v1.p.rapidapi.com',
            'endpoints': {
                'players': '/players',
                'top_scorers': '/players/topscorers',
                'top_assists': '/players/topassists',
                'squads': '/players/squads'
            }
        },
        'nba': {
            'base_url': 'https://api-basketball.p.rapidapi.com',
            'host': 'api-basketball.p.rapidapi.com',
            'endpoints': {
                'players': '/players',
                'statistics': '/players/statistics'
            }
        },
        'nhl': {
            'base_url': 'https://api-hockey.p.rapidapi.com',
            'host': 'api-hockey.p.rapidapi.com',
            'endpoints': {
                'players': '/players',
                'statistics': '/players/statistics'
            }
        }
    }
    
    def __init__(self):
        self.api_key = os.getenv('RAPIDAPI_KEY')
        self.db_url = os.getenv('DATABASE_URL')
        
        if not self.api_key:
            raise ValueError("RAPIDAPI_KEY not set")
        
        self.metrics = {
            'api_calls': 0,
            'players_collected': 0,
            'stats_collected': 0,
            'errors': 0
        }
    
    def _get_headers(self, sport: str) -> Dict:
        """Get API headers for sport."""
        config = self.SPORT_CONFIGS.get(sport, {})
        return {
            'x-rapidapi-key': self.api_key,
            'x-rapidapi-host': config.get('host', '')
        }
    
    def _make_request(self, sport: str, endpoint: str, params: Dict) -> Optional[Dict]:
        """Make API request with rate limiting."""
        config = self.SPORT_CONFIGS.get(sport)
        if not config:
            logger.error(f"Unknown sport: {sport}")
            return None
        
        url = config['base_url'] + endpoint
        headers = self._get_headers(sport)
        
        try:
            self.metrics['api_calls'] += 1
            response = requests.get(url, headers=headers, params=params, timeout=30)
            
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 429:
                logger.warning("Rate limited, waiting...")
                time.sleep(60)
                return None
            else:
                logger.error(f"API error {response.status_code}: {response.text[:200]}")
                return None
                
        except Exception as e:
            logger.error(f"Request failed: {e}")
            self.metrics['errors'] += 1
            return None
    
    def collect_soccer_player_stats(self, league_id: int, season: int, 
                                    team_id: Optional[int] = None) -> Dict:
        """
        Collect soccer player statistics for a league/season.
        """
        logger.info(f"Collecting soccer player stats - League: {league_id}, Season: {season}")
        
        params = {'league': league_id, 'season': season}
        if team_id:
            params['team'] = team_id
        
        players_collected = 0
        page = 1
        
        while True:
            params['page'] = page
            data = self._make_request('soccer', '/players', params)
            
            if not data or not data.get('response'):
                break
            
            players = data['response']
            if not players:
                break
            
            for player_data in players:
                try:
                    self._store_soccer_player(player_data, league_id, season)
                    players_collected += 1
                except Exception as e:
                    logger.error(f"Error storing player: {e}")
                    self.metrics['errors'] += 1
            
            paging = data.get('paging', {})
            if page >= paging.get('total', 1):
                break
            
            page += 1
            time.sleep(0.2)
        
        logger.info(f"Collected {players_collected} soccer players")
        return {'sport': 'soccer', 'players': players_collected}
    
    def _store_soccer_player(self, player_data: Dict, league_id: int, season: int):
        """Store soccer player and their statistics."""
        player = player_data.get('player', {})
        statistics = player_data.get('statistics', [])
        
        if not player.get('id') or not statistics:
            return
        
        conn = psycopg2.connect(self.db_url)
        cur = conn.cursor()
        
        try:
            cur.execute("""
                INSERT INTO players_unified 
                    (sport_key, external_id, player_name, position, nationality, 
                     date_of_birth, height_cm, weight_kg, photo_url)
                VALUES ('soccer', %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (sport_key, external_id) 
                DO UPDATE SET 
                    player_name = EXCLUDED.player_name,
                    position = EXCLUDED.position,
                    updated_at = NOW()
                RETURNING player_id
            """, (
                player.get('id'),
                player.get('name'),
                statistics[0].get('games', {}).get('position') if statistics else None,
                player.get('nationality'),
                player.get('birth', {}).get('date'),
                self._parse_height(player.get('height')),
                self._parse_weight(player.get('weight')),
                player.get('photo')
            ))
            
            result = cur.fetchone()
            player_id = result[0] if result else None
            
            if player_id:
                for stat in statistics:
                    self._store_soccer_season_stats(cur, player_id, stat, league_id, season)
            
            conn.commit()
            self.metrics['players_collected'] += 1
            
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
    
    def _store_soccer_season_stats(self, cur, player_id: int, stat: Dict, 
                                    league_id: int, season: int):
        """Store soccer player season statistics."""
        team = stat.get('team', {})
        games = stat.get('games', {})
        goals = stat.get('goals', {})
        passes = stat.get('passes', {})
        tackles = stat.get('tackles', {})
        shots = stat.get('shots', {})
        cards = stat.get('cards', {})
        
        stats_json = {
            'goals': goals.get('total') or 0,
            'assists': goals.get('assists') or 0,
            'shots_total': shots.get('total') or 0,
            'shots_on_target': shots.get('on') or 0,
            'passes_total': passes.get('total') or 0,
            'passes_accuracy': passes.get('accuracy'),
            'key_passes': passes.get('key') or 0,
            'tackles': tackles.get('total') or 0,
            'interceptions': tackles.get('interceptions') or 0,
            'yellow_cards': cards.get('yellow') or 0,
            'red_cards': cards.get('red') or 0,
            'rating': games.get('rating')
        }
        
        cur.execute("""
            INSERT INTO player_season_stats
                (player_id, sport_key, league_id, league_name, team_id, team_name,
                 season, games_played, games_started, minutes_played, stats, source)
            VALUES (%s, 'soccer', %s, %s, %s, %s, %s, %s, %s, %s, %s, 'api-football')
            ON CONFLICT (player_id, sport_key, league_id, season)
            DO UPDATE SET
                games_played = EXCLUDED.games_played,
                games_started = EXCLUDED.games_started,
                minutes_played = EXCLUDED.minutes_played,
                stats = EXCLUDED.stats,
                last_updated = NOW()
        """, (
            player_id,
            league_id,
            stat.get('league', {}).get('name'),
            team.get('id'),
            team.get('name'),
            season,
            games.get('appearences') or 0,
            games.get('lineups') or 0,
            games.get('minutes') or 0,
            Json(stats_json)
        ))
        
        self.metrics['stats_collected'] += 1
    
    def collect_nba_player_stats(self, league_id: int = 12, season: str = "2024-2025",
                                  team_id: Optional[int] = None) -> Dict:
        """
        Collect NBA player statistics.
        Default league_id 12 = NBA
        """
        logger.info(f"Collecting NBA player stats - Season: {season}")
        
        params = {'league': league_id, 'season': season}
        if team_id:
            params['team'] = team_id
        
        data = self._make_request('nba', '/players/statistics', params)
        
        if not data or not data.get('response'):
            return {'sport': 'nba', 'players': 0}
        
        players_collected = 0
        for player_stat in data['response']:
            try:
                self._store_nba_player(player_stat, league_id, season)
                players_collected += 1
            except Exception as e:
                logger.error(f"Error storing NBA player: {e}")
                self.metrics['errors'] += 1
        
        logger.info(f"Collected {players_collected} NBA players")
        return {'sport': 'nba', 'players': players_collected}
    
    def _store_nba_player(self, player_stat: Dict, league_id: int, season: str):
        """Store NBA player and their statistics."""
        player = player_stat.get('player', {})
        team = player_stat.get('team', {})
        game = player_stat.get('game', {})
        
        if not player.get('id'):
            return
        
        season_year = int(season.split('-')[0]) if '-' in season else int(season)
        
        stats_json = {
            'points': player_stat.get('points') or 0,
            'rebounds': (player_stat.get('totReb') or 0),
            'off_rebounds': player_stat.get('offReb') or 0,
            'def_rebounds': player_stat.get('defReb') or 0,
            'assists': player_stat.get('assists') or 0,
            'steals': player_stat.get('steals') or 0,
            'blocks': player_stat.get('blocks') or 0,
            'turnovers': player_stat.get('turnovers') or 0,
            'fg_made': player_stat.get('fgm') or 0,
            'fg_attempted': player_stat.get('fga') or 0,
            'fg_pct': player_stat.get('fgp'),
            'three_made': player_stat.get('tpm') or 0,
            'three_attempted': player_stat.get('tpa') or 0,
            'ft_made': player_stat.get('ftm') or 0,
            'ft_attempted': player_stat.get('fta') or 0,
            'fouls': player_stat.get('pFouls') or 0,
            'plus_minus': player_stat.get('plusMinus') or 0
        }
        
        conn = psycopg2.connect(self.db_url)
        cur = conn.cursor()
        
        try:
            cur.execute("""
                INSERT INTO players_unified 
                    (sport_key, external_id, player_name, team_id, team_name, position)
                VALUES ('nba', %s, %s, %s, %s, %s)
                ON CONFLICT (sport_key, external_id) 
                DO UPDATE SET 
                    player_name = EXCLUDED.player_name,
                    team_id = EXCLUDED.team_id,
                    team_name = EXCLUDED.team_name,
                    updated_at = NOW()
                RETURNING player_id
            """, (
                player.get('id'),
                player.get('name'),
                team.get('id'),
                team.get('name'),
                player_stat.get('pos')
            ))
            
            result = cur.fetchone()
            player_id = result[0] if result else None
            
            if player_id:
                minutes = self._parse_minutes(player_stat.get('min'))
                game_id = game.get('id')
                
                cur.execute("""
                    INSERT INTO player_season_stats
                        (player_id, sport_key, league_id, team_id, team_name,
                         season, games_played, minutes_played, stats, source)
                    VALUES (%s, 'nba', %s, %s, %s, %s, 1, %s, %s, 'api-basketball')
                    ON CONFLICT (player_id, sport_key, league_id, season)
                    DO UPDATE SET
                        games_played = EXCLUDED.games_played,
                        minutes_played = EXCLUDED.minutes_played,
                        stats = jsonb_build_object(
                            'points', COALESCE((player_season_stats.stats->>'points')::int, 0) + COALESCE((%s->>'points')::int, 0),
                            'rebounds', COALESCE((player_season_stats.stats->>'rebounds')::int, 0) + COALESCE((%s->>'rebounds')::int, 0),
                            'assists', COALESCE((player_season_stats.stats->>'assists')::int, 0) + COALESCE((%s->>'assists')::int, 0),
                            'steals', COALESCE((player_season_stats.stats->>'steals')::int, 0) + COALESCE((%s->>'steals')::int, 0),
                            'blocks', COALESCE((player_season_stats.stats->>'blocks')::int, 0) + COALESCE((%s->>'blocks')::int, 0),
                            'turnovers', COALESCE((player_season_stats.stats->>'turnovers')::int, 0) + COALESCE((%s->>'turnovers')::int, 0),
                            'fg_made', COALESCE((player_season_stats.stats->>'fg_made')::int, 0) + COALESCE((%s->>'fg_made')::int, 0),
                            'fg_attempted', COALESCE((player_season_stats.stats->>'fg_attempted')::int, 0) + COALESCE((%s->>'fg_attempted')::int, 0),
                            'three_made', COALESCE((player_season_stats.stats->>'three_made')::int, 0) + COALESCE((%s->>'three_made')::int, 0),
                            'ft_made', COALESCE((player_season_stats.stats->>'ft_made')::int, 0) + COALESCE((%s->>'ft_made')::int, 0),
                            'fouls', COALESCE((player_season_stats.stats->>'fouls')::int, 0) + COALESCE((%s->>'fouls')::int, 0),
                            'games_tracked', COALESCE((player_season_stats.stats->>'games_tracked')::int, 0) + 1
                        ),
                        last_updated = NOW()
                    WHERE NOT EXISTS (
                        SELECT 1 FROM player_game_stats 
                        WHERE player_id = %s AND sport_key = 'nba' AND game_id = %s
                    )
                """, (
                    player_id, league_id, team.get('id'), team.get('name'),
                    season_year, minutes, psycopg2.extras.Json(stats_json),
                    psycopg2.extras.Json(stats_json), psycopg2.extras.Json(stats_json),
                    psycopg2.extras.Json(stats_json), psycopg2.extras.Json(stats_json),
                    psycopg2.extras.Json(stats_json), psycopg2.extras.Json(stats_json),
                    psycopg2.extras.Json(stats_json), psycopg2.extras.Json(stats_json),
                    psycopg2.extras.Json(stats_json), psycopg2.extras.Json(stats_json),
                    psycopg2.extras.Json(stats_json),
                    player_id, game_id
                ))
                
                if game_id:
                    cur.execute("""
                        INSERT INTO player_game_stats (player_id, sport_key, game_id, stats, source)
                        VALUES (%s, 'nba', %s, %s, 'api-basketball')
                        ON CONFLICT (player_id, sport_key, game_id) DO NOTHING
                    """, (player_id, game_id, psycopg2.extras.Json(stats_json)))
            
            conn.commit()
            self.metrics['players_collected'] += 1
            
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
    
    def collect_nhl_player_stats(self, league_id: int = 57, season: int = 2024,
                                  team_id: Optional[int] = None) -> Dict:
        """
        Collect NHL player statistics.
        Default league_id 57 = NHL
        """
        logger.info(f"Collecting NHL player stats - Season: {season}")
        
        params = {'league': league_id, 'season': season}
        if team_id:
            params['team'] = team_id
        
        data = self._make_request('nhl', '/players/statistics', params)
        
        if not data or not data.get('response'):
            return {'sport': 'nhl', 'players': 0}
        
        players_collected = 0
        for player_stat in data['response']:
            try:
                self._store_nhl_player(player_stat, league_id, season)
                players_collected += 1
            except Exception as e:
                logger.error(f"Error storing NHL player: {e}")
                self.metrics['errors'] += 1
        
        logger.info(f"Collected {players_collected} NHL players")
        return {'sport': 'nhl', 'players': players_collected}
    
    def _store_nhl_player(self, player_stat: Dict, league_id: int, season: int):
        """Store NHL player and their statistics."""
        player = player_stat.get('player', {})
        team = player_stat.get('team', {})
        statistics = player_stat.get('statistics', {})
        
        if not player.get('id'):
            return
        
        stats_json = {
            'goals': statistics.get('goals') or 0,
            'assists': statistics.get('assists') or 0,
            'points': (statistics.get('goals') or 0) + (statistics.get('assists') or 0),
            'plus_minus': statistics.get('plusMinus') or 0,
            'penalty_minutes': statistics.get('pim') or 0,
            'shots': statistics.get('shots') or 0,
            'hits': statistics.get('hits') or 0,
            'blocked_shots': statistics.get('blocked') or 0,
            'takeaways': statistics.get('takeaways') or 0,
            'giveaways': statistics.get('giveaways') or 0,
            'faceoff_wins': statistics.get('faceoffWins') or 0,
            'faceoff_losses': statistics.get('faceoffLosses') or 0,
            'saves': statistics.get('saves') or 0,
            'goals_against': statistics.get('goalsAgainst') or 0
        }
        
        conn = psycopg2.connect(self.db_url)
        cur = conn.cursor()
        
        try:
            cur.execute("""
                INSERT INTO players_unified 
                    (sport_key, external_id, player_name, team_id, team_name, 
                     nationality, position)
                VALUES ('nhl', %s, %s, %s, %s, %s, %s)
                ON CONFLICT (sport_key, external_id) 
                DO UPDATE SET 
                    player_name = EXCLUDED.player_name,
                    team_id = EXCLUDED.team_id,
                    team_name = EXCLUDED.team_name,
                    updated_at = NOW()
                RETURNING player_id
            """, (
                player.get('id'),
                player.get('name'),
                team.get('id'),
                team.get('name'),
                player.get('nationality'),
                player.get('position')
            ))
            
            result = cur.fetchone()
            player_id = result[0] if result else None
            
            if player_id:
                cur.execute("""
                    INSERT INTO player_season_stats
                        (player_id, sport_key, league_id, team_id, team_name,
                         season, games_played, stats, source)
                    VALUES (%s, 'nhl', %s, %s, %s, %s, %s, %s, 'api-hockey')
                    ON CONFLICT (player_id, sport_key, league_id, season)
                    DO UPDATE SET
                        games_played = EXCLUDED.games_played,
                        stats = EXCLUDED.stats,
                        last_updated = NOW()
                """, (
                    player_id, league_id, team.get('id'), team.get('name'),
                    season, statistics.get('games') or 0,
                    Json(stats_json)
                ))
            
            conn.commit()
            self.metrics['players_collected'] += 1
            
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
    
    def get_player_stats(self, sport: str, player_name: Optional[str] = None,
                         team_id: Optional[int] = None, season: Optional[int] = None,
                         limit: int = 50) -> List[Dict]:
        """
        Query player statistics across sports.
        """
        conn = psycopg2.connect(self.db_url)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        try:
            query = """
                SELECT 
                    p.player_name,
                    p.position,
                    p.nationality,
                    s.team_name,
                    s.season,
                    s.games_played,
                    s.minutes_played,
                    s.stats
                FROM player_season_stats s
                JOIN players_unified p ON s.player_id = p.player_id
                WHERE s.sport_key = %s
            """
            params = [sport]
            
            if player_name:
                query += " AND p.player_name ILIKE %s"
                params.append(f"%{player_name}%")
            
            if team_id:
                query += " AND s.team_id = %s"
                params.append(team_id)
            
            if season:
                query += " AND s.season = %s"
                params.append(season)
            
            query += " ORDER BY (s.stats->>'goals')::int DESC NULLS LAST LIMIT %s"
            params.append(limit)
            
            cur.execute(query, params)
            return cur.fetchall()
            
        finally:
            conn.close()
    
    def get_top_scorers(self, sport: str, season: int, limit: int = 20) -> List[Dict]:
        """Get top scorers for a sport/season."""
        conn = psycopg2.connect(self.db_url)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        try:
            if sport == 'soccer':
                goal_field = 'goals'
            elif sport == 'nba':
                goal_field = 'points'
            else:
                goal_field = 'goals'
            
            cur.execute(f"""
                SELECT 
                    p.player_name,
                    p.position,
                    s.team_name,
                    s.games_played,
                    (s.stats->>'{goal_field}')::int as primary_stat,
                    (s.stats->>'assists')::int as assists,
                    s.stats
                FROM player_season_stats s
                JOIN players_unified p ON s.player_id = p.player_id
                WHERE s.sport_key = %s AND s.season = %s
                ORDER BY (s.stats->>'{goal_field}')::int DESC NULLS LAST
                LIMIT %s
            """, (sport, season, limit))
            
            return cur.fetchall()
            
        finally:
            conn.close()
    
    def _parse_height(self, height_str: Optional[str]) -> Optional[int]:
        """Parse height string to cm."""
        if not height_str:
            return None
        try:
            return int(height_str.replace(' cm', '').strip())
        except:
            return None
    
    def _parse_weight(self, weight_str: Optional[str]) -> Optional[int]:
        """Parse weight string to kg."""
        if not weight_str:
            return None
        try:
            return int(weight_str.replace(' kg', '').strip())
        except:
            return None
    
    def _parse_minutes(self, min_str: Optional[str]) -> int:
        """Parse minutes string (e.g., '32:45') to total minutes."""
        if not min_str:
            return 0
        try:
            if ':' in str(min_str):
                parts = str(min_str).split(':')
                return int(parts[0])
            return int(min_str)
        except:
            return 0
    
    def collect_soccer_game_stats(self, fixture_id: int) -> Dict:
        """
        Collect player game-by-game statistics for a specific fixture.
        Uses /fixtures/players endpoint from API-Football.
        
        Returns detailed per-game stats: goals, assists, shots, minutes, etc.
        Essential for player form features in prediction models.
        """
        logger.info(f"Collecting player game stats for fixture {fixture_id}")
        
        data = self._make_request('soccer', '/fixtures/players', {'fixture': fixture_id})
        
        if not data or not data.get('response'):
            return {'fixture_id': fixture_id, 'players': 0, 'error': 'No data'}
        
        players_collected = 0
        conn = psycopg2.connect(self.db_url)
        cur = conn.cursor()
        
        try:
            cur.execute("""
                SELECT league_id, home_team_id, away_team_id, 
                       home_team, away_team, kickoff_at::date as game_date
                FROM fixtures WHERE match_id = %s
            """, (fixture_id,))
            fixture_info = cur.fetchone()
            
            if not fixture_info:
                logger.warning(f"Fixture {fixture_id} not found in fixtures table")
                return {'fixture_id': fixture_id, 'players': 0, 'error': 'Fixture not found'}
            
            league_id, home_team_id, away_team_id, home_team_name, away_team_name, game_date = fixture_info
            
            for team_data in data['response']:
                team = team_data.get('team', {})
                team_id = team.get('id')
                team_name = team.get('name')
                
                is_home = (team_id == home_team_id)
                if is_home:
                    opponent_team_id = away_team_id
                    opponent_name = away_team_name
                else:
                    opponent_team_id = home_team_id
                    opponent_name = home_team_name
                
                players = team_data.get('players', [])
                for player_entry in players:
                    player = player_entry.get('player', {})
                    statistics = player_entry.get('statistics', [{}])[0]
                    
                    if not player.get('id'):
                        continue
                    
                    games = statistics.get('games', {})
                    goals_data = statistics.get('goals', {})
                    shots_data = statistics.get('shots', {})
                    passes_data = statistics.get('passes', {})
                    tackles_data = statistics.get('tackles', {})
                    duels_data = statistics.get('duels', {})
                    fouls_data = statistics.get('fouls', {})
                    cards_data = statistics.get('cards', {})
                    dribbles_data = statistics.get('dribbles', {})
                    
                    minutes = self._parse_minutes(games.get('minutes'))
                    
                    stats_json = {
                        'goals': goals_data.get('total') or 0,
                        'assists': goals_data.get('assists') or 0,
                        'shots': shots_data.get('total') or 0,
                        'shots_on_target': shots_data.get('on') or 0,
                        'passes': passes_data.get('total') or 0,
                        'passes_accuracy': passes_data.get('accuracy') or 0,
                        'key_passes': passes_data.get('key') or 0,
                        'tackles': tackles_data.get('total') or 0,
                        'interceptions': tackles_data.get('interceptions') or 0,
                        'blocks': tackles_data.get('blocks') or 0,
                        'duels_total': duels_data.get('total') or 0,
                        'duels_won': duels_data.get('won') or 0,
                        'fouls_drawn': fouls_data.get('drawn') or 0,
                        'fouls_committed': fouls_data.get('committed') or 0,
                        'yellow_cards': cards_data.get('yellow') or 0,
                        'red_cards': cards_data.get('red') or 0,
                        'dribbles_attempts': dribbles_data.get('attempts') or 0,
                        'dribbles_success': dribbles_data.get('success') or 0,
                        'saves': goals_data.get('saves') or 0,
                        'conceded': goals_data.get('conceded') or 0
                    }
                    
                    rating = None
                    if games.get('rating'):
                        try:
                            rating = float(games.get('rating'))
                        except:
                            pass
                    
                    cur.execute("""
                        INSERT INTO players_unified 
                            (sport_key, external_id, player_name, position, photo_url)
                        VALUES ('soccer', %s, %s, %s, %s)
                        ON CONFLICT (sport_key, external_id) 
                        DO UPDATE SET 
                            player_name = EXCLUDED.player_name,
                            position = COALESCE(EXCLUDED.position, players_unified.position),
                            updated_at = NOW()
                        RETURNING player_id
                    """, (
                        player.get('id'),
                        player.get('name'),
                        games.get('position'),
                        player.get('photo')
                    ))
                    
                    result = cur.fetchone()
                    player_id = result[0] if result else None
                    
                    if player_id:
                        cur.execute("""
                            INSERT INTO player_game_stats
                                (player_id, sport_key, game_id, league_id, team_id, team_name,
                                 opponent_team_id, opponent_name, game_date, is_home, is_starter, 
                                 minutes_played, stats, rating, source)
                            VALUES (%s, 'soccer', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'api-football')
                            ON CONFLICT (player_id, sport_key, game_id) 
                            DO UPDATE SET
                                opponent_team_id = EXCLUDED.opponent_team_id,
                                opponent_name = EXCLUDED.opponent_name,
                                is_home = EXCLUDED.is_home,
                                minutes_played = EXCLUDED.minutes_played,
                                stats = EXCLUDED.stats,
                                rating = EXCLUDED.rating,
                                collected_at = NOW()
                        """, (
                            player_id, fixture_id, league_id, team_id, team_name,
                            opponent_team_id, opponent_name, game_date, is_home,
                            games.get('captain') or (games.get('substitute') == False),
                            minutes, Json(stats_json), rating
                        ))
                        players_collected += 1
            
            conn.commit()
            logger.info(f"Collected {players_collected} player game stats for fixture {fixture_id}")
            
        except Exception as e:
            conn.rollback()
            logger.error(f"Error collecting game stats for fixture {fixture_id}: {e}")
            return {'fixture_id': fixture_id, 'players': 0, 'error': str(e)}
        finally:
            conn.close()
        
        self.metrics['stats_collected'] += players_collected
        return {'fixture_id': fixture_id, 'players': players_collected}
    
    def collect_soccer_game_stats_batch(self, limit: int = 100, days_back: int = 30) -> Dict:
        """
        Batch collect player game stats for recent finished fixtures.
        Skips fixtures that already have player game stats collected.
        """
        logger.info(f"Batch collecting player game stats (limit={limit}, days_back={days_back})")
        
        conn = psycopg2.connect(self.db_url)
        cur = conn.cursor()
        
        try:
            cur.execute("""
                SELECT f.match_id
                FROM fixtures f
                WHERE f.status = 'finished'
                  AND f.kickoff_at >= NOW() - INTERVAL '%s days'
                  AND f.match_id IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM player_game_stats pgs 
                      WHERE pgs.game_id = f.match_id AND pgs.sport_key = 'soccer'
                  )
                ORDER BY f.kickoff_at DESC
                LIMIT %s
            """, (days_back, limit))
            
            fixtures = [row[0] for row in cur.fetchall()]
            
        finally:
            conn.close()
        
        total_players = 0
        fixtures_processed = 0
        
        for fixture_id in fixtures:
            result = self.collect_soccer_game_stats(fixture_id)
            total_players += result.get('players', 0)
            fixtures_processed += 1
            time.sleep(0.3)
        
        logger.info(f"Batch complete: {fixtures_processed} fixtures, {total_players} player stats")
        return {
            'fixtures_processed': fixtures_processed,
            'players_collected': total_players
        }

    def collect_stats_for_pending_player_parlays(self, limit: int = 50) -> Dict:
        """
        Collect player game stats for matches with pending player parlays.
        Prioritizes matches that have already finished but need settlement data.
        """
        logger.info("Collecting game stats for pending player parlays")
        
        conn = psycopg2.connect(self.db_url)
        cur = conn.cursor()
        
        try:
            cur.execute("""
                SELECT DISTINCT ppl.match_id
                FROM player_parlay_legs ppl
                JOIN player_parlays pp ON ppl.parlay_id = pp.id
                JOIN fixtures f ON ppl.match_id = f.match_id
                WHERE pp.status = 'pending'
                  AND f.status = 'finished'
                  AND NOT EXISTS (
                      SELECT 1 FROM player_game_stats pgs 
                      WHERE pgs.game_id = ppl.match_id AND pgs.sport_key = 'soccer'
                  )
                ORDER BY ppl.match_id DESC
                LIMIT %s
            """, (limit,))
            
            fixture_ids = [row[0] for row in cur.fetchall()]
            
        finally:
            conn.close()
        
        logger.info(f"Found {len(fixture_ids)} matches needing game stats for parlays")
        
        total_players = 0
        fixtures_processed = 0
        
        for fixture_id in fixture_ids:
            result = self.collect_soccer_game_stats(fixture_id)
            total_players += result.get('players', 0)
            fixtures_processed += 1
            time.sleep(0.3)
        
        logger.info(f"Parlay stats: {fixtures_processed} fixtures, {total_players} player stats")
        return {
            'fixtures_processed': fixtures_processed,
            'players_collected': total_players
        }

    def get_collection_summary(self) -> Dict:
        """Get summary of collected player data."""
        conn = psycopg2.connect(self.db_url)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        try:
            cur.execute("""
                SELECT
                    sport_key,
                    COUNT(DISTINCT player_id) as total_players,
                    COUNT(*) as total_stat_records,
                    MAX(last_updated) as last_updated
                FROM player_season_stats
                GROUP BY sport_key
            """)

            return {
                'by_sport': cur.fetchall(),
                'metrics': self.metrics
            }

        finally:
            conn.close()

    # ═══════════════════════════════════════════════════════════
    # NBA / NHL GAME-BY-GAME STATS COLLECTION
    # ═══════════════════════════════════════════════════════════

    def collect_nba_game_stats_batch(self, days_back: int = 7, limit: int = 30) -> Dict:
        """
        Collect NBA player game stats for recently finished games.
        Discovers API-Sports game IDs via /games endpoint, then fetches per-game player stats.
        """
        logger.info(f"🏀 Collecting NBA game-by-game stats (last {days_back} days)...")
        conn = psycopg2.connect(self.db_url)
        cur = conn.cursor()

        try:
            # Find finished NBA games not yet in player_game_stats
            cur.execute("""
                SELECT f.event_id, f.home_team, f.away_team,
                       f.home_score, f.away_score, f.commence_time::date as game_date
                FROM multisport_fixtures f
                WHERE f.sport_key = 'basketball_nba'
                  AND f.status IN ('finished', 'completed')
                  AND f.commence_time > NOW() - INTERVAL '%s days'
                  AND NOT EXISTS (
                      SELECT 1 FROM player_game_stats pgs
                      WHERE pgs.game_id = f.event_id AND pgs.sport_key = 'nba'
                  )
                ORDER BY f.commence_time DESC
                LIMIT %s
            """, (days_back, limit))
            games = cur.fetchall()
            logger.info(f"  Found {len(games)} NBA games needing player stats")

            # Discover API-Sports game IDs by querying /games by date
            dates_needed = sorted(set(str(g[5]) for g in games))
            api_game_map = {}  # (date, home_lower) -> api_game_id
            for date_str in dates_needed[:5]:  # max 5 API calls for date lookups
                try:
                    data = self._make_request('nba', '/games', {'league': 12, 'season': '2025-2026', 'date': date_str})
                    if data and data.get('response'):
                        for g in data['response']:
                            teams = g.get('teams', {})
                            home_name = teams.get('home', {}).get('name', '').lower()
                            api_game_map[(date_str, home_name)] = g.get('id')
                    time.sleep(0.3)
                except Exception as e:
                    logger.debug(f"  NBA date lookup {date_str} failed: {e}")

            # Now resolve event_id -> api_game_id
            resolved_games = []
            for event_id, home, away, hs, as_, game_date in games:
                api_id = api_game_map.get((str(game_date), home.lower()))
                if not api_id:
                    # Try fuzzy match
                    for (d, h), gid in api_game_map.items():
                        if d == str(game_date) and (home.lower() in h or h in home.lower()):
                            api_id = gid
                            break
                if api_id:
                    resolved_games.append((event_id, api_id, home, away, hs, as_, game_date))

            logger.info(f"  Resolved {len(resolved_games)}/{len(games)} games to API-Sports IDs")
            games = resolved_games

            total_players = 0
            games_processed = 0

            for eid, api_id, home, away, hs, as_, game_date in games:
                try:
                    data = self._make_request('nba', '/players/statistics', {'game': api_id})
                    if not data or not data.get('response'):
                        continue

                    for ps in data['response']:
                        player = ps.get('player', {})
                        team = ps.get('team', {})
                        if not player.get('id'):
                            continue

                        minutes = self._parse_minutes(ps.get('min'))
                        if minutes < 1:
                            continue

                        stats_json = {
                            'points': ps.get('points') or 0,
                            'rebounds': (ps.get('totReb') or 0),
                            'assists': ps.get('assists') or 0,
                            'steals': ps.get('steals') or 0,
                            'blocks': ps.get('blocks') or 0,
                            'turnovers': ps.get('turnovers') or 0,
                            'fg_made': ps.get('fgm') or 0,
                            'fg_attempted': ps.get('fga') or 0,
                            'three_made': ps.get('tpm') or 0,
                            'three_attempted': ps.get('tpa') or 0,
                            'ft_made': ps.get('ftm') or 0,
                            'ft_attempted': ps.get('fta') or 0,
                            'fouls': ps.get('pFouls') or 0,
                            'plus_minus': ps.get('plusMinus') or 0,
                        }

                        # Upsert player
                        cur.execute("""
                            INSERT INTO players_unified (sport_key, external_id, player_name, team_id, team_name, position)
                            VALUES ('nba', %s, %s, %s, %s, %s)
                            ON CONFLICT (sport_key, external_id)
                            DO UPDATE SET player_name=EXCLUDED.player_name, team_id=EXCLUDED.team_id, team_name=EXCLUDED.team_name
                            RETURNING player_id
                        """, (player['id'], player.get('name'), team.get('id'), team.get('name'), ps.get('pos')))
                        pid = cur.fetchone()[0]

                        is_home = team.get('name', '').lower() in home.lower() or home.lower() in team.get('name', '').lower()
                        opp_name = away if is_home else home

                        # Use event_id as game_id (consistent with fixture lookup)
                        cur.execute("""
                            INSERT INTO player_game_stats
                                (player_id, sport_key, game_id, league_id, team_id, team_name,
                                 opponent_team_id, opponent_name, game_date, is_home, is_starter,
                                 minutes_played, stats, rating, source)
                            VALUES (%s, 'nba', %s, 12, %s, %s, NULL, %s, %s, %s, %s, %s, %s, NULL, 'api-basketball')
                            ON CONFLICT (player_id, sport_key, game_id) DO NOTHING
                        """, (pid, eid, team.get('id'), team.get('name'),
                              opp_name, game_date, is_home, ps.get('pos') is not None,
                              minutes, Json(stats_json)))
                        total_players += 1

                    conn.commit()
                    games_processed += 1
                    time.sleep(0.3)

                except Exception as e:
                    conn.rollback()
                    logger.warning(f"  NBA game {api_id} failed: {e}")

            logger.info(f"✅ NBA game stats: {total_players} player stats from {games_processed} games")
            return {'sport': 'nba', 'games': games_processed, 'players': total_players}

        except Exception as e:
            logger.error(f"NBA game stats batch failed: {e}", exc_info=True)
            return {'sport': 'nba', 'games': 0, 'players': 0, 'error': str(e)}
        finally:
            conn.close()

    def collect_nhl_game_stats_batch(self, days_back: int = 7, limit: int = 30) -> Dict:
        """
        Collect NHL player game stats for recently finished games.
        Discovers API-Sports game IDs via /games endpoint, then fetches per-game player stats.
        """
        logger.info(f"🏒 Collecting NHL game-by-game stats (last {days_back} days)...")
        conn = psycopg2.connect(self.db_url)
        cur = conn.cursor()

        try:
            cur.execute("""
                SELECT f.event_id, f.home_team, f.away_team,
                       f.home_score, f.away_score, f.commence_time::date as game_date
                FROM multisport_fixtures f
                WHERE f.sport_key = 'icehockey_nhl'
                  AND f.status IN ('finished', 'completed')
                  AND f.commence_time > NOW() - INTERVAL '%s days'
                  AND NOT EXISTS (
                      SELECT 1 FROM player_game_stats pgs
                      WHERE pgs.game_id = f.event_id AND pgs.sport_key = 'nhl'
                  )
                ORDER BY f.commence_time DESC
                LIMIT %s
            """, (days_back, limit))
            games_raw = cur.fetchall()
            logger.info(f"  Found {len(games_raw)} NHL games needing player stats")

            # Resolve API-Sports game IDs by date
            dates_needed = sorted(set(str(g[5]) for g in games_raw))
            api_game_map = {}
            for date_str in dates_needed[:5]:
                try:
                    data = self._make_request('hockey', '/games', {'league': 57, 'season': 2025, 'date': date_str})
                    if data and data.get('response'):
                        for g in data['response']:
                            teams = g.get('teams', {})
                            home_name = teams.get('home', {}).get('name', '').lower()
                            api_game_map[(date_str, home_name)] = g.get('id')
                    time.sleep(0.3)
                except Exception as e:
                    logger.debug(f"  NHL date lookup {date_str} failed: {e}")

            games = []
            for event_id, home, away, hs, as_, game_date in games_raw:
                api_id = api_game_map.get((str(game_date), home.lower()))
                if not api_id:
                    for (d, h), gid in api_game_map.items():
                        if d == str(game_date) and (home.lower() in h or h in home.lower()):
                            api_id = gid
                            break
                if api_id:
                    games.append((event_id, api_id, home, away, hs, as_, game_date))

            logger.info(f"  Resolved {len(games)}/{len(games_raw)} games to API-Sports IDs")

            total_players = 0
            games_processed = 0

            for eid, api_id, home, away, hs, as_, game_date in games:
                try:
                    data = self._make_request('hockey', '/players/statistics', {'game': api_id})
                    if not data or not data.get('response'):
                        continue

                    for ps in data['response']:
                        player = ps.get('player', {})
                        team = ps.get('team', {})
                        statistics = ps.get('statistics', [{}])
                        stat = statistics[0] if statistics else {}

                        if not player.get('id'):
                            continue

                        goals = stat.get('goals') or 0
                        assists = stat.get('assists') or 0
                        shots = stat.get('shots', {}).get('total') or 0
                        toi = stat.get('time', '0:00')
                        minutes = self._parse_minutes(toi)
                        if minutes < 1:
                            continue

                        stats_json = {
                            'goals': goals,
                            'assists': assists,
                            'points': goals + assists,
                            'shots': shots,
                            'plus_minus': stat.get('plusMinus') or 0,
                            'penalty_minutes': stat.get('penaltyMinutes') or 0,
                            'hits': stat.get('hits') or 0,
                            'blocked_shots': stat.get('blockedShots') or 0,
                            'takeaways': stat.get('takeaways') or 0,
                            'giveaways': stat.get('giveaways') or 0,
                            'faceoff_wins': stat.get('faceoffs', {}).get('won') or 0,
                            'faceoff_losses': stat.get('faceoffs', {}).get('lost') or 0,
                        }

                        # Upsert player
                        cur.execute("""
                            INSERT INTO players_unified (sport_key, external_id, player_name, team_id, team_name, position)
                            VALUES ('nhl', %s, %s, %s, %s, %s)
                            ON CONFLICT (sport_key, external_id)
                            DO UPDATE SET player_name=EXCLUDED.player_name, team_id=EXCLUDED.team_id, team_name=EXCLUDED.team_name
                            RETURNING player_id
                        """, (player['id'], player.get('name'), team.get('id'), team.get('name'),
                              stat.get('position') or player.get('position')))
                        pid = cur.fetchone()[0]

                        is_home = team.get('name', '').lower() in home.lower() or home.lower() in team.get('name', '').lower()
                        opp_name = away if is_home else home

                        cur.execute("""
                            INSERT INTO player_game_stats
                                (player_id, sport_key, game_id, league_id, team_id, team_name,
                                 opponent_team_id, opponent_name, game_date, is_home, is_starter,
                                 minutes_played, stats, rating, source)
                            VALUES (%s, 'nhl', %s, 57, %s, %s, NULL, %s, %s, %s, TRUE, %s, %s, NULL, 'api-hockey')
                            ON CONFLICT (player_id, sport_key, game_id) DO NOTHING
                        """, (pid, eid, team.get('id'), team.get('name'),
                              opp_name, game_date, is_home, minutes, Json(stats_json)))
                        total_players += 1

                    conn.commit()
                    games_processed += 1
                    time.sleep(0.3)

                except Exception as e:
                    conn.rollback()
                    logger.warning(f"  NHL game {api_id} failed: {e}")

            logger.info(f"✅ NHL game stats: {total_players} player stats from {games_processed} games")
            return {'sport': 'nhl', 'games': games_processed, 'players': total_players}

        except Exception as e:
            logger.error(f"NHL game stats batch failed: {e}", exc_info=True)
            return {'sport': 'nhl', 'games': 0, 'players': 0, 'error': str(e)}
        finally:
            conn.close()
