"""
One-time backfill: populate parlay_precomputed_legs.result for all
settled parlays that still have NULL leg results.

Run once:
    python jobs/backfill_parlay_leg_results.py
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from models.automated_parlay_generator import AutomatedParlayGenerator

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def backfill():
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    Session = sessionmaker(bind=engine)
    session = Session()
    gen = AutomatedParlayGenerator()

    try:
        rows = session.execute(text("""
            SELECT DISTINCT pp.id, pp.parlay_hash
            FROM parlay_precomputed pp
            JOIN parlay_precomputed_legs ppl ON pp.id = ppl.parlay_id
            WHERE pp.status = 'settled'
            AND ppl.result IS NULL
            ORDER BY pp.id
        """)).fetchall()

        logger.info(f"Found {len(rows)} settled parlays with NULL leg results")
        updated_parlays = 0
        updated_legs = 0

        for row in rows:
            parlay_id = row[0]
            legs = session.execute(text("""
                SELECT ppl.leg_index, ppl.leg_type, ppl.market_code, ppl.player_id,
                       m.home_goals AS home_score, m.away_goals AS away_score,
                       m.outcome AS match_result
                FROM parlay_precomputed_legs ppl
                JOIN matches m ON ppl.match_id = m.match_id
                WHERE ppl.parlay_id = :parlay_id
                ORDER BY ppl.leg_index
            """), {"parlay_id": parlay_id}).fetchall()

            if not legs:
                logger.debug(f"Parlay {parlay_id}: no matching match rows, skipping")
                continue

            for leg in legs:
                leg_won = gen._check_leg_result(
                    leg.leg_type, leg.market_code, leg.player_id,
                    leg.home_score, leg.away_score, leg.match_result
                )
                leg_result = "won" if leg_won else "lost"
                session.execute(text("""
                    UPDATE parlay_precomputed_legs
                    SET result = :result
                    WHERE parlay_id = :parlay_id AND leg_index = :leg_index
                """), {"result": leg_result, "parlay_id": parlay_id, "leg_index": leg.leg_index})
                updated_legs += 1

            updated_parlays += 1

        session.commit()
        logger.info(f"Backfill complete: {updated_parlays} parlays, {updated_legs} legs updated")

    except Exception as e:
        session.rollback()
        logger.error(f"Backfill failed: {e}", exc_info=True)
        raise
    finally:
        session.close()


if __name__ == "__main__":
    backfill()
