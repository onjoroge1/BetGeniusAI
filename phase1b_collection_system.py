"""
Phase 1B: European League Data Collection System
Expand training dataset from 1,893 to 5,000+ matches
Target leagues: Premier League, La Liga, Serie A, Bundesliga, Ligue 1, + Tier 2
"""

import os
import json
import time
import requests
import psycopg2
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
import warnings
warnings.filterwarnings('ignore')

class Phase1BCollectionSystem:
    """Comprehensive European league data collection"""
    
    def __init__(self):
        self.api_key = os.environ.get('RAPIDAPI_KEY')
        self.conn = psycopg2.connect(os.environ['DATABASE_URL'])
        
        # Target leagues for expansion
        self.target_leagues = {
            # Tier 1 European Leagues
            39: {'name': 'Premier League', 'country': 'England', 'tier': 1, 'priority': 1},
            140: {'name': 'La Liga', 'country': 'Spain', 'tier': 1, 'priority': 1},
            135: {'name': 'Serie A', 'country': 'Italy', 'tier': 1, 'priority': 1},
            78: {'name': 'Bundesliga', 'country': 'Germany', 'tier': 1, 'priority': 1},
            61: {'name': 'Ligue 1', 'country': 'France', 'tier': 1, 'priority': 1},
            
            # Tier 2 European Leagues (for diversity)
            144: {'name': 'Jupiler Pro League', 'country': 'Belgium', 'tier': 2, 'priority': 2},
            88: {'name': 'Eredivisie', 'country': 'Netherlands', 'tier': 2, 'priority': 2},
            94: {'name': 'Primeira Liga', 'country': 'Portugal', 'tier': 2, 'priority': 2},
            103: {'name': 'Eliteserien', 'country': 'Norway', 'tier': 2, 'priority': 3},
            113: {'name': 'Allsvenskan', 'country': 'Sweden', 'tier': 2, 'priority': 3},
            
            # Additional leagues for variety
            71: {'name': 'Serie B', 'country': 'Italy', 'tier': 2, 'priority': 3},
            253: {'name': 'Major League Soccer', 'country': 'USA', 'tier': 2, 'priority': 3}
        }
        
        # Season targets
        self.target_seasons = [2021, 2022, 2023, 2024]
        
    def get_current_collection_status(self) -> Dict:
        """Check current matches in database"""
        
        print("CHECKING CURRENT COLLECTION STATUS")
        print("=" * 40)
        
        query = """
        SELECT 
            league_id,
            COUNT(*) as match_count,
            MIN(match_date) as earliest_match,
            MAX(match_date) as latest_match,
            COUNT(DISTINCT season) as seasons
        FROM training_matches 
        WHERE outcome IS NOT NULL
        GROUP BY league_id
        ORDER BY match_count DESC
        """
        
        cursor = self.conn.cursor()
        cursor.execute(query)
        results = cursor.fetchall()
        
        current_status = {}
        total_matches = 0
        
        for league_id, count, earliest, latest, seasons in results:
            league_name = self.target_leagues.get(league_id, {}).get('name', f'League {league_id}')
            current_status[league_id] = {
                'name': league_name,
                'matches': count,
                'earliest': earliest,
                'latest': latest,
                'seasons': seasons
            }
            total_matches += count
            
            print(f"{league_name}: {count} matches ({seasons} seasons)")
        
        print(f"\nTotal current matches: {total_matches}")
        print(f"Target: 5,000 matches")
        print(f"Need to collect: {max(0, 5000 - total_matches)} more matches")
        
        cursor.close()
        return current_status, total_matches
    
    def collect_league_fixtures(self, league_id: int, season: int) -> List[Dict]:
        """Collect fixtures for a specific league and season"""
        
        url = "https://api-football-v1.p.rapidapi.com/v3/fixtures"
        
        headers = {
            "X-RapidAPI-Key": self.api_key,
            "X-RapidAPI-Host": "api-football-v1.p.rapidapi.com"
        }
        
        params = {
            "league": league_id,
            "season": season,
            "status": "FT"  # Only finished matches
        }
        
        league_name = self.target_leagues.get(league_id, {}).get('name', f'League {league_id}')
        print(f"Collecting {league_name} {season} fixtures...")
        
        try:
            response = requests.get(url, headers=headers, params=params)
            response.raise_for_status()
            
            data = response.json()
            
            if data.get('response'):
                fixtures = data['response']
                print(f"Found {len(fixtures)} completed matches")
                return fixtures
            else:
                print("No fixtures found")
                return []
                
        except Exception as e:
            print(f"Error collecting {league_name} {season}: {e}")
            return []
    
    def process_fixture_data(self, fixture: Dict, league_id: int, season: int) -> Optional[Dict]:
        """Process individual fixture into our format"""
        
        try:
            fixture_data = fixture['fixture']
            teams = fixture['teams']
            goals = fixture['goals']
            league_info = fixture['league']
            
            # Basic match info
            match_id = fixture_data['id']
            match_date = datetime.fromisoformat(fixture_data['date'].replace('Z', '+00:00'))
            
            home_team = teams['home']['name']
            away_team = teams['away']['name']
            home_team_id = teams['home']['id']
            away_team_id = teams['away']['id']
            
            home_goals = goals['home']
            away_goals = goals['away']
            
            # Determine outcome
            if home_goals > away_goals:
                outcome = 'Home'
            elif away_goals > home_goals:
                outcome = 'Away'
            else:
                outcome = 'Draw'
            
            # Generate features for this match
            features = self._generate_match_features(
                league_id, season, home_team, away_team, 
                match_date, home_goals, away_goals
            )
            
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
                'features': features
            }
            
        except Exception as e:
            print(f"Error processing fixture: {e}")
            return None
    
    def _generate_match_features(self, league_id: int, season: int, home_team: str, 
                               away_team: str, match_date: datetime, 
                               home_goals: int, away_goals: int) -> Dict:
        """Generate feature set for match (legitimate pre-match features only)"""
        
        # League characteristics
        league_info = self.target_leagues.get(league_id, {})
        tier = league_info.get('tier', 2)
        country = league_info.get('country', 'Unknown')
        
        # Core features (no data leakage)
        features = {
            # League context
            'season_stage': self._calculate_season_stage(match_date),
            'recency_score': self._calculate_recency_score(match_date),
            'training_weight': self._calculate_training_weight(league_id, season),
            'competition_tier': tier,
            'foundation_value': 1.0,
            'match_importance': self._calculate_match_importance(league_id, match_date),
            'data_quality_score': 0.95 if tier == 1 else 0.85,
            'regional_intensity': self._calculate_regional_intensity(country),
            'tactical_relevance': 0.9 if tier == 1 else 0.7,
            
            # Market flags
            'african_market_flag': 0.0,  # European leagues
            'european_tier1_flag': 1.0 if tier == 1 else 0.0,
            'south_american_flag': 0.0,
            'developing_market_flag': 0.0,
            'premier_league_weight': 1.0 if league_id == 39 else 0.0,
            
            # League characteristics  
            'league_home_advantage': self._calculate_league_home_advantage(league_id),
            'league_competitiveness': self._calculate_league_competitiveness(league_id),
            'prediction_reliability': 0.85 if tier == 1 else 0.75,
            'tactical_style_encoding': self._encode_tactical_style(league_id),
            'competitiveness_indicator': self._calculate_competitiveness_indicator(league_id),
            'cross_league_applicability': 0.9 if tier == 1 else 0.7
        }
        
        return features
    
    def _calculate_season_stage(self, match_date: datetime) -> float:
        """Calculate what stage of season this is (0=early, 1=late)"""
        month = match_date.month
        if month >= 8 or month <= 2:  # Aug-Feb main season
            if month >= 8:
                return (month - 8) / 6  # Aug=0, Feb=0.83
            else:
                return (month + 4) / 6  # Jan=0.83, Feb=1.0
        else:
            return 0.1  # Off-season matches
    
    def _calculate_recency_score(self, match_date: datetime) -> float:
        """How recent is this match (higher = more recent)"""
        now = datetime.now()
        days_ago = (now - match_date.replace(tzinfo=None)).days
        return max(0.1, 1.0 - (days_ago / 1460))  # 4 years decay
    
    def _calculate_training_weight(self, league_id: int, season: int) -> float:
        """Training weight based on league quality and recency"""
        base_weight = 1.0 if self.target_leagues.get(league_id, {}).get('tier', 2) == 1 else 0.8
        season_weight = 1.0 if season >= 2023 else 0.9 if season >= 2022 else 0.8
        return base_weight * season_weight
    
    def _calculate_match_importance(self, league_id: int, match_date: datetime) -> float:
        """Match importance based on league and timing"""
        base_importance = 0.9 if self.target_leagues.get(league_id, {}).get('tier', 2) == 1 else 0.7
        
        # Higher importance later in season
        month = match_date.month
        if month in [4, 5]:  # End of season
            return base_importance * 1.2
        elif month in [12, 1, 2]:  # Mid season
            return base_importance * 1.1
        else:
            return base_importance
    
    def _calculate_regional_intensity(self, country: str) -> float:
        """Regional football intensity"""
        intensity_map = {
            'England': 0.95, 'Spain': 0.90, 'Germany': 0.90, 'Italy': 0.85, 'France': 0.80,
            'Netherlands': 0.75, 'Portugal': 0.70, 'Belgium': 0.65
        }
        return intensity_map.get(country, 0.6)
    
    def _calculate_league_home_advantage(self, league_id: int) -> float:
        """League-specific home advantage"""
        home_advantage_map = {
            39: 0.58,   # Premier League
            140: 0.60,  # La Liga  
            135: 0.56,  # Serie A
            78: 0.55,   # Bundesliga
            61: 0.59,   # Ligue 1
            88: 0.62,   # Eredivisie
            94: 0.61    # Primeira Liga
        }
        return home_advantage_map.get(league_id, 0.58)
    
    def _calculate_league_competitiveness(self, league_id: int) -> float:
        """League competitiveness score"""
        competitiveness_map = {
            39: 0.85,   # Premier League - very competitive
            140: 0.75,  # La Liga - Real/Barca dominant
            135: 0.70,  # Serie A - Juventus historically dominant  
            78: 0.80,   # Bundesliga - Bayern dominant but competitive
            61: 0.70,   # Ligue 1 - PSG dominant
            88: 0.75,   # Eredivisie
            94: 0.65    # Primeira Liga - Porto/Benfica dominant
        }
        return competitiveness_map.get(league_id, 0.70)
    
    def _encode_tactical_style(self, league_id: int) -> float:
        """Encode league tactical style"""
        style_map = {
            39: 0.8,    # Premier League - physical, fast
            140: 0.9,   # La Liga - technical
            135: 0.7,   # Serie A - tactical, defensive
            78: 0.85,   # Bundesliga - organized, attacking
            61: 0.75,   # Ligue 1 - varied
            88: 0.9,    # Eredivisie - attacking, technical
            94: 0.7     # Primeira Liga - technical
        }
        return style_map.get(league_id, 0.75)
    
    def _calculate_competitiveness_indicator(self, league_id: int) -> float:
        """Main competitiveness indicator (most important feature)"""
        # This was our most important feature, so calculate carefully
        base_comp = self._calculate_league_competitiveness(league_id)
        tier_bonus = 0.1 if self.target_leagues.get(league_id, {}).get('tier', 2) == 1 else 0.0
        return min(1.0, base_comp + tier_bonus)
    
    def insert_matches_batch(self, matches: List[Dict]) -> int:
        """Insert batch of matches into training_matches table"""
        
        if not matches:
            return 0
        
        cursor = self.conn.cursor()
        
        # Check for existing matches to avoid duplicates
        existing_ids = set()
        match_ids = [match['match_id'] for match in matches]
        
        if match_ids:
            cursor.execute(
                "SELECT match_id FROM training_matches WHERE match_id = ANY(%s)",
                (match_ids,)
            )
            existing_ids = set(row[0] for row in cursor.fetchall())
        
        # Filter out existing matches
        new_matches = [match for match in matches if match['match_id'] not in existing_ids]
        
        if not new_matches:
            print(f"All {len(matches)} matches already exist in database")
            cursor.close()
            return 0
        
        print(f"Inserting {len(new_matches)} new matches (skipping {len(existing_ids)} existing)")
        
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
            # Convert features dict to JSON string for each match
            for match in new_matches:
                match['features'] = json.dumps(match['features'])
            
            cursor.executemany(insert_query, new_matches)
            self.conn.commit()
            print(f"Successfully inserted {len(new_matches)} matches")
            cursor.close()
            return len(new_matches)
            
        except Exception as e:
            print(f"Error inserting matches: {e}")
            self.conn.rollback()
            cursor.close()
            return 0
    
    def run_comprehensive_collection(self) -> Dict:
        """Run comprehensive data collection across all target leagues"""
        
        print("PHASE 1B: COMPREHENSIVE EUROPEAN DATA COLLECTION")
        print("=" * 60)
        print("Target: Expand from 1,893 to 5,000+ matches")
        print("Leagues: Premier League, La Liga, Serie A, Bundesliga, Ligue 1 +")
        
        # Check current status
        current_status, current_total = self.get_current_collection_status()
        
        if current_total >= 5000:
            print(f"Already have {current_total} matches - target achieved!")
            return {'status': 'complete', 'total_matches': current_total}
        
        needed_matches = 5000 - current_total
        print(f"Need to collect {needed_matches} more matches")
        
        collection_results = {
            'start_total': current_total,
            'target': 5000,
            'leagues_collected': {},
            'total_new_matches': 0,
            'errors': []
        }
        
        # Prioritize collection by league tier and current gaps
        collection_plan = self._create_collection_plan(current_status, needed_matches)
        
        print(f"\nCollection Plan:")
        for league_id, plan in collection_plan.items():
            league_name = self.target_leagues[league_id]['name']
            print(f"  {league_name}: {plan['seasons']} seasons, target ~{plan['target_matches']} matches")
        
        total_collected = 0
        
        # Execute collection plan
        for league_id, plan in collection_plan.items():
            if total_collected >= needed_matches:
                break
                
            league_name = self.target_leagues[league_id]['name']
            league_matches = []
            
            print(f"\nCollecting {league_name}...")
            
            for season in plan['seasons']:
                if total_collected >= needed_matches:
                    break
                    
                print(f"Season {season}...")
                
                # Get fixtures
                fixtures = self.collect_league_fixtures(league_id, season)
                
                if not fixtures:
                    collection_results['errors'].append(f"{league_name} {season}: No fixtures found")
                    continue
                
                # Process fixtures  
                season_matches = []
                for fixture in fixtures:
                    processed = self.process_fixture_data(fixture, league_id, season)
                    if processed:
                        season_matches.append(processed)
                
                league_matches.extend(season_matches)
                
                # Insert in batches to avoid memory issues
                if len(league_matches) >= 200:
                    inserted = self.insert_matches_batch(league_matches)
                    total_collected += inserted
                    league_matches = []  # Clear batch
                
                # Rate limiting
                time.sleep(1)
                
                print(f"  Processed {len(season_matches)} matches")
            
            # Insert remaining matches for this league
            if league_matches:
                inserted = self.insert_matches_batch(league_matches)
                total_collected += inserted
            
            collection_results['leagues_collected'][league_id] = {
                'name': league_name,
                'seasons': plan['seasons'],
                'matches_collected': len(league_matches) + sum(1 for batch in range(len(league_matches) // 200))
            }
            
            print(f"Collected {total_collected} total new matches so far")
        
        collection_results['total_new_matches'] = total_collected
        collection_results['final_total'] = current_total + total_collected
        
        # Final status check
        final_status, final_total = self.get_current_collection_status()
        
        print(f"\n" + "="*60)
        print("PHASE 1B COLLECTION COMPLETE")
        print("="*60)
        print(f"Starting matches: {current_total}")
        print(f"New matches collected: {total_collected}")
        print(f"Final total: {final_total}")
        print(f"Target achievement: {final_total/5000*100:.1f}%")
        
        if final_total >= 5000:
            print("🎯 TARGET ACHIEVED: 5,000+ matches collected!")
        elif final_total >= 4000:
            print("📈 EXCELLENT PROGRESS: Close to target")
        else:
            print("✅ SOLID PROGRESS: Continue collection needed")
        
        return collection_results
    
    def _create_collection_plan(self, current_status: Dict, needed_matches: int) -> Dict:
        """Create intelligent collection plan based on current gaps"""
        
        plan = {}
        
        # Priority 1: Tier 1 leagues (most important)
        tier1_leagues = [39, 140, 135, 78, 61]  # Big 5 European leagues
        
        for league_id in tier1_leagues:
            current_matches = current_status.get(league_id, {}).get('matches', 0)
            
            # Target ~300-400 matches per tier 1 league
            target_for_league = min(400, max(200, needed_matches // len(tier1_leagues)))
            
            if current_matches < target_for_league:
                seasons_needed = min(4, max(1, (target_for_league - current_matches) // 80))
                plan[league_id] = {
                    'seasons': self.target_seasons[-seasons_needed:],
                    'target_matches': target_for_league - current_matches
                }
        
        # Priority 2: Tier 2 leagues (for diversity)
        remaining_needed = needed_matches - sum(p['target_matches'] for p in plan.values())
        
        if remaining_needed > 0:
            tier2_leagues = [144, 88, 94, 103, 113]
            
            for league_id in tier2_leagues[:3]:  # Top 3 tier 2 leagues
                if remaining_needed <= 0:
                    break
                    
                current_matches = current_status.get(league_id, {}).get('matches', 0)
                target_for_league = min(200, remaining_needed // 3)
                
                if current_matches < target_for_league:
                    seasons_needed = min(2, max(1, (target_for_league - current_matches) // 60))
                    plan[league_id] = {
                        'seasons': self.target_seasons[-seasons_needed:],
                        'target_matches': target_for_league - current_matches
                    }
                    remaining_needed -= target_for_league - current_matches
        
        return plan

def main():
    """Run Phase 1B collection system"""
    
    collector = Phase1BCollectionSystem()
    
    try:
        results = collector.run_comprehensive_collection()
        
        # Save results
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        os.makedirs('reports', exist_ok=True)
        
        results_path = f'reports/phase1b_collection_{timestamp}.json'
        with open(results_path, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        
        print(f"Collection results saved: {results_path}")
        
        return results
        
    finally:
        collector.conn.close()

if __name__ == "__main__":
    main()