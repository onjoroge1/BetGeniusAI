#!/usr/bin/env python3
"""
Odds Collection Monitor & Auto-Trigger System
Ensures odds_snapshots table is always current for production predictions
"""

import os
import psycopg2
import requests
import time
import json
from datetime import datetime, timedelta
from typing import Dict, List, Any
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class OddsCollectionMonitor:
    """Monitor odds freshness and auto-trigger collection when needed"""
    
    def __init__(self):
        self.database_url = os.environ.get('DATABASE_URL')
        self.api_base = "http://localhost:8000"
        self.headers = {
            "Authorization": "Bearer betgenius_secure_key_2024",
            "Content-Type": "application/json"
        }
        
    def check_odds_freshness(self) -> Dict[str, Any]:
        """Check how fresh the odds data is"""
        
        try:
            with psycopg2.connect(self.database_url) as conn:
                with conn.cursor() as cursor:
                    # Get odds freshness statistics
                    cursor.execute("""
                        SELECT 
                            COUNT(*) as total_odds,
                            COUNT(DISTINCT match_id) as unique_matches,
                            MAX(ts_snapshot) as most_recent_data,
                            NOW() - MAX(ts_snapshot) as data_age_interval,
                            EXTRACT(EPOCH FROM (NOW() - MAX(ts_snapshot)))/3600 as data_age_hours,
                            COUNT(DISTINCT book_id) as unique_bookmakers
                        FROM odds_snapshots;
                    """)
                    
                    row = cursor.fetchone()
                    
                    if row:
                        total_odds, unique_matches, most_recent, age_interval, age_hours, bookmakers = row
                        
                        # Get upcoming matches that need odds
                        cursor.execute("""
                            SELECT COUNT(*) 
                            FROM (
                                SELECT DISTINCT match_id 
                                FROM odds_snapshots 
                                WHERE ts_snapshot > NOW() - INTERVAL '24 hours'
                            ) recent;
                        """)
                        
                        recent_matches = cursor.fetchone()[0] if cursor.fetchone() else 0
                        
                        return {
                            'total_odds': total_odds,
                            'unique_matches': unique_matches,
                            'most_recent_data': most_recent_data.isoformat() if most_recent_data else None,
                            'data_age_hours': float(age_hours) if age_hours else 999,
                            'unique_bookmakers': bookmakers,
                            'recent_matches_with_odds': recent_matches,
                            'is_fresh': age_hours < 6 if age_hours else False,  # Fresh if < 6 hours old
                            'needs_collection': age_hours > 4 if age_hours else True  # Trigger if > 4 hours old
                        }
                    
                    return {'error': 'No odds data found'}
                    
        except Exception as e:
            logger.error(f"Error checking odds freshness: {e}")
            return {'error': str(e)}
    
    def get_upcoming_matches_needing_odds(self) -> List[int]:
        """Get upcoming matches that don't have recent odds"""
        
        try:
            # Get upcoming matches from multiple leagues
            upcoming_matches = []
            leagues = [39, 140, 135, 78, 61, 88]  # EPL, La Liga, Serie A, Bundesliga, Ligue 1, Eredivisie
            
            for league_id in leagues:
                try:
                    response = requests.get(
                        f"{self.api_base}/matches/upcoming",
                        headers=self.headers,
                        params={"league_id": league_id, "limit": 10}
                    )
                    
                    if response.status_code == 200:
                        data = response.json()
                        matches = data.get('matches', [])
                        for match in matches:
                            upcoming_matches.append(match['match_id'])
                            
                except Exception as e:
                    logger.warning(f"Error getting upcoming matches for league {league_id}: {e}")
                    continue
            
            # Check which matches lack recent odds
            if not upcoming_matches:
                return []
            
            with psycopg2.connect(self.database_url) as conn:
                with conn.cursor() as cursor:
                    # Find matches without recent odds (last 12 hours)
                    placeholders = ','.join(['%s'] * len(upcoming_matches))
                    query = f"""
                        SELECT DISTINCT match_id 
                        FROM unnest(ARRAY[{placeholders}]) AS upcoming(match_id)
                        WHERE match_id NOT IN (
                            SELECT DISTINCT match_id 
                            FROM odds_snapshots 
                            WHERE ts_snapshot > NOW() - INTERVAL '12 hours'
                        );
                    """
                    
                    cursor.execute(query, upcoming_matches)
                    missing_odds = [row[0] for row in cursor.fetchall()]
                    
                    return missing_odds
                    
        except Exception as e:
            logger.error(f"Error finding matches needing odds: {e}")
            return []
    
    def trigger_odds_collection(self) -> Dict[str, Any]:
        """Trigger manual odds collection"""
        
        try:
            response = requests.post(
                f"{self.api_base}/admin/trigger-collection",
                headers=self.headers
            )
            
            if response.status_code == 200:
                return {'success': True, 'message': 'Collection triggered successfully'}
            else:
                return {'success': False, 'error': f"HTTP {response.status_code}: {response.text}"}
                
        except Exception as e:
            logger.error(f"Error triggering collection: {e}")
            return {'success': False, 'error': str(e)}
    
    def monitor_and_maintain(self) -> Dict[str, Any]:
        """Main monitoring function - checks freshness and triggers collection if needed"""
        
        logger.info("🔍 Monitoring odds collection freshness...")
        
        # Check current odds freshness
        freshness_check = self.check_odds_freshness()
        
        if 'error' in freshness_check:
            logger.error(f"❌ Unable to check odds freshness: {freshness_check['error']}")
            return freshness_check
        
        logger.info(f"📊 Odds Status: {freshness_check['total_odds']} odds from {freshness_check['unique_matches']} matches")
        logger.info(f"⏰ Data Age: {freshness_check['data_age_hours']:.1f} hours")
        logger.info(f"🎯 Recent Matches with Odds: {freshness_check['recent_matches_with_odds']}")
        
        # Check if collection is needed
        needs_collection = freshness_check['needs_collection']
        missing_matches = self.get_upcoming_matches_needing_odds()
        
        result = {
            'timestamp': datetime.now().isoformat(),
            'freshness_check': freshness_check,
            'missing_matches_count': len(missing_matches),
            'collection_triggered': False,
            'collection_result': None
        }
        
        if needs_collection or missing_matches:
            logger.warning(f"⚠️ Odds collection needed! Data age: {freshness_check['data_age_hours']:.1f}h, Missing matches: {len(missing_matches)}")
            
            # Trigger collection
            collection_result = self.trigger_odds_collection()
            result['collection_triggered'] = True
            result['collection_result'] = collection_result
            
            if collection_result['success']:
                logger.info("✅ Odds collection triggered successfully")
            else:
                logger.error(f"❌ Failed to trigger collection: {collection_result['error']}")
        else:
            logger.info("✅ Odds data is fresh - no collection needed")
        
        return result
    
    def continuous_monitor(self, check_interval_minutes: int = 30):
        """Run continuous monitoring loop"""
        
        logger.info(f"🔄 Starting continuous odds monitoring (checking every {check_interval_minutes} minutes)")
        
        while True:
            try:
                result = self.monitor_and_maintain()
                
                # Save monitoring log
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                log_file = f"odds_monitor_log_{timestamp}.json"
                
                with open(log_file, 'w') as f:
                    json.dump(result, f, indent=2)
                
                logger.info(f"📝 Monitoring result saved to {log_file}")
                
            except Exception as e:
                logger.error(f"Error in continuous monitoring: {e}")
            
            # Wait before next check
            time.sleep(check_interval_minutes * 60)

def main():
    """Run odds collection monitoring"""
    
    monitor = OddsCollectionMonitor()
    
    # Single check
    result = monitor.monitor_and_maintain()
    
    # Print summary
    print("\n" + "="*60)
    print("📊 ODDS COLLECTION MONITORING REPORT")
    print("="*60)
    
    freshness = result.get('freshness_check', {})
    
    print(f"📅 Check Time: {result['timestamp']}")
    print(f"📊 Total Odds: {freshness.get('total_odds', 'Unknown')}")
    print(f"🎯 Unique Matches: {freshness.get('unique_matches', 'Unknown')}")
    print(f"⏰ Data Age: {freshness.get('data_age_hours', 999):.1f} hours")
    print(f"📈 Bookmakers: {freshness.get('unique_bookmakers', 'Unknown')}")
    print(f"🆕 Recent Matches: {freshness.get('recent_matches_with_odds', 'Unknown')}")
    print(f"❓ Missing Matches: {result['missing_matches_count']}")
    
    status = "🟢 FRESH" if freshness.get('is_fresh') else "🔴 STALE"
    print(f"🔍 Status: {status}")
    
    if result['collection_triggered']:
        collection_success = result['collection_result']['success']
        print(f"🔄 Collection Triggered: {'✅ Success' if collection_success else '❌ Failed'}")
    else:
        print("🔄 Collection Triggered: Not needed")
    
    print("="*60)
    
    return result

if __name__ == "__main__":
    main()