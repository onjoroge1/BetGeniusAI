"""
Odds Velocity Calculator
Calculates how fast odds are moving to detect sharp money and market sentiment
"""

import psycopg2
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


class OddsVelocityCalculator:
    """Calculate odds movement velocity and trends"""
    
    def __init__(self, db_url: str):
        self.db_url = db_url
    
    def get_odds_velocity(
        self,
        match_id: int,
        book_id: str = 'pinnacle',
        lookback_minutes: int = 15
    ) -> Dict:
        """
        Calculate odds velocity over last N minutes
        Returns movement speed, direction, and recent snapshots
        """
        try:
            with psycopg2.connect(self.db_url) as conn:
                cursor = conn.cursor()
                
                # Get recent odds snapshots for this match
                cursor.execute("""
                    SELECT 
                        ts_snapshot,
                        outcome,
                        odds_decimal
                    FROM odds_snapshots
                    WHERE match_id = %s
                        AND book_id = %s
                        AND market = 'h2h'
                        AND ts_snapshot > NOW() - INTERVAL '%s minutes'
                    ORDER BY ts_snapshot DESC, outcome
                """, (match_id, book_id, lookback_minutes))
                
                rows = cursor.fetchall()
                
                if not rows:
                    return self._empty_velocity_response()
                
                # Group by outcome
                odds_by_outcome = {'H': [], 'D': [], 'A': []}
                for ts, outcome, odds in rows:
                    if outcome in odds_by_outcome:
                        odds_by_outcome[outcome].append((ts, float(odds)))
                
                # Calculate velocity for each outcome
                velocities = {}
                trends = {}
                
                for outcome, snapshots in odds_by_outcome.items():
                    if len(snapshots) >= 2:
                        # Sort by time (oldest first)
                        snapshots = sorted(snapshots, key=lambda x: x[0])
                        
                        oldest_odds = snapshots[0][1]
                        latest_odds = snapshots[-1][1]
                        
                        # Calculate total change
                        total_change = latest_odds - oldest_odds
                        
                        # Calculate velocity (change per minute)
                        time_diff = (snapshots[-1][0] - snapshots[0][0]).total_seconds() / 60
                        velocity = total_change / time_diff if time_diff > 0 else 0
                        
                        # Percentage change
                        pct_change = ((latest_odds - oldest_odds) / oldest_odds) * 100 if oldest_odds > 0 else 0
                        
                        velocities[outcome] = {
                            'velocity_per_min': round(velocity, 4),
                            'total_change': round(total_change, 3),
                            'pct_change': round(pct_change, 2),
                            'direction': 'tightening' if velocity < 0 else 'drifting',
                            'latest_odds': latest_odds,
                            'oldest_odds': oldest_odds
                        }
                        
                        trends[outcome] = snapshots[-5:] if len(snapshots) >= 5 else snapshots
                
                # Determine overall market sentiment
                market_sentiment = self._calculate_market_sentiment(velocities)
                
                return {
                    'bookmaker': book_id,
                    'lookback_minutes': lookback_minutes,
                    'velocities': {
                        'home': velocities.get('H', {}),
                        'draw': velocities.get('D', {}),
                        'away': velocities.get('A', {})
                    },
                    'market_sentiment': market_sentiment,
                    'recent_snapshots': {
                        'home': [(ts.isoformat(), odds) for ts, odds in trends.get('H', [])],
                        'draw': [(ts.isoformat(), odds) for ts, odds in trends.get('D', [])],
                        'away': [(ts.isoformat(), odds) for ts, odds in trends.get('A', [])]
                    },
                    'has_significant_movement': self._has_significant_movement(velocities)
                }
                
        except Exception as e:
            logger.error(f"Error calculating odds velocity: {e}")
            return self._empty_velocity_response()
    
    def _calculate_market_sentiment(self, velocities: Dict) -> str:
        """Determine overall market sentiment from velocity data"""
        if not velocities:
            return 'stable'
        
        # Check for significant movements
        significant_moves = []
        for outcome, data in velocities.items():
            if abs(data.get('pct_change', 0)) > 3:  # >3% change
                significant_moves.append({
                    'outcome': outcome,
                    'direction': data.get('direction'),
                    'pct_change': data.get('pct_change')
                })
        
        if not significant_moves:
            return 'stable'
        
        # Determine primary direction
        if len(significant_moves) == 1:
            move = significant_moves[0]
            outcome_name = {'H': 'home', 'D': 'draw', 'A': 'away'}.get(move['outcome'], 'unknown')
            return f"{outcome_name}_{move['direction']}"
        
        return 'mixed_movement'
    
    def _has_significant_movement(self, velocities: Dict) -> bool:
        """Check if odds have moved significantly (trigger for AI analysis)"""
        for outcome, data in velocities.items():
            pct_change = abs(data.get('pct_change', 0))
            if pct_change > 5:  # >5% change triggers AI analysis
                return True
        return False
    
    def _empty_velocity_response(self) -> Dict:
        """Return empty response when no data available"""
        return {
            'bookmaker': None,
            'lookback_minutes': 0,
            'velocities': {
                'home': {},
                'draw': {},
                'away': {}
            },
            'market_sentiment': 'no_data',
            'recent_snapshots': {
                'home': [],
                'draw': [],
                'away': []
            },
            'has_significant_movement': False
        }
    
    def get_all_live_velocities(self) -> List[Dict]:
        """Get odds velocities for all live matches"""
        try:
            with psycopg2.connect(self.db_url) as conn:
                cursor = conn.cursor()
                
                # Get live matches
                cursor.execute("""
                    SELECT DISTINCT match_id
                    FROM fixtures
                    WHERE kickoff_at <= NOW()
                        AND kickoff_at > NOW() - INTERVAL '2 hours'
                        AND status = 'scheduled'
                """)
                
                match_ids = [row[0] for row in cursor.fetchall()]
                
                results = []
                for match_id in match_ids:
                    velocity_data = self.get_odds_velocity(match_id)
                    velocity_data['match_id'] = match_id
                    results.append(velocity_data)
                
                return results
                
        except Exception as e:
            logger.error(f"Error getting live velocities: {e}")
            return []
