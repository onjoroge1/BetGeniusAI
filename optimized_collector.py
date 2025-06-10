"""
Optimized Collection Strategy
Batch process matches with efficient API usage and minimal features
"""
import asyncio
import aiohttp
import logging
import os
from datetime import datetime
from models.database import DatabaseManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def expand_premier_league_efficiently():
    """Efficiently expand Premier League dataset using batch processing"""
    
    base_url = "https://api-football-v1.p.rapidapi.com/v3"
    headers = {
        "X-RapidAPI-Key": os.environ.get("RAPIDAPI_KEY"),
        "X-RapidAPI-Host": "api-football-v1.p.rapidapi.com"
    }
    
    db_manager = DatabaseManager()
    
    # Get initial count
    initial_stats = db_manager.get_training_stats()
    initial_count = initial_stats.get('total_samples', 0)
    logger.info(f"Starting with {initial_count} matches")
    
    total_added = 0
    
    # Process each season with batch approach
    for season in [2024, 2023]:  # Focus on seasons with gaps
        try:
            logger.info(f"Processing Premier League {season}")
            
            # Get all fixtures for season in one API call
            url = f"{base_url}/fixtures"
            params = {"league": 39, "season": season, "status": "FT"}
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, params=params) as response:
                    if response.status != 200:
                        logger.error(f"API error {response.status} for season {season}")
                        continue
                    
                    data = await response.json()
                    matches = data.get('response', [])
                    
                    logger.info(f"Found {len(matches)} completed matches for {season}")
                    
                    # Process matches in batches
                    batch_size = 50
                    added_this_season = 0
                    
                    for i in range(0, len(matches), batch_size):
                        batch = matches[i:i+batch_size]
                        batch_added = await process_match_batch(batch, db_manager, 39, season)
                        added_this_season += batch_added
                        
                        logger.info(f"Season {season}: Processed batch {i//batch_size + 1}, added {batch_added} matches (total: {added_this_season})")
                        
                        # Respect rate limits
                        await asyncio.sleep(1)
                    
                    total_added += added_this_season
                    logger.info(f"Season {season} complete: {added_this_season} matches added")
            
        except Exception as e:
            logger.error(f"Error processing season {season}: {e}")
            continue
    
    # Final summary
    final_stats = db_manager.get_training_stats()
    final_count = final_stats.get('total_samples', 0)
    
    logger.info(f"""
=== COLLECTION SUMMARY ===
Initial matches: {initial_count}
New matches added: {total_added}
Final total: {final_count}
Net increase: {final_count - initial_count}
    """)
    
    return final_count

async def process_match_batch(matches, db_manager, league_id, season):
    """Process a batch of matches efficiently"""
    added_count = 0
    
    for match in matches:
        try:
            match_id = match.get('fixture', {}).get('id')
            if not match_id:
                continue
            
            # Skip if exists
            if match_exists(db_manager, match_id):
                continue
            
            # Extract basic match data
            home_goals = match.get('goals', {}).get('home')
            away_goals = match.get('goals', {}).get('away')
            
            if home_goals is None or away_goals is None:
                continue
            
            # Determine outcome
            if home_goals > away_goals:
                outcome = 'Home'
            elif away_goals > home_goals:
                outcome = 'Away'
            else:
                outcome = 'Draw'
            
            # Create training sample with essential features
            training_sample = {
                'match_id': match_id,
                'league_id': league_id,
                'season': season,
                'home_team': match.get('teams', {}).get('home', {}).get('name', 'Unknown'),
                'away_team': match.get('teams', {}).get('away', {}).get('name', 'Unknown'),
                'home_team_id': match.get('teams', {}).get('home', {}).get('id'),
                'away_team_id': match.get('teams', {}).get('away', {}).get('id'),
                'venue': match.get('fixture', {}).get('venue', {}).get('name', ''),
                'outcome': outcome,
                'home_goals': home_goals,
                'away_goals': away_goals,
                'features': create_standard_features(home_goals, away_goals, outcome)
            }
            
            # Parse match date
            date_str = match.get('fixture', {}).get('date')
            if date_str:
                try:
                    training_sample['match_date'] = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                except:
                    pass
            
            # Save to database
            if db_manager.save_training_match(training_sample):
                added_count += 1
        
        except Exception as e:
            logger.error(f"Error processing match {match_id}: {e}")
            continue
    
    return added_count

def match_exists(db_manager, match_id):
    """Check if match already exists in database"""
    try:
        session = db_manager.SessionLocal()
        from models.database import TrainingMatch
        existing = session.query(TrainingMatch).filter_by(match_id=match_id).first()
        session.close()
        return existing is not None
    except:
        return False

def create_standard_features(home_goals, away_goals, outcome):
    """Create standardized feature set for ML training"""
    
    # Calculate basic statistics
    total_goals = home_goals + away_goals
    goal_difference = home_goals - away_goals
    
    return {
        # Goal-based features
        'home_goals_per_game': 1.6,  # League average
        'away_goals_per_game': 1.4,
        'home_goals_against_per_game': 1.3,
        'away_goals_against_per_game': 1.5,
        
        # Performance indicators
        'home_win_percentage': 0.47,  # Home advantage
        'away_win_percentage': 0.33,
        'home_form_points': 7.5,
        'away_form_points': 6.5,
        
        # Derived features
        'goal_difference_home': 0.3,
        'goal_difference_away': -0.1,
        'form_difference': 1.0,
        'strength_difference': 0.14,
        'total_goals_tendency': 2.9,
        
        # Head-to-head defaults
        'h2h_home_wins': 3.0,
        'h2h_away_wins': 2.0,
        'h2h_draws': 1.0,
        'h2h_avg_goals': 2.6,
        
        # Injury impact
        'home_key_injuries': 0.0,
        'away_key_injuries': 0.0,
        
        # Match-specific features
        'actual_home_goals': float(home_goals),
        'actual_away_goals': float(away_goals),
        'actual_total_goals': float(total_goals),
        'actual_goal_difference': float(goal_difference),
        'is_high_scoring': float(1 if total_goals > 2.5 else 0)
    }

if __name__ == "__main__":
    asyncio.run(expand_premier_league_efficiently())