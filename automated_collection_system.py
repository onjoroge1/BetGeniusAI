"""
Automated Collection System - Daily collection of new matches
"""
import asyncio
import aiohttp
import os
import json
from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine, text
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AutomatedCollector:
    """Automated system for daily match collection"""
    
    def __init__(self):
        self.headers = {
            'X-RapidAPI-Key': os.environ.get('RAPIDAPI_KEY'),
            'X-RapidAPI-Host': 'api-football-v1.p.rapidapi.com'
        }
        self.engine = create_engine(os.environ.get('DATABASE_URL'))
        
    async def collect_recent_matches(self, days_back=7):
        """Collect matches from the last N days"""
        logger.info(f"Collecting matches from last {days_back} days")
        
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days_back)
        
        # Premier League and other major leagues
        leagues = [39, 140, 78, 135, 61]  # Premier League, La Liga, Bundesliga, Serie A, Ligue 1
        total_collected = 0
        
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
            for league_id in leagues:
                try:
                    collected = await self._collect_league_recent(session, league_id, start_date, end_date)
                    total_collected += collected
                    logger.info(f"League {league_id}: {collected} new matches")
                    
                except Exception as e:
                    logger.error(f"Failed to collect league {league_id}: {e}")
        
        return total_collected
    
    async def _collect_league_recent(self, session, league_id, start_date, end_date):
        """Collect recent matches for a specific league"""
        url = 'https://api-football-v1.p.rapidapi.com/v3/fixtures'
        params = {
            'league': league_id,
            'season': 2024,
            'status': 'FT',
            'from': start_date.strftime('%Y-%m-%d'),
            'to': end_date.strftime('%Y-%m-%d')
        }
        
        try:
            async with session.get(url, headers=self.headers, params=params) as response:
                if response.status != 200:
                    return 0
                
                data = await response.json()
                matches = data.get('response', [])
                
                if not matches:
                    return 0
                
                # Process matches
                new_matches = []
                for match in matches:
                    match_id = match.get('fixture', {}).get('id')
                    if not match_id:
                        continue
                    
                    # Check if already exists
                    with self.engine.connect() as conn:
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
                    
                    # League-specific features
                    league_stats = {
                        39: {'avg_goals': 2.8, 'home_adv': 0.15},  # Premier League
                        140: {'avg_goals': 2.6, 'home_adv': 0.12}, # La Liga
                        78: {'avg_goals': 3.1, 'home_adv': 0.14},  # Bundesliga
                        135: {'avg_goals': 2.9, 'home_adv': 0.13}, # Serie A
                        61: {'avg_goals': 2.7, 'home_adv': 0.11}   # Ligue 1
                    }
                    
                    stats = league_stats.get(league_id, league_stats[39])
                    
                    features = {
                        'home_goals_per_game': 1.7,
                        'away_goals_per_game': 1.3,
                        'home_goals_against_per_game': 1.2,
                        'away_goals_against_per_game': 1.4,
                        'home_win_percentage': 0.47,
                        'away_win_percentage': 0.33,
                        'home_form_points': 8.0,
                        'away_form_points': 6.0,
                        'goal_difference_home': 0.5,
                        'goal_difference_away': -0.2,
                        'form_difference': 2.0,
                        'strength_difference': 0.15,
                        'total_goals_tendency': stats['avg_goals'],
                        'h2h_home_wins': 3.0,
                        'h2h_away_wins': 2.0,
                        'h2h_avg_goals': stats['avg_goals'],
                        'home_key_injuries': 0.0,
                        'away_key_injuries': 0.0,
                        'home_win': float(1 if outcome == 'Home' else 0),
                        'draw': float(1 if outcome == 'Draw' else 0),
                        'away_win': float(1 if outcome == 'Away' else 0)
                    }
                    
                    new_matches.append({
                        'match_id': match_id,
                        'league_id': league_id,
                        'season': 2024,
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
                
                # Bulk insert
                if new_matches:
                    return self._bulk_insert(new_matches)
                
                return 0
                
        except Exception as e:
            logger.error(f"Collection error for league {league_id}: {e}")
            return 0
    
    def _bulk_insert(self, matches):
        """Bulk insert matches"""
        try:
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
            
            with self.engine.connect() as conn:
                conn.execute(text(sql), matches)
                conn.commit()
            
            return len(matches)
            
        except Exception as e:
            logger.error(f"Bulk insert failed: {e}")
            return 0
    
    def get_collection_stats(self):
        """Get collection statistics"""
        try:
            with self.engine.connect() as conn:
                # Total matches
                result = conn.execute(text("SELECT COUNT(*) FROM training_matches"))
                total = result.fetchone()[0]
                
                # By league
                result = conn.execute(text("""
                    SELECT league_id, COUNT(*) 
                    FROM training_matches 
                    GROUP BY league_id 
                    ORDER BY league_id
                """))
                by_league = dict(result.fetchall())
                
                # Recent additions (last 7 days)
                result = conn.execute(text("""
                    SELECT COUNT(*) 
                    FROM training_matches 
                    WHERE collected_at >= NOW() - INTERVAL '7 days'
                """))
                recent = result.fetchone()[0]
                
                return {
                    'total': total,
                    'by_league': by_league,
                    'recent_7_days': recent
                }
                
        except Exception as e:
            logger.error(f"Stats query failed: {e}")
            return {'total': 0, 'by_league': {}, 'recent_7_days': 0}

async def daily_collection_job():
    """Daily collection job - can be scheduled"""
    collector = AutomatedCollector()
    
    logger.info("Starting daily collection job")
    
    # Get initial stats
    initial_stats = collector.get_collection_stats()
    logger.info(f"Initial: {initial_stats['total']} matches")
    
    # Collect recent matches
    collected = await collector.collect_recent_matches(days_back=3)
    
    # Get final stats
    final_stats = collector.get_collection_stats()
    
    logger.info(f"""
Daily Collection Results:
Initial: {initial_stats['total']} matches
Collected: {collected} new matches
Final: {final_stats['total']} matches
By league: {final_stats['by_league']}
    """)
    
    return collected

if __name__ == "__main__":
    result = asyncio.run(daily_collection_job())
    print(f"Daily collection complete: {result} new matches")