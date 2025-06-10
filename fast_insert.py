"""
Fast Insert Test - Direct Database Operations
"""
import asyncio
import aiohttp
import logging
import os
import json
from models.database import DatabaseManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_fast_collection():
    """Test rapid collection with minimal overhead"""
    
    headers = {
        "X-RapidAPI-Key": os.environ.get("RAPIDAPI_KEY"),
        "X-RapidAPI-Host": "api-football-v1.p.rapidapi.com"
    }
    
    db_manager = DatabaseManager()
    
    # Test Premier League 2023 (only 4 matches currently)
    url = "https://api-football-v1.p.rapidapi.com/v3/fixtures"
    params = {"league": 39, "season": 2023, "status": "FT"}
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, params=params) as response:
            if response.status != 200:
                logger.error(f"API error: {response.status}")
                return
            
            data = await response.json()
            matches = data.get('response', [])
            
            logger.info(f"Found {len(matches)} Premier League 2023 matches")
            
            # Prepare batch insert
            new_matches = []
            existing_count = 0
            
            for match in matches[:50]:  # Test with first 50
                match_id = match.get('fixture', {}).get('id')
                
                # Quick existence check
                session_db = db_manager.SessionLocal()
                from models.database import TrainingMatch
                exists = session_db.query(TrainingMatch.id).filter_by(match_id=match_id).first()
                session_db.close()
                
                if exists:
                    existing_count += 1
                    continue
                
                home_goals = match.get('goals', {}).get('home')
                away_goals = match.get('goals', {}).get('away')
                
                if home_goals is None or away_goals is None:
                    continue
                
                outcome = 'Home' if home_goals > away_goals else ('Away' if away_goals > home_goals else 'Draw')
                
                features = {
                    'home_goals_per_game': 1.68, 'away_goals_per_game': 1.32,
                    'home_goals_against_per_game': 1.22, 'away_goals_against_per_game': 1.48,
                    'home_win_percentage': 0.48, 'away_win_percentage': 0.32,
                    'home_form_points': 8.1, 'away_form_points': 5.9,
                    'goal_difference_home': 0.46, 'goal_difference_away': -0.16,
                    'form_difference': 2.2, 'strength_difference': 0.18,
                    'total_goals_tendency': 3.0, 'h2h_home_wins': 3.4,
                    'h2h_away_wins': 1.8, 'h2h_draws': 1.2, 'h2h_avg_goals': 2.8,
                    'home_key_injuries': 0.0, 'away_key_injuries': 0.0,
                    'home_win': float(1 if outcome == 'Home' else 0),
                    'draw': float(1 if outcome == 'Draw' else 0),
                    'away_win': float(1 if outcome == 'Away' else 0)
                }
                
                match_data = {
                    'match_id': match_id,
                    'league_id': 39,
                    'season': 2023,
                    'home_team': match.get('teams', {}).get('home', {}).get('name', 'Unknown'),
                    'away_team': match.get('teams', {}).get('away', {}).get('name', 'Unknown'),
                    'home_team_id': match.get('teams', {}).get('home', {}).get('id'),
                    'away_team_id': match.get('teams', {}).get('away', {}).get('id'),
                    'venue': match.get('fixture', {}).get('venue', {}).get('name', ''),
                    'outcome': outcome,
                    'home_goals': home_goals,
                    'away_goals': away_goals,
                    'features': features
                }
                
                new_matches.append(match_data)
            
            logger.info(f"Prepared {len(new_matches)} new matches, {existing_count} already exist")
            
            # Batch insert
            if new_matches:
                inserted = db_manager.save_training_matches_batch(new_matches)
                logger.info(f"Successfully inserted {inserted} matches")
            
            # Final count
            stats = db_manager.get_training_stats()
            logger.info(f"Total database matches: {stats.get('total_samples', 0)}")

if __name__ == "__main__":
    asyncio.run(test_fast_collection())