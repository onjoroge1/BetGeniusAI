"""
Real Historical Data Collector - Using working API endpoints
"""

import os
import requests
import psycopg2
import json
import time
from datetime import datetime
from typing import Dict, List, Optional

class RealDataCollector:
    """Collect real historical match data from RapidAPI Football"""
    
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
        self.request_delay = 0.3  # 300ms between requests to be safe
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
    
    def collect_league_season(self, league_id: int, season: int) -> List[Dict]:
        """Collect all finished matches for a league season"""
        
        league_name = self.euro_leagues.get(league_id, f'League {league_id}')
        print(f"Collecting {league_name} {season} season...")
        
        params = {
            "league": league_id,
            "season": season
        }
        
        data = self._make_request("fixtures", params)
        
        if not data or not data.get('response'):
            print(f"No data returned for {league_name} {season}")
            return []
        
        fixtures = data['response']
        
        # Filter for finished matches only
        finished_matches = []
        for fixture in fixtures:
            match_data = self._extract_match_data(fixture)
            if match_data:
                finished_matches.append(match_data)
        
        print(f"Extracted {len(finished_matches)} finished matches")
        return finished_matches
    
    def _extract_match_data(self, fixture: Dict) -> Optional[Dict]:
        """Extract match data from API response"""
        
        try:
            fixture_data = fixture.get('fixture', {})
            league_data = fixture.get('league', {})
            teams_data = fixture.get('teams', {})
            goals_data = fixture.get('goals', {})
            
            # Only include finished matches
            status = fixture_data.get('status', {}).get('short')
            if status != 'FT':
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
                'match_id': fixture_data.get('id'),
                'league_id': league_data.get('id'),
                'season': league_data.get('season'),
                'match_date_utc': fixture_data.get('date'),
                'home_team_id': teams_data.get('home', {}).get('id'),
                'away_team_id': teams_data.get('away', {}).get('id'),
                'home_team_name': teams_data.get('home', {}).get('name'),
                'away_team_name': teams_data.get('away', {}).get('name'),
                'home_goals': home_goals,
                'away_goals': away_goals,
                'outcome': outcome,
                'venue': fixture_data.get('venue', {}).get('name'),
                'round': league_data.get('round'),
                'status': status
            }
            
        except Exception as e:
            print(f"Error extracting match data: {e}")
            return None
    
    def save_matches_to_db(self, matches: List[Dict]) -> int:
        """Save matches to database"""
        
        if not matches:
            return 0
        
        try:
            conn = psycopg2.connect(os.environ['DATABASE_URL'])
            cursor = conn.cursor()
            
            # Create table if not exists (ensure we have all needed columns)
            create_table_query = """
            CREATE TABLE IF NOT EXISTS matches (
                match_id BIGINT PRIMARY KEY,
                league_id INTEGER,
                season INTEGER,
                match_date_utc TIMESTAMP,
                home_team_id INTEGER,
                away_team_id INTEGER,
                home_team_name TEXT,
                away_team_name TEXT,
                home_goals INTEGER,
                away_goals INTEGER,
                outcome CHAR(1),
                venue TEXT,
                round TEXT,
                status TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
            cursor.execute(create_table_query)
            
            # Insert matches
            insert_query = """
            INSERT INTO matches (
                match_id, league_id, season, match_date_utc,
                home_team_id, away_team_id, home_team_name, away_team_name,
                home_goals, away_goals, outcome, venue, round, status,
                created_at, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            ) ON CONFLICT (match_id) DO UPDATE SET
                home_goals = EXCLUDED.home_goals,
                away_goals = EXCLUDED.away_goals,
                outcome = EXCLUDED.outcome,
                updated_at = EXCLUDED.updated_at
            """
            
            now = datetime.now()
            inserted = 0
            
            for match in matches:
                try:
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
                        match.get('status'),
                        now,
                        now
                    ))
                    inserted += 1
                except Exception as e:
                    print(f"Error inserting match {match.get('match_id')}: {e}")
                    continue
            
            conn.commit()
            cursor.close()
            conn.close()
            
            print(f"Successfully saved {inserted} matches to database")
            return inserted
            
        except Exception as e:
            print(f"Database error: {e}")
            return 0
    
    def collect_historical_data(self, seasons: List[int] = [2023, 2022, 2021]) -> Dict[int, int]:
        """Collect historical data for all European leagues"""
        
        print("REAL DATA COLLECTION - European Leagues Historical Data")
        print("=" * 60)
        
        results = {}
        total_matches = 0
        
        for league_id in self.euro_leagues.keys():
            league_total = 0
            
            print(f"\n=== {self.euro_leagues[league_id]} ===")
            
            for season in seasons:
                try:
                    matches = self.collect_league_season(league_id, season)
                    
                    if matches:
                        saved = self.save_matches_to_db(matches)
                        league_total += saved
                        print(f"{season} season: {saved} matches saved")
                    else:
                        print(f"{season} season: No matches collected")
                    
                    # Brief pause between seasons
                    time.sleep(1)
                    
                except Exception as e:
                    print(f"Error collecting {self.euro_leagues[league_id]} {season}: {e}")
                    continue
            
            results[league_id] = league_total
            total_matches += league_total
            
            print(f"{self.euro_leagues[league_id]} total: {league_total} matches")
            
            # Pause between leagues
            time.sleep(2)
        
        print(f"\n" + "=" * 60)
        print("COLLECTION SUMMARY")
        print("=" * 60)
        
        for league_id, count in results.items():
            print(f"{self.euro_leagues[league_id]:15}: {count:4d} matches")
        
        print(f"{'TOTAL':15}: {total_matches:4d} matches")
        
        if total_matches >= 3000:
            print(f"\n✅ Excellent dataset for ML training ({total_matches} matches)")
        elif total_matches >= 1000:
            print(f"\n✅ Good dataset for ML training ({total_matches} matches)")
        else:
            print(f"\n⚠️  Small dataset, may need more data ({total_matches} matches)")
        
        return results

def main():
    """Run real data collection"""
    
    collector = RealDataCollector()
    
    # Show what we'll collect
    print("Planning to collect:")
    for league_id, name in collector.euro_leagues.items():
        print(f"  {name} (ID: {league_id}) - seasons 2021, 2022, 2023")
    print(f"Expected: ~1,140 matches per league, ~5,700 total")
    
    input_text = input("\nProceed with collection? (y/n): ")
    if input_text.lower() != 'y':
        print("Collection cancelled")
        return
    
    # Collect data
    results = collector.collect_historical_data([2023, 2022, 2021])
    
    # Verify final database state
    try:
        conn = psycopg2.connect(os.environ['DATABASE_URL'])
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                COUNT(*) as total_matches,
                COUNT(DISTINCT league_id) as leagues,
                COUNT(DISTINCT season) as seasons,
                MIN(match_date_utc) as earliest,
                MAX(match_date_utc) as latest
            FROM matches 
            WHERE outcome IS NOT NULL
        """)
        
        stats = cursor.fetchone()
        
        print(f"\nFINAL DATABASE STATE:")
        print(f"Total matches: {stats[0]}")
        print(f"Leagues: {stats[1]}")
        print(f"Seasons: {stats[2]}")
        print(f"Date range: {stats[3]} to {stats[4]}")
        
        # Per-league breakdown
        cursor.execute("""
            SELECT 
                league_id,
                COUNT(*) as matches,
                COUNT(DISTINCT season) as seasons
            FROM matches 
            WHERE outcome IS NOT NULL
            GROUP BY league_id
            ORDER BY matches DESC
        """)
        
        print(f"\nPer-league breakdown:")
        for row in cursor.fetchall():
            league_name = collector.euro_leagues.get(row[0], f"League {row[0]}")
            print(f"  {league_name}: {row[1]} matches ({row[2]} seasons)")
        
        cursor.close()
        conn.close()
        
    except Exception as e:
        print(f"Error getting final stats: {e}")

if __name__ == "__main__":
    main()