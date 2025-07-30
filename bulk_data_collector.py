"""
Bulk Historical Data Collector - Fetch real match data for training
"""

import os
import requests
import psycopg2
import pandas as pd
from datetime import datetime, timedelta
import time
from typing import Dict, List, Optional
import json

class BulkDataCollector:
    """Collect historical match data from RapidAPI Football"""
    
    def __init__(self):
        self.api_key = os.environ.get('RAPIDAPI_KEY')
        if not self.api_key:
            raise ValueError("RAPIDAPI_KEY environment variable required")
        
        self.base_url = "https://api-football-v1.p.rapidapi.com/v3"
        self.headers = {
            "X-RapidAPI-Key": self.api_key,
            "X-RapidAPI-Host": "api-football-v1.p.rapidapi.com"
        }
        
        self.euro_leagues = {
            39: 'Premier League',
            140: 'La Liga',
            135: 'Serie A', 
            78: 'Bundesliga',
            61: 'Ligue 1'
        }
        
        # Rate limiting
        self.request_delay = 0.2  # 200ms between requests
        self.last_request_time = 0
    
    def _make_request(self, endpoint: str, params: Dict) -> Optional[Dict]:
        """Make rate-limited API request"""
        
        # Rate limiting
        elapsed = time.time() - self.last_request_time
        if elapsed < self.request_delay:
            time.sleep(self.request_delay - elapsed)
        
        try:
            url = f"{self.base_url}/{endpoint}"
            response = requests.get(url, headers=self.headers, params=params)
            self.last_request_time = time.time()
            
            if response.status_code == 200:
                data = response.json()
                return data
            else:
                print(f"API error {response.status_code}: {response.text}")
                return None
                
        except Exception as e:
            print(f"Request error: {e}")
            return None
    
    def get_league_seasons(self, league_id: int) -> List[int]:
        """Get available seasons for a league"""
        
        print(f"Getting seasons for league {league_id}...")
        
        data = self._make_request("leagues/seasons", {"league": league_id})
        
        if data and data.get('response'):
            seasons = data['response']
            # Filter for recent seasons (last 5 years)
            current_year = datetime.now().year
            recent_seasons = [s for s in seasons if isinstance(s, int) and s >= current_year - 5]
            
            print(f"Available seasons: {recent_seasons}")
            return sorted(recent_seasons)
        
        return []
    
    def collect_season_fixtures(self, league_id: int, season: int) -> List[Dict]:
        """Collect all fixtures for a league season"""
        
        print(f"Collecting {self.euro_leagues.get(league_id, league_id)} {season} season...")
        
        all_fixtures = []
        
        # Get fixtures in batches (API returns max 1000 per request)
        params = {
            "league": league_id,
            "season": season,
            "status": "FT"  # Only finished matches
        }
        
        data = self._make_request("fixtures", params)
        
        if data and data.get('response'):
            fixtures = data['response']
            
            for fixture in fixtures:
                # Extract match data
                match_data = self._extract_match_data(fixture)
                if match_data:
                    all_fixtures.append(match_data)
            
            print(f"Collected {len(all_fixtures)} matches")
        
        return all_fixtures
    
    def _extract_match_data(self, fixture: Dict) -> Optional[Dict]:
        """Extract relevant match data from API response"""
        
        try:
            fixture_data = fixture.get('fixture', {})
            league_data = fixture.get('league', {})
            teams_data = fixture.get('teams', {})
            goals_data = fixture.get('goals', {})
            score_data = fixture.get('score', {})
            
            # Skip if essential data missing
            if not all([fixture_data.get('id'), teams_data.get('home'), teams_data.get('away')]):
                return None
            
            # Skip if match not finished
            if fixture_data.get('status', {}).get('short') != 'FT':
                return None
            
            home_goals = goals_data.get('home')
            away_goals = goals_data.get('away')
            
            # Skip if goals data missing
            if home_goals is None or away_goals is None:
                return None
            
            # Determine outcome
            if home_goals > away_goals:
                outcome = 'H'
            elif home_goals < away_goals:
                outcome = 'A'
            else:
                outcome = 'D'
            
            return {
                'match_id': fixture_data['id'],
                'league_id': league_data.get('id'),
                'season': league_data.get('season'),
                'match_date_utc': fixture_data.get('date'),
                'home_team_id': teams_data['home'].get('id'),
                'away_team_id': teams_data['away'].get('id'),
                'home_team_name': teams_data['home'].get('name'),
                'away_team_name': teams_data['away'].get('name'),
                'home_goals': home_goals,
                'away_goals': away_goals,
                'outcome': outcome,
                'venue': fixture_data.get('venue', {}).get('name'),
                'round': league_data.get('round'),
                'referee': fixture_data.get('referee'),
                'status': fixture_data.get('status', {}).get('short')
            }
            
        except Exception as e:
            print(f"Error extracting match data: {e}")
            return None
    
    def save_matches_to_db(self, matches: List[Dict]) -> int:
        """Save matches to PostgreSQL database"""
        
        if not matches:
            return 0
        
        try:
            conn = psycopg2.connect(os.environ['DATABASE_URL'])
            cursor = conn.cursor()
            
            # Insert or update matches
            insert_query = """
            INSERT INTO matches (
                match_id, league_id, season, match_date_utc,
                home_team_id, away_team_id, home_team_name, away_team_name,
                home_goals, away_goals, outcome, venue, round, 
                referee, status, created_at, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            ) ON CONFLICT (match_id) DO UPDATE SET
                home_goals = EXCLUDED.home_goals,
                away_goals = EXCLUDED.away_goals,
                outcome = EXCLUDED.outcome,
                status = EXCLUDED.status,
                updated_at = EXCLUDED.updated_at
            """
            
            now = datetime.now()
            
            for match in matches:
                cursor.execute(insert_query, (
                    match['match_id'],
                    match['league_id'],
                    match['season'],
                    match['match_date_utc'],
                    match['home_team_id'],
                    match['away_team_id'],
                    match.get('home_team_name'),
                    match.get('away_team_name'),
                    match['home_goals'],
                    match['away_goals'],
                    match['outcome'],
                    match.get('venue'),
                    match.get('round'),
                    match.get('referee'),
                    match.get('status'),
                    now,
                    now
                ))
            
            conn.commit()
            inserted = len(matches)
            
            cursor.close()
            conn.close()
            
            print(f"Saved {inserted} matches to database")
            return inserted
            
        except Exception as e:
            print(f"Database error: {e}")
            return 0
    
    def collect_league_data(self, league_id: int, max_seasons: int = 3) -> int:
        """Collect historical data for a specific league"""
        
        print(f"\n=== Collecting {self.euro_leagues.get(league_id, f'League {league_id}')} ===")
        
        # Get available seasons
        seasons = self.get_league_seasons(league_id)
        
        if not seasons:
            print("No seasons available")
            return 0
        
        # Limit to most recent seasons
        recent_seasons = seasons[-max_seasons:] if len(seasons) > max_seasons else seasons
        
        total_matches = 0
        
        for season in recent_seasons:
            fixtures = self.collect_season_fixtures(league_id, season)
            
            if fixtures:
                saved = self.save_matches_to_db(fixtures)
                total_matches += saved
                
                print(f"Season {season}: {saved} matches saved")
            
            # Brief pause between seasons
            time.sleep(1)
        
        print(f"Total for league {league_id}: {total_matches} matches")
        return total_matches
    
    def collect_all_euro_leagues(self, max_seasons_per_league: int = 3) -> Dict[int, int]:
        """Collect data for all European leagues"""
        
        print("BULK DATA COLLECTION - European Leagues")
        print("=" * 50)
        
        results = {}
        total_matches = 0
        
        for league_id in self.euro_leagues.keys():
            try:
                matches_collected = self.collect_league_data(league_id, max_seasons_per_league)
                results[league_id] = matches_collected
                total_matches += matches_collected
                
                # Pause between leagues to be respectful to API
                time.sleep(2)
                
            except Exception as e:
                print(f"Error collecting league {league_id}: {e}")
                results[league_id] = 0
        
        print(f"\n=== COLLECTION SUMMARY ===")
        for league_id, count in results.items():
            print(f"{self.euro_leagues[league_id]}: {count} matches")
        
        print(f"Total matches collected: {total_matches}")
        
        return results
    
    def get_current_database_stats(self) -> Dict:
        """Get current database statistics"""
        
        try:
            conn = psycopg2.connect(os.environ['DATABASE_URL'])
            
            # Overall stats
            query1 = """
            SELECT 
                COUNT(*) as total_matches,
                COUNT(DISTINCT league_id) as leagues,
                COUNT(DISTINCT season) as seasons,
                MIN(match_date_utc) as earliest,
                MAX(match_date_utc) as latest
            FROM matches 
            WHERE outcome IS NOT NULL
            """
            
            df1 = pd.read_sql_query(query1, conn)
            
            # Per-league stats
            query2 = """
            SELECT 
                league_id,
                COUNT(*) as matches,
                COUNT(DISTINCT season) as seasons,
                MIN(match_date_utc) as earliest,
                MAX(match_date_utc) as latest
            FROM matches 
            WHERE outcome IS NOT NULL
            GROUP BY league_id
            ORDER BY matches DESC
            """
            
            df2 = pd.read_sql_query(query2, conn)
            
            conn.close()
            
            return {
                'overall': df1.to_dict('records')[0],
                'per_league': df2.to_dict('records')
            }
            
        except Exception as e:
            print(f"Database stats error: {e}")
            return {}

def main():
    """Run bulk data collection"""
    
    collector = BulkDataCollector()
    
    # Show current database state
    print("CURRENT DATABASE STATE:")
    print("-" * 30)
    
    stats = collector.get_current_database_stats()
    if stats:
        overall = stats['overall']
        print(f"Total matches: {overall['total_matches']}")
        print(f"Leagues: {overall['leagues']}")
        print(f"Seasons: {overall['seasons']}")
        print(f"Date range: {overall['earliest']} to {overall['latest']}")
        
        print(f"\nPer-league breakdown:")
        for league in stats['per_league']:
            league_name = collector.euro_leagues.get(league['league_id'], f"League {league['league_id']}")
            print(f"  {league_name}: {league['matches']} matches ({league['seasons']} seasons)")
    
    # Collect historical data
    print(f"\nStarting bulk collection...")
    
    # Collect 3 seasons per league (should give us ~1,140 matches per league)
    results = collector.collect_all_euro_leagues(max_seasons_per_league=3)
    
    # Show final stats
    print(f"\nFINAL DATABASE STATE:")
    print("-" * 30)
    
    final_stats = collector.get_current_database_stats()
    if final_stats:
        overall = final_stats['overall']
        print(f"Total matches: {overall['total_matches']}")
        print(f"Leagues: {overall['leagues']}")
        print(f"Seasons: {overall['seasons']}")
        
        if overall['total_matches'] >= 1000:
            print(f"✅ Sufficient data for ML training ({overall['total_matches']} matches)")
        else:
            print(f"⚠️  May need more data for robust training ({overall['total_matches']} matches)")

if __name__ == "__main__":
    main()