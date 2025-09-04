"""
BetGenius AI - Monitoring & Alerting System
Observability tools to catch real issues before users do
"""

import logging
import os
import psycopg2
from datetime import datetime, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

class MonitoringSystem:
    """
    Production monitoring system for BetGenius AI
    Catches issues with odds collection and data quality
    """
    
    def __init__(self):
        self.database_url = os.environ.get('DATABASE_URL')
        if not self.database_url:
            raise ValueError("DATABASE_URL not found in environment")
    
    def get_db_connection(self):
        """Get database connection"""
        return psycopg2.connect(self.database_url)
    
    def check_fresh_odds_availability(self, threshold_minutes: int = 90) -> Dict:
        """Check if we have fresh odds within threshold"""
        
        try:
            with self.get_db_connection() as conn:
                with conn.cursor() as cursor:
                    query = """
                        SELECT 
                            COUNT(*) as snapshot_count,
                            COUNT(DISTINCT match_id) as match_count,
                            COUNT(DISTINCT book_id) as bookmaker_count,
                            MAX(ts_snapshot) as latest_snapshot
                        FROM odds_snapshots 
                        WHERE ts_snapshot > NOW() - INTERVAL '%s minutes'
                    """
                    
                    cursor.execute(query, (threshold_minutes,))
                    result = cursor.fetchone()
                    
                    snapshot_count, match_count, bookmaker_count, latest_snapshot = result
                    
                    is_healthy = snapshot_count > 0
                    
                    return {
                        'status': 'healthy' if is_healthy else 'alert',
                        'snapshot_count': snapshot_count or 0,
                        'match_count': match_count or 0,
                        'bookmaker_count': bookmaker_count or 0,
                        'latest_snapshot': latest_snapshot,
                        'threshold_minutes': threshold_minutes,
                        'message': f'Found {snapshot_count} odds snapshots in last {threshold_minutes} minutes' if is_healthy
                                 else f'⚠️ ALERT: No odds snapshots in last {threshold_minutes} minutes'
                    }
                    
        except Exception as e:
            logger.error(f"Error checking fresh odds availability: {e}")
            return {
                'status': 'error',
                'message': f'Database error: {e}'
            }
    
    def check_unmatched_team_names(self, hours: int = 1) -> Dict:
        """Check for unmatched team names in recent collection attempts"""
        
        try:
            # For now, we'll check for patterns in logs that indicate fuzzy matching issues
            # In the future, we could create a quarantine table for unmatched names
            
            with self.get_db_connection() as conn:
                with conn.cursor() as cursor:
                    # Check for matches that should have odds but don't
                    query = """
                        SELECT 
                            t.match_id,
                            t.home_team,
                            t.away_team,
                            t.match_date,
                            COUNT(o.match_id) as odds_count
                        FROM training_matches t
                        LEFT JOIN odds_snapshots o ON t.match_id = o.match_id 
                                                   AND o.ts_snapshot > NOW() - INTERVAL '%s hours'
                        WHERE t.match_date > NOW() 
                          AND t.match_date < NOW() + INTERVAL '7 days'
                        GROUP BY t.match_id, t.home_team, t.away_team, t.match_date
                        HAVING COUNT(o.match_id) = 0
                        ORDER BY t.match_date
                        LIMIT 20
                    """
                    
                    cursor.execute(query, (hours,))
                    unmatched_matches = cursor.fetchall()
                    
                    unmatched_count = len(unmatched_matches)
                    
                    unmatched_list = []
                    for match in unmatched_matches:
                        match_id, home_team, away_team, match_date, odds_count = match
                        unmatched_list.append({
                            'match_id': match_id,
                            'home_team': home_team,
                            'away_team': away_team,
                            'match_date': str(match_date),
                            'odds_count': odds_count
                        })
                    
                    return {
                        'status': 'alert' if unmatched_count > 0 else 'healthy',
                        'unmatched_count': unmatched_count,
                        'unmatched_matches': unmatched_list,
                        'message': f'Found {unmatched_count} upcoming matches without odds collection' if unmatched_count > 0
                                 else 'All upcoming matches have odds coverage'
                    }
                    
        except Exception as e:
            logger.error(f"Error checking unmatched team names: {e}")
            return {
                'status': 'error',
                'message': f'Database error: {e}'
            }
    
    def check_odds_quality(self) -> Dict:
        """Check the quality of recently collected odds"""
        
        try:
            with self.get_db_connection() as conn:
                with conn.cursor() as cursor:
                    # Check for complete H/D/A triplets
                    query = """
                        SELECT 
                            COUNT(*) as total_snapshots,
                            COUNT(DISTINCT match_id) as matches_with_odds,
                            COUNT(*) FILTER (WHERE outcome = 'H') as home_odds,
                            COUNT(*) FILTER (WHERE outcome = 'D') as draw_odds,
                            COUNT(*) FILTER (WHERE outcome = 'A') as away_odds,
                            AVG(odds_decimal) as avg_odds,
                            MIN(odds_decimal) as min_odds,
                            MAX(odds_decimal) as max_odds
                        FROM odds_snapshots 
                        WHERE ts_snapshot > NOW() - INTERVAL '6 hours'
                    """
                    
                    cursor.execute(query)
                    result = cursor.fetchone()
                    
                    if result and result[0]:  # total_snapshots > 0
                        total_snapshots, matches_with_odds, home_odds, draw_odds, away_odds, avg_odds, min_odds, max_odds = result
                        
                        # Check if we have balanced H/D/A distribution
                        total_outcomes = home_odds + draw_odds + away_odds
                        balance_ratio = min(home_odds, draw_odds, away_odds) / (total_outcomes / 3) if total_outcomes > 0 else 0
                        
                        return {
                            'status': 'healthy' if balance_ratio > 0.8 else 'warning',
                            'total_snapshots': total_snapshots,
                            'matches_with_odds': matches_with_odds,
                            'outcome_distribution': {
                                'home': home_odds,
                                'draw': draw_odds,
                                'away': away_odds
                            },
                            'odds_stats': {
                                'avg': round(float(avg_odds), 3) if avg_odds else 0,
                                'min': float(min_odds) if min_odds else 0,
                                'max': float(max_odds) if max_odds else 0
                            },
                            'balance_ratio': round(balance_ratio, 3),
                            'message': f'Quality check: {total_snapshots} odds from {matches_with_odds} matches, balance ratio {balance_ratio:.3f}'
                        }
                    else:
                        return {
                            'status': 'warning',
                            'message': 'No odds data found in last 6 hours'
                        }
                        
        except Exception as e:
            logger.error(f"Error checking odds quality: {e}")
            return {
                'status': 'error',
                'message': f'Database error: {e}'
            }
    
    def run_full_health_check(self) -> Dict:
        """Run comprehensive health check across all systems"""
        
        logger.info("🔍 Running comprehensive system health check...")
        
        results = {
            'timestamp': datetime.utcnow().isoformat(),
            'overall_status': 'healthy',
            'checks': {}
        }
        
        # Check 1: Fresh odds availability (last 30 minutes)
        fresh_odds = self.check_fresh_odds_availability(30)
        results['checks']['fresh_odds'] = fresh_odds
        
        # Check 2: Unmatched team names (last 1 hour)  
        unmatched_teams = self.check_unmatched_team_names(1)
        results['checks']['unmatched_teams'] = unmatched_teams
        
        # Check 3: Odds quality
        odds_quality = self.check_odds_quality()
        results['checks']['odds_quality'] = odds_quality
        
        # Determine overall status
        statuses = [check.get('status', 'unknown') for check in results['checks'].values()]
        if 'error' in statuses:
            results['overall_status'] = 'error'
        elif 'alert' in statuses:
            results['overall_status'] = 'alert'
        elif 'warning' in statuses:
            results['overall_status'] = 'warning'
        
        # Log results
        if results['overall_status'] == 'healthy':
            logger.info("✅ System health check: All systems healthy")
        else:
            logger.warning(f"⚠️ System health check: Status {results['overall_status']}")
            for check_name, check_result in results['checks'].items():
                if check_result.get('status') != 'healthy':
                    logger.warning(f"   - {check_name}: {check_result.get('message', 'Unknown issue')}")
        
        return results

def run_monitoring_check():
    """Entry point for running monitoring checks"""
    
    try:
        monitor = MonitoringSystem()
        return monitor.run_full_health_check()
    except Exception as e:
        logger.error(f"Monitoring system error: {e}")
        return {
            'timestamp': datetime.utcnow().isoformat(),
            'overall_status': 'error',
            'message': f'Monitoring system failed: {e}'
        }

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = run_monitoring_check()
    print(f"Health check result: {result['overall_status']}")