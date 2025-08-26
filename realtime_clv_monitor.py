#!/usr/bin/env python3

import asyncio
import os
import sys
import psycopg2
from datetime import datetime, timedelta
import json
import time

sys.path.append('.')

class RealtimeCLVMonitor:
    """Real-time CLV monitoring and alert system"""
    
    def __init__(self):
        self.database_url = os.environ.get('DATABASE_URL')
        self.clv_threshold = 3.0  # Alert when CLV > +3%
        self.movement_threshold = 5.0  # Alert when movement > 5%
        self.running = False
        
        # High-value bookmakers identified from analysis
        self.premium_bookmakers = [148, 894, 710, 6, 748]
        
    async def start_monitoring(self):
        """Start real-time CLV monitoring"""
        print("🚨 REAL-TIME CLV MONITOR STARTED")
        print("=" * 40)
        print(f"CLV Alert Threshold: +{self.clv_threshold}%")
        print(f"Movement Alert Threshold: {self.movement_threshold}%")
        print(f"Premium Bookmakers: {self.premium_bookmakers}")
        
        self.running = True
        
        while self.running:
            try:
                await self.check_clv_opportunities()
                await self.check_line_movements()
                await self.update_bookmaker_rankings()
                
                # Check every 5 minutes for real-time monitoring
                await asyncio.sleep(300)
                
            except Exception as e:
                print(f"❌ Monitoring error: {e}")
                await asyncio.sleep(60)  # Wait 1 minute before retry
    
    async def check_clv_opportunities(self):
        """Check for current CLV opportunities"""
        try:
            with psycopg2.connect(self.database_url) as conn:
                cursor = conn.cursor()
                
                # Get recent odds for CLV analysis
                cursor.execute("""
                    SELECT 
                        os.match_id,
                        os.book_id,
                        os.outcome,
                        os.odds_decimal,
                        os.implied_prob,
                        os.secs_to_kickoff,
                        os.created_at
                    FROM odds_snapshots os
                    WHERE os.created_at > NOW() - INTERVAL '1 hour'
                      AND os.secs_to_kickoff > 3600  -- At least 1 hour to kickoff
                    ORDER BY os.created_at DESC
                """)
                
                recent_odds = cursor.fetchall()
                
                if recent_odds:
                    clv_opportunities = []
                    
                    # Group by match and outcome to find CLV opportunities
                    odds_by_match_outcome = {}
                    for odds in recent_odds:
                        match_id, book_id, outcome, odds_decimal, implied_prob, secs_to_kickoff, created_at = odds
                        key = (match_id, outcome)
                        
                        if key not in odds_by_match_outcome:
                            odds_by_match_outcome[key] = []
                        
                        odds_by_match_outcome[key].append({
                            'book_id': book_id,
                            'odds': odds_decimal,
                            'secs_to_kickoff': secs_to_kickoff,
                            'created_at': created_at
                        })
                    
                    # Calculate CLV opportunities
                    for (match_id, outcome), odds_list in odds_by_match_outcome.items():
                        if len(odds_list) >= 2:
                            # Find best and worst odds for CLV calculation
                            best_odds = max(odds_list, key=lambda x: x['odds'])
                            worst_odds = min(odds_list, key=lambda x: x['odds'])
                            
                            if best_odds['odds'] > 0 and worst_odds['odds'] > 0:
                                clv_pct = (best_odds['odds'] - worst_odds['odds']) / worst_odds['odds'] * 100
                                
                                if clv_pct >= self.clv_threshold:
                                    clv_opportunities.append({
                                        'match_id': match_id,
                                        'outcome': outcome,
                                        'best_odds': best_odds['odds'],
                                        'best_book': best_odds['book_id'],
                                        'worst_odds': worst_odds['odds'],
                                        'clv_percentage': clv_pct,
                                        'time_to_kickoff': best_odds['secs_to_kickoff']
                                    })
                    
                    # Alert on CLV opportunities
                    if clv_opportunities:
                        print(f"\n🎯 CLV OPPORTUNITIES DETECTED ({len(clv_opportunities)})")
                        for opp in clv_opportunities:
                            hours_to_kickoff = opp['time_to_kickoff'] / 3600
                            print(f"   ⚡ Match {opp['match_id']} {opp['outcome']}: {opp['clv_percentage']:+.1f}% CLV")
                            print(f"      Best: {opp['best_odds']:.3f} (Book {opp['best_book']}) vs Worst: {opp['worst_odds']:.3f}")
                            print(f"      Time to kickoff: {hours_to_kickoff:.1f}h")
                
        except Exception as e:
            print(f"❌ CLV check error: {e}")
    
    async def check_line_movements(self):
        """Check for significant line movements"""
        try:
            with psycopg2.connect(self.database_url) as conn:
                cursor = conn.cursor()
                
                # Get odds movements in last 6 hours
                cursor.execute("""
                    WITH odds_movements AS (
                        SELECT 
                            match_id,
                            outcome,
                            book_id,
                            odds_decimal,
                            created_at,
                            LAG(odds_decimal) OVER (
                                PARTITION BY match_id, outcome, book_id 
                                ORDER BY created_at
                            ) as prev_odds,
                            LAG(created_at) OVER (
                                PARTITION BY match_id, outcome, book_id 
                                ORDER BY created_at
                            ) as prev_time
                        FROM odds_snapshots
                        WHERE created_at > NOW() - INTERVAL '6 hours'
                    )
                    SELECT 
                        match_id,
                        outcome,
                        book_id,
                        prev_odds,
                        odds_decimal,
                        CASE 
                            WHEN prev_odds > 0 
                            THEN (odds_decimal - prev_odds) / prev_odds * 100
                            ELSE 0 
                        END as movement_pct,
                        created_at
                    FROM odds_movements
                    WHERE prev_odds IS NOT NULL
                      AND prev_odds > 0
                      AND ABS((odds_decimal - prev_odds) / prev_odds * 100) >= %s
                    ORDER BY ABS((odds_decimal - prev_odds) / prev_odds * 100) DESC
                    LIMIT 10
                """, (self.movement_threshold,))
                
                movements = cursor.fetchall()
                
                if movements:
                    print(f"\n📈 SIGNIFICANT LINE MOVEMENTS ({len(movements)})")
                    for movement in movements:
                        match_id, outcome, book_id, prev_odds, current_odds, movement_pct, created_at = movement
                        direction = "📈" if movement_pct > 0 else "📉"
                        
                        print(f"   {direction} Match {match_id} {outcome}: {prev_odds:.3f} → {current_odds:.3f} ({movement_pct:+.1f}%)")
                        print(f"      Bookmaker {book_id} at {created_at}")
                
        except Exception as e:
            print(f"❌ Movement check error: {e}")
    
    async def update_bookmaker_rankings(self):
        """Update bookmaker efficiency rankings"""
        try:
            with psycopg2.connect(self.database_url) as conn:
                cursor = conn.cursor()
                
                # Get bookmaker performance in last 24 hours
                cursor.execute("""
                    SELECT 
                        book_id,
                        COUNT(*) as odds_count,
                        AVG(odds_decimal) as avg_odds,
                        STDDEV(odds_decimal) as odds_variance,
                        COUNT(DISTINCT match_id) as matches_covered
                    FROM odds_snapshots
                    WHERE created_at > NOW() - INTERVAL '24 hours'
                    GROUP BY book_id
                    HAVING COUNT(*) >= 5  -- Minimum activity threshold
                    ORDER BY AVG(odds_decimal) DESC
                    LIMIT 10
                """)
                
                rankings = cursor.fetchall()
                
                if rankings:
                    print(f"\n🏆 TOP BOOKMAKER RANKINGS (24h)")
                    for i, (book_id, count, avg_odds, variance, matches) in enumerate(rankings, 1):
                        premium_marker = "⭐" if book_id in self.premium_bookmakers else "  "
                        variance_str = f"{variance:.3f}" if variance else "N/A"
                        
                        print(f"   {i:2}. {premium_marker} Bookmaker {book_id}: {avg_odds:.3f} avg odds")
                        print(f"       {count} odds, {matches} matches, variance: {variance_str}")
                
        except Exception as e:
            print(f"❌ Rankings update error: {e}")
    
    async def generate_clv_report(self):
        """Generate comprehensive CLV performance report"""
        try:
            with psycopg2.connect(self.database_url) as conn:
                cursor = conn.cursor()
                
                # Daily CLV summary
                cursor.execute("""
                    SELECT 
                        DATE(created_at) as date,
                        COUNT(*) as total_odds,
                        COUNT(DISTINCT match_id) as matches,
                        COUNT(DISTINCT book_id) as bookmakers,
                        AVG(odds_decimal) as avg_odds,
                        MIN(odds_decimal) as min_odds,
                        MAX(odds_decimal) as max_odds
                    FROM odds_snapshots
                    WHERE created_at > NOW() - INTERVAL '7 days'
                    GROUP BY DATE(created_at)
                    ORDER BY date DESC
                """)
                
                daily_summary = cursor.fetchall()
                
                print(f"\n📊 WEEKLY CLV PERFORMANCE SUMMARY")
                print("-" * 50)
                
                for date, total_odds, matches, bookmakers, avg_odds, min_odds, max_odds in daily_summary:
                    print(f"{date}: {total_odds} odds, {matches} matches, {bookmakers} bookmakers")
                    print(f"   Odds range: {min_odds:.3f} - {max_odds:.3f} (avg: {avg_odds:.3f})")
                
                # Save report
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                report_file = f"clv_monitoring_report_{timestamp}.json"
                
                report_data = {
                    'timestamp': timestamp,
                    'daily_summary': [
                        {
                            'date': str(date),
                            'total_odds': total_odds,
                            'matches': matches,
                            'bookmakers': bookmakers,
                            'avg_odds': float(avg_odds),
                            'min_odds': float(min_odds),
                            'max_odds': float(max_odds)
                        }
                        for date, total_odds, matches, bookmakers, avg_odds, min_odds, max_odds in daily_summary
                    ],
                    'monitoring_config': {
                        'clv_threshold': self.clv_threshold,
                        'movement_threshold': self.movement_threshold,
                        'premium_bookmakers': self.premium_bookmakers
                    }
                }
                
                with open(report_file, 'w') as f:
                    json.dump(report_data, f, indent=2, default=str)
                
                print(f"\n💾 CLV report saved to: {report_file}")
                
        except Exception as e:
            print(f"❌ Report generation error: {e}")
    
    def stop_monitoring(self):
        """Stop the monitoring system"""
        self.running = False
        print("\n🛑 CLV monitoring stopped")

async def main():
    """Main CLV monitoring function"""
    monitor = RealtimeCLVMonitor()
    
    try:
        # Generate initial report
        await monitor.generate_clv_report()
        
        print(f"\n🚀 Starting real-time CLV monitoring...")
        print("Press Ctrl+C to stop monitoring")
        
        # Start monitoring (this will run indefinitely)
        await monitor.start_monitoring()
        
    except KeyboardInterrupt:
        monitor.stop_monitoring()
        print("\n✅ CLV monitoring session completed")
    except Exception as e:
        print(f"❌ Fatal error in CLV monitoring: {e}")

if __name__ == "__main__":
    asyncio.run(main())