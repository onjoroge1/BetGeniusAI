"""
Team Linkage Service
Links fixtures to teams table by matching team names using fuzzy matching.
Populates home_team_id and away_team_id foreign keys.
"""

import os
import psycopg2
from typing import Optional, Dict, List, Tuple
from difflib import SequenceMatcher
import unicodedata
import re
import logging

logger = logging.getLogger(__name__)

class TeamLinkageService:
    """Service for linking fixtures to teams using intelligent name matching"""
    
    def __init__(self):
        self.db_url = os.environ.get('DATABASE_URL')
        
    def normalize_team_name(self, name: str) -> str:
        """
        Normalize team name for fuzzy matching:
        - Remove accents/diacritics
        - Strip ordinal prefixes (1., 2., etc.)
        - Remove common club tokens in isolation
        - Lowercase and clean punctuation
        """
        if not name or name == 'TBD':
            return name.lower() if name else ''
        
        s = name.strip()
        
        # Remove accents (e.g., München → Munchen)
        s = ''.join(c for c in unicodedata.normalize('NFD', s) 
                   if unicodedata.category(c) != 'Mn')
        
        # Strip ordinal prefixes like "1. ", "2. "
        s = re.sub(r'^\d+\.\s*', '', s)
        
        # Remove years (e.g., "1899", "2004")
        s = re.sub(r'\b(18\d{2}|19\d{2}|20\d{2})\b', '', s)
        
        # Normalize whitespace and punctuation
        s = re.sub(r'[.,()]+', '', s)
        s = re.sub(r'\s+', ' ', s)
        
        return s.strip().lower()
    
    def fuzzy_match_score(self, name1: str, name2: str) -> float:
        """
        Calculate fuzzy match score between two team names.
        Returns: 0.0 (no match) to 1.0 (exact match)
        
        Uses multiple strategies:
        1. Exact match (after normalization)
        2. Substring containment
        3. Sequence similarity
        """
        norm1 = self.normalize_team_name(name1)
        norm2 = self.normalize_team_name(name2)
        
        if not norm1 or not norm2:
            return 0.0
        
        # Exact match
        if norm1 == norm2:
            return 1.0
        
        # Substring match (e.g., "bayern" in "fc bayern munich")
        if norm1 in norm2 or norm2 in norm1:
            shorter = min(len(norm1), len(norm2))
            longer = max(len(norm1), len(norm2))
            return 0.85 + (shorter / longer) * 0.15  # 0.85-1.0
        
        # Token overlap (split by spaces)
        tokens1 = set(norm1.split())
        tokens2 = set(norm2.split())
        
        # Remove common noise words
        noise = {'fc', 'ac', 'sc', 'cf', 'club', 'real', 'sporting', 'athletic', 'united'}
        tokens1 = tokens1 - noise
        tokens2 = tokens2 - noise
        
        if tokens1 and tokens2:
            overlap = len(tokens1 & tokens2)
            total = len(tokens1 | tokens2)
            token_score = overlap / total if total > 0 else 0
            
            if token_score > 0.5:
                return 0.7 + token_score * 0.3  # 0.7-1.0
        
        # Sequence similarity (Levenshtein-like)
        seq_score = SequenceMatcher(None, norm1, norm2).ratio()
        
        return seq_score
    
    def find_best_team_match(self, team_name: str, league_id: Optional[int] = None) -> Optional[Dict]:
        """
        Find best matching team in teams table.
        
        Returns: {team_id, name, logo_url, match_score} or None
        """
        if not team_name or team_name == 'TBD':
            return None
        
        try:
            conn = psycopg2.connect(self.db_url)
            cursor = conn.cursor()
            
            # Get all teams (optionally filtered by league)
            if league_id:
                # Get teams that have played in this league
                query = """
                    SELECT DISTINCT t.team_id, t.name, t.logo_url, t.country
                    FROM teams t
                    LEFT JOIN fixtures f ON (f.home_team_id = t.team_id OR f.away_team_id = t.team_id)
                    WHERE f.league_id = %s OR f.league_id IS NULL
                """
                cursor.execute(query, (league_id,))
            else:
                query = "SELECT team_id, name, logo_url, country FROM teams"
                cursor.execute(query)
            
            teams = cursor.fetchall()
            
            # Calculate match scores
            best_match = None
            best_score = 0.0
            
            for team_id, name, logo_url, country in teams:
                score = self.fuzzy_match_score(team_name, name)
                
                if score > best_score:
                    best_score = score
                    best_match = {
                        'team_id': team_id,
                        'name': name,
                        'logo_url': logo_url,
                        'country': country,
                        'match_score': score
                    }
            
            cursor.close()
            conn.close()
            
            # Only return if score is above threshold
            if best_match and best_match['match_score'] >= 0.7:
                return best_match
            
            return None
            
        except Exception as e:
            logger.error(f"Error finding team match for '{team_name}': {e}", exc_info=True)
            return None
    
    def create_team(self, team_name: str, league_id: Optional[int] = None) -> Optional[int]:
        """
        Create new team in teams table.
        Logo will be enriched later by background job.
        
        Returns: team_id or None
        """
        try:
            conn = psycopg2.connect(self.db_url)
            cursor = conn.cursor()
            
            # Generate slug from name
            slug = re.sub(r'[^a-z0-9]+', '-', team_name.lower()).strip('-')
            
            cursor.execute("""
                INSERT INTO teams (name, slug, created_at, updated_at)
                VALUES (%s, %s, NOW(), NOW())
                RETURNING team_id
            """, (team_name, slug))
            
            team_id = cursor.fetchone()[0]
            conn.commit()
            
            logger.info(f"✅ Created new team: '{team_name}' (ID: {team_id})")
            
            cursor.close()
            conn.close()
            
            return team_id
            
        except Exception as e:
            logger.error(f"Error creating team '{team_name}': {e}", exc_info=True)
            return None
    
    def link_fixture(self, match_id: int, home_team: str, away_team: str, league_id: Optional[int] = None) -> Dict:
        """
        Link a single fixture to teams table.
        
        Returns: {
            'success': bool,
            'home_team_id': int or None,
            'away_team_id': int or None,
            'home_match_score': float,
            'away_match_score': float,
            'home_created': bool,
            'away_created': bool
        }
        """
        result = {
            'success': False,
            'home_team_id': None,
            'away_team_id': None,
            'home_match_score': 0.0,
            'away_match_score': 0.0,
            'home_created': False,
            'away_created': False
        }
        
        # Skip TBD fixtures
        if home_team == 'TBD' or away_team == 'TBD':
            logger.info(f"⏭️  Skipping TBD fixture {match_id}")
            return result
        
        try:
            # Find or create home team
            home_match = self.find_best_team_match(home_team, league_id)
            if home_match:
                result['home_team_id'] = home_match['team_id']
                result['home_match_score'] = home_match['match_score']
                logger.info(f"✅ Home team matched: '{home_team}' → '{home_match['name']}' (score: {home_match['match_score']:.2f})")
            else:
                # Create new team
                result['home_team_id'] = self.create_team(home_team, league_id)
                result['home_created'] = True
                logger.info(f"➕ Home team created: '{home_team}'")
            
            # Find or create away team
            away_match = self.find_best_team_match(away_team, league_id)
            if away_match:
                result['away_team_id'] = away_match['team_id']
                result['away_match_score'] = away_match['match_score']
                logger.info(f"✅ Away team matched: '{away_team}' → '{away_match['name']}' (score: {away_match['match_score']:.2f})")
            else:
                # Create new team
                result['away_team_id'] = self.create_team(away_team, league_id)
                result['away_created'] = True
                logger.info(f"➕ Away team created: '{away_team}'")
            
            # Update fixture with team_ids
            if result['home_team_id'] and result['away_team_id']:
                conn = psycopg2.connect(self.db_url)
                cursor = conn.cursor()
                
                cursor.execute("""
                    UPDATE fixtures
                    SET home_team_id = %s, away_team_id = %s, updated_at = NOW()
                    WHERE match_id = %s
                """, (result['home_team_id'], result['away_team_id'], match_id))
                
                conn.commit()
                cursor.close()
                conn.close()
                
                result['success'] = True
                logger.info(f"🔗 Linked fixture {match_id}: home_team_id={result['home_team_id']}, away_team_id={result['away_team_id']}")
            
            return result
            
        except Exception as e:
            logger.error(f"Error linking fixture {match_id}: {e}", exc_info=True)
            return result
    
    def backfill_all_fixtures(self, batch_size: int = 100, dry_run: bool = False) -> Dict:
        """
        Backfill team_ids for all fixtures with missing linkage.
        
        Args:
            batch_size: Number of fixtures to process per batch
            dry_run: If True, only log what would be done without updating DB
        
        Returns: {
            'total_processed': int,
            'total_linked': int,
            'total_skipped': int,
            'teams_created': int,
            'avg_home_score': float,
            'avg_away_score': float
        }
        """
        stats = {
            'total_processed': 0,
            'total_linked': 0,
            'total_skipped': 0,
            'teams_created': 0,
            'avg_home_score': 0.0,
            'avg_away_score': 0.0
        }
        
        try:
            conn = psycopg2.connect(self.db_url)
            cursor = conn.cursor()
            
            # Get fixtures with missing team_ids
            cursor.execute("""
                SELECT match_id, home_team, away_team, league_id
                FROM fixtures
                WHERE home_team_id IS NULL OR away_team_id IS NULL
                ORDER BY kickoff_at DESC
            """)
            
            fixtures = cursor.fetchall()
            total = len(fixtures)
            
            logger.info(f"🔍 Found {total} fixtures with missing team_ids")
            
            if dry_run:
                logger.info(f"🔬 DRY RUN MODE - No updates will be made")
            
            home_scores = []
            away_scores = []
            
            for i, (match_id, home_team, away_team, league_id) in enumerate(fixtures, 1):
                if not dry_run:
                    result = self.link_fixture(match_id, home_team, away_team, league_id)
                    
                    if result['success']:
                        stats['total_linked'] += 1
                        home_scores.append(result['home_match_score'])
                        away_scores.append(result['away_match_score'])
                        
                        if result['home_created']:
                            stats['teams_created'] += 1
                        if result['away_created']:
                            stats['teams_created'] += 1
                    else:
                        stats['total_skipped'] += 1
                else:
                    logger.info(f"[{i}/{total}] Would process: {home_team} vs {away_team}")
                
                stats['total_processed'] += 1
                
                # Progress log every batch_size
                if i % batch_size == 0:
                    logger.info(f"📊 Progress: {i}/{total} processed ({i/total*100:.1f}%)")
            
            # Calculate averages
            if home_scores:
                stats['avg_home_score'] = sum(home_scores) / len(home_scores)
            if away_scores:
                stats['avg_away_score'] = sum(away_scores) / len(away_scores)
            
            cursor.close()
            conn.close()
            
            logger.info(f"✅ BACKFILL COMPLETE: {stats['total_linked']}/{stats['total_processed']} linked, {stats['teams_created']} teams created")
            
            return stats
            
        except Exception as e:
            logger.error(f"Error in backfill: {e}", exc_info=True)
            return stats


def link_fixtures_to_teams(batch_size: int = 100, dry_run: bool = False) -> Dict:
    """
    Convenience function to run team linkage backfill.
    
    Usage:
        stats = link_fixtures_to_teams(batch_size=50, dry_run=True)  # Test first
        stats = link_fixtures_to_teams(batch_size=100, dry_run=False)  # Real run
    """
    service = TeamLinkageService()
    return service.backfill_all_fixtures(batch_size=batch_size, dry_run=dry_run)
