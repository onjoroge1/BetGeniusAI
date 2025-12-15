"""
Multi-Sport Training Data Sync

Syncs completed fixtures with their odds history into the multisport_training table.
Builds features from odds snapshots for ML training.

Usage:
    from training.multisport_training_sync import sync_training_data
    results = sync_training_data()  # Sync all sports
    results = sync_training_data(sport='basketball')  # Sync specific sport
"""

import os
import logging
import json
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import numpy as np

logger = logging.getLogger(__name__)


class MultiSportTrainingSync:
    """
    Syncs completed multi-sport fixtures with their odds features
    into the training table for ML model development.
    """
    
    def __init__(self):
        self.db_url = os.getenv('DATABASE_URL')
        if not self.db_url:
            raise ValueError("DATABASE_URL not set")
        
        self.metrics = {
            'synced': 0,
            'skipped_no_odds': 0,
            'skipped_exists': 0,
            'errors': 0
        }
    
    def sync_all_sports(self) -> Dict:
        """Sync training data for all sports"""
        results = {}
        
        for sport in ['basketball', 'hockey']:
            try:
                result = self.sync_sport(sport)
                results[sport] = result
            except Exception as e:
                logger.error(f"Error syncing {sport}: {e}")
                results[sport] = {'error': str(e)}
        
        return results
    
    def sync_sport(self, sport: str) -> Dict:
        """
        Sync completed fixtures for a specific sport into training table.
        
        Args:
            sport: 'basketball' or 'hockey'
        """
        logger.info(f"🔄 Syncing {sport} training data...")
        
        conn = psycopg2.connect(self.db_url)
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        try:
            # Get completed fixtures not yet in training
            cursor.execute("""
                SELECT f.* 
                FROM multisport_fixtures f
                LEFT JOIN multisport_training t 
                    ON t.sport = f.sport AND t.event_id = f.event_id
                WHERE f.sport = %s 
                    AND f.home_score IS NOT NULL 
                    AND f.away_score IS NOT NULL
                    AND t.id IS NULL
                ORDER BY f.commence_time
            """, (sport,))
            
            fixtures = cursor.fetchall()
            logger.info(f"  Found {len(fixtures)} completed fixtures to sync")
            
            synced = 0
            skipped_no_odds = 0
            
            for fixture in fixtures:
                # Build features from odds snapshots
                features = self._build_features(cursor, fixture)
                
                if not features:
                    skipped_no_odds += 1
                    continue
                
                # Calculate consensus probabilities
                consensus = self._calculate_consensus(cursor, fixture)
                
                # Insert into training table
                cursor.execute("""
                    INSERT INTO multisport_training 
                    (sport, sport_key, event_id, home_team, away_team, match_date,
                     home_score, away_score, outcome, features,
                     consensus_home_prob, consensus_away_prob, consensus_draw_prob)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (sport, event_id) DO NOTHING
                """, (
                    fixture['sport'],
                    fixture['sport_key'],
                    fixture['event_id'],
                    fixture['home_team'],
                    fixture['away_team'],
                    fixture['commence_time'].date(),
                    fixture['home_score'],
                    fixture['away_score'],
                    fixture['outcome'],
                    json.dumps(features),
                    consensus.get('home_prob'),
                    consensus.get('away_prob'),
                    consensus.get('draw_prob')
                ))
                synced += 1
            
            conn.commit()
            
            self.metrics['synced'] += synced
            self.metrics['skipped_no_odds'] += skipped_no_odds
            
            logger.info(f"  ✅ Synced {synced} fixtures, skipped {skipped_no_odds} (no odds)")
            
            return {
                'sport': sport,
                'synced': synced,
                'skipped_no_odds': skipped_no_odds,
                'total_in_training': self._count_training(cursor, sport)
            }
            
        except Exception as e:
            conn.rollback()
            logger.error(f"Error syncing {sport}: {e}")
            self.metrics['errors'] += 1
            raise
        finally:
            conn.close()
    
    def _build_features(self, cursor, fixture: Dict) -> Optional[Dict]:
        """
        Build feature vector from odds snapshots for a fixture.
        
        Features include:
        - Opening/closing odds and their drift
        - Spread and totals lines
        - Market efficiency indicators
        - Bookmaker consensus metrics
        """
        event_id = fixture['event_id']
        commence_time = fixture['commence_time']
        
        # Get key odds snapshots for this event (opening, mid, and closing)
        # Use a window function to get representative snapshots without loading all 5000+
        cursor.execute("""
            WITH ordered AS (
                SELECT *, 
                    ROW_NUMBER() OVER (ORDER BY ts_recorded ASC) as rn,
                    COUNT(*) OVER () as total
                FROM multisport_odds_snapshots
                WHERE event_id = %s
            )
            SELECT * FROM ordered
            WHERE rn = 1 OR rn = total OR rn = total/2
            ORDER BY ts_recorded ASC
        """, (event_id,))
        
        snapshots = cursor.fetchall()
        
        if not snapshots:
            return None
        
        # Opening odds (earliest)
        opening = snapshots[0]
        # Closing odds (latest before match start)
        closing = snapshots[-1]
        
        # Calculate features
        features = {}
        
        # === Moneyline (H2H) Features ===
        if opening['home_odds'] and closing['home_odds']:
            features['open_home_odds'] = float(opening['home_odds'])
            features['open_away_odds'] = float(opening['away_odds'])
            features['close_home_odds'] = float(closing['home_odds'])
            features['close_away_odds'] = float(closing['away_odds'])
            
            # Odds drift (positive = odds shortened = more bets on that side)
            features['home_odds_drift'] = float(opening['home_odds']) - float(closing['home_odds'])
            features['away_odds_drift'] = float(opening['away_odds']) - float(closing['away_odds'])
            
            # Implied probabilities
            features['open_home_prob'] = 1 / float(opening['home_odds']) if opening['home_odds'] else 0
            features['open_away_prob'] = 1 / float(opening['away_odds']) if opening['away_odds'] else 0
            features['close_home_prob'] = 1 / float(closing['home_odds']) if closing['home_odds'] else 0
            features['close_away_prob'] = 1 / float(closing['away_odds']) if closing['away_odds'] else 0
            
            # Probability drift
            features['home_prob_drift'] = features['close_home_prob'] - features['open_home_prob']
            features['away_prob_drift'] = features['close_away_prob'] - features['open_away_prob']
        
        # === Spread Features (for basketball/hockey) ===
        if closing.get('home_spread') is not None:
            features['spread_line'] = float(closing['home_spread'])
            features['home_spread_odds'] = float(closing['home_spread_odds']) if closing['home_spread_odds'] else None
            features['away_spread_odds'] = float(closing['away_spread_odds']) if closing['away_spread_odds'] else None
            
            # Opening spread if available
            if opening.get('home_spread') is not None:
                features['open_spread'] = float(opening['home_spread'])
                features['spread_drift'] = float(opening['home_spread']) - float(closing['home_spread'])
        
        # === Totals Features ===
        if closing.get('total_line') is not None:
            features['total_line'] = float(closing['total_line'])
            features['over_odds'] = float(closing['over_odds']) if closing['over_odds'] else None
            features['under_odds'] = float(closing['under_odds']) if closing['under_odds'] else None
            
            # Opening total if available
            if opening.get('total_line') is not None:
                features['open_total'] = float(opening['total_line'])
                features['total_drift'] = float(closing['total_line']) - float(opening['total_line'])
        
        # === Market Efficiency Features ===
        if closing.get('overround'):
            features['overround'] = float(closing['overround'])
        
        features['n_bookmakers'] = int(closing['n_bookmakers']) if closing['n_bookmakers'] else 1
        
        # Time features - handle timezone-aware vs naive datetimes
        last_snapshot_time = snapshots[-1]['ts_recorded']
        if commence_time.tzinfo is not None and last_snapshot_time.tzinfo is None:
            from datetime import timezone
            last_snapshot_time = last_snapshot_time.replace(tzinfo=timezone.utc)
        elif commence_time.tzinfo is None and last_snapshot_time.tzinfo is not None:
            commence_time = commence_time.replace(tzinfo=timezone.utc)
        
        try:
            features['hours_before_match'] = max(0, (commence_time - last_snapshot_time).total_seconds() / 3600)
        except TypeError:
            features['hours_before_match'] = 0.0
        
        # Odds volatility - query aggregate stats directly from DB for efficiency
        cursor.execute("""
            SELECT STDDEV(home_odds) as vol, COUNT(*) as cnt
            FROM multisport_odds_snapshots
            WHERE event_id = %s AND home_odds IS NOT NULL
        """, (event_id,))
        vol_result = cursor.fetchone()
        if vol_result and vol_result['vol'] and vol_result['cnt'] >= 3:
            features['home_odds_volatility'] = float(vol_result['vol'])
        else:
            features['home_odds_volatility'] = 0.0
        features['n_snapshots'] = int(vol_result['cnt']) if vol_result else len(snapshots)
        
        # === Derived Features ===
        # Favorite indicator (based on closing odds)
        if features.get('close_home_odds') and features.get('close_away_odds'):
            features['home_is_favorite'] = 1 if features['close_home_odds'] < features['close_away_odds'] else 0
            features['odds_diff'] = features['close_home_odds'] - features['close_away_odds']
            features['prob_diff'] = features['close_home_prob'] - features['close_away_prob']
        
        return features
    
    def _calculate_consensus(self, cursor, fixture: Dict) -> Dict:
        """Calculate consensus probabilities from odds snapshots"""
        
        cursor.execute("""
            SELECT 
                AVG(home_prob) as home_prob,
                AVG(away_prob) as away_prob,
                AVG(draw_prob) as draw_prob
            FROM multisport_odds_snapshots
            WHERE event_id = %s
                AND is_consensus = true
        """, (fixture['event_id'],))
        
        result = cursor.fetchone()
        
        if result and result['home_prob']:
            return {
                'home_prob': float(result['home_prob']),
                'away_prob': float(result['away_prob']),
                'draw_prob': float(result['draw_prob']) if result['draw_prob'] else 0.0
            }
        
        # Fallback: use latest closing odds
        cursor.execute("""
            SELECT home_prob, away_prob, draw_prob
            FROM multisport_odds_snapshots
            WHERE event_id = %s
            ORDER BY ts_recorded DESC
            LIMIT 1
        """, (fixture['event_id'],))
        
        result = cursor.fetchone()
        
        if result:
            return {
                'home_prob': float(result['home_prob']) if result['home_prob'] else 0.5,
                'away_prob': float(result['away_prob']) if result['away_prob'] else 0.5,
                'draw_prob': float(result['draw_prob']) if result['draw_prob'] else 0.0
            }
        
        return {'home_prob': 0.5, 'away_prob': 0.5, 'draw_prob': 0.0}
    
    def _count_training(self, cursor, sport: str) -> int:
        """Count total training records for a sport"""
        cursor.execute("""
            SELECT COUNT(*) FROM multisport_training WHERE sport = %s
        """, (sport,))
        return cursor.fetchone()[0]


def sync_training_data(sport: Optional[str] = None) -> Dict:
    """
    Entry point for syncing multi-sport training data.
    
    Args:
        sport: Optional sport filter ('basketball' or 'hockey')
    
    Returns:
        Dict with sync results per sport
    """
    syncer = MultiSportTrainingSync()
    
    if sport:
        return syncer.sync_sport(sport)
    else:
        return syncer.sync_all_sports()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    results = sync_training_data()
    print(f"\nSync Results: {json.dumps(results, indent=2)}")
