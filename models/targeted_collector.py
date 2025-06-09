"""
BetGenius AI Backend - Targeted Data Collection
Focused collection strategy: one league at a time with progress tracking
"""
import asyncio
import logging
import os
from datetime import datetime
from typing import Dict, List, Any, Optional
from models.data_collector import SportsDataCollector
from models.database import DatabaseManager

logger = logging.getLogger(__name__)

class TargetedCollector:
    """Focused data collection strategy for reliable dataset expansion"""
    
    def __init__(self):
        self.data_collector = SportsDataCollector()
        self.db_manager = None
        
    def _get_db_manager(self):
        """Lazy-load database manager"""
        if not self.db_manager:
            try:
                self.db_manager = DatabaseManager()
                logger.info("Database manager initialized for targeted collection")
            except Exception as e:
                logger.error(f"Failed to initialize database: {e}")
                self.db_manager = None
        return self.db_manager
    
    async def collect_single_league_season(self, league_id: int, season: int, 
                                         max_matches: int = 100) -> Dict[str, Any]:
        """
        Collect matches from a single league/season with progress tracking
        Returns detailed results for monitoring
        """
        start_time = datetime.now()
        results = {
            "league_id": league_id,
            "season": season,
            "started_at": start_time.isoformat(),
            "matches_processed": 0,
            "matches_saved": 0,
            "matches_failed": 0,
            "errors": [],
            "status": "in_progress"
        }
        
        try:
            logger.info(f"Starting targeted collection: League {league_id}, Season {season}")
            
            # Get completed matches for this league/season
            matches = await self._get_completed_matches(league_id, season, max_matches)
            logger.info(f"Found {len(matches)} completed matches for league {league_id}, season {season}")
            
            if not matches:
                results["status"] = "no_matches_found"
                return results
            
            db_manager = self._get_db_manager()
            if not db_manager:
                results["status"] = "database_error"
                results["errors"].append("Database manager initialization failed")
                return results
            
            # Process matches one by one with progress tracking
            for i, match in enumerate(matches):
                try:
                    match_id = match.get('fixture', {}).get('id')
                    if not match_id:
                        continue
                    
                    # Check if already exists
                    if self._match_exists(match_id):
                        logger.debug(f"Match {match_id} already exists, skipping")
                        continue
                    
                    # Collect comprehensive match data
                    match_data = await self.data_collector.get_match_data(match_id)
                    if not match_data:
                        results["matches_failed"] += 1
                        continue
                    
                    # Prepare training data
                    training_sample = self._prepare_training_sample(match, match_data, league_id, season)
                    
                    # Save to database
                    if db_manager.save_training_match(training_sample):
                        results["matches_saved"] += 1
                        logger.info(f"Saved match {match_id} ({i+1}/{len(matches)})")
                    else:
                        results["matches_failed"] += 1
                    
                    results["matches_processed"] += 1
                    
                    # Rate limiting
                    await asyncio.sleep(0.8)
                    
                    # Progress logging every 10 matches
                    if (i + 1) % 10 == 0:
                        logger.info(f"Progress: {i+1}/{len(matches)} matches processed, {results['matches_saved']} saved")
                
                except Exception as e:
                    logger.error(f"Failed to process match {match_id}: {e}")
                    results["matches_failed"] += 1
                    results["errors"].append(f"Match {match_id}: {str(e)}")
                    continue
            
            results["status"] = "completed"
            end_time = datetime.now()
            results["completed_at"] = end_time.isoformat()
            results["duration_seconds"] = (end_time - start_time).total_seconds()
            
            logger.info(f"Collection completed: {results['matches_saved']}/{results['matches_processed']} matches saved")
            
        except Exception as e:
            logger.error(f"Collection failed for league {league_id}, season {season}: {e}")
            results["status"] = "failed"
            results["errors"].append(str(e))
        
        return results
    
    async def _get_completed_matches(self, league_id: int, season: int, max_matches: int) -> List[Dict]:
        """Get completed matches for a specific league/season"""
        try:
            from models.training_data_collector import TrainingDataCollector
            collector = TrainingDataCollector()
            return await collector._get_completed_matches(league_id, season, max_matches)
        except Exception as e:
            logger.error(f"Failed to get completed matches: {e}")
            return []
    
    def _match_exists(self, match_id: int) -> bool:
        """Check if match already exists in database"""
        try:
            db_manager = self._get_db_manager()
            if not db_manager:
                return False
            
            session = db_manager.SessionLocal()
            from models.database import TrainingMatch
            existing = session.query(TrainingMatch).filter_by(match_id=match_id).first()
            session.close()
            return existing is not None
            
        except Exception as e:
            logger.error(f"Error checking if match exists: {e}")
            return False
    
    def _prepare_training_sample(self, match: Dict, match_data: Dict, 
                               league_id: int, season: int) -> Dict[str, Any]:
        """Prepare training sample for database storage"""
        try:
            # Extract match outcome
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
    
    async def expand_dataset_incrementally(self, target_matches: int = 500) -> Dict[str, Any]:
        """
        Incrementally expand dataset using targeted collection
        Prioritizes leagues and seasons based on current data gaps
        """
        start_time = datetime.now()
        
        # Priority order: Premier League (39), La Liga (140), Bundesliga (78), Serie A (135)
        leagues_priority = [
            {"id": 39, "name": "Premier League", "seasons": [2023, 2022, 2021]},
            {"id": 140, "name": "La Liga", "seasons": [2023, 2022, 2021]},
            {"id": 78, "name": "Bundesliga", "seasons": [2023, 2022, 2021]},
            {"id": 135, "name": "Serie A", "seasons": [2023, 2022, 2021]}
        ]
        
        results = {
            "started_at": start_time.isoformat(),
            "target_matches": target_matches,
            "leagues_processed": [],
            "total_new_matches": 0,
            "status": "in_progress"
        }
        
        try:
            db_manager = self._get_db_manager()
            if not db_manager:
                results["status"] = "database_error"
                return results
            
            # Get current database stats
            current_stats = db_manager.get_training_stats()
            current_total = current_stats.get("total_samples", 0)
            
            logger.info(f"Current database: {current_total} matches, target: {target_matches}")
            
            if current_total >= target_matches:
                results["status"] = "target_already_reached"
                return results
            
            # Collect from leagues in priority order until target reached
            for league in leagues_priority:
                if current_total >= target_matches:
                    break
                
                league_results = {
                    "league_id": league["id"],
                    "league_name": league["name"],
                    "seasons_collected": []
                }
                
                for season in league["seasons"]:
                    if current_total >= target_matches:
                        break
                    
                    # Calculate how many more matches we need
                    remaining_needed = target_matches - current_total
                    max_for_season = min(100, remaining_needed)
                    
                    logger.info(f"Collecting from {league['name']} {season} (need {remaining_needed} more)")
                    
                    season_result = await self.collect_single_league_season(
                        league["id"], season, max_for_season
                    )
                    
                    league_results["seasons_collected"].append(season_result)
                    current_total += season_result.get("matches_saved", 0)
                    results["total_new_matches"] += season_result.get("matches_saved", 0)
                    
                    logger.info(f"Added {season_result.get('matches_saved', 0)} matches. Total: {current_total}")
                
                results["leagues_processed"].append(league_results)
            
            end_time = datetime.now()
            results["completed_at"] = end_time.isoformat()
            results["duration_minutes"] = (end_time - start_time).total_seconds() / 60
            results["final_total"] = current_total
            results["status"] = "completed"
            
        except Exception as e:
            logger.error(f"Incremental expansion failed: {e}")
            results["status"] = "failed"
            results["error"] = str(e)
        
        return results