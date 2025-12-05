"""
League ECE (Expected Calibration Error) Calculator

Calculates per-league calibration metrics to weight predictions appropriately.
Well-calibrated leagues get higher confidence weights.

V3 Features derived:
1. league_ece - Calibration error (lower is better)
2. league_tier_weight - Prediction confidence weight (A=1.0, B=0.8, C=0.6, D=0.4)
3. league_historical_edge - Historical model performance vs market

Runs: Weekly (Sunday 02:00 UTC)
"""

import os
import logging
import numpy as np
import psycopg2
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Tuple, Optional

logger = logging.getLogger(__name__)


class LeagueECECalculator:
    """
    Calculates Expected Calibration Error and other metrics per league
    
    ECE measures how well-calibrated predictions are:
    - Predictions of 70% should win 70% of the time
    - Lower ECE = better calibrated model
    """
    
    ECE_THRESHOLDS = {
        'A': 0.05,   # ECE < 5% = excellent calibration
        'B': 0.10,   # ECE < 10% = good calibration
        'C': 0.15,   # ECE < 15% = acceptable calibration
        'D': 1.00    # ECE >= 15% = poor calibration
    }
    
    TIER_WEIGHTS = {
        'A': 1.00,
        'B': 0.85,
        'C': 0.70,
        'D': 0.50
    }
    
    MIN_MATCHES_FOR_CALIBRATION = 30  # Need at least 30 matches per league
    ROLLING_WINDOW_DAYS = 90  # Use last 90 days of data
    
    def __init__(self):
        self.db_url = os.getenv('DATABASE_URL')
        if not self.db_url:
            raise ValueError("DATABASE_URL not set")
    
    def calculate_all_leagues(self) -> Dict:
        """Calculate ECE for all leagues with sufficient data"""
        
        logger.info("🎯 Starting League ECE calculation...")
        
        results = {
            'leagues_processed': 0,
            'leagues_updated': 0,
            'leagues_skipped': 0,
            'errors': []
        }
        
        try:
            conn = psycopg2.connect(self.db_url)
            cursor = conn.cursor()
            
            # Get leagues with enough finished predictions
            leagues = self._get_eligible_leagues(cursor)
            logger.info(f"  Found {len(leagues)} leagues with sufficient data")
            
            for league_id, league_name in leagues:
                try:
                    metrics = self._calculate_league_metrics(cursor, league_id)
                    
                    if metrics:
                        self._store_calibration(cursor, league_id, league_name, metrics)
                        results['leagues_updated'] += 1
                    else:
                        results['leagues_skipped'] += 1
                        
                    results['leagues_processed'] += 1
                    
                except Exception as e:
                    logger.error(f"  Error processing league {league_id}: {e}")
                    results['errors'].append(f"{league_id}: {str(e)}")
            
            conn.commit()
            cursor.close()
            conn.close()
            
            logger.info(f"✅ ECE calculation complete: {results['leagues_updated']} leagues updated")
            
        except Exception as e:
            logger.error(f"❌ ECE calculation failed: {e}")
            results['errors'].append(str(e))
        
        return results
    
    def _get_eligible_leagues(self, cursor) -> List[Tuple[int, str]]:
        """Get leagues with enough finished matches for calibration"""
        
        window_start = datetime.now(timezone.utc) - timedelta(days=self.ROLLING_WINDOW_DAYS)
        
        cursor.execute("""
            SELECT 
                f.league_id,
                COALESCE(lm.league_name, f.league_name) as league_name,
                COUNT(*) as match_count
            FROM consensus_predictions p
            JOIN fixtures f ON p.match_id = f.match_id
            LEFT JOIN league_map lm ON f.league_id = lm.league_id
            WHERE f.status = 'finished'
              AND f.kickoff_at >= %s
              AND p.consensus_h > 0 AND p.consensus_a > 0
            GROUP BY f.league_id, COALESCE(lm.league_name, f.league_name)
            HAVING COUNT(*) >= %s
            ORDER BY match_count DESC
        """, (window_start, self.MIN_MATCHES_FOR_CALIBRATION))
        
        return cursor.fetchall()
    
    def _calculate_league_metrics(self, cursor, league_id: int) -> Optional[Dict]:
        """Calculate calibration metrics for a specific league"""
        
        window_start = datetime.now(timezone.utc) - timedelta(days=self.ROLLING_WINDOW_DAYS)
        
        # Get predictions and outcomes (join with matches for results)
        cursor.execute("""
            SELECT 
                p.consensus_h,
                p.consensus_d,
                p.consensus_a,
                CASE 
                    WHEN m.home_score > m.away_score THEN 'H'
                    WHEN m.home_score < m.away_score THEN 'A'
                    ELSE 'D'
                END as outcome
            FROM consensus_predictions p
            JOIN fixtures f ON p.match_id = f.match_id
            LEFT JOIN matches m ON f.match_id = m.id
            WHERE f.league_id = %s
              AND f.status = 'finished'
              AND f.kickoff_at >= %s
              AND p.consensus_h > 0 AND p.consensus_a > 0
              AND m.home_score IS NOT NULL
        """, (league_id, window_start))
        
        rows = cursor.fetchall()
        
        if len(rows) < self.MIN_MATCHES_FOR_CALIBRATION:
            return None
        
        # Convert to arrays
        probs_home = np.array([r[0] for r in rows])
        probs_draw = np.array([r[1] for r in rows])
        probs_away = np.array([r[2] for r in rows])
        outcomes = [r[3] for r in rows]
        
        # Create one-hot outcome vectors
        outcome_home = np.array([1 if o == 'H' else 0 for o in outcomes])
        outcome_draw = np.array([1 if o == 'D' else 0 for o in outcomes])
        outcome_away = np.array([1 if o == 'A' else 0 for o in outcomes])
        
        # Calculate ECE (average across 3 outcomes)
        ece_home = self._calculate_ece(probs_home, outcome_home)
        ece_draw = self._calculate_ece(probs_draw, outcome_draw)
        ece_away = self._calculate_ece(probs_away, outcome_away)
        ece_avg = (ece_home + ece_draw + ece_away) / 3
        
        # Calculate Brier score
        brier = self._calculate_brier(probs_home, probs_draw, probs_away, 
                                       outcome_home, outcome_draw, outcome_away)
        
        # Calculate Log Loss
        log_loss = self._calculate_log_loss(probs_home, probs_draw, probs_away,
                                            outcome_home, outcome_draw, outcome_away)
        
        # Calculate 3-way accuracy
        pred_outcomes = []
        for ph, pd, pa in zip(probs_home, probs_draw, probs_away):
            if ph >= pd and ph >= pa:
                pred_outcomes.append('H')
            elif pd >= ph and pd >= pa:
                pred_outcomes.append('D')
            else:
                pred_outcomes.append('A')
        
        accuracy = sum(1 for p, a in zip(pred_outcomes, outcomes) if p == a) / len(outcomes)
        
        # Determine tier
        tier = self._get_tier(ece_avg)
        tier_weight = self.TIER_WEIGHTS[tier]
        
        return {
            'ece_score': ece_avg,
            'brier_score': brier,
            'log_loss': log_loss,
            'accuracy_3way': accuracy,
            'n_matches': len(rows),
            'tier': tier,
            'tier_weight': tier_weight,
            'window_start': window_start.date(),
            'window_end': datetime.now(timezone.utc).date()
        }
    
    def _calculate_ece(self, probs: np.ndarray, outcomes: np.ndarray, n_bins: int = 10) -> float:
        """
        Calculate Expected Calibration Error
        
        ECE = sum over bins of |accuracy(bin) - confidence(bin)| * weight(bin)
        """
        
        bin_boundaries = np.linspace(0, 1, n_bins + 1)
        ece = 0.0
        
        for i in range(n_bins):
            in_bin = (probs > bin_boundaries[i]) & (probs <= bin_boundaries[i + 1])
            prop_in_bin = in_bin.mean()
            
            if prop_in_bin > 0:
                avg_confidence = probs[in_bin].mean()
                avg_accuracy = outcomes[in_bin].mean()
                ece += np.abs(avg_accuracy - avg_confidence) * prop_in_bin
        
        return float(ece)
    
    def _calculate_brier(self, ph: np.ndarray, pd: np.ndarray, pa: np.ndarray,
                         oh: np.ndarray, od: np.ndarray, oa: np.ndarray) -> float:
        """Calculate Brier score (lower is better)"""
        
        brier = ((ph - oh) ** 2 + (pd - od) ** 2 + (pa - oa) ** 2).mean()
        return float(brier)
    
    def _calculate_log_loss(self, ph: np.ndarray, pd: np.ndarray, pa: np.ndarray,
                            oh: np.ndarray, od: np.ndarray, oa: np.ndarray) -> float:
        """Calculate Log Loss (lower is better)"""
        
        eps = 1e-15
        ph = np.clip(ph, eps, 1 - eps)
        pd = np.clip(pd, eps, 1 - eps)
        pa = np.clip(pa, eps, 1 - eps)
        
        log_loss = -(oh * np.log(ph) + od * np.log(pd) + oa * np.log(pa)).mean()
        return float(log_loss)
    
    def _get_tier(self, ece: float) -> str:
        """Determine calibration tier from ECE score"""
        
        if ece < self.ECE_THRESHOLDS['A']:
            return 'A'
        elif ece < self.ECE_THRESHOLDS['B']:
            return 'B'
        elif ece < self.ECE_THRESHOLDS['C']:
            return 'C'
        else:
            return 'D'
    
    def _store_calibration(self, cursor, league_id: int, league_name: str, metrics: Dict):
        """Store calibration metrics in database"""
        
        cursor.execute("""
            INSERT INTO league_calibration (
                league_id, league_name, sport,
                ece_score, brier_score, log_loss, accuracy_3way,
                n_matches, window_start, window_end,
                tier, tier_weight, updated_at
            ) VALUES (
                %s, %s, 'soccer',
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, NOW()
            )
            ON CONFLICT (league_id, window_end) 
            DO UPDATE SET
                ece_score = EXCLUDED.ece_score,
                brier_score = EXCLUDED.brier_score,
                log_loss = EXCLUDED.log_loss,
                accuracy_3way = EXCLUDED.accuracy_3way,
                n_matches = EXCLUDED.n_matches,
                tier = EXCLUDED.tier,
                tier_weight = EXCLUDED.tier_weight,
                updated_at = NOW()
        """, (
            league_id, league_name,
            metrics['ece_score'], metrics['brier_score'], 
            metrics['log_loss'], metrics['accuracy_3way'],
            metrics['n_matches'], metrics['window_start'], metrics['window_end'],
            metrics['tier'], metrics['tier_weight']
        ))
        
        logger.debug(f"  League {league_id}: ECE={metrics['ece_score']:.3f}, Tier={metrics['tier']}")


def get_league_ece_calculator():
    """Factory function to get LeagueECECalculator instance"""
    return LeagueECECalculator()


def run_league_ece_calculation():
    """Entry point for scheduler"""
    try:
        calculator = get_league_ece_calculator()
        return calculator.calculate_all_leagues()
    except Exception as e:
        logger.error(f"League ECE calculation failed: {e}")
        return {'error': str(e)}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = run_league_ece_calculation()
    print(f"Result: {result}")
