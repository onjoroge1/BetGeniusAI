"""
BetGenius AI Backend - Automated Data Collection System
Continuous collection of completed matches for training data updates
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any
import json
import os
from .training_data_collector import TrainingDataCollector
from .database import DatabaseManager

logger = logging.getLogger(__name__)

class AutomatedCollector:
    """
    Automated system for continuous data collection and model updates
    Runs daily to collect new completed matches from all leagues
    """
    
    def __init__(self):
        self.training_collector = TrainingDataCollector()
        self.db_manager = None
        self.major_leagues = [39, 140, 78, 135]  # Premier League, La Liga, Bundesliga, Serie A
        self.current_season = 2024
        self.collection_log_file = "data/collection_log.json"
        
    def _get_db_manager(self):
        """Lazy-load database manager"""
        if self.db_manager is None:
            try:
                self.db_manager = DatabaseManager()
                logger.info("Database manager initialized for automated collection")
            except Exception as e:
                logger.warning(f"Database not available: {e}")
                self.db_manager = None
        return self.db_manager
    
    async def collect_recent_matches(self, days_back: int = 7) -> Dict[str, Any]:
        """
        Collect matches completed in the last N days across all leagues
        Returns summary of collection results
        """
        try:
            collection_summary = {
                "timestamp": datetime.utcnow().isoformat(),
                "days_back": days_back,
                "leagues_processed": [],
                "new_matches_collected": 0,
                "total_matches_in_db": 0,
                "errors": []
            }
            
            db_manager = self._get_db_manager()
            all_new_matches = []
            
            for league_id in self.major_leagues:
                try:
                    league_name = self._get_league_name(league_id)
                    logger.info(f"Collecting recent matches for {league_name} (ID: {league_id})")
                    
                    # Get recent completed matches for this league
                    recent_matches = await self._get_recent_completed_matches(
                        league_id, days_back
                    )
                    
                    if recent_matches:
                        # Process matches for training data
                        processed_matches = await self.training_collector._process_matches_for_training(
                            recent_matches
                        )
                        
                        # Save to database if available
                        if db_manager and processed_matches:
                            saved_count = db_manager.save_training_matches_batch(processed_matches)
                            all_new_matches.extend(processed_matches)
                            
                            collection_summary["leagues_processed"].append({
                                "league_id": league_id,
                                "league_name": league_name,
                                "matches_found": len(recent_matches),
                                "matches_processed": len(processed_matches),
                                "matches_saved": saved_count
                            })
                            
                            logger.info(f"Saved {saved_count} new matches from {league_name}")
                        else:
                            logger.warning(f"No database available or no matches to save for {league_name}")
                    
                    # Rate limiting between leagues
                    await asyncio.sleep(2)
                    
                except Exception as e:
                    error_msg = f"Failed to collect from league {league_id}: {e}"
                    logger.error(error_msg)
                    collection_summary["errors"].append(error_msg)
            
            # Update summary
            collection_summary["new_matches_collected"] = len(all_new_matches)
            
            if db_manager:
                stats = db_manager.get_training_stats()
                collection_summary["total_matches_in_db"] = stats.get("training_data", {}).get("total_samples", 0)
            
            # Log collection results
            await self._log_collection_results(collection_summary)
            
            return collection_summary
            
        except Exception as e:
            logger.error(f"Automated collection failed: {e}")
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "error": str(e),
                "new_matches_collected": 0
            }
    
    async def _get_recent_completed_matches(self, league_id: int, days_back: int) -> List[Dict]:
        """Get recently completed matches for a specific league"""
        try:
            # Calculate date range
            end_date = datetime.utcnow()
            start_date = end_date - timedelta(days=days_back)
            
            # Use the training collector's method to get matches
            url = f"{self.training_collector.base_url}/fixtures"
            params = {
                "league": league_id,
                "season": self.current_season,
                "status": "FT",  # Full Time only
                "from": start_date.strftime("%Y-%m-%d"),
                "to": end_date.strftime("%Y-%m-%d")
            }
            
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=self.training_collector.headers, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        matches = data.get('response', [])
                        
                        # Filter for truly completed matches with valid scores
                        completed_matches = [
                            match for match in matches 
                            if (match.get('fixture', {}).get('status', {}).get('short') == 'FT' and
                                match.get('goals', {}).get('home') is not None and
                                match.get('goals', {}).get('away') is not None)
                        ]
                        
                        logger.info(f"Found {len(completed_matches)} completed matches for league {league_id} in last {days_back} days")
                        return completed_matches
                    else:
                        logger.warning(f"API returned status {response.status} for league {league_id}")
                        return []
                        
        except Exception as e:
            logger.error(f"Failed to get recent matches for league {league_id}: {e}")
            return []
    
    def _get_league_name(self, league_id: int) -> str:
        """Get human-readable league name"""
        league_names = {
            39: "Premier League",
            140: "La Liga",
            78: "Bundesliga", 
            135: "Serie A"
        }
        return league_names.get(league_id, f"League {league_id}")
    
    async def _log_collection_results(self, results: Dict[str, Any]):
        """Log collection results to file for monitoring"""
        try:
            # Load existing log
            log_entries = []
            if os.path.exists(self.collection_log_file):
                with open(self.collection_log_file, 'r') as f:
                    log_entries = json.load(f)
            
            # Add new entry
            log_entries.append(results)
            
            # Keep only last 30 days of logs
            cutoff_date = datetime.utcnow() - timedelta(days=30)
            log_entries = [
                entry for entry in log_entries 
                if datetime.fromisoformat(entry["timestamp"].replace('Z', '+00:00')) > cutoff_date
            ]
            
            # Save updated log
            os.makedirs(os.path.dirname(self.collection_log_file), exist_ok=True)
            with open(self.collection_log_file, 'w') as f:
                json.dump(log_entries, f, indent=2, default=str)
                
            logger.info(f"Collection results logged to {self.collection_log_file}")
            
        except Exception as e:
            logger.error(f"Failed to log collection results: {e}")
    
    async def auto_retrain_if_needed(self, min_new_matches: int = 50) -> bool:
        """
        Automatically retrain models if enough new data has been collected
        Returns True if retraining was triggered
        """
        try:
            db_manager = self._get_db_manager()
            if not db_manager:
                logger.warning("No database available for auto-retraining")
                return False
            
            # Check how many matches collected in last 7 days
            recent_matches = db_manager.get_recent_matches(limit=1000)
            week_ago = datetime.utcnow() - timedelta(days=7)
            
            recent_count = sum(
                1 for match in recent_matches 
                if datetime.fromisoformat(match["collected_at"].replace('Z', '+00:00')) > week_ago
            )
            
            if recent_count >= min_new_matches:
                logger.info(f"Found {recent_count} new matches, triggering model retraining...")
                
                # Import and retrain ML models
                from .ml_predictor import MLPredictor
                predictor = MLPredictor()
                predictor._train_models()
                
                if predictor.is_trained:
                    logger.info("Models successfully retrained with new data")
                    return True
                else:
                    logger.warning("Model retraining failed")
                    return False
            else:
                logger.info(f"Only {recent_count} new matches, retraining threshold is {min_new_matches}")
                return False
                
        except Exception as e:
            logger.error(f"Auto-retraining failed: {e}")
            return False
    
    async def daily_collection_cycle(self):
        """
        Complete daily collection cycle:
        1. Collect recent matches
        2. Auto-retrain if enough new data
        3. Log results
        """
        try:
            logger.info("Starting daily automated collection cycle...")
            
            # Collect recent matches (last 3 days to catch any delayed results)
            collection_results = await self.collect_recent_matches(days_back=3)
            
            # Auto-retrain if we have enough new data
            if collection_results["new_matches_collected"] >= 10:
                retrain_success = await self.auto_retrain_if_needed(min_new_matches=10)
                collection_results["auto_retrained"] = retrain_success
            else:
                collection_results["auto_retrained"] = False
            
            logger.info(f"Daily collection cycle completed: {collection_results['new_matches_collected']} new matches")
            return collection_results
            
        except Exception as e:
            logger.error(f"Daily collection cycle failed: {e}")
            return {"error": str(e), "new_matches_collected": 0}
    
    def get_collection_history(self, days: int = 7) -> List[Dict]:
        """Get collection history for monitoring"""
        try:
            if not os.path.exists(self.collection_log_file):
                return []
            
            with open(self.collection_log_file, 'r') as f:
                log_entries = json.load(f)
            
            # Filter to last N days
            cutoff_date = datetime.utcnow() - timedelta(days=days)
            recent_entries = [
                entry for entry in log_entries 
                if datetime.fromisoformat(entry["timestamp"].replace('Z', '+00:00')) > cutoff_date
            ]
            
            return recent_entries
            
        except Exception as e:
            logger.error(f"Failed to get collection history: {e}")
            return []