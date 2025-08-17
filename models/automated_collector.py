"""
BetGenius AI Backend - Automated Data Collection System
Continuous collection of completed matches for training data updates
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import json
import os
import aiohttp
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
                            logger.info(f"💾 SAVING TO DATABASE: {len(processed_matches)} processed matches from {league_name}")
                            logger.info(f"🎯 TARGET TABLE: training_matches (TrainingMatch model)")
                            
                            saved_count = db_manager.save_training_matches_batch(processed_matches)
                            all_new_matches.extend(processed_matches)
                            
                            collection_summary["leagues_processed"].append({
                                "league_id": league_id,
                                "league_name": league_name,
                                "matches_found": len(recent_matches),
                                "matches_processed": len(processed_matches),
                                "matches_saved": saved_count,
                                "target_table": "training_matches"
                            })
                            
                            logger.info(f"✅ SAVED: {saved_count} new matches from {league_name} to 'training_matches' table")
                            
                            if saved_count != len(processed_matches):
                                duplicates = len(processed_matches) - saved_count
                                logger.info(f"⚠️ DUPLICATES SKIPPED: {duplicates} matches already existed in database")
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
        ENHANCED DUAL COLLECTION CYCLE:
        1. Phase A: Collect recent completed matches → training_matches
        2. Phase B: Collect upcoming match odds → odds_snapshots  
        3. Auto-retrain if enough new data
        4. Log comprehensive results
        """
        try:
            logger.info("🔄 Starting ENHANCED dual collection cycle...")
            logger.info("📋 Phase A: Completed matches → training_matches")
            logger.info("📋 Phase B: Upcoming matches → odds_snapshots")
            
            # Phase A: Collect recent matches (existing functionality)
            completed_results = await self.collect_recent_matches(days_back=3)
            
            # Phase B: Collect upcoming match odds (NEW)
            odds_results = await self.collect_upcoming_odds_snapshots()
            
            # Combine results
            total_collection_results = {
                "timestamp": datetime.utcnow().isoformat(),
                "phase_a_completed": completed_results,
                "phase_b_odds": odds_results,
                "new_matches_collected": completed_results.get("new_matches_collected", 0),
                "new_odds_collected": odds_results.get("new_odds_collected", 0),
                "total_new_data_points": (
                    completed_results.get("new_matches_collected", 0) + 
                    odds_results.get("new_odds_collected", 0)
                ),
                "auto_retrained": False
            }
            
            # Auto-retrain if we have enough new training data
            if completed_results.get("new_matches_collected", 0) >= 10:
                retrain_success = await self.auto_retrain_if_needed(min_new_matches=10)
                total_collection_results["auto_retrained"] = retrain_success
            
            logger.info(f"✅ DUAL collection completed:")
            logger.info(f"   • Training matches: {completed_results.get('new_matches_collected', 0)} new")
            logger.info(f"   • Odds snapshots: {odds_results.get('new_odds_collected', 0)} new")
            logger.info(f"   • Total data points: {total_collection_results['total_new_data_points']}")
            
            return total_collection_results
            
        except Exception as e:
            logger.error(f"❌ Dual collection cycle failed: {e}")
            return {
                "error": str(e), 
                "new_matches_collected": 0,
                "new_odds_collected": 0,
                "total_new_data_points": 0
            }
    
    async def collect_upcoming_odds_snapshots(self) -> Dict[str, Any]:
        """
        NEW: Collect odds snapshots for upcoming matches at optimal timing windows
        Populates odds_snapshots table for T-48h/T-24h model predictions
        """
        try:
            logger.info("🎯 Starting odds snapshots collection for upcoming matches...")
            
            odds_summary = {
                "timestamp": datetime.utcnow().isoformat(),
                "leagues_processed": [],
                "new_odds_collected": 0,
                "upcoming_matches_found": 0,
                "errors": []
            }
            
            db_manager = self._get_db_manager()
            
            # Get upcoming matches in next 7 days
            for league_id in self.major_leagues:
                try:
                    league_name = self._get_league_name(league_id)
                    logger.info(f"🔍 Checking upcoming matches for {league_name} (ID: {league_id})")
                    
                    upcoming_matches = await self._get_upcoming_matches(league_id, days_ahead=7)
                    
                    if upcoming_matches:
                        logger.info(f"📅 Found {len(upcoming_matches)} upcoming matches in {league_name}")
                        
                        for match in upcoming_matches:
                            try:
                                # Calculate hours to kickoff
                                match_date = datetime.fromisoformat(
                                    match['fixture']['date'].replace('Z', '+00:00')
                                ).replace(tzinfo=None)
                                hours_to_kickoff = (match_date - datetime.utcnow()).total_seconds() / 3600
                                
                                # Collect odds at specific timing windows
                                if hours_to_kickoff in [72, 48, 24, 12, 6, 3, 1]:
                                    odds_collected = await self._collect_and_save_odds(
                                        match, league_id, hours_to_kickoff
                                    )
                                    if odds_collected:
                                        odds_summary["new_odds_collected"] += 1
                                        
                            except Exception as match_error:
                                logger.warning(f"Failed to process match odds: {match_error}")
                        
                        odds_summary["upcoming_matches_found"] += len(upcoming_matches)
                        odds_summary["leagues_processed"].append({
                            "league_id": league_id,
                            "league_name": league_name,
                            "upcoming_matches": len(upcoming_matches)
                        })
                    else:
                        logger.info(f"📭 No upcoming matches found for {league_name}")
                    
                    # Rate limiting
                    await asyncio.sleep(2)
                    
                except Exception as league_error:
                    error_msg = f"Failed to collect odds for league {league_id}: {league_error}"
                    logger.error(error_msg)
                    odds_summary["errors"].append(error_msg)
            
            logger.info(f"✅ Odds collection completed: {odds_summary['new_odds_collected']} new snapshots")
            return odds_summary
            
        except Exception as e:
            logger.error(f"❌ Odds snapshots collection failed: {e}")
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "error": str(e),
                "new_odds_collected": 0,
                "upcoming_matches_found": 0
            }
    
    async def _get_upcoming_matches(self, league_id: int, days_ahead: int = 7) -> List[Dict]:
        """Get upcoming matches for a specific league"""
        try:
            # Calculate date range for upcoming matches
            start_date = datetime.utcnow()
            end_date = start_date + timedelta(days=days_ahead)
            
            url = f"{self.training_collector.base_url}/fixtures"
            params = {
                "league": league_id,
                "season": self.current_season,
                "status": "NS",  # Not Started only
                "from": start_date.strftime("%Y-%m-%d"),
                "to": end_date.strftime("%Y-%m-%d")
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=self.training_collector.headers, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        matches = data.get('response', [])
                        
                        # Filter for scheduled matches with valid fixture data
                        upcoming_matches = [
                            match for match in matches 
                            if (match.get('fixture', {}).get('status', {}).get('short') == 'NS' and
                                match.get('fixture', {}).get('date') is not None)
                        ]
                        
                        logger.info(f"Found {len(upcoming_matches)} upcoming matches for league {league_id}")
                        return upcoming_matches
                    else:
                        logger.warning(f"API returned status {response.status} for upcoming matches in league {league_id}")
                        return []
                        
        except Exception as e:
            logger.error(f"Failed to get upcoming matches for league {league_id}: {e}")
            return []
    
    async def _collect_and_save_odds(self, match: Dict, league_id: int, hours_to_kickoff: float) -> bool:
        """Collect and save odds snapshot for a specific match and timing"""
        try:
            # This is a placeholder for odds collection logic
            # In production, this would fetch from The Odds API or similar
            logger.info(f"📊 Would collect odds for match {match['fixture']['id']} at T-{int(hours_to_kickoff)}h")
            
            # For now, we'll log the intent but not actually collect
            # This prevents API overuse during development
            return False  # Set to True when actual odds API is integrated
            
        except Exception as e:
            logger.error(f"Failed to collect odds for match {match.get('fixture', {}).get('id', 'unknown')}: {e}")
            return False
    
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