"""
Soccer Anytime Goalscorer Odds Collector & Edge Detection

Collects real bookmaker odds for anytime goalscorer markets from The Odds API,
matches them to our fixtures/players, and computes edge vs model predictions.
"""

import os
import re
import math
import logging
import unicodedata
import requests
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger(__name__)

SOCCER_LEAGUES = {
    'soccer_epl': {'league_id': 39, 'name': 'Premier League'},
    'soccer_spain_la_liga': {'league_id': 140, 'name': 'La Liga'},
    'soccer_italy_serie_a': {'league_id': 135, 'name': 'Serie A'},
    'soccer_germany_bundesliga': {'league_id': 78, 'name': 'Bundesliga'},
    'soccer_france_ligue_one': {'league_id': 61, 'name': 'Ligue 1'},
    'soccer_usa_mls': {'league_id': 253, 'name': 'MLS'},
}

LEAGUE_AVG_GOAL_RATE = 0.12
SHRINKAGE_GAMES = 15
MIN_PROB = 0.04
MAX_PROB = 0.45


def _normalize_name(name: str) -> str:
    if not name:
        return ''
    name = unicodedata.normalize('NFD', name)
    name = ''.join(c for c in name if unicodedata.category(c) != 'Mn')
    name = name.lower().strip()
    name = re.sub(r'[^a-z\s]', '', name)
    name = re.sub(r'\s+', ' ', name)
    return name


def _name_tokens(name: str) -> set:
    return set(_normalize_name(name).split())


class SoccerScorerOddsCollector:
    BASE_URL = "https://api.the-odds-api.com/v4"

    def __init__(self):
        self.api_key = os.getenv('ODDS_API_KEY')
        self.db_url = os.getenv('DATABASE_URL')

        if not self.api_key:
            raise ValueError("ODDS_API_KEY not set")
        if not self.db_url:
            raise ValueError("DATABASE_URL not set")

        self.engine = create_engine(self.db_url, pool_pre_ping=True, pool_recycle=300)
        self._ensure_tables()

        self.metrics = {
            'api_calls': 0,
            'events_found': 0,
            'events_matched': 0,
            'players_matched': 0,
            'players_unmatched': 0,
            'odds_collected': 0,
            'errors': 0,
            'remaining_quota': None,
        }

    def _ensure_tables(self):
        with self.engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS soccer_scorer_odds (
                    id SERIAL PRIMARY KEY,
                    match_id INTEGER NOT NULL,
                    league_id INTEGER,
                    sport_key VARCHAR(50) NOT NULL,
                    event_id VARCHAR(100) NOT NULL,
                    player_name VARCHAR(200) NOT NULL,
                    player_id INTEGER,
                    bookmaker VARCHAR(50) NOT NULL,
                    decimal_odds NUMERIC(8,3) NOT NULL,
                    american_odds INTEGER,
                    implied_prob NUMERIC(6,4),
                    commence_time TIMESTAMPTZ,
                    collected_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(match_id, player_name, bookmaker, collected_at)
                )
            """))

            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_soccer_scorer_odds_match 
                ON soccer_scorer_odds(match_id, collected_at DESC)
            """))

            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_soccer_scorer_odds_player 
                ON soccer_scorer_odds(player_id, collected_at DESC)
                WHERE player_id IS NOT NULL
            """))

            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS player_name_aliases (
                    id SERIAL PRIMARY KEY,
                    odds_api_name VARCHAR(200) NOT NULL,
                    player_id INTEGER NOT NULL,
                    player_name VARCHAR(200),
                    confidence NUMERIC(4,2) DEFAULT 1.0,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(odds_api_name, player_id)
                )
            """))

            conn.commit()
            logger.info("SoccerScorerOddsCollector: Tables ensured")

    def _api_request(self, endpoint: str, params: Dict = None) -> Optional[any]:
        url = f"{self.BASE_URL}{endpoint}"
        params = params or {}
        params['apiKey'] = self.api_key

        try:
            response = requests.get(url, params=params, timeout=30)
            self.metrics['api_calls'] += 1

            remaining = response.headers.get('x-requests-remaining', 'N/A')
            self.metrics['remaining_quota'] = remaining

            if response.status_code == 200:
                return response.json()
            elif response.status_code == 429:
                logger.warning("Rate limited on The Odds API")
                return None
            elif response.status_code == 422:
                logger.debug(f"No player props available for this endpoint: {endpoint}")
                return None
            else:
                logger.error(f"API error {response.status_code}: {response.text[:200]}")
                self.metrics['errors'] += 1
                return None

        except Exception as e:
            logger.error(f"Request failed: {e}")
            self.metrics['errors'] += 1
            return None

    def _american_to_decimal(self, american_odds: int) -> float:
        if american_odds is None:
            return None
        if american_odds > 0:
            return round(1 + (american_odds / 100), 3)
        else:
            return round(1 + (100 / abs(american_odds)), 3)

    def _get_events(self, sport_key: str) -> List[Dict]:
        data = self._api_request(
            f"/sports/{sport_key}/odds",
            params={'regions': 'us,uk,eu', 'markets': 'h2h', 'oddsFormat': 'decimal'}
        )
        if not data:
            return []

        events = []
        for event in data:
            try:
                commence = datetime.fromisoformat(event['commence_time'].replace('Z', '+00:00'))
                if commence > datetime.now(timezone.utc) - timedelta(hours=1):
                    events.append({
                        'id': event['id'],
                        'home_team': event.get('home_team', ''),
                        'away_team': event.get('away_team', ''),
                        'commence_time': commence,
                        'sport_key': sport_key,
                    })
            except Exception:
                continue

        return events

    def _match_event_to_fixture(self, event: Dict, league_id: int) -> Optional[int]:
        commence = event['commence_time']
        home_norm = _normalize_name(event['home_team'])
        away_norm = _normalize_name(event['away_team'])

        with self.engine.connect() as conn:
            result = conn.execute(text("""
                SELECT match_id, home_team, away_team, kickoff_at
                FROM fixtures
                WHERE league_id = :league_id
                AND kickoff_at BETWEEN :start AND :end
                AND status IN ('NS', 'scheduled', 'TBD', '1H', '2H', 'HT')
                ORDER BY kickoff_at
            """), {
                'league_id': league_id,
                'start': commence - timedelta(hours=3),
                'end': commence + timedelta(hours=3),
            })

            best_match = None
            best_score = 0

            for row in result.fetchall():
                fixture_home_norm = _normalize_name(row.home_team)
                fixture_away_norm = _normalize_name(row.away_team)

                home_tokens = _name_tokens(event['home_team'])
                away_tokens = _name_tokens(event['away_team'])
                f_home_tokens = _name_tokens(row.home_team)
                f_away_tokens = _name_tokens(row.away_team)

                home_overlap = len(home_tokens & f_home_tokens) / max(len(home_tokens | f_home_tokens), 1)
                away_overlap = len(away_tokens & f_away_tokens) / max(len(away_tokens | f_away_tokens), 1)

                score = (home_overlap + away_overlap) / 2

                if home_norm in fixture_home_norm or fixture_home_norm in home_norm:
                    score = max(score, 0.8)
                if away_norm in fixture_away_norm or fixture_away_norm in away_norm:
                    score = max(score, 0.8)

                if score > best_score:
                    best_score = score
                    best_match = row.match_id

            if best_score >= 0.4:
                return best_match

        return None

    def _match_player_to_db(self, player_name: str, match_id: int) -> Optional[int]:
        with self.engine.connect() as conn:
            cached = conn.execute(text("""
                SELECT player_id FROM player_name_aliases
                WHERE odds_api_name = :name
                LIMIT 1
            """), {'name': player_name}).fetchone()

            if cached:
                return cached.player_id

            result = conn.execute(text("""
                SELECT p.player_id, p.player_name
                FROM players_unified p
                JOIN player_season_stats pss ON p.player_id = pss.player_id
                    AND pss.sport_key = 'soccer' AND pss.season = 2024
                JOIN (
                    SELECT home_team_id, away_team_id FROM fixtures WHERE match_id = :match_id
                ) f ON pss.team_id IN (
                    SELECT api_football_team_id FROM teams 
                    WHERE team_id IN (f.home_team_id, f.away_team_id)
                    AND api_football_team_id IS NOT NULL
                )
                WHERE p.position IN ('Attacker', 'Midfielder', 'F', 'M', 'Defender', 'D')
            """), {'match_id': match_id})

            players = result.fetchall()
            if not players:
                return None

            search_norm = _normalize_name(player_name)
            search_tokens = _name_tokens(player_name)
            search_last = search_norm.split()[-1] if search_norm.split() else ''

            best_pid = None
            best_score = 0
            best_db_name = None

            for p in players:
                db_norm = _normalize_name(p.player_name)
                db_tokens = _name_tokens(p.player_name)
                db_last = db_norm.split()[-1] if db_norm.split() else ''

                if search_norm == db_norm:
                    best_pid = p.player_id
                    best_score = 1.0
                    best_db_name = p.player_name
                    break

                token_overlap = len(search_tokens & db_tokens) / max(len(search_tokens | db_tokens), 1)

                last_name_match = 1.0 if search_last == db_last and len(search_last) >= 3 else 0.0

                if search_norm in db_norm or db_norm in search_norm:
                    substring_score = 0.7
                else:
                    substring_score = 0.0

                score = max(token_overlap, last_name_match * 0.85, substring_score)

                if score > best_score:
                    best_score = score
                    best_pid = p.player_id
                    best_db_name = p.player_name

            if best_score >= 0.5 and best_pid:
                try:
                    conn.execute(text("""
                        INSERT INTO player_name_aliases (odds_api_name, player_id, player_name, confidence)
                        VALUES (:odds_name, :player_id, :db_name, :conf)
                        ON CONFLICT (odds_api_name, player_id) DO NOTHING
                    """), {
                        'odds_name': player_name,
                        'player_id': best_pid,
                        'db_name': best_db_name,
                        'conf': round(best_score, 2),
                    })
                    conn.commit()
                except Exception:
                    pass
                return best_pid

            return None

    def collect_event_scorer_odds(self, sport_key: str, event_id: str, 
                                  match_id: int, league_id: int) -> Dict:
        data = self._api_request(
            f"/sports/{sport_key}/events/{event_id}/odds",
            params={
                'regions': 'us,uk,eu',
                'markets': 'player_anytime_goalscorer',
                'oddsFormat': 'american',
            }
        )

        if not data:
            return {'event_id': event_id, 'odds_collected': 0, 'error': 'no_data'}

        odds_collected = 0
        players_matched = 0
        players_unmatched = 0

        with self.engine.connect() as conn:
            for bookmaker in data.get('bookmakers', []):
                bookie_key = bookmaker['key']

                for market in bookmaker.get('markets', []):
                    if market['key'] != 'player_anytime_goalscorer':
                        continue

                    for outcome in market.get('outcomes', []):
                        player_name = outcome.get('description') or outcome.get('name', '')
                        american_price = outcome.get('price')

                        if not player_name or american_price is None:
                            continue

                        decimal_odds = self._american_to_decimal(american_price)
                        if not decimal_odds or decimal_odds <= 1.0:
                            continue

                        implied_prob = round(1.0 / decimal_odds, 4)

                        player_id = self._match_player_to_db(player_name, match_id)
                        if player_id:
                            players_matched += 1
                        else:
                            players_unmatched += 1

                        try:
                            conn.execute(text("""
                                INSERT INTO soccer_scorer_odds
                                (match_id, league_id, sport_key, event_id, player_name,
                                 player_id, bookmaker, decimal_odds, american_odds,
                                 implied_prob, commence_time)
                                VALUES (:match_id, :league_id, :sport_key, :event_id, :player_name,
                                        :player_id, :bookmaker, :decimal_odds, :american_odds,
                                        :implied_prob, :commence_time)
                                ON CONFLICT (match_id, player_name, bookmaker, collected_at)
                                DO NOTHING
                            """), {
                                'match_id': match_id,
                                'league_id': league_id,
                                'sport_key': sport_key,
                                'event_id': event_id,
                                'player_name': player_name,
                                'player_id': player_id,
                                'bookmaker': bookie_key,
                                'decimal_odds': decimal_odds,
                                'american_odds': american_price,
                                'implied_prob': implied_prob,
                                'commence_time': data.get('commence_time'),
                            })
                            odds_collected += 1
                        except Exception as e:
                            logger.debug(f"Insert error: {e}")

            conn.commit()

        self.metrics['odds_collected'] += odds_collected
        self.metrics['players_matched'] += players_matched
        self.metrics['players_unmatched'] += players_unmatched

        return {
            'event_id': event_id,
            'match_id': match_id,
            'odds_collected': odds_collected,
            'players_matched': players_matched,
            'players_unmatched': players_unmatched,
        }

    def collect_all_soccer_scorer_odds(self, hours_ahead: int = 48) -> Dict:
        total_odds = 0
        total_events = 0
        total_matched = 0
        league_results = {}

        for sport_key, league_info in SOCCER_LEAGUES.items():
            league_id = league_info['league_id']
            league_name = league_info['name']

            try:
                events = self._get_events(sport_key)
                if not events:
                    league_results[sport_key] = {'events': 0, 'odds': 0, 'note': 'no_events'}
                    continue

                cutoff = datetime.now(timezone.utc) + timedelta(hours=hours_ahead)
                events = [e for e in events if e['commence_time'] <= cutoff]

                league_odds = 0
                league_events = 0
                league_matched_events = 0

                for event in events:
                    match_id = self._match_event_to_fixture(event, league_id)
                    if not match_id:
                        logger.debug(f"No fixture match for {event['home_team']} vs {event['away_team']}")
                        continue

                    league_matched_events += 1
                    result = self.collect_event_scorer_odds(sport_key, event['id'], match_id, league_id)
                    league_odds += result.get('odds_collected', 0)
                    league_events += 1

                total_odds += league_odds
                total_events += league_events
                total_matched += league_matched_events

                league_results[sport_key] = {
                    'league': league_name,
                    'events_found': len(events),
                    'events_matched': league_matched_events,
                    'odds_collected': league_odds,
                }

                logger.info(f"⚽ {league_name}: {league_matched_events}/{len(events)} events matched, {league_odds} odds collected")

            except Exception as e:
                logger.error(f"Failed to collect {league_name} scorer odds: {e}")
                league_results[sport_key] = {'error': str(e)}
                self.metrics['errors'] += 1

        logger.info(f"⚽ Soccer scorer odds: {total_odds} odds from {total_events} events across {len(SOCCER_LEAGUES)} leagues")

        return {
            'total_odds_collected': total_odds,
            'total_events_processed': total_events,
            'total_events_matched': total_matched,
            'leagues': league_results,
            'metrics': self.metrics,
        }


class SoccerScorerEdgeDetector:

    def __init__(self):
        self.db_url = os.getenv('DATABASE_URL')
        self.engine = create_engine(self.db_url, pool_pre_ping=True, pool_recycle=300)

    def _poisson_prob(self, goals: int, games_played: int) -> float:
        games_equiv = max(games_played, 1.0)
        raw_rate = goals / games_equiv
        shrinkage_weight = min(games_equiv / (games_equiv + SHRINKAGE_GAMES), 0.85)
        shrunk_rate = raw_rate * shrinkage_weight + LEAGUE_AVG_GOAL_RATE * (1 - shrinkage_weight)
        shrunk_rate = max(0.03, min(0.55, shrunk_rate))
        prob = 1.0 - math.exp(-shrunk_rate)
        return max(MIN_PROB, min(MAX_PROB, prob))

    def get_best_single_bets(self, limit: int = 20, min_edge: float = 2.0,
                              hours_ahead: int = 72) -> List[Dict]:
        with self.engine.connect() as conn:
            result = conn.execute(text("""
                WITH latest_odds AS (
                    SELECT DISTINCT ON (match_id, player_name, bookmaker)
                        sso.match_id,
                        sso.league_id,
                        sso.player_name AS odds_player_name,
                        sso.player_id,
                        sso.bookmaker,
                        sso.decimal_odds,
                        sso.implied_prob,
                        sso.collected_at
                    FROM soccer_scorer_odds sso
                    JOIN fixtures f ON f.match_id = sso.match_id
                    WHERE f.kickoff_at > NOW()
                      AND f.kickoff_at < NOW() + (CAST(:hours AS INTEGER) * INTERVAL '1 hour')
                      AND f.status IN ('NS', 'scheduled', 'TBD')
                      AND sso.collected_at > NOW() - INTERVAL '12 hours'
                    ORDER BY match_id, player_name, bookmaker, collected_at DESC
                ),
                consensus_odds AS (
                    SELECT
                        match_id,
                        odds_player_name,
                        player_id,
                        AVG(decimal_odds) AS avg_decimal_odds,
                        AVG(implied_prob) AS avg_implied_prob,
                        MAX(decimal_odds) AS best_odds,
                        MIN(implied_prob) AS min_implied_prob,
                        COUNT(DISTINCT bookmaker) AS bookmaker_count,
                        MAX(collected_at) AS last_update,
                        league_id
                    FROM latest_odds
                    GROUP BY match_id, odds_player_name, player_id, league_id
                    HAVING COUNT(DISTINCT bookmaker) >= 2
                )
                SELECT
                    co.match_id,
                    co.league_id,
                    co.odds_player_name,
                    co.player_id,
                    co.avg_decimal_odds,
                    co.avg_implied_prob,
                    co.best_odds,
                    co.min_implied_prob,
                    co.bookmaker_count,
                    co.last_update,
                    f.home_team,
                    f.away_team,
                    f.league_name,
                    f.kickoff_at,
                    p.player_name AS db_player_name,
                    p.position,
                    pss.games_played,
                    COALESCE((pss.stats->>'goals')::int, 0) AS season_goals,
                    pss.team_name
                FROM consensus_odds co
                JOIN fixtures f ON f.match_id = co.match_id
                LEFT JOIN players_unified p ON p.player_id = co.player_id
                LEFT JOIN player_season_stats pss ON pss.player_id = co.player_id
                    AND pss.sport_key = 'soccer' AND pss.season = 2024
                ORDER BY co.avg_implied_prob ASC
                LIMIT 200
            """), {'hours': str(hours_ahead)})

            candidates = []
            for row in result.fetchall():
                r = dict(row._mapping)

                if r['player_id'] and r['games_played'] and r['games_played'] >= 3:
                    model_prob = self._poisson_prob(r['season_goals'], r['games_played'])
                else:
                    model_prob = r['avg_implied_prob'] * 0.95 if r['avg_implied_prob'] else 0.10

                implied_prob = float(r['avg_implied_prob']) if r['avg_implied_prob'] else 0
                best_odds = float(r['best_odds']) if r['best_odds'] else 0
                best_implied = 1.0 / best_odds if best_odds > 1 else implied_prob

                edge_pct = (model_prob - implied_prob) * 100

                if best_odds > 1:
                    ev = model_prob * (best_odds - 1) - (1 - model_prob)
                else:
                    ev = 0

                player_display = r['db_player_name'] or r['odds_player_name']

                candidates.append({
                    'match_id': r['match_id'],
                    'league_id': r['league_id'],
                    'league': r['league_name'],
                    'home_team': r['home_team'],
                    'away_team': r['away_team'],
                    'kickoff_at': r['kickoff_at'].isoformat() if r['kickoff_at'] else None,
                    'player_name': player_display,
                    'player_id': r['player_id'],
                    'position': r['position'],
                    'team': r['team_name'],
                    'market': 'anytime_scorer',
                    'model_prob': round(model_prob, 4),
                    'implied_prob': round(implied_prob, 4),
                    'best_odds': round(best_odds, 2),
                    'avg_odds': round(float(r['avg_decimal_odds']), 2) if r['avg_decimal_odds'] else None,
                    'edge_pct': round(edge_pct, 2),
                    'ev': round(ev, 4),
                    'bookmaker_count': r['bookmaker_count'],
                    'season_goals': r['season_goals'],
                    'games_played': r['games_played'],
                    'goals_per_game': round(r['season_goals'] / r['games_played'], 3) if r['games_played'] and r['games_played'] > 0 else None,
                    'has_model_data': r['player_id'] is not None and r['games_played'] is not None,
                    'confidence': 'high' if r['games_played'] and r['games_played'] >= 10 and r['bookmaker_count'] >= 3 else 'medium' if r['games_played'] and r['games_played'] >= 5 else 'low',
                    'last_update': r['last_update'].isoformat() if r['last_update'] else None,
                })

            positive_ev = [c for c in candidates if c['edge_pct'] >= min_edge]
            positive_ev.sort(key=lambda x: x['ev'], reverse=True)

            if len(positive_ev) < limit:
                remaining = [c for c in candidates if c not in positive_ev]
                remaining.sort(key=lambda x: x['ev'], reverse=True)
                positive_ev.extend(remaining[:limit - len(positive_ev)])

            return positive_ev[:limit]

    def get_edge_legs_for_parlays(self, min_edge: float = 0.0, min_bookmakers: int = 2,
                                   hours_ahead: int = 72) -> List[Dict]:
        bets = self.get_best_single_bets(limit=100, min_edge=min_edge, hours_ahead=hours_ahead)
        return [b for b in bets if b['has_model_data'] and b['bookmaker_count'] >= min_bookmakers]

    def get_coverage_stats(self) -> Dict:
        with self.engine.connect() as conn:
            result = conn.execute(text("""
                SELECT
                    COUNT(DISTINCT match_id) AS matches_with_odds,
                    COUNT(DISTINCT player_name) AS unique_players,
                    COUNT(DISTINCT CASE WHEN player_id IS NOT NULL THEN player_name END) AS matched_players,
                    COUNT(*) AS total_odds_rows,
                    COUNT(DISTINCT bookmaker) AS bookmakers,
                    MIN(collected_at) AS earliest,
                    MAX(collected_at) AS latest
                FROM soccer_scorer_odds
                WHERE collected_at > NOW() - INTERVAL '24 hours'
            """))

            row = result.fetchone()
            if row:
                return {
                    'matches_with_odds': row.matches_with_odds,
                    'unique_players': row.unique_players,
                    'matched_players': row.matched_players,
                    'unmatched_players': row.unique_players - row.matched_players,
                    'match_rate_pct': round(row.matched_players / max(row.unique_players, 1) * 100, 1),
                    'total_odds_rows': row.total_odds_rows,
                    'bookmakers': row.bookmakers,
                    'earliest': row.earliest.isoformat() if row.earliest else None,
                    'latest': row.latest.isoformat() if row.latest else None,
                }

            return {'matches_with_odds': 0}


def collect_soccer_scorer_odds_job() -> Dict:
    try:
        collector = SoccerScorerOddsCollector()
        result = collector.collect_all_soccer_scorer_odds(hours_ahead=48)
        return {'success': True, **result}
    except Exception as e:
        logger.error(f"Soccer scorer odds collection failed: {e}")
        return {'success': False, 'error': str(e)}
