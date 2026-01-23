"""
Multi-Sport Odds Collector
Collects odds for NBA, NHL, and MLB from The Odds API.

Sports covered:
- basketball_nba: NBA (Oct-Jun)
- icehockey_nhl: NHL (Oct-Jun) 
- baseball_mlb: MLB (Apr-Oct) - Currently off-season

This collector works with The Odds API for odds data.
For team stats/player stats, see api_sports_collector.py
"""

import os
import logging
import requests
import psycopg2
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class MultiSportCollector:
    """
    Collects odds for non-soccer sports from The Odds API.
    """
    
    SPORT_CONFIGS = {
        'basketball_nba': {
            'name': 'NBA',
            'sport': 'basketball',
            'markets': ['h2h', 'spreads', 'totals'],
            'regions': 'us',
            'outcome_type': '2way',
            'active_months': [10, 11, 12, 1, 2, 3, 4, 5, 6],
            'typical_games_per_day': 8
        },
        'basketball_euroleague': {
            'name': 'Euroleague',
            'sport': 'basketball',
            'markets': ['h2h', 'spreads', 'totals'],
            'regions': 'eu',
            'outcome_type': '2way',
            'active_months': [10, 11, 12, 1, 2, 3, 4, 5],
            'typical_games_per_day': 4
        },
        'icehockey_nhl': {
            'name': 'NHL',
            'sport': 'hockey',
            'markets': ['h2h', 'spreads', 'totals'],
            'regions': 'us',
            'outcome_type': '2way',
            'active_months': [10, 11, 12, 1, 2, 3, 4, 5, 6],
            'typical_games_per_day': 10
        },
        'baseball_mlb': {
            'name': 'MLB',
            'sport': 'baseball',
            'markets': ['h2h', 'spreads', 'totals'],
            'regions': 'us',
            'outcome_type': '2way',
            'active_months': [4, 5, 6, 7, 8, 9, 10],
            'typical_games_per_day': 15
        },
        'americanfootball_nfl': {
            'name': 'NFL',
            'sport': 'american-football',
            'markets': ['h2h', 'spreads', 'totals'],
            'regions': 'us',
            'outcome_type': '2way',
            'active_months': [9, 10, 11, 12, 1, 2],  # Sept-Feb (regular + playoffs)
            'typical_games_per_day': 14  # Mainly Sunday games
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
            'events_processed': 0,
            'odds_stored': 0,
            'fixtures_created': 0,
            'errors': 0
        }
    
    def collect_all_active_sports(self) -> Dict:
        """
        Collect odds for all currently active sports.
        Skips sports that are out of season.
        """
        current_month = datetime.now().month
        results = {}
        
        for sport_key, config in self.SPORT_CONFIGS.items():
            if current_month in config['active_months']:
                logger.info(f"📊 Collecting {config['name']}...")
                try:
                    result = self.collect_sport(sport_key)
                    results[sport_key] = result
                except Exception as e:
                    logger.error(f"❌ {config['name']} collection failed: {e}")
                    results[sport_key] = {'error': str(e)}
            else:
                logger.debug(f"⏸️ {config['name']} is off-season (month {current_month})")
                results[sport_key] = {'status': 'off_season'}
        
        return results
    
    def collect_sport(self, sport_key: str) -> Dict:
        """
        Collect odds for a specific sport.
        
        Args:
            sport_key: e.g., 'basketball_nba', 'icehockey_nhl'
        """
        config = self.SPORT_CONFIGS.get(sport_key)
        if not config:
            return {'error': f'Unknown sport: {sport_key}'}
        
        odds_data = self._fetch_odds(sport_key, config)
        
        if not odds_data:
            return {'events': 0, 'odds_stored': 0}
        
        fixtures_created = self._store_fixtures(odds_data, sport_key, config)
        odds_stored = self._store_odds(odds_data, sport_key, config)
        
        return {
            'sport': sport_key,
            'name': config['name'],
            'events': len(odds_data),
            'fixtures_created': fixtures_created,
            'odds_stored': odds_stored
        }
    
    def _fetch_odds(self, sport_key: str, config: Dict) -> List[Dict]:
        """Fetch odds from The Odds API"""
        
        url = f"{self.base_url}/sports/{sport_key}/odds"
        params = {
            'apiKey': self.api_key,
            'regions': config['regions'],
            'markets': ','.join(config['markets']),
            'oddsFormat': 'decimal'
        }
        
        try:
            response = requests.get(url, params=params, timeout=30)
            self.metrics['api_calls'] += 1
            
            if response.status_code == 404:
                logger.debug(f"No events for {sport_key}")
                return []
            
            response.raise_for_status()
            data = response.json()
            logger.info(f"  📥 Fetched {len(data)} events for {sport_key}")
            return data
            
        except requests.RequestException as e:
            logger.error(f"API request failed for {sport_key}: {e}")
            self.metrics['errors'] += 1
            return []
    
    def _store_fixtures(self, events: List[Dict], sport_key: str, config: Dict) -> int:
        """Store/update fixtures in multisport_fixtures table"""
        
        if not events:
            return 0
        
        created_count = 0
        
        try:
            conn = psycopg2.connect(self.db_url)
            cursor = conn.cursor()
            
            for event in events:
                event_id = event.get('id')
                home_team = event.get('home_team')
                away_team = event.get('away_team')
                commence_time = event.get('commence_time')
                
                if not all([event_id, home_team, away_team, commence_time]):
                    continue
                
                try:
                    commence_dt = datetime.fromisoformat(commence_time.replace('Z', '+00:00'))
                except:
                    continue
                
                cursor.execute("""
                    INSERT INTO multisport_fixtures (
                        sport, sport_key, event_id,
                        home_team, away_team, commence_time,
                        status, updated_at
                    ) VALUES (
                        %s, %s, %s,
                        %s, %s, %s,
                        'scheduled', NOW()
                    )
                    ON CONFLICT (sport, event_id) 
                    DO UPDATE SET
                        home_team = EXCLUDED.home_team,
                        away_team = EXCLUDED.away_team,
                        commence_time = EXCLUDED.commence_time,
                        updated_at = NOW()
                    RETURNING (xmax = 0) as inserted
                """, (
                    config['sport'], sport_key, event_id,
                    home_team, away_team, commence_dt
                ))
                
                row = cursor.fetchone()
                if row and row[0]:
                    created_count += 1
            
            conn.commit()
            cursor.close()
            conn.close()
            
            self.metrics['fixtures_created'] += created_count
            
        except Exception as e:
            logger.error(f"Database error storing fixtures: {e}")
        
        return created_count
    
    def _store_odds(self, events: List[Dict], sport_key: str, config: Dict) -> int:
        """Store odds snapshots in multisport_odds_snapshots table"""
        
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
                
                try:
                    commence_dt = datetime.fromisoformat(commence_time.replace('Z', '+00:00'))
                except:
                    commence_dt = None
                
                consensus = self._calculate_consensus(event, home_team, away_team)
                
                if consensus:
                    try:
                        cursor.execute("""
                            INSERT INTO multisport_odds_snapshots (
                                sport, sport_key, event_id,
                                home_team, away_team, commence_time,
                                home_odds, away_odds, draw_odds,
                                home_prob, away_prob, draw_prob,
                                home_spread, home_spread_odds, away_spread_odds,
                                total_line, over_odds, under_odds,
                                overround, n_bookmakers,
                                bookmaker, is_consensus, ts_recorded
                            ) VALUES (
                                %s, %s, %s,
                                %s, %s, %s,
                                %s, %s, %s,
                                %s, %s, %s,
                                %s, %s, %s,
                                %s, %s, %s,
                                %s, %s,
                                %s, %s, %s
                            )
                            ON CONFLICT (event_id, bookmaker, ts_recorded)
                            DO NOTHING
                        """, (
                            config['sport'], sport_key, event_id,
                            home_team, away_team, commence_dt,
                            consensus.get('home_odds'), consensus.get('away_odds'), None,
                            consensus.get('home_prob'), consensus.get('away_prob'), None,
                            consensus.get('spread'), consensus.get('spread_home_odds'), consensus.get('spread_away_odds'),
                            consensus.get('total'), consensus.get('over_odds'), consensus.get('under_odds'),
                            consensus.get('overround'), consensus.get('n_bookmakers'),
                            'consensus', True, now
                        ))
                        stored_count += 1
                    except Exception as e:
                        logger.debug(f"Insert error: {e}")
                
                for bookmaker in event.get('bookmakers', []):
                    bm_key = bookmaker.get('key')
                    bm_data = self._parse_bookmaker_odds(bookmaker, home_team, away_team)
                    
                    if bm_data:
                        try:
                            cursor.execute("""
                                INSERT INTO multisport_odds_snapshots (
                                    sport, sport_key, event_id,
                                    home_team, away_team, commence_time,
                                    home_odds, away_odds, draw_odds,
                                    home_prob, away_prob, draw_prob,
                                    home_spread, home_spread_odds, away_spread_odds,
                                    total_line, over_odds, under_odds,
                                    overround, n_bookmakers,
                                    bookmaker, is_consensus, ts_recorded
                                ) VALUES (
                                    %s, %s, %s,
                                    %s, %s, %s,
                                    %s, %s, %s,
                                    %s, %s, %s,
                                    %s, %s, %s,
                                    %s, %s, %s,
                                    %s, %s,
                                    %s, %s, %s
                                )
                                ON CONFLICT (event_id, bookmaker, ts_recorded)
                                DO NOTHING
                            """, (
                                config['sport'], sport_key, event_id,
                                home_team, away_team, commence_dt,
                                bm_data.get('home_odds'), bm_data.get('away_odds'), None,
                                bm_data.get('home_prob'), bm_data.get('away_prob'), None,
                                bm_data.get('spread'), bm_data.get('spread_home_odds'), bm_data.get('spread_away_odds'),
                                bm_data.get('total'), bm_data.get('over_odds'), bm_data.get('under_odds'),
                                bm_data.get('overround'), 1,
                                bm_key, False, now
                            ))
                            stored_count += 1
                        except Exception as e:
                            logger.debug(f"Insert error for {bm_key}: {e}")
            
            conn.commit()
            cursor.close()
            conn.close()
            
            self.metrics['odds_stored'] += stored_count
            
        except Exception as e:
            logger.error(f"Database error storing odds: {e}")
        
        return stored_count
    
    def _calculate_consensus(self, event: Dict, home_team: str, away_team: str) -> Optional[Dict]:
        """Calculate consensus odds from all bookmakers"""
        
        bookmakers = event.get('bookmakers', [])
        if not bookmakers:
            return None
        
        home_odds_list = []
        away_odds_list = []
        spreads = []
        totals = []
        
        for bm in bookmakers:
            for market in bm.get('markets', []):
                market_key = market.get('key')
                outcomes = {o['name']: o for o in market.get('outcomes', [])}
                
                if market_key == 'h2h':
                    if home_team in outcomes:
                        home_odds_list.append(outcomes[home_team]['price'])
                    if away_team in outcomes:
                        away_odds_list.append(outcomes[away_team]['price'])
                
                elif market_key == 'spreads':
                    if home_team in outcomes:
                        spreads.append({
                            'spread': outcomes[home_team].get('point'),
                            'home_odds': outcomes[home_team]['price'],
                            'away_odds': outcomes[away_team]['price'] if away_team in outcomes else None
                        })
                
                elif market_key == 'totals':
                    if 'Over' in outcomes:
                        totals.append({
                            'total': outcomes['Over'].get('point'),
                            'over_odds': outcomes['Over']['price'],
                            'under_odds': outcomes['Under']['price'] if 'Under' in outcomes else None
                        })
        
        if not home_odds_list or not away_odds_list:
            return None
        
        avg_home = sum(home_odds_list) / len(home_odds_list)
        avg_away = sum(away_odds_list) / len(away_odds_list)
        
        home_prob = 1 / avg_home
        away_prob = 1 / avg_away
        overround = home_prob + away_prob
        
        home_prob_norm = home_prob / overround
        away_prob_norm = away_prob / overround
        
        result = {
            'home_odds': round(avg_home, 3),
            'away_odds': round(avg_away, 3),
            'home_prob': round(home_prob_norm, 4),
            'away_prob': round(away_prob_norm, 4),
            'overround': round(overround, 4),
            'n_bookmakers': len(bookmakers)
        }
        
        if spreads:
            latest_spread = spreads[-1]
            result['spread'] = latest_spread['spread']
            result['spread_home_odds'] = latest_spread['home_odds']
            result['spread_away_odds'] = latest_spread['away_odds']
        
        if totals:
            latest_total = totals[-1]
            result['total'] = latest_total['total']
            result['over_odds'] = latest_total['over_odds']
            result['under_odds'] = latest_total['under_odds']
        
        return result
    
    def _parse_bookmaker_odds(self, bookmaker: Dict, home_team: str, away_team: str) -> Optional[Dict]:
        """Parse odds from a single bookmaker"""
        
        result = {}
        
        for market in bookmaker.get('markets', []):
            market_key = market.get('key')
            outcomes = {o['name']: o for o in market.get('outcomes', [])}
            
            if market_key == 'h2h':
                if home_team in outcomes and away_team in outcomes:
                    home_odds = outcomes[home_team]['price']
                    away_odds = outcomes[away_team]['price']
                    
                    home_prob = 1 / home_odds
                    away_prob = 1 / away_odds
                    overround = home_prob + away_prob
                    
                    result['home_odds'] = home_odds
                    result['away_odds'] = away_odds
                    result['home_prob'] = round(home_prob / overround, 4)
                    result['away_prob'] = round(away_prob / overround, 4)
                    result['overround'] = round(overround, 4)
            
            elif market_key == 'spreads':
                if home_team in outcomes:
                    result['spread'] = outcomes[home_team].get('point')
                    result['spread_home_odds'] = outcomes[home_team]['price']
                    if away_team in outcomes:
                        result['spread_away_odds'] = outcomes[away_team]['price']
            
            elif market_key == 'totals':
                if 'Over' in outcomes:
                    result['total'] = outcomes['Over'].get('point')
                    result['over_odds'] = outcomes['Over']['price']
                    if 'Under' in outcomes:
                        result['under_odds'] = outcomes['Under']['price']
        
        return result if 'home_odds' in result else None
    
    def collect_results(self) -> Dict:
        """
        Collect results for completed games using The Odds API scores endpoint.
        """
        results = {}
        current_month = datetime.now().month
        
        for sport_key, config in self.SPORT_CONFIGS.items():
            if current_month in config['active_months']:
                try:
                    result = self._fetch_and_store_results(sport_key, config)
                    results[sport_key] = result
                except Exception as e:
                    logger.error(f"Results collection failed for {sport_key}: {e}")
                    results[sport_key] = {'error': str(e)}
        
        return results
    
    def _fetch_and_store_results(self, sport_key: str, config: Dict) -> Dict:
        """Fetch scores and update fixtures with results"""
        
        url = f"{self.base_url}/sports/{sport_key}/scores"
        params = {
            'apiKey': self.api_key,
            'daysFrom': 3
        }
        
        try:
            response = requests.get(url, params=params, timeout=30)
            self.metrics['api_calls'] += 1
            
            if response.status_code != 200:
                return {'error': f'API returned {response.status_code}'}
            
            scores = response.json()
            updated = 0
            
            conn = psycopg2.connect(self.db_url)
            cursor = conn.cursor()
            
            for game in scores:
                if not game.get('completed'):
                    continue
                
                event_id = game.get('id')
                home_team = game.get('home_team')
                away_team = game.get('away_team')
                
                home_score = None
                away_score = None
                
                for score_entry in game.get('scores', []):
                    if score_entry.get('name') == home_team:
                        home_score = int(score_entry.get('score', 0))
                    elif score_entry.get('name') == away_team:
                        away_score = int(score_entry.get('score', 0))
                
                if home_score is not None and away_score is not None:
                    outcome = 'H' if home_score > away_score else 'A'
                    
                    cursor.execute("""
                        UPDATE multisport_fixtures
                        SET status = 'finished',
                            home_score = %s,
                            away_score = %s,
                            outcome = %s,
                            updated_at = NOW()
                        WHERE sport = %s AND event_id = %s
                          AND status != 'finished'
                    """, (home_score, away_score, outcome, config['sport'], event_id))
                    
                    if cursor.rowcount > 0:
                        updated += 1
            
            conn.commit()
            cursor.close()
            conn.close()
            
            return {'scores_fetched': len(scores), 'results_updated': updated}
            
        except Exception as e:
            logger.error(f"Error fetching results for {sport_key}: {e}")
            return {'error': str(e)}


_collector_instance = None

def get_multisport_collector() -> MultiSportCollector:
    """Get singleton instance of MultiSportCollector"""
    global _collector_instance
    if _collector_instance is None:
        _collector_instance = MultiSportCollector()
    return _collector_instance


def run_multisport_collection():
    """Entry point for scheduler - collect odds for all active sports"""
    collector = get_multisport_collector()
    
    logger.info("🏀🏒⚾ Multi-Sport Collector: Starting collection...")
    results = collector.collect_all_active_sports()
    
    total_events = sum(r.get('events', 0) for r in results.values() if isinstance(r, dict))
    total_odds = sum(r.get('odds_stored', 0) for r in results.values() if isinstance(r, dict))
    
    logger.info(f"🏀🏒⚾ Multi-Sport Collection Complete: {total_events} events, {total_odds} odds stored")
    
    return results


def run_multisport_results():
    """Entry point for scheduler - collect results for completed games"""
    collector = get_multisport_collector()
    
    logger.info("📊 Multi-Sport Results: Fetching scores...")
    results = collector.collect_results()
    
    total_updated = sum(r.get('results_updated', 0) for r in results.values() if isinstance(r, dict))
    logger.info(f"📊 Multi-Sport Results Complete: {total_updated} results updated")
    
    return results
