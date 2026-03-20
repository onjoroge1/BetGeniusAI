"""
Multi-Sport Data Collector
Collects match results, schedules, and syncs training data for NBA, NHL, NFL, and NCAAB.
Uses The Odds API for match results/scores (same API as odds collection).

This collector works alongside the odds collector to populate match results.
"""

import os
import logging
import json
import requests
import psycopg2
import psycopg2.extras
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class MultiSportDataCollector:
    """
    Unified collector for multi-sport data.
    Uses The Odds API for match results (same API key as odds).
    Collects: match results, schedules
    Sports: NBA, NHL, NFL, NCAAB
    """
    
    SPORT_CONFIGS = {
        'basketball_nba': {
            'name': 'NBA',
            'sport': 'basketball',
            'active_months': [10, 11, 12, 1, 2, 3, 4, 5, 6],
            'has_playoffs': True
        },
        'basketball_ncaab': {
            'name': 'NCAAB',
            'sport': 'basketball',
            'active_months': [11, 12, 1, 2, 3, 4],  # Nov-Apr (regular season + March Madness)
            'has_playoffs': True
        },
        'icehockey_nhl': {
            'name': 'NHL',
            'sport': 'hockey',
            'active_months': [10, 11, 12, 1, 2, 3, 4, 5, 6],
            'has_playoffs': True
        },
        'americanfootball_nfl': {
            'name': 'NFL',
            'sport': 'american-football',
            'active_months': [9, 10, 11, 12, 1, 2],  # Sept-Feb
            'has_playoffs': True,
            'has_weeks': True
        }
    }
    
    def __init__(self):
        self.odds_api_key = os.getenv('ODDS_API_KEY')
        self.db_url = os.getenv('DATABASE_URL')
        self.base_url = "https://api.the-odds-api.com/v4"
        
        if not self.odds_api_key:
            logger.warning("ODDS_API_KEY not set")
        
        self.metrics = {
            'api_calls': 0,
            'matches_stored': 0,
            'schedule_updated': 0,
            'errors': 0
        }
    
    def collect_all_sports(self) -> Dict:
        """Collect data for all active sports"""
        current_month = datetime.now().month
        results = {}
        
        for sport_key, config in self.SPORT_CONFIGS.items():
            if current_month in config['active_months']:
                logger.info(f"📊 Collecting {config['name']} data...")
                try:
                    result = self.collect_sport_data(sport_key)
                    results[sport_key] = result
                except Exception as e:
                    logger.error(f"❌ {config['name']} collection failed: {e}")
                    results[sport_key] = {'error': str(e)}
                    self.metrics['errors'] += 1
            else:
                logger.debug(f"⏸️ {config['name']} is off-season")
                results[sport_key] = {'status': 'off_season'}
        
        return results
    
    def collect_sport_data(self, sport_key: str) -> Dict:
        """Collect all data types for a specific sport"""
        config = self.SPORT_CONFIGS.get(sport_key)
        if not config:
            return {'error': f'Unknown sport: {sport_key}'}
        
        results = {'sport': sport_key, 'name': config['name']}
        
        # Collect scores/results from The Odds API
        games_result = self.collect_scores(sport_key, config)
        results['games'] = games_result
        
        # Sync completed games to training table
        sync_result = self.sync_to_training_table(sport_key)
        results['training_sync'] = sync_result
        
        return results
    
    def collect_scores(self, sport_key: str, config: Dict, days_from: int = 3) -> Dict:
        """
        Collect scores from The Odds API.
        Uses the /scores endpoint which returns completed games.
        """
        if not self.odds_api_key:
            return {'error': 'ODDS_API_KEY not configured'}
        
        url = f"{self.base_url}/sports/{sport_key}/scores"
        params = {
            'apiKey': self.odds_api_key,
            'daysFrom': days_from  # Get scores from last N days
        }
        
        try:
            response = requests.get(url, params=params, timeout=30)
            self.metrics['api_calls'] += 1
            
            if response.status_code == 404:
                logger.debug(f"No scores available for {sport_key}")
                return {'fetched': 0, 'stored': 0}
            
            if response.status_code != 200:
                logger.warning(f"API error {response.status_code} for {sport_key}: {response.text[:200]}")
                return {'error': f'API returned {response.status_code}'}
            
            scores = response.json()
            stored = self._store_scores(scores, sport_key, config)
            
            return {
                'fetched': len(scores),
                'stored': stored,
                'days_from': days_from
            }
            
        except Exception as e:
            logger.error(f"Scores request failed for {sport_key}: {e}")
            self.metrics['errors'] += 1
            return {'error': str(e)}
    
    def _store_scores(self, scores: List[Dict], sport_key: str, config: Dict) -> int:
        """Store scores in multisport_match_results table"""
        
        if not scores:
            return 0
        
        stored_count = 0
        
        try:
            conn = psycopg2.connect(self.db_url)
            cursor = conn.cursor()
            
            for game in scores:
                try:
                    event_id = game.get('id')
                    home_team = game.get('home_team')
                    away_team = game.get('away_team')
                    commence_time = game.get('commence_time')
                    completed = game.get('completed', False)
                    
                    if not all([event_id, home_team, away_team]):
                        continue
                    
                    # Parse commence time
                    try:
                        game_dt = datetime.fromisoformat(commence_time.replace('Z', '+00:00'))
                    except:
                        game_dt = datetime.now(timezone.utc)
                    
                    # Get scores
                    home_score = None
                    away_score = None
                    
                    for score_entry in game.get('scores', []):
                        if score_entry.get('name') == home_team:
                            home_score = int(score_entry.get('score', 0))
                        elif score_entry.get('name') == away_team:
                            away_score = int(score_entry.get('score', 0))
                    
                    # Determine result
                    if completed and home_score is not None and away_score is not None:
                        result = 'H' if home_score > away_score else 'A'
                        status = 'final'
                    else:
                        result = None
                        status = 'scheduled' if not completed else 'in_progress'
                    
                    # Store in schedule table (all games)
                    cursor.execute("""
                        INSERT INTO multisport_schedule (
                            sport_key, event_id,
                            home_team, away_team, commence_time,
                            status, updated_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, NOW())
                        ON CONFLICT (sport_key, event_id) 
                        DO UPDATE SET
                            status = EXCLUDED.status,
                            updated_at = NOW()
                    """, (
                        sport_key, event_id,
                        home_team, away_team, game_dt,
                        status
                    ))
                    
                    # Store in results table (completed games only)
                    if completed and home_score is not None:
                        cursor.execute("""
                            INSERT INTO multisport_match_results (
                                sport_key, event_id, game_date,
                                home_team, away_team,
                                home_score, away_score, result,
                                status, updated_at
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                            ON CONFLICT (sport_key, event_id)
                            DO UPDATE SET
                                home_score = EXCLUDED.home_score,
                                away_score = EXCLUDED.away_score,
                                result = EXCLUDED.result,
                                status = EXCLUDED.status,
                                updated_at = NOW()
                        """, (
                            sport_key, event_id, game_dt,
                            home_team, away_team,
                            home_score, away_score, result,
                            status
                        ))
                        
                        stored_count += 1
                    
                except Exception as e:
                    logger.debug(f"Error storing game: {e}")
                    continue
            
            conn.commit()
            cursor.close()
            conn.close()
            
            self.metrics['matches_stored'] += stored_count
            
        except Exception as e:
            logger.error(f"Database error: {e}")
            self.metrics['errors'] += 1
        
        return stored_count
    
    def sync_to_training_table(self, sport_key: str) -> Dict:
        """
        Sync completed matches with odds to multisport_training table.
        This creates labeled training data by joining results with odds.
        """
        try:
            conn = psycopg2.connect(self.db_url)
            cursor = conn.cursor()
            
            # Find completed matches that have odds but aren't in training table
            # Note: multisport_training has both 'sport' and 'sport_key' columns
            cursor.execute("""
                INSERT INTO multisport_training (
                    sport, sport_key, event_id, home_team, away_team,
                    match_date, home_score, away_score, outcome,
                    consensus_home_prob, consensus_away_prob
                )
                SELECT DISTINCT ON (r.event_id)
                    o.sport,
                    r.sport_key,
                    r.event_id,
                    r.home_team,
                    r.away_team,
                    r.game_date::date,
                    r.home_score,
                    r.away_score,
                    r.result,
                    o.home_prob,
                    o.away_prob
                FROM multisport_match_results r
                INNER JOIN multisport_odds_snapshots o 
                    ON r.event_id = o.event_id 
                    AND r.sport_key = o.sport_key
                WHERE r.sport_key = %s
                  AND r.status = 'final'
                  AND o.is_consensus = TRUE
                  AND NOT EXISTS (
                      SELECT 1 FROM multisport_training t 
                      WHERE t.event_id = r.event_id AND t.sport_key = r.sport_key
                  )
                ORDER BY r.event_id, o.ts_recorded DESC
                ON CONFLICT (sport_key, event_id) DO NOTHING
            """, (sport_key,))
            
            synced = cursor.rowcount
            conn.commit()
            
            # Get total training count
            cursor.execute("""
                SELECT COUNT(*) FROM multisport_training 
                WHERE sport_key = %s
            """, (sport_key,))
            total = cursor.fetchone()[0]
            
            cursor.close()
            conn.close()
            
            return {'synced': synced, 'total_training': total}
            
        except Exception as e:
            logger.error(f"Training sync failed: {e}")
            return {'error': str(e)}
    
    def get_collection_status(self) -> Dict:
        """Get current collection status and counts"""
        
        try:
            conn = psycopg2.connect(self.db_url)
            cursor = conn.cursor()
            
            # Count results by sport
            cursor.execute("""
                SELECT sport_key, COUNT(*), 
                       MIN(game_date), MAX(game_date)
                FROM multisport_match_results
                GROUP BY sport_key
            """)
            results_counts = {row[0]: {
                'count': row[1],
                'earliest': row[2].isoformat() if row[2] else None,
                'latest': row[3].isoformat() if row[3] else None
            } for row in cursor.fetchall()}
            
            # Count schedule by sport
            cursor.execute("""
                SELECT sport_key, status, COUNT(*)
                FROM multisport_schedule
                GROUP BY sport_key, status
            """)
            schedule_counts = {}
            for row in cursor.fetchall():
                if row[0] not in schedule_counts:
                    schedule_counts[row[0]] = {}
                schedule_counts[row[0]][row[1]] = row[2]
            
            # Count training data by sport (uses 'outcome' column)
            cursor.execute("""
                SELECT sport_key, COUNT(*), 
                       SUM(CASE WHEN outcome = 'H' THEN 1 ELSE 0 END) as home_wins,
                       SUM(CASE WHEN outcome = 'A' THEN 1 ELSE 0 END) as away_wins
                FROM multisport_training
                GROUP BY sport_key
            """)
            training_counts = {}
            for row in cursor.fetchall():
                total = row[1] or 0
                home_wins = row[2] or 0
                training_counts[row[0]] = {
                    'total': total,
                    'home_wins': home_wins,
                    'away_wins': row[3] or 0,
                    'home_win_rate': round(home_wins / total * 100, 1) if total > 0 else 0
                }
            
            # Count odds snapshots by sport
            cursor.execute("""
                SELECT sport_key, COUNT(*), MIN(ts_recorded), MAX(ts_recorded)
                FROM multisport_odds_snapshots
                GROUP BY sport_key
            """)
            odds_counts = {row[0]: {
                'count': row[1],
                'earliest': row[2].isoformat() if row[2] else None,
                'latest': row[3].isoformat() if row[3] else None
            } for row in cursor.fetchall()}
            
            cursor.close()
            conn.close()
            
            return {
                'match_results': results_counts,
                'schedule': schedule_counts,
                'training_data': training_counts,
                'odds_snapshots': odds_counts,
                'metrics': self.metrics
            }
            
        except Exception as e:
            logger.error(f"Status query failed: {e}")
            return {'error': str(e)}


# Convenience function for scheduler
def run_multisport_collection():
    """Run multi-sport data collection (for scheduler)"""
    try:
        collector = MultiSportDataCollector()
        results = collector.collect_all_sports()
        logger.info(f"✅ Multi-sport data collection complete: {results}")
        return results
    except Exception as e:
        logger.error(f"❌ Multi-sport data collection failed: {e}")
        return {'error': str(e)}
