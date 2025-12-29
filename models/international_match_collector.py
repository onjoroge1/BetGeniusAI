"""
International Match Collector - World Cup & Tournament Data
Collects historical international match data from API-Football for:
- FIFA World Cup (2002-2022, 2026)
- World Cup Qualifiers (CAF, UEFA, CONMEBOL, CONCACAF, AFC)
- Continental tournaments (Euro, AFCON, Copa America)
- International Friendlies (weighted lower for training)

Uses RAPIDAPI_KEY for API-Football access.
"""

import os
import logging
import requests
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple
import time

logger = logging.getLogger(__name__)


class InternationalMatchCollector:
    """
    Collects international football match data for World Cup model training.
    
    Key Features:
    - Historical backfill for past World Cups (2002-2022)
    - Real-time collection for WC Qualifiers
    - Tournament stage classification (group, r16, qf, sf, final)
    - Extra time and penalty shootout tracking
    - Squad and player data collection
    """
    
    INTERNATIONAL_LEAGUES = {
        1: {'name': 'FIFA World Cup', 'priority': 1, 'is_tournament': True},
        4: {'name': 'UEFA Euro', 'priority': 1, 'is_tournament': True},
        6: {'name': 'Africa Cup of Nations', 'priority': 2, 'is_tournament': True},
        9: {'name': 'Copa America', 'priority': 2, 'is_tournament': True},
        5: {'name': 'UEFA Nations League', 'priority': 3, 'is_tournament': False},
        29: {'name': 'WC Qualifiers - CAF', 'priority': 2, 'is_tournament': False},
        30: {'name': 'WC Qualifiers - AFC', 'priority': 2, 'is_tournament': False},
        31: {'name': 'WC Qualifiers - CONCACAF', 'priority': 2, 'is_tournament': False},
        32: {'name': 'WC Qualifiers - UEFA', 'priority': 1, 'is_tournament': False},
        33: {'name': 'WC Qualifiers - OFC', 'priority': 3, 'is_tournament': False},
        34: {'name': 'WC Qualifiers - CONMEBOL', 'priority': 1, 'is_tournament': False},
        10: {'name': 'International Friendlies', 'priority': 4, 'is_tournament': False},
    }
    
    WORLD_CUP_SEASONS = [2002, 2006, 2010, 2014, 2018, 2022, 2026]
    EURO_SEASONS = [2004, 2008, 2012, 2016, 2020, 2024]
    COPA_SEASONS = [2004, 2007, 2011, 2015, 2016, 2019, 2021, 2024]
    AFCON_SEASONS = [2004, 2006, 2008, 2010, 2012, 2013, 2015, 2017, 2019, 2021, 2023]
    
    def __init__(self):
        self.api_key = os.getenv('RAPIDAPI_KEY')
        self.db_url = os.getenv('DATABASE_URL')
        self.base_url = "https://api-football-v1.p.rapidapi.com/v3"
        
        if not self.api_key:
            raise ValueError("RAPIDAPI_KEY not set")
        
        self.headers = {
            'x-rapidapi-key': self.api_key,
            'x-rapidapi-host': 'api-football-v1.p.rapidapi.com'
        }
        
        self.metrics = {
            'api_calls': 0,
            'matches_collected': 0,
            'matches_inserted': 0,
            'errors': 0,
            'rate_limit_waits': 0
        }
        
        self.rate_limit_remaining = 100
        self.rate_limit_reset = None
    
    def _make_api_request(self, endpoint: str, params: Optional[dict] = None) -> Optional[dict]:
        """Make API request with rate limiting."""
        url = f"{self.base_url}/{endpoint}"
        
        if self.rate_limit_remaining < 5:
            wait_time = 60
            logger.warning(f"Rate limit low ({self.rate_limit_remaining}), waiting {wait_time}s")
            time.sleep(wait_time)
            self.metrics['rate_limit_waits'] += 1
        
        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=30)
            self.metrics['api_calls'] += 1
            
            self.rate_limit_remaining = int(response.headers.get('x-ratelimit-requests-remaining', 100))
            
            if response.status_code == 429:
                logger.warning("Rate limited, waiting 60s...")
                time.sleep(60)
                return self._make_api_request(endpoint, params)
            
            if response.status_code != 200:
                logger.error(f"API error {response.status_code}: {response.text[:200]}")
                return None
            
            data = response.json()
            if data.get('errors'):
                logger.error(f"API returned errors: {data['errors']}")
                return None
            
            return data
            
        except Exception as e:
            logger.error(f"Request failed: {e}")
            self.metrics['errors'] += 1
            return None
    
    def _classify_stage(self, round_name: str) -> str:
        """Classify tournament stage from round name."""
        if not round_name:
            return 'unknown'
        
        round_lower = round_name.lower()
        
        if 'final' in round_lower and 'semi' not in round_lower and 'quarter' not in round_lower:
            return 'final'
        if 'semi' in round_lower or 'sf' in round_lower:
            return 'sf'
        if 'quarter' in round_lower or 'qf' in round_lower:
            return 'qf'
        if 'round of 16' in round_lower or 'r16' in round_lower or '1/8' in round_lower:
            return 'r16'
        if 'round of 32' in round_lower or 'r32' in round_lower:
            return 'r32'
        if 'group' in round_lower or 'matchday' in round_lower:
            return 'group'
        if '3rd place' in round_lower or 'third' in round_lower:
            return '3rd_place'
        if 'play-off' in round_lower or 'playoff' in round_lower:
            return 'playoff'
        if 'qualifying' in round_lower or 'qual' in round_lower:
            return 'qualifying'
        
        return 'other'
    
    def _determine_outcome(self, home_goals: int, away_goals: int) -> str:
        """Determine match outcome (H/D/A)."""
        if home_goals > away_goals:
            return 'H'
        elif away_goals > home_goals:
            return 'A'
        return 'D'
    
    def collect_league_season(self, league_id: int, season: int) -> Dict:
        """
        Collect all matches for a specific league and season.
        """
        league_info = self.INTERNATIONAL_LEAGUES.get(league_id, {})
        league_name = league_info.get('name', f'League {league_id}')
        
        logger.info(f"📥 Collecting {league_name} {season}...")
        
        data = self._make_api_request('fixtures', {
            'league': league_id,
            'season': season,
            'status': 'FT-AET-PEN'
        })
        
        if not data or not data.get('response'):
            logger.warning(f"  No data for {league_name} {season}")
            return {'matches': 0, 'inserted': 0}
        
        matches = data['response']
        self.metrics['matches_collected'] += len(matches)
        
        inserted = 0
        for match in matches:
            try:
                if self._store_international_match(match, league_id, league_name, season):
                    inserted += 1
            except Exception as e:
                logger.error(f"  Error storing match {match.get('fixture', {}).get('id')}: {e}")
                self.metrics['errors'] += 1
        
        self.metrics['matches_inserted'] += inserted
        logger.info(f"  ✅ {league_name} {season}: {len(matches)} matches, {inserted} inserted")
        
        return {'matches': len(matches), 'inserted': inserted}
    
    def _store_international_match(self, match_data: dict, league_id: int, 
                                    league_name: str, season: int) -> bool:
        """Store a single international match."""
        fixture = match_data.get('fixture', {})
        teams = match_data.get('teams', {})
        goals = match_data.get('goals', {})
        score = match_data.get('score', {})
        league = match_data.get('league', {})
        
        fixture_id = fixture.get('id')
        if not fixture_id:
            return False
        
        home_goals = goals.get('home')
        away_goals = goals.get('away')
        
        if home_goals is None or away_goals is None:
            return False
        
        extra_time = score.get('extratime', {}).get('home') is not None
        penalty = score.get('penalty', {}).get('home') is not None
        
        ht_score = score.get('halftime', {})
        penalty_score = score.get('penalty', {})
        
        stage = self._classify_stage(league.get('round', ''))
        outcome = self._determine_outcome(home_goals, away_goals)
        
        match_date = fixture.get('date')
        venue_data = fixture.get('venue', {})
        
        venue_country = league.get('country', 'World')
        
        league_info = self.INTERNATIONAL_LEAGUES.get(league_id, {})
        is_tournament = league_info.get('is_tournament', True)
        
        if is_tournament:
            is_neutral = True
        else:
            home_team = teams.get('home', {}).get('name', '')
            venue_city = venue_data.get('city', '')
            venue_name = venue_data.get('name', '')
            
            home_in_venue = any([
                home_team.lower() in venue_city.lower() if venue_city else False,
                home_team.lower() in venue_name.lower() if venue_name else False,
            ])
            is_neutral = not home_in_venue
        
        conn = None
        try:
            conn = psycopg2.connect(self.db_url)
            cur = conn.cursor()
            
            cur.execute("""
                INSERT INTO international_matches (
                    api_football_fixture_id, tournament_id, tournament_name,
                    tournament_stage, season, match_date,
                    home_team_id, away_team_id, home_team_name, away_team_name,
                    home_goals, away_goals, home_goals_ht, away_goals_ht,
                    outcome, extra_time, penalty_shootout,
                    penalty_home, penalty_away,
                    venue, city, country, neutral_venue
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (api_football_fixture_id) DO UPDATE SET
                    home_goals = EXCLUDED.home_goals,
                    away_goals = EXCLUDED.away_goals,
                    outcome = EXCLUDED.outcome,
                    extra_time = EXCLUDED.extra_time,
                    penalty_shootout = EXCLUDED.penalty_shootout
            """, (
                fixture_id,
                league_id,
                league_name,
                stage,
                season,
                match_date,
                teams.get('home', {}).get('id'),
                teams.get('away', {}).get('id'),
                teams.get('home', {}).get('name'),
                teams.get('away', {}).get('name'),
                home_goals,
                away_goals,
                ht_score.get('home'),
                ht_score.get('away'),
                outcome,
                extra_time,
                penalty,
                penalty_score.get('home'),
                penalty_score.get('away'),
                venue_data.get('name'),
                venue_data.get('city'),
                venue_country,
                is_neutral if is_neutral is not None else True
            ))
            
            conn.commit()
            
            if penalty:
                self._store_penalty_shootout(cur, match_data, league_id, league_name, stage)
                conn.commit()
            
            return True
            
        except psycopg2.errors.UniqueViolation:
            if conn:
                conn.rollback()
            return False
        except Exception as e:
            if conn:
                conn.rollback()
            raise e
        finally:
            if conn:
                conn.close()
    
    def _store_penalty_shootout(self, cursor, match_data: dict, 
                                 tournament_id: int, tournament_name: str, stage: str):
        """Store penalty shootout record for psychology features."""
        teams = match_data.get('teams', {})
        score = match_data.get('score', {})
        fixture = match_data.get('fixture', {})
        
        penalty_score = score.get('penalty', {})
        home_pens = penalty_score.get('home', 0)
        away_pens = penalty_score.get('away', 0)
        
        match_date = fixture.get('date', '')[:10]
        
        home_result = 'W' if home_pens > away_pens else 'L'
        away_result = 'W' if away_pens > home_pens else 'L'
        
        cursor.execute("""
            INSERT INTO penalty_shootout_history (
                team_id, team_name, opponent_id, opponent_name,
                tournament_id, tournament_name, match_date, stage,
                result, penalties_scored, penalties_missed
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
        """, (
            teams.get('home', {}).get('id'),
            teams.get('home', {}).get('name'),
            teams.get('away', {}).get('id'),
            teams.get('away', {}).get('name'),
            tournament_id,
            tournament_name,
            match_date,
            stage,
            home_result,
            home_pens,
            5 - home_pens if home_pens < 5 else 0
        ))
        
        cursor.execute("""
            INSERT INTO penalty_shootout_history (
                team_id, team_name, opponent_id, opponent_name,
                tournament_id, tournament_name, match_date, stage,
                result, penalties_scored, penalties_missed
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
        """, (
            teams.get('away', {}).get('id'),
            teams.get('away', {}).get('name'),
            teams.get('home', {}).get('id'),
            teams.get('home', {}).get('name'),
            tournament_id,
            tournament_name,
            match_date,
            stage,
            away_result,
            away_pens,
            5 - away_pens if away_pens < 5 else 0
        ))
    
    def backfill_world_cups(self) -> Dict:
        """Backfill all historical World Cup matches."""
        logger.info("🏆 Starting World Cup historical backfill...")
        
        results = {}
        for season in self.WORLD_CUP_SEASONS:
            if season > datetime.now().year:
                continue
            result = self.collect_league_season(1, season)
            results[f"WC_{season}"] = result
            time.sleep(1)
        
        return results
    
    def backfill_euros(self) -> Dict:
        """Backfill all historical Euro matches."""
        logger.info("🇪🇺 Starting Euro historical backfill...")
        
        results = {}
        for season in self.EURO_SEASONS:
            if season > datetime.now().year:
                continue
            result = self.collect_league_season(4, season)
            results[f"Euro_{season}"] = result
            time.sleep(1)
        
        return results
    
    def backfill_copa_america(self) -> Dict:
        """Backfill all historical Copa America matches."""
        logger.info("🌎 Starting Copa America historical backfill...")
        
        results = {}
        for season in self.COPA_SEASONS:
            if season > datetime.now().year:
                continue
            result = self.collect_league_season(9, season)
            results[f"Copa_{season}"] = result
            time.sleep(1)
        
        return results
    
    def backfill_afcon(self) -> Dict:
        """Backfill all historical AFCON matches."""
        logger.info("🌍 Starting AFCON historical backfill...")
        
        results = {}
        for season in self.AFCON_SEASONS:
            if season > datetime.now().year:
                continue
            result = self.collect_league_season(6, season)
            results[f"AFCON_{season}"] = result
            time.sleep(1)
        
        return results
    
    def backfill_wc_qualifiers(self, start_year: int = 2018) -> Dict:
        """Backfill World Cup qualifier matches."""
        logger.info("🎯 Starting WC Qualifiers backfill...")
        
        qualifier_leagues = [29, 30, 31, 32, 34]
        current_year = datetime.now().year
        
        results = {}
        for league_id in qualifier_leagues:
            league_name = self.INTERNATIONAL_LEAGUES[league_id]['name']
            for season in range(start_year, current_year + 1):
                result = self.collect_league_season(league_id, season)
                results[f"{league_name}_{season}"] = result
                time.sleep(0.5)
        
        return results
    
    def run_full_backfill(self) -> Dict:
        """
        Run complete historical backfill for all international competitions.
        This is a long-running operation - expect 1-2 hours.
        """
        logger.info("🌐 Starting FULL international match backfill...")
        start_time = datetime.now()
        
        all_results = {
            'world_cups': self.backfill_world_cups(),
            'euros': self.backfill_euros(),
            'copa_america': self.backfill_copa_america(),
            'afcon': self.backfill_afcon(),
            'wc_qualifiers': self.backfill_wc_qualifiers()
        }
        
        duration = (datetime.now() - start_time).total_seconds()
        
        summary = {
            'duration_seconds': duration,
            'api_calls': self.metrics['api_calls'],
            'matches_collected': self.metrics['matches_collected'],
            'matches_inserted': self.metrics['matches_inserted'],
            'errors': self.metrics['errors'],
            'details': all_results
        }
        
        logger.info(f"✅ Backfill complete in {duration:.0f}s")
        logger.info(f"   API calls: {self.metrics['api_calls']}")
        logger.info(f"   Matches collected: {self.metrics['matches_collected']}")
        logger.info(f"   Matches inserted: {self.metrics['matches_inserted']}")
        
        return summary
    
    # API-Football uses different season years for WC 2026 qualifiers by confederation
    WC_2026_QUALIFIER_SEASONS = {
        29: 2023,  # CAF - uses 2023 season
        30: 2026,  # AFC - uses 2026 season
        31: 2026,  # CONCACAF - uses 2026 season
        32: 2024,  # UEFA - uses 2024 season
        33: 2026,  # OFC (Oceania) - uses 2026 season
        34: 2026,  # CONMEBOL - uses 2026 season
    }
    
    def collect_current_qualifiers(self) -> Dict:
        """
        Collect recent WC qualifier matches (for scheduled collection).
        Uses correct API season mapping for each confederation.
        """
        logger.info("📥 Collecting current WC qualifier matches...")
        
        qualifier_leagues = [29, 30, 31, 32, 33, 34]
        
        results = {}
        for league_id in qualifier_leagues:
            league_name = self.INTERNATIONAL_LEAGUES.get(league_id, {}).get('name', f'League {league_id}')
            # Use correct API season for each confederation
            season = self.WC_2026_QUALIFIER_SEASONS.get(league_id, 2026)
            result = self.collect_league_season(league_id, season)
            results[league_name] = result
            time.sleep(0.5)
        
        return results
    
    def get_collection_stats(self) -> Dict:
        """Get current collection statistics."""
        conn = None
        try:
            conn = psycopg2.connect(self.db_url)
            cur = conn.cursor(cursor_factory=RealDictCursor)
            
            cur.execute("""
                SELECT 
                    tournament_name,
                    COUNT(*) as total_matches,
                    COUNT(DISTINCT season) as seasons,
                    MIN(match_date) as earliest_match,
                    MAX(match_date) as latest_match,
                    SUM(CASE WHEN penalty_shootout THEN 1 ELSE 0 END) as penalty_shootouts
                FROM international_matches
                GROUP BY tournament_name
                ORDER BY total_matches DESC
            """)
            
            stats = cur.fetchall()
            
            cur.execute("SELECT COUNT(*) as total FROM international_matches")
            row = cur.fetchone()
            total = row['total'] if row else 0
            
            cur.execute("SELECT COUNT(*) as total FROM penalty_shootout_history")
            row = cur.fetchone()
            shootouts = row['total'] if row else 0
            
            return {
                'total_matches': total,
                'penalty_shootouts_recorded': shootouts,
                'by_tournament': [dict(s) for s in stats]
            }
            
        finally:
            if conn:
                conn.close()


def test_collector():
    """Test the collector with a small sample."""
    collector = InternationalMatchCollector()
    
    print("\n🧪 Testing International Match Collector...")
    print(f"   API Key configured: {'Yes' if collector.api_key else 'No'}")
    print(f"   Rate limit remaining: {collector.rate_limit_remaining}")
    
    result = collector.collect_league_season(1, 2022)
    print(f"\n   World Cup 2022: {result}")
    
    stats = collector.get_collection_stats()
    print(f"\n   Collection Stats: {stats}")
    
    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_collector()
