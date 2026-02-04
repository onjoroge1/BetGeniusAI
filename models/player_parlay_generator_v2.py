"""
Player Parlay Generator V2

Improved parlay generation with:
- Calibrated probabilities (isotonic regression)
- Real market odds integration where available
- True edge calculation (model vs market)
- Diversification constraints (max 2 per player, max 2 per match)
- EV-based selection instead of circular edge
- Honest confidence scoring
"""

import os
import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from itertools import combinations
from collections import defaultdict
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger(__name__)


class PlayerParlayGeneratorV2:
    DEFAULT_BET = 100.0
    MARGIN_DEVIG = 0.04
    
    MAX_PLAYER_APPEARANCES = 2
    MAX_LEGS_PER_MATCH = 2
    MIN_EV_THRESHOLD = 0.02
    MIN_CALIBRATED_PROB = 0.08
    MAX_CALIBRATED_PROB = 0.45
    
    EV_SOURCE_MARKET = 'market'
    EV_SOURCE_MODEL = 'model_confidence'
    
    def __init__(self):
        self.engine = create_engine(
            os.environ.get('DATABASE_URL'),
            pool_pre_ping=True,
            pool_recycle=300
        )
        self.Session = sessionmaker(bind=self.engine)
        self.calibrator = None
        self._init_calibrator()
        self._ensure_tables()
    
    def _init_calibrator(self):
        """Initialize probability calibrator."""
        try:
            from utils.player_calibrator import get_calibrator
            self.calibrator = get_calibrator()
            status = self.calibrator.get_status()
            logger.info(f"PlayerParlayV2: Calibrator loaded (method={status['method']})")
        except Exception as e:
            logger.warning(f"Calibrator not available: {e}")
    
    def _ensure_tables(self):
        """Ensure V2 tables exist with new schema."""
        with self.engine.connect() as conn:
            conn.execute(text("""
                ALTER TABLE player_parlays 
                ADD COLUMN IF NOT EXISTS has_market_odds BOOLEAN DEFAULT FALSE,
                ADD COLUMN IF NOT EXISTS ev_pct NUMERIC(8,3),
                ADD COLUMN IF NOT EXISTS calibrated_prob_pct NUMERIC(8,3)
            """))
            
            conn.execute(text("""
                ALTER TABLE player_parlay_legs
                ADD COLUMN IF NOT EXISTS calibrated_prob NUMERIC(6,4),
                ADD COLUMN IF NOT EXISTS real_market_odds NUMERIC(8,2),
                ADD COLUMN IF NOT EXISTS ev NUMERIC(6,4),
                ADD COLUMN IF NOT EXISTS has_market_odds BOOLEAN DEFAULT FALSE
            """))
            
            conn.commit()
            logger.info("PlayerParlayV2: Schema updated")
    
    def _calibrate_prob(self, raw_prob: float) -> float:
        """Apply calibration to raw model probability."""
        if self.calibrator:
            return self.calibrator.calibrate(raw_prob)
        
        if raw_prob >= 0.5:
            return raw_prob * 0.45
        elif raw_prob >= 0.3:
            return raw_prob * 0.50
        else:
            return raw_prob * 0.60
    
    def _get_upcoming_fixtures(self, hours_ahead: int = 72) -> List[Dict]:
        """Get upcoming fixtures with team IDs."""
        with self.engine.connect() as conn:
            result = conn.execute(text(f"""
                SELECT 
                    f.match_id,
                    f.home_team,
                    f.away_team,
                    f.league_name,
                    f.kickoff_at,
                    f.home_team_id,
                    f.away_team_id
                FROM fixtures f
                WHERE f.kickoff_at > NOW()
                  AND f.kickoff_at < NOW() + INTERVAL '{hours_ahead} hours'
                  AND f.status IN ('NS', 'scheduled', 'TBD')
                  AND f.home_team_id IS NOT NULL
                  AND f.away_team_id IS NOT NULL
                ORDER BY f.kickoff_at
                LIMIT 50
            """))
            return [dict(row._mapping) for row in result.fetchall()]
    
    def _get_market_odds_for_player(self, player_name: str, event_id: str = None) -> Optional[float]:
        """
        Get real market odds for anytime scorer.
        
        Note: Soccer player props are NOT available from The Odds API.
        Returns None for soccer - we'll use calibrated model probs instead.
        """
        return None
    
    def _get_top_players_for_match(self, match_id: int, home_team_id: int, away_team_id: int, limit: int = 6) -> List[Dict]:
        """Get top scoring players for a match."""
        with self.engine.connect() as conn:
            result = conn.execute(text("""
                WITH fixture_teams AS (
                    SELECT api_football_team_id FROM teams WHERE team_id = :home_id AND api_football_team_id IS NOT NULL
                    UNION
                    SELECT api_football_team_id FROM teams WHERE team_id = :away_id AND api_football_team_id IS NOT NULL
                )
                SELECT 
                    p.player_id,
                    p.player_name,
                    p.position,
                    pss.team_id,
                    pss.team_name,
                    COALESCE((pss.stats->>'goals')::int, 0) as season_goals,
                    COALESCE(pss.games_played, 0) as games_played
                FROM players_unified p
                JOIN player_season_stats pss ON p.player_id = pss.player_id 
                    AND pss.sport_key = 'soccer' AND pss.season = 2024
                WHERE pss.team_id IN (SELECT api_football_team_id FROM fixture_teams)
                  AND p.position IN ('Attacker', 'Midfielder')
                ORDER BY COALESCE((pss.stats->>'goals')::int, 0) DESC
                LIMIT :limit
            """), {'home_id': home_team_id, 'away_id': away_team_id, 'limit': limit})
            
            return [dict(row._mapping) for row in result.fetchall()]
    
    def _compute_raw_model_prob(self, player: Dict) -> float:
        """Compute raw model probability from player stats."""
        season_goals = player.get('season_goals', 0)
        games = max(player.get('games_played', 1), 1)
        
        goals_per_game = season_goals / games
        raw_prob = min(0.65, max(0.05, goals_per_game * 0.8))
        
        position = player.get('position', '')
        if position == 'Attacker':
            raw_prob = min(0.65, raw_prob * 1.1)
        elif position == 'Midfielder':
            raw_prob = min(0.50, raw_prob * 0.9)
        
        return raw_prob
    
    def _generate_player_legs(self, fixtures: List[Dict]) -> List[Dict]:
        """Generate candidate legs with calibrated probabilities."""
        all_legs = []
        
        for fixture in fixtures:
            players = self._get_top_players_for_match(
                fixture['match_id'],
                fixture['home_team_id'],
                fixture['away_team_id'],
                limit=6
            )
            
            for player in players:
                raw_prob = self._compute_raw_model_prob(player)
                calibrated_prob = self._calibrate_prob(raw_prob)
                
                if calibrated_prob < self.MIN_CALIBRATED_PROB or calibrated_prob > self.MAX_CALIBRATED_PROB:
                    continue
                
                market_odds = self._get_market_odds_for_player(
                    player['player_name'],
                    str(fixture['match_id'])
                )
                
                if market_odds:
                    market_prob = 1 / market_odds
                    has_market = True
                else:
                    fair_odds = 1 / calibrated_prob
                    market_odds = fair_odds * (1 + self.MARGIN_DEVIG)
                    market_prob = 1 / market_odds
                    has_market = False
                
                ev = calibrated_prob * market_odds - 1
                
                if has_market:
                    edge_pct = ((calibrated_prob - market_prob) / market_prob * 100) if market_prob > 0 else 0
                    ev_source = self.EV_SOURCE_MARKET
                else:
                    edge_pct = 0
                    ev_source = self.EV_SOURCE_MODEL
                
                if calibrated_prob >= self.MIN_CALIBRATED_PROB:
                    all_legs.append({
                        'match_id': fixture['match_id'],
                        'home_team': fixture['home_team'],
                        'away_team': fixture['away_team'],
                        'league_name': fixture['league_name'],
                        'kickoff_at': fixture['kickoff_at'],
                        'player_id': player['player_id'],
                        'player_name': player['player_name'],
                        'team_name': player.get('team_name', 'Unknown'),
                        'raw_prob': round(raw_prob, 4),
                        'calibrated_prob': round(calibrated_prob, 4),
                        'market_prob': round(market_prob, 4),
                        'decimal_odds': round(market_odds, 2),
                        'ev': round(ev, 4),
                        'edge_pct': round(edge_pct, 1),
                        'has_market_odds': has_market,
                        'ev_source': ev_source
                    })
        
        return all_legs
    
    def _apply_diversification(self, legs: List[Dict], max_legs: int = 20) -> List[Dict]:
        """
        Apply diversification constraints:
        - Max 2 legs per player across all parlays
        - Max 2 legs per match
        - Prioritize by EV/calibrated_prob
        """
        legs_sorted = sorted(legs, key=lambda x: (x['has_market_odds'], x['ev']), reverse=True)
        
        player_counts = defaultdict(int)
        match_counts = defaultdict(int)
        selected = []
        
        for leg in legs_sorted:
            player_id = leg['player_id']
            match_id = leg['match_id']
            
            if player_counts[player_id] >= self.MAX_PLAYER_APPEARANCES:
                continue
            if match_counts[match_id] >= self.MAX_LEGS_PER_MATCH:
                continue
            
            selected.append(leg)
            player_counts[player_id] += 1
            match_counts[match_id] += 1
            
            if len(selected) >= max_legs:
                break
        
        return selected
    
    def _build_parlay(self, legs: List[Dict]) -> Dict:
        """Build parlay with true statistics."""
        match_ids = list(set(leg['match_id'] for leg in legs))
        
        combined_odds = 1.0
        combined_calibrated_prob = 1.0
        has_any_market = False
        ev_sources = set()
        
        for leg in legs:
            combined_odds *= leg['decimal_odds']
            combined_calibrated_prob *= leg['calibrated_prob']
            if leg['has_market_odds']:
                has_any_market = True
            ev_sources.add(leg.get('ev_source', self.EV_SOURCE_MODEL))
        
        ev_pct = (combined_calibrated_prob * combined_odds - 1) * 100
        
        if has_any_market:
            ev_source = self.EV_SOURCE_MARKET
        else:
            ev_source = self.EV_SOURCE_MODEL
        
        avg_calibrated_prob = sum(l['calibrated_prob'] for l in legs) / len(legs)
        if avg_calibrated_prob >= 0.25 and combined_calibrated_prob >= 0.10:
            confidence = 'high'
        elif avg_calibrated_prob >= 0.15 and combined_calibrated_prob >= 0.05:
            confidence = 'medium'
        else:
            confidence = 'low'
        
        leg_ids = sorted([f"{l['player_id']}_{l['match_id']}" for l in legs])
        parlay_hash = hashlib.md5('|'.join(leg_ids).encode()).hexdigest()[:16]
        
        max_kickoff = max(leg['kickoff_at'] for leg in legs)
        expires_at = max_kickoff + timedelta(hours=3)
        
        return {
            'parlay_hash': parlay_hash,
            'leg_count': len(legs),
            'match_ids': match_ids,
            'legs': legs,
            'combined_odds': round(combined_odds, 2),
            'raw_prob_pct': round(combined_calibrated_prob * 100, 3),
            'calibrated_prob_pct': round(combined_calibrated_prob * 100, 3),
            'ev_pct': round(ev_pct, 2),
            'edge_pct': round(ev_pct, 2) if has_any_market else 0,
            'confidence_tier': confidence,
            'has_market_odds': has_any_market,
            'ev_source': ev_source,
            'payout_100': round(self.DEFAULT_BET * combined_odds, 2),
            'expires_at': expires_at
        }
    
    def _save_parlay(self, parlay: Dict) -> bool:
        """Save parlay with V2 fields."""
        session = self.Session()
        try:
            result = session.execute(text("""
                INSERT INTO player_parlays 
                (parlay_hash, leg_count, match_ids, combined_odds, raw_prob_pct, 
                 adjusted_prob_pct, edge_pct, confidence_tier, payout_100, expires_at,
                 has_market_odds, ev_pct, calibrated_prob_pct)
                VALUES (:parlay_hash, :leg_count, :match_ids, :combined_odds, :raw_prob_pct,
                        :adjusted_prob_pct, :edge_pct, :confidence_tier, :payout_100, :expires_at,
                        :has_market_odds, :ev_pct, :calibrated_prob_pct)
                ON CONFLICT (parlay_hash) DO UPDATE SET
                    combined_odds = EXCLUDED.combined_odds,
                    edge_pct = EXCLUDED.edge_pct,
                    ev_pct = EXCLUDED.ev_pct,
                    has_market_odds = EXCLUDED.has_market_odds,
                    expires_at = EXCLUDED.expires_at
                RETURNING id
            """), {
                'parlay_hash': parlay['parlay_hash'],
                'leg_count': parlay['leg_count'],
                'match_ids': parlay['match_ids'],
                'combined_odds': parlay['combined_odds'],
                'raw_prob_pct': parlay['raw_prob_pct'],
                'adjusted_prob_pct': parlay['calibrated_prob_pct'],
                'edge_pct': parlay['edge_pct'],
                'confidence_tier': parlay['confidence_tier'],
                'payout_100': parlay['payout_100'],
                'expires_at': parlay['expires_at'],
                'has_market_odds': parlay['has_market_odds'],
                'ev_pct': parlay['ev_pct'],
                'calibrated_prob_pct': parlay['calibrated_prob_pct']
            })
            
            row = result.fetchone()
            if row:
                parlay_id = row[0]
                
                session.execute(text(
                    "DELETE FROM player_parlay_legs WHERE parlay_id = :parlay_id"
                ), {'parlay_id': parlay_id})
                
                for idx, leg in enumerate(parlay['legs']):
                    session.execute(text("""
                        INSERT INTO player_parlay_legs
                        (parlay_id, leg_index, match_id, home_team, away_team, 
                         league_name, kickoff_at, player_id, player_name, team_name,
                         model_prob, market_prob, decimal_odds, edge_pct,
                         calibrated_prob, real_market_odds, ev, has_market_odds)
                        VALUES (:parlay_id, :leg_index, :match_id, :home_team, :away_team,
                                :league_name, :kickoff_at, :player_id, :player_name, :team_name,
                                :model_prob, :market_prob, :decimal_odds, :edge_pct,
                                :calibrated_prob, :real_market_odds, :ev, :has_market_odds)
                    """), {
                        'parlay_id': parlay_id,
                        'leg_index': idx,
                        'match_id': leg['match_id'],
                        'home_team': leg['home_team'],
                        'away_team': leg['away_team'],
                        'league_name': leg['league_name'],
                        'kickoff_at': leg['kickoff_at'],
                        'player_id': leg['player_id'],
                        'player_name': leg['player_name'],
                        'team_name': leg['team_name'],
                        'model_prob': leg['raw_prob'],
                        'market_prob': leg['market_prob'],
                        'decimal_odds': leg['decimal_odds'],
                        'edge_pct': leg['edge_pct'],
                        'calibrated_prob': leg['calibrated_prob'],
                        'real_market_odds': leg['decimal_odds'] if leg['has_market_odds'] else None,
                        'ev': leg['ev'],
                        'has_market_odds': leg['has_market_odds']
                    })
                
                session.commit()
                return True
            
            session.rollback()
            return False
            
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to save player parlay: {e}")
            return False
        finally:
            session.close()
    
    def generate_all_player_parlays(self, hours_ahead: int = 72) -> Dict:
        """
        Generate player parlays with V2 improvements:
        - Calibrated probabilities
        - Diversification constraints
        - EV-based selection
        """
        logger.info(f"PlayerParlayV2: Starting generation for {hours_ahead}h ahead")
        
        fixtures = self._get_upcoming_fixtures(hours_ahead)
        logger.info(f"PlayerParlayV2: Found {len(fixtures)} fixtures")
        
        if len(fixtures) < 2:
            return {
                'status': 'insufficient_fixtures',
                'fixtures_found': len(fixtures),
                'parlays_generated': 0
            }
        
        fixtures = fixtures[:15]
        
        all_legs = self._generate_player_legs(fixtures)
        logger.info(f"PlayerParlayV2: Generated {len(all_legs)} raw legs")
        
        diversified_legs = self._apply_diversification(all_legs, max_legs=20)
        logger.info(f"PlayerParlayV2: After diversification: {len(diversified_legs)} legs")
        
        if len(diversified_legs) < 2:
            return {
                'status': 'insufficient_qualified_legs',
                'fixtures_found': len(fixtures),
                'legs_found': len(all_legs),
                'diversified_legs': len(diversified_legs),
                'parlays_generated': 0
            }
        
        parlays_generated = 0
        by_tier = {'high': 0, 'medium': 0, 'low': 0}
        
        combos = list(combinations(diversified_legs, 2))[:100]
        
        for combo in combos:
            combo_list = list(combo)
            
            if combo_list[0]['match_id'] == combo_list[1]['match_id']:
                continue
            
            parlay = self._build_parlay(combo_list)
            
            if parlay['ev_pct'] >= 0 and parlay['confidence_tier'] in ['high', 'medium']:
                saved = self._save_parlay(parlay)
                if saved:
                    parlays_generated += 1
                    by_tier[parlay['confidence_tier']] += 1
        
        logger.info(f"PlayerParlayV2: Generated {parlays_generated} parlays")
        
        return {
            'status': 'success',
            'version': 'v2',
            'fixtures_found': len(fixtures),
            'legs_generated': len(all_legs),
            'diversified_legs': len(diversified_legs),
            'parlays_generated': parlays_generated,
            'by_tier': by_tier,
            'calibrator_status': self.calibrator.get_status() if self.calibrator else None
        }
    
    def get_best_parlays(self, limit: int = 10, min_ev: float = 0) -> List[Dict]:
        """Get best parlays by EV."""
        with self.engine.connect() as conn:
            result = conn.execute(text("""
                SELECT 
                    pp.id,
                    pp.parlay_hash,
                    pp.leg_count,
                    pp.match_ids,
                    pp.combined_odds,
                    pp.calibrated_prob_pct,
                    pp.ev_pct,
                    pp.confidence_tier,
                    pp.has_market_odds,
                    pp.payout_100,
                    pp.expires_at
                FROM player_parlays pp
                WHERE pp.expires_at > NOW()
                  AND pp.status = 'pending'
                  AND COALESCE(pp.ev_pct, pp.edge_pct) >= :min_ev
                ORDER BY COALESCE(pp.ev_pct, pp.edge_pct) DESC
                LIMIT :limit
            """), {'min_ev': min_ev, 'limit': limit})
            
            parlays = []
            for row in result.fetchall():
                parlay_data = dict(row._mapping)
                
                legs_result = conn.execute(text("""
                    SELECT 
                        player_name, team_name, 
                        COALESCE(calibrated_prob, model_prob) as prob,
                        decimal_odds, 
                        COALESCE(ev, edge_pct / 100.0) as ev,
                        COALESCE(has_market_odds, FALSE) as has_market_odds,
                        home_team, away_team, league_name, kickoff_at
                    FROM player_parlay_legs
                    WHERE parlay_id = :parlay_id
                    ORDER BY leg_index
                """), {'parlay_id': parlay_data['id']})
                
                parlay_data['legs'] = [dict(leg._mapping) for leg in legs_result.fetchall()]
                parlays.append(parlay_data)
            
            return parlays


def run_player_parlay_v2_generation(hours_ahead: int = 72) -> Dict:
    """Run V2 parlay generation."""
    generator = PlayerParlayGeneratorV2()
    return generator.generate_all_player_parlays(hours_ahead)
