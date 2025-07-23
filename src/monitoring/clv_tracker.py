"""
Closing Line Value (CLV) Tracking System - Phase 4 Implementation
Tracks opening vs closing odds to prove betting edge and model value
"""

import pandas as pd
import numpy as np
from sqlalchemy import create_engine, Column, String, Float, Integer, DateTime, Boolean, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

Base = declarative_base()

class BettingRecord(Base):
    """Database model for betting records with CLV tracking"""
    __tablename__ = 'betting_records'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    fixture_id = Column(String, nullable=False)
    league_id = Column(String, nullable=False)
    match_date = Column(DateTime, nullable=False)
    
    # Team information
    home_team = Column(String)
    away_team = Column(String)
    
    # Bet details
    bet_outcome = Column(String, nullable=False)  # 'home', 'draw', 'away'
    bet_placed_at = Column(DateTime, default=datetime.utcnow)
    stake = Column(Float, nullable=False)
    
    # Opening odds (when bet was considered)
    opening_odds = Column(Float, nullable=False)
    opening_home_odds = Column(Float)
    opening_draw_odds = Column(Float)
    opening_away_odds = Column(Float)
    
    # Closing odds (final odds before match)
    closing_odds = Column(Float)
    closing_home_odds = Column(Float)
    closing_draw_odds = Column(Float)
    closing_away_odds = Column(Float)
    
    # Model predictions
    model_probability = Column(Float, nullable=False)
    model_edge = Column(Float, nullable=False)
    expected_value = Column(Float, nullable=False)
    
    # Results
    actual_outcome = Column(String)  # 'home', 'draw', 'away'
    bet_won = Column(Boolean)
    payout = Column(Float, default=0.0)
    profit = Column(Float, default=0.0)
    
    # CLV metrics
    clv_absolute = Column(Float)  # Closing odds - Opening odds
    clv_percentage = Column(Float)  # (Closing - Opening) / Opening
    clv_yield = Column(Float)  # CLV as percentage of stake
    
    # Metadata
    bookmaker = Column(String, default='Bet365')
    model_version = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

class CLVTracker:
    """Tracks Closing Line Value to measure betting model quality"""
    
    def __init__(self):
        database_url = os.environ.get('DATABASE_URL')
        if not database_url:
            raise ValueError("DATABASE_URL environment variable not set")
        
        self.engine = create_engine(database_url)
        Base.metadata.create_all(self.engine)
        
        Session = sessionmaker(bind=self.engine)
        self.session = Session()
    
    def record_bet(self, fixture_id: str, league_id: str, match_date: datetime,
                   home_team: str, away_team: str, bet_outcome: str, stake: float,
                   opening_odds: Dict, model_probability: float, model_edge: float) -> int:
        """
        Record a new betting opportunity
        
        Args:
            fixture_id: Unique fixture identifier
            league_id: League identifier
            match_date: Match datetime
            home_team: Home team name
            away_team: Away team name
            bet_outcome: Outcome being bet on ('home', 'draw', 'away')
            stake: Bet stake amount
            opening_odds: Dict with opening odds for all outcomes
            model_probability: Model probability for bet outcome
            model_edge: Calculated edge
            
        Returns:
            Betting record ID
        """
        
        # Calculate expected value
        bet_odds = opening_odds.get(f'{bet_outcome}_odds', 0)
        expected_value = (model_probability * bet_odds) - 1
        
        record = BettingRecord(
            fixture_id=fixture_id,
            league_id=league_id,
            match_date=match_date,
            home_team=home_team,
            away_team=away_team,
            bet_outcome=bet_outcome,
            stake=stake,
            opening_odds=bet_odds,
            opening_home_odds=opening_odds.get('home_odds'),
            opening_draw_odds=opening_odds.get('draw_odds'),
            opening_away_odds=opening_odds.get('away_odds'),
            model_probability=model_probability,
            model_edge=model_edge,
            expected_value=expected_value,
            model_version='TwoStage_Enhanced_v2.0'
        )
        
        self.session.add(record)
        self.session.commit()
        
        print(f"📝 Recorded bet: {home_team} vs {away_team} - {bet_outcome.upper()} @ {bet_odds:.2f}")
        
        return record.id
    
    def update_closing_odds(self, record_id: int, closing_odds: Dict):
        """Update betting record with closing odds and calculate CLV"""
        
        record = self.session.query(BettingRecord).filter(
            BettingRecord.id == record_id
        ).first()
        
        if not record:
            raise ValueError(f"Betting record {record_id} not found")
        
        # Update closing odds
        record.closing_home_odds = closing_odds.get('home_odds')
        record.closing_draw_odds = closing_odds.get('draw_odds')
        record.closing_away_odds = closing_odds.get('away_odds')
        
        # Get closing odds for the specific bet
        closing_odds_for_bet = closing_odds.get(f'{record.bet_outcome}_odds', record.opening_odds)
        record.closing_odds = closing_odds_for_bet
        
        # Calculate CLV metrics
        if record.opening_odds > 0:
            record.clv_absolute = closing_odds_for_bet - record.opening_odds
            record.clv_percentage = (closing_odds_for_bet - record.opening_odds) / record.opening_odds
            record.clv_yield = record.clv_percentage  # CLV as percentage return
        
        record.updated_at = datetime.utcnow()
        self.session.commit()
        
        print(f"📈 CLV updated: {record.clv_percentage:.1%} ({record.opening_odds:.2f} → {closing_odds_for_bet:.2f})")
    
    def record_match_result(self, record_id: int, actual_outcome: str):
        """Record match result and calculate bet profit/loss"""
        
        record = self.session.query(BettingRecord).filter(
            BettingRecord.id == record_id
        ).first()
        
        if not record:
            raise ValueError(f"Betting record {record_id} not found")
        
        record.actual_outcome = actual_outcome
        record.bet_won = (record.bet_outcome == actual_outcome)
        
        # Calculate payout and profit
        if record.bet_won:
            record.payout = record.stake * record.opening_odds
            record.profit = record.payout - record.stake
        else:
            record.payout = 0.0
            record.profit = -record.stake
        
        record.updated_at = datetime.utcnow()
        self.session.commit()
        
        result_emoji = "✅" if record.bet_won else "❌"
        print(f"{result_emoji} Match result: {actual_outcome.upper()} - Profit: ${record.profit:.2f}")
    
    def calculate_clv_metrics(self, league_id: Optional[str] = None, days: int = 30) -> Dict:
        """Calculate comprehensive CLV metrics"""
        
        # Base query
        query = self.session.query(BettingRecord).filter(
            BettingRecord.clv_percentage.isnot(None),
            BettingRecord.bet_placed_at >= datetime.utcnow() - timedelta(days=days)
        )
        
        # Filter by league if specified
        if league_id:
            query = query.filter(BettingRecord.league_id == league_id)
        
        records = query.all()
        
        if not records:
            return {'status': 'no_data', 'message': 'No CLV data available'}
        
        # Calculate metrics
        clv_values = [r.clv_percentage for r in records if r.clv_percentage is not None]
        profits = [r.profit for r in records if r.profit is not None]
        
        metrics = {
            'total_bets': len(records),
            'avg_clv': np.mean(clv_values) if clv_values else 0,
            'median_clv': np.median(clv_values) if clv_values else 0,
            'positive_clv_rate': np.mean([clv > 0 for clv in clv_values]) if clv_values else 0,
            'clv_std': np.std(clv_values) if clv_values else 0,
            'total_clv_yield': sum(clv_values) if clv_values else 0,
            'avg_profit': np.mean(profits) if profits else 0,
            'total_profit': sum(profits) if profits else 0,
            'win_rate': np.mean([r.bet_won for r in records if r.bet_won is not None]),
            'period_days': days
        }
        
        # CLV correlation with profitability
        if len(clv_values) > 5 and len(profits) > 5:
            correlation = np.corrcoef(clv_values, profits)[0, 1]
            metrics['clv_profit_correlation'] = correlation
        
        return metrics
    
    def generate_clv_report(self, league_id: Optional[str] = None) -> Dict:
        """Generate comprehensive CLV report"""
        
        print(f"📊 Generating CLV report" + (f" for {league_id}" if league_id else ""))
        
        # Get metrics for different time periods
        weekly_metrics = self.calculate_clv_metrics(league_id, days=7)
        monthly_metrics = self.calculate_clv_metrics(league_id, days=30)
        
        # Get recent performance trend
        trend_query = self.session.query(BettingRecord).filter(
            BettingRecord.clv_percentage.isnot(None),
            BettingRecord.bet_placed_at >= datetime.utcnow() - timedelta(days=30)
        )
        
        if league_id:
            trend_query = trend_query.filter(BettingRecord.league_id == league_id)
        
        recent_records = trend_query.order_by(BettingRecord.bet_placed_at.desc()).limit(20).all()
        
        report = {
            'timestamp': datetime.now().isoformat(),
            'league_id': league_id,
            'weekly_metrics': weekly_metrics,
            'monthly_metrics': monthly_metrics,
            'recent_performance': []
        }
        
        # Add recent performance details
        for record in recent_records:
            performance = {
                'fixture_id': record.fixture_id,
                'match': f"{record.home_team} vs {record.away_team}",
                'bet_outcome': record.bet_outcome,
                'opening_odds': record.opening_odds,
                'closing_odds': record.closing_odds,
                'clv_percentage': record.clv_percentage,
                'profit': record.profit,
                'bet_won': record.bet_won,
                'match_date': record.match_date.isoformat() if record.match_date else None
            }
            report['recent_performance'].append(performance)
        
        return report
    
    def detect_clv_trends(self, league_id: Optional[str] = None) -> Dict:
        """Detect trends in CLV performance"""
        
        # Get last 50 bets
        query = self.session.query(BettingRecord).filter(
            BettingRecord.clv_percentage.isnot(None)
        )
        
        if league_id:
            query = query.filter(BettingRecord.league_id == league_id)
        
        records = query.order_by(BettingRecord.bet_placed_at.desc()).limit(50).all()
        
        if len(records) < 10:
            return {'status': 'insufficient_data'}
        
        # Split into recent and older periods
        recent_records = records[:25]
        older_records = records[25:]
        
        recent_clv = np.mean([r.clv_percentage for r in recent_records])
        older_clv = np.mean([r.clv_percentage for r in older_records])
        
        # Trend analysis
        clv_trend = recent_clv - older_clv
        
        trend_analysis = {
            'recent_avg_clv': recent_clv,
            'previous_avg_clv': older_clv,
            'clv_trend': clv_trend,
            'trend_direction': 'improving' if clv_trend > 0.01 else 'declining' if clv_trend < -0.01 else 'stable',
            'sample_size': len(records)
        }
        
        # Add alerts
        alerts = []
        if recent_clv < -0.02:  # Negative CLV indicates poor timing
            alerts.append('Negative CLV suggests poor bet timing or odds shopping')
        
        if clv_trend < -0.03:  # Significant decline
            alerts.append('CLV declining - model may be losing edge')
        
        if recent_clv > 0.05:  # Very positive CLV
            alerts.append('Strong positive CLV indicates excellent bet selection')
        
        trend_analysis['alerts'] = alerts
        
        return trend_analysis
    
    def get_league_clv_ranking(self) -> List[Dict]:
        """Get CLV performance ranking by league"""
        
        # Get all leagues with CLV data
        leagues = self.session.query(BettingRecord.league_id).distinct().all()
        league_rankings = []
        
        for (league_id,) in leagues:
            metrics = self.calculate_clv_metrics(league_id, days=30)
            
            if metrics.get('total_bets', 0) > 5:  # Minimum bet threshold
                league_rankings.append({
                    'league_id': league_id,
                    'avg_clv': metrics['avg_clv'],
                    'positive_clv_rate': metrics['positive_clv_rate'],
                    'total_bets': metrics['total_bets'],
                    'win_rate': metrics['win_rate'],
                    'total_profit': metrics['total_profit']
                })
        
        # Sort by average CLV (descending)
        league_rankings.sort(key=lambda x: x['avg_clv'], reverse=True)
        
        return league_rankings

def main():
    """Test CLV tracking system"""
    print("🚀 Phase 4: CLV Tracking System")
    print("=" * 40)
    
    try:
        # Initialize CLV tracker
        clv_tracker = CLVTracker()
        
        # Simulate some betting records for testing
        print("📝 Simulating betting records...")
        
        # Record sample bets
        from datetime import datetime, timedelta
        
        sample_bets = [
            {
                'fixture_id': 'EPL_001',
                'league_id': 'EPL',
                'match_date': datetime.now() + timedelta(days=1),
                'home_team': 'Manchester United',
                'away_team': 'Liverpool',
                'bet_outcome': 'home',
                'stake': 20.0,
                'opening_odds': {'home_odds': 2.50, 'draw_odds': 3.20, 'away_odds': 2.80},
                'model_probability': 0.45,
                'model_edge': 0.035
            },
            {
                'fixture_id': 'LALIGA_001', 
                'league_id': 'LALIGA',
                'match_date': datetime.now() + timedelta(days=2),
                'home_team': 'Barcelona',
                'away_team': 'Real Madrid',
                'bet_outcome': 'draw',
                'stake': 15.0,
                'opening_odds': {'home_odds': 2.20, 'draw_odds': 3.40, 'away_odds': 3.10},
                'model_probability': 0.32,
                'model_edge': 0.041
            }
        ]
        
        bet_ids = []
        for bet in sample_bets:
            bet_id = clv_tracker.record_bet(**bet)
            bet_ids.append(bet_id)
        
        # Simulate closing odds updates
        print("📈 Updating with closing odds...")
        
        closing_odds_updates = [
            {'home_odds': 2.65, 'draw_odds': 3.10, 'away_odds': 2.70},  # Home odds improved
            {'home_odds': 2.15, 'draw_odds': 3.50, 'away_odds': 3.20}   # Draw odds improved
        ]
        
        for i, bet_id in enumerate(bet_ids):
            clv_tracker.update_closing_odds(bet_id, closing_odds_updates[i])
        
        # Simulate match results
        print("⚽ Recording match results...")
        match_results = ['home', 'draw']  # First bet wins, second bet wins
        
        for i, bet_id in enumerate(bet_ids):
            clv_tracker.record_match_result(bet_id, match_results[i])
        
        # Generate CLV metrics
        print("\n📊 CLV Performance Analysis:")
        
        overall_metrics = clv_tracker.calculate_clv_metrics()
        print(f"  Overall CLV: {overall_metrics.get('avg_clv', 0):.1%}")
        print(f"  Positive CLV Rate: {overall_metrics.get('positive_clv_rate', 0):.1%}")
        print(f"  Total Bets: {overall_metrics.get('total_bets', 0)}")
        print(f"  Win Rate: {overall_metrics.get('win_rate', 0):.1%}")
        print(f"  Total Profit: ${overall_metrics.get('total_profit', 0):.2f}")
        
        # CLV trend analysis
        trend_analysis = clv_tracker.detect_clv_trends()
        if trend_analysis.get('status') != 'insufficient_data':
            print(f"\n📈 CLV Trend Analysis:")
            print(f"  Trend Direction: {trend_analysis['trend_direction']}")
            print(f"  Recent CLV: {trend_analysis['recent_avg_clv']:.1%}")
            
            if trend_analysis['alerts']:
                print(f"  🚨 Alerts:")
                for alert in trend_analysis['alerts']:
                    print(f"    • {alert}")
        
        # League ranking
        league_rankings = clv_tracker.get_league_clv_ranking()
        if league_rankings:
            print(f"\n🏆 League CLV Rankings:")
            for i, league in enumerate(league_rankings, 1):
                print(f"  {i}. {league['league_id']}: {league['avg_clv']:.1%} CLV ({league['total_bets']} bets)")
        
        # Generate comprehensive CLV report
        clv_report = clv_tracker.generate_clv_report()
        
        print(f"\n✅ CLV tracking system operational!")
        print(f"📈 Tracking {overall_metrics.get('total_bets', 0)} betting decisions")
        print(f"🎯 Positive CLV demonstrates model edge over market")
        
    except Exception as e:
        print(f"❌ CLV tracking error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()