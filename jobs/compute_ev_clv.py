"""
EV and CLV Computation Job

Computes Expected Value and Closing Line Value for all model predictions
Joins model_inference_logs to market_features to calculate:
- EV_close: p_model(outcome) - p_close_novig(outcome) 
- CLV_prob: p_close(outcome) - p_open(outcome)

Author: BetGenius AI Team
Date: Oct 2025
"""

import os
import sys
import psycopg2
from datetime import datetime
from typing import Dict, List, Tuple, Optional
import logging

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from models.database import DatabaseManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def compute_ev_clv_for_predictions():
    """
    Compute EV and CLV for all predictions with market features
    
    Updates model_inference_logs with:
    - ev_close_* : EV for each outcome
    - ev_close_pick : EV for the model's chosen outcome
    - clv_prob_* : CLV for each outcome
    - clv_prob_pick : CLV for the model's chosen outcome
    - pick_outcome : The model's chosen outcome (H/D/A)
    - close_ts : Closing timestamp from market_features
    """
    logger.info("\n" + "="*70)
    logger.info("💰 COMPUTING EV & CLV FOR MODEL PREDICTIONS")
    logger.info("="*70 + "\n")
    
    conn = psycopg2.connect(os.getenv('DATABASE_URL'))
    cursor = conn.cursor()
    
    try:
        # Get all predictions with market features
        sql = """
        SELECT 
            mil.id,
            mil.match_id,
            mil.model_version,
            mil.p_home,
            mil.p_draw,
            mil.p_away,
            mf.p_open_home,
            mf.p_open_draw,
            mf.p_open_away,
            mf.p_last_home,
            mf.p_last_draw,
            mf.p_last_away,
            mf.ts_last
        FROM model_inference_logs mil
        JOIN market_features mf ON mil.match_id = mf.match_id
        WHERE mil.ev_close_pick IS NULL
          OR mil.clv_prob_pick IS NULL
        ORDER BY mil.id
        """
        
        cursor.execute(sql)
        rows = cursor.fetchall()
        
        if not rows:
            logger.info("✅ All predictions already have EV/CLV computed")
            return
        
        logger.info(f"📊 Found {len(rows)} predictions to compute EV/CLV for")
        
        updates = []
        
        for row in rows:
            (
                pred_id, match_id, model_version,
                p_home, p_draw, p_away,
                p_open_home, p_open_draw, p_open_away,
                p_close_home, p_close_draw, p_close_away,
                ts_close
            ) = row
            
            # Convert to float for calculations
            p_home = float(p_home)
            p_draw = float(p_draw)
            p_away = float(p_away)
            
            # Handle None values in market features
            if None in [p_open_home, p_open_draw, p_open_away, p_close_home, p_close_draw, p_close_away]:
                logger.warning(f"⚠️ Match {match_id}: Missing market features, skipping")
                continue
            
            p_open_home = float(p_open_home)
            p_open_draw = float(p_open_draw)
            p_open_away = float(p_open_away)
            p_close_home = float(p_close_home)
            p_close_draw = float(p_close_draw)
            p_close_away = float(p_close_away)
            
            # === EV CLOSE (model prob - closing market prob) ===
            ev_close_home = p_home - p_close_home
            ev_close_draw = p_draw - p_close_draw
            ev_close_away = p_away - p_close_away
            
            # === CLV PROB (closing prob - opening prob) ===
            clv_prob_home = p_close_home - p_open_home
            clv_prob_draw = p_close_draw - p_open_draw
            clv_prob_away = p_close_away - p_open_away
            
            # === Determine model's pick (highest probability) ===
            probs = {'H': p_home, 'D': p_draw, 'A': p_away}
            pick_outcome = max(probs, key=probs.get)
            
            # === EV and CLV for the picked outcome ===
            if pick_outcome == 'H':
                ev_close_pick = ev_close_home
                clv_prob_pick = clv_prob_home
            elif pick_outcome == 'D':
                ev_close_pick = ev_close_draw
                clv_prob_pick = clv_prob_draw
            else:  # 'A'
                ev_close_pick = ev_close_away
                clv_prob_pick = clv_prob_away
            
            updates.append({
                'id': pred_id,
                'ev_close_home': ev_close_home,
                'ev_close_draw': ev_close_draw,
                'ev_close_away': ev_close_away,
                'ev_close_pick': ev_close_pick,
                'clv_prob_home': clv_prob_home,
                'clv_prob_draw': clv_prob_draw,
                'clv_prob_away': clv_prob_away,
                'clv_prob_pick': clv_prob_pick,
                'pick_outcome': pick_outcome,
                'close_ts': ts_close
            })
        
        # === Batch update ===
        logger.info(f"💾 Updating {len(updates)} predictions with EV/CLV...")
        
        update_sql = """
        UPDATE model_inference_logs
        SET 
            ev_close_home = %s,
            ev_close_draw = %s,
            ev_close_away = %s,
            ev_close_pick = %s,
            clv_prob_home = %s,
            clv_prob_draw = %s,
            clv_prob_away = %s,
            clv_prob_pick = %s,
            pick_outcome = %s,
            close_ts = %s
        WHERE id = %s
        """
        
        for update in updates:
            cursor.execute(update_sql, (
                update['ev_close_home'],
                update['ev_close_draw'],
                update['ev_close_away'],
                update['ev_close_pick'],
                update['clv_prob_home'],
                update['clv_prob_draw'],
                update['clv_prob_away'],
                update['clv_prob_pick'],
                update['pick_outcome'],
                update['close_ts'],
                update['id']
            ))
        
        conn.commit()
        
        logger.info(f"✅ Successfully updated {len(updates)} predictions")
        
        # === Summary statistics ===
        cursor.execute("""
        SELECT 
            COUNT(*) as total,
            AVG(ev_close_pick) as avg_ev,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ev_close_pick) as median_ev,
            AVG(clv_prob_pick) as avg_clv,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY clv_prob_pick) as median_clv,
            SUM(CASE WHEN ev_close_pick > 0 THEN 1 ELSE 0 END) as positive_ev_count,
            SUM(CASE WHEN clv_prob_pick > 0 THEN 1 ELSE 0 END) as positive_clv_count
        FROM model_inference_logs
        WHERE ev_close_pick IS NOT NULL
        """)
        
        stats = cursor.fetchone()
        if stats:
            total, avg_ev, median_ev, avg_clv, median_clv, pos_ev, pos_clv = stats
            
            logger.info("\n" + "="*70)
            logger.info("📊 EV & CLV SUMMARY STATISTICS")
            logger.info("="*70)
            logger.info(f"Total predictions: {total}")
            logger.info(f"\nExpected Value (Close):")
            logger.info(f"  Mean EV:       {avg_ev:.4f}")
            logger.info(f"  Median EV:     {median_ev:.4f}")
            logger.info(f"  Positive EV:   {pos_ev}/{total} ({100*pos_ev/total:.1f}%)")
            logger.info(f"\nClosing Line Value:")
            logger.info(f"  Mean CLV:      {avg_clv:.4f}")
            logger.info(f"  Median CLV:    {median_clv:.4f}")
            logger.info(f"  Positive CLV:  {pos_clv}/{total} ({100*pos_clv/total:.1f}%)")
            logger.info("="*70 + "\n")
    
    except Exception as e:
        logger.error(f"❌ Error computing EV/CLV: {e}")
        conn.rollback()
        raise
    
    finally:
        cursor.close()
        conn.close()


def main():
    """Main entry point"""
    try:
        compute_ev_clv_for_predictions()
        logger.info("✅ EV/CLV computation complete!")
    
    except Exception as e:
        logger.error(f"❌ Job failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
