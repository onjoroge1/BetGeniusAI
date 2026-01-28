"""
Player Prop Odds Collector

Collects player prop odds from The Odds API for US sports (NBA, NFL, NHL, MLB).
Note: Soccer player props are NOT available from The Odds API.

For soccer, we use synthetic market odds based on model predictions with margin adjustment.
"""

import os
import logging
import requests
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger(__name__)


class PlayerPropOddsCollector:
    """
    Collects player prop odds from The Odds API.
    
    Supported Sports & Markets:
    - NBA: player_points, player_rebounds, player_assists, player_threes
    - NFL: player_pass_tds, player_pass_yds, player_rush_yds, player_receptions
    - NHL: player_points (goals + assists)
    - MLB: batter_hits, batter_home_runs, pitcher_strikeouts
    
    Note: Soccer player scorer props are NOT available.
    """
    
    BASE_URL = "https://api.the-odds-api.com/v4"
    
    SPORT_MARKETS = {
        'basketball_nba': [
            'player_points', 'player_rebounds', 'player_assists', 
            'player_threes', 'player_blocks_steals'
        ],
        'americanfootball_nfl': [
            'player_pass_tds', 'player_pass_yds', 'player_rush_yds', 
            'player_receptions', 'player_reception_yds'
        ],
        'icehockey_nhl': [
            'player_points', 'player_goals', 'player_assists'
        ],
        'baseball_mlb': [
            'batter_hits', 'batter_home_runs', 'pitcher_strikeouts'
        ]
    }
    
    def __init__(self):
        self.api_key = os.getenv('ODDS_API_KEY')
        self.db_url = os.getenv('DATABASE_URL')
        
        if not self.api_key:
            raise ValueError("ODDS_API_KEY not set")
        
        self.engine = create_engine(self.db_url, pool_pre_ping=True)
        self._ensure_tables()
        
        self.metrics = {
            'api_calls': 0,
            'events_processed': 0,
            'props_collected': 0,
            'errors': 0
        }
    
    def _ensure_tables(self):
        """Create player_prop_odds table if not exists."""
        with self.engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS player_prop_odds (
                    id SERIAL PRIMARY KEY,
                    sport_key VARCHAR(50) NOT NULL,
                    event_id VARCHAR(100) NOT NULL,
                    player_name VARCHAR(200) NOT NULL,
                    market_key VARCHAR(100) NOT NULL,
                    bookmaker VARCHAR(50) NOT NULL,
                    line NUMERIC(6,2),
                    over_price INTEGER,
                    under_price INTEGER,
                    over_decimal NUMERIC(6,3),
                    under_decimal NUMERIC(6,3),
                    commence_time TIMESTAMPTZ,
                    collected_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(sport_key, event_id, player_name, market_key, bookmaker, line)
                )
            """))
            
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_player_prop_odds_player 
                ON player_prop_odds(player_name, market_key)
            """))
            
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_player_prop_odds_event 
                ON player_prop_odds(event_id, collected_at DESC)
            """))
            
            conn.commit()
            logger.info("PlayerPropOddsCollector: Tables initialized")
    
    def _make_request(self, endpoint: str, params: Dict = None) -> Optional[Dict]:
        """Make API request with rate limiting."""
        url = f"{self.BASE_URL}{endpoint}"
        params = params or {}
        params['apiKey'] = self.api_key
        
        try:
            response = requests.get(url, params=params, timeout=30)
            self.metrics['api_calls'] += 1
            
            remaining = response.headers.get('x-requests-remaining', 'N/A')
            logger.debug(f"API call - remaining quota: {remaining}")
            
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 429:
                logger.warning("Rate limited - backing off")
                return None
            else:
                logger.error(f"API error {response.status_code}: {response.text[:200]}")
                self.metrics['errors'] += 1
                return None
                
        except Exception as e:
            logger.error(f"Request failed: {e}")
            self.metrics['errors'] += 1
            return None
    
    def get_upcoming_events(self, sport_key: str, hours_ahead: int = 24) -> List[Dict]:
        """Get upcoming events for a sport."""
        data = self._make_request(
            f"/sports/{sport_key}/odds",
            params={'regions': 'us', 'markets': 'h2h', 'oddsFormat': 'decimal'}
        )
        
        if not data:
            return []
        
        cutoff = datetime.now(timezone.utc) + timedelta(hours=hours_ahead)
        events = []
        
        for event in data:
            commence = datetime.fromisoformat(event['commence_time'].replace('Z', '+00:00'))
            if commence <= cutoff:
                events.append({
                    'id': event['id'],
                    'home_team': event.get('home_team'),
                    'away_team': event.get('away_team'),
                    'commence_time': commence
                })
        
        return events
    
    def collect_player_props_for_event(
        self, 
        sport_key: str, 
        event_id: str,
        markets: List[str] = None
    ) -> Dict:
        """Collect player prop odds for a specific event."""
        markets = markets or self.SPORT_MARKETS.get(sport_key, [])
        
        if not markets:
            return {'error': f'No markets configured for {sport_key}'}
        
        data = self._make_request(
            f"/sports/{sport_key}/events/{event_id}/odds",
            params={
                'regions': 'us',
                'markets': ','.join(markets),
                'oddsFormat': 'american'
            }
        )
        
        if not data:
            return {'error': 'API request failed', 'props_collected': 0}
        
        props_collected = 0
        commence_time = data.get('commence_time')
        
        with self.engine.connect() as conn:
            for bookmaker in data.get('bookmakers', []):
                bookie_key = bookmaker['key']
                
                for market in bookmaker.get('markets', []):
                    market_key = market['key']
                    
                    outcomes = market.get('outcomes', [])
                    i = 0
                    while i < len(outcomes):
                        outcome = outcomes[i]
                        player_name = outcome.get('description', '')
                        line = outcome.get('point')
                        
                        if outcome.get('name') == 'Over':
                            over_price = outcome.get('price')
                            under_price = None
                            
                            if i + 1 < len(outcomes) and outcomes[i + 1].get('description') == player_name:
                                under_price = outcomes[i + 1].get('price')
                                i += 1
                            
                            over_decimal = self._american_to_decimal(over_price)
                            under_decimal = self._american_to_decimal(under_price) if under_price else None
                            
                            try:
                                conn.execute(text("""
                                    INSERT INTO player_prop_odds 
                                    (sport_key, event_id, player_name, market_key, bookmaker, 
                                     line, over_price, under_price, over_decimal, under_decimal, commence_time)
                                    VALUES (:sport_key, :event_id, :player_name, :market_key, :bookmaker,
                                            :line, :over_price, :under_price, :over_decimal, :under_decimal, :commence_time)
                                    ON CONFLICT (sport_key, event_id, player_name, market_key, bookmaker, line)
                                    DO UPDATE SET 
                                        over_price = EXCLUDED.over_price,
                                        under_price = EXCLUDED.under_price,
                                        over_decimal = EXCLUDED.over_decimal,
                                        under_decimal = EXCLUDED.under_decimal,
                                        collected_at = NOW()
                                """), {
                                    'sport_key': sport_key,
                                    'event_id': event_id,
                                    'player_name': player_name,
                                    'market_key': market_key,
                                    'bookmaker': bookie_key,
                                    'line': line,
                                    'over_price': over_price,
                                    'under_price': under_price,
                                    'over_decimal': over_decimal,
                                    'under_decimal': under_decimal,
                                    'commence_time': commence_time
                                })
                                props_collected += 1
                            except Exception as e:
                                logger.debug(f"Insert error: {e}")
                        
                        i += 1
            
            conn.commit()
        
        self.metrics['props_collected'] += props_collected
        self.metrics['events_processed'] += 1
        
        return {
            'event_id': event_id,
            'sport_key': sport_key,
            'props_collected': props_collected
        }
    
    def _american_to_decimal(self, american_odds: int) -> float:
        """Convert American odds to decimal."""
        if american_odds is None:
            return None
        if american_odds > 0:
            return 1 + (american_odds / 100)
        else:
            return 1 + (100 / abs(american_odds))
    
    def collect_all_props(self, sport_key: str, hours_ahead: int = 24) -> Dict:
        """Collect player props for all upcoming events in a sport."""
        events = self.get_upcoming_events(sport_key, hours_ahead)
        
        total_props = 0
        events_processed = 0
        
        for event in events:
            result = self.collect_player_props_for_event(sport_key, event['id'])
            if 'error' not in result:
                total_props += result.get('props_collected', 0)
                events_processed += 1
        
        logger.info(f"Collected {total_props} props from {events_processed} {sport_key} events")
        
        return {
            'sport_key': sport_key,
            'events_processed': events_processed,
            'props_collected': total_props,
            'metrics': self.metrics
        }
    
    def get_player_prop_odds(
        self, 
        player_name: str, 
        market_key: str = 'player_points',
        sport_key: str = None
    ) -> Optional[Dict]:
        """Get latest prop odds for a player."""
        with self.engine.connect() as conn:
            query = """
                SELECT 
                    player_name,
                    market_key,
                    AVG(line) as avg_line,
                    AVG(over_decimal) as avg_over_odds,
                    AVG(under_decimal) as avg_under_odds,
                    1.0 / AVG(over_decimal) as implied_over_prob,
                    COUNT(DISTINCT bookmaker) as bookmaker_count,
                    MAX(collected_at) as last_update
                FROM player_prop_odds
                WHERE player_name ILIKE :player_name
                AND market_key = :market_key
                AND collected_at > NOW() - INTERVAL '6 hours'
            """
            params = {'player_name': f'%{player_name}%', 'market_key': market_key}
            
            if sport_key:
                query += " AND sport_key = :sport_key"
                params['sport_key'] = sport_key
            
            query += " GROUP BY player_name, market_key"
            
            result = conn.execute(text(query), params).fetchone()
            
            if result:
                return {
                    'player_name': result.player_name,
                    'market_key': result.market_key,
                    'avg_line': float(result.avg_line) if result.avg_line else None,
                    'avg_over_odds': float(result.avg_over_odds) if result.avg_over_odds else None,
                    'implied_over_prob': float(result.implied_over_prob) if result.implied_over_prob else None,
                    'bookmaker_count': result.bookmaker_count,
                    'last_update': result.last_update.isoformat() if result.last_update else None
                }
        
        return None


def collect_player_props_job() -> Dict:
    """Scheduled job to collect player props for US sports."""
    try:
        collector = PlayerPropOddsCollector()
        
        results = {}
        for sport_key in ['basketball_nba', 'icehockey_nhl']:
            try:
                result = collector.collect_all_props(sport_key, hours_ahead=48)
                results[sport_key] = result
            except Exception as e:
                logger.error(f"Failed to collect {sport_key} props: {e}")
                results[sport_key] = {'error': str(e)}
        
        return {
            'success': True,
            'results': results,
            'metrics': collector.metrics
        }
        
    except Exception as e:
        logger.error(f"Player props collection job failed: {e}")
        return {'success': False, 'error': str(e)}
