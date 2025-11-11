"""
TBD Fixture Resolver
Periodically checks if "TBD" placeholder fixtures have been updated with real team names.
Polls The Odds API every 5-10 minutes to update fixtures when teams are determined.

Architecture:
- Finds all fixtures with 'TBD' in home_team or away_team
- Caches API responses per league to avoid redundant calls
- Updates fixtures table with real team names
- Soft deletes (archives) old finished TBD fixtures instead of hard delete
- Includes retry logic and observable metrics
"""

import os
import psycopg2
import requests
import logging
import time
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
            46: "soccer_england_league2",
            61: "soccer_france_ligue_one",
            71: "soccer_brazil_campeonato",
            78: "soccer_germany_bundesliga",
            88: "soccer_netherlands_eredivisie",
            94: "soccer_portugal_primeira_liga",
            103: "soccer_norway_eliteserien",
            113: "soccer_sweden_allsvenskan",
            119: "soccer_denmark_superliga",
            135: "soccer_italy_serie_a",
            140: "soccer_spain_la_liga",
            141: "soccer_spain_segunda_division",
            144: "soccer_belgium_first_div",
            179: "soccer_scotland_premiership",
            203: "soccer_turkey_super_league",
            253: "soccer_efl_champ",
        }
        
        self.league_cache: Dict[int, List[Dict]] = {}
        self.api_calls_this_run = 0
        self.max_api_calls = 20
        
        self.metrics = {
            "tbd_count": 0,
            "resolved": 0,
            "archived": 0,
            "failed": 0,
            "api_calls": 0
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
                      AND COALESCE(archived, false) = false
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
                
                self.metrics["tbd_count"] = len(fixtures)
                logger.info(f"Found {len(fixtures)} TBD fixtures to resolve")
                return fixtures
                
        except Exception as e:
            logger.error(f"Failed to get TBD fixtures: {e}")
            return []
    
    def query_odds_api_with_cache(self, league_id: int) -> Optional[List[Dict]]:
        """
        Query The Odds API for a league (with caching to avoid redundant calls)
        Returns: List of events if successful, None otherwise
        """
        if league_id in self.league_cache:
            logger.debug(f"Using cached API response for league {league_id}")
            return self.league_cache[league_id]
        
        if self.api_calls_this_run >= self.max_api_calls:
            logger.warning(f"API call limit reached ({self.max_api_calls}), skipping league {league_id}")
            return None
        
        sport_key = self.sport_mappings.get(league_id)
        if not sport_key:
            logger.debug(f"No sport mapping for league_id {league_id}")
            return None
        
        max_retries = 3
        for attempt in range(max_retries):
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
                
                self.api_calls_this_run += 1
                self.metrics["api_calls"] += 1
                
                if not isinstance(data, list):
                    logger.warning(f"Unexpected API response format for {sport_key}")
                    return None
                
                self.league_cache[league_id] = data
                logger.debug(f"✅ Fetched and cached {len(data)} events for league {league_id}")
                return data
                
            except requests.exceptions.RequestException as e:
                wait_time = 2 ** attempt
                logger.warning(f"API request failed (attempt {attempt + 1}/{max_retries}): {e}")
                
                if attempt < max_retries - 1:
                    logger.info(f"Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    logger.error(f"Failed to query Odds API for league {league_id} after {max_retries} attempts")
                    self.metrics["failed"] += 1
                    return None
        
        return None
    
    def find_fixture_in_league_data(self, league_data: List[Dict], kickoff_at: datetime) -> Optional[Dict]:
        """
        Find a fixture in league data by kickoff time
        Returns: Dict with home_team and away_team if found, None otherwise
        """
        for event in league_data:
            try:
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
            except Exception as e:
                logger.warning(f"Error parsing event: {e}")
                continue
        
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
            self.metrics["failed"] += 1
            return False
    
    def ensure_archived_column(self):
        """
        Ensure the archived column exists in fixtures table (for soft delete)
        """
        try:
            with psycopg2.connect(self.db_url) as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    ALTER TABLE fixtures 
                    ADD COLUMN IF NOT EXISTS archived BOOLEAN DEFAULT false
                """)
                
                conn.commit()
                
        except Exception as e:
            logger.warning(f"Failed to add archived column (may already exist): {e}")
    
    def archive_old_tbd_fixtures(self) -> int:
        """
        Archive (soft delete) old finished TBD fixtures
        Returns: Number of fixtures archived
        """
        try:
            self.ensure_archived_column()
            
            with psycopg2.connect(self.db_url) as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    UPDATE fixtures
                    SET archived = true,
                        updated_at = NOW()
                    WHERE (home_team = 'TBD' OR away_team = 'TBD')
                      AND status = 'finished'
                      AND kickoff_at < NOW() - INTERVAL '24 hours'
                      AND COALESCE(archived, false) = false
                    RETURNING match_id
                """)
                
                archived_ids = cursor.fetchall()
                conn.commit()
                
                count = len(archived_ids)
                if count > 0:
                    logger.info(f"📦 Archived {count} old finished TBD fixtures (soft delete)")
                    self.metrics["archived"] = count
                
                return count
                
        except Exception as e:
            logger.error(f"Failed to archive old TBD fixtures: {e}")
            self.metrics["failed"] += 1
            return 0
    
    def resolve_tbd_fixtures(self) -> Dict[str, int]:
        """
        Main resolution process
        Returns: metrics dict with counts
        """
        self.league_cache.clear()
        self.api_calls_this_run = 0
        
        self.ensure_archived_column()
        
        tbd_fixtures = self.get_tbd_fixtures()
        
        if not tbd_fixtures:
            logger.info("No TBD fixtures to resolve")
            archived = self.archive_old_tbd_fixtures()
            return self.metrics
        
        group_by_league = {}
        for fixture in tbd_fixtures:
            league_id = fixture["league_id"]
            if league_id not in group_by_league:
                group_by_league[league_id] = []
            group_by_league[league_id].append(fixture)
        
        logger.info(f"Processing {len(tbd_fixtures)} TBD fixtures across {len(group_by_league)} leagues")
        
        for league_id, fixtures in group_by_league.items():
            league_data = self.query_odds_api_with_cache(league_id)
            
            if not league_data:
                continue
            
            for fixture in fixtures:
                match_id = fixture["match_id"]
                kickoff_at = fixture["kickoff_at"]
                
                updated_teams = self.find_fixture_in_league_data(league_data, kickoff_at)
                
                if updated_teams:
                    success = self.update_fixture_teams(
                        match_id,
                        updated_teams["home_team"],
                        updated_teams["away_team"]
                    )
                    
                    if success:
                        self.metrics["resolved"] += 1
        
        archived = self.archive_old_tbd_fixtures()
        
        logger.info(f"TBD Resolution Summary: {self.metrics['resolved']} resolved, "
                   f"{self.metrics['archived']} archived, {self.metrics['api_calls']} API calls, "
                   f"{self.metrics['failed']} failures, {self.metrics['tbd_count']} total TBD")
        
        if self.metrics['tbd_count'] > 50:
            logger.warning(f"⚠️ HIGH TBD COUNT: {self.metrics['tbd_count']} unresolved TBD fixtures detected!")
        
        return self.metrics


def run_tbd_resolution():
    """
    Entry point for scheduler
    """
    resolver = TbdFixtureResolver()
    try:
        metrics = resolver.resolve_tbd_fixtures()
        logger.info(f"TBD resolution complete: {metrics['resolved']} resolved, "
                   f"{metrics['archived']} archived, {metrics['tbd_count']} remain")
        return True
    except Exception as e:
        logger.error(f"TBD resolution failed: {e}")
        return False
