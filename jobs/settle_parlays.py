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
    
    V3 improvements:
    - Uses fixtures table (status='finished') instead of match_results
    - Pre-loads player_game_stats in bulk for efficiency
    - Processes in batches with commits to avoid timeouts
    - Mark legs as 'unknown' when data is missing (not 'lost')
    - Mark parlays as 'data_pending' when some legs have unknown status
    """
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        return {'error': 'DATABASE_URL not set', 'settled': 0}
    
    engine = create_engine(db_url, pool_pre_ping=True)
    
    settled_count = 0
    won_count = 0
    lost_count = 0
    data_pending_count = 0
    skipped_count = 0
    
    try:
        with engine.connect() as conn:
            finished_fixture_ids = set()
            rows = conn.execute(text("""
                SELECT match_id FROM fixtures WHERE status = 'finished'
            """)).fetchall()
            for r in rows:
                finished_fixture_ids.add(r.match_id)
            
            logger.info(f"SETTLE: {len(finished_fixture_ids)} finished fixtures in DB")
            
            game_stats_cache = {}
            stats_rows = conn.execute(text("""
                SELECT game_id, player_id, COALESCE((stats->>'goals')::int, 0) as goals
                FROM player_game_stats
            """)).fetchall()
            
            games_with_stats = set()
            for sr in stats_rows:
                games_with_stats.add(sr.game_id)
                game_stats_cache[(sr.player_id, sr.game_id)] = sr.goals
            
            logger.info(f"SETTLE: Loaded {len(game_stats_cache)} player stat records across {len(games_with_stats)} games")
            
            pending_parlays = conn.execute(text("""
                SELECT 
                    pp.id,
                    pp.match_ids,
                    pp.combined_odds,
                    pp.confidence_tier
                FROM player_parlays pp
                WHERE pp.status IN ('pending', 'data_pending')
                AND pp.expires_at < NOW()
                ORDER BY pp.expires_at ASC
            """)).fetchall()
            
            logger.info(f"SETTLE: Processing {len(pending_parlays)} expired parlays")
            
            parlay_ids = [p.id for p in pending_parlays]
            all_legs = {}
            if parlay_ids:
                leg_rows = conn.execute(text("""
                    SELECT 
                        ppl.parlay_id,
                        ppl.id as leg_id,
                        ppl.player_id,
                        ppl.player_name,
                        ppl.match_id,
                        ppl.result
                    FROM player_parlay_legs ppl
                    WHERE ppl.parlay_id = ANY(:parlay_ids)
                """), {'parlay_ids': parlay_ids}).fetchall()
                
                for lr in leg_rows:
                    all_legs.setdefault(lr.parlay_id, []).append(lr)
                
                logger.info(f"SETTLE: Pre-loaded {len(leg_rows)} legs for {len(all_legs)} parlays")
            
            leg_updates_won = []
            leg_updates_lost = []
            leg_updates_unknown = []
            parlay_updates_settled_won = []
            parlay_updates_settled_lost = []
            parlay_updates_data_pending = []
            
            for parlay in pending_parlays:
                parlay_id = parlay.id
                match_ids = parlay.match_ids if parlay.match_ids else []
                
                if not match_ids:
                    skipped_count += 1
                    continue
                
                all_finished = all(mid in finished_fixture_ids for mid in match_ids)
                if not all_finished:
                    skipped_count += 1
                    continue
                
                legs = all_legs.get(parlay_id, [])
                
                all_won = True
                any_lost = False
                any_unknown = False
                
                for leg in legs:
                    if leg.result == 'lost':
                        any_lost = True
                        all_won = False
                    elif leg.result == 'won':
                        pass
                    elif leg.result == 'unknown':
                        any_unknown = True
                        all_won = False
                    else:
                        if leg.match_id not in games_with_stats:
                            leg_updates_unknown.append(leg.leg_id)
                            any_unknown = True
                            all_won = False
                            continue
                        
                        goals = game_stats_cache.get((leg.player_id, leg.match_id))
                        
                        if goals is None:
                            leg_updates_unknown.append(leg.leg_id)
                            any_unknown = True
                            all_won = False
                            continue
                        
                        if goals > 0:
                            leg_updates_won.append(leg.leg_id)
                        else:
                            leg_updates_lost.append(leg.leg_id)
                            any_lost = True
                            all_won = False
                
                if any_unknown and not any_lost:
                    parlay_updates_data_pending.append(parlay_id)
                    data_pending_count += 1
                elif any_lost:
                    parlay_updates_settled_lost.append(parlay_id)
                    settled_count += 1
                    lost_count += 1
                elif all_won:
                    parlay_updates_settled_won.append(parlay_id)
                    settled_count += 1
                    won_count += 1
            
            logger.info(f"SETTLE: Computed results - leg updates: {len(leg_updates_won)} won, {len(leg_updates_lost)} lost, {len(leg_updates_unknown)} unknown")
            
            if leg_updates_won:
                conn.execute(text("UPDATE player_parlay_legs SET result = 'won' WHERE id = ANY(:ids)"), {'ids': leg_updates_won})
            if leg_updates_lost:
                conn.execute(text("UPDATE player_parlay_legs SET result = 'lost' WHERE id = ANY(:ids)"), {'ids': leg_updates_lost})
            if leg_updates_unknown:
                conn.execute(text("UPDATE player_parlay_legs SET result = 'unknown' WHERE id = ANY(:ids)"), {'ids': leg_updates_unknown})
            if parlay_updates_settled_won:
                conn.execute(text("UPDATE player_parlays SET status = 'settled', result = 'won', settled_at = NOW() WHERE id = ANY(:ids)"), {'ids': parlay_updates_settled_won})
            if parlay_updates_settled_lost:
                conn.execute(text("UPDATE player_parlays SET status = 'settled', result = 'lost', settled_at = NOW() WHERE id = ANY(:ids)"), {'ids': parlay_updates_settled_lost})
            if parlay_updates_data_pending:
                conn.execute(text("UPDATE player_parlays SET status = 'data_pending' WHERE id = ANY(:ids)"), {'ids': parlay_updates_data_pending})
            
            conn.commit()
            
            logger.info(f"SETTLE: Complete - settled={settled_count} (won={won_count}, lost={lost_count}), data_pending={data_pending_count}, skipped={skipped_count}")
            
            return {
                'settled': settled_count,
                'won': won_count,
                'lost': lost_count,
                'data_pending': data_pending_count,
                'skipped': skipped_count
            }
            
    except Exception as e:
        logger.error(f"Player parlay settlement failed: {e}")
        return {'error': str(e), 'settled': settled_count, 'won': won_count, 'lost': lost_count}


if __name__ == "__main__":
    import asyncio
    logging.basicConfig(level=logging.INFO)
    
    result = asyncio.run(settle_parlays_job())
    print(f"Settlement result: {result}")
    
    player_result = asyncio.run(settle_player_parlays_job())
    print(f"Player parlay settlement result: {player_result}")
    
    summary = get_parlay_performance_summary()
    print(f"Performance summary: {summary}")
