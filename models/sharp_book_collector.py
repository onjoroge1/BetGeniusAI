"""
Sharp Book Collector - V3 Feature Intelligence
Tracks Pinnacle and other sharp bookmaker odds separately for edge detection.

V3 Features derived:
1. sharp_prob_home/draw/away - Sharp market view (Pinnacle implied probs)
2. soft_vs_sharp_divergence  - Edge detection (Pinnacle vs soft book avg)
3. sharp_line_movement       - Smart money direction tracking
4. sharp_overround           - Market efficiency indicator

Sharp books: Lower margins, welcome winning bettors, prices move on information
Soft books: Higher margins, limit winners, prices move on liability
"""

import os
import logging
import requests
import psycopg2
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class SharpBookCollector:
    """
    Collects odds from sharp bookmakers (Pinnacle, Betfair) separately
    for V3 feature engineering.
    """
    
    SHARP_BOOKS = ['pinnacle', 'betfair_ex_uk', 'matchbook', 'betfair']
    SOFT_BOOKS = ['draftkings', 'fanduel', 'betmgm', 'caesars', 'pointsbetus', 'bovada']
    
    SPORT_CONFIGS = {
        'soccer': {
            'sport_keys': [
                'soccer_epl', 'soccer_spain_la_liga', 'soccer_germany_bundesliga',
                'soccer_italy_serie_a', 'soccer_france_ligue_one', 'soccer_netherlands_eredivisie',
                'soccer_portugal_primeira_liga', 'soccer_efl_champ'
            ],
            'has_draw': True,
            'regions': 'eu,uk,us'
        },
        'basketball': {
            'sport_keys': ['basketball_nba', 'basketball_euroleague'],
            'has_draw': False,
            'regions': 'us,eu'
        },
        'hockey': {
            'sport_keys': ['icehockey_nhl'],
            'has_draw': False,
            'regions': 'us,eu'
        }
    }
    
    def __init__(self):
        self.api_key = os.getenv('ODDS_API_KEY')
        self.db_url = os.getenv('DATABASE_URL')
        self.base_url = "https://api.the-odds-api.com/v4"
        
        if not self.api_key:
            raise ValueError("ODDS_API_KEY not set")
        
        self.metrics = {
            'api_calls': 0,
            'matches_processed': 0,
            'sharp_odds_stored': 0,
            'errors': 0
        }
    
    def collect_sharp_odds(self, sport: str = 'soccer') -> Dict:
        """
        Collect odds from sharp bookmakers for specified sport.
        
        Args:
            sport: 'soccer', 'basketball', or 'hockey'
        
        Returns:
            Dict with collection metrics
        """
        logger.info(f"🎯 Sharp Book Collector: Starting {sport} collection...")
        
        config = self.SPORT_CONFIGS.get(sport)
        if not config:
            logger.error(f"Unknown sport: {sport}")
            return {'error': f'Unknown sport: {sport}'}
        
        total_stored = 0
        
        for sport_key in config['sport_keys']:
            try:
                odds_data = self._fetch_odds(sport_key, config['regions'])
                if odds_data:
                    stored = self._store_sharp_odds(odds_data, sport, config['has_draw'])
                    total_stored += stored
                    logger.info(f"  ✅ {sport_key}: {stored} sharp odds stored")
            except Exception as e:
                logger.error(f"  ❌ {sport_key}: {e}")
                self.metrics['errors'] += 1
        
        self.metrics['sharp_odds_stored'] += total_stored
        
        return {
            'sport': sport,
            'odds_stored': total_stored,
            'api_calls': self.metrics['api_calls'],
            'errors': self.metrics['errors']
        }
    
    def _fetch_odds(self, sport_key: str, regions: str) -> List[Dict]:
        """Fetch odds from The Odds API with sharp bookmaker filter"""
        
        bookmakers_param = ','.join(self.SHARP_BOOKS)
        
        url = f"{self.base_url}/sports/{sport_key}/odds"
        params = {
            'apiKey': self.api_key,
            'regions': regions,
            'markets': 'h2h',
            'oddsFormat': 'decimal',
            'bookmakers': bookmakers_param
        }
        
        try:
            response = requests.get(url, params=params, timeout=30)
            self.metrics['api_calls'] += 1
            
            if response.status_code == 404:
                logger.debug(f"No events for {sport_key}")
                return []
            
            response.raise_for_status()
            return response.json()
            
        except requests.RequestException as e:
            logger.error(f"API request failed for {sport_key}: {e}")
            return []
    
    def _store_sharp_odds(self, events: List[Dict], sport: str, has_draw: bool) -> int:
        """Store sharp bookmaker odds in database"""
        
        if not events:
            return 0
        
        stored_count = 0
        now = datetime.now(timezone.utc)
        
        try:
            conn = psycopg2.connect(self.db_url)
            cursor = conn.cursor()
            
            for event in events:
                event_id = event.get('id')
                home_team = event.get('home_team')
                away_team = event.get('away_team')
                commence_time = event.get('commence_time')
                
                if not all([event_id, home_team, away_team]):
                    continue
                
                commence_dt = None
                hours_before = None
                if commence_time:
                    try:
                        commence_dt = datetime.fromisoformat(commence_time.replace('Z', '+00:00'))
                        hours_before = (commence_dt - now).total_seconds() / 3600
                    except:
                        pass
                
                match_id = self._get_match_id(cursor, home_team, away_team, commence_dt, sport)
                
                for bookmaker in event.get('bookmakers', []):
                    bm_key = bookmaker.get('key')
                    
                    if bm_key not in self.SHARP_BOOKS:
                        continue
                    
                    for market in bookmaker.get('markets', []):
                        if market.get('key') != 'h2h':
                            continue
                        
                        outcomes = {o['name']: o['price'] for o in market.get('outcomes', [])}
                        
                        odds_home = outcomes.get(home_team)
                        odds_away = outcomes.get(away_team)
                        odds_draw = outcomes.get('Draw') if has_draw else None
                        
                        if not odds_home or not odds_away:
                            continue
                        
                        prob_home, prob_draw, prob_away, overround = self._calculate_probs(
                            odds_home, odds_draw, odds_away, has_draw
                        )
                        
                        try:
                            cursor.execute("""
                                INSERT INTO sharp_book_odds (
                                    event_id, match_id, sport, bookmaker, is_sharp,
                                    home_team, away_team,
                                    odds_home, odds_draw, odds_away,
                                    prob_home, prob_draw, prob_away,
                                    overround, margin,
                                    ts_recorded, ts_kickoff, hours_before_kickoff
                                ) VALUES (
                                    %s, %s, %s, %s, true,
                                    %s, %s,
                                    %s, %s, %s,
                                    %s, %s, %s,
                                    %s, %s,
                                    %s, %s, %s
                                )
                                ON CONFLICT (event_id, bookmaker, ts_recorded) 
                                DO UPDATE SET
                                    odds_home = EXCLUDED.odds_home,
                                    odds_draw = EXCLUDED.odds_draw,
                                    odds_away = EXCLUDED.odds_away,
                                    prob_home = EXCLUDED.prob_home,
                                    prob_draw = EXCLUDED.prob_draw,
                                    prob_away = EXCLUDED.prob_away,
                                    overround = EXCLUDED.overround
                            """, (
                                event_id, match_id, sport, bm_key,
                                home_team, away_team,
                                odds_home, odds_draw, odds_away,
                                prob_home, prob_draw, prob_away,
                                overround, overround - 1.0 if overround else None,
                                now, commence_dt, hours_before
                            ))
                            stored_count += 1
                        except Exception as e:
                            logger.warning(f"Insert error for {event_id}/{bm_key}: {e}")
            
            conn.commit()
            cursor.close()
            conn.close()
            
        except Exception as e:
            logger.error(f"Database error storing sharp odds: {e}")
        
        return stored_count
    
    def _get_match_id(self, cursor, home_team: str, away_team: str, 
                      commence_time: Optional[datetime], sport: str) -> Optional[int]:
        """Try to find existing match_id from fixtures table"""
        
        if sport == 'soccer':
            try:
                cursor.execute("""
                    SELECT match_id FROM fixtures 
                    WHERE LOWER(home_team) LIKE %s 
                      AND LOWER(away_team) LIKE %s
                      AND kickoff_at BETWEEN %s AND %s
                    LIMIT 1
                """, (
                    f"%{home_team.lower()[:10]}%",
                    f"%{away_team.lower()[:10]}%",
                    commence_time - timedelta(hours=2) if commence_time else datetime.now() - timedelta(days=1),
                    commence_time + timedelta(hours=2) if commence_time else datetime.now() + timedelta(days=7)
                ))
                row = cursor.fetchone()
                if row:
                    return row[0]
            except:
                pass
        
        return None
    
    def _calculate_probs(self, odds_h: float, odds_d: Optional[float], 
                         odds_a: float, has_draw: bool) -> Tuple[float, float, float, float]:
        """Calculate implied probabilities from decimal odds"""
        
        prob_h = 1 / odds_h if odds_h else 0
        prob_a = 1 / odds_a if odds_a else 0
        prob_d = 1 / odds_d if odds_d and has_draw else 0
        
        overround = prob_h + prob_d + prob_a
        
        if overround > 0:
            prob_h = prob_h / overround
            prob_d = prob_d / overround if has_draw else 0
            prob_a = prob_a / overround
        
        return prob_h, prob_d, prob_a, overround
    
    def get_sharp_soft_divergence(self, match_id: int) -> Dict:
        """
        Calculate divergence between sharp and soft book odds for a match.
        
        Returns:
            Dict with divergence metrics for V3 features
        """
        try:
            conn = psycopg2.connect(self.db_url)
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT 
                    AVG(prob_home) FILTER (WHERE bookmaker IN ('pinnacle', 'betfair_ex_uk')) as sharp_home,
                    AVG(prob_draw) FILTER (WHERE bookmaker IN ('pinnacle', 'betfair_ex_uk')) as sharp_draw,
                    AVG(prob_away) FILTER (WHERE bookmaker IN ('pinnacle', 'betfair_ex_uk')) as sharp_away,
                    AVG(overround) FILTER (WHERE bookmaker = 'pinnacle') as pinnacle_overround
                FROM sharp_book_odds
                WHERE match_id = %s
                  AND ts_recorded = (
                      SELECT MAX(ts_recorded) FROM sharp_book_odds WHERE match_id = %s
                  )
            """, (match_id, match_id))
            
            row = cursor.fetchone()
            cursor.close()
            conn.close()
            
            if row and row[0]:
                return {
                    'sharp_prob_home': float(row[0]) if row[0] else None,
                    'sharp_prob_draw': float(row[1]) if row[1] else None,
                    'sharp_prob_away': float(row[2]) if row[2] else None,
                    'pinnacle_overround': float(row[3]) if row[3] else None
                }
            
            return {}
            
        except Exception as e:
            logger.error(f"Error getting sharp/soft divergence: {e}")
            return {}


from datetime import timedelta

_collector_instance = None

def get_sharp_book_collector() -> SharpBookCollector:
    """Get singleton instance of SharpBookCollector"""
    global _collector_instance
    if _collector_instance is None:
        _collector_instance = SharpBookCollector()
    return _collector_instance


def run_sharp_book_collection():
    """Entry point for scheduler - collect sharp odds for all sports"""
    collector = get_sharp_book_collector()
    results = {}
    
    for sport in ['soccer', 'basketball', 'hockey']:
        try:
            result = collector.collect_sharp_odds(sport)
            results[sport] = result
        except Exception as e:
            logger.error(f"Sharp book collection failed for {sport}: {e}")
            results[sport] = {'error': str(e)}
    
    total_stored = sum(r.get('odds_stored', 0) for r in results.values())
    logger.info(f"🎯 Sharp Book Collection Complete: {total_stored} total odds stored")
    
    return results
