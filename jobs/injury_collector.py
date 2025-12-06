"""
Injury Collector Job

Collects injury and suspension data from API-Football for upcoming matches.
Computes team injury impact scores for V3 features.

V3 Features derived:
1. home_injury_impact / away_injury_impact - Weighted impact of missing players
2. home_key_players_out / away_key_players_out - Count of key players out
3. injury_advantage - Relative team strength change
4. total_squad_availability - % of first XI available

Runs: Every 6 hours (injuries don't change rapidly)
API Endpoint: https://v3.football.api-sports.io/injuries
"""

import os
import logging
import requests
import psycopg2
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class InjuryCollector:
    """
    Collects injury/suspension data from API-Football
    
    Player value ratings are estimated based on position and typical importance:
    - Goalkeeper: 7.0-9.0 (critical if first choice)
    - Defenders: 5.0-8.0
    - Midfielders: 6.0-9.0
    - Forwards: 7.0-10.0 (star strikers highest impact)
    """
    
    POSITION_BASE_RATINGS = {
        'Goalkeeper': 7.5,
        'Defender': 6.0,
        'Midfielder': 7.0,
        'Attacker': 8.0
    }
    
    INJURY_TYPE_MAPPING = {
        'Missing Fixture': 'Injury',
        'Questionable': 'Doubt',
        'Suspended': 'Suspension',
        'International Duty': 'International'
    }
    
    def __init__(self):
        self.api_key = os.getenv('RAPIDAPI_KEY')
        self.db_url = os.getenv('DATABASE_URL')
        
        if not self.api_key:
            raise ValueError("RAPIDAPI_KEY not set")
        if not self.db_url:
            raise ValueError("DATABASE_URL not set")
        
        self.base_url = "https://api-football-v1.p.rapidapi.com/v3"
        self.headers = {
            'x-rapidapi-key': self.api_key,
            'x-rapidapi-host': 'api-football-v1.p.rapidapi.com'
        }
        
        self.metrics = {
            'api_calls': 0,
            'injuries_stored': 0,
            'summaries_updated': 0,
            'errors': 0
        }
    
    TRACKED_LEAGUES = [
        39,   # Premier League
        140,  # La Liga
        78,   # Bundesliga
        135,  # Serie A
        61,   # Ligue 1
        2,    # Champions League
        3,    # Europa League
        848,  # Conference League
        88,   # Eredivisie
        94,   # Primeira Liga (Portugal)
    ]
    
    def collect_upcoming_injuries(self, days_ahead: int = 7) -> Dict:
        """Collect injuries for matches in the next N days"""
        
        logger.info(f"🏥 Starting injury collection (next {days_ahead} days)...")
        
        try:
            conn = psycopg2.connect(self.db_url)
            cursor = conn.cursor()
            
            # Get upcoming fixtures
            fixtures = self._get_upcoming_fixtures(cursor, days_ahead)
            logger.info(f"  Found {len(fixtures)} upcoming fixtures")
            
            # Collect injuries per fixture
            for fixture_id, home_id, away_id, kickoff, league_id in fixtures:
                try:
                    injuries = self._fetch_fixture_injuries(fixture_id)
                    
                    if injuries:
                        self._store_injuries(cursor, injuries, fixture_id, kickoff, league_id)
                        self._update_team_summaries(cursor, fixture_id, home_id, away_id, injuries)
                        
                except Exception as e:
                    logger.error(f"  Error for fixture {fixture_id}: {e}")
                    self.metrics['errors'] += 1
            
            conn.commit()
            cursor.close()
            conn.close()
            
            logger.info(f"✅ Injury collection complete: {self.metrics['injuries_stored']} injuries, "
                       f"{self.metrics['summaries_updated']} summaries")
            
        except Exception as e:
            logger.error(f"❌ Injury collection failed: {e}")
            self.metrics['errors'] += 1
        
        return self.metrics
    
    def collect_league_injuries(self, league_ids: List[int] = None, season: int = 2024) -> Dict:
        """
        Collect injuries by league - more efficient than fixture-by-fixture.
        Returns all injuries for players in specified leagues this season.
        """
        
        if league_ids is None:
            league_ids = self.TRACKED_LEAGUES
        
        logger.info(f"🏥 Starting league-based injury collection for {len(league_ids)} leagues...")
        
        try:
            conn = psycopg2.connect(self.db_url)
            cursor = conn.cursor()
            
            for league_id in league_ids:
                try:
                    injuries = self._fetch_league_injuries(league_id, season)
                    logger.info(f"  League {league_id}: {len(injuries)} injuries found")
                    
                    for injury in injuries:
                        self._store_league_injury(cursor, injury)
                    
                except Exception as e:
                    logger.error(f"  Error for league {league_id}: {e}")
                    self.metrics['errors'] += 1
            
            conn.commit()
            cursor.close()
            conn.close()
            
            logger.info(f"✅ League injury collection complete: {self.metrics['injuries_stored']} injuries stored")
            
        except Exception as e:
            logger.error(f"❌ League injury collection failed: {e}")
            self.metrics['errors'] += 1
        
        return self.metrics
    
    def _fetch_league_injuries(self, league_id: int, season: int) -> List[Dict]:
        """Fetch all injuries for a league/season from API-Football"""
        
        url = f"{self.base_url}/injuries"
        params = {'league': league_id, 'season': season}
        
        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=30)
            self.metrics['api_calls'] += 1
            
            if response.status_code == 200:
                data = response.json()
                return data.get('response', [])
            else:
                logger.warning(f"  API returned {response.status_code} for league {league_id}")
                return []
                
        except requests.RequestException as e:
            logger.error(f"  API request failed: {e}")
            return []
    
    def _parse_fixture_date(self, date_str: str) -> Optional[datetime]:
        """Parse ISO date string from API to date object"""
        if not date_str:
            return None
        try:
            return datetime.fromisoformat(date_str.replace('+00:00', '').replace('Z', '')).date()
        except (ValueError, TypeError):
            return None
    
    def _store_league_injury(self, cursor, injury: Dict):
        """Store a single injury record from league-based collection"""
        
        player = injury.get('player', {})
        team = injury.get('team', {})
        fixture = injury.get('fixture', {})
        league = injury.get('league', {})
        
        player_id = player.get('id')
        player_name = player.get('name', 'Unknown')
        team_id = team.get('id')
        team_name = team.get('name')
        league_id = league.get('id')
        
        injury_type = player.get('type', 'Unknown')
        injury_reason = player.get('reason', '')
        
        fixture_id = fixture.get('id')
        fixture_date = self._parse_fixture_date(fixture.get('date'))
        
        base_rating = 6.0
        if 'Questionable' in str(injury_type) or 'Doubt' in str(injury_type):
            rating_multiplier = 0.5
        else:
            rating_multiplier = 1.0
        
        player_rating = base_rating * rating_multiplier
        
        try:
            cursor.execute("""
                INSERT INTO player_injuries (
                    player_id, player_name, team_id, team_name, league_id,
                    injury_type, injury_reason, player_value_rating,
                    fixture_id, fixture_date, source, ts_recorded
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, 'api-football', NOW()
                )
                ON CONFLICT (player_id, fixture_id) 
                DO UPDATE SET
                    injury_type = EXCLUDED.injury_type,
                    injury_reason = EXCLUDED.injury_reason,
                    player_value_rating = EXCLUDED.player_value_rating,
                    ts_recorded = NOW()
            """, (
                player_id, player_name, team_id, team_name, league_id,
                injury_type, injury_reason, player_rating,
                fixture_id, fixture_date
            ))
            self.metrics['injuries_stored'] += 1
            
        except Exception as e:
            logger.debug(f"  Insert error: {e}")
    
    def _get_upcoming_fixtures(self, cursor, days_ahead: int) -> List:
        """Get upcoming fixtures from database"""
        
        now = datetime.now(timezone.utc)
        end_date = now + timedelta(days=days_ahead)
        
        cursor.execute("""
            SELECT 
                f.match_id,
                f.home_team_id,
                f.away_team_id,
                f.kickoff_at,
                f.league_id
            FROM fixtures f
            WHERE f.kickoff_at BETWEEN %s AND %s
              AND f.status = 'scheduled'
              AND f.home_team_id IS NOT NULL
            ORDER BY f.kickoff_at
            LIMIT 100
        """, (now, end_date))
        
        return cursor.fetchall()
    
    def _fetch_fixture_injuries(self, fixture_id: int) -> List[Dict]:
        """Fetch injuries from API-Football for a specific fixture"""
        
        url = f"{self.base_url}/injuries"
        params = {'fixture': fixture_id}
        
        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=30)
            self.metrics['api_calls'] += 1
            
            if response.status_code == 200:
                data = response.json()
                return data.get('response', [])
            else:
                logger.warning(f"  API returned {response.status_code} for fixture {fixture_id}")
                return []
                
        except requests.RequestException as e:
            logger.error(f"  API request failed: {e}")
            return []
    
    def _store_injuries(self, cursor, injuries: List[Dict], fixture_id: int, 
                        fixture_date: datetime, league_id: int):
        """Store injury records in database"""
        
        for injury in injuries:
            player = injury.get('player', {})
            team = injury.get('team', {})
            
            player_id = player.get('id')
            player_name = player.get('name', 'Unknown')
            team_id = team.get('id')
            team_name = team.get('name')
            
            injury_type = injury.get('player', {}).get('type', 'Unknown')
            injury_reason = injury.get('player', {}).get('reason', '')
            
            # Estimate player value rating based on position and injury type
            position = player.get('position', 'Unknown')
            base_rating = self.POSITION_BASE_RATINGS.get(position, 6.0)
            
            # Adjust rating based on injury type (definite out vs doubtful)
            if 'Questionable' in injury_type or 'Doubt' in injury_type:
                rating_multiplier = 0.5  # Less certain impact
            else:
                rating_multiplier = 1.0
            
            player_rating = base_rating * rating_multiplier
            
            try:
                cursor.execute("""
                    INSERT INTO player_injuries (
                        player_id, player_name, team_id, team_name, league_id,
                        injury_type, injury_reason, player_value_rating,
                        fixture_id, fixture_date, source, ts_recorded
                    ) VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, 'api-football', NOW()
                    )
                    ON CONFLICT (player_id, fixture_id) 
                    DO UPDATE SET
                        injury_type = EXCLUDED.injury_type,
                        injury_reason = EXCLUDED.injury_reason,
                        player_value_rating = EXCLUDED.player_value_rating,
                        ts_recorded = NOW()
                """, (
                    player_id, player_name, team_id, team_name, league_id,
                    injury_type, injury_reason, player_rating,
                    fixture_id, fixture_date.date() if fixture_date else None
                ))
                self.metrics['injuries_stored'] += 1
                
            except Exception as e:
                logger.debug(f"  Insert error: {e}")
    
    def _update_team_summaries(self, cursor, fixture_id: int, 
                                home_id: int, away_id: int, injuries: List[Dict]):
        """Update team injury summaries for the match"""
        
        home_injuries = []
        away_injuries = []
        
        for injury in injuries:
            team_id = injury.get('team', {}).get('id')
            player = injury.get('player', {})
            
            injury_info = {
                'name': player.get('name', 'Unknown'),
                'type': player.get('type', 'Unknown'),
                'reason': player.get('reason', ''),
                'position': player.get('position', 'Unknown')
            }
            
            if team_id == home_id:
                home_injuries.append(injury_info)
            elif team_id == away_id:
                away_injuries.append(injury_info)
        
        # Update home team summary
        self._store_team_summary(cursor, fixture_id, home_id, 'home', home_injuries)
        
        # Update away team summary
        self._store_team_summary(cursor, fixture_id, away_id, 'away', away_injuries)
    
    def _store_team_summary(self, cursor, fixture_id: int, team_id: int, 
                            team_type: str, injuries: List[Dict]):
        """Store aggregated team injury summary"""
        
        n_injured = sum(1 for i in injuries if 'Missing' in i.get('type', ''))
        n_suspended = sum(1 for i in injuries if 'Suspended' in i.get('type', ''))
        
        # Calculate total impact score
        total_impact = 0.0
        key_players = []
        
        for injury in injuries:
            position = injury.get('position', 'Unknown')
            base_rating = self.POSITION_BASE_RATINGS.get(position, 6.0)
            
            if 'Questionable' in injury.get('type', ''):
                impact = base_rating * 0.5
            else:
                impact = base_rating
            
            total_impact += impact
            
            # Key players are those with rating > 7
            if base_rating > 7:
                key_players.append(injury.get('name', 'Unknown'))
        
        try:
            cursor.execute("""
                INSERT INTO team_injury_summary (
                    match_id, team_id, team_type,
                    n_injured, n_suspended, total_impact_score,
                    key_players_out, ts_computed
                ) VALUES (
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, NOW()
                )
                ON CONFLICT (match_id, team_id)
                DO UPDATE SET
                    n_injured = EXCLUDED.n_injured,
                    n_suspended = EXCLUDED.n_suspended,
                    total_impact_score = EXCLUDED.total_impact_score,
                    key_players_out = EXCLUDED.key_players_out,
                    ts_computed = NOW()
            """, (
                fixture_id, team_id, team_type,
                n_injured, n_suspended, total_impact,
                key_players if key_players else None
            ))
            self.metrics['summaries_updated'] += 1
            
        except Exception as e:
            logger.debug(f"  Summary insert error: {e}")


def get_injury_collector():
    """Factory function to get InjuryCollector instance"""
    return InjuryCollector()


def run_injury_collection():
    """Entry point for scheduler"""
    try:
        collector = get_injury_collector()
        return collector.collect_upcoming_injuries(days_ahead=7)
    except Exception as e:
        logger.error(f"Injury collection failed: {e}")
        return {'error': str(e)}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = run_injury_collection()
    print(f"Result: {result}")
