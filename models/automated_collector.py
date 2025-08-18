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
                                    # Allow ±2 hour window for practical collection
                                    if abs(hours_to_kickoff - window) <= 2:
                                        logger.info(f"🎯 Collecting odds for T-{window}h window (actual: T-{hours_to_kickoff:.1f}h)")
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
        """Get upcoming matches for a specific league using RapidAPI"""
        try:
            # Use RapidAPI to get fixtures (upcoming matches)
            rapid_api_key = os.environ.get('RAPIDAPI_KEY')
            if not rapid_api_key:
                logger.error("RAPIDAPI_KEY not found in environment")
                return []
            
            # Calculate date range for upcoming matches
            current_date = datetime.utcnow()
            end_date = current_date + timedelta(days=days_ahead)
            
            url = "https://api-football-v1.p.rapidapi.com/v3/fixtures"
            headers = {
                'X-RapidAPI-Key': rapid_api_key,
                'X-RapidAPI-Host': 'api-football-v1.p.rapidapi.com'
            }
            
            params = {
                'league': league_id,
                'season': 2024,  # Current season
                'status': 'NS',  # Not Started (upcoming)
                'from': current_date.strftime('%Y-%m-%d'),
                'to': end_date.strftime('%Y-%m-%d')
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        fixtures = data.get('response', [])
                        
                        # Transform to our internal format
                        upcoming_matches = []
                        for fixture in fixtures:
                            try:
                                # Parse match date and check timing windows
                                match_date_str = fixture.get('fixture', {}).get('date', '')
                                match_date = datetime.fromisoformat(match_date_str.replace('Z', '+00:00')).replace(tzinfo=None)
                                
                                # Calculate hours until match
                                hours_until_match = (match_date - current_date).total_seconds() / 3600
                                
                                # Include matches that are within our timing windows (24h-168h ahead)
                                if 24 <= hours_until_match <= 168:  # 1-7 days ahead
                                    match_data = {
                                        'match_id': fixture['fixture']['id'],
                                        'date': match_date_str,
                                        'home_team': fixture['teams']['home']['name'],
                                        'away_team': fixture['teams']['away']['name'],
                                        'home_team_id': fixture['teams']['home']['id'],
                                        'away_team_id': fixture['teams']['away']['id'],
                                        'venue': fixture.get('fixture', {}).get('venue', {}).get('name', ''),
                                        'league_id': league_id,
                                        'hours_until_match': round(hours_until_match, 1)
                                    }
                                    upcoming_matches.append(match_data)
                                    
                            except Exception as date_error:
                                logger.warning(f"Failed to parse fixture {fixture.get('fixture', {}).get('id', 'unknown')}: {date_error}")
                        
                        logger.info(f"Found {len(upcoming_matches)} upcoming matches for league {league_id} in optimal timing windows")
                        return upcoming_matches
                        
                    else:
                        logger.warning(f"RapidAPI returned status {response.status} for upcoming matches in league {league_id}")
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
                logger.warning("ODDS_API_KEY not found - cannot collect real odds data")
                return False
            
            try:
                # Map league ID to The Odds API sport key
                league_sport_map = {
                    39: 'soccer_epl',      # Premier League
                    140: 'soccer_spain_la_liga',  # La Liga
                    135: 'soccer_italy_serie_a',  # Serie A
                    78: 'soccer_germany_bundesliga',  # Bundesliga
                    61: 'soccer_france_ligue_one',    # Ligue 1
                    88: 'soccer_netherlands_eredivisie'  # Eredivisie
                }
                
                sport_key = league_sport_map.get(league_id, 'soccer_epl')
                
                # Use The Odds API to get real bookmaker odds
                url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds"
                params = {
                    'apikey': odds_api_key,  # API key as parameter
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
                                # Match by team names (fuzzy matching may be needed)
                                home_match = self._fuzzy_match_team(match['home_team'], event.get('home_team', ''))
                                away_match = self._fuzzy_match_team(match['away_team'], event.get('away_team', ''))
                                
                                if home_match and away_match:
                                    match_odds = event
                                    break
                            
                            if match_odds:
                                # Extract bookmaker odds and create consensus
                                consensus_data = self._create_odds_consensus(match_odds, match_id, timing_window)
                                
                                # Save to odds_snapshots table
                                saved = await self._save_odds_snapshot(consensus_data)
                                
                                if saved:
                                    logger.info(f"✅ Saved odds snapshot: Match {match_id}, T-{timing_window}h")
                                    return True
                                else:
                                    logger.warning(f"Failed to save odds snapshot for match {match_id}")
                                    return False
                            else:
                                logger.info(f"📭 No odds found for match {match_id} in current odds data")
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
    
    def _fuzzy_match_team(self, team1: str, team2: str) -> bool:
        """Simple fuzzy matching for team names"""
        if not team1 or not team2:
            return False
        # Simple matching - can be enhanced with fuzzy string matching
        return team1.lower().replace(' ', '') in team2.lower().replace(' ', '') or \
               team2.lower().replace(' ', '') in team1.lower().replace(' ', '')
    
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
    
    async def _save_odds_snapshot(self, consensus_data: Dict) -> bool:
        """Save odds snapshot to database"""
        try:
            # Use raw SQL to save to odds_snapshots table
            import psycopg2
            database_url = os.environ.get('DATABASE_URL')
            
            with psycopg2.connect(database_url) as conn:
                cursor = conn.cursor()
                
                # Insert into odds_snapshots table (create if needed)
                insert_sql = """
                    INSERT INTO odds_snapshots 
                    (match_id, horizon_hours, ts_effective, ph_cons, pd_cons, pa_cons,
                     n_books, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (match_id, horizon_hours) DO UPDATE SET
                    ts_effective = EXCLUDED.ts_effective,
                    ph_cons = EXCLUDED.ph_cons,
                    pd_cons = EXCLUDED.pd_cons,
                    pa_cons = EXCLUDED.pa_cons,
                    n_books = EXCLUDED.n_books,
                    created_at = EXCLUDED.created_at
                """
                
                values = (
                    consensus_data['match_id'],
                    consensus_data['horizon_hours'],
                    consensus_data['timestamp'],
                    consensus_data['ph_cons'],
                    consensus_data['pd_cons'],
                    consensus_data['pa_cons'],
                    consensus_data['n_books'],
                    consensus_data['timestamp']
                )
                
                cursor.execute(insert_sql, values)
                conn.commit()
                
            return True
            
        except Exception as e:
            logger.error(f"Failed to save odds snapshot: {e}")
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