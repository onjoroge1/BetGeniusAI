"""
API-Football Fixture ID Resolver
Automatically resolves and links fixtures to API-Football IDs using a 3-pass hybrid approach:
1. Direct table join on existing mappings
2. Cached fallback lookup table
3. API-Football search by team/date with fuzzy matching

Confidence scoring and audit trail for manual review queue (<90% confidence)
"""

import os
import psycopg2
import requests
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, List, Tuple
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)


class FixtureIDResolver:
    def __init__(self):
        self.db_url = os.getenv("DATABASE_URL")
        self.api_key = os.getenv("RAPIDAPI_KEY")
        self.api_base = "https://api-football-v1.p.rapidapi.com/v3"
        self.headers = {
            "X-RapidAPI-Key": self.api_key,
            "X-RapidAPI-Host": "api-football-v1.p.rapidapi.com"
        }
        
        # Manual override mappings for problematic team names
        # Format: (our_name, api_football_name) pairs for exact matching
        self.manual_overrides = self._load_manual_overrides()
    
    def _load_manual_overrides(self) -> Dict[str, str]:
        """
        Load manual team name overrides from database
        Returns: dict of {our_team_name: api_football_team_name}
        """
        try:
            with psycopg2.connect(self.db_url) as conn:
                cursor = conn.cursor()
                
                # Create manual overrides table if it doesn't exist
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS fixture_id_manual_overrides (
                        override_id SERIAL PRIMARY KEY,
                        our_team_name VARCHAR(255) NOT NULL UNIQUE,
                        api_football_team_name VARCHAR(255) NOT NULL,
                        notes TEXT,
                        created_at TIMESTAMPTZ DEFAULT NOW(),
                        last_used_at TIMESTAMPTZ,
                        use_count INTEGER DEFAULT 0
                    )
                """)
                
                # Load overrides into memory
                cursor.execute("""
                    SELECT our_team_name, api_football_team_name 
                    FROM fixture_id_manual_overrides
                """)
                
                overrides = {}
                for our_name, api_name in cursor.fetchall():
                    overrides[our_name.lower().strip()] = api_name
                
                conn.commit()
                logger.info(f"Loaded {len(overrides)} manual team name overrides")
                return overrides
                
        except Exception as e:
            logger.warning(f"Failed to load manual overrides: {e}")
            return {}
    
    def check_manual_override(self, team_name: str) -> Optional[str]:
        """Check if team has a manual override mapping"""
        key = team_name.lower().strip()
        return self.manual_overrides.get(key)
        
    def normalize_team_name(self, name: str) -> str:
        """
        Enhanced normalization for team names with multi-language support
        Handles: German prefixes (1., FSV, etc.), accents, abbreviations
        """
        if not name:
            return ""
        
        # Convert to lowercase and strip
        normalized = name.lower().strip()
        
        # Remove common prefixes (expanded for German, Spanish, Italian, etc.)
        prefixes = [
            '1. ', '1.', 'fc ', 'as ', 'ac ', 'sc ', 'rc ', 'cf ', 'cd ', 
            'afc ', 'bfc ', 'fsv ', 'sv ', 'vfb ', 'vfl ', 'tsg ', 'ssc ',
            'us ', 'ss ', 'uc ', 'real ', 'athletic ', 'club ', 'union ',
            'racing ', 'olympique ', 'sporting ', 'ajax ', 'psv '
        ]
        
        for prefix in prefixes:
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix):].strip()
                break  # Only remove first prefix
        
        # Remove common suffixes
        suffixes = [' fc', ' sc', ' united', ' city', ' town', ' rovers', ' wanderers']
        for suffix in suffixes:
            if normalized.endswith(suffix):
                normalized = normalized[:-len(suffix)].strip()
                break
        
        # Handle accents and special characters
        accent_map = {
            'á': 'a', 'à': 'a', 'ä': 'a', 'â': 'a', 'ã': 'a',
            'é': 'e', 'è': 'e', 'ë': 'e', 'ê': 'e',
            'í': 'i', 'ì': 'i', 'ï': 'i', 'î': 'i',
            'ó': 'o', 'ò': 'o', 'ö': 'o', 'ô': 'o', 'õ': 'o', 'ø': 'o',
            'ú': 'u', 'ù': 'u', 'ü': 'u', 'û': 'u',
            'ñ': 'n', 'ç': 'c', 'ß': 'ss', 'æ': 'ae', 'œ': 'oe'
        }
        
        for accented, plain in accent_map.items():
            normalized = normalized.replace(accented, plain)
        
        # Remove punctuation and extra spaces
        normalized = normalized.replace('.', '').replace('-', ' ').replace("'", '')
        normalized = ' '.join(normalized.split())  # Normalize whitespace
        
        return normalized
    
    def calculate_confidence(self, home_similarity: float, away_similarity: float, 
                           date_diff_hours: float, league_match: bool) -> Tuple[float, str]:
        """
        Calculate confidence score (0-100) for a fixture match
        Returns: (confidence_score, reason)
        """
        # Base score from team name similarity (70% weight)
        team_score = (home_similarity + away_similarity) / 2 * 70
        
        # Date proximity score (20% weight)
        # Perfect match = 20 points, decay over 48 hours
        if date_diff_hours <= 1:
            date_score = 20
        elif date_diff_hours <= 6:
            date_score = 18
        elif date_diff_hours <= 24:
            date_score = 15
        elif date_diff_hours <= 48:
            date_score = 10
        else:
            date_score = 0
            
        # League match bonus (10% weight)
        league_score = 10 if league_match else 0
        
        confidence = team_score + date_score + league_score
        
        # Build reason string
        reasons = []
        if home_similarity >= 0.95 and away_similarity >= 0.95:
            reasons.append("exact_team_match")
        elif home_similarity >= 0.80 and away_similarity >= 0.80:
            reasons.append("strong_team_match")
        else:
            reasons.append("fuzzy_team_match")
            
        if date_diff_hours <= 1:
            reasons.append("exact_date_match")
        elif date_diff_hours <= 24:
            reasons.append("close_date_match")
        else:
            reasons.append("distant_date_match")
            
        if league_match:
            reasons.append("league_confirmed")
            
        return min(confidence, 100.0), ",".join(reasons)
    
    def similarity_score(self, str1: str, str2: str) -> float:
        """
        Enhanced similarity scoring with multi-pass matching:
        1. Check manual overrides (100% confidence)
        2. Exact match after normalization (100% confidence)
        3. Fuzzy match with SequenceMatcher
        """
        # Check manual overrides first
        override1 = self.check_manual_override(str1)
        override2 = self.check_manual_override(str2)
        
        if override1 and override2:
            # Both have overrides - compare overrides
            return 1.0 if override1.lower() == override2.lower() else 0.0
        elif override1:
            # str1 has override - compare with normalized str2
            norm2 = self.normalize_team_name(str2)
            return 1.0 if override1.lower() == norm2 else 0.8  # Partial credit
        elif override2:
            # str2 has override - compare with normalized str1
            norm1 = self.normalize_team_name(str1)
            return 1.0 if norm1 == override2.lower() else 0.8  # Partial credit
        
        # No overrides - use enhanced normalization + fuzzy match
        norm1 = self.normalize_team_name(str1)
        norm2 = self.normalize_team_name(str2)
        
        # Exact match after normalization
        if norm1 == norm2:
            return 1.0
        
        # Check if one is substring of the other (common for abbreviated names)
        if norm1 in norm2 or norm2 in norm1:
            return 0.95
        
        # Fuzzy match with SequenceMatcher
        return SequenceMatcher(None, norm1, norm2).ratio()
    
    def pass1_table_join(self) -> int:
        """
        Pass 1: Insert upcoming fixtures into matches table if they have known API-Football IDs
        This enables the live_data_collector to find them via its existing JOIN query
        Returns: number of fixtures synced to matches table
        """
        logger.info("🔍 Pass 1: Syncing fixtures to matches table...")
        
        with psycopg2.connect(self.db_url) as conn:
            cursor = conn.cursor()
            
            # For upcoming fixtures that exist in cache with high confidence,
            # insert them into matches table so live_data_collector can find them
            cursor.execute("""
                INSERT INTO matches (
                    match_id, league_id, season, match_date_utc,
                    home_team_id, away_team_id, api_football_fixture_id
                )
                SELECT DISTINCT
                    f.match_id,
                    f.league_id,
                    EXTRACT(YEAR FROM f.kickoff_at) as season,
                    f.kickoff_at AT TIME ZONE 'UTC' as match_date_utc,
                    f.home_team_id,
                    f.away_team_id,
                    c.api_football_fixture_id
                FROM fixtures f
                JOIN fixture_id_cache c 
                  ON f.home_team = c.home_team 
                  AND f.away_team = c.away_team
                  AND DATE(f.kickoff_at) = c.kickoff_date
                WHERE f.kickoff_at > NOW() - INTERVAL '1 day'
                  AND f.kickoff_at < NOW() + INTERVAL '7 days'
                  AND c.confidence >= 80
                  AND c.api_football_fixture_id IS NOT NULL
                ON CONFLICT (match_id) 
                DO UPDATE SET 
                    api_football_fixture_id = EXCLUDED.api_football_fixture_id
                RETURNING match_id
            """)
            
            synced = cursor.fetchall()
            conn.commit()
            
            count = len(synced)
            logger.info(f"✅ Pass 1: Synced {count} fixtures to matches table")
            return count
    
    def pass2_cache_lookup(self) -> int:
        """
        Pass 2: Populate matches table from cache for recently added fixtures
        Returns: number of fixtures synced
        """
        logger.info("🔍 Pass 2: Cache-based sync to matches table...")
        
        with psycopg2.connect(self.db_url) as conn:
            cursor = conn.cursor()
            
            # For upcoming fixtures not yet in matches table, try to populate from cache
            cursor.execute("""
                INSERT INTO matches (
                    match_id, league_id, season, match_date_utc,
                    home_team_id, away_team_id, api_football_fixture_id
                )
                SELECT DISTINCT
                    f.match_id,
                    f.league_id,
                    EXTRACT(YEAR FROM f.kickoff_at) as season,
                    f.kickoff_at AT TIME ZONE 'UTC' as match_date_utc,
                    f.home_team_id,
                    f.away_team_id,
                    c.api_football_fixture_id
                FROM fixtures f
                JOIN fixture_id_cache c 
                  ON f.home_team = c.home_team 
                  AND f.away_team = c.away_team
                  AND DATE(f.kickoff_at) = c.kickoff_date
                LEFT JOIN matches m ON f.match_id = m.match_id
                WHERE m.match_id IS NULL  -- Not yet in matches table
                  AND f.kickoff_at > NOW() - INTERVAL '1 day'
                  AND f.kickoff_at < NOW() + INTERVAL '7 days'
                  AND c.confidence >= 80
                  AND c.api_football_fixture_id IS NOT NULL
                ON CONFLICT (match_id) DO NOTHING
                RETURNING match_id
            """)
            
            synced = cursor.fetchall()
            
            # Update cache usage stats
            if synced:
                cursor.execute("""
                    UPDATE fixture_id_cache
                    SET last_used_at = NOW(), use_count = use_count + 1
                    WHERE api_football_fixture_id IN (
                        SELECT api_football_fixture_id FROM matches
                        WHERE match_id = ANY(%s)
                    )
                """, ([r[0] for r in synced],))
            
            conn.commit()
            
            count = len(synced)
            logger.info(f"✅ Pass 2: Synced {count} fixtures from cache")
            return count
    
    def pass3_api_search(self, limit: int = 20) -> int:
        """
        Pass 3: API-Football search by team/date with fuzzy matching
        Returns: number of fixtures resolved
        """
        logger.info("🔍 Pass 3: API-Football search...")
        
        with psycopg2.connect(self.db_url) as conn:
            cursor = conn.cursor()
            
            # Get fixtures that aren't yet in matches table (unresolved)
            cursor.execute("""
                SELECT f.match_id, f.home_team, f.away_team, f.league_id, f.kickoff_at
                FROM fixtures f
                LEFT JOIN matches m ON f.match_id = m.match_id
                WHERE m.match_id IS NULL  -- Not yet in matches table
                  AND f.kickoff_at BETWEEN NOW() - INTERVAL '3 days' AND NOW() + INTERVAL '7 days'
                  AND f.status = 'scheduled'
                ORDER BY f.kickoff_at ASC
                LIMIT %s
            """, (limit,))
            
            unresolved = cursor.fetchall()
            
            if not unresolved:
                logger.info("✅ Pass 3: No unresolved fixtures to search")
                return 0
            
            logger.info(f"🔍 Pass 3: Searching for {len(unresolved)} fixtures...")
            resolved_count = 0
            
            for match_id, home_team, away_team, league_id, kickoff_at in unresolved:
                try:
                    # Search API-Football for this fixture
                    # Use date range ±2 days to catch timezone differences
                    search_date = kickoff_at.strftime("%Y-%m-%d")
                    
                    # For now, skip league filtering since we don't have a leagues table
                    # We'll rely on team name + date matching
                    api_league_id = None
                    
                    # Build API query
                    params = {"date": search_date}
                    if api_league_id:
                        params["league"] = api_league_id
                        params["season"] = kickoff_at.year
                    
                    response = requests.get(
                        f"{self.api_base}/fixtures",
                        headers=self.headers,
                        params=params,
                        timeout=10
                    )
                    
                    if response.status_code != 200:
                        logger.warning(f"❌ API request failed for {match_id}: {response.status_code}")
                        continue
                    
                    data = response.json()
                    fixtures = data.get("response", [])
                    
                    if not fixtures:
                        logger.debug(f"No API-Football fixtures found for {home_team} vs {away_team}")
                        continue
                    
                    # Find best match using fuzzy matching
                    best_match = None
                    best_confidence = 0
                    best_reason = ""
                    
                    for fixture in fixtures:
                        api_home = fixture["teams"]["home"]["name"]
                        api_away = fixture["teams"]["away"]["name"]
                        api_date = datetime.fromisoformat(fixture["fixture"]["date"].replace("Z", "+00:00"))
                        api_league = fixture["league"]["id"]
                        
                        # Calculate similarities
                        home_sim = self.similarity_score(home_team, api_home)
                        away_sim = self.similarity_score(away_team, api_away)
                        date_diff_hours = abs((api_date - kickoff_at).total_seconds()) / 3600
                        league_match = (api_league_id == api_league) if api_league_id else False
                        
                        # Calculate confidence
                        confidence, reason = self.calculate_confidence(
                            home_sim, away_sim, date_diff_hours, league_match
                        )
                        
                        if confidence > best_confidence:
                            best_confidence = confidence
                            best_match = fixture["fixture"]["id"]
                            best_reason = reason
                    
                    if best_match and best_confidence >= 70:  # Minimum 70% confidence
                        # Get team IDs for the fixture
                        cursor.execute("""
                            SELECT home_team_id, away_team_id
                            FROM fixtures
                            WHERE match_id = %s
                        """, (match_id,))
                        team_ids = cursor.fetchone()
                        home_team_id = team_ids[0] if team_ids else None
                        away_team_id = team_ids[1] if team_ids else None
                        
                        # Insert into matches table so live_data_collector can find it
                        cursor.execute("""
                            INSERT INTO matches (
                                match_id, league_id, season, match_date_utc,
                                home_team_id, away_team_id, api_football_fixture_id
                            )
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (match_id) 
                            DO UPDATE SET api_football_fixture_id = EXCLUDED.api_football_fixture_id
                        """, (match_id, league_id, kickoff_at.year, 
                              kickoff_at.astimezone(timezone.utc).replace(tzinfo=None),
                              home_team_id, away_team_id, best_match))
                        
                        # Add to cache for future use
                        cursor.execute("""
                            INSERT INTO fixture_id_cache 
                            (home_team, away_team, league_id, kickoff_date, 
                             api_football_fixture_id, confidence, confidence_reason)
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (home_team, away_team, kickoff_date) 
                            DO UPDATE SET 
                                api_football_fixture_id = EXCLUDED.api_football_fixture_id,
                                confidence = EXCLUDED.confidence,
                                confidence_reason = EXCLUDED.confidence_reason,
                                last_used_at = NOW()
                        """, (home_team, away_team, league_id, kickoff_at.date(), 
                              best_match, best_confidence, best_reason))
                        
                        # If confidence < 90%, add to manual review queue
                        if best_confidence < 90:
                            cursor.execute("""
                                INSERT INTO fixture_resolver_queue 
                                (match_id, home_team, away_team, kickoff_at, 
                                 suggested_api_football_id, confidence, confidence_reason, 
                                 status, created_at)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending_review', NOW())
                                ON CONFLICT (match_id) DO NOTHING
                            """, (match_id, home_team, away_team, kickoff_at, 
                                  best_match, best_confidence, best_reason))
                        
                        conn.commit()
                        resolved_count += 1
                        logger.info(f"✅ Resolved {match_id}: {home_team} vs {away_team} "
                                  f"→ API-Football ID {best_match} (confidence: {best_confidence:.1f}%)")
                        
                except Exception as e:
                    logger.error(f"❌ Error resolving {match_id}: {str(e)}")
                    conn.rollback()
                    continue
            
            logger.info(f"✅ Pass 3: Resolved {resolved_count} fixtures via API search")
            return resolved_count
    
    def resolve_all(self, api_search_limit: int = 20) -> Dict[str, int]:
        """
        Run all 3 passes of the resolver
        Returns: dict with counts from each pass
        """
        logger.info("🚀 Starting 3-pass fixture ID resolver...")
        
        # Create necessary tables first
        with psycopg2.connect(self.db_url) as conn:
            cursor = conn.cursor()
            
            # Create cache table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS fixture_id_cache (
                    cache_id SERIAL PRIMARY KEY,
                    home_team VARCHAR(255),
                    away_team VARCHAR(255),
                    league_id INTEGER,
                    kickoff_date DATE,
                    api_football_fixture_id INTEGER,
                    confidence FLOAT,
                    confidence_reason TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    last_used_at TIMESTAMPTZ DEFAULT NOW(),
                    use_count INTEGER DEFAULT 1,
                    UNIQUE(home_team, away_team, kickoff_date)
                )
            """)
            
            # Create manual review queue table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS fixture_resolver_queue (
                    queue_id SERIAL PRIMARY KEY,
                    match_id VARCHAR(255) UNIQUE,
                    home_team VARCHAR(255),
                    away_team VARCHAR(255),
                    kickoff_at TIMESTAMPTZ,
                    suggested_api_football_id INTEGER,
                    confidence FLOAT,
                    confidence_reason TEXT,
                    status VARCHAR(50) DEFAULT 'pending_review',
                    reviewed_at TIMESTAMPTZ,
                    reviewed_by VARCHAR(255),
                    final_api_football_id INTEGER,
                    notes TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            conn.commit()
        
        # Run 3-pass resolution
        pass1 = self.pass1_table_join()
        pass2 = self.pass2_cache_lookup()
        pass3 = self.pass3_api_search(limit=api_search_limit)
        
        total = pass1 + pass2 + pass3
        
        results = {
            "pass1_table_join": pass1,
            "pass2_cache_lookup": pass2,
            "pass3_api_search": pass3,
            "total_resolved": total
        }
        
        logger.info(f"✅ Resolver complete: {total} fixtures resolved "
                   f"(Pass1: {pass1}, Pass2: {pass2}, Pass3: {pass3})")
        
        return results
    
    def add_manual_override(self, our_team_name: str, api_football_team_name: str, notes: str = "") -> bool:
        """
        Add a manual team name override
        Returns: True if added successfully, False if already exists
        """
        try:
            with psycopg2.connect(self.db_url) as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    INSERT INTO fixture_id_manual_overrides 
                    (our_team_name, api_football_team_name, notes)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (our_team_name) DO UPDATE
                    SET api_football_team_name = EXCLUDED.api_football_team_name,
                        notes = EXCLUDED.notes
                    RETURNING override_id
                """, (our_team_name, api_football_team_name, notes))
                
                result = cursor.fetchone()
                conn.commit()
                
                # Reload overrides
                self.manual_overrides = self._load_manual_overrides()
                
                logger.info(f"✅ Added manual override: {our_team_name} → {api_football_team_name}")
                return True
                
        except Exception as e:
            logger.error(f"❌ Failed to add manual override: {e}")
            return False
    
    def get_queue_stats(self) -> Dict:
        """Get statistics on manual review queue"""
        with psycopg2.connect(self.db_url) as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT 
                    COUNT(*) FILTER (WHERE status = 'pending_review') as pending,
                    COUNT(*) FILTER (WHERE status = 'approved') as approved,
                    COUNT(*) FILTER (WHERE status = 'rejected') as rejected,
                    COUNT(*) as total,
                    AVG(confidence) FILTER (WHERE status = 'pending_review') as avg_confidence_pending
                FROM fixture_resolver_queue
            """)
            
            row = cursor.fetchone()
            
            return {
                "pending_review": row[0] or 0,
                "approved": row[1] or 0,
                "rejected": row[2] or 0,
                "total": row[3] or 0,
                "avg_confidence_pending": round(row[4], 2) if row[4] else 0
            }
    
    def get_override_stats(self) -> Dict:
        """Get statistics on manual overrides"""
        with psycopg2.connect(self.db_url) as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_overrides,
                    COUNT(*) FILTER (WHERE use_count > 0) as used_overrides,
                    SUM(use_count) as total_uses,
                    MAX(last_used_at) as last_used
                FROM fixture_id_manual_overrides
            """)
            
            row = cursor.fetchone()
            
            return {
                "total_overrides": row[0] or 0,
                "used_overrides": row[1] or 0,
                "total_uses": row[2] or 0,
                "last_used": row[3]
            }


if __name__ == "__main__":
    # Test the resolver
    logging.basicConfig(level=logging.INFO)
    resolver = FixtureIDResolver()
    results = resolver.resolve_all(api_search_limit=10)
    print("\n📊 Resolver Results:")
    for key, value in results.items():
        print(f"  {key}: {value}")
    
    queue_stats = resolver.get_queue_stats()
    print("\n📋 Manual Review Queue:")
    for key, value in queue_stats.items():
        print(f"  {key}: {value}")
