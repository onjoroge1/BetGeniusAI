#!/usr/bin/env python3
"""
Backfill fixture_id for training_matches by searching API-Football.
Uses team names and match dates to find matching fixtures.
"""

import os
import psycopg2
from datetime import datetime, timedelta
from utils.api_football_client import ApiFootballClient
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


def backfill_fixtures_for_matches(batch_size: int = 50, max_batches: int = 5):
    """
    Backfill fixture_id for training_matches without fixture_id.
    
    Args:
        batch_size: Matches to process per batch
        max_batches: Maximum batches to process (safety limit)
    """
    client = ApiFootballClient()
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    
    stats = {
        'processed': 0,
        'matched': 0,
        'no_match': 0,
        'errors': 0
    }
    
    for batch_num in range(max_batches):
        logger.info(f"\n{'='*80}")
        logger.info(f"BATCH {batch_num + 1}/{max_batches}")
        logger.info(f"{'='*80}")
        
        cursor.execute("""
            SELECT match_id, league_id, home_team, away_team, match_date
            FROM training_matches
            WHERE fixture_id IS NULL
            AND match_date IS NOT NULL
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
            
            date_from = (match_date - timedelta(days=1)).strftime('%Y-%m-%d')
            date_to = (match_date + timedelta(days=1)).strftime('%Y-%m-%d')
            
            try:
                fixtures = client.search_fixtures_by_teams(
                    home_team=home_team,
                    away_team=away_team,
                    date_from=date_from,
                    date_to=date_to,
                    league_id=api_league_id,
                    season=season
                )
                
                if fixtures:
                    fixture = fixtures[0]
                    fixture_id = fixture['fixture']['id']
                    
                    cursor.execute("""
                        UPDATE training_matches
                        SET fixture_id = %s
                        WHERE match_id = %s
                    """, (fixture_id, match_id))
                    
                    stats['matched'] += 1
                    logger.info(
                        f"✅ Match {match_id}: {home_team} vs {away_team} "
                        f"→ fixture {fixture_id}"
                    )
                else:
                    stats['no_match'] += 1
                    logger.debug(
                        f"❌ No fixture found for: {home_team} vs {away_team} "
                        f"({match_date.strftime('%Y-%m-%d')})"
                    )
                
                time.sleep(0.3)
                
            except Exception as e:
                stats['errors'] += 1
                logger.error(f"Error processing match {match_id}: {str(e)}")
        
        conn.commit()
        logger.info(
            f"\nBatch {batch_num + 1} complete: "
            f"{stats['matched']} matched, {stats['no_match']} no match, "
            f"{stats['errors']} errors"
        )
    
    cursor.close()
    conn.close()
    
    logger.info(f"\n{'='*80}")
    logger.info("BACKFILL COMPLETE")
    logger.info(f"{'='*80}")
    logger.info(f"Total processed: {stats['processed']}")
    logger.info(f"✅ Matched: {stats['matched']}")
    logger.info(f"❌ No match: {stats['no_match']}")
    logger.info(f"⚠️  Errors: {stats['errors']}")
    
    if stats['matched'] > 0:
        match_rate = stats['matched'] / stats['processed'] * 100
        logger.info(f"📊 Match rate: {match_rate:.1f}%")
        logger.info(f"\n✅ Run gap fill worker to fetch odds for {stats['matched']} matches")


if __name__ == '__main__':
    logger.info("Starting fixture ID backfill...")
    logger.info("Targeting major European leagues only (9 leagues)")
    logger.info("Batch size: 50 matches, Max batches: 5 (250 matches total)\n")
    
    backfill_fixtures_for_matches(batch_size=50, max_batches=5)
