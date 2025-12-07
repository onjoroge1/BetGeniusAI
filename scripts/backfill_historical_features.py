#!/usr/bin/env python3
"""
Backfill Historical Features from historical_odds Table

This script populates historical_features table with H2H and form data
derived from the historical_odds dataset (22,335+ matches since 2020).

Features computed:
- H2H: home_wins, draws, away_wins (from past 10 meetings)
- Form: points, goals scored/conceded (from last 5 matches)
- Advanced stats: shots, corners, yellows averages (from last 10 matches)

Usage:
    python scripts/backfill_historical_features.py [--dry-run] [--league LEAGUE_CODE]

"""

import os
import sys
import argparse
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import psycopg2
from psycopg2.extras import execute_values, RealDictCursor

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get('DATABASE_URL')

class HistoricalFeaturesBackfill:
    """Backfill H2H, form, and advanced stats from historical_odds table."""
    
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.conn = None
        self.team_mapping = {}  # historical_name -> api_football_team_id
        self.reverse_mapping = {}  # api_football_team_id -> historical_name
        self.league_mapping = {}  # api_football_league_id -> historical_code
        
    def connect(self):
        """Establish database connection."""
        self.conn = psycopg2.connect(DATABASE_URL)
        logger.info("Connected to database")
        
    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()
            
    def load_mappings(self):
        """Load team and league mappings from mapping tables."""
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Load team mappings
            cur.execute("""
                SELECT historical_name, historical_league, api_football_team_id, api_football_name
                FROM team_name_mapping
            """)
            for row in cur.fetchall():
                key = (row['historical_name'], row['historical_league'])
                self.team_mapping[key] = row['api_football_team_id']
                # Reverse mapping: team_id -> (historical_name, league_code)
                self.reverse_mapping[row['api_football_team_id']] = (row['historical_name'], row['historical_league'])
            
            # Load league mappings
            cur.execute("""
                SELECT historical_code, api_football_league_id
                FROM league_code_mapping
            """)
            for row in cur.fetchall():
                self.league_mapping[row['api_football_league_id']] = row['historical_code']
                
        logger.info(f"Loaded {len(self.team_mapping)} team mappings, {len(self.league_mapping)} league mappings")
        
    def get_fixtures_to_process(self, league_code: Optional[str] = None) -> List[Dict]:
        """Get fixtures from major leagues that need historical features."""
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Get fixtures from mapped leagues
            league_ids = list(self.league_mapping.keys())
            
            if league_code:
                # Filter to specific league
                league_ids = [lid for lid, code in self.league_mapping.items() if code == league_code]
                
            placeholders = ','.join(['%s'] * len(league_ids))
            cur.execute(f"""
                SELECT f.match_id, f.home_team_id, f.away_team_id, f.league_id, 
                       f.kickoff_at, f.home_team, f.away_team,
                       th.name as home_name, ta.name as away_name
                FROM fixtures f
                LEFT JOIN teams th ON f.home_team_id = th.team_id
                LEFT JOIN teams ta ON f.away_team_id = ta.team_id
                WHERE f.league_id IN ({placeholders})
                  AND f.kickoff_at >= '2020-01-01'
                  AND NOT EXISTS (
                      SELECT 1 FROM historical_features hf 
                      WHERE hf.match_id = f.match_id AND hf.feature_type = 'combined'
                  )
                ORDER BY f.kickoff_at
            """, league_ids)
            
            fixtures = cur.fetchall()
            logger.info(f"Found {len(fixtures)} fixtures to process")
            return fixtures
            
    def lookup_historical_team(self, team_id: int, league_id: int) -> Optional[str]:
        """Map API-Football team_id to historical_odds team name."""
        league_code = self.league_mapping.get(league_id)
        if not league_code:
            return None
            
        if team_id in self.reverse_mapping:
            hist_name, hist_league = self.reverse_mapping[team_id]
            if hist_league == league_code:
                return hist_name
        return None
        
    def compute_h2h_features(self, home_team: str, away_team: str, league: str, 
                              before_date: datetime, limit: int = 10) -> Dict:
        """Compute H2H features from historical_odds."""
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT home_team, away_team, home_goals, away_goals, result
                FROM historical_odds
                WHERE league = %s
                  AND ((home_team = %s AND away_team = %s) OR (home_team = %s AND away_team = %s))
                  AND match_date < %s
                ORDER BY match_date DESC
                LIMIT %s
            """, (league, home_team, away_team, away_team, home_team, before_date.date(), limit))
            
            matches = cur.fetchall()
            
        if not matches:
            return {
                'h2h_home_wins': None,
                'h2h_draws': None,
                'h2h_away_wins': None,
                'h2h_matches_used': 0
            }
            
        home_wins = 0
        draws = 0
        away_wins = 0
        
        for m in matches:
            if m['home_team'] == home_team:
                # Match is in same direction
                if m['result'] == 'H':
                    home_wins += 1
                elif m['result'] == 'D':
                    draws += 1
                else:
                    away_wins += 1
            else:
                # Match is reversed (away team was at home)
                if m['result'] == 'H':
                    away_wins += 1
                elif m['result'] == 'D':
                    draws += 1
                else:
                    home_wins += 1
                    
        return {
            'h2h_home_wins': home_wins,
            'h2h_draws': draws,
            'h2h_away_wins': away_wins,
            'h2h_matches_used': len(matches)
        }
        
    def compute_form_features(self, team: str, league: str, is_home: bool,
                               before_date: datetime, limit: int = 5) -> Dict:
        """Compute form features from historical_odds."""
        prefix = 'home' if is_home else 'away'
        
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Get last N matches for this team (any venue)
            cur.execute("""
                SELECT home_team, away_team, home_goals, away_goals, result
                FROM historical_odds
                WHERE league = %s
                  AND (home_team = %s OR away_team = %s)
                  AND match_date < %s
                ORDER BY match_date DESC
                LIMIT %s
            """, (league, team, team, before_date.date(), limit))
            
            matches = cur.fetchall()
            
        if not matches:
            return {
                f'{prefix}_form_points': None,
                f'{prefix}_form_goals_scored': None,
                f'{prefix}_form_goals_conceded': None,
                f'{prefix}_matches_used': 0
            }
            
        points = 0
        goals_scored = 0
        goals_conceded = 0
        
        for m in matches:
            if m['home_team'] == team:
                goals_scored += m['home_goals'] or 0
                goals_conceded += m['away_goals'] or 0
                if m['result'] == 'H':
                    points += 3
                elif m['result'] == 'D':
                    points += 1
            else:
                goals_scored += m['away_goals'] or 0
                goals_conceded += m['home_goals'] or 0
                if m['result'] == 'A':
                    points += 3
                elif m['result'] == 'D':
                    points += 1
                    
        return {
            f'{prefix}_form_points': points,
            f'{prefix}_form_goals_scored': goals_scored,
            f'{prefix}_form_goals_conceded': goals_conceded,
            f'{prefix}_matches_used': len(matches)
        }
        
    def compute_venue_form(self, team: str, league: str, is_home: bool,
                           before_date: datetime, limit: int = 10) -> Dict:
        """Compute venue-specific form (home wins at home, away wins at away)."""
        prefix = 'home' if is_home else 'away'
        
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            if is_home:
                # Get home matches
                cur.execute("""
                    SELECT result
                    FROM historical_odds
                    WHERE league = %s AND home_team = %s AND match_date < %s
                    ORDER BY match_date DESC
                    LIMIT %s
                """, (league, team, before_date.date(), limit))
                matches = cur.fetchall()
                wins = sum(1 for m in matches if m['result'] == 'H')
            else:
                # Get away matches
                cur.execute("""
                    SELECT result
                    FROM historical_odds
                    WHERE league = %s AND away_team = %s AND match_date < %s
                    ORDER BY match_date DESC
                    LIMIT %s
                """, (league, team, before_date.date(), limit))
                matches = cur.fetchall()
                wins = sum(1 for m in matches if m['result'] == 'A')
                
        if not matches:
            return {f'{prefix}_last10_{prefix}_wins': None}
            
        return {f'{prefix}_last10_{prefix}_wins': wins}
        
    def compute_advanced_stats(self, team: str, league: str, is_home: bool,
                                before_date: datetime, limit: int = 10) -> Dict:
        """Compute advanced stats averages from historical_odds."""
        prefix = 'home' if is_home else 'away'
        
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT home_team, away_team, 
                       home_shots, away_shots,
                       home_shots_target, away_shots_target,
                       home_corners, away_corners,
                       home_yellows, away_yellows
                FROM historical_odds
                WHERE league = %s
                  AND (home_team = %s OR away_team = %s)
                  AND match_date < %s
                  AND home_shots IS NOT NULL
                ORDER BY match_date DESC
                LIMIT %s
            """, (league, team, team, before_date.date(), limit))
            
            matches = cur.fetchall()
            
        if not matches:
            return {
                f'{prefix}_shots_avg': None,
                f'{prefix}_shots_target_avg': None,
                f'{prefix}_corners_avg': None,
                f'{prefix}_yellows_avg': None
            }
            
        shots = []
        shots_target = []
        corners = []
        yellows = []
        
        for m in matches:
            if m['home_team'] == team:
                if m['home_shots'] is not None:
                    shots.append(m['home_shots'])
                if m['home_shots_target'] is not None:
                    shots_target.append(m['home_shots_target'])
                if m['home_corners'] is not None:
                    corners.append(m['home_corners'])
                if m['home_yellows'] is not None:
                    yellows.append(m['home_yellows'])
            else:
                if m['away_shots'] is not None:
                    shots.append(m['away_shots'])
                if m['away_shots_target'] is not None:
                    shots_target.append(m['away_shots_target'])
                if m['away_corners'] is not None:
                    corners.append(m['away_corners'])
                if m['away_yellows'] is not None:
                    yellows.append(m['away_yellows'])
                    
        return {
            f'{prefix}_shots_avg': sum(shots) / len(shots) if shots else None,
            f'{prefix}_shots_target_avg': sum(shots_target) / len(shots_target) if shots_target else None,
            f'{prefix}_corners_avg': sum(corners) / len(corners) if corners else None,
            f'{prefix}_yellows_avg': sum(yellows) / len(yellows) if yellows else None
        }
        
    def process_fixture(self, fixture: Dict) -> Optional[Dict]:
        """Process a single fixture and compute all historical features."""
        match_id = fixture['match_id']
        home_team_id = fixture['home_team_id']
        away_team_id = fixture['away_team_id']
        league_id = fixture['league_id']
        kickoff_at = fixture['kickoff_at']
        
        # Map to historical team names
        league_code = self.league_mapping.get(league_id)
        if not league_code:
            return None
            
        home_hist = self.lookup_historical_team(home_team_id, league_id)
        away_hist = self.lookup_historical_team(away_team_id, league_id)
        
        if not home_hist or not away_hist:
            # Try direct team name match
            if fixture['home_team']:
                # Check if fixture home_team matches any historical name
                for (hist_name, hist_league), team_id in self.team_mapping.items():
                    if hist_league == league_code:
                        if hist_name.lower() == fixture['home_team'].lower():
                            home_hist = hist_name
                        if hist_name.lower() == fixture['away_team'].lower():
                            away_hist = hist_name
                            
        if not home_hist or not away_hist:
            return None
            
        # Compute all features
        features = {'match_id': match_id, 'feature_type': 'combined'}
        
        # H2H features
        h2h = self.compute_h2h_features(home_hist, away_hist, league_code, kickoff_at)
        features.update(h2h)
        
        # Form features for home team
        home_form = self.compute_form_features(home_hist, league_code, True, kickoff_at)
        features.update(home_form)
        
        # Form features for away team  
        away_form = self.compute_form_features(away_hist, league_code, False, kickoff_at)
        features.update(away_form)
        
        # Venue-specific form
        home_venue = self.compute_venue_form(home_hist, league_code, True, kickoff_at)
        features.update(home_venue)
        away_venue = self.compute_venue_form(away_hist, league_code, False, kickoff_at)
        features.update(away_venue)
        
        # Advanced stats
        home_stats = self.compute_advanced_stats(home_hist, league_code, True, kickoff_at)
        features.update(home_stats)
        away_stats = self.compute_advanced_stats(away_hist, league_code, False, kickoff_at)
        features.update(away_stats)
        
        return features
        
    def insert_features(self, features_list: List[Dict]):
        """Batch insert features into historical_features table."""
        if not features_list or self.dry_run:
            return
            
        with self.conn.cursor() as cur:
            columns = [
                'match_id', 'feature_type',
                'h2h_home_wins', 'h2h_draws', 'h2h_away_wins', 'h2h_matches_used',
                'home_form_points', 'home_form_goals_scored', 'home_form_goals_conceded',
                'away_form_points', 'away_form_goals_scored', 'away_form_goals_conceded',
                'home_last10_home_wins', 'away_last10_away_wins',
                'home_shots_avg', 'away_shots_avg',
                'home_shots_target_avg', 'away_shots_target_avg',
                'home_corners_avg', 'away_corners_avg',
                'home_yellows_avg', 'away_yellows_avg',
                'matches_used_home', 'matches_used_away'
            ]
            
            values = []
            for f in features_list:
                row = (
                    f.get('match_id'),
                    f.get('feature_type'),
                    f.get('h2h_home_wins'),
                    f.get('h2h_draws'),
                    f.get('h2h_away_wins'),
                    f.get('h2h_matches_used'),
                    f.get('home_form_points'),
                    f.get('home_form_goals_scored'),
                    f.get('home_form_goals_conceded'),
                    f.get('away_form_points'),
                    f.get('away_form_goals_scored'),
                    f.get('away_form_goals_conceded'),
                    f.get('home_last10_home_wins'),
                    f.get('away_last10_away_wins'),
                    f.get('home_shots_avg'),
                    f.get('away_shots_avg'),
                    f.get('home_shots_target_avg'),
                    f.get('away_shots_target_avg'),
                    f.get('home_corners_avg'),
                    f.get('away_corners_avg'),
                    f.get('home_yellows_avg'),
                    f.get('away_yellows_avg'),
                    f.get('home_matches_used'),
                    f.get('away_matches_used')
                )
                values.append(row)
                
            sql = f"""
                INSERT INTO historical_features ({', '.join(columns)})
                VALUES %s
                ON CONFLICT (match_id, feature_type) DO UPDATE SET
                    h2h_home_wins = EXCLUDED.h2h_home_wins,
                    h2h_draws = EXCLUDED.h2h_draws,
                    h2h_away_wins = EXCLUDED.h2h_away_wins,
                    h2h_matches_used = EXCLUDED.h2h_matches_used,
                    home_form_points = EXCLUDED.home_form_points,
                    home_form_goals_scored = EXCLUDED.home_form_goals_scored,
                    home_form_goals_conceded = EXCLUDED.home_form_goals_conceded,
                    away_form_points = EXCLUDED.away_form_points,
                    away_form_goals_scored = EXCLUDED.away_form_goals_scored,
                    away_form_goals_conceded = EXCLUDED.away_form_goals_conceded,
                    home_last10_home_wins = EXCLUDED.home_last10_home_wins,
                    away_last10_away_wins = EXCLUDED.away_last10_away_wins,
                    home_shots_avg = EXCLUDED.home_shots_avg,
                    away_shots_avg = EXCLUDED.away_shots_avg,
                    home_shots_target_avg = EXCLUDED.home_shots_target_avg,
                    away_shots_target_avg = EXCLUDED.away_shots_target_avg,
                    home_corners_avg = EXCLUDED.home_corners_avg,
                    away_corners_avg = EXCLUDED.away_corners_avg,
                    home_yellows_avg = EXCLUDED.home_yellows_avg,
                    away_yellows_avg = EXCLUDED.away_yellows_avg,
                    matches_used_home = EXCLUDED.matches_used_home,
                    matches_used_away = EXCLUDED.matches_used_away
            """
            
            execute_values(cur, sql, values)
            self.conn.commit()
            
    def run(self, league_code: Optional[str] = None, batch_size: int = 100):
        """Run the backfill process."""
        try:
            self.connect()
            self.load_mappings()
            
            fixtures = self.get_fixtures_to_process(league_code)
            
            if not fixtures:
                logger.info("No fixtures to process")
                return
                
            processed = 0
            skipped = 0
            features_batch = []
            
            for i, fixture in enumerate(fixtures):
                features = self.process_fixture(fixture)
                
                if features:
                    features_batch.append(features)
                    processed += 1
                else:
                    skipped += 1
                    
                # Batch insert
                if len(features_batch) >= batch_size:
                    self.insert_features(features_batch)
                    logger.info(f"Processed {processed} fixtures, skipped {skipped}")
                    features_batch = []
                    
                # Progress update
                if (i + 1) % 500 == 0:
                    logger.info(f"Progress: {i + 1}/{len(fixtures)} fixtures")
                    
            # Final batch
            if features_batch:
                self.insert_features(features_batch)
                
            logger.info(f"Completed: {processed} processed, {skipped} skipped")
            
        finally:
            self.close()


def main():
    parser = argparse.ArgumentParser(description='Backfill historical features from historical_odds')
    parser.add_argument('--dry-run', action='store_true', help='Run without inserting data')
    parser.add_argument('--league', type=str, help='Specific league code to process (e.g., E0, SP1)')
    args = parser.parse_args()
    
    backfill = HistoricalFeaturesBackfill(dry_run=args.dry_run)
    backfill.run(league_code=args.league)


if __name__ == '__main__':
    main()
