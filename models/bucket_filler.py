"""
BetGenius AI - Bucket Filler Safety Net
Lightweight job that fills missing time buckets every 15 minutes
Prevents gaps in odds collection due to server downtime or missed windows
"""

import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import psycopg2
from models.automated_collector import AutomatedCollector

logger = logging.getLogger(__name__)

class BucketFiller:
    """
    Safety net system that fills missing time buckets for upcoming matches
    Runs every 15 minutes to catch any gaps in the main 6h/3h schedule
    """
    
    def __init__(self):
        self.collector = AutomatedCollector()
        # Time buckets to monitor (hours before kickoff)
        self.time_buckets = [168, 120, 72, 48, 24, 12, 6, 3, 1]
        # Tolerance for each bucket (hours)
        self.tolerances = [12, 12, 8, 8, 6, 6, 5, 3, 2]
        
    def get_database_connection(self):
        """Get database connection"""
        database_url = os.environ.get('DATABASE_URL')
        if not database_url:
            raise ValueError("DATABASE_URL not found in environment")
        return psycopg2.connect(database_url)
    
    def find_missing_buckets(self) -> List[Dict]:
        """Find matches that are missing odds snapshots for their time buckets"""
        
        try:
            with self.get_database_connection() as conn:
                with conn.cursor() as cursor:
                    # Find upcoming matches that might need bucket fills
                    query = """
                        SELECT 
                            m.match_id,
                            m.home_team,
                            m.away_team,
                            m.match_date,
                            l.league_name,
                            EXTRACT(EPOCH FROM (m.match_date - NOW()))/3600 as hours_to_kickoff
                        FROM training_matches m
                        JOIN league_map l ON m.league_id = l.league_id
                        WHERE m.match_date > NOW() 
                          AND m.match_date < NOW() + INTERVAL '7 days'
                        ORDER BY m.match_date
                    """
                    
                    cursor.execute(query)
                    upcoming_matches = cursor.fetchall()
                    
                    missing_buckets = []
                    
                    for match in upcoming_matches:
                        match_id, home_team, away_team, match_date, league, hours_to_kickoff = match
                        
                        # Check which time buckets this match should have
                        for i, bucket_hours in enumerate(self.time_buckets):
                            tolerance = self.tolerances[i]
                            
                            # Is this match in the window for this bucket?
                            if (bucket_hours - tolerance) <= hours_to_kickoff <= (bucket_hours + tolerance):
                                
                                # Check if we already have odds for this bucket window
                                bucket_query = """
                                    SELECT COUNT(*) 
                                    FROM odds_snapshots 
                                    WHERE match_id = %s
                                      AND ts_snapshot > NOW() - INTERVAL '24 hours'
                                      AND ABS(EXTRACT(EPOCH FROM (match_date - ts_snapshot))/3600 - %s) <= %s
                                """
                                
                                cursor.execute(bucket_query, (match_id, bucket_hours, tolerance))
                                existing_count = cursor.fetchone()[0]
                                
                                if existing_count == 0:
                                    missing_buckets.append({
                                        'match_id': match_id,
                                        'home_team': home_team,
                                        'away_team': away_team,
                                        'league': league,
                                        'match_date': match_date,
                                        'hours_to_kickoff': hours_to_kickoff,
                                        'target_bucket': f'T-{bucket_hours}h',
                                        'tolerance': tolerance
                                    })
                    
                    return missing_buckets
                    
        except Exception as e:
            logger.error(f"Error finding missing buckets: {e}")
            return []
    
    async def fill_missing_buckets(self) -> Dict:
        """Fill any missing time buckets for upcoming matches"""
        
        logger.info("🛡️ SAFETY NET: Starting bucket fill check...")
        
        missing_buckets = self.find_missing_buckets()
        
        if not missing_buckets:
            logger.info("✅ SAFETY NET: No missing buckets found - all windows covered")
            return {'buckets_filled': 0, 'matches_processed': 0}
        
        logger.info(f"🔍 SAFETY NET: Found {len(missing_buckets)} missing bucket opportunities")
        
        # Group by match to avoid duplicate API calls
        matches_to_fill = {}
        for bucket in missing_buckets:
            match_id = bucket['match_id']
            if match_id not in matches_to_fill:
                matches_to_fill[match_id] = bucket
        
        filled_count = 0
        
        for match_id, match_info in matches_to_fill.items():
            try:
                logger.info(f"🛡️ FILLING: {match_info['home_team']} vs {match_info['away_team']} - {match_info['target_bucket']}")
                
                # Use the existing collector to get odds for this match
                # This will automatically determine the correct time window
                results = await self.collector.collect_odds_for_specific_matches([match_id])
                
                if results and results.get('new_odds_collected', 0) > 0:
                    filled_count += 1
                    logger.info(f"✅ FILLED: Match {match_id} - {results.get('new_odds_collected', 0)} odds collected")
                else:
                    logger.warning(f"⚠️ NO ODDS: Could not collect odds for match {match_id}")
                    
            except Exception as e:
                logger.error(f"❌ FILL ERROR: Match {match_id} - {e}")
        
        result = {
            'buckets_checked': len(missing_buckets),
            'buckets_filled': filled_count,
            'matches_processed': len(matches_to_fill)
        }
        
        logger.info(f"🛡️ SAFETY NET COMPLETE: {result}")
        return result

async def main():
    """Main entry point for bucket filler"""
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    logger.info("🛡️ BetGenius Safety Net - Bucket Filler Starting")
    
    try:
        filler = BucketFiller()
        results = await filler.fill_missing_buckets()
        
        # Log results for monitoring
        if results['buckets_filled'] > 0:
            logger.info(f"🎯 SUCCESS: Filled {results['buckets_filled']} missing buckets")
        else:
            logger.info("✅ SUCCESS: All buckets covered, no action needed")
            
    except Exception as e:
        logger.error(f"❌ SAFETY NET FAILED: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())