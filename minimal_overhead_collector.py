"""
Minimal Overhead Collector - Quick expansion to 5000 matches
Focused on the most essential European leagues with minimal API calls
"""

import os
import json
import time
import requests
import psycopg2
from datetime import datetime, timedelta
from typing import Dict, List, Optional

class MinimalOverheadCollector:
    """Fast collection system with minimal overhead"""
    
    def __init__(self):
        self.api_key = os.environ.get('RAPIDAPI_KEY')
        self.conn = psycopg2.connect(os.environ['DATABASE_URL'])
        
        # Focus on Big 5 + top tier 2 leagues only
        self.target_leagues = {
            39: {'name': 'Premier League', 'tier': 1},
            140: {'name': 'La Liga', 'tier': 1}, 
            135: {'name': 'Serie A', 'tier': 1},
            78: {'name': 'Bundesliga', 'tier': 1},
            61: {'name': 'Ligue 1', 'tier': 1},
            88: {'name': 'Eredivisie', 'tier': 2},
            94: {'name': 'Primeira Liga', 'tier': 2}
        }
        
    def get_collection_gaps(self) -> Dict:
        """Quick check of what we need"""
        
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM training_matches WHERE outcome IS NOT NULL")
        total = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT league_id, COUNT(*) 
            FROM training_matches 
            WHERE outcome IS NOT NULL
            GROUP BY league_id
        """)
        
        by_league = dict(cursor.fetchall())
        cursor.close()
        
        print(f"Current total: {total} matches")
        print(f"Target: 5,000 matches")
        print(f"Need: {max(0, 5000 - total)} more matches")
        
        return {
            'total': total,
            'needed': max(0, 5000 - total),
            'by_league': by_league
        }
    
    def collect_season_batch(self, league_id: int, season: int) -> int:
        """Collect and insert one season efficiently"""
        
        league_name = self.target_leagues[league_id]['name']
        print(f"Collecting {league_name} {season}...")
        
        # Get fixtures
        url = "https://api-football-v1.p.rapidapi.com/v3/fixtures"
        headers = {
            "X-RapidAPI-Key": self.api_key,
            "X-RapidAPI-Host": "api-football-v1.p.rapidapi.com"
        }
        params = {
            "league": league_id,
            "season": season,
            "status": "FT"
        }
        
        try:
            response = requests.get(url, headers=headers, params=params)
            response.raise_for_status()
            data = response.json()
            
            if not data.get('response'):
                print(f"No data for {league_name} {season}")
                return 0
                
            fixtures = data['response']
            print(f"Found {len(fixtures)} matches")
            
            # Process and insert in one batch
            matches_to_insert = []
            
            for fixture in fixtures:
                processed = self._process_fixture_fast(fixture, league_id, season)
                if processed:
                    matches_to_insert.append(processed)
            
            # Check for existing and insert new ones
            inserted = self._insert_batch_fast(matches_to_insert)
            print(f"Inserted {inserted} new matches")
            
            return inserted
            
        except Exception as e:
            print(f"Error collecting {league_name} {season}: {e}")
            return 0
    
    def _process_fixture_fast(self, fixture: Dict, league_id: int, season: int) -> Optional[Dict]:
        """Fast fixture processing"""
        
        try:
            fixture_data = fixture['fixture']
            teams = fixture['teams']
            goals = fixture['goals']
            
            # Extract basic info
            match_id = fixture_data['id']
            match_date = datetime.fromisoformat(fixture_data['date'].replace('Z', '+00:00'))
            
            home_team = teams['home']['name']
            away_team = teams['away']['name']
            home_team_id = teams['home']['id']
            away_team_id = teams['away']['id']
            
            home_goals = goals['home'] or 0
            away_goals = goals['away'] or 0
            
            # Outcome
            if home_goals > away_goals:
                outcome = 'Home'
            elif away_goals > home_goals:
                outcome = 'Away'
            else:
                outcome = 'Draw'
            
            # Simple feature set (no complex calculations)
            features = self._generate_simple_features(league_id, season, match_date)
            
            return {
                'match_id': match_id,
                'league_id': league_id,
                'season': season,
                'home_team': home_team,
                'away_team': away_team,
                'home_team_id': home_team_id,
                'away_team_id': away_team_id,
                'match_date': match_date,
                'home_goals': home_goals,
                'away_goals': away_goals,
                'outcome': outcome,
                'features': json.dumps(features)
            }
            
        except Exception as e:
            print(f"Error processing fixture: {e}")
            return None
    
    def _generate_simple_features(self, league_id: int, season: int, match_date: datetime) -> Dict:
        """Generate minimal but effective feature set"""
        
        tier = self.target_leagues[league_id]['tier']
        
        # Essential features only
        features = {
            'season_stage': 0.5,  # Default mid-season
            'recency_score': 1.0 if season >= 2023 else 0.8,
            'training_weight': 1.0 if tier == 1 else 0.8,
            'competition_tier': tier,
            'foundation_value': 1.0,
            'match_importance': 0.9 if tier == 1 else 0.7,
            'data_quality_score': 0.95 if tier == 1 else 0.85,
            'regional_intensity': 0.9 if tier == 1 else 0.7,
            'tactical_relevance': 0.9 if tier == 1 else 0.7,
            'african_market_flag': 0.0,
            'european_tier1_flag': 1.0 if tier == 1 else 0.0,
            'south_american_flag': 0.0,
            'league_home_advantage': 0.58,
            'premier_league_weight': 1.0 if league_id == 39 else 0.0,
            'developing_market_flag': 0.0,
            'league_competitiveness': {
                39: 0.85, 140: 0.75, 135: 0.70, 78: 0.80, 61: 0.70,
                88: 0.75, 94: 0.65
            }.get(league_id, 0.70),
            'prediction_reliability': 0.85 if tier == 1 else 0.75,
            'tactical_style_encoding': 0.8,
            'competitiveness_indicator': {
                39: 0.95, 140: 0.85, 135: 0.80, 78: 0.90, 61: 0.80,
                88: 0.85, 94: 0.75
            }.get(league_id, 0.80),
            'cross_league_applicability': 0.9 if tier == 1 else 0.7
        }
        
        return features
    
    def _insert_batch_fast(self, matches: List[Dict]) -> int:
        """Fast batch insert with duplicate checking"""
        
        if not matches:
            return 0
        
        cursor = self.conn.cursor()
        
        # Check existing matches
        match_ids = [m['match_id'] for m in matches]
        cursor.execute(
            "SELECT match_id FROM training_matches WHERE match_id = ANY(%s)",
            (match_ids,)
        )
        existing_ids = set(row[0] for row in cursor.fetchall())
        
        # Filter new matches
        new_matches = [m for m in matches if m['match_id'] not in existing_ids]
        
        if not new_matches:
            cursor.close()
            return 0
        
        # Insert new matches
        insert_query = """
        INSERT INTO training_matches (
            match_id, league_id, season, home_team, away_team,
            home_team_id, away_team_id, match_date, home_goals,
            away_goals, outcome, features
        ) VALUES (
            %(match_id)s, %(league_id)s, %(season)s, %(home_team)s, %(away_team)s,
            %(home_team_id)s, %(away_team_id)s, %(match_date)s, %(home_goals)s,
            %(away_goals)s, %(outcome)s, %(features)s::jsonb
        )
        """
        
        try:
            cursor.executemany(insert_query, new_matches)
            self.conn.commit()
            cursor.close()
            return len(new_matches)
            
        except Exception as e:
            print(f"Insert error: {e}")
            self.conn.rollback()
            cursor.close()
            return 0
    
    def run_fast_collection(self) -> Dict:
        """Run fast collection to reach 5000 matches"""
        
        print("FAST COLLECTION TO 5000 MATCHES")
        print("=" * 40)
        
        # Check current status
        status = self.get_collection_gaps()
        
        if status['needed'] <= 0:
            print("Target already achieved!")
            return status
        
        # Collection plan: most recent seasons first
        collection_plan = []
        
        # Tier 1 leagues: 2022-2024 seasons
        for league_id in [140, 135, 78, 61]:  # Skip 39 (already has 960)
            for season in [2024, 2023, 2022]:
                collection_plan.append((league_id, season))
        
        # Tier 2 leagues: 2023-2024 seasons  
        for league_id in [88, 94]:
            for season in [2024, 2023]:
                collection_plan.append((league_id, season))
        
        print(f"Collection plan: {len(collection_plan)} league-seasons")
        
        total_collected = 0
        
        for league_id, season in collection_plan:
            if status['total'] + total_collected >= 5000:
                break
                
            collected = self.collect_season_batch(league_id, season)
            total_collected += collected
            
            print(f"Progress: {status['total'] + total_collected}/5000 matches")
            
            # Rate limiting
            time.sleep(2)
            
            if total_collected >= status['needed']:
                break
        
        # Final check
        final_status = self.get_collection_gaps()
        
        print(f"\nCOLLECTION COMPLETE")
        print(f"Collected: {total_collected} new matches")
        print(f"Final total: {final_status['total']} matches")
        
        if final_status['total'] >= 5000:
            print("🎯 TARGET ACHIEVED: 5,000+ matches!")
        
        return {
            'start_total': status['total'],
            'collected': total_collected,
            'final_total': final_status['total'],
            'target_achieved': final_status['total'] >= 5000
        }

def main():
    """Run minimal overhead collection"""
    
    collector = MinimalOverheadCollector()
    
    try:
        results = collector.run_fast_collection()
        
        # Save results
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        os.makedirs('reports', exist_ok=True)
        
        with open(f'reports/fast_collection_{timestamp}.json', 'w') as f:
            json.dump(results, f, indent=2, default=str)
        
        return results
        
    finally:
        collector.conn.close()

if __name__ == "__main__":
    main()