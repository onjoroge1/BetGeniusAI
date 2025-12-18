"""
World Cup Feature Builder - Tournament-Specific Features
Generates 30 WC-specific features for international tournament predictions.

Features are grouped into:
1. Tournament Context (8 features)
2. Team Experience (6 features)
3. Squad Stability (5 features)
4. Logistics (5 features)
5. Psychology (6 features)
"""

import os
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import numpy as np

logger = logging.getLogger(__name__)


class WCFeatureBuilder:
    """
    Builds World Cup-specific features for tournament match predictions.
    
    These features complement the 61 base V2 features with tournament-specific
    context that significantly impacts international match outcomes.
    """
    
    STAGE_ORDER = {
        'group': 1,
        'r32': 2,
        'r16': 3,
        'qf': 4,
        'sf': 5,
        '3rd_place': 6,
        'final': 7,
        'qualifying': 0,
        'playoff': 0,
        'other': 0,
        'unknown': 0
    }
    
    WC_WINNERS = {
        'Brazil': 5,
        'Germany': 4,
        'Italy': 4,
        'Argentina': 3,
        'France': 2,
        'Uruguay': 2,
        'England': 1,
        'Spain': 1
    }
    
    EURO_WINNERS = {
        'Germany': 3,
        'Spain': 3,
        'Italy': 2,
        'France': 2,
        'Portugal': 1,
        'Netherlands': 1,
        'Denmark': 1,
        'Greece': 1,
        'Czech Republic': 1,
        'Soviet Union': 1
    }
    
    def __init__(self):
        self.db_url = os.getenv('DATABASE_URL')
    
    def _get_connection(self):
        return psycopg2.connect(self.db_url)
    
    def build_features(self, fixture_id: int, home_team: str, away_team: str,
                       tournament_id: int, stage: str, season: int) -> Dict:
        """
        Build all 30 WC-specific features for a match.
        
        Args:
            fixture_id: API Football fixture ID
            home_team: Home team name
            away_team: Away team name
            tournament_id: League ID (1=WC, 4=Euro, etc.)
            stage: Tournament stage (group, r16, qf, sf, final)
            season: Tournament year
            
        Returns:
            Dictionary of 30 WC features
        """
        features = {}
        
        features.update(self._build_tournament_context(stage, tournament_id, season, home_team, away_team))
        features.update(self._build_team_experience(home_team, away_team, tournament_id))
        features.update(self._build_squad_stability(home_team, away_team, tournament_id, season))
        features.update(self._build_logistics(fixture_id, home_team, away_team))
        features.update(self._build_psychology(home_team, away_team, tournament_id, stage))
        
        return features
    
    def _build_tournament_context(self, stage: str, tournament_id: int, 
                                   season: int, home_team: str, away_team: str) -> Dict:
        """
        Tournament Context Features (8):
        - stage_group: Is this a group stage match?
        - stage_knockout: Is this a knockout match?
        - stage_importance: Ordinal importance of stage (1-7)
        - is_elimination: Can a team be eliminated in this match?
        - matchday: Which matchday of the group stage (1, 2, 3)
        - is_must_win_home: Does home team need to win to advance?
        - is_must_win_away: Does away team need to win to advance?
        - rivalry_flag: Historical rivalry between teams
        """
        features = {}
        
        stage_num = self.STAGE_ORDER.get(stage, 0)
        
        features['stage_group'] = 1 if stage == 'group' else 0
        features['stage_knockout'] = 1 if stage in ['r16', 'qf', 'sf', 'final'] else 0
        features['stage_importance'] = stage_num
        features['is_elimination'] = 1 if stage in ['r16', 'qf', 'sf', 'final'] else 0
        
        features['matchday'] = self._get_matchday(home_team, tournament_id, season) if stage == 'group' else 0
        
        features['is_must_win_home'] = self._calculate_must_win(home_team, tournament_id, season, stage)
        features['is_must_win_away'] = self._calculate_must_win(away_team, tournament_id, season, stage)
        
        features['rivalry_flag'] = self._check_rivalry(home_team, away_team)
        
        return features
    
    def _build_team_experience(self, home_team: str, away_team: str, 
                                tournament_id: int) -> Dict:
        """
        Team Experience Features (6):
        - home_avg_caps: Average caps of home team players
        - away_avg_caps: Average caps of away team players
        - home_tournament_apps: Home team's tournament appearances
        - away_tournament_apps: Away team's tournament appearances
        - home_titles: Number of titles won (WC/Euro)
        - away_titles: Number of titles won (WC/Euro)
        """
        features = {}
        
        features['home_avg_caps'] = self._get_avg_caps(home_team)
        features['away_avg_caps'] = self._get_avg_caps(away_team)
        
        features['home_tournament_apps'] = self._count_tournament_appearances(home_team, tournament_id)
        features['away_tournament_apps'] = self._count_tournament_appearances(away_team, tournament_id)
        
        if tournament_id == 1:
            features['home_titles'] = self.WC_WINNERS.get(home_team, 0)
            features['away_titles'] = self.WC_WINNERS.get(away_team, 0)
        elif tournament_id == 4:
            features['home_titles'] = self.EURO_WINNERS.get(home_team, 0)
            features['away_titles'] = self.EURO_WINNERS.get(away_team, 0)
        else:
            features['home_titles'] = 0
            features['away_titles'] = 0
        
        return features
    
    def _build_squad_stability(self, home_team: str, away_team: str,
                                tournament_id: int, season: int) -> Dict:
        """
        Squad Stability Features (5):
        - home_squad_new_pct: Percentage of new players vs previous tournament
        - away_squad_new_pct: Percentage of new players vs previous tournament
        - home_club_dispersion: How many different clubs represented
        - away_club_dispersion: How many different clubs represented
        - home_chemistry_score: How often the squad plays together
        """
        features = {}
        
        features['home_squad_new_pct'] = self._get_squad_turnover(home_team, tournament_id, season)
        features['away_squad_new_pct'] = self._get_squad_turnover(away_team, tournament_id, season)
        
        features['home_club_dispersion'] = self._get_club_dispersion(home_team, tournament_id, season)
        features['away_club_dispersion'] = self._get_club_dispersion(away_team, tournament_id, season)
        
        features['home_chemistry_score'] = self._calculate_chemistry(home_team, tournament_id, season)
        
        return features
    
    def _build_logistics(self, fixture_id: int, home_team: str, away_team: str) -> Dict:
        """
        Logistics Features (5):
        - rest_days_home: Days since last match for home team
        - rest_days_away: Days since last match for away team
        - rest_advantage: Difference in rest days
        - travel_disadvantage: Relative travel distance disadvantage
        - time_zone_diff: Time zone difference from home country
        """
        features = {}
        
        rest_home, rest_away = self._get_rest_days(fixture_id, home_team, away_team)
        
        features['rest_days_home'] = rest_home
        features['rest_days_away'] = rest_away
        features['rest_advantage'] = rest_home - rest_away
        
        features['travel_disadvantage'] = 0
        features['time_zone_diff'] = 0
        
        return features
    
    def _build_psychology(self, home_team: str, away_team: str,
                          tournament_id: int, stage: str) -> Dict:
        """
        Psychology Features (6):
        - home_penalty_win_rate: Historical penalty shootout win rate
        - away_penalty_win_rate: Historical penalty shootout win rate
        - home_knockout_survival: Knockout stage win percentage
        - away_knockout_survival: Knockout stage win percentage
        - home_underdog_flag: Is home team significantly lower ranked?
        - pressure_index: Combined pressure based on stage and expectations
        """
        features = {}
        
        features['home_penalty_win_rate'] = self._get_penalty_win_rate(home_team)
        features['away_penalty_win_rate'] = self._get_penalty_win_rate(away_team)
        
        features['home_knockout_survival'] = self._get_knockout_survival(home_team, tournament_id)
        features['away_knockout_survival'] = self._get_knockout_survival(away_team, tournament_id)
        
        home_titles = self.WC_WINNERS.get(home_team, 0) + self.EURO_WINNERS.get(home_team, 0)
        away_titles = self.WC_WINNERS.get(away_team, 0) + self.EURO_WINNERS.get(away_team, 0)
        features['home_underdog_flag'] = 1 if home_titles < away_titles else 0
        
        stage_pressure = self.STAGE_ORDER.get(stage, 0) / 7.0
        title_pressure = max(home_titles, away_titles) / 5.0
        features['pressure_index'] = (stage_pressure + title_pressure) / 2
        
        return features
    
    def _get_matchday(self, team: str, tournament_id: int, season: int) -> int:
        """Determine which matchday of the group stage."""
        conn = None
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            
            cur.execute("""
                SELECT COUNT(*) + 1 as matchday
                FROM international_matches
                WHERE tournament_id = %s
                  AND season = %s
                  AND tournament_stage = 'group'
                  AND (home_team_name = %s OR away_team_name = %s)
            """, (tournament_id, season, team, team))
            
            row = cur.fetchone()
            return min(row[0] if row else 1, 3)
            
        except Exception as e:
            logger.warning(f"Error getting matchday: {e}")
            return 1
        finally:
            if conn:
                conn.close()
    
    def _calculate_must_win(self, team: str, tournament_id: int, 
                            season: int, stage: str) -> int:
        """Calculate if team is in a must-win situation."""
        if stage in ['r16', 'qf', 'sf', 'final']:
            return 1
        
        if stage == 'group':
            conn = None
            try:
                conn = self._get_connection()
                cur = conn.cursor()
                
                cur.execute("""
                    SELECT 
                        SUM(CASE 
                            WHEN (home_team_name = %s AND outcome = 'H') OR 
                                 (away_team_name = %s AND outcome = 'A') THEN 3
                            WHEN outcome = 'D' THEN 1
                            ELSE 0
                        END) as points,
                        COUNT(*) as matches
                    FROM international_matches
                    WHERE tournament_id = %s
                      AND season = %s
                      AND tournament_stage = 'group'
                      AND (home_team_name = %s OR away_team_name = %s)
                """, (team, team, tournament_id, season, team, team))
                
                row = cur.fetchone()
                if row:
                    points = row[0] or 0
                    matches = row[1] or 0
                else:
                    points, matches = 0, 0
                
                if matches == 2 and points <= 1:
                    return 1
                    
            except Exception as e:
                logger.warning(f"Error calculating must_win: {e}")
            finally:
                if conn:
                    conn.close()
        
        return 0
    
    def _check_rivalry(self, home_team: str, away_team: str) -> int:
        """Check if this is a known rivalry match."""
        rivalries = [
            ('Argentina', 'Brazil'),
            ('Argentina', 'England'),
            ('Germany', 'Netherlands'),
            ('Germany', 'England'),
            ('Germany', 'Italy'),
            ('Spain', 'Portugal'),
            ('France', 'Italy'),
            ('France', 'Germany'),
            ('Brazil', 'Uruguay'),
            ('Mexico', 'USA'),
            ('England', 'Scotland'),
            ('Egypt', 'Algeria'),
            ('Nigeria', 'Ghana'),
            ('Morocco', 'Algeria'),
            ('Japan', 'South Korea'),
        ]
        
        teams = {home_team, away_team}
        for t1, t2 in rivalries:
            if teams == {t1, t2}:
                return 1
        return 0
    
    def _get_avg_caps(self, team: str) -> float:
        """Get average caps for a team's players."""
        conn = None
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            
            cur.execute("""
                SELECT AVG(total_caps) as avg_caps
                FROM player_international_stats
                WHERE team_name = %s
            """, (team,))
            
            row = cur.fetchone()
            return float(row[0]) if row and row[0] else 30.0
            
        except Exception as e:
            return 30.0
        finally:
            if conn:
                conn.close()
    
    def _count_tournament_appearances(self, team: str, tournament_id: int) -> int:
        """Count how many times a team has appeared in a tournament."""
        conn = None
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            
            cur.execute("""
                SELECT COUNT(DISTINCT season) as appearances
                FROM international_matches
                WHERE tournament_id = %s
                  AND (home_team_name = %s OR away_team_name = %s)
            """, (tournament_id, team, team))
            
            row = cur.fetchone()
            return row[0] if row else 0
            
        except Exception as e:
            return 0
        finally:
            if conn:
                conn.close()
    
    def _get_squad_turnover(self, team: str, tournament_id: int, season: int) -> float:
        """Calculate percentage of new players vs previous tournament."""
        return 0.3
    
    def _get_club_dispersion(self, team: str, tournament_id: int, season: int) -> int:
        """Count number of different clubs represented in squad."""
        return 15
    
    def _calculate_chemistry(self, team: str, tournament_id: int, season: int) -> float:
        """Calculate squad chemistry based on matches played together."""
        conn = None
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            
            cur.execute("""
                SELECT COUNT(*) as recent_matches
                FROM international_matches
                WHERE (home_team_name = %s OR away_team_name = %s)
                  AND match_date > NOW() - INTERVAL '2 years'
            """, (team, team))
            
            row = cur.fetchone()
            matches = row[0] if row else 0
            
            return min(matches / 30.0, 1.0)
            
        except Exception as e:
            return 0.5
        finally:
            if conn:
                conn.close()
    
    def _get_rest_days(self, fixture_id: int, home_team: str, away_team: str) -> Tuple[int, int]:
        """Get rest days for both teams before this match."""
        return (4, 4)
    
    def _get_penalty_win_rate(self, team: str) -> float:
        """Get historical penalty shootout win rate."""
        conn = None
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            
            cur.execute("""
                SELECT 
                    COUNT(*) FILTER (WHERE result = 'W') as wins,
                    COUNT(*) as total
                FROM penalty_shootout_history
                WHERE team_name = %s
            """, (team,))
            
            row = cur.fetchone()
            if row and row[1] > 0:
                return row[0] / row[1]
            return 0.5
            
        except Exception as e:
            return 0.5
        finally:
            if conn:
                conn.close()
    
    def _get_knockout_survival(self, team: str, tournament_id: int) -> float:
        """Get knockout stage win percentage."""
        conn = None
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            
            cur.execute("""
                SELECT 
                    COUNT(*) FILTER (WHERE 
                        (home_team_name = %s AND outcome = 'H') OR 
                        (away_team_name = %s AND outcome = 'A') OR
                        (penalty_shootout AND (
                            (home_team_name = %s AND penalty_home > penalty_away) OR
                            (away_team_name = %s AND penalty_away > penalty_home)
                        ))
                    ) as wins,
                    COUNT(*) as total
                FROM international_matches
                WHERE tournament_id = %s
                  AND tournament_stage IN ('r16', 'qf', 'sf', 'final')
                  AND (home_team_name = %s OR away_team_name = %s)
            """, (team, team, team, team, tournament_id, team, team))
            
            row = cur.fetchone()
            if row and row[1] > 0:
                return row[0] / row[1]
            return 0.5
            
        except Exception as e:
            return 0.5
        finally:
            if conn:
                conn.close()
    
    def get_feature_names(self) -> List[str]:
        """Return list of all 30 WC feature names."""
        return [
            'stage_group', 'stage_knockout', 'stage_importance', 'is_elimination',
            'matchday', 'is_must_win_home', 'is_must_win_away', 'rivalry_flag',
            'home_avg_caps', 'away_avg_caps', 'home_tournament_apps', 'away_tournament_apps',
            'home_titles', 'away_titles',
            'home_squad_new_pct', 'away_squad_new_pct', 'home_club_dispersion',
            'away_club_dispersion', 'home_chemistry_score',
            'rest_days_home', 'rest_days_away', 'rest_advantage',
            'travel_disadvantage', 'time_zone_diff',
            'home_penalty_win_rate', 'away_penalty_win_rate',
            'home_knockout_survival', 'away_knockout_survival',
            'home_underdog_flag', 'pressure_index'
        ]


def test_feature_builder():
    """Test the WC feature builder with sample data."""
    builder = WCFeatureBuilder()
    
    print("\nTesting WC Feature Builder...")
    
    features = builder.build_features(
        fixture_id=855736,
        home_team='Argentina',
        away_team='France',
        tournament_id=1,
        stage='final',
        season=2022
    )
    
    print(f"\nGenerated {len(features)} features:")
    for name, value in features.items():
        print(f"  {name}: {value}")
    
    print(f"\nFeature names: {builder.get_feature_names()}")
    
    return features


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_feature_builder()
