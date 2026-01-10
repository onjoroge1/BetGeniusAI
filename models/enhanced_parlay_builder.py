"""
BetGenius AI - Enhanced Parlay Builder
Supports match results, totals, and player props with cross-market correlation
"""

import os
import uuid
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional, Tuple
from itertools import combinations
from sqlalchemy import create_engine, text

from models.totals_predictor import TotalsPredictor
from models.player_props_service import PlayerPropsService

logger = logging.getLogger(__name__)


CROSS_MARKET_CORRELATIONS = {
    ('match_result', 'H', 'totals', 'over_2.5'): 0.35,
    ('match_result', 'A', 'totals', 'over_2.5'): 0.30,
    ('match_result', 'D', 'totals', 'under_2.5'): 0.25,
    ('match_result', 'H', 'totals', 'under_2.5'): -0.15,
    ('match_result', 'A', 'totals', 'under_2.5'): -0.10,
    
    ('match_result', 'H', 'player_prop', 'anytime_scorer_home'): 0.45,
    ('match_result', 'A', 'player_prop', 'anytime_scorer_away'): 0.45,
    ('match_result', 'H', 'player_prop', 'anytime_scorer_away'): -0.20,
    ('match_result', 'A', 'player_prop', 'anytime_scorer_home'): -0.20,
    
    ('totals', 'over_2.5', 'player_prop', 'anytime_scorer'): 0.55,
    ('totals', 'under_2.5', 'player_prop', 'anytime_scorer'): -0.40,
    
    ('totals', 'over_2.5', 'totals', 'btts_yes'): 0.60,
    ('totals', 'under_2.5', 'totals', 'btts_no'): 0.50,
}

SAME_LEAGUE_PENALTY = 0.10
SAME_TIME_PENALTY = 0.03
FAVORITES_COMBO_PENALTY = 0.05

CONFIDENCE_THRESHOLDS = {
    'high': {'min_edge': 0.08, 'max_correlation': 0.15},
    'medium': {'min_edge': 0.05, 'max_correlation': 0.25},
    'low': {'min_edge': 0.02, 'max_correlation': 0.40},
}


class EnhancedParlayBuilder:
    """Enhanced parlay builder supporting multiple market types"""
    
    def __init__(self):
        self.database_url = os.environ.get('DATABASE_URL')
        if not self.database_url:
            raise ValueError("DATABASE_URL required")
        
        self.engine = create_engine(
            self.database_url,
            pool_pre_ping=True,
            pool_recycle=300
        )
        
        self.totals_predictor = TotalsPredictor()
        self.player_props = PlayerPropsService()
    
    def build_custom_parlay(self, selections: List[Dict]) -> Dict:
        """
        Build a custom parlay from user selections.
        
        Each selection should have:
        - leg_type: 'match_result' | 'totals' | 'player_prop'
        - match_id: int
        - market: str (e.g., 'H', 'D', 'A', 'over_2.5', 'anytime_scorer')
        - player_id: int (for player_prop only)
        """
        if len(selections) < 2:
            return {'error': 'Parlay requires at least 2 selections'}
        
        if len(selections) > 10:
            return {'error': 'Maximum 10 legs per parlay'}
        
        legs = []
        for sel in selections:
            leg = self._build_leg(sel)
            if 'error' in leg:
                return {'error': f"Failed to build leg: {leg['error']}"}
            legs.append(leg)
        
        combined_odds = 1.0
        combined_prob = 1.0
        
        for leg in legs:
            combined_odds *= leg['decimal_odds']
            combined_prob *= leg['model_prob']
        
        correlation_penalty = self._calculate_cross_market_correlation(legs)
        
        adjusted_prob = combined_prob * (1 - correlation_penalty)
        
        implied_prob = 1 / combined_odds if combined_odds > 0 else 0
        edge = (adjusted_prob - implied_prob) / implied_prob if implied_prob > 0 else 0
        
        confidence_tier = self._determine_confidence_tier(edge, correlation_penalty)
        
        return {
            'parlay_id': str(uuid.uuid4())[:8],
            'leg_count': len(legs),
            'legs': legs,
            'combined_odds': round(combined_odds, 2),
            'combined_prob_raw': round(combined_prob * 100, 2),
            'correlation_penalty_pct': round(correlation_penalty * 100, 1),
            'adjusted_prob_pct': round(adjusted_prob * 100, 2),
            'implied_prob_pct': round(implied_prob * 100, 2),
            'edge_pct': round(edge * 100, 1),
            'edge_indicator': 'positive' if edge > 0 else 'negative',
            'confidence_tier': confidence_tier,
            'recommendation': self._generate_recommendation(edge, correlation_penalty, legs),
            'leg_type_breakdown': self._get_leg_type_breakdown(legs)
        }
    
    def _build_leg(self, selection: Dict) -> Dict:
        """Build a single leg based on selection type"""
        leg_type = selection.get('leg_type', 'match_result')
        match_id = selection.get('match_id')
        market = selection.get('market')
        
        match_info = self._get_match_info(match_id)
        if not match_info:
            return {'error': f'Match {match_id} not found'}
        
        if leg_type == 'match_result':
            return self._build_match_result_leg(match_info, market)
        
        elif leg_type == 'totals':
            return self._build_totals_leg(match_info, market)
        
        elif leg_type == 'player_prop':
            player_id = selection.get('player_id')
            if not player_id:
                return {'error': 'player_id required for player_prop'}
            return self._build_player_prop_leg(match_info, player_id, market)
        
        else:
            return {'error': f'Unknown leg_type: {leg_type}'}
    
    def _get_match_info(self, match_id: int) -> Optional[Dict]:
        """Get match information including odds"""
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
                    oc.pa_cons,
                    ps.probs_h as model_prob_h,
                    ps.probs_d as model_prob_d,
                    ps.probs_a as model_prob_a
                FROM fixtures f
                LEFT JOIN odds_consensus oc ON f.match_id = oc.match_id
                LEFT JOIN (
                    SELECT DISTINCT ON (match_id) 
                        match_id, probs_h, probs_d, probs_a
                    FROM prediction_snapshots
                    ORDER BY match_id, served_at DESC
                ) ps ON f.match_id = ps.match_id
                WHERE f.match_id = :match_id
            """), {'match_id': match_id})
            
            row = result.fetchone()
            if row:
                return {
                    'match_id': row.match_id,
                    'home_team': row.home_team,
                    'away_team': row.away_team,
                    'home_team_id': row.home_team_id,
                    'away_team_id': row.away_team_id,
                    'league_id': row.league_id,
                    'league_name': row.league_name,
                    'kickoff_at': row.kickoff_at,
                    'odds': {
                        'H': 1 / row.ph_cons if row.ph_cons and row.ph_cons > 0 else 2.0,
                        'D': 1 / row.pd_cons if row.pd_cons and row.pd_cons > 0 else 3.5,
                        'A': 1 / row.pa_cons if row.pa_cons and row.pa_cons > 0 else 3.0
                    },
                    'market_prob': {
                        'H': row.ph_cons or 0.45,
                        'D': row.pd_cons or 0.28,
                        'A': row.pa_cons or 0.27
                    },
                    'model_prob': {
                        'H': row.model_prob_h or row.ph_cons or 0.45,
                        'D': row.model_prob_d or row.pd_cons or 0.28,
                        'A': row.model_prob_a or row.pa_cons or 0.27
                    }
                }
        return None
    
    def _build_match_result_leg(self, match_info: Dict, market: str) -> Dict:
        """Build a match result (1X2) leg"""
        if market not in ['H', 'D', 'A']:
            return {'error': f'Invalid match_result market: {market}'}
        
        outcome_names = {'H': 'Home Win', 'D': 'Draw', 'A': 'Away Win'}
        
        model_prob = match_info['model_prob'][market]
        market_prob = match_info['market_prob'][market]
        decimal_odds = match_info['odds'][market]
        
        edge = (model_prob - market_prob) / market_prob if market_prob > 0 else 0
        
        return {
            'leg_type': 'match_result',
            'match_id': match_info['match_id'],
            'home_team': match_info['home_team'],
            'away_team': match_info['away_team'],
            'league_name': match_info['league_name'],
            'kickoff_at': match_info['kickoff_at'],
            'market': market,
            'market_name': outcome_names[market],
            'model_prob': round(model_prob, 4),
            'market_prob': round(market_prob, 4),
            'decimal_odds': round(decimal_odds, 2),
            'edge_pct': round(edge * 100, 1)
        }
    
    def _build_totals_leg(self, match_info: Dict, market: str) -> Dict:
        """Build a totals (over/under) leg"""
        totals = self.totals_predictor.predict_match(match_info['match_id'])
        
        if not totals or totals.get('status') != 'available':
            return {'error': 'Totals prediction unavailable'}
        
        ou_key = market.replace('_', '.')
        if market.startswith('over') or market.startswith('under'):
            parts = market.split('_')
            if len(parts) >= 2:
                ou_key = f"{parts[0]}_{'.'.join(parts[1:])}"
        
        if ou_key not in totals['over_under']:
            return {'error': f'Invalid totals market: {market}. Valid: {list(totals["over_under"].keys())}'}
        
        model_prob = totals['over_under'][ou_key]
        
        default_market_probs = {
            'over_0.5': 0.85, 'under_0.5': 0.15,
            'over_1.5': 0.70, 'under_1.5': 0.30,
            'over_2.5': 0.52, 'under_2.5': 0.48,
            'over_3.5': 0.32, 'under_3.5': 0.68,
            'over_4.5': 0.15, 'under_4.5': 0.85
        }
        market_prob = default_market_probs.get(ou_key, 0.50)
        
        decimal_odds = 1 / market_prob if market_prob > 0 else 2.0
        
        edge = (model_prob - market_prob) / market_prob if market_prob > 0 else 0
        
        market_display = market.replace('_', ' ').replace('.', ' ').title()
        
        return {
            'leg_type': 'totals',
            'match_id': match_info['match_id'],
            'home_team': match_info['home_team'],
            'away_team': match_info['away_team'],
            'league_name': match_info['league_name'],
            'kickoff_at': match_info['kickoff_at'],
            'market': market,
            'market_name': f"Total Goals {market_display}",
            'expected_goals': totals['expected_goals']['total'],
            'model_prob': round(model_prob, 4),
            'market_prob': round(market_prob, 4),
            'decimal_odds': round(decimal_odds, 2),
            'edge_pct': round(edge * 100, 1)
        }
    
    def _build_player_prop_leg(self, match_info: Dict, player_id: int, market: str) -> Dict:
        """Build a player prop leg"""
        props = self.player_props.get_player_props_for_parlay(player_id, match_info['match_id'])
        
        if 'error' in props:
            return {'error': props['error']}
        
        market_key = market
        if market_key not in props['markets']:
            return {'error': f'Invalid player_prop market: {market}'}
        
        model_prob = props['markets'][market_key]['probability']
        
        default_market_probs = {
            'anytime_scorer': 0.25,
            '2_plus_goals': 0.08,
            'to_assist': 0.18
        }
        market_prob = default_market_probs.get(market, 0.20)
        
        decimal_odds = 1 / market_prob if market_prob > 0 else 4.0
        
        edge = (model_prob - market_prob) / market_prob if market_prob > 0 else 0
        
        market_names = {
            'anytime_scorer': 'Anytime Scorer',
            '2_plus_goals': '2+ Goals',
            'to_assist': 'To Record Assist'
        }
        
        return {
            'leg_type': 'player_prop',
            'match_id': match_info['match_id'],
            'home_team': match_info['home_team'],
            'away_team': match_info['away_team'],
            'league_name': match_info['league_name'],
            'kickoff_at': match_info['kickoff_at'],
            'player_id': player_id,
            'player_name': props['player_name'],
            'market': market,
            'market_name': market_names.get(market, market),
            'model_prob': round(model_prob, 4),
            'market_prob': round(market_prob, 4),
            'decimal_odds': round(decimal_odds, 2),
            'edge_pct': round(edge * 100, 1)
        }
    
    def _calculate_cross_market_correlation(self, legs: List[Dict]) -> float:
        """Calculate correlation penalty across all legs"""
        penalty = 0.0
        
        for i, leg1 in enumerate(legs):
            for leg2 in legs[i+1:]:
                if leg1['match_id'] == leg2['match_id']:
                    penalty += self._get_same_match_correlation(leg1, leg2)
                else:
                    if leg1.get('league_name') == leg2.get('league_name'):
                        penalty += SAME_LEAGUE_PENALTY
                    
                    if leg1.get('kickoff_at') and leg2.get('kickoff_at'):
                        time_diff = abs((leg1['kickoff_at'] - leg2['kickoff_at']).total_seconds())
                        if time_diff < 7200:
                            penalty += SAME_TIME_PENALTY
        
        favorites = sum(1 for leg in legs if leg.get('decimal_odds', 10) < 1.50)
        if favorites >= 2:
            penalty += FAVORITES_COMBO_PENALTY
        
        return min(penalty, 0.50)
    
    def _get_same_match_correlation(self, leg1: Dict, leg2: Dict) -> float:
        """Get correlation penalty for two legs from the same match"""
        type1 = leg1['leg_type']
        type2 = leg2['leg_type']
        market1 = leg1['market']
        market2 = leg2['market']
        
        key = (type1, market1, type2, market2)
        reverse_key = (type2, market2, type1, market1)
        
        correlation = CROSS_MARKET_CORRELATIONS.get(key) or CROSS_MARKET_CORRELATIONS.get(reverse_key)
        
        if correlation is not None:
            return abs(correlation) * 0.3
        
        return 0.15
    
    def _determine_confidence_tier(self, edge: float, correlation: float) -> str:
        """Determine confidence tier based on edge and correlation"""
        for tier, thresholds in CONFIDENCE_THRESHOLDS.items():
            if edge >= thresholds['min_edge'] and correlation <= thresholds['max_correlation']:
                return tier
        return 'low'
    
    def _generate_recommendation(self, edge: float, correlation: float, legs: List[Dict]) -> str:
        """Generate recommendation text"""
        leg_types = set(leg['leg_type'] for leg in legs)
        
        if edge > 0.10 and correlation < 0.15:
            return f"Strong value parlay with {edge*100:.1f}% edge and low correlation"
        elif edge > 0.05:
            if len(leg_types) > 1:
                return f"Diversified parlay across {len(leg_types)} market types with positive edge"
            return f"Positive edge parlay (+{edge*100:.1f}%)"
        elif edge > 0:
            return "Marginal edge - consider smaller stake"
        else:
            return f"Negative edge ({edge*100:.1f}%) - not recommended"
    
    def _get_leg_type_breakdown(self, legs: List[Dict]) -> Dict:
        """Get breakdown of leg types"""
        breakdown = {'match_result': 0, 'totals': 0, 'player_prop': 0}
        for leg in legs:
            leg_type = leg.get('leg_type', 'match_result')
            breakdown[leg_type] = breakdown.get(leg_type, 0) + 1
        return breakdown
    
    def generate_smart_parlays(self, max_parlays: int = 10, 
                                min_edge: float = 0.05) -> List[Dict]:
        """Generate AI-curated smart parlays across all market types"""
        all_legs = self._get_available_legs()
        
        if len(all_legs) < 2:
            return []
        
        positive_edge_legs = [leg for leg in all_legs if leg['edge_pct'] > 0]
        positive_edge_legs.sort(key=lambda x: x['edge_pct'], reverse=True)
        
        parlays = []
        
        for leg_count in [2, 3]:
            if len(positive_edge_legs) < leg_count:
                continue
            
            for combo in combinations(positive_edge_legs[:20], leg_count):
                selections = [
                    {
                        'leg_type': leg['leg_type'],
                        'match_id': leg['match_id'],
                        'market': leg['market'],
                        'player_id': leg.get('player_id')
                    }
                    for leg in combo
                ]
                
                parlay = self.build_custom_parlay(selections)
                
                if 'error' not in parlay and parlay['edge_pct'] >= min_edge * 100:
                    parlays.append(parlay)
        
        parlays.sort(key=lambda x: x['edge_pct'], reverse=True)
        return parlays[:max_parlays]
    
    def _get_available_legs(self) -> List[Dict]:
        """Get all available legs for parlay generation"""
        legs = []
        
        with self.engine.connect() as conn:
            result = conn.execute(text("""
                SELECT 
                    f.match_id,
                    f.home_team,
                    f.away_team,
                    f.league_name,
                    f.kickoff_at,
                    oc.ph_cons,
                    oc.pd_cons,
                    oc.pa_cons,
                    ps.probs_h,
                    ps.probs_d,
                    ps.probs_a
                FROM fixtures f
                JOIN odds_consensus oc ON f.match_id = oc.match_id
                LEFT JOIN (
                    SELECT DISTINCT ON (match_id) 
                        match_id, probs_h, probs_d, probs_a
                    FROM prediction_snapshots
                    ORDER BY match_id, served_at DESC
                ) ps ON f.match_id = ps.match_id
                WHERE f.status = 'scheduled'
                AND f.kickoff_at > NOW()
                AND f.kickoff_at < NOW() + INTERVAL '48 hours'
                AND oc.ph_cons IS NOT NULL
                LIMIT 50
            """))
            
            for row in result:
                for outcome in ['H', 'D', 'A']:
                    market_prob = getattr(row, f'p{outcome.lower()}_cons') or 0.33
                    model_prob = getattr(row, f'probs_{outcome.lower()}') or market_prob
                    
                    if market_prob > 0:
                        edge = (model_prob - market_prob) / market_prob * 100
                        decimal_odds = 1 / market_prob if market_prob > 0 else 2.0
                        
                        legs.append({
                            'leg_type': 'match_result',
                            'match_id': row.match_id,
                            'home_team': row.home_team,
                            'away_team': row.away_team,
                            'league_name': row.league_name,
                            'kickoff_at': row.kickoff_at,
                            'market': outcome,
                            'model_prob': model_prob,
                            'decimal_odds': decimal_odds,
                            'edge_pct': edge
                        })
                
                totals = self.totals_predictor.predict_match(row.match_id)
                if totals and totals.get('status') == 'available':
                    for market_key in ['over_2.5', 'under_2.5']:
                        ou_key = market_key.replace('.', '_')
                        model_prob = totals['over_under'].get(ou_key, 0.5)
                        market_prob = 0.52 if 'over' in market_key else 0.48
                        
                        if market_prob > 0:
                            edge = (model_prob - market_prob) / market_prob * 100
                            decimal_odds = 1 / market_prob
                            
                            legs.append({
                                'leg_type': 'totals',
                                'match_id': row.match_id,
                                'home_team': row.home_team,
                                'away_team': row.away_team,
                                'league_name': row.league_name,
                                'kickoff_at': row.kickoff_at,
                                'market': market_key,
                                'model_prob': model_prob,
                                'decimal_odds': decimal_odds,
                                'edge_pct': edge
                            })
        
        return legs
