"""
Parlay Settlement Job
Settles parlays when all legs have finished and tracks performance
"""
import os
import logging
from datetime import datetime, timezone
from sqlalchemy import create_engine, text

logger = logging.getLogger(__name__)


async def settle_parlays_job() -> dict:
    """
    Settle parlays by checking if all legs have finished.
    Updates parlay status and creates performance records.
    """
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        return {'error': 'DATABASE_URL not set', 'settled': 0}
    
    engine = create_engine(db_url, pool_pre_ping=True)
    
    try:
        with engine.connect() as conn:
            active_parlays = conn.execute(text("""
                SELECT 
                    parlay_id::text,
                    leg_count,
                    legs,
                    implied_odds,
                    edge_pct,
                    confidence_tier,
                    adjusted_prob
                FROM parlay_consensus
                WHERE status IN ('active', 'pending', 'expired')
                AND latest_kickoff < NOW() - INTERVAL '3 hours'
            """)).fetchall()
            
            settled_count = 0
            won_count = 0
            lost_count = 0
            
            for parlay in active_parlays:
                parlay_id = parlay.parlay_id
                legs = parlay.legs if isinstance(parlay.legs, list) else []
                
                if not legs:
                    continue
                
                match_ids = [int(leg.get('match_id')) for leg in legs if leg.get('match_id')]
                if not match_ids:
                    continue
                
                results = conn.execute(text("""
                    SELECT 
                        match_id,
                        outcome
                    FROM match_results
                    WHERE match_id = ANY(:match_ids)
                """), {'match_ids': match_ids}).fetchall()
                
                results_by_id = {r.match_id: r.outcome for r in results}
                
                if len(results_by_id) < len(match_ids):
                    continue
                
                legs_won = 0
                legs_lost = 0
                all_legs_won = True
                
                for leg in legs:
                    match_id = leg.get('match_id')
                    predicted_outcome = leg.get('outcome')
                    actual_outcome = results_by_id.get(match_id)
                    
                    if actual_outcome == predicted_outcome:
                        legs_won += 1
                    else:
                        legs_lost += 1
                        all_legs_won = False
                
                stake = 1.0
                payout = parlay.implied_odds if all_legs_won else 0.0
                profit = payout - stake
                
                conn.execute(text("""
                    UPDATE parlay_consensus
                    SET status = 'settled', won = :won
                    WHERE parlay_id = CAST(:parlay_id AS uuid)
                """), {'parlay_id': parlay_id, 'won': all_legs_won})
                
                conn.execute(text("""
                    INSERT INTO parlay_performance (
                        parlay_id, settled_at, won, legs_won, legs_lost,
                        stake, payout, profit, pre_edge_pct, 
                        pre_confidence_tier, pre_adjusted_prob
                    ) VALUES (
                        CAST(:parlay_id AS uuid), NOW(), :won, :legs_won, :legs_lost,
                        :stake, :payout, :profit, :pre_edge_pct,
                        :pre_confidence_tier, :pre_adjusted_prob
                    )
                """), {
                    'parlay_id': parlay_id,
                    'won': all_legs_won,
                    'legs_won': legs_won,
                    'legs_lost': legs_lost,
                    'stake': stake,
                    'payout': payout,
                    'profit': profit,
                    'pre_edge_pct': parlay.edge_pct or 0,
                    'pre_confidence_tier': parlay.confidence_tier or 'low',
                    'pre_adjusted_prob': parlay.adjusted_prob or 0
                })
                
                settled_count += 1
                if all_legs_won:
                    won_count += 1
                else:
                    lost_count += 1
            
            conn.commit()
            
            logger.info(f"Settled {settled_count} parlays (Won: {won_count}, Lost: {lost_count})")
            
            return {
                'settled': settled_count,
                'won': won_count,
                'lost': lost_count
            }
            
    except Exception as e:
        logger.error(f"Parlay settlement failed: {e}")
        return {'error': str(e), 'settled': 0}


def get_parlay_performance_summary() -> dict:
    """Get overall parlay performance statistics"""
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        return {}
    
    engine = create_engine(db_url, pool_pre_ping=True)
    
    try:
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT 
                    COUNT(*) as total_parlays,
                    COUNT(*) FILTER (WHERE won = true) as wins,
                    COUNT(*) FILTER (WHERE won = false) as losses,
                    SUM(profit) as total_profit,
                    AVG(profit) as avg_profit,
                    AVG(CASE WHEN won THEN payout ELSE 0 END) as avg_payout_on_win,
                    
                    -- By confidence tier
                    COUNT(*) FILTER (WHERE pre_confidence_tier = 'high') as high_tier_count,
                    COUNT(*) FILTER (WHERE pre_confidence_tier = 'high' AND won) as high_tier_wins,
                    SUM(profit) FILTER (WHERE pre_confidence_tier = 'high') as high_tier_profit,
                    
                    COUNT(*) FILTER (WHERE pre_confidence_tier = 'medium') as medium_tier_count,
                    COUNT(*) FILTER (WHERE pre_confidence_tier = 'medium' AND won) as medium_tier_wins,
                    SUM(profit) FILTER (WHERE pre_confidence_tier = 'medium') as medium_tier_profit,
                    
                    COUNT(*) FILTER (WHERE pre_confidence_tier = 'low') as low_tier_count,
                    COUNT(*) FILTER (WHERE pre_confidence_tier = 'low' AND won) as low_tier_wins,
                    SUM(profit) FILTER (WHERE pre_confidence_tier = 'low') as low_tier_profit
                FROM parlay_performance
            """)).fetchone()
            
            if not result or result.total_parlays == 0:
                return {'message': 'No settled parlays yet'}
            
            total = result.total_parlays
            wins = result.wins
            losses = result.losses
            
            return {
                'overall': {
                    'total_parlays': total,
                    'wins': wins,
                    'losses': losses,
                    'win_rate': round(wins / total * 100, 1) if total > 0 else 0,
                    'total_profit': round(float(result.total_profit or 0), 2),
                    'avg_profit': round(float(result.avg_profit or 0), 2),
                    'roi_pct': round(float(result.total_profit or 0) / total * 100, 1) if total > 0 else 0
                },
                'by_tier': {
                    'high': {
                        'count': result.high_tier_count or 0,
                        'wins': result.high_tier_wins or 0,
                        'win_rate': round((result.high_tier_wins or 0) / (result.high_tier_count or 1) * 100, 1),
                        'profit': round(float(result.high_tier_profit or 0), 2)
                    },
                    'medium': {
                        'count': result.medium_tier_count or 0,
                        'wins': result.medium_tier_wins or 0,
                        'win_rate': round((result.medium_tier_wins or 0) / (result.medium_tier_count or 1) * 100, 1),
                        'profit': round(float(result.medium_tier_profit or 0), 2)
                    },
                    'low': {
                        'count': result.low_tier_count or 0,
                        'wins': result.low_tier_wins or 0,
                        'win_rate': round((result.low_tier_wins or 0) / (result.low_tier_count or 1) * 100, 1),
                        'profit': round(float(result.low_tier_profit or 0), 2)
                    }
                }
            }
            
    except Exception as e:
        logger.error(f"Failed to get performance summary: {e}")
        return {'error': str(e)}


async def settle_player_parlays_job() -> dict:
    """
    Settle player parlays by checking goal scorers in completed matches.
    """
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        return {'error': 'DATABASE_URL not set', 'settled': 0}
    
    engine = create_engine(db_url, pool_pre_ping=True)
    
    try:
        with engine.connect() as conn:
            pending_parlays = conn.execute(text("""
                SELECT 
                    pp.id,
                    pp.match_ids,
                    pp.combined_odds,
                    pp.confidence_tier
                FROM player_parlays pp
                WHERE pp.status = 'pending'
                AND pp.expires_at < NOW()
            """)).fetchall()
            
            settled_count = 0
            won_count = 0
            lost_count = 0
            
            for parlay in pending_parlays:
                parlay_id = parlay.id
                match_ids = parlay.match_ids if parlay.match_ids else []
                
                if not match_ids:
                    continue
                
                finished_matches = conn.execute(text("""
                    SELECT COUNT(*) as cnt
                    FROM match_results
                    WHERE match_id = ANY(:match_ids)
                """), {'match_ids': match_ids}).fetchone()
                
                if finished_matches.cnt < len(match_ids):
                    continue
                
                legs = conn.execute(text("""
                    SELECT 
                        ppl.player_id,
                        ppl.match_id,
                        ppl.result
                    FROM player_parlay_legs ppl
                    WHERE ppl.parlay_id = :parlay_id
                """), {'parlay_id': parlay_id}).fetchall()
                
                all_won = True
                data_missing = False
                for leg in legs:
                    if leg.result == 'lost':
                        all_won = False
                    elif leg.result == 'won':
                        pass
                    else:
                        game_stats_exist = conn.execute(text("""
                            SELECT 1 FROM player_game_stats pgs
                            WHERE pgs.game_id = :match_id
                            LIMIT 1
                        """), {'match_id': leg.match_id}).fetchone()
                        
                        if not game_stats_exist:
                            data_missing = True
                            continue
                        
                        scorers = conn.execute(text("""
                            SELECT 1 FROM player_game_stats pgs
                            WHERE pgs.player_id = :player_id
                            AND pgs.game_id = :match_id
                            AND (pgs.stats->>'goals')::int > 0
                        """), {'player_id': leg.player_id, 'match_id': leg.match_id}).fetchone()
                        
                        won = scorers is not None
                        conn.execute(text("""
                            UPDATE player_parlay_legs
                            SET result = :result
                            WHERE parlay_id = :parlay_id AND player_id = :player_id AND match_id = :match_id
                        """), {
                            'result': 'won' if won else 'lost',
                            'parlay_id': parlay_id,
                            'player_id': leg.player_id,
                            'match_id': leg.match_id
                        })
                        
                        if not won:
                            all_won = False
                
                if data_missing:
                    continue
                
                conn.execute(text("""
                    UPDATE player_parlays
                    SET status = 'settled', result = :result, settled_at = NOW()
                    WHERE id = :parlay_id
                """), {
                    'parlay_id': parlay_id,
                    'result': 'won' if all_won else 'lost'
                })
                
                settled_count += 1
                if all_won:
                    won_count += 1
                else:
                    lost_count += 1
            
            conn.commit()
            
            logger.info(f"Settled {settled_count} player parlays (Won: {won_count}, Lost: {lost_count})")
            
            return {
                'settled': settled_count,
                'won': won_count,
                'lost': lost_count
            }
            
    except Exception as e:
        logger.error(f"Player parlay settlement failed: {e}")
        return {'error': str(e), 'settled': 0}


if __name__ == "__main__":
    import asyncio
    logging.basicConfig(level=logging.INFO)
    
    result = asyncio.run(settle_parlays_job())
    print(f"Settlement result: {result}")
    
    player_result = asyncio.run(settle_player_parlays_job())
    print(f"Player parlay settlement result: {player_result}")
    
    summary = get_parlay_performance_summary()
    print(f"Performance summary: {summary}")
