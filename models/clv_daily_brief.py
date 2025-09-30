"""
CLV Daily Brief - Backend-only daily aggregation and reporting
Runs once per day at 00:05 UTC to summarize previous day's CLV Club performance
"""
import logging
from datetime import datetime, timedelta, time, timezone, date
from typing import Optional, Dict, Any, List
import psycopg2
from psycopg2.extras import RealDictCursor
from utils.config import settings

logger = logging.getLogger(__name__)

class CLVDailyBrief:
    """Daily aggregator for CLV Club metrics"""
    
    def __init__(self):
        self.enabled = getattr(settings, 'ENABLE_CLV_DAILY_BRIEF', True)
        self.retain_days = getattr(settings, 'CLV_DAILY_RETAIN_DAYS', 90)
    
    def get_connection(self):
        """Get database connection"""
        return psycopg2.connect(settings.DATABASE_URL)
    
    async def run_daily_brief(self) -> Dict[str, Any]:
        """
        Run daily aggregation for previous UTC day
        
        Returns summary of what was aggregated
        """
        if not self.enabled:
            logger.info("CLV Daily Brief disabled (ENABLE_CLV_DAILY_BRIEF=false)")
            return {"status": "disabled"}
        
        start_time = datetime.now(timezone.utc)
        
        # Calculate previous UTC day
        today = datetime.now(timezone.utc).date()
        stat_date = today - timedelta(days=1)
        d_start = datetime.combine(stat_date, time.min, tzinfo=timezone.utc)
        d_end = d_start + timedelta(days=1)
        
        logger.info(f"📊 CLV Daily Brief: Aggregating {stat_date} ({d_start} to {d_end})")
        
        try:
            conn = self.get_connection()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            
            # Run rollup SQL
            leagues_processed = self._run_rollup(cur, stat_date, d_start, d_end)
            
            # Run suppression mix if table exists
            suppression_updated = self._update_suppression_mix(cur, stat_date)
            
            # Retention cleanup
            deleted = self._cleanup_old_stats(cur)
            
            conn.commit()
            cur.close()
            conn.close()
            
            duration_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
            
            result = {
                "status": "success",
                "stat_date": str(stat_date),
                "leagues_processed": leagues_processed,
                "suppression_updated": suppression_updated,
                "old_rows_deleted": deleted,
                "duration_ms": duration_ms
            }
            
            logger.info(f"✅ CLV Daily Brief complete: {leagues_processed} leagues, {deleted} old rows deleted ({duration_ms}ms)")
            return result
            
        except Exception as e:
            logger.error(f"❌ CLV Daily Brief failed: {e}", exc_info=True)
            return {"status": "error", "error": str(e)}
    
    def _run_rollup(self, cur, stat_date: date, d_start: datetime, d_end: datetime) -> int:
        """Execute main rollup SQL and return number of leagues processed"""
        
        rollup_sql = """
        WITH day_alerts AS (
          SELECT *
          FROM clv_alerts
          WHERE created_at >= %(d_start)s AND created_at < %(d_end)s
        ),
        day_realized AS (
          SELECT r.*
          FROM clv_realized r
          JOIN clv_alerts a ON a.alert_id = r.alert_id
          WHERE r.settled_at >= %(d_start)s AND r.settled_at < %(d_end)s
        ),
        stats AS (
          SELECT
            %(stat_date)s::date AS stat_date,
            a.league,
            COUNT(*)::int AS alerts_emitted,
            AVG(a.books_used)::numeric(6,3) AS books_used_avg,
            AVG(a.stability)::numeric(6,3)  AS stability_avg,
            AVG(a.clv_pct)::numeric(6,3)    AS clv_pct_avg
          FROM day_alerts a
          GROUP BY a.league
        ),
        real AS (
          SELECT
            a.league,
            COUNT(*)::int AS realized_count,
            AVG(r.realized_clv_pct)::numeric(7,3) AS realized_clv_avg,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY r.realized_clv_pct)::numeric(7,3) AS realized_clv_p50
          FROM day_realized r
          JOIN clv_alerts a ON a.alert_id = r.alert_id
          GROUP BY a.league
        ),
        closing_share AS (
          SELECT
            a.league,
            JSONB_OBJECT_AGG(method, share) AS closing_method_share
          FROM (
            SELECT a.league,
                   r.closing_method AS method,
                   (COUNT(*) * 1.0 / SUM(COUNT(*)) OVER (PARTITION BY a.league))::numeric(6,3) AS share
            FROM day_realized r
            JOIN clv_alerts a ON a.alert_id = r.alert_id
            WHERE r.closing_method IS NOT NULL
            GROUP BY a.league, r.closing_method
          ) t
          GROUP BY t.league
        ),
        topN AS (
          SELECT a.league,
                 JSONB_AGG(
                   JSONB_BUILD_OBJECT(
                     'match_id', a.match_id,
                     'outcome',  a.outcome,
                     'clv_pct',  a.clv_pct,
                     'books_used', a.books_used,
                     'stability',  a.stability,
                     'window',     a.window_tag
                   )
                   ORDER BY a.clv_pct DESC
                 ) AS top_opportunities
          FROM (
            SELECT * FROM day_alerts ORDER BY clv_pct DESC LIMIT 10
          ) a
          GROUP BY a.league
        )
        INSERT INTO clv_daily_stats
        (stat_date, league, alerts_emitted, books_used_avg, stability_avg, clv_pct_avg,
         realized_count, realized_clv_avg, realized_clv_p50, closing_method_share, top_opportunities)
        SELECT
          %(stat_date)s::date,
          COALESCE(st.league, re.league) AS league,
          COALESCE(st.alerts_emitted, 0),
          st.books_used_avg,
          st.stability_avg,
          st.clv_pct_avg,
          COALESCE(re.realized_count, 0),
          re.realized_clv_avg,
          re.realized_clv_p50,
          cs.closing_method_share,
          tn.top_opportunities
        FROM stats st
        FULL JOIN real re ON re.league = st.league
        LEFT JOIN closing_share cs ON cs.league = COALESCE(st.league, re.league)
        LEFT JOIN topN tn         ON tn.league = COALESCE(st.league, re.league)
        ON CONFLICT (stat_date, league) DO UPDATE
        SET alerts_emitted     = EXCLUDED.alerts_emitted,
            books_used_avg     = EXCLUDED.books_used_avg,
            stability_avg      = EXCLUDED.stability_avg,
            clv_pct_avg        = EXCLUDED.clv_pct_avg,
            realized_count     = EXCLUDED.realized_count,
            realized_clv_avg   = EXCLUDED.realized_clv_avg,
            realized_clv_p50   = EXCLUDED.realized_clv_p50,
            closing_method_share = EXCLUDED.closing_method_share,
            top_opportunities  = EXCLUDED.top_opportunities,
            updated_at         = NOW()
        RETURNING league;
        """
        
        cur.execute(rollup_sql, {
            'stat_date': stat_date,
            'd_start': d_start,
            'd_end': d_end
        })
        
        leagues = cur.fetchall()
        return len(leagues)
    
    def _update_suppression_mix(self, cur, stat_date: date) -> bool:
        """Update suppression mix in daily stats if counter table exists"""
        
        # Check if suppression counters table exists
        cur.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'clv_suppression_counters'
            );
        """)
        
        if not cur.fetchone()['exists']:
            return False
        
        # Aggregate suppression counters into daily stats
        suppression_sql = """
        UPDATE clv_daily_stats s
        SET suppression_mix = sup.suppression_mix,
            updated_at = NOW()
        FROM (
          SELECT stat_date, league,
                 JSONB_OBJECT_AGG(reason, cnt) AS suppression_mix
          FROM (
            SELECT stat_date, league, reason, SUM(count)::int AS cnt
            FROM clv_suppression_counters
            WHERE stat_date = %(stat_date)s
            GROUP BY stat_date, league, reason
          ) x
          GROUP BY stat_date, league
        ) sup
        WHERE s.stat_date = sup.stat_date AND s.league = sup.league;
        """
        
        cur.execute(suppression_sql, {'stat_date': stat_date})
        return True
    
    def _cleanup_old_stats(self, cur) -> int:
        """Delete stats older than retention period"""
        
        cur.execute("""
            DELETE FROM clv_daily_stats 
            WHERE stat_date < CURRENT_DATE - INTERVAL '%s days'
            RETURNING stat_date;
        """, (self.retain_days,))
        
        deleted = cur.fetchall()
        return len(deleted)
    
    def get_daily_stats(self, stat_date: Optional[str] = None, league: Optional[str] = None):
        """
        Get daily stats for a specific date and/or league
        
        Args:
            stat_date: Date string (YYYY-MM-DD) or None for yesterday
            league: League name or None for all leagues
        
        Returns:
            Dict with stats for single league or List of dicts for all leagues
        """
        if not stat_date:
            # Default to yesterday
            yesterday = (datetime.now(timezone.utc).date() - timedelta(days=1))
            stat_date = yesterday.isoformat()
        
        try:
            conn = self.get_connection()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            
            if league:
                # Single league
                cur.execute("""
                    SELECT * FROM clv_daily_stats 
                    WHERE stat_date = %s AND league = %s
                """, (stat_date, league))
                row = cur.fetchone()
                result = dict(row) if row else {
                    "stat_date": stat_date,
                    "league": league,
                    "alerts_emitted": 0
                }
            else:
                # All leagues for that date, ordered by alerts
                cur.execute("""
                    SELECT * FROM clv_daily_stats 
                    WHERE stat_date = %s
                    ORDER BY alerts_emitted DESC NULLS LAST
                    LIMIT 20
                """, (stat_date,))
                rows = cur.fetchall()
                result = [dict(r) for r in rows] if rows else []
            
            cur.close()
            conn.close()
            
            return result
                
        except Exception as e:
            logger.error(f"Error fetching daily stats: {e}", exc_info=True)
            return None
    
    def increment_suppression(self, stat_date: date, league: str, reason: str):
        """
        Increment suppression counter (called from alert producer)
        
        Args:
            stat_date: UTC date
            league: League name
            reason: STALE | LOW_BOOKS | LOW_STABILITY | LOW_CLV | BAD_IDENTITY
        """
        try:
            conn = self.get_connection()
            cur = conn.cursor()
            
            cur.execute("""
                INSERT INTO clv_suppression_counters (stat_date, league, reason, count)
                VALUES (%s, %s, %s, 1)
                ON CONFLICT (stat_date, league, reason) 
                DO UPDATE SET count = clv_suppression_counters.count + 1
            """, (stat_date, league, reason))
            
            conn.commit()
            cur.close()
            conn.close()
            
        except Exception as e:
            logger.error(f"Error incrementing suppression counter: {e}")


# Global instance
daily_brief = CLVDailyBrief()
