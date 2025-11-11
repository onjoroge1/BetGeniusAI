"""
Logo URL Constructor for API-Sports Teams
Constructs logo URLs directly from api_football_team_id without needing API calls.
"""

import os
import psycopg2
import logging
from typing import Optional

logger = logging.getLogger(__name__)

def construct_logo_url(api_football_team_id: int) -> str:
    """
    Construct logo URL from API-Football team ID.
    
    Pattern: https://media.api-sports.io/football/teams/{team_id}.png
    
    Args:
        api_football_team_id: The API-Football team ID
        
    Returns:
        Full logo URL string
        
    Example:
        >>> construct_logo_url(33)
        'https://media.api-sports.io/football/teams/33.png'
    """
    return f"https://media.api-sports.io/football/teams/{api_football_team_id}.png"


def backfill_missing_logos(dry_run: bool = True) -> dict:
    """
    Backfill logo URLs for teams that have api_football_team_id but no logo_url.
    
    This is a safety net - normally the enrichment service sets both together.
    But this handles edge cases where logo_url might be missing.
    
    Args:
        dry_run: If True, only report what would be updated without changing DB
        
    Returns:
        {
            'teams_found': int,
            'teams_updated': int,
            'sample_teams': List[str]
        }
    """
    conn = psycopg2.connect(os.environ.get('DATABASE_URL'))
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT team_id, name, api_football_team_id
            FROM teams
            WHERE api_football_team_id IS NOT NULL
              AND logo_url IS NULL
        """)
        
        teams_to_fix = cursor.fetchall()
        teams_found = len(teams_to_fix)
        
        if teams_found == 0:
            logger.info("✅ No missing logos found - all teams with API IDs have logo URLs")
            return {
                'teams_found': 0,
                'teams_updated': 0,
                'sample_teams': []
            }
        
        logger.info(f"Found {teams_found} teams with API ID but no logo URL")
        
        sample_teams = []
        teams_updated = 0
        
        for team_id, team_name, api_id in teams_to_fix:
            logo_url = construct_logo_url(api_id)
            sample_teams.append(f"{team_name} (ID:{api_id}) → {logo_url}")
            
            if not dry_run:
                cursor.execute("""
                    UPDATE teams
                    SET logo_url = %s,
                        logo_last_synced_at = NOW(),
                        updated_at = NOW()
                    WHERE team_id = %s
                """, (logo_url, team_id))
                teams_updated += 1
        
        if not dry_run:
            conn.commit()
            logger.info(f"✅ Updated {teams_updated} teams with constructed logo URLs")
        else:
            logger.info(f"DRY RUN: Would update {teams_found} teams")
        
        return {
            'teams_found': teams_found,
            'teams_updated': teams_updated if not dry_run else 0,
            'sample_teams': sample_teams[:10]
        }
        
    except Exception as e:
        conn.rollback()
        logger.error(f"Error backfilling logos: {e}", exc_info=True)
        raise
    finally:
        cursor.close()
        conn.close()


def get_teams_needing_enrichment(limit: int = 50) -> list:
    """
    Get teams that need API-Football enrichment (no api_football_team_id).
    
    Args:
        limit: Max teams to return
        
    Returns:
        List of (team_id, name, country) tuples
    """
    conn = psycopg2.connect(os.environ.get('DATABASE_URL'))
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT team_id, name, country
            FROM teams
            WHERE api_football_team_id IS NULL
              AND name NOT IN ('TBD', '')
            ORDER BY name
            LIMIT %s
        """, (limit,))
        
        teams = cursor.fetchall()
        logger.info(f"Found {len(teams)} teams needing enrichment")
        return teams
        
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("\n" + "="*60)
    print("LOGO URL CONSTRUCTOR - Analysis")
    print("="*60 + "\n")
    
    print("1. Checking for missing logo URLs...")
    result = backfill_missing_logos(dry_run=True)
    print(f"   Teams with API ID but no logo: {result['teams_found']}")
    
    if result['sample_teams']:
        print("\n   Sample teams that would be fixed:")
        for team in result['sample_teams']:
            print(f"   - {team}")
    
    print("\n2. Teams needing API-Football enrichment...")
    teams_needing_enrichment = get_teams_needing_enrichment(limit=10)
    print(f"   Total teams without API ID: {len(teams_needing_enrichment)}")
    
    if teams_needing_enrichment:
        print("\n   Sample teams (need API search):")
        for team_id, name, country in teams_needing_enrichment:
            print(f"   - {name} ({country or 'Unknown country'})")
    
    print("\n" + "="*60)
    print("TIP: Run team enrichment to fetch logos for teams without API IDs:")
    print("     from models.team_enrichment import get_team_enrichment_service")
    print("     service = get_team_enrichment_service()")
    print("     service.enrich_teams_from_fixtures(limit=50)")
    print("="*60 + "\n")
