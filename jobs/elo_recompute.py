"""
ELO Rating System for Football Teams

Computes and maintains rolling ELO ratings with:
- League-specific home advantage
- K-factor adjustments for match importance
- Daily snapshots for point-in-time lookups

Author: BetGenius AI Team
Date: Oct 2025
"""

import os
import sys
import psycopg2
import numpy as np
from datetime import datetime, timedelta, date
from typing import Dict, Tuple
from collections import defaultdict

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from models.database import DatabaseManager


# ELO Configuration
INITIAL_ELO = 1500.0
K_BASE = 20.0
K_CUP_BONUS = 5.0  # Extra K for cups/tournaments
HOME_ADVANTAGE = {
    'default': 100.0,
    'Premier League': 90.0,
    'La Liga': 85.0,
    'Bundesliga': 95.0,
    'Serie A': 80.0,
    'Ligue 1': 85.0,
}


def get_home_advantage(league: str) -> float:
    """Get home advantage for league"""
    return HOME_ADVANTAGE.get(league, HOME_ADVANTAGE['default'])


def expected_score(elo_a: float, elo_b: float) -> float:
    """
    Calculate expected score for team A.
    Returns probability in [0,1].
    """
    return 1.0 / (1.0 + 10 ** ((elo_b - elo_a) / 400.0))


def update_elo(
    elo_winner: float,
    elo_loser: float,
    k_factor: float,
    is_draw: bool = False
) -> Tuple[float, float]:
    """
    Update ELO ratings after a match.
    
    Args:
        elo_winner: Current ELO of winning team (or team1 if draw)
        elo_loser: Current ELO of losing team (or team2 if draw)
        k_factor: K-factor for this match
        is_draw: Whether the match was a draw
    
    Returns:
        (new_elo_winner, new_elo_loser)
    """
    expected_win = expected_score(elo_winner, elo_loser)
    
    if is_draw:
        # Both teams get 0.5 points
        actual_score = 0.5
        delta = k_factor * (actual_score - expected_win)
        return elo_winner + delta, elo_loser - delta
    else:
        # Winner gets 1, loser gets 0
        delta = k_factor * (1.0 - expected_win)
        return elo_winner + delta, elo_loser - delta


class ELOSystem:
    """Manages ELO ratings for all teams"""
    
    def __init__(self):
        self.ratings = {}  # (team_id, venue) -> elo
        self.team_names = {}  # team_id -> team_name
        self.match_counts = {}  # team_id -> count
        self.history = []  # List of (date, team_id, elo_home, elo_away, elo_neutral)
    
    def get_rating(self, team_id: int, venue: str = 'neutral') -> float:
        """Get current ELO rating for team at venue"""
        key = (team_id, venue)
        if key not in self.ratings:
            self.ratings[(team_id, 'home')] = INITIAL_ELO
            self.ratings[(team_id, 'away')] = INITIAL_ELO
            self.ratings[(team_id, 'neutral')] = INITIAL_ELO
            self.match_counts[team_id] = 0
        return self.ratings[key]
    
    def process_match(
        self,
        match_date: date,
        home_team_id: int,
        away_team_id: int,
        outcome: str,
        league: str
    ):
        """
        Process a single match and update ELO ratings.
        
        Args:
            match_date: Date of match
            home_team_id: Home team ID
            away_team_id: Away team ID
            outcome: 'H', 'D', or 'A'
            league: League name for home advantage
        """
        # Get current ratings
        home_elo = self.get_rating(home_team_id, 'home')
        away_elo = self.get_rating(away_team_id, 'away')
        
        # Apply home advantage
        home_adv = get_home_advantage(league)
        home_elo_adj = home_elo + home_adv
        
        # Determine K-factor (could add cup bonus later)
        k_factor = K_BASE
        
        # Update based on outcome
        if outcome == 'H':
            new_home, new_away = update_elo(home_elo_adj, away_elo, k_factor, is_draw=False)
            new_home -= home_adv  # Remove home advantage from update
        elif outcome == 'A':
            new_away, new_home = update_elo(away_elo, home_elo_adj, k_factor, is_draw=False)
            new_home -= home_adv
        else:  # Draw
            new_home, new_away = update_elo(home_elo_adj, away_elo, k_factor, is_draw=True)
            new_home -= home_adv
        
        # Update ratings
        self.ratings[(home_team_id, 'home')] = new_home
        self.ratings[(away_team_id, 'away')] = new_away
        
        # Update neutral ratings (average of home/away)
        self.ratings[(home_team_id, 'neutral')] = (new_home + self.get_rating(home_team_id, 'away')) / 2
        self.ratings[(away_team_id, 'neutral')] = (new_away + self.get_rating(away_team_id, 'home')) / 2
        
        # Increment match counts
        self.match_counts[home_team_id] = self.match_counts.get(home_team_id, 0) + 1
        self.match_counts[away_team_id] = self.match_counts.get(away_team_id, 0) + 1
        
        # Record snapshot
        self.history.append((
            match_date,
            home_team_id,
            self.ratings[(home_team_id, 'home')],
            self.ratings[(home_team_id, 'away')],
            self.ratings[(home_team_id, 'neutral')]
        ))
        self.history.append((
            match_date,
            away_team_id,
            self.ratings[(away_team_id, 'home')],
            self.ratings[(away_team_id, 'away')],
            self.ratings[(away_team_id, 'neutral')]
        ))
    
    def get_history(self):
        """Get all ELO history snapshots"""
        return self.history


def rebuild_elo_ratings(since_date: str = None):
    """
    Rebuild all ELO ratings from scratch by replaying historical matches.
    
    Args:
        since_date: Optional cutoff (YYYY-MM-DD). Only process matches after this date.
    """
    print("=" * 70)
    print("ELO RATING SYSTEM - REBUILD")
    print("=" * 70)
    
    db_manager = DatabaseManager()
    conn = psycopg2.connect(db_manager.database_url)
    cursor = conn.cursor()
    
    # Fetch all historical matches with results
    # Use training_matches which has canonical team IDs
    print(f"📊 Fetching historical matches...")
    
    if since_date:
        sql = """
            SELECT 
                tm.match_date::date as match_date,
                tm.home_team_id,
                tm.away_team_id,
                tm.home_team,
                tm.away_team,
                mr.outcome,
                COALESCE(mr.league, 'Unknown') as league
            FROM training_matches tm
            INNER JOIN match_results mr ON tm.match_id = mr.match_id
            WHERE tm.match_date IS NOT NULL
              AND tm.match_date >= %s
              AND tm.home_team_id IS NOT NULL
              AND tm.away_team_id IS NOT NULL
              AND mr.outcome IS NOT NULL
            ORDER BY tm.match_date, tm.match_id
        """
        cursor.execute(sql, (since_date,))
    else:
        sql = """
            SELECT 
                tm.match_date::date as match_date,
                tm.home_team_id,
                tm.away_team_id,
                tm.home_team,
                tm.away_team,
                mr.outcome,
                COALESCE(mr.league, 'Unknown') as league
            FROM training_matches tm
            INNER JOIN match_results mr ON tm.match_id = mr.match_id
            WHERE tm.match_date IS NOT NULL
              AND tm.home_team_id IS NOT NULL
              AND tm.away_team_id IS NOT NULL
              AND mr.outcome IS NOT NULL
            ORDER BY tm.match_date, tm.match_id
        """
        cursor.execute(sql)
    
    matches = cursor.fetchall()
    print(f"   Found {len(matches)} historical matches with results")
    
    if len(matches) == 0:
        print("❌ No matches found. Cannot compute ELO ratings.")
        cursor.close()
        conn.close()
        return
    
    # Initialize ELO system
    elo_system = ELOSystem()
    
    # Store team names
    for row in matches:
        home_id, away_id = row[1], row[2]
        home_name, away_name = row[3], row[4]
        elo_system.team_names[home_id] = home_name
        elo_system.team_names[away_id] = away_name
    
    # Process matches chronologically
    print(f"🔄 Processing {len(matches)} matches chronologically...")
    for i, row in enumerate(matches, 1):
        match_date, home_id, away_id, home_name, away_name, outcome, league = row
        
        elo_system.process_match(
            match_date=match_date,
            home_team_id=home_id,
            away_team_id=away_id,
            outcome=outcome,
            league=league
        )
        
        if i % 500 == 0:
            print(f"   Processed {i}/{len(matches)} matches...")
    
    print(f"✅ Processed {len(matches)} matches")
    
    # Get all history
    history = elo_system.get_history()
    print(f"📝 Generated {len(history)} ELO snapshots")
    
    # Clear existing ELO ratings
    print(f"🗑️  Clearing existing ELO ratings...")
    cursor.execute("DELETE FROM elo_ratings")
    conn.commit()
    
    # Insert new ratings
    print(f"💾 Inserting {len(history)} ELO snapshots...")
    
    batch_size = 1000
    for i in range(0, len(history), batch_size):
        batch = history[i:i+batch_size]
        
        insert_sql = """
            INSERT INTO elo_ratings (
                as_of_date, team_id, team_name,
                elo_home, elo_away, elo_neutral,
                matches_played
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (team_id, as_of_date) DO UPDATE SET
                elo_home = EXCLUDED.elo_home,
                elo_away = EXCLUDED.elo_away,
                elo_neutral = EXCLUDED.elo_neutral,
                matches_played = EXCLUDED.matches_played
        """
        
        values = [
            (
                snap_date,
                team_id,
                elo_system.team_names.get(team_id, f'Team {team_id}'),
                elo_home,
                elo_away,
                elo_neutral,
                elo_system.match_counts.get(team_id, 0)
            )
            for snap_date, team_id, elo_home, elo_away, elo_neutral in batch
        ]
        
        cursor.executemany(insert_sql, values)
        conn.commit()
        
        if (i + batch_size) % 5000 == 0:
            print(f"   Inserted {min(i+batch_size, len(history))}/{len(history)}...")
    
    print(f"✅ Inserted all ELO snapshots")
    
    # Show statistics
    cursor.execute("""
        SELECT 
            COUNT(DISTINCT team_id) as num_teams,
            AVG(elo_neutral) as avg_elo,
            STDDEV(elo_neutral) as std_elo,
            MIN(elo_neutral) as min_elo,
            MAX(elo_neutral) as max_elo
        FROM elo_ratings
        WHERE as_of_date = (SELECT MAX(as_of_date) FROM elo_ratings)
    """)
    
    stats = cursor.fetchone()
    print("\n" + "=" * 70)
    print("📊 ELO RATINGS SUMMARY (Latest Snapshot):")
    print(f"   Teams rated: {stats[0]}")
    print(f"   Mean ELO: {stats[1]:.1f}")
    print(f"   StdDev: {stats[2]:.1f}")
    print(f"   Range: [{stats[3]:.1f}, {stats[4]:.1f}]")
    print("=" * 70)
    
    cursor.close()
    conn.close()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Rebuild ELO ratings from historical matches')
    parser.add_argument('--since', type=str, help='Only process matches since date (YYYY-MM-DD)')
    
    args = parser.parse_args()
    
    rebuild_elo_ratings(since_date=args.since)
