#!/usr/bin/env python3
"""
Team Logo Enrichment Script

Fetches missing team logos from API-Football for teams in your database.
Uses intelligent name matching and constructs logo URLs using the pattern:
https://media.api-sports.io/football/teams/{team_id}.png

Usage:
    python scripts/enrich_team_logos.py --limit 50        # Enrich 50 teams
    python scripts/enrich_team_logos.py --limit 50 --force  # Re-fetch all teams
    python scripts/enrich_team_logos.py --status           # Show current stats
"""

import sys
import os
import argparse
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.team_enrichment import get_team_enrichment_service
from utils.logo_constructor import backfill_missing_logos, get_teams_needing_enrichment
import psycopg2

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def show_status():
    """Show current logo enrichment status"""
    conn = psycopg2.connect(os.environ.get('DATABASE_URL'))
    cursor = conn.cursor()
    
    try:
        print("\n" + "="*70)
        print("TEAM LOGO ENRICHMENT STATUS")
        print("="*70)
        
        cursor.execute("""
            SELECT 
                COUNT(*) as total_teams,
                COUNT(logo_url) as teams_with_logos,
                COUNT(*) - COUNT(logo_url) as teams_without_logos,
                COUNT(api_football_team_id) as teams_with_api_id,
                ROUND(100.0 * COUNT(logo_url) / COUNT(*), 1) as logo_coverage_pct
            FROM teams
        """)
        
        row = cursor.fetchone()
        total, with_logos, without_logos, with_api_id, coverage_pct = row
        
        print(f"\n📊 Overall Statistics:")
        print(f"   Total teams:          {total:,}")
        print(f"   Teams with logos:     {with_logos:,} ({coverage_pct}%)")
        print(f"   Teams WITHOUT logos:  {without_logos:,}")
        print(f"   Teams with API ID:    {with_api_id:,}")
        
        if without_logos > 0:
            cursor.execute("""
                SELECT name, country
                FROM teams
                WHERE logo_url IS NULL
                  AND name NOT IN ('TBD', '')
                ORDER BY name
                LIMIT 10
            """)
            
            print(f"\n🔍 Sample teams needing enrichment (showing 10 of {without_logos}):")
            for name, country in cursor.fetchall():
                country_str = f"({country})" if country else "(Unknown)"
                print(f"   - {name} {country_str}")
        
        print("\n💡 Recommendation:")
        if without_logos > 0:
            print(f"   Run: python scripts/enrich_team_logos.py --limit {min(50, without_logos)}")
            print(f"   This will enrich up to {min(50, without_logos)} teams (rate limited to 1 request/sec)")
        else:
            print("   ✅ All teams have logos! No enrichment needed.")
        
        print("="*70 + "\n")
        
    finally:
        cursor.close()
        conn.close()


def main():
    parser = argparse.ArgumentParser(description='Enrich team logos from API-Football')
    parser.add_argument('--limit', type=int, default=50,
                       help='Maximum number of teams to enrich (default: 50)')
    parser.add_argument('--force', action='store_true',
                       help='Re-fetch logos for all teams, even if cached')
    parser.add_argument('--status', action='store_true',
                       help='Show current enrichment status and exit')
    
    args = parser.parse_args()
    
    if args.status:
        show_status()
        return
    
    print("\n" + "="*70)
    print("TEAM LOGO ENRICHMENT")
    print("="*70 + "\n")
    
    # Step 1: Backfill any teams with API ID but no logo (safety net)
    print("Step 1: Checking for teams with API ID but missing logos...")
    backfill_result = backfill_missing_logos(dry_run=False)
    
    if backfill_result['teams_updated'] > 0:
        print(f"✅ Backfilled {backfill_result['teams_updated']} logos using ID constructor")
    else:
        print("✅ No backfill needed - all teams with API IDs have logos")
    
    # Step 2: Enrich teams from API-Football
    print(f"\nStep 2: Enriching up to {args.limit} teams from API-Football...")
    print("   (This makes API calls, rate limited to 1 request/second)")
    
    service = get_team_enrichment_service()
    result = service.enrich_teams_from_fixtures(limit=args.limit, force=args.force)
    
    print("\n" + "="*70)
    print("ENRICHMENT RESULTS")
    print("="*70)
    print(f"   Teams processed:  {result['teams_processed']}")
    print(f"   Teams enriched:   {result['teams_enriched']} ✅")
    print(f"   Teams failed:     {result['teams_failed']}")
    print(f"   API calls made:   {result['api_calls']}")
    
    # Step 3: Link fixtures to teams
    print("\nStep 3: Linking fixtures to teams...")
    link_result = service.link_fixtures_to_teams()
    print(f"✅ Linked {link_result['fixtures_linked']} fixtures to teams")
    
    # Step 4: Show updated status
    print("\n")
    show_status()


if __name__ == '__main__':
    main()
