import os
import time
import requests
from typing import Dict, List, Optional, Any
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class ApiFootballClient:
    """
    RapidAPI API-Football client with retry logic and rate limiting.
    Handles 429/503 errors with exponential backoff.
    """
    
    def __init__(self):
        self.api_key = os.getenv('RAPIDAPI_KEY')
        self.host = os.getenv('APIFOOTBALL_HOST', 'api-football-v1.p.rapidapi.com')
        self.base_url = f'https://{self.host}/v3'
        self.headers = {
            'x-rapidapi-key': self.api_key,
            'x-rapidapi-host': self.host
        }
        
        self.max_retries = 4
        self.base_delay = 1.0
        self.timeout = 30
        
    def _make_request(self, endpoint: str, params: Dict = None) -> Optional[Dict]:
        """
        Make API request with exponential backoff retry logic.
        Retries on 429 (rate limit) and 503 (service unavailable).
        """
        url = f"{self.base_url}/{endpoint}"
        
        for attempt in range(self.max_retries):
            try:
                response = requests.get(
                    url,
                    headers=self.headers,
                    params=params if params else {},
                    timeout=self.timeout
                )
                
                if response.status_code == 200:
                    data = response.json()
                    if data.get('errors'):
                        logger.error(f"API-Football errors: {data['errors']}")
                        return None
                    return data
                
                elif response.status_code in [429, 503]:
                    delay = self.base_delay * (2 ** attempt)
                    logger.warning(
                        f"Rate limit/unavailable (attempt {attempt + 1}/{self.max_retries}). "
                        f"Retrying in {delay}s... Status: {response.status_code}"
                    )
                    time.sleep(delay)
                    continue
                
                elif response.status_code == 404:
                    logger.debug(f"Resource not found: {endpoint} with params {params}")
                    return None
                
                else:
                    logger.error(
                        f"API-Football error: {response.status_code} - {response.text[:200]}"
                    )
                    return None
                    
            except requests.exceptions.Timeout:
                logger.error(f"Timeout on attempt {attempt + 1}/{self.max_retries}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.base_delay * (2 ** attempt))
                    continue
                return None
                
            except Exception as e:
                logger.error(f"Request failed: {str(e)}")
                return None
        
        logger.error(f"Max retries exceeded for {endpoint}")
        return None
    
    def get_bookmakers(self) -> List[Dict[str, Any]]:
        """
        Fetch all available bookmakers from API-Football.
        Returns: [{"id": 8, "name": "Bet365"}, ...]
        """
        data = self._make_request('odds/bookmakers')
        if data and 'response' in data:
            bookmakers = data['response']
            logger.info(f"Fetched {len(bookmakers)} bookmakers from API-Football")
            return bookmakers
        return []
    
    def get_odds_by_fixture(self, fixture_id: int, live: bool = False) -> Optional[Dict]:
        """
        Fetch odds for a specific fixture.
        
        Args:
            fixture_id: API-Football fixture ID
            live: If True, fetch live odds; otherwise pre-match
        
        Returns:
            Raw API response with odds data
        """
        endpoint = 'odds/live' if live else 'odds'
        params = {'fixture': fixture_id}
        
        data = self._make_request(endpoint, params)
        if data and 'response' in data and len(data['response']) > 0:
            return data['response'][0]
        
        return None
    
    def get_fixture_by_api_football_id(self, fixture_id: int) -> Optional[Dict]:
        """
        Get fixture details by API-Football fixture ID.
        Useful for validation and debugging.
        """
        data = self._make_request('fixtures', {'id': fixture_id})
        if data and 'response' in data and len(data['response']) > 0:
            return data['response'][0]
        return None
    
    def get_teams(self, league_id: int, season: int) -> List[Dict]:
        """
        Get all teams for a league and season.
        
        Args:
            league_id: API-Football league ID
            season: Season year (e.g., 2024)
        
        Returns:
            List of team dictionaries
        """
        params = {
            'league': league_id,
            'season': season
        }
        
        data = self._make_request('teams', params)
        if data and 'response' in data:
            return data['response']
        return []
    
    def search_fixtures_by_date_and_league(
        self, 
        date: str, 
        league_id: int, 
        season: int
    ) -> List[Dict]:
        """
        Search for fixtures by date and league.
        
        Args:
            date: Date in YYYY-MM-DD format
            league_id: API-Football league ID
            season: Season year (e.g., 2024)
        
        Returns:
            List of fixture dictionaries
        """
        params = {
            'date': date,
            'league': league_id,
            'season': season
        }
        
        data = self._make_request('fixtures', params)
        if data and 'response' in data:
            return data['response']
        return []
    
    def search_fixtures_by_teams(
        self,
        home_team: str,
        away_team: str,
        date_from: str,
        date_to: str,
        league_id: Optional[int] = None,
        season: Optional[int] = None
    ) -> List[Dict]:
        """
        Search for fixtures by team names and date range.
        
        Args:
            home_team: Home team name
            away_team: Away team name
            date_from: Start date (YYYY-MM-DD)
            date_to: End date (YYYY-MM-DD)
            league_id: Optional league filter
            season: Optional season year (required for date filters)
        
        Returns:
            List of matching fixtures
        """
        params = {'from': date_from, 'to': date_to}
        if league_id:
            params['league'] = league_id
        if season:
            params['season'] = season
        
        data = self._make_request('fixtures', params)
        if not data or 'response' not in data:
            return []
        
        fixtures = data['response']
        home_canonical = OddsMapper.canonicalize_bookmaker_name(home_team)
        away_canonical = OddsMapper.canonicalize_bookmaker_name(away_team)
        
        matched = []
        for fixture in fixtures:
            api_home = OddsMapper.canonicalize_bookmaker_name(
                fixture['teams']['home']['name']
            )
            api_away = OddsMapper.canonicalize_bookmaker_name(
                fixture['teams']['away']['name']
            )
            
            if home_canonical in api_home or api_home in home_canonical:
                if away_canonical in api_away or api_away in away_canonical:
                    matched.append(fixture)
        
        return matched


class OddsMapper:
    """
    Maps API-Football odds format to our internal format.
    """
    
    MARKET_MAP = {
        'Match Winner': 'h2h',
        '1X2': 'h2h',
        'Winner': 'h2h',
        'Over/Under': 'totals',
        'Goals Over/Under': 'totals',
        'Asian Handicap': 'spreads',
        'Handicap': 'spreads'
    }
    
    OUTCOME_MAP = {
        'Home': 'H',
        'Draw': 'D',
        'Away': 'A',
        'Over': 'over',
        'Under': 'under'
    }
    
    @classmethod
    def map_market(cls, api_market: str) -> Optional[str]:
        """Map API-Football market name to our internal market type."""
        return cls.MARKET_MAP.get(api_market)
    
    @classmethod
    def map_outcome(cls, api_outcome: str) -> Optional[str]:
        """Map API-Football outcome to our internal outcome code."""
        return cls.OUTCOME_MAP.get(api_outcome)
    
    @classmethod
    def canonicalize_bookmaker_name(cls, name: str) -> str:
        """
        Canonicalize bookmaker name for desk_group matching.
        Examples: "Bet365" -> "bet365", "William Hill" -> "williamhill"
        """
        return name.lower().replace(' ', '').replace('-', '').replace('_', '')
