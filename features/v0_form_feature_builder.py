"""
V0 Form-Only Feature Builder

Builds features for matches WITHOUT requiring odds data.
Uses only historical form data: ELO ratings, recent results, H2H, home/away splits.

This enables predictions for:
- Matches before odds are published
- Minor leagues without bookmaker coverage
- International friendlies

Features (~25 total):
1. ELO Features (5): home_elo, away_elo, elo_diff, elo_expected, elo_advantage
2. Form Features (8): home_form_5, away_form_5, home_goals_5, away_goals_5, form_diff, goal_diff, home_win_streak, away_win_streak
3. H2H Features (4): h2h_home_wins, h2h_draws, h2h_away_wins, h2h_total
4. Home/Away Splits (4): home_home_rate, away_away_rate, home_goals_home, away_goals_away
5. Context Features (4): is_derby, league_tier, neutral_venue, days_since_last
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, List
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import numpy as np
import os

from models.team_elo import TeamELOManager, INITIAL_ELO

logger = logging.getLogger(__name__)

FEATURE_NAMES = [
    'home_elo', 'away_elo', 'elo_diff', 'elo_expected', 'elo_advantage',
    'home_form_5', 'away_form_5', 'home_goals_5', 'away_goals_5',
    'form_diff', 'goal_diff', 'home_win_streak', 'away_win_streak',
    'h2h_home_wins', 'h2h_draws', 'h2h_away_wins', 'h2h_total',
    'home_home_rate', 'away_away_rate', 'home_goals_home', 'away_goals_away',
    'is_derby', 'league_tier', 'neutral_venue', 'days_since_last'
]


class V0FormFeatureBuilder:
    """Builds form-only features for matches without odds."""
    
    TIER_1_LEAGUES = {39, 140, 78, 135, 61}  # EPL, La Liga, Bundesliga, Serie A, Ligue 1
    TIER_2_LEAGUES = {88, 94, 40, 2, 3}  # Eredivisie, Primeira Liga, Championship, UCL, UEL
    
    def __init__(self):
        self.engine = create_engine(os.environ['DATABASE_URL'])
        self.Session = sessionmaker(bind=self.engine)
        self.elo_manager = TeamELOManager()
    
    def build_features(self, match_id: int, 
                       home_team_id: int = None, 
                       away_team_id: int = None,
                       kickoff_at: datetime = None,
                       league_id: int = None) -> Optional[Dict]:
        """
        Build form features for a match.
        
        Can be called with just match_id (will lookup details) or with all params.
        Returns dict with feature names and values, or None if insufficient data.
        """
        session = self.Session()
        try:
            if not all([home_team_id, away_team_id]):
                match_info = self._get_match_info(session, match_id)
                if not match_info:
                    logger.debug(f"Match {match_id} not found in fixtures")
                    return None
                home_team_id = match_info['home_team_id']
                away_team_id = match_info['away_team_id']
                kickoff_at = match_info['kickoff_at']
                league_id = match_info['league_id']
            
            if not home_team_id or not away_team_id:
                logger.debug(f"Missing team IDs for match {match_id}")
                return None
            
            features = {}
            
            elo_features = self._build_elo_features(home_team_id, away_team_id)
            features.update(elo_features)
            
            form_features = self._build_form_features(session, home_team_id, away_team_id, kickoff_at)
            features.update(form_features)
            
            h2h_features = self._build_h2h_features(session, home_team_id, away_team_id, kickoff_at)
            features.update(h2h_features)
            
            split_features = self._build_split_features(session, home_team_id, away_team_id, kickoff_at)
            features.update(split_features)
            
            context_features = self._build_context_features(
                session, home_team_id, away_team_id, league_id, kickoff_at
            )
            features.update(context_features)
            
            features['match_id'] = match_id
            
            return features
            
        except Exception as e:
            logger.error(f"Error building V0 features for match {match_id}: {e}")
            return None
        finally:
            session.close()
    
    def _get_match_info(self, session, match_id: int) -> Optional[Dict]:
        """Get basic match info from fixtures."""
        result = session.execute(text("""
            SELECT home_team_id, away_team_id, kickoff_at, league_id
            FROM fixtures WHERE match_id = :match_id
        """), {'match_id': match_id})
        row = result.fetchone()
        if row:
            return {
                'home_team_id': row.home_team_id,
                'away_team_id': row.away_team_id,
                'kickoff_at': row.kickoff_at,
                'league_id': row.league_id
            }
        return None
    
    def _build_elo_features(self, home_team_id: int, away_team_id: int) -> Dict:
        """Build ELO-based features."""
        home_elo = self.elo_manager.get_team_elo(home_team_id)
        away_elo = self.elo_manager.get_team_elo(away_team_id)
        
        elo_diff = home_elo - away_elo
        home_elo_with_ha = home_elo + 100
        elo_expected = 1.0 / (1.0 + 10 ** ((away_elo - home_elo_with_ha) / 400.0))
        elo_advantage = (home_elo - INITIAL_ELO) - (away_elo - INITIAL_ELO)
        
        return {
            'home_elo': round(home_elo, 1),
            'away_elo': round(away_elo, 1),
            'elo_diff': round(elo_diff, 1),
            'elo_expected': round(elo_expected, 4),
            'elo_advantage': round(elo_advantage, 1)
        }
    
    def _build_form_features(self, session, home_team_id: int, away_team_id: int, 
                            before_date: datetime = None) -> Dict:
        """Build recent form features (last 5 matches)."""
        if before_date is None:
            before_date = datetime.utcnow()
        
        def get_form(team_id: int, is_home_matches_only: bool = False) -> Dict:
            venue_filter = ""
            if is_home_matches_only:
                venue_filter = "AND f.home_team_id = :team_id"
            else:
                venue_filter = "AND (f.home_team_id = :team_id OR f.away_team_id = :team_id)"
            
            result = session.execute(text(f"""
                SELECT 
                    f.home_team_id, f.away_team_id,
                    m.home_goals, m.away_goals, m.outcome
                FROM fixtures f
                JOIN matches m ON f.match_id = m.match_id
                WHERE f.status = 'finished'
                AND f.kickoff_at < :before_date
                {venue_filter}
                ORDER BY f.kickoff_at DESC
                LIMIT 5
            """), {'team_id': team_id, 'before_date': before_date})
            
            points = 0
            goals_for = 0
            goals_against = 0
            win_streak = 0
            matches = list(result)
            
            for i, row in enumerate(matches):
                is_home = row.home_team_id == team_id
                if is_home:
                    gf, ga = row.home_goals or 0, row.away_goals or 0
                    won = (row.home_goals or 0) > (row.away_goals or 0)
                    drew = (row.home_goals or 0) == (row.away_goals or 0)
                else:
                    gf, ga = row.away_goals or 0, row.home_goals or 0
                    won = (row.away_goals or 0) > (row.home_goals or 0)
                    drew = (row.home_goals or 0) == (row.away_goals or 0)
                
                goals_for += gf
                goals_against += ga
                
                if won:
                    points += 3
                    if i == 0 or (i == win_streak):
                        win_streak += 1
                elif drew:
                    points += 1
            
            n_matches = len(matches) if matches else 1
            return {
                'form': points / (n_matches * 3),
                'goals_avg': goals_for / n_matches if n_matches else 0,
                'win_streak': win_streak
            }
        
        home_form = get_form(home_team_id)
        away_form = get_form(away_team_id)
        
        return {
            'home_form_5': round(home_form['form'], 3),
            'away_form_5': round(away_form['form'], 3),
            'home_goals_5': round(home_form['goals_avg'], 2),
            'away_goals_5': round(away_form['goals_avg'], 2),
            'form_diff': round(home_form['form'] - away_form['form'], 3),
            'goal_diff': round(home_form['goals_avg'] - away_form['goals_avg'], 2),
            'home_win_streak': home_form['win_streak'],
            'away_win_streak': away_form['win_streak']
        }
    
    def _build_h2h_features(self, session, home_team_id: int, away_team_id: int,
                           before_date: datetime = None) -> Dict:
        """Build head-to-head features."""
        if before_date is None:
            before_date = datetime.utcnow()
        
        result = session.execute(text("""
            SELECT m.outcome, f.home_team_id
            FROM fixtures f
            JOIN matches m ON f.match_id = m.match_id
            WHERE f.status = 'finished'
            AND f.kickoff_at < :before_date
            AND (
                (f.home_team_id = :home_id AND f.away_team_id = :away_id) OR
                (f.home_team_id = :away_id AND f.away_team_id = :home_id)
            )
            ORDER BY f.kickoff_at DESC
            LIMIT 10
        """), {'home_id': home_team_id, 'away_id': away_team_id, 'before_date': before_date})
        
        h2h_home_wins = 0
        h2h_draws = 0
        h2h_away_wins = 0
        
        for row in result:
            if row.outcome == 'D':
                h2h_draws += 1
            elif row.outcome == 'H':
                if row.home_team_id == home_team_id:
                    h2h_home_wins += 1
                else:
                    h2h_away_wins += 1
            elif row.outcome == 'A':
                if row.home_team_id == home_team_id:
                    h2h_away_wins += 1
                else:
                    h2h_home_wins += 1
        
        total = h2h_home_wins + h2h_draws + h2h_away_wins
        
        return {
            'h2h_home_wins': h2h_home_wins,
            'h2h_draws': h2h_draws,
            'h2h_away_wins': h2h_away_wins,
            'h2h_total': total
        }
    
    def _build_split_features(self, session, home_team_id: int, away_team_id: int,
                             before_date: datetime = None) -> Dict:
        """Build home/away split features."""
        if before_date is None:
            before_date = datetime.utcnow()
        
        def get_venue_stats(team_id: int, is_home: bool) -> Dict:
            if is_home:
                team_filter = "f.home_team_id = :team_id"
                goals_col = "m.home_goals"
                win_outcome = "'H'"
            else:
                team_filter = "f.away_team_id = :team_id"
                goals_col = "m.away_goals"
                win_outcome = "'A'"
            
            result = session.execute(text(f"""
                SELECT 
                    COUNT(*) as matches,
                    SUM(CASE WHEN m.outcome = {win_outcome} THEN 1 ELSE 0 END) as wins,
                    AVG({goals_col}) as goals_avg
                FROM fixtures f
                JOIN matches m ON f.match_id = m.match_id
                WHERE f.status = 'finished'
                AND {team_filter}
                AND f.kickoff_at < :before_date
                AND f.kickoff_at > :before_date - INTERVAL '180 days'
            """), {'team_id': team_id, 'before_date': before_date})
            
            row = result.fetchone()
            if row and row.matches and row.matches > 0:
                return {
                    'win_rate': float(row.wins or 0) / float(row.matches),
                    'goals_avg': float(row.goals_avg or 0)
                }
            return {'win_rate': 0.33, 'goals_avg': 1.0}
        
        home_at_home = get_venue_stats(home_team_id, is_home=True)
        away_at_away = get_venue_stats(away_team_id, is_home=False)
        
        return {
            'home_home_rate': round(home_at_home['win_rate'], 3),
            'away_away_rate': round(away_at_away['win_rate'], 3),
            'home_goals_home': round(home_at_home['goals_avg'], 2),
            'away_goals_away': round(away_at_away['goals_avg'], 2)
        }
    
    def _build_context_features(self, session, home_team_id: int, away_team_id: int,
                                league_id: int, kickoff_at: datetime = None) -> Dict:
        """Build context features."""
        is_derby = 0
        
        if league_id in self.TIER_1_LEAGUES:
            league_tier = 1
        elif league_id in self.TIER_2_LEAGUES:
            league_tier = 2
        else:
            league_tier = 3
        
        neutral_venue = 0
        
        days_since_last = 7
        if kickoff_at:
            result = session.execute(text("""
                SELECT MAX(f.kickoff_at) as last_match
                FROM fixtures f
                WHERE f.status = 'finished'
                AND (f.home_team_id = :home_id OR f.away_team_id = :home_id)
                AND f.kickoff_at < :kickoff_at
            """), {'home_id': home_team_id, 'kickoff_at': kickoff_at})
            row = result.fetchone()
            if row and row.last_match:
                days_since_last = (kickoff_at - row.last_match).days
        
        return {
            'is_derby': is_derby,
            'league_tier': league_tier,
            'neutral_venue': neutral_venue,
            'days_since_last': min(days_since_last, 30)
        }
    
    def build_training_dataset(self, limit: int = None) -> List[Dict]:
        """
        Build training dataset from all finished matches.
        
        Returns list of feature dicts with 'outcome' label.
        """
        session = self.Session()
        try:
            limit_clause = f"LIMIT {limit}" if limit else ""
            
            result = session.execute(text(f"""
                SELECT 
                    f.match_id, f.home_team_id, f.away_team_id,
                    f.league_id, f.kickoff_at, m.outcome
                FROM fixtures f
                JOIN matches m ON f.match_id = m.match_id
                WHERE f.status = 'finished'
                AND f.home_team_id IS NOT NULL
                AND f.away_team_id IS NOT NULL
                AND m.outcome IS NOT NULL
                ORDER BY f.kickoff_at ASC
                {limit_clause}
            """))
            
            dataset = []
            for row in result:
                features = self.build_features(
                    match_id=row.match_id,
                    home_team_id=row.home_team_id,
                    away_team_id=row.away_team_id,
                    kickoff_at=row.kickoff_at,
                    league_id=row.league_id
                )
                
                if features:
                    features['outcome'] = row.outcome
                    dataset.append(features)
            
            logger.info(f"Built {len(dataset)} training samples for V0")
            return dataset
            
        except Exception as e:
            logger.error(f"Error building V0 training dataset: {e}")
            return []
        finally:
            session.close()


if __name__ == "__main__":
    builder = V0FormFeatureBuilder()
    
    from sqlalchemy import create_engine, text
    engine = create_engine(os.environ['DATABASE_URL'])
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT match_id FROM fixtures 
            WHERE status = 'scheduled' 
            AND kickoff_at > NOW()
            LIMIT 1
        """))
        row = result.fetchone()
        if row:
            features = builder.build_features(row.match_id)
            print(f"Sample features for match {row.match_id}:")
            for k, v in sorted(features.items()):
                print(f"  {k}: {v}")
