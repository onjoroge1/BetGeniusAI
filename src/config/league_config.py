"""
League Configuration System - Phase 4 Implementation
Config-driven thresholds and league-specific parameters
"""

import pandas as pd
import numpy as np
from sqlalchemy import create_engine, Column, String, Float, Integer, DateTime, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
from datetime import datetime
from typing import Dict, List, Optional

Base = declarative_base()

class LeagueConfig(Base):
    """Database model for league-specific configuration"""
    __tablename__ = 'league_configs'
    
    league_id = Column(String, primary_key=True)
    league_name = Column(String, nullable=False)
    tier = Column(Integer, default=1)  # 1=Top5, 2=Championship, 3=Others
    region = Column(String, default='Europe')
    
    # Betting thresholds
    edge_threshold = Column(Float, default=0.03)  # 3% minimum edge
    min_probability = Column(Float, default=0.15)  # 15% minimum probability
    min_expected_value = Column(Float, default=0.05)  # 5% minimum EV
    
    # Performance targets
    target_roi = Column(Float, default=0.08)  # 8% target ROI
    target_accuracy = Column(Float, default=0.55)  # 55% target accuracy
    min_bet_volume = Column(Integer, default=10)  # Minimum weekly bets
    
    # Risk management
    max_stake_per_bet = Column(Float, default=20.0)  # Maximum stake per bet
    max_daily_exposure = Column(Float, default=100.0)  # Maximum daily exposure
    kelly_fraction = Column(Float, default=0.25)  # Kelly fraction multiplier
    
    # Status flags
    is_active = Column(Boolean, default=True)
    is_monitored = Column(Boolean, default=True)
    last_updated = Column(DateTime, default=datetime.utcnow)
    created_date = Column(DateTime, default=datetime.utcnow)

class LeaguePerformance(Base):
    """Historical performance tracking per league"""
    __tablename__ = 'league_performance'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    league_id = Column(String, nullable=False)
    report_date = Column(DateTime, default=datetime.utcnow)
    
    # Accuracy metrics
    accuracy_3way = Column(Float)
    accuracy_top2 = Column(Float)
    macro_f1 = Column(Float)
    log_loss = Column(Float)
    brier_score = Column(Float)
    
    # Betting metrics
    roi = Column(Float)
    hit_rate = Column(Float)
    num_bets = Column(Integer)
    total_stakes = Column(Float)
    total_profit = Column(Float)
    avg_edge = Column(Float)
    clv = Column(Float)
    
    # Sample size
    matches_evaluated = Column(Integer)

class ConfigManager:
    """Manages league configurations and thresholds"""
    
    def __init__(self):
        database_url = os.environ.get('DATABASE_URL')
        if not database_url:
            raise ValueError("DATABASE_URL environment variable not set")
        
        self.engine = create_engine(database_url)
        Base.metadata.create_all(self.engine)
        
        Session = sessionmaker(bind=self.engine)
        self.session = Session()
        
        # Initialize default configurations if empty
        self._initialize_default_configs()
    
    def _initialize_default_configs(self):
        """Initialize default league configurations"""
        
        # Check if configs already exist
        if self.session.query(LeagueConfig).count() > 0:
            return
        
        print("Initializing default league configurations...")
        
        # European Tier 1 Leagues (Top 5)
        tier1_leagues = [
            ('EPL', 'English Premier League', 'England'),
            ('LALIGA', 'La Liga Santander', 'Spain'),
            ('SERIEA', 'Serie A', 'Italy'),
            ('BUNDESLIGA', 'Bundesliga', 'Germany'),
            ('LIGUE1', 'Ligue 1', 'France')
        ]
        
        # European Tier 2 Leagues
        tier2_leagues = [
            ('CHAMPIONSHIP', 'EFL Championship', 'England'),
            ('LIGUE2', 'Ligue 2', 'France'),
            ('SERIEB', 'Serie B', 'Italy'),
            ('BUNDESLIGA2', '2. Bundesliga', 'Germany'),
            ('LALIGA2', 'La Liga SmartBank', 'Spain')
        ]
        
        # Other European Leagues
        tier3_leagues = [
            ('EREDIVISIE', 'Eredivisie', 'Netherlands'),
            ('PRIMEIRA', 'Primeira Liga', 'Portugal'),
            ('SUPERLIG', 'Süper Lig', 'Turkey'),
            ('BELGIANPRO', 'Belgian Pro League', 'Belgium'),
            ('SCOTTISHPREM', 'Scottish Premiership', 'Scotland')
        ]
        
        # Add Tier 1 configurations
        for league_id, name, region in tier1_leagues:
            config = LeagueConfig(
                league_id=league_id,
                league_name=name,
                tier=1,
                region=region,
                edge_threshold=0.03,  # 3% edge for premium leagues
                min_probability=0.20,  # Higher confidence required
                target_roi=0.10,  # 10% target ROI
                target_accuracy=0.60,  # Higher accuracy target
                max_stake_per_bet=25.0
            )
            self.session.add(config)
        
        # Add Tier 2 configurations  
        for league_id, name, region in tier2_leagues:
            config = LeagueConfig(
                league_id=league_id,
                league_name=name,
                tier=2,
                region=region,
                edge_threshold=0.025,  # Slightly lower edge threshold
                min_probability=0.18,
                target_roi=0.12,  # Higher ROI target for tier 2
                target_accuracy=0.58,
                max_stake_per_bet=20.0
            )
            self.session.add(config)
        
        # Add Tier 3 configurations
        for league_id, name, region in tier3_leagues:
            config = LeagueConfig(
                league_id=league_id,
                league_name=name,
                tier=3,
                region=region,
                edge_threshold=0.04,  # Higher edge for less familiar leagues
                min_probability=0.25,  # Higher confidence required
                target_roi=0.08,
                target_accuracy=0.55,
                max_stake_per_bet=15.0
            )
            self.session.add(config)
        
        self.session.commit()
        print(f"Initialized {len(tier1_leagues + tier2_leagues + tier3_leagues)} league configurations")
    
    def get_league_config(self, league_id: str) -> Optional[LeagueConfig]:
        """Get configuration for specific league"""
        return self.session.query(LeagueConfig).filter(
            LeagueConfig.league_id == league_id
        ).first()
    
    def get_all_active_leagues(self) -> List[LeagueConfig]:
        """Get all active league configurations"""
        return self.session.query(LeagueConfig).filter(
            LeagueConfig.is_active == True
        ).all()
    
    def update_league_thresholds(self, league_id: str, **kwargs):
        """Update thresholds for specific league"""
        config = self.get_league_config(league_id)
        if not config:
            raise ValueError(f"League {league_id} not found")
        
        for key, value in kwargs.items():
            if hasattr(config, key):
                setattr(config, key, value)
        
        config.last_updated = datetime.utcnow()
        self.session.commit()
        
        print(f"Updated {league_id} thresholds: {kwargs}")
    
    def record_performance(self, league_id: str, performance_data: Dict):
        """Record performance metrics for league"""
        performance = LeaguePerformance(
            league_id=league_id,
            **performance_data
        )
        
        self.session.add(performance)
        self.session.commit()
        
        print(f"Recorded performance for {league_id}: {performance_data.get('roi', 0):.1%} ROI")
    
    def get_league_performance_history(self, league_id: str, days: int = 30) -> List[LeaguePerformance]:
        """Get recent performance history for league"""
        cutoff_date = datetime.utcnow() - pd.Timedelta(days=days)
        
        return self.session.query(LeaguePerformance).filter(
            LeaguePerformance.league_id == league_id,
            LeaguePerformance.report_date >= cutoff_date
        ).order_by(LeaguePerformance.report_date.desc()).all()
    
    def generate_league_health_report(self) -> Dict:
        """Generate comprehensive health report for all leagues"""
        print("Generating league health report...")
        
        health_report = {
            'timestamp': datetime.now().isoformat(),
            'leagues': {},
            'summary': {}
        }
        
        active_leagues = self.get_all_active_leagues()
        
        total_leagues = len(active_leagues)
        healthy_leagues = 0
        warning_leagues = 0
        critical_leagues = 0
        
        for config in active_leagues:
            # Get recent performance
            recent_performance = self.get_league_performance_history(config.league_id, days=7)
            
            if recent_performance:
                latest = recent_performance[0]
                
                # Health status assessment
                health_status = 'Healthy'
                issues = []
                
                # Check ROI performance
                if latest.roi < config.target_roi * 0.5:  # Less than 50% of target
                    health_status = 'Critical'
                    issues.append(f"ROI {latest.roi:.1%} below target {config.target_roi:.1%}")
                elif latest.roi < config.target_roi * 0.8:  # Less than 80% of target
                    health_status = 'Warning'
                    issues.append(f"ROI {latest.roi:.1%} below target {config.target_roi:.1%}")
                
                # Check accuracy
                if latest.accuracy_3way < config.target_accuracy * 0.9:
                    if health_status == 'Healthy':
                        health_status = 'Warning'
                    issues.append(f"Accuracy {latest.accuracy_3way:.1%} below target {config.target_accuracy:.1%}")
                
                # Check bet volume
                if latest.num_bets < config.min_bet_volume:
                    if health_status == 'Healthy':
                        health_status = 'Warning'
                    issues.append(f"Low volume: {latest.num_bets} bets (target: {config.min_bet_volume})")
                
                league_report = {
                    'config': {
                        'name': config.league_name,
                        'tier': config.tier,
                        'edge_threshold': config.edge_threshold,
                        'target_roi': config.target_roi
                    },
                    'performance': {
                        'accuracy_3way': latest.accuracy_3way,
                        'accuracy_top2': latest.accuracy_top2,
                        'log_loss': latest.log_loss,
                        'roi': latest.roi,
                        'num_bets': latest.num_bets,
                        'clv': latest.clv
                    },
                    'health_status': health_status,
                    'issues': issues,
                    'last_updated': latest.report_date.isoformat()
                }
                
                # Count health statuses
                if health_status == 'Healthy':
                    healthy_leagues += 1
                elif health_status == 'Warning':
                    warning_leagues += 1
                else:
                    critical_leagues += 1
                    
            else:
                # No recent data
                league_report = {
                    'config': {
                        'name': config.league_name,
                        'tier': config.tier,
                        'edge_threshold': config.edge_threshold,
                        'target_roi': config.target_roi
                    },
                    'performance': None,
                    'health_status': 'No Data',
                    'issues': ['No recent performance data'],
                    'last_updated': None
                }
                warning_leagues += 1
            
            health_report['leagues'][config.league_id] = league_report
        
        # Summary statistics
        health_report['summary'] = {
            'total_leagues': total_leagues,
            'healthy': healthy_leagues,
            'warning': warning_leagues,
            'critical': critical_leagues,
            'health_percentage': healthy_leagues / total_leagues if total_leagues > 0 else 0
        }
        
        return health_report
    
    def optimize_thresholds_for_league(self, league_id: str, performance_history: List) -> Dict:
        """Optimize betting thresholds based on performance history"""
        
        if len(performance_history) < 5:
            return {'status': 'insufficient_data', 'message': 'Need at least 5 data points'}
        
        # Convert to DataFrame for analysis
        df = pd.DataFrame([{
            'roi': p.roi,
            'num_bets': p.num_bets,
            'hit_rate': p.hit_rate,
            'avg_edge': p.avg_edge
        } for p in performance_history])
        
        current_config = self.get_league_config(league_id)
        
        # Simple optimization logic
        avg_roi = df['roi'].mean()
        avg_volume = df['num_bets'].mean()
        
        recommendations = {
            'current_edge_threshold': current_config.edge_threshold,
            'current_roi': avg_roi,
            'current_volume': avg_volume
        }
        
        # If ROI is good but volume is low, lower edge threshold
        if avg_roi > current_config.target_roi and avg_volume < current_config.min_bet_volume:
            new_edge = max(0.02, current_config.edge_threshold - 0.005)
            recommendations['recommended_edge'] = new_edge
            recommendations['reason'] = 'Good ROI, increase volume by lowering edge threshold'
        
        # If ROI is poor, increase edge threshold
        elif avg_roi < current_config.target_roi * 0.8:
            new_edge = min(0.08, current_config.edge_threshold + 0.01)
            recommendations['recommended_edge'] = new_edge
            recommendations['reason'] = 'Poor ROI, increase selectivity by raising edge threshold'
        
        else:
            recommendations['recommended_edge'] = current_config.edge_threshold
            recommendations['reason'] = 'Current thresholds performing well'
        
        return recommendations

def main():
    """Initialize and test league configuration system"""
    print("🚀 Phase 4: League Configuration System")
    print("=" * 45)
    
    try:
        # Initialize configuration manager
        config_manager = ConfigManager()
        
        # Generate health report
        health_report = config_manager.generate_league_health_report()
        
        print(f"\n📊 League Health Summary:")
        summary = health_report['summary']
        print(f"  Total Leagues: {summary['total_leagues']}")
        print(f"  Healthy: {summary['healthy']} ({summary['healthy']/summary['total_leagues']:.1%})")
        print(f"  Warning: {summary['warning']}")
        print(f"  Critical: {summary['critical']}")
        
        print(f"\n🏆 League Status Overview:")
        for league_id, report in health_report['leagues'].items():
            config = report['config']
            status = report['health_status']
            
            status_emoji = {
                'Healthy': '✅',
                'Warning': '⚠️',  
                'Critical': '❌',
                'No Data': '📊'
            }.get(status, '❓')
            
            print(f"  {status_emoji} {config['name']} (Tier {config['tier']}) - {status}")
            if report['issues']:
                for issue in report['issues']:
                    print(f"    • {issue}")
        
        # Test threshold updates
        print(f"\n🔧 Testing threshold updates...")
        
        # Update EPL thresholds as example
        config_manager.update_league_thresholds(
            'EPL',
            edge_threshold=0.035,
            min_probability=0.22,
            target_roi=0.12
        )
        
        # Get updated config
        epl_config = config_manager.get_league_config('EPL')
        print(f"  EPL updated - Edge: {epl_config.edge_threshold:.1%}, Target ROI: {epl_config.target_roi:.1%}")
        
        print(f"\n✅ League configuration system operational!")
        print(f"📈 Ready for per-league threshold optimization and monitoring")
        
    except Exception as e:
        print(f"❌ Configuration system error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()