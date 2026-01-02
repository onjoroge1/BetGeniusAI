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
                
                cur.execute("""
                    INSERT INTO player_season_stats
                        (player_id, sport_key, league_id, team_id, team_name,
                         season, games_played, minutes_played, stats, source)
                    VALUES (%s, 'nba', %s, %s, %s, %s, 1, %s, %s, 'api-basketball')
                    ON CONFLICT (player_id, sport_key, league_id, season)
                    DO UPDATE SET
                        games_played = player_season_stats.games_played + 1,
                        minutes_played = player_season_stats.minutes_played + EXCLUDED.minutes_played,
                        stats = player_season_stats.stats || EXCLUDED.stats,
                        last_updated = NOW()
                """, (
                    player_id, league_id, team.get('id'), team.get('name'),
                    season_year, minutes, psycopg2.extras.Json(stats_json)
                ))
            
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
