#!/usr/bin/env python3
"""
Automated Metrics Results Calculator
Checks for completed matches in prediction_snapshots, fetches final scores from RapidAPI,
and automatically computes accuracy metrics (Brier, LogLoss, Hit-rate)
"""

import os
import sys
import requests
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any

# Add current directory to path to import our modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from models.database import DatabaseManager, PredictionSnapshot, MatchResult, MetricsPerMatch

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class MetricsResultsCalculator:
    """
    Automated calculator that:
    1. Finds completed matches from prediction_snapshots  
    2. Fetches final scores from RapidAPI
    3. Computes and stores accuracy metrics
    """
    
    def __init__(self):
        self.rapidapi_key = os.environ.get('RAPIDAPI_KEY')
        if not self.rapidapi_key:
            raise ValueError("RAPIDAPI_KEY environment variable is required")
        
        self.rapidapi_headers = {
            'X-RapidAPI-Key': self.rapidapi_key,
            'X-RapidAPI-Host': 'api-football-v1.p.rapidapi.com'
        }
        
        self.db_manager = DatabaseManager()
        
    def get_match_final_score(self, match_id: int) -> Optional[Dict[str, Any]]:
        """Fetch final match score from RapidAPI"""
        try:
            url = "https://api-football-v1.p.rapidapi.com/v3/fixtures"
            params = {'id': match_id}
            
            response = requests.get(url, headers=self.rapidapi_headers, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('response') and len(data['response']) > 0:
                    fixture = data['response'][0]
                    
                    # Check if match is finished
                    status = fixture.get('fixture', {}).get('status', {}).get('short')
                    
                    if status in ['FT', 'AET', 'PEN']:  # Full Time, After Extra Time, Penalties
                        goals = fixture.get('goals', {})
                        teams = fixture.get('teams', {})
                        league = fixture.get('league', {})
                        
                        home_goals = goals.get('home')
                        away_goals = goals.get('away')
                        
                        if home_goals is not None and away_goals is not None:
                            return {
                                'match_id': match_id,
                                'home_goals': home_goals,
                                'away_goals': away_goals,
                                'league': league.get('name', 'Unknown'),
                                'home_team': teams.get('home', {}).get('name', 'Unknown'),
                                'away_team': teams.get('away', {}).get('name', 'Unknown'),
                                'status': status,
                                'finished_at': fixture.get('fixture', {}).get('date')
                            }
                    else:
                        logger.debug(f"Match {match_id} not finished yet (status: {status})")
                        return None
            
            logger.warning(f"Failed to get match {match_id}: HTTP {response.status_code}")
            return None
            
        except Exception as e:
            logger.error(f"Error fetching match {match_id}: {e}")
            return None
    
    def find_completed_matches_needing_results(self) -> List[Dict[str, Any]]:
        """Find prediction snapshots for matches that are completed but don't have results yet"""
        try:
            session = self.db_manager.SessionLocal()
            
            # Get all prediction snapshots where:
            # 1. kickoff_at is in the past (> 2 hours ago to allow for completion)
            # 2. Match doesn't already have a result in match_results table
            cutoff_time = datetime.now(timezone.utc) - timedelta(hours=2)
            
            # Query for snapshots of matches that need results
            snapshots_query = session.query(PredictionSnapshot).filter(
                PredictionSnapshot.kickoff_at < cutoff_time,
                ~PredictionSnapshot.match_id.in_(
                    session.query(MatchResult.match_id)
                )
            ).distinct(PredictionSnapshot.match_id)
            
            snapshots = snapshots_query.all()
            session.close()
            
            completed_matches = []
            for snapshot in snapshots:
                completed_matches.append({
                    'match_id': snapshot.match_id,
                    'kickoff_at': snapshot.kickoff_at,
                    'league': snapshot.league,
                    'latest_snapshot_id': snapshot.snapshot_id
                })
            
            logger.info(f"Found {len(completed_matches)} matches needing results")
            return completed_matches
            
        except Exception as e:
            logger.error(f"Error finding completed matches: {e}")
            return []
    
    def process_completed_matches(self, limit: int = 50) -> Dict[str, int]:
        """Process completed matches and compute accuracy metrics"""
        stats = {
            'matches_checked': 0,
            'results_fetched': 0, 
            'metrics_computed': 0,
            'errors': 0
        }
        
        try:
            # Find matches needing results
            completed_matches = self.find_completed_matches_needing_results()
            
            if not completed_matches:
                logger.info("No completed matches needing results")
                return stats
            
            # Process matches (limit to avoid rate limiting)
            matches_to_process = completed_matches[:limit]
            logger.info(f"Processing {len(matches_to_process)} completed matches...")
            
            for match_info in matches_to_process:
                match_id = match_info['match_id']
                stats['matches_checked'] += 1
                
                logger.info(f"Checking match {match_id} ({match_info.get('league', 'Unknown')})...")
                
                # Fetch final score from RapidAPI
                match_result = self.get_match_final_score(match_id)
                
                if match_result:
                    logger.info(f"✅ Match {match_id}: {match_result['home_team']} {match_result['home_goals']}-{match_result['away_goals']} {match_result['away_team']}")
                    
                    # Save match result to database
                    success = self.db_manager.save_match_result(match_result)
                    
                    if success:
                        stats['results_fetched'] += 1
                        
                        # Compute accuracy metrics for this match
                        computed_count = self.db_manager.compute_accuracy_metrics()
                        stats['metrics_computed'] += computed_count
                        
                        logger.info(f"📊 Computed metrics for {computed_count} matches")
                    else:
                        logger.warning(f"Failed to save result for match {match_id}")
                        stats['errors'] += 1
                else:
                    logger.info(f"⏳ Match {match_id} not finished or data unavailable")
            
            return stats
            
        except Exception as e:
            logger.error(f"Error processing completed matches: {e}")
            stats['errors'] += 1
            return stats
    
    def run_calculation(self, limit: int = 50) -> None:
        """Main entry point - run the automated calculation"""
        logger.info("🎯 Starting automated metrics calculation...")
        logger.info(f"Checking for completed matches (limit: {limit})")
        
        try:
            stats = self.process_completed_matches(limit=limit)
            
            logger.info("📊 CALCULATION COMPLETE")
            logger.info(f"   Matches checked: {stats['matches_checked']}")
            logger.info(f"   Results fetched: {stats['results_fetched']}")  
            logger.info(f"   Metrics computed: {stats['metrics_computed']}")
            logger.info(f"   Errors: {stats['errors']}")
            
            if stats['metrics_computed'] > 0:
                logger.info("✅ New accuracy metrics are now available in the database!")
            elif stats['matches_checked'] == 0:
                logger.info("ℹ️  No completed matches found needing results")
            else:
                logger.info("ℹ️  All checked matches were either not finished or already processed")
                
        except Exception as e:
            logger.error(f"Fatal error in calculation: {e}")
            raise

def main():
    """Command line entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Calculate accuracy metrics for completed matches')
    parser.add_argument('--limit', type=int, default=50, 
                       help='Maximum number of matches to process (default: 50)')
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Enable verbose logging')
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    try:
        calculator = MetricsResultsCalculator()
        calculator.run_calculation(limit=args.limit)
        
    except KeyboardInterrupt:
        logger.info("Calculation interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Calculation failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()