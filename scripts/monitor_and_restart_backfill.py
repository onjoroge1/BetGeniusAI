#!/usr/bin/env python3
"""
Backfill Monitoring and Auto-Restart Script

Monitors the match_context backfill process and automatically restarts it when:
1. The process completes (processes 5000 matches then exits)
2. The process stalls (no progress for 5+ minutes)
3. The process crashes

Runs continuously until all matches are backfilled.

Usage:
    python scripts/monitor_and_restart_backfill.py
    
    # With custom parameters:
    python scripts/monitor_and_restart_backfill.py --stall-timeout 300 --check-interval 60
"""

import os
import sys
import time
import subprocess
import psutil
import argparse
import logging
from datetime import datetime
import psycopg2

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class BackfillMonitor:
    """Monitor and auto-restart backfill process"""
    
    def __init__(self, stall_timeout: int = 300, check_interval: int = 60):
        """
        Args:
            stall_timeout: Seconds of no progress before considering stalled (default: 5 minutes)
            check_interval: Seconds between progress checks (default: 60 seconds)
        """
        self.database_url = os.getenv('DATABASE_URL')
        if not self.database_url:
            raise ValueError("DATABASE_URL not set")
        
        self.stall_timeout = stall_timeout
        self.check_interval = check_interval
        self.process = None
        self.last_count = 0
        self.last_progress_time = time.time()
        self.restart_count = 0
        
    def get_backfilled_count(self) -> int:
        """Get current count of backfilled matches"""
        try:
            conn = psycopg2.connect(self.database_url)
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM match_context")
                count = cur.fetchone()[0]
            conn.close()
            return count
        except Exception as e:
            logger.error(f"Error querying database: {e}")
            return self.last_count
    
    def get_remaining_count(self) -> int:
        """Get count of matches still needing backfill"""
        try:
            conn = psycopg2.connect(self.database_url)
            with conn.cursor() as cur:
                query = """
                    SELECT COUNT(*)
                    FROM training_matches tm
                    LEFT JOIN match_context mc ON tm.match_id = mc.match_id
                    WHERE mc.match_id IS NULL
                      AND tm.match_date >= '2020-01-01'
                      AND tm.match_date < NOW()
                      AND tm.outcome IS NOT NULL
                """
                cur.execute(query)
                count = cur.fetchone()[0]
            conn.close()
            return count
        except Exception as e:
            logger.error(f"Error querying database: {e}")
            return -1
    
    def is_process_running(self) -> bool:
        """Check if backfill process is still running"""
        if self.process is None:
            return False
        
        try:
            # Check if process exists and is running
            proc = psutil.Process(self.process.pid)
            return proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False
    
    def start_backfill(self):
        """Start the backfill process"""
        logger.info("🚀 Starting backfill process...")
        
        # Set environment for LibGOMP
        env = os.environ.copy()
        gcc_lib_path = subprocess.check_output(
            ["gcc", "-print-file-name=libgomp.so"], 
            text=True
        ).strip()
        lib_dir = os.path.dirname(gcc_lib_path)
        
        if 'LD_LIBRARY_PATH' in env:
            env['LD_LIBRARY_PATH'] = f"{lib_dir}:{env['LD_LIBRARY_PATH']}"
        else:
            env['LD_LIBRARY_PATH'] = lib_dir
        
        # Start backfill process
        self.process = subprocess.Popen(
            ["python", "scripts/backfill_match_context.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            text=True,
            bufsize=1
        )
        
        self.restart_count += 1
        logger.info(f"   Process started (PID: {self.process.pid}, Restart #{self.restart_count})")
        
        # Reset progress tracking
        self.last_count = self.get_backfilled_count()
        self.last_progress_time = time.time()
    
    def check_progress(self) -> tuple[bool, str]:
        """
        Check if backfill is making progress
        
        Returns:
            (is_healthy, status_message)
        """
        current_count = self.get_backfilled_count()
        time_since_progress = time.time() - self.last_progress_time
        
        # Check if count increased
        if current_count > self.last_count:
            progress = current_count - self.last_count
            self.last_count = current_count
            self.last_progress_time = time.time()
            return True, f"Progress: +{progress} matches (total: {current_count})"
        
        # Check if stalled
        if time_since_progress > self.stall_timeout:
            return False, f"STALLED: No progress for {time_since_progress:.0f}s"
        
        # Still healthy but no progress yet
        return True, f"Running... (no progress for {time_since_progress:.0f}s, {current_count} total)"
    
    def monitor_loop(self):
        """Main monitoring loop"""
        logger.info("="*70)
        logger.info("  BACKFILL MONITOR - Auto-Restart Enabled")
        logger.info("="*70)
        logger.info(f"Stall timeout:   {self.stall_timeout}s ({self.stall_timeout/60:.1f} minutes)")
        logger.info(f"Check interval:  {self.check_interval}s")
        logger.info("="*70)
        
        # Initial status
        remaining = self.get_remaining_count()
        current = self.get_backfilled_count()
        logger.info(f"\n📊 Initial Status:")
        logger.info(f"   Backfilled:  {current:,} matches")
        logger.info(f"   Remaining:   {remaining:,} matches")
        logger.info(f"   Total:       {current + remaining:,} matches\n")
        
        if remaining == 0:
            logger.info("✅ All matches already backfilled! Nothing to do.")
            return
        
        # Start first backfill
        self.start_backfill()
        
        # Monitor loop
        while True:
            time.sleep(self.check_interval)
            
            # Check remaining count
            remaining = self.get_remaining_count()
            
            if remaining == 0:
                logger.info("\n" + "="*70)
                logger.info("✅ BACKFILL COMPLETE - All matches processed!")
                logger.info("="*70)
                logger.info(f"Total restarts:  {self.restart_count}")
                logger.info(f"Final count:     {self.get_backfilled_count():,} matches")
                logger.info("="*70)
                
                # Kill any remaining process
                if self.is_process_running():
                    self.process.terminate()
                    self.process.wait(timeout=10)
                
                break
            
            # Check if process is still running
            process_running = self.is_process_running()
            
            if not process_running:
                logger.warning(f"⚠️  Process stopped (remaining: {remaining:,} matches)")
                logger.info("   Restarting in 5 seconds...")
                time.sleep(5)
                self.start_backfill()
                continue
            
            # Check progress
            is_healthy, status_msg = self.check_progress()
            logger.info(f"   {status_msg} (remaining: {remaining:,})")
            
            if not is_healthy:
                logger.warning(f"⚠️  {status_msg}")
                logger.info("   Killing stalled process and restarting...")
                
                # Kill stalled process
                try:
                    self.process.terminate()
                    self.process.wait(timeout=10)
                except:
                    self.process.kill()
                
                time.sleep(5)
                self.start_backfill()


def main():
    """Run backfill monitor"""
    parser = argparse.ArgumentParser(
        description='Monitor and auto-restart match_context backfill'
    )
    parser.add_argument(
        '--stall-timeout',
        type=int,
        default=300,
        help='Seconds of no progress before restart (default: 300 = 5 minutes)'
    )
    parser.add_argument(
        '--check-interval',
        type=int,
        default=60,
        help='Seconds between progress checks (default: 60)'
    )
    
    args = parser.parse_args()
    
    try:
        monitor = BackfillMonitor(
            stall_timeout=args.stall_timeout,
            check_interval=args.check_interval
        )
        monitor.monitor_loop()
        
    except KeyboardInterrupt:
        logger.info("\n\n⏸️  Monitor stopped by user")
        sys.exit(0)
        
    except Exception as e:
        logger.error(f"❌ Monitor error: {e}")
        logger.exception(e)
        sys.exit(1)


if __name__ == "__main__":
    main()
