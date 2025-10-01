"""
Team matching system for API-Football fixture resolution.
Handles accent normalization, aliases, and fuzzy matching.
"""

import unicodedata
import re
from typing import Optional, Tuple, Dict, List
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

try:
    from rapidfuzz import fuzz
    FUZZY_AVAILABLE = True
except ImportError:
    import difflib
    FUZZY_AVAILABLE = False
    logger.warning("rapidfuzz not available, using difflib for fuzzy matching")


class TeamMatcher:
    """
    Deterministic + fuzzy team matching for fixture ID resolution.
    
    Features:
    - Accent/diacritic normalization (Atlético → Atletico)
    - Team alias lookup (PSG → Paris Saint-Germain)
    - Fuzzy matching with configurable threshold
    - Fixture scoring with date proximity and league matching
    """
    
    def __init__(self, db_conn, api_client, fuzzy_threshold: float = 0.92, margin_threshold: float = 0.03):
        """
        Args:
            db_conn: psycopg2 connection
            api_client: ApiFootballClient instance
            fuzzy_threshold: Minimum score for fuzzy matches (default 0.92)
            margin_threshold: Required margin between top 2 candidates (default 0.03)
        """
        self.db = db_conn
        self.client = api_client
        self.fuzzy_threshold = fuzzy_threshold
        self.margin_threshold = margin_threshold
        self._alias_cache = {}
        self._load_alias_cache()
    
    def _load_alias_cache(self):
        """Load team aliases into memory."""
        cursor = self.db.cursor()
        cursor.execute("SELECT team_canonical, aliases FROM team_alias")
        for canonical, aliases in cursor.fetchall():
            self._alias_cache[canonical] = aliases
        cursor.close()
        logger.info(f"Loaded {len(self._alias_cache)} team aliases")
    
    @staticmethod
    def canonicalize(name: str) -> str:
        """
        Normalize team name: remove accents, lowercase, strip non-alphanumerics.
        
        Examples:
            Atlético Madrid → atleticomadrid
            Paris Saint-Germain → parissaintgermain
            Man Utd → manutd
        """
        # Remove accents/diacritics
        nfd = unicodedata.normalize('NFD', name)
        without_accents = ''.join(c for c in nfd if unicodedata.category(c) != 'Mn')
        
        # Lowercase and remove non-alphanumerics
        canonical = re.sub(r'[^a-z0-9]', '', without_accents.lower())
        return canonical
    
    def fuzzy_score(self, s1: str, s2: str) -> float:
        """
        Compute fuzzy similarity score (0.0 to 1.0).
        Uses rapidfuzz if available, else difflib.
        """
        if FUZZY_AVAILABLE:
            return fuzz.ratio(s1, s2) / 100.0
        else:
            return difflib.SequenceMatcher(None, s1, s2).ratio()
    
    def resolve_team_name(self, name: str, league_id: int, season: int) -> Optional[int]:
        """
        Resolve team name to API-Football team_id.
        
        Strategy:
        1. Exact canonical match against apif_teams_ref
        2. Alias lookup
        3. Fuzzy match with threshold
        
        Returns:
            team_id if found, else None
        """
        canonical = self.canonicalize(name)
        cursor = self.db.cursor()
        
        # 1. Exact canonical match
        cursor.execute("""
            SELECT team_id FROM apif_teams_ref
            WHERE league_id = %s AND season = %s AND team_canonical = %s
            LIMIT 1
        """, (league_id, season, canonical))
        
        result = cursor.fetchone()
        if result:
            cursor.close()
            return result[0]
        
        # 2. Alias lookup
        for alias_canonical, aliases in self._alias_cache.items():
            if canonical == alias_canonical or canonical in [self.canonicalize(a) for a in aliases]:
                cursor.execute("""
                    SELECT team_id FROM apif_teams_ref
                    WHERE league_id = %s AND season = %s AND team_canonical = %s
                    LIMIT 1
                """, (league_id, season, alias_canonical))
                
                result = cursor.fetchone()
                if result:
                    cursor.close()
                    return result[0]
        
        # 3. Fuzzy match
        cursor.execute("""
            SELECT team_id, team_canonical FROM apif_teams_ref
            WHERE league_id = %s AND season = %s
        """, (league_id, season))
        
        best_score = 0.0
        best_team_id = None
        
        for team_id, team_canonical in cursor.fetchall():
            score = self.fuzzy_score(canonical, team_canonical)
            if score > best_score:
                best_score = score
                best_team_id = team_id
        
        cursor.close()
        
        if best_score >= self.fuzzy_threshold:
            logger.debug(f"Fuzzy match: {name} → team_id {best_team_id} (score={best_score:.3f})")
            return best_team_id
        
        return None
    
    def match_fixture(
        self,
        league_id: int,
        season: int,
        kickoff_date: datetime,
        home_name: str,
        away_name: str
    ) -> Tuple[Optional[int], Dict]:
        """
        Match a fixture using team names and date.
        
        Returns:
            (fixture_id, diagnostic_dict) where diagnostic contains:
            - status: 'matched' | 'ambiguous_top2' | 'no_candidates' | 'error'
            - candidate_count: number of candidates found
            - top_score: score of best match
            - margin_vs_second: margin between top 2
            - message: human-readable diagnostic
        """
        diag = {
            'status': 'error',
            'candidate_count': 0,
            'top_score': 0.0,
            'margin_vs_second': 0.0,
            'message': ''
        }
        
        try:
            # Search fixtures in ±1 day window
            date_from = (kickoff_date - timedelta(days=1)).strftime('%Y-%m-%d')
            date_to = (kickoff_date + timedelta(days=1)).strftime('%Y-%m-%d')
            
            fixtures = self.client.search_fixtures_by_date_and_league(
                date=kickoff_date.strftime('%Y-%m-%d'),
                league_id=league_id,
                season=season
            )
            
            if not fixtures:
                diag['status'] = 'no_candidates'
                diag['message'] = f"No fixtures found for league {league_id} on {kickoff_date.strftime('%Y-%m-%d')}"
                return None, diag
            
            # Resolve team names to IDs
            home_id = self.resolve_team_name(home_name, league_id, season)
            away_id = self.resolve_team_name(away_name, league_id, season)
            
            if not home_id or not away_id:
                diag['status'] = 'error'
                diag['message'] = f"Could not resolve teams: {home_name} ({home_id}) vs {away_name} ({away_id})"
                return None, diag
            
            # Score candidates
            candidates = []
            for fixture in fixtures:
                fixture_home_id = fixture['teams']['home']['id']
                fixture_away_id = fixture['teams']['away']['id']
                fixture_date = datetime.fromisoformat(fixture['fixture']['date'].replace('Z', '+00:00'))
                
                # Exact team match bonus
                home_match = 1.0 if fixture_home_id == home_id else 0.0
                away_match = 1.0 if fixture_away_id == away_id else 0.0
                
                # Date proximity score (1.0 at exact date, decays by 0.5 per day)
                days_diff = abs((fixture_date.date() - kickoff_date.date()).days)
                date_score = max(0.0, 1.0 - (days_diff / 2.0))
                
                # Combined score (team matching is critical, date is tie-breaker)
                score = 0.4 * home_match + 0.4 * away_match + 0.2 * date_score
                
                if score > 0:
                    candidates.append({
                        'fixture_id': fixture['fixture']['id'],
                        'score': score,
                        'home_id': fixture_home_id,
                        'away_id': fixture_away_id,
                        'date': fixture_date
                    })
            
            candidates.sort(key=lambda x: x['score'], reverse=True)
            diag['candidate_count'] = len(candidates)
            
            if not candidates:
                diag['status'] = 'no_candidates'
                diag['message'] = f"No matching fixtures for teams {home_id} vs {away_id}"
                return None, diag
            
            # Check if top candidate is clear winner
            top = candidates[0]
            diag['top_score'] = top['score']
            
            if len(candidates) > 1:
                second = candidates[1]
                diag['margin_vs_second'] = top['score'] - second['score']
            else:
                diag['margin_vs_second'] = 1.0
            
            # Acceptance criteria: score ≥ 0.92 and margin ≥ 0.03
            if top['score'] >= self.fuzzy_threshold and diag['margin_vs_second'] >= self.margin_threshold:
                diag['status'] = 'matched'
                diag['message'] = f"Matched fixture {top['fixture_id']} (score={top['score']:.3f})"
                return top['fixture_id'], diag
            elif len(candidates) > 1 and diag['margin_vs_second'] < self.margin_threshold:
                diag['status'] = 'ambiguous_top2'
                diag['message'] = f"Ambiguous: top 2 scores too close ({top['score']:.3f} vs {second['score']:.3f})"
                return None, diag
            else:
                diag['status'] = 'no_candidates'
                diag['message'] = f"Top score {top['score']:.3f} below threshold {self.fuzzy_threshold}"
                return None, diag
        
        except Exception as e:
            diag['status'] = 'error'
            diag['message'] = str(e)
            logger.error(f"Error matching fixture: {e}")
            return None, diag
    
    def ensure_team_cache(self, league_id: int, season: int) -> int:
        """
        Populate apif_teams_ref for a league+season if not already cached.
        
        Returns:
            Number of teams cached
        """
        cursor = self.db.cursor()
        
        # Check if already cached
        cursor.execute("""
            SELECT COUNT(*) FROM apif_teams_ref
            WHERE league_id = %s AND season = %s
        """, (league_id, season))
        
        count = cursor.fetchone()[0]
        if count > 0:
            logger.debug(f"Team cache hit: {count} teams for league {league_id} season {season}")
            cursor.close()
            return count
        
        # Fetch teams from API-Football
        logger.info(f"Fetching teams for league {league_id} season {season}...")
        teams = self.client.get_teams(league_id, season)
        
        if not teams:
            logger.warning(f"No teams returned for league {league_id} season {season}")
            cursor.close()
            return 0
        
        # Insert into cache
        for team in teams:
            team_id = team['team']['id']
            team_name = team['team']['name']
            team_canonical = self.canonicalize(team_name)
            
            cursor.execute("""
                INSERT INTO apif_teams_ref (league_id, season, team_id, team_name, team_canonical)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (league_id, season, team_id) DO NOTHING
            """, (league_id, season, team_id, team_name, team_canonical))
        
        self.db.commit()
        cursor.close()
        
        logger.info(f"Cached {len(teams)} teams for league {league_id} season {season}")
        return len(teams)
    
    def record_success(self, match_id: int, fixture_id: int, diag: Dict):
        """Record successful fixture match."""
        cursor = self.db.cursor()
        cursor.execute("""
            INSERT INTO fixture_map_state (
                match_id, status, candidate_count, chosen_fixture_id,
                top_score, margin_vs_second, diagnostic_msg
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (match_id) DO UPDATE SET
                status = EXCLUDED.status,
                candidate_count = EXCLUDED.candidate_count,
                chosen_fixture_id = EXCLUDED.chosen_fixture_id,
                top_score = EXCLUDED.top_score,
                margin_vs_second = EXCLUDED.margin_vs_second,
                diagnostic_msg = EXCLUDED.diagnostic_msg,
                updated_at = NOW()
        """, (match_id, diag['status'], diag['candidate_count'], fixture_id,
              diag['top_score'], diag['margin_vs_second'], diag['message']))
        self.db.commit()
        cursor.close()
    
    def record_failure(self, match_id: int, diag: Dict):
        """Record failed fixture match attempt."""
        cursor = self.db.cursor()
        cursor.execute("""
            INSERT INTO fixture_map_state (
                match_id, status, candidate_count, chosen_fixture_id,
                top_score, margin_vs_second, diagnostic_msg
            ) VALUES (%s, %s, %s, NULL, %s, %s, %s)
            ON CONFLICT (match_id) DO UPDATE SET
                status = EXCLUDED.status,
                candidate_count = EXCLUDED.candidate_count,
                top_score = EXCLUDED.top_score,
                margin_vs_second = EXCLUDED.margin_vs_second,
                diagnostic_msg = EXCLUDED.diagnostic_msg,
                updated_at = NOW()
        """, (match_id, diag['status'], diag['candidate_count'],
              diag['top_score'], diag['margin_vs_second'], diag['message']))
        self.db.commit()
        cursor.close()
    
    def add_team_aliases(self, team_canonical: str, aliases: List[str]):
        """Add or update team aliases."""
        cursor = self.db.cursor()
        cursor.execute("""
            INSERT INTO team_alias (team_canonical, aliases)
            VALUES (%s, %s)
            ON CONFLICT (team_canonical) DO UPDATE SET
                aliases = EXCLUDED.aliases
        """, (team_canonical, aliases))
        self.db.commit()
        cursor.close()
        
        # Refresh cache
        self._alias_cache[team_canonical] = aliases
        logger.info(f"Added/updated aliases for {team_canonical}: {aliases}")
