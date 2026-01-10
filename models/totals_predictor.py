"""
BetGenius AI - Totals Prediction Service
Poisson-based over/under goal predictions for football matches
"""

import os
import logging
import numpy as np
from scipy.stats import poisson
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine, text

logger = logging.getLogger(__name__)


class TotalsPredictor:
    """Poisson-based model for predicting total goals and over/under markets"""
    
    GOAL_LINES = [0.5, 1.5, 2.5, 3.5, 4.5]
    
    def __init__(self):
        self.database_url = os.environ.get('DATABASE_URL')
        if not self.database_url:
            raise ValueError("DATABASE_URL environment variable required")
        
        self.engine = create_engine(
            self.database_url,
            pool_pre_ping=True,
            pool_recycle=300
        )
    
    def get_team_goal_stats(self, team_id: int, is_home: bool, 
                            cutoff: datetime = None, lookback_days: int = 180) -> Dict:
        """Get team's goal scoring and conceding statistics"""
        if cutoff is None:
            cutoff = datetime.now(timezone.utc)
        
        start_date = cutoff - timedelta(days=lookback_days)
        
        with self.engine.connect() as conn:
            if is_home:
                result = conn.execute(text("""
                    SELECT 
                        COUNT(*) as matches,
                        COALESCE(AVG(home_goals), 1.2) as goals_scored_avg,
                        COALESCE(AVG(away_goals), 1.2) as goals_conceded_avg,
                        COALESCE(STDDEV(home_goals), 1.0) as goals_scored_std,
                        COALESCE(SUM(CASE WHEN home_goals > away_goals THEN 1 ELSE 0 END), 0) as wins,
                        COALESCE(SUM(CASE WHEN home_goals = away_goals THEN 1 ELSE 0 END), 0) as draws
                    FROM matches
                    WHERE home_team_id = :team_id
                    AND match_date_utc >= :start_date
                    AND match_date_utc < :cutoff
                    AND home_goals IS NOT NULL
                """), {
                    'team_id': team_id,
                    'start_date': start_date,
                    'cutoff': cutoff
                })
            else:
                result = conn.execute(text("""
                    SELECT 
                        COUNT(*) as matches,
                        COALESCE(AVG(away_goals), 1.0) as goals_scored_avg,
                        COALESCE(AVG(home_goals), 1.4) as goals_conceded_avg,
                        COALESCE(STDDEV(away_goals), 1.0) as goals_scored_std,
                        COALESCE(SUM(CASE WHEN away_goals > home_goals THEN 1 ELSE 0 END), 0) as wins,
                        COALESCE(SUM(CASE WHEN away_goals = home_goals THEN 1 ELSE 0 END), 0) as draws
                    FROM matches
                    WHERE away_team_id = :team_id
                    AND match_date_utc >= :start_date
                    AND match_date_utc < :cutoff
                    AND away_goals IS NOT NULL
                """), {
                    'team_id': team_id,
                    'start_date': start_date,
                    'cutoff': cutoff
                })
            
            row = result.fetchone()
            if row and row.matches and row.matches >= 3:
                return {
                    'matches': row.matches,
                    'goals_scored_avg': float(row.goals_scored_avg),
                    'goals_conceded_avg': float(row.goals_conceded_avg),
                    'goals_scored_std': float(row.goals_scored_std) if row.goals_scored_std else 1.0,
                    'win_rate': row.wins / row.matches if row.matches > 0 else 0.33,
                    'draw_rate': row.draws / row.matches if row.matches > 0 else 0.25
                }
        
        if is_home:
            return {
                'matches': 0,
                'goals_scored_avg': 1.4,
                'goals_conceded_avg': 1.1,
                'goals_scored_std': 1.0,
                'win_rate': 0.45,
                'draw_rate': 0.25
            }
        else:
            return {
                'matches': 0,
                'goals_scored_avg': 1.1,
                'goals_conceded_avg': 1.4,
                'goals_scored_std': 1.0,
                'win_rate': 0.30,
                'draw_rate': 0.25
            }
    
    def get_league_averages(self, league_id: int, lookback_days: int = 365) -> Dict:
        """Get league-wide goal averages for normalization"""
        cutoff = datetime.now(timezone.utc)
        start_date = cutoff - timedelta(days=lookback_days)
        
        with self.engine.connect() as conn:
            result = conn.execute(text("""
                SELECT 
                    COUNT(*) as matches,
                    COALESCE(AVG(home_goals), 1.3) as home_goals_avg,
                    COALESCE(AVG(away_goals), 1.1) as away_goals_avg,
                    COALESCE(AVG(home_goals + away_goals), 2.4) as total_goals_avg
                FROM matches
                WHERE league_id = :league_id
                AND match_date_utc >= :start_date
                AND match_date_utc < :cutoff
                AND home_goals IS NOT NULL
            """), {
                'league_id': league_id,
                'start_date': start_date,
                'cutoff': cutoff
            })
            
            row = result.fetchone()
            if row and row.matches and row.matches >= 20:
                return {
                    'matches': row.matches,
                    'home_goals_avg': float(row.home_goals_avg),
                    'away_goals_avg': float(row.away_goals_avg),
                    'total_goals_avg': float(row.total_goals_avg)
                }
        
        return {
            'matches': 0,
            'home_goals_avg': 1.35,
            'away_goals_avg': 1.10,
            'total_goals_avg': 2.45
        }
    
    def calculate_expected_goals(self, home_team_id: int, away_team_id: int,
                                  league_id: int = None) -> Dict:
        """Calculate expected goals for each team using Poisson adjustment"""
        home_stats = self.get_team_goal_stats(home_team_id, is_home=True)
        away_stats = self.get_team_goal_stats(away_team_id, is_home=False)
        
        if league_id:
            league_avg = self.get_league_averages(league_id)
        else:
            league_avg = {'home_goals_avg': 1.35, 'away_goals_avg': 1.10}
        
        home_attack_strength = home_stats['goals_scored_avg'] / league_avg['home_goals_avg']
        away_defense_strength = away_stats['goals_conceded_avg'] / league_avg['home_goals_avg']
        
        away_attack_strength = away_stats['goals_scored_avg'] / league_avg['away_goals_avg']
        home_defense_strength = home_stats['goals_conceded_avg'] / league_avg['away_goals_avg']
        
        lambda_home = home_attack_strength * away_defense_strength * league_avg['home_goals_avg']
        lambda_away = away_attack_strength * home_defense_strength * league_avg['away_goals_avg']
        
        lambda_home = max(0.3, min(4.0, lambda_home))
        lambda_away = max(0.2, min(3.5, lambda_away))
        
        return {
            'lambda_home': lambda_home,
            'lambda_away': lambda_away,
            'expected_total': lambda_home + lambda_away,
            'home_attack_strength': home_attack_strength,
            'away_attack_strength': away_attack_strength,
            'home_defense_strength': home_defense_strength,
            'away_defense_strength': away_defense_strength,
            'home_sample_size': home_stats['matches'],
            'away_sample_size': away_stats['matches']
        }
    
    def calculate_over_under_probabilities(self, lambda_home: float, 
                                            lambda_away: float) -> Dict:
        """Calculate over/under probabilities for all goal lines"""
        probabilities = {}
        
        for line in self.GOAL_LINES:
            over_prob = self._calculate_over_probability(lambda_home, lambda_away, line)
            probabilities[f'over_{line}'] = round(over_prob, 4)
            probabilities[f'under_{line}'] = round(1 - over_prob, 4)
        
        return probabilities
    
    def _calculate_over_probability(self, lambda_home: float, lambda_away: float, 
                                     line: float) -> float:
        """Calculate probability of total goals being over a given line"""
        max_goals = 10
        under_prob = 0.0
        
        threshold = int(line)
        
        for home_goals in range(0, max_goals + 1):
            for away_goals in range(0, max_goals + 1):
                total = home_goals + away_goals
                if total <= threshold:
                    prob_home = poisson.pmf(home_goals, lambda_home)
                    prob_away = poisson.pmf(away_goals, lambda_away)
                    under_prob += prob_home * prob_away
        
        return 1 - under_prob
    
    def calculate_correct_score_probabilities(self, lambda_home: float,
                                               lambda_away: float,
                                               max_goals: int = 5) -> Dict:
        """Calculate correct score probabilities"""
        scores = {}
        
        for h in range(0, max_goals + 1):
            for a in range(0, max_goals + 1):
                prob_home = poisson.pmf(h, lambda_home)
                prob_away = poisson.pmf(a, lambda_away)
                prob = prob_home * prob_away
                if prob > 0.001:
                    scores[f'{h}-{a}'] = round(prob, 4)
        
        sorted_scores = dict(sorted(scores.items(), key=lambda x: x[1], reverse=True)[:10])
        return sorted_scores
    
    def calculate_btts_probability(self, lambda_home: float, lambda_away: float) -> Dict:
        """Calculate Both Teams To Score probability"""
        prob_home_scores = 1 - poisson.pmf(0, lambda_home)
        prob_away_scores = 1 - poisson.pmf(0, lambda_away)
        
        btts_yes = prob_home_scores * prob_away_scores
        
        return {
            'btts_yes': round(btts_yes, 4),
            'btts_no': round(1 - btts_yes, 4),
            'home_to_score': round(prob_home_scores, 4),
            'away_to_score': round(prob_away_scores, 4)
        }
    
    def predict_match(self, match_id: int) -> Optional[Dict]:
        """Get complete totals prediction for a match"""
        with self.engine.connect() as conn:
            result = conn.execute(text("""
                SELECT 
                    f.match_id,
                    f.home_team,
                    f.away_team,
                    f.home_team_id,
                    f.away_team_id,
                    f.league_id,
                    f.league_name,
                    f.kickoff_at,
                    oc.ph_cons,
                    oc.pd_cons,
                    oc.pa_cons
                FROM fixtures f
                LEFT JOIN odds_consensus oc ON f.match_id = oc.match_id
                WHERE f.match_id = :match_id
            """), {'match_id': match_id})
            
            row = result.fetchone()
            if not row:
                return None
            
            if not row.home_team_id or not row.away_team_id:
                return {
                    'match_id': match_id,
                    'error': 'Missing team IDs',
                    'status': 'unavailable'
                }
            
            xg = self.calculate_expected_goals(
                row.home_team_id,
                row.away_team_id,
                row.league_id
            )
            
            ou_probs = self.calculate_over_under_probabilities(
                xg['lambda_home'],
                xg['lambda_away']
            )
            
            btts = self.calculate_btts_probability(
                xg['lambda_home'],
                xg['lambda_away']
            )
            
            correct_scores = self.calculate_correct_score_probabilities(
                xg['lambda_home'],
                xg['lambda_away']
            )
            
            confidence = min(1.0, (xg['home_sample_size'] + xg['away_sample_size']) / 20)
            
            return {
                'match_id': match_id,
                'home_team': row.home_team,
                'away_team': row.away_team,
                'league': row.league_name,
                'kickoff_at': row.kickoff_at.isoformat() if row.kickoff_at else None,
                'expected_goals': {
                    'home': round(xg['lambda_home'], 2),
                    'away': round(xg['lambda_away'], 2),
                    'total': round(xg['expected_total'], 2)
                },
                'over_under': ou_probs,
                'btts': btts,
                'correct_score_top_5': dict(list(correct_scores.items())[:5]),
                'model_confidence': round(confidence, 2),
                'sample_sizes': {
                    'home_matches': xg['home_sample_size'],
                    'away_matches': xg['away_sample_size']
                },
                'status': 'available'
            }
    
    def get_totals_for_parlays(self, match_ids: List[int]) -> List[Dict]:
        """Get totals predictions formatted for parlay builder"""
        results = []
        
        for match_id in match_ids:
            pred = self.predict_match(match_id)
            if pred and pred.get('status') == 'available':
                over_2_5_prob = pred['over_under'].get('over_2.5', 0.5)
                under_2_5_prob = pred['over_under'].get('under_2.5', 0.5)
                
                results.append({
                    'match_id': match_id,
                    'home_team': pred['home_team'],
                    'away_team': pred['away_team'],
                    'markets': {
                        'over_2.5': {
                            'probability': over_2_5_prob,
                            'expected_goals': pred['expected_goals']['total']
                        },
                        'under_2.5': {
                            'probability': under_2_5_prob,
                            'expected_goals': pred['expected_goals']['total']
                        },
                        'over_1.5': {
                            'probability': pred['over_under'].get('over_1.5', 0.7)
                        },
                        'under_1.5': {
                            'probability': pred['over_under'].get('under_1.5', 0.3)
                        },
                        'btts_yes': {
                            'probability': pred['btts']['btts_yes']
                        },
                        'btts_no': {
                            'probability': pred['btts']['btts_no']
                        }
                    },
                    'confidence': pred['model_confidence']
                })
        
        return results
