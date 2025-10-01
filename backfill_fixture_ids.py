#!/usr/bin/env python3
"""
Backfill fixture_id for training_matches using enhanced TeamMatcher.
Uses deterministic + fuzzy team matching with API-Football.
"""

import os
import psycopg2
from datetime import datetime
from utils.api_football_client import ApiFootballClient
from utils.team_matcher import TeamMatcher
import logging
import time

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv('DATABASE_URL')

LEAGUE_MAPPING = {
    2: {'api_football_id': 2, 'name': 'UEFA Champions League', 'season_logic': 'year_start'},
    3: {'api_football_id': 3, 'name': 'UEFA Europa League', 'season_logic': 'year_start'},
    39: {'api_football_id': 39, 'name': 'Premier League', 'season_logic': 'year_start'},
    40: {'api_football_id': 40, 'name': 'Championship', 'season_logic': 'year_start'},
    78: {'api_football_id': 78, 'name': 'Bundesliga', 'season_logic': 'year_start'},
    135: {'api_football_id': 135, 'name': 'Serie A', 'season_logic': 'year_start'},
    140: {'api_football_id': 140, 'name': 'La Liga', 'season_logic': 'year_start'},
    141: {'api_football_id': 141, 'name': 'LaLiga 2', 'season_logic': 'year_start'},
    61: {'api_football_id': 61, 'name': 'Ligue 1', 'season_logic': 'year_start'},
}


def get_season_from_date(match_date: datetime, season_logic: str = 'year_start') -> int:
    """
    Determine season year from match date.
    
    For European football:
    - Matches Aug-Dec belong to season starting that year
    - Matches Jan-Jul belong to season starting previous year
    
    Example: 
    - 2024-09-15 → season 2024
    - 2025-02-10 → season 2024
    """
    if season_logic == 'year_start':
        if match_date.month >= 8:
            return match_date.year
        else:
            return match_date.year - 1
    
    return match_date.year


def seed_team_cache(matcher: TeamMatcher):
    """
    Pre-seed team cache for all leagues/seasons in LEAGUE_MAPPING.
    This reduces API calls during backfill and improves matching accuracy.
    """
    logger.info("\n" + "="*80)
    logger.info("SEEDING TEAM CACHE")
    logger.info("="*80)
    
    # Get unique league/season combinations from training_matches
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT DISTINCT league_id, EXTRACT(YEAR FROM match_date) as year
        FROM training_matches
        WHERE fixture_id IS NULL
        AND match_date IS NOT NULL
        AND league_id IN (2, 3, 39, 40, 78, 135, 140, 141, 61)
        ORDER BY year DESC, league_id
    """)
    
    combinations = cursor.fetchall()
    cursor.close()
    conn.close()
    
    logger.info(f"Found {len(combinations)} unique league/season combinations")
    
    total_cached = 0
    for league_id, year in combinations:
        if league_id not in LEAGUE_MAPPING:
            continue
        
        league_info = LEAGUE_MAPPING[league_id]
        
        # Determine season (European leagues span two calendar years)
        # For a match in 2024: if Aug-Dec → season 2024, if Jan-Jul → season 2023
        # So we need to cache both 2023 and 2024 seasons for year 2024
        for season_offset in [0, -1]:
            season = int(year) + season_offset
            if season < 2020:  # Skip very old seasons
                continue
            
            try:
                count = matcher.ensure_team_cache(league_id, season)
                if count > 0:
                    total_cached += count
                    logger.info(
                        f"✅ Cached {count} teams for {league_info['name']} "
                        f"season {season}"
                    )
                time.sleep(0.5)  # Rate limiting
            except Exception as e:
                logger.warning(f"Failed to cache {league_info['name']} {season}: {e}")
    
    logger.info(f"\n✅ Team cache seeded: {total_cached} total teams cached")


def backfill_fixtures_for_matches(batch_size: int = 50, max_batches: int = 5, seed_cache: bool = True):
    """
    Backfill fixture_id for training_matches using TeamMatcher.
    
    Args:
        batch_size: Matches to process per batch
        max_batches: Maximum batches to process (safety limit)
        seed_cache: Whether to pre-seed team cache (recommended: True)
    """
    client = ApiFootballClient()
    conn = psycopg2.connect(DATABASE_URL)
    matcher = TeamMatcher(conn, client)
    
    # Pre-seed team cache for better matching
    if seed_cache:
        seed_team_cache(matcher)
    
    stats = {
        'processed': 0,
        'matched': 0,
        'ambiguous': 0,
        'no_candidates': 0,
        'errors': 0
    }
    
    cursor = conn.cursor()
    
    for batch_num in range(max_batches):
        logger.info(f"\n{'='*80}")
        logger.info(f"BATCH {batch_num + 1}/{max_batches}")
        logger.info(f"{'='*80}")
        
        cursor.execute("""
            SELECT match_id, league_id, home_team, away_team, match_date
            FROM training_matches
            WHERE fixture_id IS NULL
            AND match_date IS NOT NULL
            AND match_date BETWEEN '2024-08-01' AND '2025-05-31'
            AND league_id IN (2, 3, 39, 40, 78, 135, 140, 141, 61)
            ORDER BY match_date DESC
            LIMIT %s
        """, (batch_size,))
        
        matches = cursor.fetchall()
        
        if not matches:
            logger.info("No more matches to process")
            break
        
        logger.info(f"Processing {len(matches)} matches...")
        
        for match_id, league_id, home_team, away_team, match_date in matches:
            stats['processed'] += 1
            
            if league_id not in LEAGUE_MAPPING:
                logger.debug(f"League {league_id} not in mapping, skipping")
                continue
            
            league_info = LEAGUE_MAPPING[league_id]
            api_league_id = league_info['api_football_id']
            season = get_season_from_date(match_date, league_info['season_logic'])
            
            try:
                # Use TeamMatcher for intelligent fixture matching
                fixture_id, diag = matcher.match_fixture(
                    league_id=api_league_id,
                    season=season,
                    kickoff_date=match_date,
                    home_name=home_team,
                    away_name=away_team
                )
                
                if fixture_id:
                    # Success - update training_matches
                    cursor.execute("""
                        UPDATE training_matches
                        SET fixture_id = %s
                        WHERE match_id = %s
                    """, (fixture_id, match_id))
                    
                    matcher.record_success(match_id, fixture_id, diag)
                    stats['matched'] += 1
                    
                    logger.info(
                        f"✅ {match_id}: {home_team} vs {away_team} "
                        f"→ fixture {fixture_id} (score={diag['top_score']:.3f})"
                    )
                else:
                    # Failed - record diagnostics
                    matcher.record_failure(match_id, diag)
                    
                    if diag['status'] == 'ambiguous_top2':
                        stats['ambiguous'] += 1
                        logger.warning(f"⚠️  {match_id}: Ambiguous - {diag['message']}")
                    elif diag['status'] == 'no_candidates':
                        stats['no_candidates'] += 1
                        logger.debug(f"❌ {match_id}: No candidates - {diag['message']}")
                    else:
                        stats['errors'] += 1
                        logger.error(f"❌ {match_id}: Error - {diag['message']}")
                
                time.sleep(0.3)  # Rate limiting
                
            except Exception as e:
                stats['errors'] += 1
                logger.error(f"Error processing match {match_id}: {str(e)}")
        
        conn.commit()
        logger.info(
            f"\nBatch {batch_num + 1} complete: "
            f"{stats['matched']} matched, {stats['ambiguous']} ambiguous, "
            f"{stats['no_candidates']} no candidates, {stats['errors']} errors"
        )
    
    cursor.close()
    conn.close()
    
    # Final statistics
    logger.info(f"\n{'='*80}")
    logger.info("BACKFILL COMPLETE")
    logger.info(f"{'='*80}")
    logger.info(f"Total processed: {stats['processed']}")
    logger.info(f"✅ Matched: {stats['matched']}")
    logger.info(f"⚠️  Ambiguous: {stats['ambiguous']}")
    logger.info(f"❌ No candidates: {stats['no_candidates']}")
    logger.info(f"⚠️  Errors: {stats['errors']}")
    
    if stats['processed'] > 0:
        match_rate = stats['matched'] / stats['processed'] * 100
        logger.info(f"\n📊 Match rate: {match_rate:.1f}%")
        
        if stats['matched'] > 0:
            logger.info(f"\n✅ Next step: Run gap fill worker to fetch odds for {stats['matched']} matches")
        
        if stats['ambiguous'] > 0:
            logger.info(
                f"\n⚠️  {stats['ambiguous']} ambiguous matches logged in fixture_map_state table"
                f"\n   Query: SELECT * FROM fixture_map_state WHERE status = 'ambiguous_top2';"
            )


if __name__ == '__main__':
    logger.info("Starting fixture ID backfill with TeamMatcher...")
    logger.info("Features: Accent normalization, team aliases, fuzzy matching")
    logger.info("Targeting major European leagues (9 leagues)")
    logger.info("Batch size: 50 matches, Max batches: 5 (250 matches total)\n")
    
    backfill_fixtures_for_matches(batch_size=50, max_batches=5, seed_cache=True)
