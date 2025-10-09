"""
CLV Club Alert Producer
Scans fixtures every minute, detects CLV opportunities, and creates alerts with TTL
"""

import os
import psycopg2
import hashlib
import uuid
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
import logging

from models.clv_club import CLVClubEngine, BookOdds
from models.database import DatabaseManager, CLVAlert
from utils.config import settings

logger = logging.getLogger(__name__)

class CLVAlertProducer:
    """
    Produces CLV alerts by scanning upcoming fixtures
    Runs every 60 seconds with idempotency via minute-hash
    """
    
    def __init__(self):
        self.engine = CLVClubEngine()
        self.db_manager = DatabaseManager()
        self.database_url = os.environ.get('DATABASE_URL')
        
        # Feature flag: Filter out TBD fixtures (teams not determined yet)
        self.allow_tbd = os.getenv("ALLOW_TBD_FIXTURES", "0") == "1"  # Default OFF - no TBD matches
        
        if not settings.ENABLE_CLV_CLUB:
            logger.info("CLV Club is disabled in config")
        
        # Major leagues (stricter book requirements)
        self.major_leagues = [
            'Premier League',
            'La Liga',
            'Serie A',
            'Bundesliga',
            'Ligue 1'
        ]
    
    def _generate_alert_hash(self, match_id: int, outcome: str, minute: datetime) -> str:
        """
        Generate idempotency hash for alerts
        Prevents duplicate alerts within same minute
        """
        minute_str = minute.strftime('%Y%m%d%H%M')
        hash_input = f"{match_id}_{outcome}_{minute_str}"
        return hashlib.md5(hash_input.encode()).hexdigest()
    
    def _is_major_league(self, league: str) -> bool:
        """Check if league requires stricter book requirements"""
        return league in self.major_leagues
    
    def _get_upcoming_fixtures(self, max_hours_ahead: int = 72) -> List[Dict[str, Any]]:
        """
        Get fixtures within the next N hours that have recent odds
        
        Returns:
            List of dicts with match_id, league, kickoff_time
        """
        try:
            with psycopg2.connect(self.database_url) as conn:
                cursor = conn.cursor()
                
                # Find fixtures with odds in the target window
                # ✅ FIX: Use fixtures table (not matches) since fresh odds link to fixtures
                # ✅ Filter out TBD/placeholder fixtures (unless feature flag enabled)
                tbd_guard = "" if self.allow_tbd else "AND f.home_team NOT ILIKE 'TBD%' AND f.away_team NOT ILIKE 'TBD%'"
                
                sql_query = f"""
                    SELECT 
                        os.match_id,
                        COALESCE(lm.league_name, CAST(os.league_id AS text)) as league_name,
                        f.kickoff_at as kickoff_at
                    FROM odds_snapshots os
                    LEFT JOIN league_map lm ON os.league_id = lm.league_id
                    LEFT JOIN fixtures f ON os.match_id = f.match_id
                    WHERE f.kickoff_at > NOW()
                      AND f.kickoff_at < NOW() + make_interval(hours => %s)
                      AND os.ts_snapshot > NOW() - INTERVAL '10 minutes'
                      {tbd_guard}
                    GROUP BY os.match_id, lm.league_name, os.league_id, f.kickoff_at
                    HAVING COUNT(DISTINCT os.book_id) >= %s
                """
                
                cursor.execute(sql_query, (max_hours_ahead, settings.CLV_MIN_BOOKS_MINOR))
                
                fixtures = []
                for row in cursor.fetchall():
                    match_id, league, kickoff_at = row
                    # Ensure kickoff_at is timezone-aware (database returns naive datetime)
                    if kickoff_at.tzinfo is None:
                        from datetime import timezone
                        kickoff_at = kickoff_at.replace(tzinfo=timezone.utc)
                    fixtures.append({
                        'match_id': match_id,
                        'league': league,
                        'kickoff_time': kickoff_at
                    })
                
                logger.debug(f"Found {len(fixtures)} fixtures with recent odds")
                return fixtures
                
        except Exception as e:
            logger.exception(f"Error fetching upcoming fixtures: {e}")
            return []
    
    def _get_match_odds(self, match_id: int) -> List[BookOdds]:
        """
        Get latest odds for a match from all bookmakers
        
        Returns:
            List of BookOdds objects
        """
        try:
            with psycopg2.connect(self.database_url) as conn:
                cursor = conn.cursor()
                
                # Get most recent odds per bookmaker (within last 5 minutes)
                cursor.execute("""
                    WITH ranked_odds AS (
                        SELECT 
                            os.book_id,
                            os.outcome,
                            os.odds_decimal,
                            os.ts_snapshot,
                            ROW_NUMBER() OVER (
                                PARTITION BY os.book_id, os.outcome 
                                ORDER BY os.ts_snapshot DESC
                            ) as rn
                        FROM odds_snapshots os
                        WHERE os.match_id = %s
                          AND os.ts_snapshot > NOW() - INTERVAL '5 minutes'
                    )
                    SELECT book_id, outcome, odds_decimal, ts_snapshot
                    FROM ranked_odds
                    WHERE rn = 1
                    ORDER BY book_id, outcome
                """, (match_id,))
                
                # Group by book_id to build complete 3-way odds
                book_odds_map = {}
                for row in cursor.fetchall():
                    book_id, outcome, odds_decimal, ts_snapshot = row
                    
                    # Ensure timestamp is timezone-aware (database returns naive datetime)
                    if ts_snapshot and ts_snapshot.tzinfo is None:
                        from datetime import timezone
                        ts_snapshot = ts_snapshot.replace(tzinfo=timezone.utc)
                    
                    if book_id not in book_odds_map:
                        book_odds_map[book_id] = {
                            'book_id': book_id,
                            'odds_h': None,
                            'odds_d': None,
                            'odds_a': None,
                            'timestamp': ts_snapshot
                        }
                    
                    if outcome == 'H':
                        book_odds_map[book_id]['odds_h'] = odds_decimal
                    elif outcome == 'D':
                        book_odds_map[book_id]['odds_d'] = odds_decimal
                    elif outcome == 'A':
                        book_odds_map[book_id]['odds_a'] = odds_decimal
                
                # Convert to BookOdds objects (only complete 3-way odds)
                book_odds_list = []
                for book_id, data in book_odds_map.items():
                    if all([data['odds_h'], data['odds_d'], data['odds_a']]):
                        book_odds = BookOdds(
                            book_id=book_id,
                            odds_h=data['odds_h'],
                            odds_d=data['odds_d'],
                            odds_a=data['odds_a'],
                            timestamp=data['timestamp'],
                            desk_group=self.engine.get_desk_group(book_id)
                        )
                        book_odds_list.append(book_odds)
                
                logger.debug(f"Match {match_id}: {len(book_odds_list)} complete 3-way odds")
                return book_odds_list
                
        except Exception as e:
            logger.error(f"Error fetching match odds for {match_id}: {e}")
            return []
    
    def _get_historical_probs(self, match_id: int) -> Dict[str, List[float]]:
        """
        Get historical composite probabilities for stability calculation
        
        Returns:
            Dict with keys 'H', 'D', 'A' containing recent probabilities
        """
        try:
            with psycopg2.connect(self.database_url) as conn:
                cursor = conn.cursor()
                
                # Get consensus predictions from last 60-90 minutes
                cursor.execute("""
                    SELECT 
                        time_bucket,
                        consensus_h,
                        consensus_d,
                        consensus_a
                    FROM consensus_predictions
                    WHERE match_id = %s
                      AND created_at > NOW() - INTERVAL '90 minutes'
                    ORDER BY created_at DESC
                    LIMIT 10
                """, (match_id,))
                
                rows = cursor.fetchall()
                
                if not rows:
                    return {}
                
                h_probs = []
                d_probs = []
                a_probs = []
                
                for row in rows:
                    _, h, d, a = row
                    if h: h_probs.append(h)
                    if d: d_probs.append(d)
                    if a: a_probs.append(a)
                
                return {
                    'H': h_probs,
                    'D': d_probs,
                    'A': a_probs
                }
                
        except Exception as e:
            logger.debug(f"No historical probs for match {match_id}: {e}")
            return {}
    
    def _save_alert(self, opportunity, fixture_info: Dict) -> bool:
        """
        Save CLV alert to database with idempotency check
        
        Returns:
            True if alert was created, False if skipped (duplicate)
        """
        try:
            current_time = datetime.now(timezone.utc)
            current_minute = current_time.replace(second=0, microsecond=0)
            
            # Generate idempotency hash
            alert_hash = self._generate_alert_hash(
                opportunity.match_id,
                opportunity.outcome,
                current_minute
            )
            
            # Calculate TTL
            ttl_seconds = self.engine.calculate_alert_ttl(
                opportunity.kickoff_time,
                current_time
            )
            expires_at = current_time + timedelta(seconds=ttl_seconds)
            
            session = self.db_manager.SessionLocal()
            
            # Check for existing alert with same hash (idempotency)
            existing = session.query(CLVAlert).filter_by(
                match_id=opportunity.match_id,
                outcome=opportunity.outcome
            ).filter(
                CLVAlert.created_at >= current_minute,
                CLVAlert.created_at < current_minute + timedelta(minutes=1)
            ).first()
            
            if existing:
                logger.debug(f"Alert already exists for match {opportunity.match_id} outcome {opportunity.outcome}")
                session.close()
                return False
            
            # Create new alert
            alert = CLVAlert(
                alert_id=uuid.uuid4(),
                match_id=opportunity.match_id,
                league=opportunity.league,
                outcome=opportunity.outcome,
                best_book_id=opportunity.best_book_id,
                best_odds_dec=opportunity.best_odds_dec,
                market_odds_dec=opportunity.market_odds_dec,
                clv_pct=opportunity.clv_pct,
                stability=opportunity.stability,
                books_used=opportunity.books_used,
                window_tag=opportunity.window_tag,
                expires_at=expires_at,
                created_at=current_time
            )
            
            session.add(alert)
            session.commit()
            session.close()
            
            logger.info(f"✅ CLV Alert created: Match {opportunity.match_id} {opportunity.outcome} " +
                       f"CLV={opportunity.clv_pct:.2f}% Stability={opportunity.stability:.3f}")
            return True
            
        except Exception as e:
            logger.error(f"Error saving CLV alert: {e}")
            return False
    
    def run_producer_cycle(self) -> Dict[str, Any]:
        """
        Run one producer cycle: scan fixtures, detect opportunities, create alerts
        
        Returns:
            Stats dict with counts
        """
        if not settings.ENABLE_CLV_CLUB:
            return {'enabled': False}
        
        import time
        cycle_start = time.time()
        
        logger.info("🔍 CLV Alert Producer: Starting cycle...")
        
        stats = {
            'enabled': True,
            'fixtures_scanned': 0,
            'opportunities_found': 0,
            'alerts_created': 0,
            'suppression_reasons': {
                'STALE': 0,
                'LOW_BOOKS': 0,
                'LOW_STABILITY': 0,
                'LOW_CLV': 0,
                'BAD_IDENTITY': 0
            },
            'timings': {
                'total_ms': 0,
                'gather_odds_ms': 0,
                'analyze_ms': 0
            }
        }
        
        try:
            # Get upcoming fixtures
            fixtures = self._get_upcoming_fixtures()
            stats['fixtures_scanned'] = len(fixtures)
            
            if not fixtures:
                logger.info("No upcoming fixtures with recent odds")
                return stats
            
            # Process each fixture
            for fixture in fixtures:
                try:
                    match_id = fixture['match_id']
                    league = fixture['league']
                    kickoff_time = fixture['kickoff_time']
                    
                    # Get current odds
                    t_start = time.time()
                    book_odds = self._get_match_odds(match_id)
                    stats['timings']['gather_odds_ms'] += int((time.time() - t_start) * 1000)
                    
                    if len(book_odds) < settings.CLV_MIN_BOOKS_MINOR:
                        stats['suppression_reasons']['LOW_BOOKS'] += 1
                        continue
                    
                    # Get historical probs for stability
                    historical_probs = self._get_historical_probs(match_id)
                    
                    # Analyze CLV opportunities
                    t_analyze = time.time()
                    opportunities = self.engine.analyze_match_clv(
                        match_id=match_id,
                        league=league,
                        kickoff_time=kickoff_time,
                        book_odds_list=book_odds,
                        historical_probs=historical_probs
                    )
                    stats['timings']['analyze_ms'] += int((time.time() - t_analyze) * 1000)
                    
                    # Gate and emit alerts
                    is_major = self._is_major_league(league)
                    
                    for opportunity in opportunities:
                        stats['opportunities_found'] += 1
                        
                        # Apply gates
                        should_emit, reason = self.engine.should_emit_alert(opportunity, is_major)
                        
                        if should_emit:
                            # Save alert
                            if self._save_alert(opportunity, fixture):
                                stats['alerts_created'] += 1
                        else:
                            # Track suppression reason with standardized codes
                            if 'books' in reason.lower() or 'insufficient' in reason.lower():
                                stats['suppression_reasons']['LOW_BOOKS'] += 1
                            elif 'stability' in reason.lower():
                                stats['suppression_reasons']['LOW_STABILITY'] += 1
                            elif 'threshold' in reason.lower() or 'clv' in reason.lower():
                                stats['suppression_reasons']['LOW_CLV'] += 1
                            elif 'stale' in reason.lower():
                                stats['suppression_reasons']['STALE'] += 1
                    
                except Exception as e:
                    logger.error(f"Error processing fixture {fixture.get('match_id')}: {e}")
                    continue
            
            # Calculate total cycle time
            stats['timings']['total_ms'] = int((time.time() - cycle_start) * 1000)
            
            logger.info(f"📊 CLV Producer complete: {stats['alerts_created']} alerts created " +
                       f"from {stats['opportunities_found']} opportunities " +
                       f"({stats['fixtures_scanned']} fixtures) in {stats['timings']['total_ms']}ms")
            
            if stats['alerts_created'] == 0 and stats['opportunities_found'] > 0:
                suppression_log = ', '.join([f"{k}={v}" for k, v in stats['suppression_reasons'].items() if v > 0])
                logger.info(f"   Suppressions: {suppression_log}")
            
            # Log timings for observability
            logger.debug(f"   Stage timings: gather={stats['timings']['gather_odds_ms']}ms, " +
                        f"analyze={stats['timings']['analyze_ms']}ms")
            
            return stats
            
        except Exception as e:
            logger.error(f"CLV producer cycle failed: {e}")
            stats['error'] = str(e)
            return stats


def run_clv_alert_producer():
    """Standalone function to run producer (for scheduler integration)"""
    producer = CLVAlertProducer()
    return producer.run_producer_cycle()
