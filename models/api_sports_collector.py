"""
API-Sports Collector - Basketball & Baseball Stats
Collects team stats, player stats, and standings from API-Sports.io

APIs:
- API-Basketball: https://v1.basketball.api-sports.io
- API-Baseball: https://v1.baseball.api-sports.io

Uses API_SPORTS_KEY (separate from RAPIDAPI_KEY used for football)
"""

import os
import logging
import requests
import psycopg2
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class APISportsCollector:
    """
    Collects team/player data from API-Sports for V3 features.
    
    Basketball Features (V3):
    - Team offensive/defensive ratings
    - Recent form (last 5/10 games)
    - Home/Away splits
    - Back-to-back detection
    
    Baseball Features (V3):
    - Pitcher matchup data
    - Team batting/pitching stats
    - Home/Away splits
    """
    
    BASKETBALL_LEAGUES = {
        12: 'NBA',
        120: 'Euroleague'
    }
    
    BASEBALL_LEAGUES = {
        1: 'MLB'
    }
    
    def __init__(self):
        self.api_key = os.getenv('API_SPORTS_KEY')
        self.db_url = os.getenv('DATABASE_URL')
        
        self.basketball_base = "https://v1.basketball.api-sports.io"
        self.baseball_base = "https://v1.baseball.api-sports.io"
        
        if not self.api_key:
            raise ValueError("API_SPORTS_KEY not set")
        
        self.headers = {
            'x-rapidapi-key': self.api_key,
            'x-rapidapi-host': ''
        }
        
        self.metrics = {
            'api_calls': 0,
            'teams_synced': 0,
            'games_synced': 0,
            'errors': 0
        }
    
    def collect_basketball_data(self) -> Dict:
        """
        Collect NBA/Euroleague data for V3 features.
        """
        logger.info("🏀 API-Basketball: Starting collection...")
        
        results = {}
        
        for league_id, league_name in self.BASKETBALL_LEAGUES.items():
            try:
                teams = self._fetch_basketball_teams(league_id)
                games = self._fetch_basketball_games(league_id)
                
                teams_stored = self._store_teams(teams, 'basketball', league_id, league_name)
                games_stored = self._store_basketball_games(games, league_id)
                
                results[league_name] = {
                    'teams': teams_stored,
                    'games': games_stored
                }
                
                logger.info(f"  ✅ {league_name}: {teams_stored} teams, {games_stored} games")
                
            except Exception as e:
                logger.error(f"  ❌ {league_name}: {e}")
                results[league_name] = {'error': str(e)}
                self.metrics['errors'] += 1
        
        return results
    
    def collect_baseball_data(self) -> Dict:
        """
        Collect MLB data for V3 features.
        Note: MLB is off-season (Nov-Mar), so this will return limited data.
        """
        current_month = datetime.now().month
        
        if current_month in [11, 12, 1, 2, 3]:
            logger.info("⚾ API-Baseball: MLB is off-season, skipping collection")
            return {'status': 'off_season'}
        
        logger.info("⚾ API-Baseball: Starting collection...")
        
        results = {}
        
        for league_id, league_name in self.BASEBALL_LEAGUES.items():
            try:
                teams = self._fetch_baseball_teams(league_id)
                games = self._fetch_baseball_games(league_id)
                
                teams_stored = self._store_teams(teams, 'baseball', league_id, league_name)
                games_stored = self._store_baseball_games(games, league_id)
                
                results[league_name] = {
                    'teams': teams_stored,
                    'games': games_stored
                }
                
                logger.info(f"  ✅ {league_name}: {teams_stored} teams, {games_stored} games")
                
            except Exception as e:
                logger.error(f"  ❌ {league_name}: {e}")
                results[league_name] = {'error': str(e)}
        
        return results
    
    def _fetch_basketball_teams(self, league_id: int) -> List[Dict]:
        """Fetch teams for a basketball league"""
        
        self.headers['x-rapidapi-host'] = 'v1.basketball.api-sports.io'
        
        url = f"{self.basketball_base}/teams"
        params = {'league': league_id, 'season': '2024-2025'}
        
        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=30)
            self.metrics['api_calls'] += 1
            
            if response.status_code != 200:
                logger.warning(f"Basketball teams API returned {response.status_code}")
                return []
            
            data = response.json()
            return data.get('response', [])
            
        except Exception as e:
            logger.error(f"Error fetching basketball teams: {e}")
            return []
    
    def _fetch_basketball_games(self, league_id: int, days_back: int = 7, days_forward: int = 7) -> List[Dict]:
        """Fetch recent and upcoming basketball games"""
        
        self.headers['x-rapidapi-host'] = 'v1.basketball.api-sports.io'
        
        all_games = []
        
        today = datetime.now().date()
        start_date = today - timedelta(days=days_back)
        end_date = today + timedelta(days=days_forward)
        
        current_date = start_date
        while current_date <= end_date:
            url = f"{self.basketball_base}/games"
            params = {
                'league': league_id,
                'season': '2024-2025',
                'date': current_date.isoformat()
            }
            
            try:
                response = requests.get(url, headers=self.headers, params=params, timeout=30)
                self.metrics['api_calls'] += 1
                
                if response.status_code == 200:
                    data = response.json()
                    games = data.get('response', [])
                    all_games.extend(games)
            except:
                pass
            
            current_date += timedelta(days=1)
        
        return all_games
    
    def _fetch_baseball_teams(self, league_id: int) -> List[Dict]:
        """Fetch teams for a baseball league"""
        
        self.headers['x-rapidapi-host'] = 'v1.baseball.api-sports.io'
        
        url = f"{self.baseball_base}/teams"
        params = {'league': league_id, 'season': 2024}
        
        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=30)
            self.metrics['api_calls'] += 1
            
            if response.status_code != 200:
                return []
            
            data = response.json()
            return data.get('response', [])
            
        except Exception as e:
            logger.error(f"Error fetching baseball teams: {e}")
            return []
    
    def _fetch_baseball_games(self, league_id: int) -> List[Dict]:
        """Fetch baseball games"""
        
        self.headers['x-rapidapi-host'] = 'v1.baseball.api-sports.io'
        
        today = datetime.now().date()
        
        url = f"{self.baseball_base}/games"
        params = {
            'league': league_id,
            'season': 2024,
            'date': today.isoformat()
        }
        
        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=30)
            self.metrics['api_calls'] += 1
            
            if response.status_code == 200:
                data = response.json()
                return data.get('response', [])
            return []
            
        except Exception as e:
            logger.error(f"Error fetching baseball games: {e}")
            return []
    
    def _store_teams(self, teams: List[Dict], sport: str, league_id: int, league_name: str) -> int:
        """Store teams in apisports_teams_ref table"""
        
        if not teams:
            return 0
        
        stored = 0
        
        try:
            conn = psycopg2.connect(self.db_url)
            cursor = conn.cursor()
            
            for team_data in teams:
                team_id = team_data.get('id')
                team_name = team_data.get('name')
                
                if not team_id or not team_name:
                    continue
                
                logo = team_data.get('logo')
                code = team_data.get('code')
                country = team_data.get('country', {}).get('name') if isinstance(team_data.get('country'), dict) else team_data.get('country')
                
                cursor.execute("""
                    INSERT INTO apisports_teams_ref (
                        sport, team_id, team_name, team_code,
                        logo_url, league_id, league_name, country
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (sport, team_id) 
                    DO UPDATE SET
                        team_name = EXCLUDED.team_name,
                        logo_url = EXCLUDED.logo_url
                """, (
                    sport, team_id, team_name, code,
                    logo, league_id, league_name, country
                ))
                stored += 1
            
            conn.commit()
            cursor.close()
            conn.close()
            
            self.metrics['teams_synced'] += stored
            
        except Exception as e:
            logger.error(f"Error storing teams: {e}")
        
        return stored
    
    def _store_basketball_games(self, games: List[Dict], league_id: int) -> int:
        """Store basketball games and link to multisport_fixtures"""
        
        if not games:
            return 0
        
        stored = 0
        
        try:
            conn = psycopg2.connect(self.db_url)
            cursor = conn.cursor()
            
            for game in games:
                game_id = game.get('id')
                home_team = game.get('teams', {}).get('home', {})
                away_team = game.get('teams', {}).get('away', {})
                
                home_name = home_team.get('name')
                away_name = away_team.get('name')
                home_id = home_team.get('id')
                away_id = away_team.get('id')
                
                date_str = game.get('date')
                status = game.get('status', {}).get('short')
                
                scores = game.get('scores', {})
                home_score = scores.get('home', {}).get('total')
                away_score = scores.get('away', {}).get('total')
                
                if not all([game_id, home_name, away_name]):
                    continue
                
                cursor.execute("""
                    UPDATE multisport_fixtures
                    SET api_sports_id = %s,
                        home_team_id = %s,
                        away_team_id = %s,
                        home_score = COALESCE(%s, home_score),
                        away_score = COALESCE(%s, away_score),
                        status = CASE 
                            WHEN %s IN ('FT', 'AOT') THEN 'finished'
                            WHEN %s = 'NS' THEN 'scheduled'
                            ELSE status
                        END,
                        outcome = CASE 
                            WHEN %s > %s THEN 'H'
                            WHEN %s < %s THEN 'A'
                            ELSE outcome
                        END,
                        updated_at = NOW()
                    WHERE sport = 'basketball'
                      AND LOWER(home_team) LIKE %s
                      AND LOWER(away_team) LIKE %s
                      AND DATE(commence_time) = DATE(%s)
                """, (
                    game_id, home_id, away_id,
                    home_score, away_score,
                    status, status,
                    home_score, away_score, home_score, away_score,
                    f"%{home_name.lower()[:15]}%",
                    f"%{away_name.lower()[:15]}%",
                    date_str
                ))
                
                if cursor.rowcount > 0:
                    stored += 1
            
            conn.commit()
            cursor.close()
            conn.close()
            
            self.metrics['games_synced'] += stored
            
        except Exception as e:
            logger.error(f"Error storing basketball games: {e}")
        
        return stored
    
    def _store_baseball_games(self, games: List[Dict], league_id: int) -> int:
        """Store baseball games"""
        return 0
    
    def get_team_stats(self, sport: str, team_id: int, season: str = '2024-2025') -> Optional[Dict]:
        """
        Get team statistics for V3 features.
        
        Returns:
            Dict with offensive/defensive ratings, form, etc.
        """
        if sport == 'basketball':
            return self._get_basketball_team_stats(team_id, season)
        elif sport == 'baseball':
            return self._get_baseball_team_stats(team_id, season)
        return None
    
    def _get_basketball_team_stats(self, team_id: int, season: str) -> Optional[Dict]:
        """Get basketball team statistics"""
        
        self.headers['x-rapidapi-host'] = 'v1.basketball.api-sports.io'
        
        url = f"{self.basketball_base}/statistics"
        params = {'team': team_id, 'season': season, 'league': 12}
        
        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=30)
            self.metrics['api_calls'] += 1
            
            if response.status_code == 200:
                data = response.json()
                stats = data.get('response', {})
                
                if stats:
                    games = stats.get('games', {})
                    points = stats.get('points', {})
                    
                    return {
                        'games_played': games.get('played', {}).get('all', 0),
                        'wins': games.get('wins', {}).get('all', {}).get('total', 0),
                        'losses': games.get('loses', {}).get('all', {}).get('total', 0),
                        'points_for_avg': points.get('for', {}).get('average', {}).get('all', 0),
                        'points_against_avg': points.get('against', {}).get('average', {}).get('all', 0),
                        'home_wins': games.get('wins', {}).get('home', {}).get('total', 0),
                        'away_wins': games.get('wins', {}).get('away', {}).get('total', 0)
                    }
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting basketball stats: {e}")
            return None
    
    def _get_baseball_team_stats(self, team_id: int, season: str) -> Optional[Dict]:
        """Get baseball team statistics"""
        return None


_collector_instance = None

def get_api_sports_collector() -> APISportsCollector:
    """Get singleton instance of APISportsCollector"""
    global _collector_instance
    if _collector_instance is None:
        _collector_instance = APISportsCollector()
    return _collector_instance


def run_api_sports_collection():
    """Entry point for scheduler - collect all API-Sports data"""
    collector = get_api_sports_collector()
    
    results = {}
    
    logger.info("🏀⚾ API-Sports: Starting collection...")
    
    try:
        results['basketball'] = collector.collect_basketball_data()
    except Exception as e:
        logger.error(f"Basketball collection failed: {e}")
        results['basketball'] = {'error': str(e)}
    
    try:
        results['baseball'] = collector.collect_baseball_data()
    except Exception as e:
        logger.error(f"Baseball collection failed: {e}")
        results['baseball'] = {'error': str(e)}
    
    logger.info(f"🏀⚾ API-Sports Collection Complete")
    
    return results
