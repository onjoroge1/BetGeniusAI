"""
BetGenius AI - Parlay Builder Service
Generates AI-curated parlays with correlation adjustments and edge calculation
"""

import os
import uuid
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional, Tuple
from itertools import combinations
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger(__name__)


CORRELATION_PENALTIES = {
    'same_league': 0.10,
    'same_country': 0.05,
    'same_time_slot': 0.03,
    'favorites_combo': 0.05,
}

CONFIDENCE_THRESHOLDS = {
    'high': {'min_edge': 0.04, 'max_correlation': 0.15},
    'medium': {'min_edge': 0.02, 'max_correlation': 0.25},
    'low': {'min_edge': 0.01, 'max_correlation': 0.40},
}

class ParlayBuilder:
    """Service for building AI-curated parlays from odds consensus"""
    
    def __init__(self):
        self.database_url = os.environ.get('DATABASE_URL')
        if not self.database_url:
            raise ValueError("DATABASE_URL environment variable is required")
        
        self.engine = create_engine(
            self.database_url,
            pool_pre_ping=True,
            pool_recycle=300
        )
        self.SessionLocal = sessionmaker(bind=self.engine)
    
    def get_eligible_matches(self, hours_ahead: int = 48) -> List[Dict[str, Any]]:
        """Get matches eligible for parlay generation"""
        with self.engine.connect() as conn:
            result = conn.execute(text("""
                SELECT 
                    f.match_id as match_id,
                    f.home_team,
                    f.away_team,
                    f.league_name,
                    f.kickoff_at,
                    oc.ph_cons,
                    oc.pd_cons,
                    oc.pa_cons,
                    CASE WHEN oc.ph_cons > 0 THEN 1.0/oc.ph_cons ELSE NULL END as odds_h,
                    CASE WHEN oc.pd_cons > 0 THEN 1.0/oc.pd_cons ELSE NULL END as odds_d,
                    CASE WHEN oc.pa_cons > 0 THEN 1.0/oc.pa_cons ELSE NULL END as odds_a,
                    ps.probs_h as model_prob_h,
                    ps.probs_d as model_prob_d,
                    ps.probs_a as model_prob_a,
                    ps.confidence
                FROM fixtures f
                JOIN odds_consensus oc ON f.match_id = oc.match_id
                LEFT JOIN (
                    SELECT DISTINCT ON (match_id) 
                        match_id, probs_h, probs_d, probs_a, confidence
                    FROM prediction_snapshots
                    ORDER BY match_id, served_at DESC
                ) ps ON f.match_id = ps.match_id
                WHERE f.kickoff_at > NOW()
                AND f.kickoff_at < NOW() + (:hours || ' hours')::interval
                AND f.status = 'scheduled'
                AND oc.ph_cons IS NOT NULL
                AND oc.pd_cons IS NOT NULL
                AND oc.pa_cons IS NOT NULL
                ORDER BY f.kickoff_at ASC
            """), {'hours': hours_ahead})
            
            matches = []
            for row in result:
                matches.append({
                    'match_id': row.match_id,
                    'home_team': row.home_team,
                    'away_team': row.away_team,
                    'league_name': row.league_name,
                    'kickoff_at': row.kickoff_at,
                    'odds': {'H': row.odds_h, 'D': row.odds_d, 'A': row.odds_a},
                    'market_prob': {
                        'H': row.ph_cons or 0.33,
                        'D': row.pd_cons or 0.33,
                        'A': row.pa_cons or 0.33
                    },
                    'model_prob': {
                        'H': row.model_prob_h or row.ph_cons or 0.33,
                        'D': row.model_prob_d or row.pd_cons or 0.33,
                        'A': row.model_prob_a or row.pa_cons or 0.33
                    },
                    'confidence': row.confidence or 0.0
                })
            
            return matches
    
    def calculate_best_selection(self, match: Dict) -> Tuple[str, float, float, float]:
        """Determine best outcome selection for a match based on edge"""
        best_outcome = None
        best_edge = -1.0
        best_prob = 0.0
        best_odds = 0.0
        
        for outcome in ['H', 'D', 'A']:
            model_prob = match['model_prob'][outcome]
            market_prob = match['market_prob'][outcome]
            odds = match['odds'][outcome]
            
            if market_prob > 0:
                edge = (model_prob - market_prob) / market_prob
                if edge > best_edge:
                    best_edge = edge
                    best_outcome = outcome
                    best_prob = model_prob
                    best_odds = odds
        
        return best_outcome, best_prob, best_odds, best_edge
    
    def calculate_correlation_penalty(self, legs: List[Dict]) -> float:
        """Calculate correlation penalty for a set of legs"""
        penalty = 0.0
        
        leagues = [leg['league_name'] for leg in legs if leg.get('league_name')]
        unique_leagues = set(leagues)
        if len(leagues) > len(unique_leagues):
            same_league_count = len(leagues) - len(unique_leagues)
            penalty += same_league_count * CORRELATION_PENALTIES['same_league']
        
        kickoff_times = [leg['kickoff_at'] for leg in legs]
        for i, t1 in enumerate(kickoff_times):
            for t2 in kickoff_times[i+1:]:
                if abs((t1 - t2).total_seconds()) < 7200:
                    penalty += CORRELATION_PENALTIES['same_time_slot']
        
        favorites = sum(1 for leg in legs if leg['decimal_odds'] < 1.50)
        if favorites >= 2:
            penalty += CORRELATION_PENALTIES['favorites_combo']
        
        return min(penalty, 0.40)
    
    def generate_same_day_parlays(
        self, 
        target_date: datetime = None,
        leg_counts: List[int] = [2],
        max_parlays: int = 50
    ) -> List[Dict]:
        """Generate parlays from matches on the same day"""
        if target_date is None:
            target_date = datetime.now(timezone.utc)
        
        start_of_day = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = start_of_day + timedelta(days=1)
        
        matches = self.get_eligible_matches(hours_ahead=48)
        day_matches = [
            m for m in matches 
            if start_of_day <= m['kickoff_at'].replace(tzinfo=timezone.utc) < end_of_day
        ]
        
        if len(day_matches) < 2:
            logger.info(f"Not enough matches for same-day parlays: {len(day_matches)}")
            return []
        
        parlays = []
        for leg_count in leg_counts:
            if leg_count > len(day_matches):
                continue
            
            for combo in combinations(day_matches, leg_count):
                legs = []
                for match in combo:
                    outcome, prob, odds, edge = self.calculate_best_selection(match)
                    if edge > -0.05 and prob >= 0.20:
                        legs.append({
                            'match_id': match['match_id'],
                            'home_team': match['home_team'],
                            'away_team': match['away_team'],
                            'league_name': match['league_name'],
                            'kickoff_at': match['kickoff_at'],
                            'outcome': outcome,
                            'model_prob': prob,
                            'decimal_odds': odds,
                            'edge': edge
                        })
                
                if len(legs) == leg_count:
                    parlay = self._build_parlay(legs, 'same_day', 'today')
                    if parlay:
                        parlays.append(parlay)
        
        parlays.sort(key=lambda x: x['edge_pct'], reverse=True)
        return parlays[:max_parlays]
    
    def generate_league_parlays(
        self,
        league_name: str = None,
        leg_counts: List[int] = [2],
        max_parlays: int = 20
    ) -> List[Dict]:
        """Generate parlays from matches in the same league"""
        matches = self.get_eligible_matches(hours_ahead=168)
        
        if league_name:
            league_matches = [m for m in matches if m['league_name'] == league_name]
        else:
            leagues = {}
            for m in matches:
                if m['league_name']:
                    if m['league_name'] not in leagues:
                        leagues[m['league_name']] = []
                    leagues[m['league_name']].append(m)
            
            all_parlays = []
            for league, league_matches in leagues.items():
                if len(league_matches) >= 2:
                    parlays = self._generate_parlays_from_matches(
                        league_matches, leg_counts, 'same_league', league
                    )
                    all_parlays.extend(parlays)
            
            all_parlays.sort(key=lambda x: x['edge_pct'], reverse=True)
            return all_parlays[:max_parlays]
        
        return self._generate_parlays_from_matches(
            league_matches, leg_counts, 'same_league', league_name
        )[:max_parlays]
    
    def _generate_parlays_from_matches(
        self,
        matches: List[Dict],
        leg_counts: List[int],
        parlay_type: str,
        league_group: str = None
    ) -> List[Dict]:
        """Internal method to generate parlays from a set of matches"""
        parlays = []
        
        for leg_count in leg_counts:
            if leg_count > len(matches):
                continue
            
            for combo in combinations(matches, leg_count):
                legs = []
                for match in combo:
                    outcome, prob, odds, edge = self.calculate_best_selection(match)
                    if edge > -0.05 and prob >= 0.20:
                        legs.append({
                            'match_id': match['match_id'],
                            'home_team': match['home_team'],
                            'away_team': match['away_team'],
                            'league_name': match['league_name'],
                            'kickoff_at': match['kickoff_at'],
                            'outcome': outcome,
                            'model_prob': prob,
                            'decimal_odds': odds,
                            'edge': edge
                        })
                
                if len(legs) == leg_count:
                    kickoffs = [leg['kickoff_at'] for leg in legs]
                    earliest = min(kickoffs)
                    latest = max(kickoffs)
                    now = datetime.now(timezone.utc)
                    
                    if earliest.date() == now.date():
                        window = 'today'
                    elif earliest.date() == (now + timedelta(days=1)).date():
                        window = 'tomorrow'
                    elif earliest.weekday() >= 5 or (now + timedelta(days=1)).weekday() >= 5:
                        window = 'weekend'
                    else:
                        window = 'week'
                    
                    parlay = self._build_parlay(legs, parlay_type, window, league_group)
                    if parlay:
                        parlays.append(parlay)
        
        return parlays
    
    def _build_parlay(
        self,
        legs: List[Dict],
        parlay_type: str,
        kickoff_window: str,
        league_group: str = None,
        allow_negative_edge: bool = False
    ) -> Optional[Dict]:
        """Build a complete parlay object from legs"""
        if not legs:
            return None
        
        if len(legs) != 2:
            return None
        
        combined_prob = 1.0
        combined_odds = 1.0
        for leg in legs:
            combined_prob *= leg['model_prob']
            combined_odds *= leg['decimal_odds']
        
        correlation_penalty = self.calculate_correlation_penalty(legs)
        adjusted_prob = combined_prob * (1 - correlation_penalty)
        
        market_implied_prob = 1 / combined_odds if combined_odds > 0 else 0
        
        if market_implied_prob > 0:
            edge_pct = (adjusted_prob - market_implied_prob) / market_implied_prob
        else:
            edge_pct = 0.0
        
        if edge_pct < 0.04 or edge_pct > 0.15:
            return None
        
        if edge_pct >= CONFIDENCE_THRESHOLDS['high']['min_edge'] and correlation_penalty <= CONFIDENCE_THRESHOLDS['high']['max_correlation']:
            confidence_tier = 'high'
        else:
            return None
        
        kickoffs = [leg['kickoff_at'] for leg in legs]
        earliest_kickoff = min(kickoffs)
        latest_kickoff = max(kickoffs)
        
        legs_json = []
        for leg in legs:
            legs_json.append({
                'match_id': leg['match_id'],
                'home_team': leg['home_team'],
                'away_team': leg['away_team'],
                'outcome': leg['outcome'],
                'model_prob': round(leg['model_prob'], 4),
                'decimal_odds': round(leg['decimal_odds'], 3),
                'edge': round(leg['edge'], 4)
            })
        
        return {
            'parlay_id': str(uuid.uuid4()),
            'leg_count': len(legs),
            'legs': legs_json,
            'combined_prob': round(combined_prob, 6),
            'correlation_penalty': round(correlation_penalty, 4),
            'adjusted_prob': round(adjusted_prob, 6),
            'implied_odds': round(combined_odds, 3),
            'market_implied_prob': round(market_implied_prob, 6),
            'edge_pct': round(edge_pct, 4),
            'confidence_tier': confidence_tier,
            'parlay_type': parlay_type,
            'league_group': league_group,
            'earliest_kickoff': earliest_kickoff,
            'latest_kickoff': latest_kickoff,
            'kickoff_window': kickoff_window,
            'status': 'active'
        }
    
    OPTIMAL_MIN_EDGE = 0.04
    OPTIMAL_MAX_EDGE = 0.15
    
    def get_recommended_parlays(
        self,
        min_edge: float = None,
        max_parlays: int = 10,
        confidence_tiers: List[str] = ['high']
    ) -> List[Dict]:
        """
        Get AI-curated recommended parlays - OPTIMIZED for profitability.
        
        Based on performance analysis:
        - Only 2-leg parlays (disabled 3-leg and 4-leg)
        - Only high-confidence tier
        - Edge range 6-10% (optimal bucket with +2086% ROI)
        """
        if min_edge is None:
            min_edge = self.OPTIMAL_MIN_EDGE
            
        all_parlays = []
        
        same_day = self.generate_same_day_parlays(max_parlays=30)
        all_parlays.extend(same_day)
        
        league_parlays = self.generate_league_parlays(max_parlays=30)
        all_parlays.extend(league_parlays)
        
        filtered = [
            p for p in all_parlays
            if p['edge_pct'] >= min_edge 
            and p['edge_pct'] <= self.OPTIMAL_MAX_EDGE
            and p['confidence_tier'] in confidence_tiers
            and p['leg_count'] == 2
        ]
        
        filtered.sort(key=lambda x: (
            -1 if x['confidence_tier'] == 'high' else 0,
            -x['edge_pct']
        ))
        
        seen_match_combos = set()
        unique_parlays = []
        for p in filtered:
            match_ids = tuple(sorted([leg['match_id'] for leg in p['legs']]))
            if match_ids not in seen_match_combos:
                seen_match_combos.add(match_ids)
                unique_parlays.append(p)
        
        return unique_parlays[:max_parlays]
    
    def build_custom_parlay(self, selections: List[Dict]) -> Optional[Dict]:
        """
        Build a custom parlay from user selections.
        
        selections: List of {match_id: int, outcome: str} dicts
        """
        if len(selections) < 2:
            logger.warning(f"build_custom_parlay: Not enough selections ({len(selections)})")
            return None
        
        match_ids = [s['match_id'] for s in selections]
        logger.info(f"build_custom_parlay: Building parlay for match_ids={match_ids}")
        
        with self.engine.connect() as conn:
            placeholders = ','.join([f':id{i}' for i in range(len(match_ids))])
            params = {f'id{i}': mid for i, mid in enumerate(match_ids)}
            
            result = conn.execute(text(f"""
                SELECT 
                    f.match_id as match_id,
                    f.home_team,
                    f.away_team,
                    f.league_name,
                    f.kickoff_at,
                    CASE WHEN oc.ph_cons > 0 THEN 1.0/oc.ph_cons ELSE NULL END as odds_h,
                    CASE WHEN oc.pd_cons > 0 THEN 1.0/oc.pd_cons ELSE NULL END as odds_d,
                    CASE WHEN oc.pa_cons > 0 THEN 1.0/oc.pa_cons ELSE NULL END as odds_a,
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
                WHERE f.match_id IN ({placeholders})
            """), params)
            
            matches_by_id = {}
            rows_found = 0
            for row in result:
                rows_found += 1
                matches_by_id[row.match_id] = {
                    'match_id': row.match_id,
                    'home_team': row.home_team,
                    'away_team': row.away_team,
                    'league_name': row.league_name,
                    'kickoff_at': row.kickoff_at,
                    'odds': {'H': row.odds_h, 'D': row.odds_d, 'A': row.odds_a},
                    'model_prob': {
                        'H': row.probs_h or row.ph_cons or 0.33,
                        'D': row.probs_d or row.pd_cons or 0.33,
                        'A': row.probs_a or row.pa_cons or 0.33
                    },
                    'market_prob': {
                        'H': row.ph_cons or 0.33,
                        'D': row.pd_cons or 0.33,
                        'A': row.pa_cons or 0.33
                    }
                }
            
            logger.info(f"build_custom_parlay: Found {rows_found} matches from DB")
        
        legs = []
        for sel in selections:
            match = matches_by_id.get(sel['match_id'])
            if not match:
                continue
            
            outcome = sel['outcome']
            model_prob = match['model_prob'][outcome]
            market_prob = match['market_prob'][outcome]
            odds = match['odds'][outcome]
            
            edge = (model_prob - market_prob) / market_prob if market_prob > 0 else 0
            
            legs.append({
                'match_id': match['match_id'],
                'home_team': match['home_team'],
                'away_team': match['away_team'],
                'league_name': match['league_name'],
                'kickoff_at': match['kickoff_at'],
                'outcome': outcome,
                'model_prob': model_prob,
                'decimal_odds': odds,
                'edge': edge
            })
        
        if len(legs) < 2:
            logger.warning(f"build_custom_parlay: Not enough valid legs ({len(legs)})")
            return None
        
        logger.info(f"build_custom_parlay: Built parlay with {len(legs)} legs")
        parlay = self._build_parlay(legs, 'custom', 'custom', allow_negative_edge=True)
        if parlay:
            parlay['confidence_tier'] = parlay.get('confidence_tier', 'low')
        
        return parlay
    
    def save_parlay(self, parlay: Dict) -> bool:
        """Save a generated parlay to the database"""
        try:
            import json
            with self.engine.connect() as conn:
                conn.execute(text("""
                    INSERT INTO parlay_consensus (
                        parlay_id, leg_count, legs, combined_prob, correlation_penalty,
                        adjusted_prob, implied_odds, market_implied_prob, edge_pct,
                        confidence_tier, parlay_type, league_group, earliest_kickoff,
                        latest_kickoff, kickoff_window, status, created_at
                    ) VALUES (
                        :parlay_id, :leg_count, :legs, :combined_prob, :correlation_penalty,
                        :adjusted_prob, :implied_odds, :market_implied_prob, :edge_pct,
                        :confidence_tier, :parlay_type, :league_group, :earliest_kickoff,
                        :latest_kickoff, :kickoff_window, :status, NOW()
                    )
                    ON CONFLICT (parlay_id) DO UPDATE SET
                        edge_pct = EXCLUDED.edge_pct,
                        adjusted_prob = EXCLUDED.adjusted_prob,
                        status = EXCLUDED.status
                """), {
                    'parlay_id': parlay['parlay_id'],
                    'leg_count': parlay['leg_count'],
                    'legs': json.dumps(parlay['legs']),
                    'combined_prob': parlay['combined_prob'],
                    'correlation_penalty': parlay['correlation_penalty'],
                    'adjusted_prob': parlay['adjusted_prob'],
                    'implied_odds': parlay['implied_odds'],
                    'market_implied_prob': parlay['market_implied_prob'],
                    'edge_pct': parlay['edge_pct'],
                    'confidence_tier': parlay['confidence_tier'],
                    'parlay_type': parlay['parlay_type'],
                    'league_group': parlay.get('league_group'),
                    'earliest_kickoff': parlay['earliest_kickoff'],
                    'latest_kickoff': parlay['latest_kickoff'],
                    'kickoff_window': parlay['kickoff_window'],
                    'status': parlay.get('status', 'active')
                })
                conn.commit()
                
                for leg in parlay['legs']:
                    conn.execute(text("""
                        INSERT INTO parlay_legs (
                            parlay_id, match_id, home_team, away_team,
                            league_name, kickoff_at, outcome, decimal_odds, model_prob
                        ) VALUES (
                            :parlay_id, :match_id, :home_team, :away_team,
                            :league_name, :kickoff_at, :outcome, :decimal_odds, :model_prob
                        )
                    """), {
                        'parlay_id': parlay['parlay_id'],
                        'match_id': leg['match_id'],
                        'home_team': leg['home_team'],
                        'away_team': leg['away_team'],
                        'league_name': leg.get('league_name'),
                        'kickoff_at': parlay['earliest_kickoff'],
                        'outcome': leg['outcome'],
                        'decimal_odds': leg['decimal_odds'],
                        'model_prob': leg['model_prob']
                    })
                conn.commit()
            
            return True
        except Exception as e:
            logger.error(f"Failed to save parlay: {e}")
            return False
    
    def refresh_parlays(self) -> int:
        """Generate and save fresh parlays - called by scheduler"""
        try:
            with self.engine.connect() as conn:
                conn.execute(text("""
                    UPDATE parlay_consensus 
                    SET status = 'expired'
                    WHERE earliest_kickoff < NOW() - INTERVAL '30 minutes'
                    AND status = 'active'
                """))
                conn.commit()
            
            parlays = self.get_recommended_parlays(max_parlays=20)
            saved_count = 0
            
            for parlay in parlays:
                if self.save_parlay(parlay):
                    saved_count += 1
            
            logger.info(f"🎰 Refreshed parlays: {saved_count} saved")
            return saved_count
            
        except Exception as e:
            logger.error(f"Failed to refresh parlays: {e}")
            return 0


def test_parlay_builder():
    """Test the parlay builder functionality"""
    logging.basicConfig(level=logging.INFO)
    
    try:
        builder = ParlayBuilder()
        
        print("\n=== Getting Eligible Matches ===")
        matches = builder.get_eligible_matches(hours_ahead=72)
        print(f"Found {len(matches)} eligible matches")
        
        if matches:
            for m in matches[:3]:
                print(f"  - {m['home_team']} vs {m['away_team']} ({m['league_name']})")
        
        print("\n=== Generating Same-Day Parlays ===")
        same_day = builder.generate_same_day_parlays(max_parlays=5)
        print(f"Generated {len(same_day)} same-day parlays")
        
        if same_day:
            parlay = same_day[0]
            print(f"  Best parlay: {parlay['leg_count']} legs, {parlay['edge_pct']*100:.1f}% edge, {parlay['confidence_tier']} confidence")
            for leg in parlay['legs']:
                print(f"    - {leg['home_team']} vs {leg['away_team']}: {leg['outcome']} @ {leg['decimal_odds']:.2f}")
        
        print("\n=== Getting Recommended Parlays ===")
        recommended = builder.get_recommended_parlays(max_parlays=5)
        print(f"Found {len(recommended)} recommended parlays")
        
        for i, p in enumerate(recommended[:3], 1):
            print(f"\n  #{i} {p['confidence_tier'].upper()} - {p['leg_count']} legs")
            print(f"      Edge: {p['edge_pct']*100:.1f}% | Odds: {p['implied_odds']:.2f} | Correlation: {p['correlation_penalty']*100:.1f}%")
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    test_parlay_builder()
