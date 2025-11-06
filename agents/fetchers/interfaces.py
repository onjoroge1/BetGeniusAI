"""
Data Fetcher Interfaces for Phase 2

Clean separation of concerns:
- Fetchers: Pull data from external APIs
- Computers: Calculate from existing database
- Upsert: Single transaction with lineage tracking
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime


@dataclass
class FetchResult:
    """Standard result from any fetcher"""
    success: bool
    data: Optional[Dict]
    error: Optional[str]
    source: str
    fetch_duration_ms: float


class LineupFetcher(ABC):
    """Fetch player lineups and availability for a match"""
    
    @abstractmethod
    def fetch(self, match_id: int) -> FetchResult:
        """
        Fetch lineup data for a match
        
        Args:
            match_id: Match identifier
            
        Returns:
            FetchResult with data structure:
            {
                'players': [
                    {
                        'player_id': int,
                        'name': str,
                        'status': 'started' | 'bench' | 'out',
                        'minutes_played': int,
                        'reason': str (optional, e.g., 'injury', 'suspension')
                    },
                    ...
                ]
            }
        """
        pass


class RefereeFeature(ABC):
    """Fetch referee assignment and statistics"""
    
    @abstractmethod
    def fetch(self, match_id: int) -> FetchResult:
        """
        Fetch referee data for a match
        
        Args:
            match_id: Match identifier
            
        Returns:
            FetchResult with data structure:
            {
                'referee': {
                    'name': str,
                    'api_football_id': int,
                    'card_rate': float,
                    'home_bias_index': float,
                    'matches_refereed': int
                }
            }
        """
        pass


class WeatherFetcher(ABC):
    """Fetch weather conditions at match time"""
    
    @abstractmethod
    def fetch(self, latitude: float, longitude: float, kickoff_at: datetime) -> FetchResult:
        """
        Fetch weather data for a match location and time
        
        Args:
            latitude: Venue latitude
            longitude: Venue longitude
            kickoff_at: Match kickoff time
            
        Returns:
            FetchResult with data structure:
            {
                'temperature_celsius': float,
                'wind_speed_kmh': float,
                'precipitation_mm': float,
                'conditions': str ('clear' | 'rain' | 'snow' | 'cloudy')
            }
        """
        pass


class ContextComputer(ABC):
    """Compute context features from existing database"""
    
    @abstractmethod
    def compute(self, match_id: int) -> FetchResult:
        """
        Compute match context features from database
        
        Args:
            match_id: Match identifier
            
        Returns:
            FetchResult with data structure:
            {
                'rest_days_home': float,
                'rest_days_away': float,
                'schedule_congestion_home_7d': int,
                'schedule_congestion_away_7d': int,
                'derby_flag': bool
            }
        """
        pass


# Concrete implementations

class APIFootballLineupFetcher(LineupFetcher):
    """Fetch lineups from API-Football"""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://v3.football.api-sports.io"
    
    def fetch(self, match_id: int) -> FetchResult:
        """Fetch from API-Football"""
        import time
        start = time.time()
        
        try:
            # TODO: Implement actual API call
            # For now, return stub
            data = {
                'players': []
            }
            
            duration = (time.time() - start) * 1000
            
            return FetchResult(
                success=True,
                data=data,
                error=None,
                source='api-football',
                fetch_duration_ms=duration
            )
            
        except Exception as e:
            duration = (time.time() - start) * 1000
            return FetchResult(
                success=False,
                data=None,
                error=str(e),
                source='api-football',
                fetch_duration_ms=duration
            )


class APIFootballRefereeFetcher(RefereeFeature):
    """Fetch referee from API-Football"""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://v3.football.api-sports.io"
    
    def fetch(self, match_id: int) -> FetchResult:
        """Fetch from API-Football"""
        import time
        start = time.time()
        
        try:
            # TODO: Implement actual API call
            data = {
                'referee': {
                    'name': 'Unknown',
                    'api_football_id': None,
                    'card_rate': 2.5,
                    'home_bias_index': 0.0,
                    'matches_refereed': 0
                }
            }
            
            duration = (time.time() - start) * 1000
            
            return FetchResult(
                success=True,
                data=data,
                error=None,
                source='api-football',
                fetch_duration_ms=duration
            )
            
        except Exception as e:
            duration = (time.time() - start) * 1000
            return FetchResult(
                success=False,
                data=None,
                error=str(e),
                source='api-football',
                fetch_duration_ms=duration
            )


class DatabaseContextComputer(ContextComputer):
    """Compute context features from database"""
    
    def __init__(self, database_url: str):
        from sqlalchemy import create_engine
        self.engine = create_engine(database_url)
    
    def compute(self, match_id: int) -> FetchResult:
        """Compute from database"""
        import time
        from sqlalchemy import text
        
        start = time.time()
        
        try:
            # Get match metadata
            query = text("""
                SELECT home_team_id, away_team_id, match_date
                FROM training_matches
                WHERE match_id = :match_id
            """)
            
            with self.engine.connect() as conn:
                result = conn.execute(query, {"match_id": match_id}).mappings().first()
            
            if not result:
                raise ValueError(f"Match {match_id} not found")
            
            home_team_id = result['home_team_id']
            away_team_id = result['away_team_id']
            match_date = result['match_date']
            
            # Calculate rest days
            rest_days_home = self._calculate_rest_days(home_team_id, match_date)
            rest_days_away = self._calculate_rest_days(away_team_id, match_date)
            
            # Calculate schedule congestion (7 days)
            congestion_home = self._calculate_congestion(home_team_id, match_date, days=7)
            congestion_away = self._calculate_congestion(away_team_id, match_date, days=7)
            
            # Check if derby (simple heuristic: same city teams)
            derby_flag = False  # TODO: Implement proper derby detection
            
            data = {
                'rest_days_home': rest_days_home,
                'rest_days_away': rest_days_away,
                'schedule_congestion_home_7d': congestion_home,
                'schedule_congestion_away_7d': congestion_away,
                'derby_flag': derby_flag
            }
            
            duration = (time.time() - start) * 1000
            
            return FetchResult(
                success=True,
                data=data,
                error=None,
                source='database-computed',
                fetch_duration_ms=duration
            )
            
        except Exception as e:
            duration = (time.time() - start) * 1000
            return FetchResult(
                success=False,
                data=None,
                error=str(e),
                source='database-computed',
                fetch_duration_ms=duration
            )
    
    def _calculate_rest_days(self, team_id: int, match_date: datetime) -> float:
        """Calculate days since team's last match"""
        from sqlalchemy import text
        
        query = text("""
            SELECT match_date
            FROM training_matches
            WHERE (home_team_id = :team_id OR away_team_id = :team_id)
              AND match_date < :match_date
            ORDER BY match_date DESC
            LIMIT 1
        """)
        
        with self.engine.connect() as conn:
            result = conn.execute(query, {
                "team_id": team_id,
                "match_date": match_date
            }).scalar()
        
        if not result:
            return 7.0  # Default
        
        days_since = (match_date - result).total_seconds() / 86400.0
        return float(max(0, days_since))
    
    def _calculate_congestion(self, team_id: int, match_date: datetime, days: int = 7) -> int:
        """Count matches in recent window"""
        from sqlalchemy import text
        from datetime import timedelta
        
        window_start = match_date - timedelta(days=days)
        
        query = text("""
            SELECT COUNT(*) as match_count
            FROM training_matches
            WHERE (home_team_id = :team_id OR away_team_id = :team_id)
              AND match_date BETWEEN :window_start AND :match_date
              AND match_date < :match_date
        """)
        
        with self.engine.connect() as conn:
            result = conn.execute(query, {
                "team_id": team_id,
                "window_start": window_start,
                "match_date": match_date
            }).scalar()
        
        return int(result or 0)
