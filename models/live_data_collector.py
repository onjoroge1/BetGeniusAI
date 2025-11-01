"""
Live Match Data Collector
Fetches real-time scores, statistics, and events from API-Football
"""

import os
import requests
import psycopg2
from psycopg2.extras import execute_values
from datetime import datetime, timedelta
import logging
from typing import Dict, List, Optional, Tuple
import json

logger = logging.getLogger(__name__)


class LiveDataCollector:
    """Collects live match data from API-Football"""
    
    def __init__(self):
        self.api_key = os.environ.get('RAPIDAPI_KEY')
        self.base_url = "https://api-football-v1.p.rapidapi.com/v3"
        self.headers = {
            "X-RapidAPI-Key": self.api_key,
            "X-RapidAPI-Host": "api-football-v1.p.rapidapi.com"
        }
        self.db_url = os.environ.get('DATABASE_URL')
    
    def get_live_matches(self) -> List[int]:
        """
        Get list of currently live match IDs from our database
        Returns API-Football fixture IDs for matches that should be live
        """
        with psycopg2.connect(self.db_url) as conn:
            cursor = conn.cursor()
            
            # Get matches that kicked off in last 2 hours and aren't finished
            # Join with matches table to get API-Football fixture IDs
            cursor.execute("""
                SELECT DISTINCT 
                    f.match_id,
                    m.api_football_fixture_id
                FROM fixtures f
                LEFT JOIN matches m ON f.match_id = m.match_id
                WHERE f.kickoff_at <= NOW()
                    AND f.kickoff_at > NOW() - INTERVAL '2 hours'
                    AND f.status = 'scheduled'
                    AND m.api_football_fixture_id IS NOT NULL
                ORDER BY f.kickoff_at DESC
            """)
            
            matches = cursor.fetchall()
            logger.info(f"Found {len(matches)} potentially live matches")
            
            return [(row[0], row[1]) for row in matches]  # (our_match_id, api_football_id)
    
    def fetch_live_fixture(self, api_football_id: int) -> Optional[Dict]:
        """Fetch live fixture data from API-Football"""
        try:
            url = f"{self.base_url}/fixtures"
            params = {"id": api_football_id}
            
            response = requests.get(url, headers=self.headers, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            if data.get('response') and len(data['response']) > 0:
                return data['response'][0]
            
            return None
            
        except Exception as e:
            logger.error(f"Error fetching fixture {api_football_id}: {e}")
            return None
    
    def parse_live_statistics(self, fixture_data: Dict) -> Tuple[Dict, List]:
        """
        Parse live statistics and events from API-Football fixture data
        Returns: (statistics_dict, events_list)
        """
        statistics = {}
        events = []
        
        try:
            # Extract current score and minute
            fixture = fixture_data.get('fixture', {})
            goals = fixture_data.get('goals', {})
            score = fixture_data.get('score', {})
            
            statistics['minute'] = fixture.get('status', {}).get('elapsed')
            statistics['period'] = fixture.get('status', {}).get('long', 'Unknown')
            statistics['home_score'] = goals.get('home', 0)
            statistics['away_score'] = goals.get('away', 0)
            
            # Parse statistics
            stats_array = fixture_data.get('statistics', [])
            
            # Initialize defaults
            stats_map = {
                'possession': (None, None),
                'shots_total': (None, None),
                'shots_on_target': (None, None),
                'corners': (None, None),
                'yellow_cards': (None, None),
                'red_cards': (None, None),
                'fouls': (None, None),
                'offsides': (None, None)
            }
            
            # API-Football returns stats for home and away teams separately
            for team_stats in stats_array:
                team_type = 'home' if team_stats.get('team', {}).get('id') == fixture_data.get('teams', {}).get('home', {}).get('id') else 'away'
                
                for stat in team_stats.get('statistics', []):
                    stat_type = stat.get('type', '').lower()
                    value = stat.get('value')
                    
                    # Map API-Football stat types to our fields
                    if 'ball possession' in stat_type:
                        value = int(value.replace('%', '')) if value and '%' in str(value) else value
                        if team_type == 'home':
                            statistics['home_possession'] = value
                        else:
                            statistics['away_possession'] = value
                    
                    elif 'total shots' in stat_type:
                        if team_type == 'home':
                            statistics['home_shots_total'] = value
                        else:
                            statistics['away_shots_total'] = value
                    
                    elif 'shots on goal' in stat_type or 'shots on target' in stat_type:
                        if team_type == 'home':
                            statistics['home_shots_on_target'] = value
                        else:
                            statistics['away_shots_on_target'] = value
                    
                    elif 'corner' in stat_type:
                        if team_type == 'home':
                            statistics['home_corners'] = value
                        else:
                            statistics['away_corners'] = value
                    
                    elif 'yellow card' in stat_type:
                        if team_type == 'home':
                            statistics['home_yellow_cards'] = value
                        else:
                            statistics['away_yellow_cards'] = value
                    
                    elif 'red card' in stat_type:
                        if team_type == 'home':
                            statistics['home_red_cards'] = value
                        else:
                            statistics['away_red_cards'] = value
                    
                    elif 'fouls' in stat_type:
                        if team_type == 'home':
                            statistics['home_fouls'] = value
                        else:
                            statistics['away_fouls'] = value
                    
                    elif 'offsides' in stat_type:
                        if team_type == 'home':
                            statistics['home_offsides'] = value
                        else:
                            statistics['away_offsides'] = value
            
            # Parse events (goals, cards, substitutions)
            events_array = fixture_data.get('events', [])
            for event in events_array:
                event_type = event.get('type', '').lower()
                
                # Map to our event types
                mapped_type = None
                if 'goal' in event_type:
                    mapped_type = 'goal'
                elif 'card' in event_type:
                    detail = event.get('detail', '').lower()
                    if 'yellow' in detail:
                        mapped_type = 'yellow_card'
                    elif 'red' in detail:
                        mapped_type = 'red_card'
                elif 'subst' in event_type:
                    mapped_type = 'substitution'
                
                if mapped_type:
                    events.append({
                        'minute': event.get('time', {}).get('elapsed'),
                        'minute_extra': event.get('time', {}).get('extra'),
                        'event_type': mapped_type,
                        'team': 'home' if event.get('team', {}).get('id') == fixture_data.get('teams', {}).get('home', {}).get('id') else 'away',
                        'player_name': event.get('player', {}).get('name'),
                        'player_id': event.get('player', {}).get('id'),
                        'assist_player_name': event.get('assist', {}).get('name'),
                        'detail': event.get('detail'),
                        'score_home': statistics['home_score'],
                        'score_away': statistics['away_score'],
                        'raw_data': event
                    })
            
        except Exception as e:
            logger.error(f"Error parsing statistics: {e}", exc_info=True)
        
        return statistics, events
    
    def store_live_statistics(self, match_id: int, statistics: Dict):
        """Store live statistics in database"""
        try:
            with psycopg2.connect(self.db_url) as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    INSERT INTO live_match_stats (
                        match_id, minute, period,
                        home_score, away_score,
                        home_possession, away_possession,
                        home_shots_total, away_shots_total,
                        home_shots_on_target, away_shots_on_target,
                        home_corners, away_corners,
                        home_yellow_cards, away_yellow_cards,
                        home_red_cards, away_red_cards,
                        home_fouls, away_fouls,
                        home_offsides, away_offsides
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                """, (
                    match_id,
                    statistics.get('minute'),
                    statistics.get('period'),
                    statistics.get('home_score', 0),
                    statistics.get('away_score', 0),
                    statistics.get('home_possession'),
                    statistics.get('away_possession'),
                    statistics.get('home_shots_total'),
                    statistics.get('away_shots_total'),
                    statistics.get('home_shots_on_target'),
                    statistics.get('away_shots_on_target'),
                    statistics.get('home_corners'),
                    statistics.get('away_corners'),
                    statistics.get('home_yellow_cards'),
                    statistics.get('away_yellow_cards'),
                    statistics.get('home_red_cards'),
                    statistics.get('away_red_cards'),
                    statistics.get('home_fouls'),
                    statistics.get('away_fouls'),
                    statistics.get('home_offsides'),
                    statistics.get('away_offsides')
                ))
                
                conn.commit()
                logger.info(f"✅ Stored live stats for match {match_id} (minute {statistics.get('minute')})")
                
        except Exception as e:
            logger.error(f"Error storing statistics: {e}")
    
    def store_events(self, match_id: int, events: List[Dict]):
        """Store match events in database (deduplicated)"""
        if not events:
            return
        
        try:
            with psycopg2.connect(self.db_url) as conn:
                cursor = conn.cursor()
                
                # Check which events already exist to avoid duplicates
                for event in events:
                    cursor.execute("""
                        SELECT id FROM match_events
                        WHERE match_id = %s
                            AND minute = %s
                            AND event_type = %s
                            AND player_name = %s
                        LIMIT 1
                    """, (
                        match_id,
                        event.get('minute'),
                        event.get('event_type'),
                        event.get('player_name')
                    ))
                    
                    if cursor.fetchone():
                        continue  # Event already exists
                    
                    # Insert new event
                    cursor.execute("""
                        INSERT INTO match_events (
                            match_id, minute, minute_extra, event_type, team,
                            player_name, player_id, assist_player_name, detail,
                            score_home, score_away, raw_data
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                        )
                    """, (
                        match_id,
                        event.get('minute'),
                        event.get('minute_extra'),
                        event.get('event_type'),
                        event.get('team'),
                        event.get('player_name'),
                        event.get('player_id'),
                        event.get('assist_player_name'),
                        event.get('detail'),
                        event.get('score_home'),
                        event.get('score_away'),
                        json.dumps(event.get('raw_data', {}))
                    ))
                
                conn.commit()
                logger.info(f"✅ Stored {len(events)} new events for match {match_id}")
                
        except Exception as e:
            logger.error(f"Error storing events: {e}")
    
    def collect_all_live_matches(self):
        """Main collection loop - fetch data for all live matches"""
        try:
            live_matches = self.get_live_matches()
            
            if not live_matches:
                logger.info("No live matches to collect")
                return
            
            logger.info(f"🔴 LIVE COLLECTION: Processing {len(live_matches)} matches")
            
            for our_match_id, api_football_id in live_matches:
                try:
                    # Fetch live data
                    fixture_data = self.fetch_live_fixture(api_football_id)
                    
                    if not fixture_data:
                        logger.warning(f"No data for match {our_match_id} (API-Football ID: {api_football_id})")
                        continue
                    
                    # Parse statistics and events
                    statistics, events = self.parse_live_statistics(fixture_data)
                    
                    # Store in database
                    self.store_live_statistics(our_match_id, statistics)
                    self.store_events(our_match_id, events)
                    
                    logger.info(f"✅ Collected live data for match {our_match_id}: "
                              f"{statistics.get('home_score', 0)}-{statistics.get('away_score', 0)} "
                              f"(min {statistics.get('minute')})")
                    
                except Exception as e:
                    logger.error(f"Error processing match {our_match_id}: {e}")
                    continue
            
            logger.info(f"✅ Live collection complete")
            
        except Exception as e:
            logger.error(f"Error in live collection: {e}", exc_info=True)


# Standalone function for scheduler
def collect_live_data():
    """Wrapper function for scheduler"""
    collector = LiveDataCollector()
    collector.collect_all_live_matches()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    collect_live_data()
