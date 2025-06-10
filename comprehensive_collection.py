"""
Comprehensive Database Collection
Collect ALL available matches from Premier League 2022, 2023, 2024 seasons
"""
import asyncio
import aiohttp
import logging
import os
from datetime import datetime
from models.database import DatabaseManager
from models.data_collector import SportsDataCollector

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ComprehensiveCollector:
    def __init__(self):
        self.base_url = "https://api-football-v1.p.rapidapi.com/v3"
        self.headers = {
            "X-RapidAPI-Key": os.environ.get("RAPIDAPI_KEY"),
            "X-RapidAPI-Host": "api-football-v1.p.rapidapi.com"
        }
        self.db_manager = DatabaseManager()
        self.data_collector = SportsDataCollector()

    async def collect_all_premier_league_seasons(self):
        """Collect ALL matches from Premier League 2022, 2023, 2024"""
        
        seasons = [2024, 2023, 2022]
        league_id = 39  # Premier League
        
        total_collected = 0
        results = {}
        
        for season in seasons:
            logger.info(f"Starting collection for Premier League {season}")
            
            # Get all completed matches for this season
            all_matches = await self._get_all_completed_matches(league_id, season)
            logger.info(f"Found {len(all_matches)} completed matches for {season} season")
            
            if not all_matches:
                logger.warning(f"No matches found for {season} season")
                continue
            
            # Process all matches for this season
            season_collected = await self._process_season_matches(all_matches, league_id, season)
            total_collected += season_collected
            
            results[season] = {
                "available_matches": len(all_matches),
                "collected": season_collected
            }
            
            logger.info(f"Completed {season}: {season_collected}/{len(all_matches)} matches collected")
        
        logger.info(f"Total collection complete: {total_collected} new matches added")
        return results

    async def _get_all_completed_matches(self, league_id, season):
        """Get ALL completed matches for a season (not limited to 55)"""
        try:
            url = f"{self.base_url}/fixtures"
            params = {
                "league": league_id,
                "season": season,
                "status": "FT"  # Full Time completed matches
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=self.headers, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        matches = data.get('response', [])
                        
                        # Filter for valid completed matches
                        valid_matches = [
                            match for match in matches
                            if (match.get('goals', {}).get('home') is not None and
                                match.get('goals', {}).get('away') is not None)
                        ]
                        
                        return valid_matches
                    else:
                        logger.error(f"API error {response.status} for season {season}")
                        return []
                        
        except Exception as e:
            logger.error(f"Failed to get matches for season {season}: {e}")
            return []

    async def _process_season_matches(self, matches, league_id, season):
        """Process all matches from a season"""
        collected_count = 0
        
        for i, match in enumerate(matches):
            try:
                match_id = match.get('fixture', {}).get('id')
                if not match_id:
                    continue
                
                # Skip if already exists
                if self._match_exists(match_id):
                    continue
                
                # Get comprehensive match data
                match_data = await self.data_collector.get_match_data(match_id)
                if not match_data:
                    continue
                
                # Prepare training sample
                training_sample = self._prepare_training_sample(match, match_data, league_id, season)
                
                # Save to database
                if self.db_manager.save_training_match(training_sample):
                    collected_count += 1
                    
                    # Progress logging
                    if collected_count % 10 == 0:
                        logger.info(f"Season {season}: {collected_count} matches saved, processing {i+1}/{len(matches)}")
                
                # Rate limiting
                await asyncio.sleep(0.3)
                
            except Exception as e:
                logger.error(f"Failed to process match {match_id}: {e}")
                continue
        
        return collected_count

    def _match_exists(self, match_id):
        """Check if match already exists"""
        try:
            session = self.db_manager.SessionLocal()
            from models.database import TrainingMatch
            existing = session.query(TrainingMatch).filter_by(match_id=match_id).first()
            session.close()
            return existing is not None
        except:
            return False

    def _prepare_training_sample(self, match, match_data, league_id, season):
        """Prepare training sample with proper structure"""
        try:
            home_goals = match.get('goals', {}).get('home', 0)
            away_goals = match.get('goals', {}).get('away', 0)
            
            if home_goals > away_goals:
                outcome = 'Home'
            elif away_goals > home_goals:
                outcome = 'Away'
            else:
                outcome = 'Draw'
            
            # Parse match date
            match_date_str = match.get('fixture', {}).get('date')
            match_date = None
            if match_date_str:
                try:
                    match_date = datetime.fromisoformat(match_date_str.replace('Z', '+00:00'))
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
                'features': match_data.get('features', {}),
            }
        except Exception as e:
            logger.error(f"Failed to prepare training sample: {e}")
            return {}

async def main():
    collector = ComprehensiveCollector()
    
    # Get initial count
    initial_stats = collector.db_manager.get_training_stats()
    initial_count = initial_stats.get('total_samples', 0)
    logger.info(f"Starting collection. Current database: {initial_count} matches")
    
    # Collect all seasons
    results = await collector.collect_all_premier_league_seasons()
    
    # Final stats
    final_stats = collector.db_manager.get_training_stats()
    final_count = final_stats.get('total_samples', 0)
    
    logger.info(f"""
=== COMPREHENSIVE COLLECTION COMPLETE ===
Initial matches: {initial_count}
Final matches: {final_count}
New matches added: {final_count - initial_count}

Season breakdown:
2024: {results.get(2024, {}).get('collected', 0)} matches
2023: {results.get(2023, {}).get('collected', 0)} matches  
2022: {results.get(2022, {}).get('collected', 0)} matches
    """)

if __name__ == "__main__":
    asyncio.run(main())