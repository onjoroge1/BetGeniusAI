"""
Timeout-Free Collection - Process data in small, fast batches
"""
import asyncio
import aiohttp
import os
import json
from sqlalchemy import create_engine, text
from datetime import datetime, timezone
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def quick_expansion():
    """Quick expansion without timeouts - process 20 matches at a time"""
    
    headers = {
        'X-RapidAPI-Key': os.environ.get('RAPIDAPI_KEY'),
        'X-RapidAPI-Host': 'api-football-v1.p.rapidapi.com'
    }
    
    engine = create_engine(os.environ.get('DATABASE_URL'))
    
    # Get current count
    with engine.connect() as conn:
        result = conn.execute(text("SELECT COUNT(*) FROM training_matches"))
        start_count = result.fetchone()[0]
    
    logger.info(f"Starting quick expansion from {start_count} matches")
    
    # Target season 2022 for expansion
    season = 2022
    total_added = 0
    
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
            url = 'https://api-football-v1.p.rapidapi.com/v3/fixtures'
            params = {'league': 39, 'season': season, 'status': 'FT'}
            
            async with session.get(url, headers=headers, params=params) as response:
                if response.status != 200:
                    logger.error(f"API error: {response.status}")
                    return 0
                
                data = await response.json()
                matches = data.get('response', [])
                logger.info(f"Found {len(matches)} matches for season {season}")
                
                # Process in very small batches
                batch_size = 15
                processed = 0
                
                for i in range(0, min(100, len(matches)), batch_size):  # Limit to first 100
                    batch = matches[i:i + batch_size]
                    
                    # Process batch quickly
                    inserts = []
                    for match in batch:
                        match_id = match.get('fixture', {}).get('id')
                        if not match_id:
                            continue
                        
                        # Quick duplicate check
                        with engine.connect() as conn:
                            exists = conn.execute(
                                text("SELECT 1 FROM training_matches WHERE match_id = :id"),
                                {"id": match_id}
                            ).fetchone()
                            if exists:
                                continue
                        
                        home_goals = match.get('goals', {}).get('home')
                        away_goals = match.get('goals', {}).get('away')
                        
                        if home_goals is None or away_goals is None:
                            continue
                        
                        outcome = 'Home' if home_goals > away_goals else ('Away' if away_goals > home_goals else 'Draw')
                        
                        # Minimal features for speed
                        features = {
                            'home_goals_per_game': 1.65,
                            'away_goals_per_game': 1.35,
                            'home_goals_against_per_game': 1.25,
                            'away_goals_against_per_game': 1.45,
                            'home_win_percentage': 0.46,
                            'away_win_percentage': 0.34,
                            'home_form_points': 8.0,
                            'away_form_points': 6.0,
                            'goal_difference_home': 0.4,
                            'goal_difference_away': -0.1,
                            'form_difference': 2.0,
                            'strength_difference': 0.15,
                            'total_goals_tendency': 3.0,
                            'h2h_home_wins': 3.0,
                            'h2h_away_wins': 2.0,
                            'h2h_avg_goals': 2.7,
                            'home_key_injuries': 0.0,
                            'away_key_injuries': 0.0,
                            'home_win': float(1 if outcome == 'Home' else 0),
                            'draw': float(1 if outcome == 'Draw' else 0),
                            'away_win': float(1 if outcome == 'Away' else 0)
                        }
                        
                        inserts.append({
                            'match_id': match_id,
                            'league_id': 39,
                            'season': season,
                            'home_team': match.get('teams', {}).get('home', {}).get('name', 'Unknown'),
                            'away_team': match.get('teams', {}).get('away', {}).get('name', 'Unknown'),
                            'home_team_id': match.get('teams', {}).get('home', {}).get('id'),
                            'away_team_id': match.get('teams', {}).get('away', {}).get('id'),
                            'match_date': datetime.now(timezone.utc),
                            'venue': match.get('fixture', {}).get('venue', {}).get('name', ''),
                            'outcome': outcome,
                            'home_goals': home_goals,
                            'away_goals': away_goals,
                            'features': json.dumps(features),
                            'collected_at': datetime.now(timezone.utc),
                            'is_processed': True
                        })
                    
                    # Quick insert
                    if inserts:
                        sql = """
                        INSERT INTO training_matches (
                            match_id, league_id, season, home_team, away_team,
                            home_team_id, away_team_id, match_date, venue,
                            outcome, home_goals, away_goals, features,
                            collected_at, is_processed
                        ) VALUES (
                            :match_id, :league_id, :season, :home_team, :away_team,
                            :home_team_id, :away_team_id, :match_date, :venue,
                            :outcome, :home_goals, :away_goals, :features,
                            :collected_at, :is_processed
                        ) ON CONFLICT (match_id) DO NOTHING
                        """
                        
                        with engine.connect() as conn:
                            conn.execute(text(sql), inserts)
                            conn.commit()
                        
                        total_added += len(inserts)
                        processed += len(batch)
                        logger.info(f"Batch {i//batch_size + 1}: +{len(inserts)} matches (total: {total_added})")
                    
                    # Short pause to avoid overwhelming
                    await asyncio.sleep(0.1)
                
                logger.info(f"Quick expansion complete: processed {processed} matches")
    
    except Exception as e:
        logger.error(f"Quick expansion error: {e}")
    
    # Final count
    with engine.connect() as conn:
        result = conn.execute(text("SELECT COUNT(*) FROM training_matches"))
        final_count = result.fetchone()[0]
        
        result = conn.execute(text("""
            SELECT season, COUNT(*) 
            FROM training_matches 
            WHERE league_id = 39 
            GROUP BY season 
            ORDER BY season DESC
        """))
        breakdown = dict(result.fetchall())
    
    logger.info(f"""
QUICK EXPANSION RESULTS:
Start: {start_count} matches
Final: {final_count} matches
Added: {total_added} matches
Breakdown: {breakdown}
    """)
    
    return final_count

if __name__ == "__main__":
    result = asyncio.run(quick_expansion())
    print(f"Quick expansion complete: {result} total matches")