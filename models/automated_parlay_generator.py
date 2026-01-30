"""
Automated Parlay Generator - Phase 1
Generates same-match parlays with all 3 leg types:
- Match Result (H/D/A)
- Totals (Over/Under)
- Player Props (Anytime Scorer, 2+ Goals)

Features:
- Pre-computes parlays as matches come in
- Calculates payout from $100 default bet
- Tracks performance after games settle
- Organizes into 2/3/4/5+ leg buckets
"""

import os
import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from itertools import combinations
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger(__name__)

class AutomatedParlayGenerator:
    DEFAULT_BET = 100.0
    
    CORRELATION_PENALTIES = {
        ('match_result', 'totals'): 0.15,
        ('match_result', 'player_prop'): 0.12,
        ('totals', 'player_prop'): 0.10,
        ('match_result', 'match_result'): 0.0,
        ('totals', 'totals'): 0.08,
        ('player_prop', 'player_prop'): 0.05
    }
    
    def __init__(self):
        self.engine = create_engine(
            os.environ.get('DATABASE_URL'),
            pool_pre_ping=True,
            pool_recycle=300
        )
        self.Session = sessionmaker(bind=self.engine)
        self.v2_predictor = None
        
        try:
            from models.totals_predictor import TotalsPredictor
            from models.player_props_service import PlayerPropsService
            self.totals_predictor = TotalsPredictor()
            self.player_props = PlayerPropsService()
            logger.info("AutomatedParlayGenerator initialized with predictors")
        except Exception as e:
            logger.error(f"Failed to initialize predictors: {e}")
            self.totals_predictor = None
            self.player_props = None
        
        try:
            from models.v2_lgbm_predictor import V2LightGBMPredictor
            self.v2_predictor = V2LightGBMPredictor()
            logger.info("AutomatedParlayGenerator: V2 LightGBM predictor initialized")
        except Exception as e:
            logger.warning(f"V2 predictor not available: {e}")
    
    def generate_parlays_for_match(self, match_id: int) -> Dict:
        """Generate all same-match parlay combinations for a single match"""
        match_info = self._get_match_info(match_id)
        if not match_info:
            return {'error': 'Match not found', 'parlays_generated': 0}
        
        legs = self._extract_all_legs(match_info)
        if len(legs) < 2:
            return {'error': 'Insufficient legs available', 'parlays_generated': 0}
        
        parlays_generated = 0
        parlays_by_leg_count = {2: 0, 3: 0, 4: 0, '5+': 0}
        
        MIN_EDGE_PCT = 4.0
        MAX_EDGE_PCT = 15.0
        TARGET_LEG_COUNT = 2
        MIN_PARLAY_PROB = 0.20
        
        if len(legs) >= TARGET_LEG_COUNT:
            combos = list(combinations(legs, TARGET_LEG_COUNT))
            for combo in combos:
                parlay = self._build_parlay(list(combo), match_info)
                if parlay:
                    edge = parlay.get('edge_pct', -100)
                    adjusted_prob = parlay.get('adjusted_prob_pct', 0) / 100 if parlay.get('adjusted_prob_pct') else 0
                    
                    if MIN_EDGE_PCT <= edge <= MAX_EDGE_PCT and adjusted_prob >= MIN_PARLAY_PROB:
                        saved = self._save_parlay(parlay)
                        if saved:
                            parlays_generated += 1
                            parlays_by_leg_count[TARGET_LEG_COUNT] = parlays_by_leg_count.get(TARGET_LEG_COUNT, 0) + 1
        
        return {
            'match_id': match_id,
            'home_team': match_info['home_team'],
            'away_team': match_info['away_team'],
            'legs_available': len(legs),
            'parlays_generated': parlays_generated,
            'by_leg_count': parlays_by_leg_count
        }
    
    def generate_all_upcoming_parlays(self, hours_ahead: int = 48) -> Dict:
        """Generate parlays for all upcoming matches"""
        session = self.Session()
        try:
            now = datetime.now(timezone.utc)
            cutoff = now + timedelta(hours=hours_ahead)
            
            result = session.execute(text("""
                SELECT f.match_id, f.kickoff_at
                FROM fixtures f
                JOIN odds_consensus oc ON f.match_id = oc.match_id
                WHERE f.status = 'scheduled'
                AND f.kickoff_at > :now
                AND f.kickoff_at < :cutoff
                AND oc.ph_cons IS NOT NULL
                GROUP BY f.match_id, f.kickoff_at
                ORDER BY f.kickoff_at
                LIMIT 50
            """), {'now': now, 'cutoff': cutoff})
            
            matches = [row[0] for row in result.fetchall()]
            
            total_generated = 0
            match_results = []
            
            for match_id in matches:
                gen_result = self.generate_parlays_for_match(match_id)
                total_generated += gen_result.get('parlays_generated', 0)
                match_results.append(gen_result)
            
            self._cleanup_expired_parlays()
            
            return {
                'matches_processed': len(matches),
                'total_parlays_generated': total_generated,
                'match_details': match_results
            }
            
        except Exception as e:
            logger.error(f"Error in generate_all_upcoming_parlays: {e}")
            return {'matches_processed': 0, 'total_parlays_generated': 0, 'error': str(e)}
        finally:
            try:
                session.close()
            except Exception:
                pass
    
    def _get_match_info(self, match_id: int) -> Optional[Dict]:
        """Get match information with odds"""
        session = self.Session()
        try:
            result = session.execute(text("""
                SELECT 
                    f.match_id,
                    f.home_team, f.away_team,
                    f.home_team_id, f.away_team_id,
                    f.league_id,
                    COALESCE(lm.league_name, 'League ' || f.league_id::text) as league_name,
                    f.kickoff_at,
                    oc.ph_cons, oc.pd_cons, oc.pa_cons
                FROM fixtures f
                JOIN odds_consensus oc ON f.match_id = oc.match_id
                LEFT JOIN league_map lm ON f.league_id = lm.league_id
                WHERE f.match_id = :match_id
            """), {'match_id': match_id})
            
            row = result.fetchone()
            if not row:
                return None
            
            ph = row.ph_cons or 0.33
            pd = row.pd_cons or 0.33
            pa = row.pa_cons or 0.34
            
            home_odds = 1 / ph if ph > 0 else 3.0
            draw_odds = 1 / pd if pd > 0 else 3.5
            away_odds = 1 / pa if pa > 0 else 2.5
            
            model_h, model_d, model_a = ph, pd, pa
            if self.v2_predictor:
                try:
                    v2_pred = self.v2_predictor.predict(match_id=row.match_id)
                    if v2_pred and 'probabilities' in v2_pred:
                        model_h = v2_pred['probabilities'].get('home', ph)
                        model_d = v2_pred['probabilities'].get('draw', pd)
                        model_a = v2_pred['probabilities'].get('away', pa)
                        logger.debug(f"Match {row.match_id}: V2 model probs H={model_h:.3f} D={model_d:.3f} A={model_a:.3f}")
                except Exception as e:
                    logger.warning(f"V2 prediction failed for match {row.match_id}: {e}")
            
            return {
                'match_id': row.match_id,
                'home_team': row.home_team,
                'away_team': row.away_team,
                'home_team_id': row.home_team_id,
                'away_team_id': row.away_team_id,
                'league_id': row.league_id,
                'league_name': row.league_name,
                'kickoff_at': row.kickoff_at,
                'market_prob': {
                    'H': ph,
                    'D': pd,
                    'A': pa
                },
                'model_prob': {
                    'H': model_h,
                    'D': model_d,
                    'A': model_a
                },
                'odds': {
                    'H': round(home_odds, 2),
                    'D': round(draw_odds, 2),
                    'A': round(away_odds, 2)
                }
            }
        finally:
            try:
                session.close()
            except Exception:
                pass
    
    def _extract_all_legs(self, match_info: Dict) -> List[Dict]:
        """Extract all available legs for a match (match result, totals, player props)"""
        legs = []
        
        for outcome in ['H', 'D', 'A']:
            model_prob = float(match_info['model_prob'][outcome])
            market_prob = float(match_info['market_prob'][outcome])
            decimal_odds = float(match_info['odds'][outcome])
            edge = (model_prob - market_prob) / market_prob if market_prob > 0 else 0
            
            outcome_names = {'H': 'Home Win', 'D': 'Draw', 'A': 'Away Win'}
            
            legs.append({
                'leg_type': 'match_result',
                'match_id': match_info['match_id'],
                'home_team': match_info['home_team'],
                'away_team': match_info['away_team'],
                'league_name': match_info['league_name'],
                'kickoff_at': match_info['kickoff_at'],
                'market_code': outcome,
                'market_name': outcome_names[outcome],
                'player_id': None,
                'player_name': None,
                'model_prob': float(round(model_prob, 4)),
                'market_prob': float(round(market_prob, 4)),
                'decimal_odds': float(round(decimal_odds, 2)),
                'edge_pct': float(round(edge * 100, 1))
            })
        
        if self.totals_predictor:
            try:
                totals = self.totals_predictor.predict_match(match_info['match_id'])
                if totals and totals.get('status') == 'available':
                    expected_total = totals.get('expected_goals', {}).get('total', 2.5)
                    
                    for market_key in ['over_2.5', 'under_2.5', 'over_1.5', 'under_1.5']:
                        if market_key in totals['over_under']:
                            model_prob = float(totals['over_under'][market_key])
                            
                            market_margin = 0.06
                            fair_prob = model_prob
                            opposite_key = market_key.replace('over', 'under') if 'over' in market_key else market_key.replace('under', 'over')
                            opposite_prob = float(totals['over_under'].get(opposite_key, 1 - fair_prob))
                            
                            total_with_margin = fair_prob + opposite_prob + market_margin
                            market_prob = fair_prob * (1 + market_margin / 2) / total_with_margin if total_with_margin > 0 else 0.5
                            market_prob = max(0.15, min(0.85, market_prob))
                            
                            decimal_odds = 1 / market_prob if market_prob > 0 else 2.0
                            edge = (model_prob - market_prob) / market_prob if market_prob > 0 else 0
                            
                            legs.append({
                                'leg_type': 'totals',
                                'match_id': match_info['match_id'],
                                'home_team': match_info['home_team'],
                                'away_team': match_info['away_team'],
                                'league_name': match_info['league_name'],
                                'kickoff_at': match_info['kickoff_at'],
                                'market_code': market_key,
                                'market_name': f"Total Goals {market_key.replace('_', ' ').title()}",
                                'player_id': None,
                                'player_name': None,
                                'model_prob': float(round(model_prob, 4)),
                                'market_prob': float(round(market_prob, 4)),
                                'decimal_odds': float(round(decimal_odds, 2)),
                                'edge_pct': float(round(edge * 100, 1))
                            })
            except Exception as e:
                logger.debug(f"Totals prediction failed for {match_info['match_id']}: {e}")
        
        if self.player_props:
            try:
                top_players = self.player_props.get_top_scorer_picks(match_info['match_id'], limit=4)
                if top_players and 'picks' in top_players:
                    for player in top_players['picks'][:4]:
                        model_prob = float(player.get('anytime_scorer_prob', 0.15))
                        market_prob = 0.18
                        decimal_odds = 1 / market_prob if market_prob > 0 else 5.5
                        edge = (model_prob - market_prob) / market_prob if market_prob > 0 else 0
                        
                        legs.append({
                            'leg_type': 'player_prop',
                            'match_id': match_info['match_id'],
                            'home_team': match_info['home_team'],
                            'away_team': match_info['away_team'],
                            'league_name': match_info['league_name'],
                            'kickoff_at': match_info['kickoff_at'],
                            'market_code': 'anytime_scorer',
                            'market_name': f"{player.get('player_name', 'Unknown')} Anytime Scorer",
                            'player_id': player.get('player_id'),
                            'player_name': player.get('player_name'),
                            'model_prob': float(round(model_prob, 4)),
                            'market_prob': float(round(market_prob, 4)),
                            'decimal_odds': float(round(decimal_odds, 2)),
                            'edge_pct': float(round(edge * 100, 1))
                        })
            except Exception as e:
                logger.debug(f"Player props failed for {match_info['match_id']}: {e}")
        
        return legs
    
    def _build_parlay(self, legs: List[Dict], match_info: Dict) -> Optional[Dict]:
        """Build a parlay from a list of legs with correlation adjustment"""
        if len(legs) < 2:
            return None
        
        combined_odds = 1.0
        raw_prob = 1.0
        total_correlation_penalty = 0.0
        
        for leg in legs:
            combined_odds *= float(leg['decimal_odds'])
            raw_prob *= float(leg['model_prob'])
        
        leg_types = [leg['leg_type'] for leg in legs]
        for i, type1 in enumerate(leg_types):
            for type2 in leg_types[i+1:]:
                key = tuple(sorted([type1, type2]))
                penalty = self.CORRELATION_PENALTIES.get(key, 0.05)
                total_correlation_penalty += penalty
        
        total_correlation_penalty = min(total_correlation_penalty, 0.40)
        
        adjusted_prob = raw_prob * (1 - total_correlation_penalty)
        implied_prob = 1 / combined_odds if combined_odds > 0 else 0
        edge = (adjusted_prob - implied_prob) / implied_prob if implied_prob > 0 else 0
        
        if edge > 0.10:
            confidence_tier = 'high'
        elif edge > 0:
            confidence_tier = 'medium'
        else:
            confidence_tier = 'low'
        
        payout = self.DEFAULT_BET * combined_odds
        
        parlay_hash = self._generate_parlay_hash(legs)
        
        expires_at = match_info['kickoff_at'] if isinstance(match_info['kickoff_at'], datetime) else datetime.now(timezone.utc) + timedelta(hours=48)
        
        return {
            'parlay_hash': parlay_hash,
            'leg_count': len(legs),
            'same_match_flag': True,
            'match_ids': [match_info['match_id']],
            'correlation_penalty_pct': float(round(total_correlation_penalty * 100, 2)),
            'combined_odds': float(round(combined_odds, 2)),
            'raw_prob_pct': float(round(raw_prob * 100, 3)),
            'adjusted_prob_pct': float(round(adjusted_prob * 100, 3)),
            'implied_prob_pct': float(round(implied_prob * 100, 3)),
            'edge_pct': float(round(edge * 100, 2)),
            'confidence_tier': confidence_tier,
            'payout_100': float(round(payout, 2)),
            'leg_types': list(set(leg_types)),
            'expires_at': expires_at,
            'legs': legs
        }
    
    def _generate_parlay_hash(self, legs: List[Dict]) -> str:
        """Generate unique hash for a parlay combination"""
        leg_keys = sorted([
            f"{leg['match_id']}_{leg['leg_type']}_{leg['market_code']}_{leg.get('player_id', '')}"
            for leg in legs
        ])
        hash_input = '|'.join(leg_keys)
        return hashlib.md5(hash_input.encode()).hexdigest()[:16]
    
    def _save_parlay(self, parlay: Dict) -> bool:
        """Save parlay and legs to database"""
        session = self.Session()
        try:
            existing = session.execute(text("""
                SELECT id FROM parlay_precomputed WHERE parlay_hash = :hash
            """), {'hash': parlay['parlay_hash']}).fetchone()
            
            if existing:
                return False
            
            result = session.execute(text("""
                INSERT INTO parlay_precomputed 
                (parlay_hash, leg_count, same_match_flag, match_ids, 
                 correlation_penalty_pct, combined_odds, raw_prob_pct, 
                 adjusted_prob_pct, implied_prob_pct, edge_pct, 
                 confidence_tier, payout_100, leg_types, expires_at)
                VALUES 
                (:hash, :leg_count, :same_match, :match_ids,
                 :corr_penalty, :combined_odds, :raw_prob,
                 :adj_prob, :implied_prob, :edge,
                 :confidence, :payout, :leg_types, :expires)
                RETURNING id
            """), {
                'hash': parlay['parlay_hash'],
                'leg_count': parlay['leg_count'],
                'same_match': parlay['same_match_flag'],
                'match_ids': parlay['match_ids'],
                'corr_penalty': parlay['correlation_penalty_pct'],
                'combined_odds': parlay['combined_odds'],
                'raw_prob': parlay['raw_prob_pct'],
                'adj_prob': parlay['adjusted_prob_pct'],
                'implied_prob': parlay['implied_prob_pct'],
                'edge': parlay['edge_pct'],
                'confidence': parlay['confidence_tier'],
                'payout': parlay['payout_100'],
                'leg_types': parlay['leg_types'],
                'expires': parlay['expires_at']
            })
            
            parlay_id = result.fetchone()[0]
            
            for idx, leg in enumerate(parlay['legs']):
                kickoff_str = leg['kickoff_at'].isoformat() if isinstance(leg['kickoff_at'], datetime) else str(leg['kickoff_at'])
                
                session.execute(text("""
                    INSERT INTO parlay_precomputed_legs
                    (parlay_id, leg_index, leg_type, match_id, home_team, away_team,
                     league_name, kickoff_at, market_code, market_name, player_id,
                     player_name, model_prob, market_prob, decimal_odds, edge_pct)
                    VALUES
                    (:parlay_id, :idx, :leg_type, :match_id, :home, :away,
                     :league, :kickoff, :market_code, :market_name, :player_id,
                     :player_name, :model_prob, :market_prob, :odds, :edge)
                """), {
                    'parlay_id': parlay_id,
                    'idx': idx,
                    'leg_type': leg['leg_type'],
                    'match_id': leg['match_id'],
                    'home': leg['home_team'],
                    'away': leg['away_team'],
                    'league': leg['league_name'],
                    'kickoff': kickoff_str,
                    'market_code': leg['market_code'],
                    'market_name': leg['market_name'],
                    'player_id': leg.get('player_id'),
                    'player_name': leg.get('player_name'),
                    'model_prob': leg['model_prob'],
                    'market_prob': leg['market_prob'],
                    'odds': leg['decimal_odds'],
                    'edge': leg['edge_pct']
                })
            
            session.commit()
            return True
            
        except Exception as e:
            try:
                session.rollback()
            except Exception:
                pass
            logger.error(f"Failed to save parlay: {e}")
            return False
        finally:
            try:
                session.close()
            except Exception:
                pass
    
    def settle_parlays(self) -> Dict:
        """Settle completed parlays based on match results"""
        session = self.Session()
        try:
            result = session.execute(text("""
                SELECT DISTINCT pp.id, pp.parlay_hash, pp.payout_100
                FROM parlay_precomputed pp
                JOIN parlay_precomputed_legs ppl ON pp.id = ppl.parlay_id
                JOIN matches m ON ppl.match_id = m.match_id
                WHERE pp.status = 'pending'
                AND m.outcome IS NOT NULL
            """))
            
            parlays_to_settle = result.fetchall()
            settled_count = 0
            won_count = 0
            lost_count = 0
            
            for parlay_row in parlays_to_settle:
                parlay_id = parlay_row[0]
                
                legs_result = session.execute(text("""
                    SELECT ppl.leg_type, ppl.market_code, ppl.player_id,
                           m.home_goals as home_score, m.away_goals as away_score, m.outcome as match_result
                    FROM parlay_precomputed_legs ppl
                    JOIN matches m ON ppl.match_id = m.match_id
                    WHERE ppl.parlay_id = :parlay_id
                """), {'parlay_id': parlay_id})
                
                all_won = True
                for leg in legs_result.fetchall():
                    leg_won = self._check_leg_result(
                        leg.leg_type, leg.market_code, leg.player_id,
                        leg.home_score, leg.away_score, leg.match_result
                    )
                    if not leg_won:
                        all_won = False
                        break
                
                parlay_result = 'won' if all_won else 'lost'
                session.execute(text("""
                    UPDATE parlay_precomputed 
                    SET status = 'settled', result = :result, settled_at = NOW()
                    WHERE id = :id
                """), {'result': parlay_result, 'id': parlay_id})
                
                settled_count += 1
                if all_won:
                    won_count += 1
                else:
                    lost_count += 1
            
            session.commit()
            
            self._update_performance_summary(session)
            
            return {
                'settled': settled_count,
                'won': won_count,
                'lost': lost_count
            }
            
        except Exception as e:
            try:
                session.rollback()
            except Exception:
                pass
            logger.error(f"Failed to settle parlays: {e}")
            return {'error': str(e)}
        finally:
            try:
                session.close()
            except Exception:
                pass
    
    def _check_leg_result(self, leg_type: str, market_code: str, player_id: int,
                          home_score: int, away_score: int, match_result: str) -> bool:
        """Check if a leg won based on match result"""
        if leg_type == 'match_result':
            if market_code == 'H':
                return home_score > away_score
            elif market_code == 'D':
                return home_score == away_score
            elif market_code == 'A':
                return away_score > home_score
        
        elif leg_type == 'totals':
            total_goals = (home_score or 0) + (away_score or 0)
            if 'over' in market_code:
                line = float(market_code.split('_')[1])
                return total_goals > line
            elif 'under' in market_code:
                line = float(market_code.split('_')[1])
                return total_goals < line
        
        elif leg_type == 'player_prop':
            pass
        
        return False
    
    def _update_performance_summary(self, session):
        """Update performance summary table"""
        try:
            session.execute(text("""
                INSERT INTO parlay_performance_summary 
                (period, period_start, leg_count, confidence_tier, 
                 total_parlays, won, lost, pending, total_staked, total_returns, roi_pct, avg_edge_pct)
                SELECT 
                    'daily',
                    DATE(settled_at),
                    leg_count,
                    confidence_tier,
                    COUNT(*),
                    SUM(CASE WHEN result = 'won' THEN 1 ELSE 0 END),
                    SUM(CASE WHEN result = 'lost' THEN 1 ELSE 0 END),
                    SUM(CASE WHEN result IS NULL THEN 1 ELSE 0 END),
                    COUNT(*) * 100.0,
                    SUM(CASE WHEN result = 'won' THEN payout_100 ELSE 0 END),
                    (SUM(CASE WHEN result = 'won' THEN payout_100 ELSE 0 END) - COUNT(*) * 100.0) / (COUNT(*) * 100.0) * 100,
                    AVG(edge_pct)
                FROM parlay_precomputed
                WHERE status = 'settled'
                AND settled_at >= CURRENT_DATE - INTERVAL '7 days'
                GROUP BY DATE(settled_at), leg_count, confidence_tier
                ON CONFLICT (period, period_start, leg_count, confidence_tier)
                DO UPDATE SET
                    total_parlays = EXCLUDED.total_parlays,
                    won = EXCLUDED.won,
                    lost = EXCLUDED.lost,
                    pending = EXCLUDED.pending,
                    total_staked = EXCLUDED.total_staked,
                    total_returns = EXCLUDED.total_returns,
                    roi_pct = EXCLUDED.roi_pct,
                    avg_edge_pct = EXCLUDED.avg_edge_pct,
                    updated_at = NOW()
            """))
            session.commit()
        except Exception as e:
            logger.error(f"Failed to update performance summary: {e}")
    
    def _cleanup_expired_parlays(self):
        """Remove expired parlays"""
        session = self.Session()
        try:
            session.execute(text("""
                DELETE FROM parlay_precomputed 
                WHERE expires_at < NOW() - INTERVAL '24 hours'
                AND status = 'pending'
            """))
            session.commit()
        except Exception as e:
            logger.error(f"Cleanup failed: {e}")
        finally:
            try:
                session.close()
            except Exception:
                pass
    
    def get_best_parlays(self, leg_count: int = None, confidence: str = None,
                         min_edge: float = 0, limit: int = 20) -> List[Dict]:
        """Get best parlays filtered by criteria"""
        session = self.Session()
        try:
            query = """
                SELECT 
                    pp.id, pp.parlay_hash, pp.leg_count, pp.combined_odds,
                    pp.adjusted_prob_pct, pp.edge_pct, pp.confidence_tier,
                    pp.payout_100, pp.correlation_penalty_pct, pp.leg_types,
                    pp.status, pp.result
                FROM parlay_precomputed pp
                WHERE pp.status = 'pending'
                AND pp.expires_at > NOW()
                AND pp.edge_pct >= :min_edge
            """
            
            params = {'min_edge': min_edge}
            
            if leg_count:
                query += " AND pp.leg_count = :leg_count"
                params['leg_count'] = leg_count
            
            if confidence:
                query += " AND pp.confidence_tier = :confidence"
                params['confidence'] = confidence
            
            query += " ORDER BY pp.edge_pct DESC LIMIT :limit"
            params['limit'] = limit
            
            result = session.execute(text(query), params)
            parlays = []
            
            for row in result.fetchall():
                legs_result = session.execute(text("""
                    SELECT leg_type, market_code, market_name, player_name,
                           model_prob, decimal_odds, edge_pct, home_team, away_team
                    FROM parlay_precomputed_legs
                    WHERE parlay_id = :parlay_id
                    ORDER BY leg_index
                """), {'parlay_id': row.id})
                
                legs = []
                for leg in legs_result.fetchall():
                    legs.append({
                        'leg_type': leg.leg_type,
                        'market': leg.market_code,
                        'market_name': leg.market_name,
                        'player_name': leg.player_name,
                        'teams': f"{leg.home_team} vs {leg.away_team}",
                        'model_prob': float(leg.model_prob),
                        'odds': float(leg.decimal_odds),
                        'edge_pct': float(leg.edge_pct)
                    })
                
                parlays.append({
                    'parlay_id': row.parlay_hash,
                    'leg_count': row.leg_count,
                    'combined_odds': float(row.combined_odds),
                    'win_probability': float(row.adjusted_prob_pct),
                    'edge_pct': float(row.edge_pct),
                    'confidence': row.confidence_tier,
                    'payout_100': float(row.payout_100),
                    'correlation_penalty': float(row.correlation_penalty_pct),
                    'leg_types': row.leg_types,
                    'legs': legs
                })
            
            return parlays
            
        finally:
            try:
                session.close()
            except Exception:
                pass
    
    def get_performance_stats(self) -> Dict:
        """Get overall parlay performance statistics"""
        session = self.Session()
        try:
            result = session.execute(text("""
                SELECT 
                    leg_count,
                    confidence_tier,
                    COUNT(*) as total,
                    SUM(CASE WHEN result = 'won' THEN 1 ELSE 0 END) as won,
                    SUM(CASE WHEN result = 'lost' THEN 1 ELSE 0 END) as lost,
                    SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending,
                    ROUND(AVG(edge_pct)::numeric, 2) as avg_edge,
                    ROUND(AVG(payout_100)::numeric, 2) as avg_payout,
                    SUM(CASE WHEN result = 'won' THEN payout_100 ELSE 0 END) as total_returns,
                    COUNT(*) * 100.0 as total_staked
                FROM parlay_precomputed
                GROUP BY leg_count, confidence_tier
                ORDER BY leg_count, confidence_tier
            """))
            
            stats = []
            for row in result.fetchall():
                roi = ((row.total_returns or 0) - (row.total_staked or 0)) / (row.total_staked or 1) * 100
                win_rate = (row.won or 0) / (row.won + row.lost) * 100 if (row.won + row.lost) > 0 else 0
                
                stats.append({
                    'leg_count': row.leg_count,
                    'confidence': row.confidence_tier,
                    'total_parlays': row.total,
                    'won': row.won or 0,
                    'lost': row.lost or 0,
                    'pending': row.pending or 0,
                    'win_rate_pct': round(win_rate, 1),
                    'avg_edge_pct': float(row.avg_edge) if row.avg_edge else 0,
                    'avg_payout': float(row.avg_payout) if row.avg_payout else 0,
                    'roi_pct': round(roi, 2)
                })
            
            return {
                'by_bucket': stats,
                'summary': {
                    'total_parlays': sum(s['total_parlays'] for s in stats),
                    'total_won': sum(s['won'] for s in stats),
                    'total_lost': sum(s['lost'] for s in stats),
                    'total_pending': sum(s['pending'] for s in stats)
                }
            }
            
        finally:
            try:
                session.close()
            except Exception:
                pass
