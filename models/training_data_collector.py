"""
BetGenius AI Backend - Training Data Collection
Collects real historical match data for ML model training
"""

import asyncio
import aiohttp
import json
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import os

from utils.config import settings, get_rapidapi_headers
from models.data_collector import SportsDataCollector
from models.database import DatabaseManager

logger = logging.getLogger(__name__)

class TrainingDataCollector:
    """Collects authentic historical match data for training ML models"""
    
    def __init__(self):
        self.base_url = settings.RAPIDAPI_FOOTBALL_URL
        self.headers = get_rapidapi_headers()
        self.data_collector = SportsDataCollector()
        self.training_data_file = "data/training_data.json"
        self.db_manager = None
    
    def _get_db_manager(self):
        """Lazy-load database manager"""
        if self.db_manager is None:
            try:
                self.db_manager = DatabaseManager()
                logger.info("Database manager initialized successfully")
            except Exception as e:
                logger.warning(f"Database not available, using file storage: {e}")
                self.db_manager = False
        return self.db_manager
        
    async def collect_training_data(self, leagues: List[int] = [39, 140, 78, 135], 
                                  seasons: List[int] = [2023, 2022, 2021],
                                  max_matches_per_league: int = 200) -> List[Dict]:
        """
        Collect historical match data for training
        Returns list of matches with features and actual outcomes
        """
        all_training_data = []
        
        logger.info(f"Starting training data collection for {len(leagues)} leagues, {len(seasons)} seasons")
        
        # Initialize database manager
        db_manager = self._get_db_manager()
        
        for league_id in leagues:
            for season in seasons:
                try:
                    matches = await self._get_completed_matches(league_id, season, max_matches_per_league)
                    logger.info(f"Found {len(matches)} completed matches for league {league_id}, season {season}")
                    
                    # Process matches to extract features and outcomes
                    processed_matches = await self._process_matches_for_training(matches)
                    
                    # Save to database immediately instead of waiting for completion
                    if db_manager and hasattr(db_manager, 'save_training_matches_batch'):
                        saved_count = db_manager.save_training_matches_batch(processed_matches)
                        logger.info(f"Saved {saved_count} matches to database for league {league_id}, season {season}")
                    else:
                        logger.info(f"Database unavailable, collecting {len(processed_matches)} matches in memory")
                    
                    all_training_data.extend(processed_matches)
                    
                    # Rate limiting
                    await asyncio.sleep(1)
                    
                except Exception as e:
                    logger.error(f"Failed to collect data for league {league_id}, season {season}: {e}")
                    continue
        
        logger.info(f"Collected {len(all_training_data)} training samples")
        
        # Save training data
        await self._save_training_data(all_training_data)
        
        return all_training_data
    
    async def _get_completed_matches(self, league_id: int, season: int, 
                                   max_matches: int = 200) -> List[Dict]:
        """Get completed matches for a league/season"""
        try:
            url = f"{self.base_url}/fixtures"
            params = {
                "league": league_id,
                "season": season,
                "status": "FT"  # Full Time - completed matches only
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=self.headers, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        matches = data.get('response', [])
                        
                        # Filter matches with valid results
                        completed_matches = [
                            match for match in matches 
                            if (match.get('fixture', {}).get('status', {}).get('short') == 'FT' and
                                match.get('goals', {}).get('home') is not None and
                                match.get('goals', {}).get('away') is not None)
                        ]
                        
                        return completed_matches[:max_matches]
                    else:
                        logger.warning(f"API returned status {response.status} for league {league_id}")
                        return []
                        
        except Exception as e:
            logger.error(f"Failed to get completed matches: {e}")
            return []
    
    async def _process_matches_for_training(self, matches: List[Dict]) -> List[Dict]:
        """Process raw matches into training data with features and outcomes"""
        training_samples = []
        
        for match in matches:
            try:
                match_id = match.get('fixture', {}).get('id')
                if not match_id:
                    continue
                
                # Get the actual outcome
                home_goals = match.get('goals', {}).get('home', 0)
                away_goals = match.get('goals', {}).get('away', 0)
                
                if home_goals > away_goals:
                    outcome = 0  # Home win
                elif home_goals < away_goals:
                    outcome = 2  # Away win
                else:
                    outcome = 1  # Draw
                
                # Collect match data (this will get team stats, form, etc.)
                match_data = await self.data_collector.get_match_data(match_id)
                
                if match_data and 'features' in match_data:
                    # Map outcome to string for database
                    outcome_map = {0: 'Home', 1: 'Draw', 2: 'Away'}
                    
                    training_sample = {
                        'match_id': match_id,
                        'league_id': match.get('league', {}).get('id', 0),
                        'season': match.get('league', {}).get('season', 2023),
                        'home_team': match_data.get('match_info', {}).get('home_team', 'Unknown'),
                        'away_team': match_data.get('match_info', {}).get('away_team', 'Unknown'),
                        'home_team_id': match.get('teams', {}).get('home', {}).get('id'),
                        'away_team_id': match.get('teams', {}).get('away', {}).get('id'),
                        'venue': match_data.get('match_info', {}).get('venue', ''),
                        'outcome': outcome_map[outcome],
                        'home_goals': home_goals,
                        'away_goals': away_goals,
                        'features': match_data['features'],
                        'actual_score': f"{home_goals}-{away_goals}",
                        'match_info': match_data.get('match_info', {}),
                        'league': match.get('league', {}).get('name', 'Unknown')
                    }
                    training_samples.append(training_sample)
                
                # Rate limiting - don't overwhelm the API
                await asyncio.sleep(0.5)
                
            except Exception as e:
                logger.warning(f"Failed to process match {match.get('fixture', {}).get('id')}: {e}")
                continue
        
        return training_samples
    
    async def _save_training_data(self, training_data: List[Dict]):
        """Save training data to file"""
        try:
            # Ensure data directory exists
            os.makedirs("data", exist_ok=True)
            
            # Save with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"data/training_data_{timestamp}.json"
            
            with open(filename, 'w') as f:
                json.dump(training_data, f, indent=2, default=str)
            
            # Also save as the main training file
            with open(self.training_data_file, 'w') as f:
                json.dump(training_data, f, indent=2, default=str)
            
            logger.info(f"Training data saved to {filename} and {self.training_data_file}")
            
        except Exception as e:
            logger.error(f"Failed to save training data: {e}")
    
    async def load_training_data(self) -> List[Dict]:
        """Load existing training data"""
        try:
            if os.path.exists(self.training_data_file):
                with open(self.training_data_file, 'r') as f:
                    data = json.load(f)
                logger.info(f"Loaded {len(data)} training samples from {self.training_data_file}")
                return data
            else:
                logger.warning("No training data file found")
                return []
        except Exception as e:
            logger.error(f"Failed to load training data: {e}")
            return []
    
    async def update_training_data(self, days_back: int = 7) -> List[Dict]:
        """Update training data with recent completed matches"""
        try:
            # Get recent matches from major leagues
            recent_data = []
            major_leagues = [39, 140, 78, 135]  # Premier League, La Liga, Bundesliga, Serie A
            
            for league_id in major_leagues:
                # Get matches from the last week that are completed
                url = f"{self.base_url}/fixtures"
                params = {
                    "league": league_id,
                    "season": 2024,
                    "status": "FT",
                    "last": days_back
                }
                
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, headers=self.headers, params=params) as response:
                        if response.status == 200:
                            data = await response.json()
                            matches = data.get('response', [])
                            
                            processed = await self._process_matches_for_training(matches)
                            recent_data.extend(processed)
                
                await asyncio.sleep(1)  # Rate limiting
            
            if recent_data:
                # Load existing data
                existing_data = await self.load_training_data()
                
                # Combine and remove duplicates
                all_data = existing_data + recent_data
                unique_data = {item['match_id']: item for item in all_data}.values()
                
                # Save updated data
                await self._save_training_data(list(unique_data))
                
                logger.info(f"Added {len(recent_data)} new training samples")
                return list(unique_data)
            
            return await self.load_training_data()
            
        except Exception as e:
            logger.error(f"Failed to update training data: {e}")
            return await self.load_training_data()
    
    def get_training_stats(self) -> Dict[str, Any]:
        """Get statistics about current training data"""
        try:
            if os.path.exists(self.training_data_file):
                with open(self.training_data_file, 'r') as f:
                    data = json.load(f)
                
                if not data:
                    return {"total_samples": 0, "leagues": [], "outcomes": {}}
                
                # Calculate statistics
                total_samples = len(data)
                leagues = list(set(item.get('league', 'Unknown') for item in data))
                
                outcome_counts = {}
                for item in data:
                    outcome = item.get('outcome')
                    if outcome == 0:
                        outcome_counts['home_wins'] = outcome_counts.get('home_wins', 0) + 1
                    elif outcome == 1:
                        outcome_counts['draws'] = outcome_counts.get('draws', 0) + 1
                    elif outcome == 2:
                        outcome_counts['away_wins'] = outcome_counts.get('away_wins', 0) + 1
                
                return {
                    "total_samples": total_samples,
                    "leagues": leagues,
                    "outcomes": outcome_counts,
                    "last_updated": datetime.fromtimestamp(
                        os.path.getmtime(self.training_data_file)
                    ).isoformat()
                }
            
            return {"total_samples": 0, "leagues": [], "outcomes": {}}
            
        except Exception as e:
            logger.error(f"Failed to get training stats: {e}")
            return {"error": str(e)}