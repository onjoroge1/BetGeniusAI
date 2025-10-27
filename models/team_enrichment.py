"""
Team Logo Enrichment Service
Fetches team metadata (logos, names, etc.) from API-Football and caches in teams table.
"""

import os
import time
import requests
import psycopg2
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
import logging

logger = logging.getLogger(__name__)

class TeamEnrichmentService:
    """Service for enriching team data with logos from API-Football"""
    
    def __init__(self):
        self.api_key = os.environ.get('RAPIDAPI_KEY')
        self.api_host = "api-football-v1.p.rapidapi.com"
        self.base_url = f"https://{self.api_host}/v3"
        self.cache_ttl_days = 30  # Refresh logos every 30 days
        
    def _make_api_request(self, endpoint: str, params: Dict = None) -> Optional[Dict]:
        """Make request to API-Football with rate limiting"""
        headers = {
            'x-rapidapi-host': self.api_host,
            'x-rapidapi-key': self.api_key
        }
        
        try:
            url = f"{self.base_url}{endpoint}"
            logger.info(f"API-Football request: {url} with params: {params}")
            
            response = requests.get(
                url,
                headers=headers,
                params=params or {},
                timeout=10
            )
            
            logger.info(f"API-Football response status: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                logger.info(f"API-Football response: results={len(data.get('response', []))} items")
                return data
            else:
                logger.error(f"API-Football error: {response.status_code} - {response.text[:500]}")
                return None
                
        except Exception as e:
            logger.error(f"API-Football request failed: {e}", exc_info=True)
            return None
    
    def search_team_by_name(self, team_name: str, league_id: Optional[int] = None) -> Optional[Dict]:
        """
        Search for team by name in API-Football
        Returns: {team_id, name, logo, country, etc.}
        """
        params = {'search': team_name}
        if league_id:
            params['league'] = league_id
            
        data = self._make_api_request('/teams', params)
        
        if data and data.get('response'):
            results = data['response']
            
            # Try exact match first
            for item in results:
                team = item.get('team', {})
                if team.get('name', '').lower() == team_name.lower():
                    return {
                        'api_football_team_id': team.get('id'),
                        'name': team.get('name'),
                        'logo_url': team.get('logo'),
                        'country': team.get('country'),
                        'slug': team.get('code', '').lower()
                    }
            
            # Fallback to first result if no exact match
            if results:
                team = results[0].get('team', {})
                return {
                    'api_football_team_id': team.get('id'),
                    'name': team.get('name'),
                    'logo_url': team.get('logo'),
                    'country': team.get('country'),
                    'slug': team.get('code', '').lower()
                }
        
        logger.warning(f"No team found for: {team_name}")
        return None
    
    def upsert_team(self, conn, team_data: Dict) -> Optional[int]:
        """
        Insert or update team in teams table
        Returns: team_id
        """
        cursor = conn.cursor()
        
        try:
            # Check if team exists by name (case-insensitive)
            cursor.execute("""
                SELECT team_id FROM teams 
                WHERE LOWER(name) = LOWER(%s)
                LIMIT 1
            """, (team_data['name'],))
            
            existing = cursor.fetchone()
            
            if existing:
                # Update existing team
                team_id = existing[0]
                cursor.execute("""
                    UPDATE teams 
                    SET api_football_team_id = %s,
                        logo_url = %s,
                        country = %s,
                        slug = %s,
                        logo_last_synced_at = NOW(),
                        updated_at = NOW()
                    WHERE team_id = %s
                """, (
                    team_data.get('api_football_team_id'),
                    team_data.get('logo_url'),
                    team_data.get('country'),
                    team_data.get('slug'),
                    team_id
                ))
                logger.info(f"Updated team: {team_data['name']} (ID: {team_id})")
            else:
                # Insert new team
                cursor.execute("""
                    INSERT INTO teams (
                        api_football_team_id, name, logo_url, country, slug, logo_last_synced_at
                    ) VALUES (%s, %s, %s, %s, %s, NOW())
                    RETURNING team_id
                """, (
                    team_data.get('api_football_team_id'),
                    team_data['name'],
                    team_data.get('logo_url'),
                    team_data.get('country'),
                    team_data.get('slug')
                ))
                team_id = cursor.fetchone()[0]
                logger.info(f"Inserted new team: {team_data['name']} (ID: {team_id})")
            
            conn.commit()
            return team_id
            
        except Exception as e:
            conn.rollback()
            logger.error(f"Error upserting team {team_data.get('name')}: {e}")
            return None
    
    def enrich_teams_from_fixtures(self, limit: int = 50, force: bool = False) -> Dict:
        """
        Enrich teams by extracting unique team names from fixtures
        and fetching their logos from API-Football
        
        Args:
            limit: Max teams to process (rate limit protection)
            force: Re-fetch even if cached
        
        Returns:
            {
                'teams_processed': int,
                'teams_enriched': int,
                'teams_failed': int,
                'api_calls': int
            }
        """
        conn = psycopg2.connect(os.environ.get('DATABASE_URL'))
        cursor = conn.cursor()
        
        stats = {
            'teams_processed': 0,
            'teams_enriched': 0,
            'teams_failed': 0,
            'api_calls': 0
        }
        
        try:
            # Get unique team names from fixtures that don't have logos
            if force:
                # Re-fetch all teams
                query = """
                    SELECT DISTINCT name, league_id
                    FROM (
                        SELECT home_team as name, league_id FROM fixtures WHERE home_team NOT IN ('TBD', '')
                        UNION
                        SELECT away_team as name, league_id FROM fixtures WHERE away_team NOT IN ('TBD', '')
                    ) teams
                    ORDER BY name
                    LIMIT %s
                """
            else:
                # Only fetch teams without recent logos
                query = """
                    SELECT DISTINCT name, league_id
                    FROM (
                        SELECT f.home_team as name, f.league_id 
                        FROM fixtures f
                        LEFT JOIN teams t ON LOWER(f.home_team) = LOWER(t.name)
                        WHERE f.home_team NOT IN ('TBD', '')
                          AND (t.team_id IS NULL OR t.logo_url IS NULL OR t.logo_last_synced_at < NOW() - INTERVAL '30 days')
                        UNION
                        SELECT f.away_team as name, f.league_id
                        FROM fixtures f
                        LEFT JOIN teams t ON LOWER(f.away_team) = LOWER(t.name)
                        WHERE f.away_team NOT IN ('TBD', '')
                          AND (t.team_id IS NULL OR t.logo_url IS NULL OR t.logo_last_synced_at < NOW() - INTERVAL '30 days')
                    ) teams
                    ORDER BY name
                    LIMIT %s
                """
            
            cursor.execute(query, (limit,))
            teams_to_enrich = cursor.fetchall()
            
            logger.info(f"Found {len(teams_to_enrich)} teams to enrich")
            
            for team_name, league_id in teams_to_enrich:
                stats['teams_processed'] += 1
                
                # Search API-Football for team
                team_data = self.search_team_by_name(team_name, league_id)
                stats['api_calls'] += 1
                
                if team_data:
                    # Upsert into teams table
                    team_id = self.upsert_team(conn, team_data)
                    if team_id:
                        stats['teams_enriched'] += 1
                    else:
                        stats['teams_failed'] += 1
                else:
                    stats['teams_failed'] += 1
                    # Still create placeholder team
                    placeholder = {
                        'name': team_name,
                        'logo_url': None,
                        'country': None,
                        'slug': team_name.lower().replace(' ', '-')
                    }
                    self.upsert_team(conn, placeholder)
                
                # Rate limiting: 1 request per second
                time.sleep(1)
            
            logger.info(f"Team enrichment complete: {stats}")
            
        except Exception as e:
            logger.error(f"Team enrichment failed: {e}")
            conn.rollback()
        finally:
            cursor.close()
            conn.close()
        
        return stats
    
    def link_fixtures_to_teams(self) -> Dict:
        """
        Link existing fixtures to teams table via home_team_id and away_team_id
        Returns: {fixtures_linked: int}
        """
        conn = psycopg2.connect(os.environ.get('DATABASE_URL'))
        cursor = conn.cursor()
        
        try:
            # Link home teams
            cursor.execute("""
                UPDATE fixtures f
                SET home_team_id = t.team_id
                FROM teams t
                WHERE LOWER(f.home_team) = LOWER(t.name)
                  AND f.home_team_id IS NULL
            """)
            home_linked = cursor.rowcount
            
            # Link away teams
            cursor.execute("""
                UPDATE fixtures f
                SET away_team_id = t.team_id
                FROM teams t
                WHERE LOWER(f.away_team) = LOWER(t.name)
                  AND f.away_team_id IS NULL
            """)
            away_linked = cursor.rowcount
            
            conn.commit()
            
            total_linked = home_linked + away_linked
            logger.info(f"Linked {total_linked} fixtures to teams (home: {home_linked}, away: {away_linked})")
            
            return {
                'fixtures_linked': total_linked,
                'home_linked': home_linked,
                'away_linked': away_linked
            }
            
        except Exception as e:
            conn.rollback()
            logger.error(f"Error linking fixtures to teams: {e}")
            return {'fixtures_linked': 0, 'error': str(e)}
        finally:
            cursor.close()
            conn.close()


# Singleton instance
_team_service = None

def get_team_enrichment_service() -> TeamEnrichmentService:
    """Get or create team enrichment service singleton"""
    global _team_service
    if _team_service is None:
        _team_service = TeamEnrichmentService()
    return _team_service
