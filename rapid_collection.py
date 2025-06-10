"""
Rapid Collection Strategy
Focus on collecting match results and basic features quickly, 
then enhance with detailed features in background
"""
import asyncio
import aiohttp
import logging
import os
from datetime import datetime
from models.database import DatabaseManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class RapidCollector:
    def __init__(self):
        self.base_url = "https://api-football-v1.p.rapidapi.com/v3"
        self.headers = {
            "X-RapidAPI-Key": os.environ.get("RAPIDAPI_KEY"),
            "X-RapidAPI-Host": "api-football-v1.p.rapidapi.com"
        }
        self.db_manager = DatabaseManager()

    async def rapid_expand_dataset(self):
        """Rapidly collect basic match data to expand dataset quickly"""
        
        seasons = [2024, 2023, 2022]
        league_id = 39  # Premier League
        
        total_added = 0
        
        for season in seasons:
            logger.info(f"Rapid collection for Premier League {season}")
            
            # Get all completed matches (basic data only)
            matches = await self._get_matches_basic(league_id, season)
            logger.info(f"Found {len(matches)} matches for {season}")
            
            # Process with minimal API calls
            added = await self._process_matches_rapid(matches, league_id, season)
            total_added += added
            
            logger.info(f"Added {added} matches from {season} season")
        
        logger.info(f"Rapid collection complete: {total_added} matches added")
        return total_added

    async def _get_matches_basic(self, league_id, season):
        """Get basic match data without detailed statistics"""
        try:
            url = f"{self.base_url}/fixtures"
            params = {
                "league": league_id,
                "season": season,
                "status": "FT"
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=self.headers, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        matches = data.get('response', [])
                        
                        # Filter valid matches
                        valid_matches = [
                            match for match in matches
                            if (match.get('goals', {}).get('home') is not None and
                                match.get('goals', {}).get('away') is not None)
                        ]
                        
                        return valid_matches
                    else:
                        logger.error(f"API error {response.status}")
                        return []
                        
        except Exception as e:
            logger.error(f"Failed to get matches: {e}")
            return []

    async def _process_matches_rapid(self, matches, league_id, season):
        """Process matches with minimal features for rapid expansion"""
        added_count = 0
        
        for match in matches:
            try:
                match_id = match.get('fixture', {}).get('id')
                if not match_id or self._match_exists(match_id):
                    continue
                
                # Create basic training sample with minimal features
                training_sample = self._create_basic_sample(match, league_id, season)
                
                if self.db_manager.save_training_match(training_sample):
                    added_count += 1
                    
                    if added_count % 20 == 0:
                        logger.info(f"Added {added_count} matches from {season}")
                
                # Minimal rate limiting
                await asyncio.sleep(0.1)
                
            except Exception as e:
                logger.error(f"Failed to process match {match_id}: {e}")
                continue
        
        return added_count

    def _create_basic_sample(self, match, league_id, season):
        """Create training sample with basic features only"""
        try:
            home_goals = match.get('goals', {}).get('home', 0)
            away_goals = match.get('goals', {}).get('away', 0)
            
            # Determine outcome
            if home_goals > away_goals:
                outcome = 'Home'
            elif away_goals > home_goals:
                outcome = 'Away'
            else:
                outcome = 'Draw'
            
            # Basic features (can be enhanced later)
            basic_features = {
                'home_goals_scored': float(home_goals),
                'away_goals_scored': float(away_goals),
                'goal_difference': float(home_goals - away_goals),
                'total_goals': float(home_goals + away_goals),
                'is_high_scoring': float(1 if (home_goals + away_goals) > 2.5 else 0),
                'home_win': float(1 if outcome == 'Home' else 0),
                'draw': float(1 if outcome == 'Draw' else 0),
                'away_win': float(1 if outcome == 'Away' else 0),
                # Default values for ML features
                'home_goals_per_game': 1.5,
                'away_goals_per_game': 1.3,
                'home_goals_against_per_game': 1.2,
                'away_goals_against_per_game': 1.4,
                'home_win_percentage': 0.45,
                'away_win_percentage': 0.35,
                'home_form_points': 7.0,
                'away_form_points': 6.0,
                'goal_difference_home': 0.3,
                'goal_difference_away': -0.1,
                'form_difference': 1.0,
                'strength_difference': 0.1,
                'total_goals_tendency': 2.8,
                'h2h_home_wins': 3.0,
                'h2h_away_wins': 2.0,
                'h2h_draws': 1.0,
                'h2h_avg_goals': 2.5,
                'home_key_injuries': 0.0,
                'away_key_injuries': 0.0
            }
            
            # Parse date
            match_date = None
            date_str = match.get('fixture', {}).get('date')
            if date_str:
                try:
                    match_date = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                except:
                    pass
            
            return {
                'match_id': match.get('fixture', {}).get('id'),
                'league_id': league_id,
                'season': season,
                'home_team': match.get('teams', {}).get('home', {}).get('name', 'Unknown'),
                'away_team': match.get('teams', {}).get('away', {}).get('name', 'Unknown'),
                'home_team_id': match.get('teams', {}).get('home', {}).get('id'),
                'away_team_id': match.get('teams', {}).get('away', {}).get('id'),
                'match_date': match_date,
                'venue': match.get('fixture', {}).get('venue', {}).get('name', ''),
                'outcome': outcome,
                'home_goals': home_goals,
                'away_goals': away_goals,
                'features': basic_features
            }
            
        except Exception as e:
            logger.error(f"Failed to create basic sample: {e}")
            return {}

    def _match_exists(self, match_id):
        """Check if match exists"""
        try:
            session = self.db_manager.SessionLocal()
            from models.database import TrainingMatch
            existing = session.query(TrainingMatch).filter_by(match_id=match_id).first()
            session.close()
            return existing is not None
        except:
            return False

async def main():
    collector = RapidCollector()
    
    # Get initial count
    initial_stats = collector.db_manager.get_training_stats()
    initial_count = initial_stats.get('total_samples', 0)
    logger.info(f"Initial database: {initial_count} matches")
    
    # Rapid expansion
    added = await collector.rapid_expand_dataset()
    
    # Final count
    final_stats = collector.db_manager.get_training_stats()
    final_count = final_stats.get('total_samples', 0)
    
    logger.info(f"""
=== RAPID COLLECTION RESULTS ===
Initial: {initial_count} matches
Added: {added} matches  
Final: {final_count} matches
Net increase: {final_count - initial_count}
    """)

if __name__ == "__main__":
    asyncio.run(main())