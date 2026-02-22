"""
Team ELO Rating System

Computes and maintains ELO ratings for all teams based on match results.
Used by V0 Form-Only predictor for matches without odds data.

ELO Formula:
- K-factor: 32 (standard for sports)
- Home advantage: +100 ELO points
- Expected score: 1 / (1 + 10^((opponent_elo - team_elo) / 400))
- New ELO = Old ELO + K * (Actual - Expected)
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import os

logger = logging.getLogger(__name__)

K_FACTOR = 32
HOME_ADVANTAGE = 100
INITIAL_ELO = 1500


class TeamELOManager:
    """Manages team ELO ratings computation and storage."""
    
    def __init__(self):
        self.engine = create_engine(
            os.environ['DATABASE_URL'],
            pool_pre_ping=True,
            pool_size=3,
            max_overflow=2,
            pool_recycle=300,
            connect_args={'connect_timeout': 10}
        )
        self.Session = sessionmaker(bind=self.engine)
        self._ensure_tables()
    
    def _ensure_tables(self):
        """Create team_elo table if it doesn't exist."""
        with self.engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS team_elo (
                    team_id INTEGER PRIMARY KEY,
                    team_name VARCHAR(255),
                    league_id INTEGER,
                    elo_rating FLOAT DEFAULT 1500,
                    matches_played INTEGER DEFAULT 0,
                    wins INTEGER DEFAULT 0,
                    draws INTEGER DEFAULT 0,
                    losses INTEGER DEFAULT 0,
                    last_match_date TIMESTAMP,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    elo_history JSONB DEFAULT '[]'::jsonb
                );
                
                CREATE INDEX IF NOT EXISTS idx_team_elo_rating ON team_elo(elo_rating DESC);
                CREATE INDEX IF NOT EXISTS idx_team_elo_league ON team_elo(league_id);
            """))
            conn.commit()
            logger.info("Team ELO table ensured")
    
    def get_team_elo(self, team_id: int) -> float:
        """Get current ELO rating for a team."""
        with self.engine.connect() as conn:
            result = conn.execute(text("""
                SELECT elo_rating FROM team_elo WHERE team_id = :team_id
            """), {'team_id': team_id})
            row = result.fetchone()
            return float(row.elo_rating) if row else INITIAL_ELO
    
    def get_team_elos(self, team_ids: List[int]) -> Dict[int, float]:
        """Get ELO ratings for multiple teams."""
        if not team_ids:
            return {}
        
        with self.engine.connect() as conn:
            result = conn.execute(text("""
                SELECT team_id, elo_rating FROM team_elo 
                WHERE team_id = ANY(:team_ids)
            """), {'team_ids': team_ids})
            
            elos = {row.team_id: float(row.elo_rating) for row in result}
            for tid in team_ids:
                if tid not in elos:
                    elos[tid] = INITIAL_ELO
            return elos
    
    def calculate_expected_score(self, team_elo: float, opponent_elo: float, is_home: bool = False) -> float:
        """Calculate expected score (0-1) based on ELO difference."""
        if is_home:
            team_elo += HOME_ADVANTAGE
        
        elo_diff = opponent_elo - team_elo
        expected = 1.0 / (1.0 + 10 ** (elo_diff / 400.0))
        return expected
    
    def calculate_new_elo(self, old_elo: float, expected: float, actual: float) -> float:
        """Calculate new ELO after a match."""
        return old_elo + K_FACTOR * (actual - expected)
    
    def update_elos_from_match(self, 
                                home_team_id: int, 
                                away_team_id: int,
                                home_team_name: str,
                                away_team_name: str,
                                home_goals: int, 
                                away_goals: int,
                                match_date: datetime,
                                league_id: int = None) -> Tuple[float, float]:
        """
        Update ELO ratings after a match.
        Returns: (new_home_elo, new_away_elo)
        """
        home_elo = self.get_team_elo(home_team_id)
        away_elo = self.get_team_elo(away_team_id)
        
        home_expected = self.calculate_expected_score(home_elo, away_elo, is_home=True)
        away_expected = 1.0 - home_expected
        
        if home_goals > away_goals:
            home_actual, away_actual = 1.0, 0.0
            home_result, away_result = 'W', 'L'
        elif home_goals < away_goals:
            home_actual, away_actual = 0.0, 1.0
            home_result, away_result = 'L', 'W'
        else:
            home_actual, away_actual = 0.5, 0.5
            home_result, away_result = 'D', 'D'
        
        new_home_elo = self.calculate_new_elo(home_elo, home_expected, home_actual)
        new_away_elo = self.calculate_new_elo(away_elo, away_expected, away_actual)
        
        self._save_team_elo(home_team_id, home_team_name, new_home_elo, 
                          home_result, match_date, league_id)
        self._save_team_elo(away_team_id, away_team_name, new_away_elo,
                          away_result, match_date, league_id)
        
        return new_home_elo, new_away_elo
    
    def _save_team_elo(self, team_id: int, team_name: str, new_elo: float,
                       result: str, match_date: datetime, league_id: int = None):
        """Save updated ELO to database."""
        with self.engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO team_elo (team_id, team_name, league_id, elo_rating, 
                    matches_played, wins, draws, losses, last_match_date, last_updated)
                VALUES (:team_id, :team_name, :league_id, :elo, 1,
                    CASE WHEN :result = 'W' THEN 1 ELSE 0 END,
                    CASE WHEN :result = 'D' THEN 1 ELSE 0 END,
                    CASE WHEN :result = 'L' THEN 1 ELSE 0 END,
                    :match_date, CURRENT_TIMESTAMP)
                ON CONFLICT (team_id) DO UPDATE SET
                    team_name = COALESCE(EXCLUDED.team_name, team_elo.team_name),
                    league_id = COALESCE(EXCLUDED.league_id, team_elo.league_id),
                    elo_rating = :elo,
                    matches_played = team_elo.matches_played + 1,
                    wins = team_elo.wins + CASE WHEN :result = 'W' THEN 1 ELSE 0 END,
                    draws = team_elo.draws + CASE WHEN :result = 'D' THEN 1 ELSE 0 END,
                    losses = team_elo.losses + CASE WHEN :result = 'L' THEN 1 ELSE 0 END,
                    last_match_date = :match_date,
                    last_updated = CURRENT_TIMESTAMP
            """), {
                'team_id': team_id,
                'team_name': team_name,
                'league_id': league_id,
                'elo': new_elo,
                'result': result,
                'match_date': match_date
            })
            conn.commit()
    
    def compute_all_elos_from_history(self, reset: bool = False) -> Dict[str, int]:
        """
        Compute ELO ratings from all historical matches.
        Processes matches chronologically to build accurate ratings.
        Uses in-memory computation for speed, then bulk saves at end.
        
        Returns: {'matches_processed': N, 'teams_updated': M}
        """
        if reset:
            with self.engine.connect() as conn:
                conn.execute(text("TRUNCATE TABLE team_elo"))
                conn.commit()
                logger.info("Reset all ELO ratings")
        
        team_elos = {}
        team_stats = {}
        
        with self.engine.connect() as conn:
            result = conn.execute(text("""
                SELECT 
                    f.match_id, f.home_team, f.away_team,
                    f.home_team_id, f.away_team_id,
                    f.league_id, f.kickoff_at,
                    m.home_goals, m.away_goals
                FROM fixtures f
                JOIN matches m ON f.match_id = m.match_id
                WHERE f.status = 'finished'
                AND f.home_team_id IS NOT NULL 
                AND f.away_team_id IS NOT NULL
                AND m.home_goals IS NOT NULL
                ORDER BY f.kickoff_at ASC
            """))
            
            matches = list(result)
            logger.info(f"Processing {len(matches)} matches for ELO computation...")
            
            matches_processed = 0
            for row in matches:
                try:
                    home_id, away_id = row.home_team_id, row.away_team_id
                    
                    home_elo = team_elos.get(home_id, INITIAL_ELO)
                    away_elo = team_elos.get(away_id, INITIAL_ELO)
                    
                    home_expected = self.calculate_expected_score(home_elo, away_elo, is_home=True)
                    
                    if row.home_goals > row.away_goals:
                        home_actual, away_actual = 1.0, 0.0
                        home_result, away_result = 'W', 'L'
                    elif row.home_goals < row.away_goals:
                        home_actual, away_actual = 0.0, 1.0
                        home_result, away_result = 'L', 'W'
                    else:
                        home_actual, away_actual = 0.5, 0.5
                        home_result, away_result = 'D', 'D'
                    
                    new_home_elo = self.calculate_new_elo(home_elo, home_expected, home_actual)
                    new_away_elo = self.calculate_new_elo(away_elo, 1 - home_expected, away_actual)
                    
                    team_elos[home_id] = new_home_elo
                    team_elos[away_id] = new_away_elo
                    
                    for tid, name, lid, result, match_date in [
                        (home_id, row.home_team, row.league_id, home_result, row.kickoff_at),
                        (away_id, row.away_team, row.league_id, away_result, row.kickoff_at)
                    ]:
                        if tid not in team_stats:
                            team_stats[tid] = {
                                'name': name, 'league_id': lid,
                                'matches': 0, 'wins': 0, 'draws': 0, 'losses': 0,
                                'last_match': match_date
                            }
                        team_stats[tid]['matches'] += 1
                        if result == 'W': team_stats[tid]['wins'] += 1
                        elif result == 'D': team_stats[tid]['draws'] += 1
                        else: team_stats[tid]['losses'] += 1
                        team_stats[tid]['last_match'] = match_date
                    
                    matches_processed += 1
                    if matches_processed % 500 == 0:
                        logger.info(f"  Processed {matches_processed}/{len(matches)} matches...")
                        
                except Exception as e:
                    logger.warning(f"Error processing match {row.match_id}: {e}")
                    continue
        
        logger.info(f"Bulk saving {len(team_elos)} team ELO ratings...")
        with self.engine.connect() as conn:
            for tid, elo in team_elos.items():
                stats = team_stats.get(tid, {})
                conn.execute(text("""
                    INSERT INTO team_elo (team_id, team_name, league_id, elo_rating, 
                        matches_played, wins, draws, losses, last_match_date, last_updated)
                    VALUES (:tid, :name, :lid, :elo, :matches, :wins, :draws, :losses, :last_match, CURRENT_TIMESTAMP)
                    ON CONFLICT (team_id) DO UPDATE SET
                        team_name = EXCLUDED.team_name,
                        league_id = EXCLUDED.league_id,
                        elo_rating = EXCLUDED.elo_rating,
                        matches_played = EXCLUDED.matches_played,
                        wins = EXCLUDED.wins,
                        draws = EXCLUDED.draws,
                        losses = EXCLUDED.losses,
                        last_match_date = EXCLUDED.last_match_date,
                        last_updated = CURRENT_TIMESTAMP
                """), {
                    'tid': tid, 'name': stats.get('name'), 'lid': stats.get('league_id'),
                    'elo': elo, 'matches': stats.get('matches', 0),
                    'wins': stats.get('wins', 0), 'draws': stats.get('draws', 0),
                    'losses': stats.get('losses', 0), 'last_match': stats.get('last_match')
                })
            conn.commit()
        
        logger.info(f"Computed ELO from {matches_processed} matches, {len(team_elos)} teams")
        return {
            'matches_processed': matches_processed,
            'teams_updated': len(team_elos)
        }
    
    def update_elos_since(self, since_date: datetime) -> int:
        """Update ELOs for matches since a given date (for incremental updates)."""
        with self.engine.connect() as conn:
            result = conn.execute(text("""
                SELECT 
                    f.match_id, f.home_team, f.away_team,
                    f.home_team_id, f.away_team_id,
                    f.league_id, f.kickoff_at,
                    m.home_goals, m.away_goals
                FROM fixtures f
                JOIN matches m ON f.match_id = m.match_id
                WHERE f.status = 'finished'
                AND f.home_team_id IS NOT NULL 
                AND f.away_team_id IS NOT NULL
                AND m.home_goals IS NOT NULL
                AND f.kickoff_at >= :since_date
                AND NOT EXISTS (
                    SELECT 1 FROM team_elo te 
                    WHERE te.team_id = f.home_team_id 
                    AND te.last_match_date >= f.kickoff_at
                )
                ORDER BY f.kickoff_at ASC
            """), {'since_date': since_date})
            
            count = 0
            for row in result:
                try:
                    self.update_elos_from_match(
                        home_team_id=row.home_team_id,
                        away_team_id=row.away_team_id,
                        home_team_name=row.home_team,
                        away_team_name=row.away_team,
                        home_goals=row.home_goals,
                        away_goals=row.away_goals,
                        match_date=row.kickoff_at,
                        league_id=row.league_id
                    )
                    count += 1
                except Exception as e:
                    logger.warning(f"Error updating match {row.match_id}: {e}")
            
            return count
    
    def get_elo_stats(self) -> Dict:
        """Get summary statistics about ELO ratings."""
        with self.engine.connect() as conn:
            result = conn.execute(text("""
                SELECT 
                    COUNT(*) as total_teams,
                    AVG(elo_rating) as avg_elo,
                    MIN(elo_rating) as min_elo,
                    MAX(elo_rating) as max_elo,
                    SUM(matches_played) as total_matches_processed
                FROM team_elo
            """))
            row = result.fetchone()
            
            top_teams = conn.execute(text("""
                SELECT team_name, elo_rating, matches_played
                FROM team_elo
                ORDER BY elo_rating DESC
                LIMIT 10
            """))
            
            return {
                'total_teams': row.total_teams or 0,
                'avg_elo': round(float(row.avg_elo or 1500), 1),
                'min_elo': round(float(row.min_elo or 1500), 1),
                'max_elo': round(float(row.max_elo or 1500), 1),
                'total_matches_processed': row.total_matches_processed or 0,
                'top_teams': [
                    {'name': r.team_name, 'elo': round(r.elo_rating, 1), 'matches': r.matches_played}
                    for r in top_teams
                ]
            }


def compute_initial_elos():
    """Compute ELO ratings from all historical data."""
    manager = TeamELOManager()
    result = manager.compute_all_elos_from_history(reset=True)
    print(f"Computed ELO for {result['matches_processed']} matches, {result['teams_updated']} teams")
    
    stats = manager.get_elo_stats()
    print(f"\nELO Statistics:")
    print(f"  Total teams: {stats['total_teams']}")
    print(f"  Average ELO: {stats['avg_elo']}")
    print(f"  ELO range: {stats['min_elo']} - {stats['max_elo']}")
    print(f"\nTop 10 Teams:")
    for t in stats['top_teams']:
        print(f"  {t['name']}: {t['elo']} ({t['matches']} matches)")
    
    return stats


if __name__ == "__main__":
    compute_initial_elos()
