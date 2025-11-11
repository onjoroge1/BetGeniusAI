"""
TBD Fixture Resolver
Periodically checks if "TBD" placeholder fixtures have been updated with real team names.
Polls The Odds API every 5-10 minutes to update fixtures when teams are determined.

Architecture:
- Finds all fixtures with 'TBD' in home_team or away_team
- Queries The Odds API to check if teams have been determined
- Updates fixtures table with real team names
- Triggers team enrichment for logo fetching
- Cleans up old finished TBD fixtures (24h retention)
"""

import os
import psycopg2
import requests
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class TbdFixtureResolver:
    def __init__(self):
        self.db_url = os.getenv("DATABASE_URL")
        self.odds_api_key = os.getenv("ODDS_API_KEY")
        self.odds_api_base = "https://api.the-odds-api.com/v4"
        
        self.sport_mappings = {
            39: "soccer_england_epl",
            140: "soccer_spain_la_liga",
            78: "soccer_germany_bundesliga",
            135: "soccer_italy_serie_a",
            61: "soccer_france_ligue_one",
            94: "soccer_portugal_primeira_liga",
            88: "soccer_netherlands_eredivisie",
            203: "soccer_turkey_super_league",
            144: "soccer_belgium_first_div",
            103: "soccer_norway_eliteserien",
            113: "soccer_sweden_allsvenskan",
            119: "soccer_denmark_superliga",
            179: "soccer_scotland_premiership",
            253: "soccer_efl_champ",
        }
    
    def get_tbd_fixtures(self) -> List[Dict]:
        """
        Get all fixtures with TBD placeholders
        Returns: List of dicts with match_id, league_id, home_team, away_team, kickoff_at
        """
        try:
            with psycopg2.connect(self.db_url) as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT 
                        match_id,
                        league_id,
                        league_name,
                        home_team,
                        away_team,
                        kickoff_at,
                        status,
                        created_at
                    FROM fixtures
                    WHERE (home_team = 'TBD' OR away_team = 'TBD')
                      AND status = 'scheduled'
                      AND kickoff_at > NOW() - INTERVAL '7 days'
                    ORDER BY kickoff_at ASC
                """)
                
                fixtures = []
                for row in cursor.fetchall():
                    fixtures.append({
                        "match_id": row[0],
                        "league_id": row[1],
                        "league_name": row[2],
                        "home_team": row[3],
                        "away_team": row[4],
                        "kickoff_at": row[5],
                        "status": row[6],
                        "created_at": row[7]
                    })
                
                logger.info(f"Found {len(fixtures)} TBD fixtures to resolve")
                return fixtures
                
        except Exception as e:
            logger.error(f"Failed to get TBD fixtures: {e}")
            return []
    
    def query_odds_api_for_fixture(self, league_id: int, kickoff_at: datetime) -> Optional[Dict]:
        """
        Query The Odds API to find the fixture by league and kickoff time
        Returns: Dict with home_team and away_team if found, None otherwise
        """
        sport_key = self.sport_mappings.get(league_id)
        if not sport_key:
            logger.debug(f"No sport mapping for league_id {league_id}")
            return None
        
        try:
            url = f"{self.odds_api_base}/sports/{sport_key}/odds/"
            params = {
                "apiKey": self.odds_api_key,
                "regions": "us,uk,eu",
                "markets": "h2h",
                "oddsFormat": "decimal"
            }
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if not isinstance(data, list):
                logger.warning(f"Unexpected API response format for {sport_key}")
                return None
            
            for event in data:
                event_time = datetime.fromisoformat(event["commence_time"].replace("Z", "+00:00"))
                time_diff = abs((event_time - kickoff_at).total_seconds())
                
                if time_diff <= 3600:
                    home_team = event.get("home_team", "TBD")
                    away_team = event.get("away_team", "TBD")
                    
                    if home_team != "TBD" and away_team != "TBD":
                        return {
                            "home_team": home_team,
                            "away_team": away_team,
                            "api_event_id": event.get("id"),
                            "commence_time": event_time
                        }
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to query Odds API for league {league_id}: {e}")
            return None
    
    def update_fixture_teams(self, match_id: str, home_team: str, away_team: str) -> bool:
        """
        Update fixture with real team names
        Returns: True if successful, False otherwise
        """
        try:
            with psycopg2.connect(self.db_url) as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    UPDATE fixtures
                    SET home_team = %s,
                        away_team = %s,
                        updated_at = NOW()
                    WHERE match_id = %s
                """, (home_team, away_team, match_id))
                
                conn.commit()
                logger.info(f"✅ Updated fixture {match_id}: {home_team} vs {away_team}")
                return True
                
        except Exception as e:
            logger.error(f"Failed to update fixture {match_id}: {e}")
            return False
    
    def cleanup_old_tbd_fixtures(self) -> int:
        """
        Archive or delete old finished TBD fixtures
        Returns: Number of fixtures cleaned up
        """
        try:
            with psycopg2.connect(self.db_url) as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    DELETE FROM fixtures
                    WHERE (home_team = 'TBD' OR away_team = 'TBD')
                      AND status = 'finished'
                      AND kickoff_at < NOW() - INTERVAL '24 hours'
                    RETURNING match_id
                """)
                
                deleted_ids = cursor.fetchall()
                conn.commit()
                
                count = len(deleted_ids)
                if count > 0:
                    logger.info(f"🗑️ Cleaned up {count} old finished TBD fixtures")
                
                return count
                
        except Exception as e:
            logger.error(f"Failed to cleanup old TBD fixtures: {e}")
            return 0
    
    def resolve_tbd_fixtures(self) -> Tuple[int, int]:
        """
        Main resolution process
        Returns: (resolved_count, cleaned_up_count)
        """
        tbd_fixtures = self.get_tbd_fixtures()
        
        if not tbd_fixtures:
            logger.info("No TBD fixtures to resolve")
            cleaned_up = self.cleanup_old_tbd_fixtures()
            return 0, cleaned_up
        
        resolved_count = 0
        
        for fixture in tbd_fixtures:
            match_id = fixture["match_id"]
            league_id = fixture["league_id"]
            kickoff_at = fixture["kickoff_at"]
            
            updated_teams = self.query_odds_api_for_fixture(league_id, kickoff_at)
            
            if updated_teams:
                success = self.update_fixture_teams(
                    match_id,
                    updated_teams["home_team"],
                    updated_teams["away_team"]
                )
                
                if success:
                    resolved_count += 1
        
        cleaned_up = self.cleanup_old_tbd_fixtures()
        
        logger.info(f"TBD Resolution Summary: {resolved_count} resolved, {cleaned_up} cleaned up")
        return resolved_count, cleaned_up


def run_tbd_resolution():
    """
    Entry point for scheduler
    """
    resolver = TbdFixtureResolver()
    try:
        resolved, cleaned = resolver.resolve_tbd_fixtures()
        logger.info(f"TBD resolution complete: {resolved} resolved, {cleaned} cleaned")
        return True
    except Exception as e:
        logger.error(f"TBD resolution failed: {e}")
        return False
