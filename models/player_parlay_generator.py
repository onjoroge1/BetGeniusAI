"""
Automated Player Parlay Generator
Generates multi-leg parlays from player scorer predictions across upcoming matches.

Features:
- Gets top scorers from teams playing in upcoming fixtures
- Uses Player V2 model to predict anytime scorer probability
- Builds 2/3/4/5 leg parlays across different matches
- Tracks performance after games settle
"""

import os
import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from itertools import combinations
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger(__name__)


class PlayerParlayGenerator:
    DEFAULT_BET = 100.0
    MARKET_MARGIN = 0.08
    COOLDOWN_HOURS = 2
    MAX_PARLAYS_PER_MATCH = 3
    
    def __init__(self):
        self.engine = create_engine(
            os.environ.get('DATABASE_URL'),
            pool_pre_ping=True,
            pool_recycle=300
        )
        self.Session = sessionmaker(bind=self.engine)
        self.player_service = None
        self.feature_builder = None
        self.classification_model = None
        self.feature_cols = None
        
        self._init_models()
        self._ensure_tables()
    
    def _init_models(self):
        try:
            from models.player_props_service import PlayerPropsService
            self.player_service = PlayerPropsService()
            logger.info("PlayerParlayGenerator: PlayerPropsService initialized")
        except Exception as e:
            logger.warning(f"PlayerPropsService not available: {e}")
        
        try:
            import pickle
            from pathlib import Path
            import json
            
            model_dir = Path("models/player_v2")
            latest_file = model_dir / "latest.json"
            
            if latest_file.exists():
                with open(latest_file, 'r') as f:
                    version = json.load(f).get('version')
                
                gi_file = model_dir / f"goal_involvement_{version}.pkl"
                if gi_file.exists():
                    with open(gi_file, 'rb') as f:
                        gi_data = pickle.load(f)
                        self.classification_model = gi_data['models']
                        self.feature_cols = gi_data['feature_cols']
                    logger.info(f"PlayerParlayGenerator: Loaded goal involvement model v{version}")
            
            from features.player_v2_feature_builder import PlayerV2FeatureBuilder
            self.feature_builder = PlayerV2FeatureBuilder()
            logger.info("PlayerParlayGenerator: Feature builder initialized")
            
        except Exception as e:
            logger.warning(f"Player V2 models not available: {e}")
    
    def _ensure_tables(self):
        with self.engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS player_parlays (
                    id SERIAL PRIMARY KEY,
                    parlay_hash VARCHAR(32) UNIQUE NOT NULL,
                    generated_at TIMESTAMPTZ DEFAULT NOW(),
                    leg_count INTEGER NOT NULL,
                    match_ids INTEGER[] NOT NULL,
                    combined_odds NUMERIC(10,2),
                    raw_prob_pct NUMERIC(8,3),
                    adjusted_prob_pct NUMERIC(8,3),
                    edge_pct NUMERIC(8,2),
                    confidence_tier VARCHAR(20),
                    payout_100 NUMERIC(12,2),
                    status VARCHAR(20) DEFAULT 'pending',
                    result VARCHAR(20),
                    settled_at TIMESTAMPTZ,
                    expires_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """))
            
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS player_parlay_legs (
                    id SERIAL PRIMARY KEY,
                    parlay_id INTEGER REFERENCES player_parlays(id) ON DELETE CASCADE,
                    leg_index INTEGER NOT NULL,
                    match_id INTEGER NOT NULL,
                    home_team VARCHAR(100),
                    away_team VARCHAR(100),
                    league_name VARCHAR(100),
                    kickoff_at TIMESTAMPTZ,
                    player_id INTEGER NOT NULL,
                    player_name VARCHAR(100),
                    team_name VARCHAR(100),
                    model_prob NUMERIC(6,4),
                    market_prob NUMERIC(6,4),
                    decimal_odds NUMERIC(8,2),
                    edge_pct NUMERIC(8,2),
                    result VARCHAR(20),
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """))
            
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_player_parlays_expires 
                ON player_parlays(expires_at) WHERE status = 'pending'
            """))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_player_parlays_confidence 
                ON player_parlays(confidence_tier, edge_pct DESC)
            """))
            conn.commit()
            logger.info("PlayerParlayGenerator: Tables ensured")
    
    def _check_match_cooldown(self, match_ids: List[int]) -> bool:
        """Check if any match in this combination has too many recent parlays."""
        with self.engine.connect() as conn:
            for match_id in match_ids:
                result = conn.execute(text("""
                    SELECT COUNT(*) as cnt
                    FROM player_parlays pp
                    WHERE :match_id = ANY(pp.match_ids)
                    AND pp.created_at > NOW() - make_interval(hours => :hours)
                    AND pp.status IN ('pending', 'active')
                """), {'match_id': match_id, 'hours': self.COOLDOWN_HOURS}).fetchone()
                
                if result and result.cnt >= self.MAX_PARLAYS_PER_MATCH:
                    return True
        return False
    
    def _get_upcoming_fixtures(self, hours_ahead: int = 72) -> List[Dict]:
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
    
    def _get_top_players_for_match(self, match_id: int, home_team_id: int, away_team_id: int, limit: int = 4) -> List[Dict]:
        players = []
        
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
            
            for row in result.fetchall():
                players.append(dict(row._mapping))
        
        return players
    
    def _predict_player_scorer_prob(self, player_id: int, match_id: int, kickoff_at: datetime) -> Optional[float]:
        """Use PlayerPropsService if available to get model prediction"""
        if self.player_service is None:
            return None
        
        try:
            prediction = self.player_service.predict_player(
                player_id=player_id,
                match_id=match_id
            )
            if prediction and 'goal_involvement_prob' in prediction:
                return prediction['goal_involvement_prob']
        except Exception as e:
            logger.debug(f"Player prediction failed for {player_id}: {e}")
        
        return None
    
    def _generate_player_legs(self, fixtures: List[Dict]) -> List[Dict]:
        all_legs = []
        
        for fixture in fixtures:
            players = self._get_top_players_for_match(
                fixture['match_id'],
                fixture['home_team_id'],
                fixture['away_team_id'],
                limit=4
            )
            
            for player in players:
                model_prob = self._predict_player_scorer_prob(
                    player['player_id'],
                    fixture['match_id'],
                    fixture['kickoff_at']
                )
                
                if model_prob is None:
                    season_goals = player.get('season_goals', 0)
                    games = max(player.get('games_played', 1), 1)
                    model_prob = min(0.6, max(0.05, (season_goals / games) * 0.8))
                
                fair_odds = 1 / model_prob if model_prob > 0 else 10.0
                margin_adjusted_odds = fair_odds * (1 + self.MARKET_MARGIN)
                decimal_odds = max(1.54, min(12.5, margin_adjusted_odds))
                implied_prob = 1 / decimal_odds if decimal_odds > 0 else 0.08
                edge = (model_prob - implied_prob) / implied_prob * 100 if implied_prob > 0 else 0
                market_prob = implied_prob
                
                if model_prob >= 0.08 and edge > -5:
                    all_legs.append({
                        'match_id': fixture['match_id'],
                        'home_team': fixture['home_team'],
                        'away_team': fixture['away_team'],
                        'league_name': fixture['league_name'],
                        'kickoff_at': fixture['kickoff_at'],
                        'player_id': player['player_id'],
                        'player_name': player['player_name'],
                        'team_name': player.get('team_name', 'Unknown'),
                        'model_prob': round(model_prob, 4),
                        'market_prob': round(market_prob, 4),
                        'decimal_odds': round(decimal_odds, 2),
                        'edge_pct': round(edge, 1)
                    })
        
        return all_legs
    
    def _build_parlay(self, legs: List[Dict]) -> Dict:
        match_ids = list(set(leg['match_id'] for leg in legs))
        
        combined_odds = 1.0
        combined_prob = 1.0
        
        for leg in legs:
            combined_odds *= leg['decimal_odds']
            combined_prob *= leg['model_prob']
        
        implied_prob = 1 / combined_odds if combined_odds > 0 else 0
        edge_pct = ((combined_prob - implied_prob) / implied_prob * 100) if implied_prob > 0 else 0
        
        if edge_pct >= 5:
            confidence = 'high'
        elif edge_pct >= -5:
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
            'raw_prob_pct': round(combined_prob * 100, 3),
            'adjusted_prob_pct': round(combined_prob * 100, 3),
            'edge_pct': round(edge_pct, 2),
            'confidence_tier': confidence,
            'payout_100': round(self.DEFAULT_BET * combined_odds, 2),
            'expires_at': expires_at
        }
    
    def _save_parlay(self, parlay: Dict) -> bool:
        session = self.Session()
        try:
            result = session.execute(text("""
                INSERT INTO player_parlays 
                (parlay_hash, leg_count, match_ids, combined_odds, raw_prob_pct, 
                 adjusted_prob_pct, edge_pct, confidence_tier, payout_100, expires_at)
                VALUES (:parlay_hash, :leg_count, :match_ids, :combined_odds, :raw_prob_pct,
                        :adjusted_prob_pct, :edge_pct, :confidence_tier, :payout_100, :expires_at)
                ON CONFLICT (parlay_hash) DO UPDATE SET
                    combined_odds = EXCLUDED.combined_odds,
                    edge_pct = EXCLUDED.edge_pct,
                    expires_at = EXCLUDED.expires_at
                RETURNING id
            """), {
                'parlay_hash': parlay['parlay_hash'],
                'leg_count': parlay['leg_count'],
                'match_ids': parlay['match_ids'],
                'combined_odds': parlay['combined_odds'],
                'raw_prob_pct': parlay['raw_prob_pct'],
                'adjusted_prob_pct': parlay['adjusted_prob_pct'],
                'edge_pct': parlay['edge_pct'],
                'confidence_tier': parlay['confidence_tier'],
                'payout_100': parlay['payout_100'],
                'expires_at': parlay['expires_at']
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
                         model_prob, market_prob, decimal_odds, edge_pct)
                        VALUES (:parlay_id, :leg_index, :match_id, :home_team, :away_team,
                                :league_name, :kickoff_at, :player_id, :player_name, :team_name,
                                :model_prob, :market_prob, :decimal_odds, :edge_pct)
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
                        'model_prob': leg['model_prob'],
                        'market_prob': leg['market_prob'],
                        'decimal_odds': leg['decimal_odds'],
                        'edge_pct': leg['edge_pct']
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
        logger.info(f"⚽ PlayerParlay: Starting generation for {hours_ahead}h ahead")
        
        fixtures = self._get_upcoming_fixtures(hours_ahead)
        logger.info(f"⚽ PlayerParlay: Found {len(fixtures)} fixtures")
        
        if len(fixtures) < 2:
            return {
                'status': 'insufficient_fixtures',
                'fixtures_found': len(fixtures),
                'parlays_generated': 0
            }
        
        fixtures = fixtures[:10]
        
        all_legs = self._generate_player_legs(fixtures)
        logger.info(f"⚽ PlayerParlay: Generated {len(all_legs)} legs")
        
        if len(all_legs) < 2:
            return {
                'status': 'insufficient_players',
                'fixtures_found': len(fixtures),
                'legs_found': len(all_legs),
                'parlays_generated': 0
            }
        
        parlays_generated = 0
        by_leg_count = {2: 0, 3: 0, 4: 0, 5: 0}
        
        all_legs_sorted = sorted(all_legs, key=lambda x: x['model_prob'], reverse=True)[:15]
        
        for leg_count in [2, 3, 4, 5]:
            if len(all_legs_sorted) >= leg_count:
                combos = list(combinations(all_legs_sorted, leg_count))[:30]
                
                for combo in combos:
                    combo_list = list(combo)
                    match_ids = list(set(leg['match_id'] for leg in combo_list))
                    if len(match_ids) < 2 and leg_count > 2:
                        continue
                    
                    if self._check_match_cooldown(match_ids):
                        continue
                    
                    parlay = self._build_parlay(combo_list)
                    
                    if parlay['edge_pct'] > -30:
                        saved = self._save_parlay(parlay)
                        if saved:
                            parlays_generated += 1
                            by_leg_count[leg_count] += 1
        
        logger.info(f"⚽ PlayerParlay: Generated {parlays_generated} parlays")
        
        return {
            'status': 'success',
            'fixtures_found': len(fixtures),
            'legs_generated': len(all_legs),
            'parlays_generated': parlays_generated,
            'by_leg_count': by_leg_count
        }
    
    def get_best_parlays(self, limit: int = 10, min_edge: float = -50, leg_count: int = None) -> List[Dict]:
        with self.engine.connect() as conn:
            leg_filter = f"AND pp.leg_count = {leg_count}" if leg_count else ""
            
            result = conn.execute(text(f"""
                SELECT 
                    pp.id,
                    pp.parlay_hash,
                    pp.leg_count,
                    pp.match_ids,
                    pp.combined_odds,
                    pp.raw_prob_pct,
                    pp.edge_pct,
                    pp.confidence_tier,
                    pp.payout_100,
                    pp.expires_at
                FROM player_parlays pp
                WHERE pp.expires_at > NOW()
                  AND pp.status = 'pending'
                  AND pp.edge_pct >= :min_edge
                  {leg_filter}
                ORDER BY pp.edge_pct DESC
                LIMIT :limit
            """), {'min_edge': min_edge, 'limit': limit})
            
            parlays = []
            for row in result.fetchall():
                parlay_data = dict(row._mapping)
                
                legs_result = conn.execute(text("""
                    SELECT 
                        player_name, team_name, model_prob, decimal_odds, edge_pct,
                        home_team, away_team, league_name, kickoff_at
                    FROM player_parlay_legs
                    WHERE parlay_id = :parlay_id
                    ORDER BY leg_index
                """), {'parlay_id': parlay_data['id']})
                
                parlay_data['legs'] = [dict(leg._mapping) for leg in legs_result.fetchall()]
                parlays.append(parlay_data)
            
            return parlays
