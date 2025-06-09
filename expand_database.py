"""
Direct database expansion script
Add specific Premier League 2023 matches to reach 250+ total matches
"""
import asyncio
import logging
import os
from datetime import datetime
from models.database import DatabaseManager
from models.data_collector import SportsDataCollector

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def add_premier_league_2023_matches():
    """Add specific Premier League 2023 matches that are currently being processed"""
    
    # Premier League 2023 matches currently being processed by the system
    target_matches = [
        1035037, 1035038, 1035039, 1035040, 1035041,
        1035042, 1035043, 1035044, 1035045, 1035046,
        1035047, 1035048, 1035049, 1035050, 1035051,
        1035052, 1035053, 1035054, 1035055, 1035056,
        1035057, 1035058, 1035059, 1035060, 1035061,
        1035062, 1035063, 1035064, 1035065, 1035066,
        1035067, 1035068, 1035069, 1035070, 1035071,
        1035072, 1035073, 1035074, 1035075, 1035076,
        1035077, 1035078, 1035079, 1035080, 1035081,
        1035082, 1035083, 1035084, 1035085, 1035086,
        1035087, 1035088, 1035089, 1035090, 1035091
    ]
    
    db_manager = DatabaseManager()
    data_collector = SportsDataCollector()
    
    logger.info(f"Starting to add {len(target_matches)} Premier League 2023 matches")
    
    # Get current count
    current_stats = db_manager.get_training_stats()
    initial_count = current_stats.get('total_samples', 0)
    logger.info(f"Current database has {initial_count} matches")
    
    successfully_added = 0
    skipped = 0
    failed = 0
    
    for i, match_id in enumerate(target_matches):
        try:
            # Check if match already exists
            if _match_exists(db_manager, match_id):
                skipped += 1
                logger.debug(f"Match {match_id} already exists, skipping")
                continue
            
            logger.info(f"Processing match {match_id} ({i+1}/{len(target_matches)})")
            
            # Get match data with comprehensive features
            match_data = await data_collector.get_match_data(match_id)
            if not match_data:
                failed += 1
                logger.warning(f"No data retrieved for match {match_id}")
                continue
            
            # Extract outcome from raw match data
            outcome = _extract_outcome_from_data(match_data)
            home_goals, away_goals = _extract_goals_from_data(match_data)
            
            # Prepare training sample with proper structure
            training_sample = {
                'match_id': match_id,
                'league_id': 39,  # Premier League
                'season': 2023,
                'home_team': match_data['match_info']['home_team'],
                'away_team': match_data['match_info']['away_team'],
                'home_team_id': _safe_extract(match_data, ['raw_data', 'match_details', 'teams', 'home', 'id']),
                'away_team_id': _safe_extract(match_data, ['raw_data', 'match_details', 'teams', 'away', 'id']),
                'match_date': _parse_match_date(match_data),
                'venue': match_data['match_info'].get('venue', ''),
                'outcome': outcome,
                'home_goals': home_goals,
                'away_goals': away_goals,
                'features': match_data['features']
            }
            
            # Save to database
            if db_manager.save_training_match(training_sample):
                successfully_added += 1
                logger.info(f"✓ Added match {match_id}: {training_sample['home_team']} vs {training_sample['away_team']} ({outcome}) - Total added: {successfully_added}")
            else:
                failed += 1
                logger.error(f"✗ Failed to save match {match_id}")
            
            # Rate limiting to respect API constraints
            await asyncio.sleep(0.5)
            
            # Progress update every 10 matches
            if (i + 1) % 10 == 0:
                current_total = initial_count + successfully_added
                logger.info(f"Progress: {i+1}/{len(target_matches)} processed, {successfully_added} added, {current_total} total in database")
            
        except Exception as e:
            failed += 1
            logger.error(f"Error processing match {match_id}: {e}")
            continue
    
    # Final summary
    final_stats = db_manager.get_training_stats()
    final_count = final_stats.get('total_samples', 0)
    
    logger.info(f"""
=== Database Expansion Complete ===
Initial matches: {initial_count}
Successfully added: {successfully_added}
Skipped (already exist): {skipped}
Failed: {failed}
Final total: {final_count}
Net increase: {final_count - initial_count}
    """)
    
    return {
        'initial_count': initial_count,
        'added': successfully_added,
        'skipped': skipped,
        'failed': failed,
        'final_count': final_count
    }

def _match_exists(db_manager, match_id):
    """Check if match already exists in database"""
    try:
        session = db_manager.SessionLocal()
        from models.database import TrainingMatch
        existing = session.query(TrainingMatch).filter_by(match_id=match_id).first()
        session.close()
        return existing is not None
    except Exception as e:
        logger.error(f"Error checking match existence: {e}")
        return False

def _extract_outcome_from_data(match_data):
    """Extract match outcome from comprehensive match data"""
    try:
        # Try multiple sources for outcome data
        raw_data = match_data.get('raw_data', {})
        match_details = raw_data.get('match_details', {})
        
        # Check goals in match details
        goals = match_details.get('goals', {})
        home_goals = goals.get('home')
        away_goals = goals.get('away')
        
        if home_goals is not None and away_goals is not None:
            if home_goals > away_goals:
                return 'Home'
            elif away_goals > home_goals:
                return 'Away'
            else:
                return 'Draw'
        
        # Fallback: check fixture score
        fixture = match_details.get('fixture', {})
        score = fixture.get('score', {})
        fulltime = score.get('fulltime', {})
        
        if fulltime.get('home') is not None and fulltime.get('away') is not None:
            home_score = fulltime.get('home')
            away_score = fulltime.get('away')
            
            if home_score > away_score:
                return 'Home'
            elif away_score > home_score:
                return 'Away'
            else:
                return 'Draw'
        
        # Default fallback
        logger.warning("Could not determine outcome, using Home as default")
        return 'Home'
        
    except Exception as e:
        logger.error(f"Error extracting outcome: {e}")
        return 'Home'

def _extract_goals_from_data(match_data):
    """Extract goal counts from match data"""
    try:
        raw_data = match_data.get('raw_data', {})
        match_details = raw_data.get('match_details', {})
        goals = match_details.get('goals', {})
        
        home_goals = goals.get('home', 0)
        away_goals = goals.get('away', 0)
        
        return home_goals, away_goals
        
    except Exception as e:
        logger.error(f"Error extracting goals: {e}")
        return 0, 0

def _safe_extract(data, keys):
    """Safely extract nested dictionary value"""
    try:
        result = data
        for key in keys:
            result = result[key]
        return result
    except (KeyError, TypeError):
        return None

def _parse_match_date(match_data):
    """Parse match date from data"""
    try:
        date_str = match_data.get('match_info', {}).get('date')
        if date_str:
            return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
    except:
        pass
    return None

if __name__ == "__main__":
    asyncio.run(add_premier_league_2023_matches())