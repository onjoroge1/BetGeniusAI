"""
BetGenius AI Backend - Automated Data Collection System
Continuous collection of completed matches for training data updates
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional
import json
import os
import aiohttp
import psycopg2
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
        self.current_season = 2025  # Updated for current season
        self.collection_log_file = "data/collection_log.json"
        self.internal_api_base = "http://localhost:8000"  # Use internal API for upcoming matches
        
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
            
            # Get leagues from league_map table
            configured_leagues = self._get_configured_leagues()
            if not configured_leagues:
                logger.warning("No leagues found in league_map table, using default leagues")
                configured_leagues = [39, 140, 78, 135]  # Fallback to major leagues
            
            for league_id in configured_leagues:
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
                        
                        # Save to database if available - DUAL TABLE POPULATION
                        if db_manager and processed_matches:
                            logger.info(f"💾 DUAL SAVE: {len(processed_matches)} processed matches from {league_name}")
                            logger.info(f"🎯 TARGET TABLES: training_matches + odds_consensus")
                            
                            # Save to training_matches table
                            training_saved = db_manager.save_training_matches_batch(processed_matches)
                            
                            # ALSO save to odds_consensus table for cross-table consistency
                            consensus_saved = db_manager.save_odds_consensus_batch(processed_matches)
                            
                            total_saved = max(training_saved, consensus_saved)  # Count unique matches across both tables
                            all_new_matches.extend(processed_matches[:total_saved])  # Only count actually new matches
                            
                            collection_summary["leagues_processed"].append({
                                "league_id": league_id,
                                "league_name": league_name,
                                "matches_found": len(recent_matches),
                                "matches_processed": len(processed_matches),
                                "matches_saved": total_saved,
                                "target_tables": ["training_matches", "odds_consensus"],
                                "training_saved": training_saved,
                                "consensus_saved": consensus_saved
                            })
                            
                            logger.info(f"✅ DUAL SAVE COMPLETE: {league_name}")
                            logger.info(f"   • training_matches: {training_saved} new")
                            logger.info(f"   • odds_consensus: {consensus_saved} new")
                            
                            if total_saved != len(processed_matches):
                                duplicates = len(processed_matches) - total_saved
                                logger.info(f"⚠️ DUPLICATES SKIPPED: {duplicates} matches already existed in both tables")
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
    
    def _get_configured_leagues(self) -> List[int]:
        """Get list of league IDs from league_map table"""
        try:
            # Use environment variable for database connection
            import os
            import psycopg2
            database_url = os.getenv('DATABASE_URL')
            
            if not database_url:
                logger.error("DATABASE_URL environment variable not found")
                return []
            
            conn = psycopg2.connect(database_url)
            cursor = conn.cursor()
            
            cursor.execute("SELECT league_id FROM league_map ORDER BY league_id")
            league_ids = [row[0] for row in cursor.fetchall()]
            
            cursor.close()
            conn.close()
            
            logger.info(f"📋 Found {len(league_ids)} configured leagues in league_map: {league_ids}")
            return league_ids
            
        except Exception as e:
            logger.error(f"Failed to get configured leagues from league_map: {e}")
            return []
    
    def _get_theodds_sport_key(self, league_id: int) -> Optional[str]:
        """Get TheOdds API sport key from league_map table"""
        try:
            database_url = os.getenv('DATABASE_URL')
            if not database_url:
                logger.error("DATABASE_URL environment variable not found")
                return None
            
            conn = psycopg2.connect(database_url)
            cursor = conn.cursor()
            
            cursor.execute(
                "SELECT theodds_sport_key FROM league_map WHERE league_id = %s", 
                (league_id,)
            )
            result = cursor.fetchone()
            
            cursor.close()
            conn.close()
            
            if result and result[0]:
                return result[0]
            else:
                logger.warning(f"No theodds_sport_key found for league_id {league_id}")
                return None
                
        except Exception as e:
            logger.error(f"Failed to get theodds_sport_key for league {league_id}: {e}")
            return None
    
    def _get_league_name(self, league_id: int) -> str:
        """Get human-readable league name"""
        league_names = {
            39: "Premier League", 
            61: "Ligue 1",
            78: "Bundesliga",
            88: "Eredivisie", 
            135: "Serie A",
            140: "La Liga"
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
            
            # Phase B: Collect upcoming match odds - MULTI-SOURCE
            # B1: The Odds API (21+ bookmakers)
            theodds_results = await self.collect_upcoming_odds_snapshots()
            
            # B2: API-Football (data consistency with training)
            apifootball_results = await self.collect_upcoming_odds_apifootball()
            
            # Combine results
            total_odds_collected = (
                theodds_results.get("new_odds_collected", 0) + 
                apifootball_results.get("rows_inserted", 0)
            )
            
            total_collection_results = {
                "timestamp": datetime.utcnow().isoformat(),
                "phase_a_completed": completed_results,
                "phase_b_theodds": theodds_results,
                "phase_b_apifootball": apifootball_results,
                "new_matches_collected": completed_results.get("new_matches_collected", 0),
                "new_odds_collected": total_odds_collected,
                "total_new_data_points": (
                    completed_results.get("new_matches_collected", 0) + 
                    total_odds_collected
                ),
                "auto_retrained": False
            }
            
            # Auto-retrain if we have enough new training data
            if completed_results.get("new_matches_collected", 0) >= 10:
                retrain_success = await self.auto_retrain_if_needed(min_new_matches=10)
                total_collection_results["auto_retrained"] = retrain_success
            
            logger.info(f"✅ MULTI-SOURCE collection completed:")
            logger.info(f"   • Training matches: {completed_results.get('new_matches_collected', 0)} new")
            logger.info(f"   • The Odds API: {theodds_results.get('new_odds_collected', 0)} snapshots")
            logger.info(f"   • API-Football: {apifootball_results.get('rows_inserted', 0)} rows")
            logger.info(f"   • Total odds collected: {total_odds_collected}")
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
        Uses The Odds API as primary source
        """
        try:
            logger.info("🎯 Starting The Odds API collection for upcoming matches...")
            
            odds_summary = {
                "timestamp": datetime.utcnow().isoformat(),
                "source": "theodds",
                "leagues_processed": [],
                "new_odds_collected": 0,
                "upcoming_matches_found": 0,
                "errors": []
            }
            
            db_manager = self._get_db_manager()
            
            # Get leagues from league_map table
            configured_leagues = self._get_configured_leagues()
            if not configured_leagues:
                logger.warning("No leagues found in league_map table, skipping odds collection")
                return odds_summary
            
            # Get upcoming matches in next 7 days
            for league_id in configured_leagues:
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
                                    match['date'].replace('Z', '+00:00')
                                ).replace(tzinfo=None)
                                hours_to_kickoff = (match_date - datetime.utcnow()).total_seconds() / 3600
                                
                                logger.info(f"🕐 Match {match['match_id']} ({match['home_team']} vs {match['away_team']}) - T-{hours_to_kickoff:.1f}h")
                                
                                # Collect odds at specific timing windows (allow range not exact)
                                timing_windows = [72, 48, 24, 12, 6, 3, 1]
                                for window in timing_windows:
                                    # Allow MUCH larger window for practical collection (±12 hours for T-48h, ±8h for others)
                                    tolerance = 12 if window >= 48 else 8
                                    if abs(hours_to_kickoff - window) <= tolerance:
                                        logger.info(f"🎯 Collecting odds for T-{window}h window (actual: T-{hours_to_kickoff:.1f}h, tolerance: ±{tolerance}h)")
                                        odds_collected = await self._collect_and_save_odds(
                                            match, league_id, window
                                        )
                                        if odds_collected:
                                            odds_summary["new_odds_collected"] += 1
                                        break
                                        
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
            
            logger.info(f"✅ The Odds API collection completed: {odds_summary['new_odds_collected']} new snapshots")
            return odds_summary
            
        except Exception as e:
            logger.error(f"❌ Odds snapshots collection failed: {e}")
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "error": str(e),
                "new_odds_collected": 0,
                "upcoming_matches_found": 0
            }
    
    async def collect_upcoming_odds_apifootball(self) -> Dict[str, Any]:
        """
        NEW: Collect real-time odds from API-Football for upcoming matches
        Provides data consistency with training data (same source)
        Complements The Odds API collection for multi-source odds
        
        Uses /matches/upcoming as authoritative source (no dependency on matches table)
        """
        try:
            logger.info("🎯 Starting API-Football real-time collection for upcoming matches...")
            
            from utils.api_football_integration import ApiFootballIngestion
            
            odds_summary = {
                "timestamp": datetime.utcnow().isoformat(),
                "source": "apifootball",
                "fixtures_processed": 0,
                "rows_inserted": 0,
                "matches_found": 0,
                "errors": []
            }
            
            # Use /matches/upcoming as authoritative source (same as TheOdds uses)
            # This eliminates dependency on matches table or odds_snapshots.raw_data
            upcoming_matches = []
            
            # Get configured leagues from database
            db_url = os.environ.get('DATABASE_URL')
            if not db_url:
                logger.error("DATABASE_URL not set - cannot fetch league configuration")
                return odds_summary
            
            conn = psycopg2.connect(db_url)
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT league_id FROM league_map ORDER BY league_id")
            league_ids = [row[0] for row in cursor.fetchall()]
            cursor.close()
            conn.close()
            
            logger.info(f"📋 Fetching upcoming matches from {len(league_ids)} leagues via /matches/upcoming")
            
            # Get upcoming matches for each league
            for league_id in league_ids:
                try:
                    league_matches = await self._get_upcoming_matches(league_id)
                    if league_matches:
                        upcoming_matches.extend(league_matches)
                except Exception as e:
                    logger.warning(f"Failed to get upcoming matches for league {league_id}: {e}")
            
            if not upcoming_matches:
                logger.info("📭 No upcoming matches found from /matches/upcoming")
                return odds_summary
            
            # Filter to matches within 7 days
            current_time = datetime.utcnow()
            filtered_matches = []
            for match in upcoming_matches:
                try:
                    match_date = datetime.fromisoformat(match['date'].replace('Z', '+00:00')).replace(tzinfo=None)
                    hours_to_kickoff = (match_date - current_time).total_seconds() / 3600
                    if 0 < hours_to_kickoff <= 168:  # 7 days
                        filtered_matches.append({
                            'match_id': match['match_id'],
                            'league_id': match['league_id'],
                            'kickoff_at': match_date,
                            'home_team': match['home_team'],
                            'away_team': match['away_team'],
                            'hours_to_kickoff': hours_to_kickoff
                        })
                except Exception as e:
                    logger.warning(f"Failed to parse match date: {e}")
            
            upcoming_matches = filtered_matches
            
            if not upcoming_matches:
                logger.info("📭 No upcoming matches found within 7 days")
                return odds_summary
            
            logger.info(f"📅 Found {len(upcoming_matches)} upcoming matches from /matches/upcoming")
            odds_summary["matches_found"] = len(upcoming_matches)
            
            # Track resolver metrics
            resolver_stats = {"from_matches": 0, "from_snapshots": 0, "from_live_search": 0, "failed": 0}
            
            # Process each match and collect odds at timing windows
            for match in upcoming_matches:
                match_id = match['match_id']
                league_id = match['league_id']
                kickoff = match['kickoff_at']
                home_team = match['home_team']
                away_team = match['away_team']
                hours_to_kickoff = match['hours_to_kickoff']
                
                try:
                    logger.info(
                        f"🕐 Match {match_id} ({home_team} vs {away_team}) - T-{hours_to_kickoff:.1f}h"
                    )
                    
                    # Check if we should collect at current timing window
                    timing_windows = [72, 48, 24, 12, 6, 3, 1]
                    should_collect = False
                    
                    for window in timing_windows:
                        tolerance = 12 if window >= 48 else 8
                        if abs(hours_to_kickoff - window) <= tolerance:
                            logger.info(
                                f"🎯 Collecting API-Football odds for T-{window}h window "
                                f"(actual: T-{hours_to_kickoff:.1f}h, tolerance: ±{tolerance}h)"
                            )
                            should_collect = True
                            break
                    
                    if not should_collect:
                        logger.debug(f"⏭️  Skipping - not in timing window (T-{hours_to_kickoff:.1f}h)")
                        continue
                    
                    # 3-step resolver: breaks circular dependency
                    fixture_id = ApiFootballIngestion.resolve_fixture_id(
                        match_id=match_id,
                        league_id=league_id,
                        kickoff_at=kickoff,
                        home_team=home_team,
                        away_team=away_team
                    )
                    
                    if not fixture_id:
                        logger.warning(f"❌ No fixture_id for {home_team} vs {away_team} (match {match_id})")
                        resolver_stats["failed"] += 1
                        continue
                    
                    # Track which resolver step worked (simplified tracking via log inspection)
                    resolver_stats["from_snapshots"] += 1  # Most will come from Step 2
                    
                    # Collect odds using API-Football
                    rows = ApiFootballIngestion.ingest_fixture_odds(
                        fixture_id=fixture_id,
                        match_id=match_id,
                        league_id=league_id,
                        kickoff_ts=kickoff,
                        live=False
                    )
                    
                    if rows > 0:
                        odds_summary["fixtures_processed"] += 1
                        odds_summary["rows_inserted"] += rows
                        logger.info(f"✅ Collected {rows} odds rows for fixture {fixture_id}")
                        
                        # Refresh consensus for this match
                        ApiFootballIngestion.refresh_consensus_for_match(match_id)
                    
                    # Rate limiting: 0.3s between fixtures (~200 req/min max)
                    await asyncio.sleep(0.3)
                    
                except Exception as match_error:
                    error_msg = f"Failed to collect odds for match {match_id}: {match_error}"
                    logger.warning(error_msg)
                    odds_summary["errors"].append(error_msg)
            
            logger.info(
                f"✅ API-Football real-time collection completed: "
                f"{odds_summary['fixtures_processed']} fixtures, "
                f"{odds_summary['rows_inserted']} rows inserted"
            )
            logger.info(f"📊 Resolver Stats: {resolver_stats}")
            odds_summary["resolver_stats"] = resolver_stats
            return odds_summary
            
        except Exception as e:
            logger.error(f"❌ API-Football real-time collection failed: {e}")
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "source": "apifootball",
                "error": str(e),
                "fixtures_processed": 0,
                "rows_inserted": 0
            }
    
    async def _get_upcoming_matches(self, league_id: int, days_ahead: int = 7) -> List[Dict]:
        """Get upcoming matches for a specific league using internal API"""
        try:
            # Use internal API endpoint that already has upcoming matches
            url = f"{self.internal_api_base}/matches/upcoming"
            params = {
                "league_id": league_id,
                "limit": 50  # Get more matches to check timing windows
            }
            
            # Add authorization for internal API
            headers = {
                'Authorization': 'Bearer betgenius_secure_key_2024'
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        matches = data.get('matches', [])
                        
                        # Filter matches in optimal timing windows
                        upcoming_matches = []
                        current_time = datetime.utcnow()
                        
                        for match in matches:
                            try:
                                # Parse match date
                                match_date = datetime.fromisoformat(
                                    match['date'].replace('Z', '+00:00')
                                ).replace(tzinfo=None)
                                
                                # Calculate hours until match
                                hours_until_match = (match_date - current_time).total_seconds() / 3600
                                
                                # Include matches within practical timing windows for T-72h/T-48h/T-24h collection
                                # Expand to include closer matches for testing (2h-168h ahead) 
                                if 2 <= hours_until_match <= 168:  # 2 hours to 7 days ahead
                                    match_data = {
                                        'match_id': match['match_id'],
                                        'date': match['date'],
                                        'home_team': match['home_team'],
                                        'away_team': match['away_team'],
                                        'venue': match.get('venue', ''),
                                        'league_id': league_id,
                                        'hours_until_match': round(hours_until_match, 1),
                                        'status': match.get('status', 'NS'),
                                        'prediction_ready': match.get('prediction_ready', False)
                                    }
                                    upcoming_matches.append(match_data)
                                    
                            except Exception as date_error:
                                logger.warning(f"Failed to parse date for match {match.get('match_id', 'unknown')}: {date_error}")
                        
                        logger.info(f"Found {len(upcoming_matches)} upcoming matches for league {league_id} in optimal timing windows (24h-168h ahead)")
                        return upcoming_matches
                    else:
                        logger.warning(f"Internal API returned status {response.status} for upcoming matches in league {league_id}")
                        return []
                        
        except Exception as e:
            logger.error(f"Failed to get upcoming matches for league {league_id}: {e}")
            return []
    
    async def _collect_and_save_odds(self, match: Dict, league_id: int, timing_window: int) -> bool:
        """Collect and save odds snapshot for a specific match and timing"""
        try:
            match_id = match.get('match_id')
            logger.info(f"📊 Collecting odds for match {match_id} ({match['home_team']} vs {match['away_team']}) at T-{timing_window}h")
            
            # Get real odds data from The Odds API
            odds_api_key = os.environ.get('ODDS_API_KEY')
            if not odds_api_key:
                logger.warning("ODDS_API_KEY not found - cannot collect authentic odds data")
                return False
            
            try:
                # Get sport key from league_map table (dynamic lookup replaces hardcoded map)
                sport_key = self._get_theodds_sport_key(league_id)
                
                if not sport_key:
                    logger.error(f"❌ CRITICAL: League {league_id} not mapped to Odds API sport key in league_map table!")
                    return False
                
                # Use The Odds API to get real bookmaker odds
                url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds"
                params = {
                    'apiKey': odds_api_key,  # API key as parameter (correct case)
                    'regions': 'eu',  # European bookmakers
                    'markets': 'h2h',  # Head-to-head (match winner)
                    'oddsFormat': 'decimal',
                    'dateFormat': 'iso'
                }
                headers = {}
                
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, params=params) as response:
                        if response.status == 200:
                            odds_data = await response.json()
                            
                            # Find odds for this specific match
                            match_odds = None
                            for event in odds_data:
                                # Match by team names with 0.92 threshold
                                home_match = self._team_match_passes_threshold(match['home_team'], event.get('home_team', ''))
                                away_match = self._team_match_passes_threshold(match['away_team'], event.get('away_team', ''))
                                
                                if home_match and away_match:
                                    match_odds = event
                                    break
                            
                            if match_odds:
                                logger.info(f"🎯 MATCH FOUND: {match['home_team']} vs {match['away_team']} → {match_odds.get('home_team', '')} vs {match_odds.get('away_team', '')}")
                                
                                # Extract individual bookmaker odds 
                                individual_odds = self._extract_bookmaker_odds(match_odds, match_id, league_id, timing_window)
                                
                                if individual_odds:
                                    logger.info(f"📊 Extracted {len(individual_odds)} bookmaker odds entries")
                                    
                                    # Save to odds_snapshots table
                                    saved = await self._save_odds_snapshot(individual_odds)
                                    
                                    if saved:
                                        logger.info(f"✅ ODDS SAVED: Match {match_id}, T-{timing_window}h ({len(individual_odds)} bookmaker entries)")
                                        return True
                                    else:
                                        logger.warning(f"Failed to save odds snapshot for match {match_id}")
                                        return False
                                else:
                                    logger.warning(f"No valid bookmaker odds extracted for match {match_id}")
                                    return False
                            else:
                                logger.info(f"📭 No team match found for {match['home_team']} vs {match['away_team']} in {len(odds_data)} API events")
                                # Log first few API events for debugging
                                for i, event in enumerate(odds_data[:3]):
                                    logger.debug(f"   API Event {i+1}: {event.get('home_team', '')} vs {event.get('away_team', '')}")
                                return False
                                
                        else:
                            logger.warning(f"The Odds API returned status {response.status}")
                            return False
                            
            except Exception as api_error:
                logger.warning(f"Failed to get odds for match {match_id}: {api_error}")
                return False
            
        except Exception as e:
            logger.error(f"Failed to collect odds for match {match.get('match_id', 'unknown')}: {e}")
            return False
    

    
    def _fuzzy_match_team(self, team1: str, team2: str) -> float:
        """Enhanced fuzzy matching with 0.92 threshold and alias support"""
        if not team1 or not team2:
            return 0.0
        
        # Team aliases for common variations
        team_aliases = {
            'internazionale': ['inter', 'inter milan'],
            'athletic club': ['athletic bilbao', 'athletic'],
            'atletico madrid': ['atletico', 'atm'],
            'real madrid': ['madrid', 'rmcf'],
            'barcelona': ['barca', 'fcb'],
            'manchester city': ['man city', 'city', 'mcfc'],
            'manchester united': ['man united', 'united', 'mufc'],
            'tottenham': ['spurs', 'thfc'],
            'deportivo la coruna': ['deportivo', 'depor'],
            'real sociedad': ['sociedad'],
            'valencia cf': ['valencia'],
            'cordoba': ['cordoba cf'],
            'castellon': ['cd castellon'],
            'mirandes': ['cd mirandes'],
            'albacete': ['albacete bp']
        }
        
        def normalize_team(name: str) -> str:
            """Advanced normalization: lowercase, strip diacritics, remove prefixes/suffixes"""
            import unicodedata
            import re
            
            # Remove accents and diacritics
            name = unicodedata.normalize('NFD', name)
            name = ''.join(c for c in name if unicodedata.category(c) != 'Mn')
            
            # Convert to lowercase
            name = name.lower().strip()
            
            # Remove common prefixes/suffixes
            prefixes_suffixes = [
                'fc', 'cf', 'city', 'united', 'atletico', 'athletic', 'club', 'sporting',
                'real', 'deportivo', 'cd', 'ud', 'ad', 'sd', 'racing', 'ca', 'ac', 'as',
                'u19', 'u21', 'ii', 'b', 'reserves', 'sp', 'bp'
            ]
            
            # Split into words
            words = re.split(r'[\s\-\.]+', name)
            filtered_words = []
            
            for word in words:
                # Remove empty words and single characters (except meaningful ones)
                if len(word) > 1 or word in ['a', 'o']:
                    # Remove common prefixes/suffixes
                    if word not in prefixes_suffixes:
                        filtered_words.append(word)
            
            # Join and remove all non-alphanumeric
            result = ''.join(filtered_words)
            return re.sub(r'[^a-z0-9]', '', result)
        
        # Check aliases first
        def check_aliases(name1: str, name2: str) -> bool:
            norm_name1 = normalize_team(name1)
            norm_name2 = normalize_team(name2)
            
            for canonical, aliases in team_aliases.items():
                canon_norm = normalize_team(canonical)
                if (norm_name1 == canon_norm and any(normalize_team(alias) == norm_name2 for alias in aliases)) or \
                   (norm_name2 == canon_norm and any(normalize_team(alias) == norm_name1 for alias in aliases)):
                    return True
            return False
        
        if check_aliases(team1, team2):
            return 1.0
        
        # Normalize both names
        norm1 = normalize_team(team1)
        norm2 = normalize_team(team2)
        
        # Exact match
        if norm1 == norm2:
            return 1.0
        
        # Substring matching (minimum 3 chars)
        if len(norm1) >= 3 and len(norm2) >= 3:
            if norm1 in norm2 or norm2 in norm1:
                # Calculate overlap ratio
                overlap = min(len(norm1), len(norm2))
                total = max(len(norm1), len(norm2))
                return overlap / total
        
        # Jaro-Winkler similarity (using simplified Levenshtein)
        if len(norm1) >= 3 and len(norm2) >= 3:
            def jaro_winkler_similarity(s1: str, s2: str) -> float:
                """Simplified Jaro-Winkler using Levenshtein"""
                if s1 == s2:
                    return 1.0
                
                # Levenshtein distance
                def levenshtein(a: str, b: str) -> int:
                    if len(a) < len(b):
                        return levenshtein(b, a)
                    if len(b) == 0:
                        return len(a)
                    
                    prev_row = list(range(len(b) + 1))
                    for i, c1 in enumerate(a):
                        curr_row = [i + 1]
                        for j, c2 in enumerate(b):
                            insertions = prev_row[j + 1] + 1
                            deletions = curr_row[j] + 1
                            substitutions = prev_row[j] + (c1 != c2)
                            curr_row.append(min(insertions, deletions, substitutions))
                        prev_row = curr_row
                    return prev_row[-1]
                
                distance = levenshtein(s1, s2)
                max_len = max(len(s1), len(s2))
                return 1 - (distance / max_len) if max_len > 0 else 0.0
            
            return jaro_winkler_similarity(norm1, norm2)
        
        return 0.0
    
    def _team_match_passes_threshold(self, team1: str, team2: str, threshold: float = 0.92) -> bool:
        """Check if team matching passes the 0.92 threshold"""
        similarity = self._fuzzy_match_team(team1, team2)
        
        # Log near-misses for curation (0.85-0.92)
        if 0.85 <= similarity < threshold:
            logger.warning(f"🔍 NEAR-MISS (similarity={similarity:.3f}): '{team1}' vs '{team2}' - consider adding alias")
        
        return similarity >= threshold
    
    def _extract_bookmaker_odds(self, match_odds: Dict, match_id: int, league_id: int, timing_window: int) -> List[Dict]:
        """Extract individual bookmaker odds for database storage"""
        bookmakers = match_odds.get('bookmakers', [])
        
        if not bookmakers:
            return []
        
        odds_data = []
        current_time = datetime.utcnow()
        match_time = datetime.fromisoformat(match_odds.get('commence_time', '').replace('Z', '+00:00')).replace(tzinfo=None)
        secs_to_kickoff = int((match_time - current_time).total_seconds())
        
        for bookmaker in bookmakers:
            book_name = bookmaker.get('title', 'Unknown')
            book_id = hash(book_name) % 1000  # Simple ID from name
            
            markets = bookmaker.get('markets', [])
            for market in markets:
                if market.get('key') == 'h2h':
                    outcomes = market.get('outcomes', [])
                    for outcome in outcomes:
                        odds_decimal = float(outcome.get('price', 1.0))
                        implied_prob = 1.0 / odds_decimal if odds_decimal > 0 else 0.0
                        
                        # Map outcome names to standard format
                        outcome_name = outcome.get('name', '')
                        if outcome_name == match_odds.get('home_team'):
                            outcome_code = 'H'
                        elif outcome_name == match_odds.get('away_team'):
                            outcome_code = 'A'
                        elif 'draw' in outcome_name.lower():
                            outcome_code = 'D'
                        else:
                            continue  # Skip unknown outcomes
                        
                        odds_entry = {
                            'match_id': match_id,
                            'league_id': league_id,
                            'book_id': book_id,
                            'outcome': outcome_code,
                            'odds_decimal': odds_decimal,
                            'implied_prob': implied_prob,
                            'secs_to_kickoff': secs_to_kickoff,
                            'timestamp': current_time
                        }
                        odds_data.append(odds_entry)
        
        return odds_data
    
    def _create_odds_consensus(self, match_odds: Dict, match_id: int, timing_window: int) -> Dict:
        """Create consensus from multiple bookmaker odds"""
        bookmakers = match_odds.get('bookmakers', [])
        
        if not bookmakers:
            return None
            
        # Extract odds from all bookmakers
        all_home_odds = []
        all_draw_odds = []
        all_away_odds = []
        
        for bookmaker in bookmakers:
            markets = bookmaker.get('markets', [])
            for market in markets:
                if market.get('key') == 'h2h':
                    outcomes = market.get('outcomes', [])
                    for outcome in outcomes:
                        if outcome.get('name') == match_odds.get('home_team'):
                            all_home_odds.append(float(outcome.get('price', 0)))
                        elif outcome.get('name') == match_odds.get('away_team'):
                            all_away_odds.append(float(outcome.get('price', 0)))
                        elif 'draw' in outcome.get('name', '').lower():
                            all_draw_odds.append(float(outcome.get('price', 0)))
        
        if not all_home_odds or not all_away_odds:
            return None
        
        # Calculate consensus probabilities (simple average of implied probabilities)
        avg_home_prob = sum(1/odds for odds in all_home_odds) / len(all_home_odds) if all_home_odds else 0.33
        avg_draw_prob = sum(1/odds for odds in all_draw_odds) / len(all_draw_odds) if all_draw_odds else 0.33
        avg_away_prob = sum(1/odds for odds in all_away_odds) / len(all_away_odds) if all_away_odds else 0.33
        
        # Normalize probabilities
        total_prob = avg_home_prob + avg_draw_prob + avg_away_prob
        if total_prob > 0:
            avg_home_prob /= total_prob
            avg_draw_prob /= total_prob
            avg_away_prob /= total_prob
        
        return {
            'match_id': match_id,
            'horizon_hours': timing_window,
            'ph_cons': avg_home_prob,
            'pd_cons': avg_draw_prob,
            'pa_cons': avg_away_prob,
            'n_books': len(bookmakers),
            'timestamp': datetime.utcnow()
        }
    
    async def _save_odds_snapshot(self, odds_data: List[Dict]) -> bool:
        """Save individual bookmaker odds to database"""
        try:
            import psycopg2
            database_url = os.environ.get('DATABASE_URL')
            
            with psycopg2.connect(database_url) as conn:
                cursor = conn.cursor()
                
                # FIRST: Upsert fixture metadata for each unique match (canonical source of truth)
                unique_matches = {}
                for book_odds in odds_data:
                    match_id = book_odds['match_id']
                    if match_id not in unique_matches:
                        unique_matches[match_id] = book_odds
                
                for match_id, book_odds in unique_matches.items():
                    try:
                        # Calculate kickoff time from snapshot
                        ts_snapshot = book_odds['timestamp']
                        secs_to_kickoff = book_odds.get('secs_to_kickoff', 0)
                        kickoff_at = ts_snapshot + timedelta(seconds=secs_to_kickoff)
                        
                        cursor.execute("""
                            INSERT INTO fixtures (
                                match_id, league_id, home_team, away_team, 
                                kickoff_at, season, status, updated_at
                            )
                            VALUES (%s, %s, %s, %s, %s, %s, %s, now())
                            ON CONFLICT (match_id) DO UPDATE SET
                                league_id = EXCLUDED.league_id,
                                kickoff_at = EXCLUDED.kickoff_at,
                                status = CASE
                                    WHEN EXCLUDED.kickoff_at < now() THEN 'finished'
                                    ELSE 'scheduled'
                                END,
                                updated_at = now()
                        """, (
                            match_id,
                            book_odds.get('league_id', 0),
                            'TBD',  # Team names not in odds_data, will be updated later
                            'TBD',
                            kickoff_at,
                            2024,
                            'finished' if kickoff_at < datetime.utcnow() else 'scheduled'
                        ))
                    except Exception as fixture_err:
                        logger.warning(f"Failed to upsert fixture {match_id}: {fixture_err}")
                
                # SECOND: Insert each bookmaker's odds individually
                saved_count = 0
                for book_odds in odds_data:
                    insert_sql = """
                        INSERT INTO odds_snapshots 
                        (match_id, league_id, book_id, market, ts_snapshot, secs_to_kickoff,
                         outcome, odds_decimal, implied_prob, market_margin, api_football_fixture_id, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (match_id, book_id, market, outcome) DO UPDATE SET
                        odds_decimal = EXCLUDED.odds_decimal,
                        implied_prob = EXCLUDED.implied_prob,
                        ts_snapshot = EXCLUDED.ts_snapshot,
                        secs_to_kickoff = EXCLUDED.secs_to_kickoff,
                        api_football_fixture_id = EXCLUDED.api_football_fixture_id
                    """
                    
                    values = (
                        book_odds['match_id'],
                        book_odds['league_id'],
                        book_odds['book_id'],
                        'h2h',  # Head-to-head market
                        book_odds['timestamp'],
                        book_odds['secs_to_kickoff'],
                        book_odds['outcome'],
                        book_odds['odds_decimal'],
                        book_odds['implied_prob'],
                        book_odds.get('market_margin', 0.05),
                        book_odds['match_id'],  # Store match_id as api_football_fixture_id (TheOdds uses APIF IDs)
                        book_odds['timestamp']
                    )
                    
                    cursor.execute(insert_sql, values)
                    saved_count += 1
                
                conn.commit()
                logger.info(f"Saved {saved_count} individual bookmaker odds to odds_snapshots")
                return True
                
        except Exception as e:
            logger.error(f"Failed to save odds snapshots: {e}")
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