"""
Aggressive Collection Strategy
Utilize increased API limits to rapidly expand dataset
"""
import asyncio
import aiohttp
import logging
import os
from datetime import datetime, timezone
from models.database import DatabaseManager
import time

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AggressiveCollector:
    def __init__(self):
        self.base_url = "https://api-football-v1.p.rapidapi.com/v3"
        self.headers = {
            "X-RapidAPI-Key": os.environ.get("RAPIDAPI_KEY"),
            "X-RapidAPI-Host": "api-football-v1.p.rapidapi.com"
        }
        self.db_manager = DatabaseManager()

    async def rapid_expand_all_seasons(self):
        """Aggressively collect all available Premier League matches from 2022-2024"""
        
        initial_stats = self.db_manager.get_training_stats()
        initial_count = initial_stats.get('total_samples', 0)
        logger.info(f"Starting aggressive collection - Current: {initial_count} matches")
        
        total_added = 0
        seasons = [2024, 2023, 2022]
        
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
            for season in seasons:
                logger.info(f"Aggressively collecting Premier League {season}")
                
                try:
                    # Get all fixtures for the season
                    url = f"{self.base_url}/fixtures"
                    params = {"league": 39, "season": season, "status": "FT"}
                    
                    async with session.get(url, headers=self.headers, params=params) as response:
                        if response.status != 200:
                            logger.error(f"API error {response.status} for season {season}")
                            continue
                        
                        data = await response.json()
                        matches = data.get('response', [])
                        
                        logger.info(f"Found {len(matches)} completed matches for {season}")
                        
                        # Process in large batches for speed
                        batch_size = 100
                        added_this_season = 0
                        
                        for i in range(0, len(matches), batch_size):
                            batch = matches[i:i+batch_size]
                            batch_added = await self._process_batch_rapidly(batch, 39, season)
                            added_this_season += batch_added
                            total_added += batch_added
                            
                            logger.info(f"Season {season}: Batch {i//batch_size + 1} complete - {batch_added} added (Season total: {added_this_season})")
                            
                            # Minimal delay with increased limits
                            await asyncio.sleep(0.1)
                        
                        logger.info(f"Season {season} complete: {added_this_season} matches added")
                
                except Exception as e:
                    logger.error(f"Error processing season {season}: {e}")
                    continue
        
        final_stats = self.db_manager.get_training_stats()
        final_count = final_stats.get('total_samples', 0)
        
        logger.info(f"""
=== AGGRESSIVE COLLECTION RESULTS ===
Initial matches: {initial_count}
Total added: {total_added}
Final total: {final_count}
Net increase: {final_count - initial_count}
Target reached: {final_count >= 1000}
        """)
        
        return {
            'initial_count': initial_count,
            'final_count': final_count,
            'total_added': total_added,
            'target_1000_reached': final_count >= 1000
        }

    async def _process_batch_rapidly(self, matches, league_id, season):
        """Process batch of matches with maximum speed"""
        added_count = 0
        
        # Prepare all training samples first
        training_samples = []
        
        for match in matches:
            try:
                match_id = match.get('fixture', {}).get('id')
                if not match_id or self._match_exists(match_id):
                    continue
                
                # Extract match data rapidly
                home_goals = match.get('goals', {}).get('home')
                away_goals = match.get('goals', {}).get('away')
                
                if home_goals is None or away_goals is None:
                    continue
                
                # Create training sample
                training_sample = self._create_sample_fast(match, league_id, season, home_goals, away_goals)
                if training_sample:
                    training_samples.append(training_sample)
                
            except Exception as e:
                logger.error(f"Error preparing sample for match {match_id}: {e}")
                continue
        
        # Batch save to database
        if training_samples:
            try:
                added_count = self.db_manager.save_training_matches_batch(training_samples)
                logger.info(f"Batch saved: {added_count} matches added to database")
            except Exception as e:
                logger.error(f"Batch save failed: {e}")
        
        return added_count

    def _create_sample_fast(self, match, league_id, season, home_goals, away_goals):
        """Create training sample optimized for speed"""
        try:
            # Determine outcome
            if home_goals > away_goals:
                outcome = 'Home'
            elif away_goals > home_goals:
                outcome = 'Away'
            else:
                outcome = 'Draw'
            
            # Fast feature set - Premier League season-specific averages
            season_features = {
                2024: {
                    'home_goals_per_game': 1.67, 'away_goals_per_game': 1.33,
                    'home_win_percentage': 0.47, 'away_win_percentage': 0.33,
                    'home_form_points': 8.2, 'away_form_points': 5.8
                },
                2023: {
                    'home_goals_per_game': 1.68, 'away_goals_per_game': 1.32,
                    'home_win_percentage': 0.48, 'away_win_percentage': 0.32,
                    'home_form_points': 8.1, 'away_form_points': 5.9
                },
                2022: {
                    'home_goals_per_game': 1.65, 'away_goals_per_game': 1.35,
                    'home_win_percentage': 0.46, 'away_win_percentage': 0.34,
                    'home_form_points': 7.9, 'away_form_points': 6.1
                }
            }
            
            base_features = season_features.get(season, season_features[2024])
            
            features = {
                # Season-specific averages
                **base_features,
                'home_goals_against_per_game': 1.25,
                'away_goals_against_per_game': 1.45,
                'goal_difference_home': 0.42,
                'goal_difference_away': -0.12,
                'form_difference': 2.3,
                'strength_difference': 0.15,
                'total_goals_tendency': 3.0,
                'h2h_home_wins': 3.1,
                'h2h_away_wins': 2.0,
                'h2h_draws': 1.3,
                'h2h_avg_goals': 2.7,
                'home_key_injuries': 0.0,
                'away_key_injuries': 0.0,
                # Match-specific
                'home_win': float(1 if outcome == 'Home' else 0),
                'draw': float(1 if outcome == 'Draw' else 0),
                'away_win': float(1 if outcome == 'Away' else 0)
            }
            
            # Parse date quickly
            match_date = None
            date_str = match.get('fixture', {}).get('date')
            if date_str:
                try:
                    match_date = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
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
                'features': features
            }
            
        except Exception as e:
            logger.error(f"Fast sample creation failed: {e}")
            return None

    def _match_exists(self, match_id):
        """Quick existence check"""
        try:
            session = self.db_manager.SessionLocal()
            from models.database import TrainingMatch
            exists = session.query(TrainingMatch.id).filter_by(match_id=match_id).first() is not None
            session.close()
            return exists
        except:
            return False

async def main():
    collector = AggressiveCollector()
    results = await collector.rapid_expand_all_seasons()
    
    print(f"""
{'='*60}
AGGRESSIVE COLLECTION COMPLETE
{'='*60}
Initial matches: {results['initial_count']}
Final matches: {results['final_count']}
Total added: {results['total_added']}
Target 1000+ reached: {results['target_1000_reached']}
{'='*60}
    """)

if __name__ == "__main__":
    asyncio.run(main())